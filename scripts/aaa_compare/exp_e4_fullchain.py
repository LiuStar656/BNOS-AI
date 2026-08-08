"""
E4 沉淀-召回-使用全链路实验（1对1 单条路径，真 LLM）

回答：认知系统沉淀的认知有多少真的被用了？
三阶段转化率：
  沉淀：对话后 long_term_memory / event_summary / self_cognition / self_info /
        other_cognition / user_facts 新增条数（相对对话前基线）
  召回：Prefetch 每轮检索命中的轮次比例（memory_present）+ 命中实体词
  使用：有命中且回复文本引用命中实体的轮次比例

设计（规避三项上生产阻断项——改用 1对1 单条路径 _on_text，不走批量）：
  阶段 A（前 27 轮）：15 条新事实陈述 + 12 条闲聊 → 触发沉淀
  阶段 B（后 33 轮）：15 个新事实提问 + 3 个种子记忆提问 + 15 条闲聊 → 触发召回+使用

用法（项目根目录，AAA 节点 venv）：
  python scripts/aaa_compare/exp_e4_fullchain.py [--rounds 60] [--out <dir>]
"""
import os
import sys
import time
import json
import sqlite3
import argparse
import urllib.request

# ── 防 OpenBLAS 崩溃：必须在 import numpy/memos 之前设置 ──
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")

PROJECT_ROOT = r"e:\杂项\BNOS_AI_project"
NODE_DIR = os.path.join(PROJECT_ROOT, "nodes", "node_python_aaa_cognition")

# ── 真实 LLM 直连（DeepSeek，与 measure.py / self_evolution_test 同源）──
API_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = "sk-REVOKED"
MODEL = "deepseek-v4-flash"
TEMPERATURE = 0.7
MAX_TOKENS = 2048


def llm_infer(prompt: str) -> str:
    for attempt in range(3):
        try:
            body = {"model": MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS}
            req = urllib.request.Request(
                API_URL, data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {API_KEY}"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"] or ""
            if content.strip():
                return content
            print(f"WARN: LLM 空响应，重试 {attempt+1}/3", flush=True)
        except Exception as e:
            print(f"WARN: LLM 异常 {e!r}，重试 {attempt+1}/3", flush=True)
            time.sleep(2)
    return ""


# ── config 覆盖：关闭后台 review（聚焦主链路沉淀，控制成本）──
sys.path.insert(0, NODE_DIR)
import config as _cfg_mod
_cfg_mod._config = {"review_interval": 0, "db_path": "../shared/chatbot.db"}

os.chdir(NODE_DIR)
import db
import main as node_main
import memos
import parser as node_psr

# ── 保留 memos.rebuild_index（E4 需要"阶段A沉淀→阶段B召回"的索引更新）──
# 仅禁无关后台线程：知识图谱导出 + 情感趋势聚合（防并发 native 崩溃）
memos.rebuild_knowledge_index = lambda *a, **k: None
db._aggregate_mood = lambda *a, **k: None

# ── 种子记忆（同 aaa_cmp，保证召回有基准对象）──
SEED_MEMORIES = [
    ("用户喜欢电影《星际穿越》，这是他最喜欢的电影，看过很多遍", "电影"),
    ("用户养了一只猫，名字叫二饼，是一只橘猫，很粘人", "宠物"),
    ("用户正在备考专升本，目标专业是计算机科学与技术", "学习"),
]

# ── 新事实（阶段 A 陈述沉淀 / 阶段 B 提问召回）──
NEW_FACTS = [
    ("我养了一只仓鼠，叫豆豆", "仓鼠"),
    ("我下个月要搬家去贵阳", "搬家"),
    ("我最喜欢的歌手是周杰伦", "音乐"),
    ("我最近在学做蛋糕", "烹饪"),
    ("我家楼下新开了一家书店", "日常"),
    ("我养了只狗叫旺财", "宠物"),
    ("我周末喜欢去爬山", "爱好"),
    ("我在准备计算机等级考试", "学习"),
    ("我喜欢喝手冲咖啡", "饮食"),
    ("我打算明年养一只猫", "计划"),
    ("我最怕打针", "健康"),
    ("我有一辆二手自行车", "物品"),
    ("我最近迷上了看悬疑小说", "爱好"),
    ("我老家在遵义", "背景"),
    ("我喜欢在晚上散步", "习惯"),
]
FACT_QUERIES = [
    ("我的仓鼠叫什么？", "豆豆"),
    ("我下个月要搬去哪？", "贵阳"),
    ("我喜欢谁的歌？", "周杰伦"),
    ("我最近在学做什么？", "蛋糕"),
    ("我家楼下开了什么店？", "书店"),
    ("我的狗叫什么？", "旺财"),
    ("我周末喜欢做什么？", "爬山"),
    ("我在准备什么考试？", "计算机等级"),
    ("我喜欢喝什么？", "手冲咖啡"),
    ("我明年打算做什么？", "猫"),
    ("我最怕什么？", "打针"),
    ("我有什么交通工具？", "自行车"),
    ("我最近在看什么类型的小说？", "悬疑"),
    ("我老家在哪？", "遵义"),
    ("我喜欢什么时候散步？", "晚上"),
]
# 种子记忆提问（阶段 B 追加）
SEED_QUERIES = [
    ("你还记得我喜欢什么电影吗？", "星际穿越"),
    ("我的猫叫什么名字？", "二饼"),
    ("我上次说的考试还记得吗？", "专升本"),
]

# ── 闲聊池（阶段 A/B 填充）──
CHAT = [
    "今天天气怎么样？", "你在想什么？", "今天学到了什么？",
    "你有什么想分享的吗？", "你觉得今天过得好吗？",
    "你的爱好是什么？", "你觉得什么是重要的？",
    "你今天开心吗？", "你平时都在做什么？",
    "你想改变什么吗？", "你喜欢和人聊天吗？",
    "今天有什么特别的吗？",
]

# ── 全部实体词（使用阶段判定：回复是否引用命中实体）──
FACT_ENTITIES = [q[1] for q in FACT_QUERIES] + [s[1] for s in SEED_QUERIES]


def build_inputs(rounds: int) -> tuple[list[str], int]:
    """构造 rounds 轮输入：阶段 A 陈述+闲聊，阶段 B 提问+闲聊。
    返回 (完整输入列表, 阶段 A 长度)"""
    n_fact = len(NEW_FACTS)
    n_seed = len(SEED_QUERIES)
    seq = []
    # 阶段 A：陈述 + 闲聊交错（前 27 轮 ≈ n_fact + 12 闲聊）
    phase_a = []
    for i, (fact, _tag) in enumerate(NEW_FACTS):
        phase_a.append(fact)
        if i % 2 == 1 and len(phase_a) < 27:
            phase_a.append(CHAT[(i // 2) % len(CHAT)])
    # 阶段 B：提问（新事实 + 种子）+ 闲聊
    phase_b = [q[0] for q in FACT_QUERIES] + [q[0] for q in SEED_QUERIES]
    phase_b_full = []
    for i, q in enumerate(phase_b):
        phase_b_full.append(q)
        if i % 2 == 1:
            phase_b_full.append(CHAT[(i // 2) % len(CHAT)])
    full = phase_a + phase_b_full
    return (full * ((rounds // len(full)) + 1))[:rounds], len(phase_a)


# ── DB 沉淀快照 ───────────────────────────────────────────────
SNAP_TABLES = ["long_term_memory", "event_summary", "self_cognition",
               "self_info", "other_cognition", "user_facts"]


def db_snapshot(dbp):
    conn = sqlite3.connect(dbp)
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
                for t in SNAP_TABLES}
    finally:
        conn.close()


def memory_section_of(prompt_text: str) -> str:
    """提取 prompt 中的记忆检索结果段（供实体匹配）"""
    if "<memory-context>" in prompt_text:
        s = prompt_text.find("<memory-context>")
        e = prompt_text.find("</memory-context>", s)
        return prompt_text[s + len("<memory-context>"):e] if e > s else ""
    return ""


def matched_entities(text: str) -> list:
    return [e for e in FACT_ENTITIES if e in text]


def extract_reply(result) -> str:
    if isinstance(result, dict):
        if result.get("_port") == "reply":
            return result.get("content", "")
        if result.get("action") == "reply":
            return result.get("content", "")
        return ""
    if isinstance(result, list):
        for r in result:
            if isinstance(r, dict) and r.get("_port") == "reply":
                return r.get("content", "")
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=60)
    ap.add_argument("--db", default=os.path.join(PROJECT_ROOT, "_tmp_evo_io", "e4_fullchain.db"))
    ap.add_argument("--runs-root", default=os.path.join(PROJECT_ROOT, "docs",
                                                        "experiments", "aaa_fullchain"))
    args = ap.parse_args()

    run_dir = os.path.join(args.runs_root, time.strftime("%Y%m%d_%H%M%S") + "_E4")
    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.db), exist_ok=True)

    dbp = args.db
    # 重建干净 DB + 播种
    if os.path.exists(dbp):
        os.remove(dbp)
    db.ensure(dbp)
    conn = sqlite3.connect(dbp)
    try:
        for content, _tag in SEED_MEMORIES:
            conn.execute(
                "INSERT INTO long_term_memory"
                "(conversation_id, identity_key, source, role, content, importance, created_at)"
                " VALUES('default','gui:default','cmp_seed','combined',?,5,"
                "datetime('now','localtime'))", (content,))
        conn.commit()
    finally:
        conn.close()

    # 重建语义索引（阻塞等待模型就绪）
    memos.load_index(dbp)
    if memos._embeddings is None or len(memos._entry_ids) == 0:
        memos.rebuild_index(dbp)
    t_wait = time.time()
    while memos._get_model(timeout=0) is None:
        time.sleep(0.2)
        if time.time() - t_wait > 300:
            print("WARN: MemOS 模型就绪超时", flush=True)
            break

    node = node_main.MyNode()
    inputs, phase_a_len = build_inputs(args.rounds)
    print(f"[E4] rounds={args.rounds} 阶段A陈述+闲聊({phase_a_len}) / 阶段B提问 "
          f"run_dir={run_dir}", flush=True)

    base = db_snapshot(dbp)
    turns = []
    for i, text in enumerate(inputs):
        rid = f"e4_{i}"
        turn = {"idx": i, "user_text": text, "memory_entities": [],
                "reply_entities": [], "reply": "", "used_memory": False,
                "memory_in_prompt": False}
        t0 = time.time()
        out = node._on_text(
            {"data_type": "text", "source": "gui", "content": text,
             "request_id": rid, "conversation_id": "default",
             "identity_key": "gui:default"}, dbp)
        if not (isinstance(out, dict) and out.get("_port") == "prompt"):
            print(f"WARN turn{i}: _on_text 未返回 prompt: {out}", flush=True)
            continue
        prompt_text = out["content"]
        mem_text = memory_section_of(prompt_text)
        if mem_text:
            turn["memory_in_prompt"] = True
            turn["memory_entities"] = matched_entities(mem_text)
        raw = llm_infer(prompt_text)
        # v7.0 阶段0-bug1：截断/空回复防御（E4 首轮 5/60 空回复的根因之一——
        # 输出在节标记处中断或空响应，max_tokens=2048 不够时【自然回复】缺失）。
        # 与 E6 对齐：检测到截断 → 追加补全提示重试一次；仍空则记 raw_len 便于复盘。
        if node_psr.is_truncated(raw or ""):
            print(f"WARN turn{i}: 输出疑似截断，重试补全", flush=True)
            raw = llm_infer(prompt_text + "\n\n（注意：上次输出被截断，"
                            "请完整输出全部小节，特别是【自然回复】。）")
        r2 = node._on_parsed(
            {"data_type": "parsed", "source": "llm", "content": raw,
             "request_id": rid, "conversation_id": "default",
             "identity_key": "gui:default"}, dbp, _cfg_mod.load_config())
        # v7.3 阶段0-bug1：反思轮（self_cognition 每 10 条触发）返回 prompt 端口
        # （E4 重跑 idx 10/20/30/40/50 空回复根因——测试路径缺陷：exp 未处理
        # 反思 prompt 的二次 LLM 调用；生产 GUI 会正常发起二次调用拿回执）。
        # 补全：用反思 prompt 调 LLM 后再走一次 _on_parsed 拿最终 reply。
        if isinstance(r2, dict) and r2.get("_port") == "prompt":
            print(f"  turn{i}: 反思轮，二次调用 LLM", flush=True)
            raw2 = llm_infer(r2["content"])
            if node_psr.is_truncated(raw2 or ""):
                raw2 = llm_infer(r2["content"] + "\n\n（注意：上次输出被截断，"
                                "请完整输出全部小节。）")
            r2 = node._on_parsed(
                {"data_type": "parsed", "source": "llm", "content": raw2,
                 "request_id": r2.get("request_id", rid),
                 "conversation_id": "default",
                 "identity_key": "gui:default"}, dbp, _cfg_mod.load_config())
        reply = extract_reply(r2)
        turn["reply"] = reply
        turn["reply_entities"] = matched_entities(reply or "")
        # 使用判定：回复引用命中实体
        hit = set(turn["memory_entities"])
        used = set(turn["reply_entities"]) & hit
        turn["used_memory"] = bool(used and hit)
        turn["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
        turns.append(turn)
        # 阶段 A → 阶段 B 交界：等待异步写库 + 强制重建索引，
        # 保证阶段 B 提问能召回阶段 A 沉淀的新事实
        if i == phase_a_len - 1:
            print("  [阶段A→B] 等待异步写库 + 重建索引", flush=True)
            time.sleep(3)
            try:
                memos.rebuild_index(dbp)
            except Exception as e:
                print(f"  WARN 重建索引: {e!r}", flush=True)
        if (i + 1) % 5 == 0 or i == args.rounds - 1:
            print(f"  [{i+1}/{args.rounds}]", flush=True)

    # 等待异步写库线程完成
    time.sleep(2)
    final = db_snapshot(dbp)

    # ── 三阶段统计 ──
    sunk = {t: final[t] - base[t] for t in SNAP_TABLES}
    total_sunk = sum(sunk.values())
    recall_turns = [t for t in turns if t["memory_in_prompt"]]
    used_turns = [t for t in turns if t["used_memory"]]
    # 提问轮（阶段 B 含实体问题）中：命中率 + 使用率
    q_turns = [t for t in turns if t["user_text"].endswith("？")
               or t["user_text"].endswith("吗")]
    q_hit = [t for t in q_turns if t["memory_in_prompt"]]
    q_used = [t for t in q_turns if t["used_memory"]]

    result = {
        "run_dir": run_dir, "model": MODEL, "rounds": args.rounds,
        "sunk": sunk, "total_sunk": total_sunk,
        "recall": {"turns_with_memory": len(recall_turns),
                   "total": len(turns),
                   "rate": round(len(recall_turns) / max(len(turns), 1), 3)},
        "usage": {"turns_used_memory": len(used_turns),
                  "total": len(turns),
                  "rate": round(len(used_turns) / max(len(turns), 1), 3)},
        "question_turns": {
            "total": len(q_turns),
            "hit": len(q_hit), "hit_rate": round(len(q_hit) / max(len(q_turns), 1), 3),
            "used": len(q_used), "used_rate": round(len(q_used) / max(len(q_turns), 1), 3),
            "used_given_hit": round(len(q_used) / max(len(q_hit), 1), 3),
        },
        "turns": turns,
    }
    out_json = os.path.join(run_dir, "e4_result.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    print("\n════════ E4 沉淀-召回-使用全链路 ════════", flush=True)
    print(f"沉淀（新增条数）: {sunk}", flush=True)
    print(f"召回率: {result['recall']['rate']} "
          f"({len(recall_turns)}/{len(turns)})", flush=True)
    print(f"使用率: {result['usage']['rate']} "
          f"({len(used_turns)}/{len(turns)})", flush=True)
    print(f"提问轮 命中率 {result['question_turns']['hit_rate']} / "
          f"使用率 {result['question_turns']['used_rate']} / "
          f"命中后使用率 {result['question_turns']['used_given_hit']}", flush=True)
    print(f"[result] {out_json}", flush=True)


if __name__ == "__main__":
    main()
