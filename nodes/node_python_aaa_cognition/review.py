# -*- coding: utf-8 -*-
"""
认知反思模块（Background Review）— 承接 [PLAN]-AAA记忆系统改造方案 §3.2

职责：
- 从最近对话中提炼持久认知（每 5 轮触发一次）
- 提取维度：自我属性（self→self_info+self_cognition）、用户事实/偏好（declarative→user_facts）、
  操作模式（procedural→self_cognition）
- 写入门槛：self 类条目需 confidence ≥ 0.7（防命令/噪声污染长期认知）

LLM 调用方式（两种，二选一）：
1. 注入钩子（测试/单进程直连）：set_llm_call(fn)，run_review 内同步调用
2. 节点间通道（真实运行）：llm_call 默认写 output_review_prompt.json，
   由 LLM 节点处理后回执到 AAA 的 _on_review_response（复用 diary 端口模式）

并发安全：本模块只做 sqlite 写入（独立连接），严禁调用 memos / 语义模型，
防止与 MemOS 并发触发 native 崩溃（0xC0000005）。
"""
import re
import time
import json
import sqlite3
from datetime import datetime

# ── LLM 调用钩子 ────────────────────────────────────────────────────
_llm_call_hook = None


def set_llm_call(fn):
    """注入同步 LLM 调用函数（用于测试/直连环境）。fn: (prompt: str) -> str"""
    global _llm_call_hook
    _llm_call_hook = fn


def llm_call(prompt: str, identity_key: str = "gui:default", user_id: str = "") -> str:
    """获取 review 的 LLM 输出。

    有注入钩子 → 同步返回文本；
    无钩子（真实节点） → 写 output_review_prompt.json 走节点间通道，返回 ""，
    回执由 AAA handle() 的 review 分支处理（_on_review_response）。

    Args:
        user_id: v6.1 多用户 — 写入 review prompt 文件，供 LLM 节点回执时带回归属
    """
    if _llm_call_hook is not None:
        return _llm_call_hook(prompt)
    _write_review_prompt_file(prompt, identity_key, user_id)
    return ""


def _write_review_prompt_file(prompt: str, identity_key: str, user_id: str = ""):
    """写 output_review_prompt.json — 由 LLM 节点通过 review 端口消费（复用 diary 模式）"""
    try:
        from config import resolve
        path = resolve("./output_review_prompt.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "data_type": "prompt",
                "content": prompt,
                "source": "review",
                "request_id": f"review_{int(time.time() * 1000)}",
                "identity_key": identity_key,
                "user_id": user_id,
            }, f, ensure_ascii=False)
    except Exception:
        pass


# ── prompt 构建 ─────────────────────────────────────────────────────
_REVIEW_HEADER = (
    "你是一个记忆管理员。审查以下最近对话，提取值得持久化的内容，只输出 JSON 数组，"
    "不要输出任何其它文字。\n\n"
    "条目类型：\n"
    '1. {"type": "self", "key": "属性名", "value": "属性值", "confidence": 0-1}'
    " — AI 自身的稳定属性（名称、性格、偏好、说话风格），只提取对话中明确出现的\n"
    '2. {"type": "declarative", "content": "关于用户的事实/偏好", "confidence": 0-1}'
    " — 用户的重要信息（姓名、喜好、习惯、关系）\n"
    '3. {"type": "procedural", "content": "重复行为模式描述", "confidence": 0-1}'
    " — 被反复执行的行为序列\n\n"
    "要求：只提取对话中有依据的信息；同一信息只输出一次；未出现则输出空数组 []。\n\n"
)


def build_review_prompt(conversation: list) -> str:
    """构建 review prompt。conversation: [{"role": "user|assistant", "content": str, "user_id": str}, ...]

    消息带 user_id 时标注具体说话对象（避免多人场景用笼统"用户"导致 declarative 归属歧义）。
    """
    lines = []
    for m in (conversation or [])[-10:]:
        role = "用户" if m.get("role") == "user" else "AI"
        uid = str(m.get("user_id") or "").strip()
        label = f"（说话对象: {uid}）" if uid and m.get("role") == "user" else ""
        content = (m.get("content") or "").strip().replace("\n", " ")
        lines.append(f"[{role}]{label}: {content[:200]}")
    if not lines:
        lines = ["（无对话记录）"]
    return _REVIEW_HEADER + "最近对话：\n" + "\n".join(lines) + "\n"


# ── 结果解析 ────────────────────────────────────────────────────────
_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def parse_review_result(text: str) -> list:
    """解析 LLM 输出的 JSON 数组，容错返回 insight 列表。

    兼容：裸 JSON / ```json 围栏 / 前后有多余文字。
    """
    if not text or not text.strip():
        return []
    candidates = []
    blocks = _JSON_BLOCK.findall(text)
    if blocks:
        candidates.extend(blocks)
    # 裸 JSON 数组（从第一个 [ 到最后一个 ]）
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, list):
                return [ins for ins in data if isinstance(ins, dict)]
        except (json.JSONDecodeError, ValueError):
            continue
    return []


# ── 持久化 ──────────────────────────────────────────────────────────
_SELF_INFO_MIN_CONFIDENCE = 0.7

# v2.1 命令/强设定句式（命中则拒绝沉淀为自我属性，防命令污染固化）
_COMMAND_PATTERNS = [
    r"从现在开始", r"我命令你", r"以后你(都|就要|只能)", r"记住你是",
    r"你的名字(就叫|改为|是)|你叫", r"你就是", r"以后都叫", r"设定为",
]


def _is_command_text(text: str) -> bool:
    """命中命令/强设定句式 → True（该内容不得固化为自我属性）"""
    if not text:
        return False
    return any(re.search(p, text) for p in _COMMAND_PATTERNS)


def persist_insight(insight: dict, db_path: str, identity_key: str = "gui:default", user_id: str = ""):
    """将一条 review 洞察写入对应表（独立连接，线程安全，不去重冲突）。

    Args:
        user_id: v6.1 多用户 — declarative 用户事实归属到具体说话对象（缺省归全局）
    """
    itype = str(insight.get("type", "declarative"))
    content = str(insight.get("content") or "").strip()
    try:
        confidence = float(insight.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    if not content and itype != "self":
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(db_path)
    try:
        if itype == "self":
            # 自我属性 → self_info（写入门槛防污染）+ 沉淀一条 self_cognition
            if confidence < _SELF_INFO_MIN_CONFIDENCE:
                return
            key = str(insight.get("key") or "").strip()
            value = str(insight.get("value") or "").strip()
            if not key and "=" in content:
                key, value = [p.strip() for p in content.split("=", 1)]
            if not key or not value:
                return
            # v2.1 命令过滤：命中命令/强设定句式 → 拒绝沉淀（命令不能固化为自我属性）
            if _is_command_text(content) or _is_command_text(value):
                return
            # v2.1 频次门槛：同一 key=value 至少出现 2 轮才允许沉淀。
            # 通过 self_info 中历史同 key=value 记录数判断（命令变体链"讽刺→冷酷→负面毒舌冷酷"因 value 不一致无法互相放行）
            hist = conn.execute(
                "SELECT COUNT(*) FROM self_info WHERE identity_key=? AND key=? AND value=?",
                (identity_key, key, value)).fetchone()[0]
            if hist < 1:
                return
            dup = conn.execute(
                "SELECT COUNT(*) FROM self_info WHERE identity_key=? AND key=? AND value=?",
                (identity_key, key, value)).fetchone()[0]
            if dup:
                return
            conn.execute(
                "INSERT INTO self_info(conversation_id,identity_key,key,value,created_at) "
                "VALUES('default',?,?,?,?)", (identity_key, key, value, now))
            conn.execute(
                "INSERT INTO self_cognition(conversation_id,identity_key,content,created_at) "
                "VALUES('default',?,?,?)", (identity_key, f"[沉淀] {key}={value}", now))
        elif itype == "declarative":
            # 用户事实/偏好 → user_facts（去重，v6.1 多用户：带 user_id 归属说话对象）
            dup = conn.execute(
                "SELECT COUNT(*) FROM user_facts WHERE identity_key=? AND content=? AND user_id=?",
                (identity_key, content, user_id)).fetchone()[0]
            if not dup:
                conn.execute(
                    "INSERT INTO user_facts(conversation_id,identity_key,category,content,user_id,created_at) "
                    "VALUES('default',?,?,?,?,?)",
                    (identity_key, "background", content, user_id, now))
        elif itype == "procedural":
            # 操作模式 → self_cognition（保留来源标记）
            conn.execute(
                "INSERT INTO self_cognition(conversation_id,identity_key,content,created_at) "
                "VALUES('default',?,?,?)", (identity_key, f"[程序性记忆] {content}", now))
        conn.commit()
    finally:
        conn.close()


def run_review(conversation: list, db_path: str, identity_key: str = "gui:default", user_id: str = "") -> int:
    """同步执行一次 review（构建 → LLM 调用 → 解析 → 持久化）。

    Args:
        user_id: v6.1 多用户 — declarative 沉淀归属的说话对象
        conversation: [{"role": "user|assistant", "content": str, "user_id": str}]

    Returns:
        写入的洞察条数（无钩子走节点间通道时返回 -1，等待回执处理）
    """
    if not conversation:
        return 0
    prompt = build_review_prompt(conversation)
    text = llm_call(prompt, identity_key, user_id)
    if not text:
        return -1  # 已走节点间通道，回执由 _on_review_response 处理
    insights = parse_review_result(text)
    n = 0
    for ins in insights:
        try:
            persist_insight(ins, db_path, identity_key, user_id)
            n += 1
        except Exception:
            continue
    return n
