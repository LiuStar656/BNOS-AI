# -*- coding: utf-8 -*-
"""AAA 提示词组装功能测试：验证 _on_text → _gather_context → pt.build 全链路组装。

分析维度：
1. 组装是否抛异常（字段缺失 → KeyError / format 错误）
2. 未填充占位符残留（{xxx} 残留 = 字段未注入）
3. 13 个节标记定义是否齐全
4. 各上下文字段是否按预期注入（用户文本/认知/历史/位置/性格/情绪/感知等）
5. 身份隔离（不同 identity_key 数据不串）
6. 特殊字符输入是否破坏组装（{}、【】、引号、emoji）

用法（在项目根目录执行，使用 AAA 节点 venv）：
    python tests/prompt_assembly_test.py

产物（输出到 docs/experiments/prompt_assembly_test/）：
    提示词组装测试-原始输出.json   各场景完整 prompt + 检查结果
    提示词组装测试报告.md         组装分析报告
"""
import os
import re
import sys
import json
import time
import sqlite3

NODE_DIR = r"E:\杂项\BNOS_AI_project\nodes\node_python_aaa_cognition"
os.chdir(NODE_DIR)
sys.path.insert(0, NODE_DIR)

# 重定向 config.resolve：防止测试期间任何 ./ 输出写入真实节点目录
import config as _cfg_mod
_orig_resolve = _cfg_mod.resolve


def _fake_resolve(p):
    if p.startswith("./"):
        return os.path.join(r"E:\杂项\BNOS_AI_project\_tmp_assembly_io", p[2:])
    return _orig_resolve(p)


_cfg_mod.resolve = _fake_resolve

import db
import main as aaa_main   # 触发 memos.preload() 加载语义模型
import prompt as pt
import prompt_retrieval as ptr

ROOT = r"E:\杂项\BNOS_AI_project"
OUT_DIR = os.path.join(ROOT, "docs", "experiments", "prompt_assembly_test")
TMP_IO = os.path.join(ROOT, "_tmp_assembly_io")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(TMP_IO, exist_ok=True)

REQUIRED_SECTIONS = ["自然回复", "心情", "想法", "情绪调整", "事件摘要",
                     "自我认知", "他人认知", "用户信息", "自我信息",
                     "用户记忆", "环境记忆", "实体名", "归档标签"]
PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")
ID_DEFAULT = "gui:default"


_scene_seq = [0]


def fresh_db():
    """为每个场景创建独立临时 DB（避免后台线程占用同一文件）"""
    _scene_seq[0] += 1
    db_path = os.path.join(ROOT, f"_tmp_assembly_{_scene_seq[0]}.db")
    if os.path.isfile(db_path):
        os.remove(db_path)
    db.ensure(db_path)
    return db_path


def seed(db_path, identity=ID_DEFAULT, conv="default", flavor="A"):
    """种入有代表性的历史数据，模拟真实运行后的库。

    flavor: 个性化内容标记（A/B），用于验证身份隔离
    """
    conn = sqlite3.connect(db_path)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    c = conn
    c.execute("INSERT INTO self_cognition(conversation_id,identity_key,content,created_at) VALUES(?,?,?,?)",
              (conv, identity, f"我喜欢在深夜保持安静（身份{flavor}专属记忆）", now))
    c.execute("INSERT INTO other_cognition(conversation_id,identity_key,content,created_at) VALUES(?,?,?,?)",
              (conv, identity, f"用户是{flavor}用户，近期在备考，情绪略焦虑", now))
    c.execute("INSERT INTO event_summary(conversation_id,identity_key,summary,created_at) VALUES(?,?,?,?)",
              (conv, identity, f"{flavor}用户聊到工作压力和周末爬山计划", now))
    c.execute("INSERT INTO event_summary(conversation_id,identity_key,summary,created_at) VALUES(?,?,?,?)",
              (conv, identity, f"{flavor}用户决定开始健身", now))
    c.execute("INSERT INTO user_facts(conversation_id,identity_key,category,content,created_at) VALUES(?,?,?,?,?)",
              (conv, identity, "background", f"姓名={flavor}用户", now))
    c.execute("INSERT INTO user_facts(conversation_id,identity_key,category,content,created_at) VALUES(?,?,?,?,?)",
              (conv, identity, "background", f"职业={flavor}职业", now))
    c.execute("INSERT INTO self_info(conversation_id,identity_key,key,value,created_at) VALUES(?,?,?,?,?)",
              (conv, identity, "last_diary_date", time.strftime("%Y-%m-%d"), now))
    c.execute("INSERT OR IGNORE INTO fixed_cognition(key,value) VALUES(?,?)", ("性格", "温柔而坚定的陪伴者"))
    c.execute("INSERT INTO feelings(conversation_id,identity_key,mood,thought,created_at) VALUES(?,?,?,?,?)",
              (conv, identity, "平静", f"{flavor}用户今天情绪不错", now))
    c.execute("INSERT INTO mood_trend(conversation_id,identity_key,period,period_start,avg_mood_value,dominant_mood,sample_count) VALUES(?,?,?,?,?,?,?)",
              (conv, identity, "week", "2026-08-03", 3.8, "平静", 12))
    c.execute("INSERT INTO personality_seed(identity_key,warmth,playfulness,directness,curiosity,style_description,preset_name) VALUES(?,?,?,?,?,?,?)",
              (identity, 0.7, 0.5, 0.4, 0.8, f"{flavor}风格描述", "默认"))
    c.execute("INSERT INTO mood_value(identity_key,mood_value,adjustment,source_mood,conversation_id,created_at) VALUES(?,?,?,?,?,?)",
              (identity, 0.3, 0.1, "平静", conv, now))
    c.execute("INSERT INTO location_history(identity_key,latitude,longitude,accuracy,city,region,country,source,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (identity, 26.5833, 106.7167, 500, "贵阳市", "贵州省", "中国", "ip", "active", now))
    c.execute("INSERT INTO long_term_memory(conversation_id,identity_key,source,role,content,importance,decay_date,created_at) VALUES(?,?,?,?,?,?,?,?)",
              (conv, identity, "exchange", "combined", f"user: {flavor}用户准备考试\nassistant: 加油", 3, None, now))
    conn.commit()
    conn.close()


def build_prompt(db_path, user_text, identity=ID_DEFAULT, attachments=None,
                 request_id="asm", conv="default"):
    """调用 AAA _on_text 组装提示词，返回 prompt 文本"""
    result = aaa_main._node._on_text(
        {"content": user_text, "request_id": request_id,
         "identity_key": identity, "attachments": attachments or []},
        db_path)
    return result.get("content", "")


def analyze(prompt_text, checks: dict, required=None) -> list:
    """检查组装结果，返回问题列表（空 = 无问题）"""
    issues = []
    # 1. 占位符残留
    ph = PLACEHOLDER_RE.findall(prompt_text)
    if ph:
        issues.append(f"未填充占位符残留: {sorted(set(ph))}")
    # 2. 节标记定义齐全（默认 13 节；第二轮模板传 required 覆盖）
    required = required or REQUIRED_SECTIONS
    missing = [s for s in required if f"【{s}】" not in prompt_text]
    if missing:
        issues.append(f"缺少节标记定义: {missing}")
    # 3. 关键结构段
    for key, needle in checks.items():
        if needle and needle not in prompt_text:
            issues.append(f"缺少预期内容「{key}」: {needle[:30]}...")
    return issues


def main():
    results = []
    t_start = time.time()

    # ── 场景 1：空库首次对话 ─────────────────────────────
    dbp = fresh_db()
    try:
        p = build_prompt(dbp, "你好")
    except Exception as e:
        p, err = "", str(e)
    else:
        err = None
    issues = (["组装异常: " + err] if err else
              analyze(p, {"用户文本": "用户文本：你好"}))
    results.append({"scene": "空库首次对话", "identity": ID_DEFAULT,
                    "prompt": p, "prompt_len": len(p), "issues": issues})

    # ── 场景 2：有丰富历史数据 ───────────────────────────
    dbp = fresh_db()
    seed(dbp)
    try:
        p = build_prompt(dbp, "今天状态怎么样？")
    except Exception as e:
        p, err = "", str(e)
    else:
        err = None
    issues = (["组装异常: " + err] if err else analyze(p, {
        "用户文本": "用户文本：今天状态怎么样？",
        "自我认知": "身份A专属记忆",
        "他人认知": "A用户，近期在备考",
        "历史摘要": "A用户聊到工作压力",
        "用户信息": "姓名=A用户",
        "自我信息": "last_diary_date=",
        "固定认知": "温柔而坚定的陪伴者",
        "性格段": "### 你的性格",
        "情绪段": "### 你的当前情绪",
        "感知段": "### 你的感知能力",
        "位置段": "位置",
        "日期时间": time.strftime("%Y-%m-%d"),
    }))
    results.append({"scene": "有丰富历史数据", "identity": ID_DEFAULT,
                    "prompt": p, "prompt_len": len(p), "issues": issues})

    # ── 场景 3：带附件 ───────────────────────────────────
    dbp = fresh_db()
    seed(dbp)
    atts = [{"type": "image", "name": "截图.png", "path": r"C:\tmp\截图.png"}]
    try:
        p = build_prompt(dbp, "看看这张图", attachments=atts)
    except Exception as e:
        p, err = "", str(e)
    else:
        err = None
    issues = (["组装异常: " + err] if err else analyze(p, {
        "附件段": "用户附带了以下附件",
        "附件名": "截图.png",
    }))
    results.append({"scene": "带附件输入", "identity": ID_DEFAULT,
                    "prompt": p, "prompt_len": len(p), "issues": issues})

    # ── 场景 4：特殊字符输入 ─────────────────────────────
    dbp = fresh_db()
    seed(dbp)
    weird = "用户说：{变量} 和 【尖括号】以及 \"引号\" 还有 👍 emoji \n第二行"
    try:
        p = build_prompt(dbp, weird)
    except Exception as e:
        p, err = "", str(e)
    else:
        err = None
    issues = (["组装异常: " + err] if err else analyze(p, {"用户文本原文": weird.strip()}))
    results.append({"scene": "特殊字符输入", "identity": ID_DEFAULT,
                    "prompt": p, "prompt_len": len(p), "issues": issues})

    # ── 场景 5：身份隔离 ─────────────────────────────────
    dbp = fresh_db()
    seed(dbp, identity="userA", flavor="A")
    seed(dbp, identity="userB", flavor="B")
    try:
        pA = build_prompt(dbp, "你好A", identity="userA", request_id="a")
        pB = build_prompt(dbp, "你好B", identity="userB", request_id="b")
    except Exception as e:
        pA, pB, err = "", "", str(e)
    else:
        err = None
    if err:
        issues = ["组装异常: " + err]
    else:
        issues = analyze(pA, {
            "身份A认知": "身份A专属记忆",
            "A用户信息": "姓名=A用户",
            "A风格": "A风格描述",
            "用户文本": "用户文本：你好A",
        })
        # 严格隔离：A 的 prompt 不得出现 B 的任何专属数据
        for leak in ("身份B专属记忆", "姓名=B用户", "B风格描述", "B用户聊到", "用户文本：你好B"):
            if leak in pA:
                issues.append(f"身份隔离失效：A 的 prompt 泄漏了 B 的数据「{leak}」")
        if "userB" in pA:
            issues.append("身份隔离失效：A 的 prompt 出现 userB 标识")
    results.append({"scene": "身份隔离(userA/userB)", "identity": "userA",
                    "prompt": pA, "prompt_len": len(pA), "issues": issues})

    # ── 场景 6：第二轮检索模板 build_second ──────────────
    dbp = fresh_db()
    seed(dbp)
    try:
        ctx = aaa_main._node._gather_context(
            "我们上次聊的电影叫什么？", dbp, conv_id="default",
            retrieval_override="[0.82] 用户喜欢《星际穿越》\n[0.75] 用户提到想再看一遍",
            identity_key=ID_DEFAULT)
        p = ptr.build_second(ctx)
    except Exception as e:
        p, err = "", str(e)
    else:
        err = None
    issues = (["组装异常: " + err] if err else analyze(p, {
        "检索结果": "用户喜欢《星际穿越》",
        "输出节": "【记忆归档】",
    }, required=["自然回复", "心情", "想法", "事件摘要", "自我认知",
                 "他人认知", "用户信息", "自我信息", "记忆归档", "归档标签"]))
    results.append({"scene": "第二轮检索模板", "identity": ID_DEFAULT,
                    "prompt": p, "prompt_len": len(p), "issues": issues})

    # ── 分析汇总 ─────────────────────────────────────────
    total = len(results)
    clean = sum(1 for r in results if not r["issues"])
    print(f"[测试] {total} 个组装场景完成，耗时 {time.time()-t_start:.0f}s")
    for r in results:
        status = "PASS" if not r["issues"] else "FAIL"
        print(f"  [{status}] {r['scene']}  prompt={r['prompt_len']}  {'; '.join(r['issues']) if r['issues'] else '无问题'}")
    print(f"[汇总] 通过 {clean}/{total}")

    # 保存原始输出
    with open(os.path.join(OUT_DIR, "提示词组装测试-原始输出.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    write_report(results, clean, total, time.strftime("%Y-%m-%d %H:%M:%S"))
    # 清理临时产物
    for f in os.listdir(ROOT):
        if f.startswith("_tmp_assembly_") and f.endswith(".db"):
            try:
                os.remove(os.path.join(ROOT, f))
            except PermissionError:
                pass


def write_report(results, clean, total, now):
    lines = [
        "# AAA 提示词组装功能测试报告",
        "",
        f"> 日期：{now}",
        "> 测试链路：`MyNode._on_text` → `_gather_context`（DB 上下文收集）→ `pt.build`（模板填充）",
        "",
        "## 一、测试概况",
        "",
        f"- 组装场景数：**{total}** 个（空库 / 有历史 / 附件 / 特殊字符 / 身份隔离 / 第二轮检索）",
        f"- 通过：{clean}，存在问题：{total - clean}",
        "",
        "## 二、逐场景结果",
        "",
        "| 场景 | Prompt长度 | 结果 | 问题 |",
        "|------|:---------:|:----:|------|",
    ]
    for r in results:
        status = "✅" if not r["issues"] else "❌"
        issues_txt = "; ".join(r["issues"]) if r["issues"] else "无"
        lines.append(f"| {r['scene']} | {r['prompt_len']} | {status} | {issues_txt} |")

    lines += [
        "",
        "## 三、检查项说明",
        "",
        "每个场景检查：",
        "- 组装是否抛异常（字段缺失/format 错误）",
        "- 是否残留未填充占位符 `{xxx}`",
        "- 13 个节标记定义（【自然回复】…【归档标签】）是否齐全",
        "- 关键上下文字段是否按预期注入（用户文本、自我/他人认知、历史摘要、用户信息、自我信息、固定认知、位置、性格、情绪、感知）",
        "",
        "## 四、结论",
        "",
    ]
    if clean == total:
        lines.append(f"{total} 个场景全部通过：AAA 提示词组装链路未发现错误组装。")
    else:
        lines.append(f"{total - clean} 个场景存在问题，详见上表与 `提示词组装测试-原始输出.json` 中的完整 prompt。")
    lines.append("")
    with open(os.path.join(OUT_DIR, "提示词组装测试报告.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[报告] 已生成: {os.path.join(OUT_DIR, '提示词组装测试报告.md')}")


if __name__ == "__main__":
    main()
