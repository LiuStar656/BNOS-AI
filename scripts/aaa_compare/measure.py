"""
AAA 节点能力测量脚本（无 GUI）— v4.0 Prefetch 改造前后对比

职责：
- 加载指定版本节点代码（--node-dir），构造 MyNode 类实例
- 不启动 GUI / 不调 LLM，直接用假 LLM 回执驱动 _on_text / _on_parsed
- 为版本建立独立 DB（--db-path），播种相同种子记忆（--seed 幂等）
- 记录每轮往返次数、prompt token 估算、记忆命中内容，写 JSON（--out）

用法：
    python measure.py --node-dir <版本目录> --db-path <db路径> \
        --mode old|new --out <结果json> [--seed]

- mode=old: 两轮交互（薄 prompt → LLM 输出【语意检索】→ 第二轮带记忆）
- mode=new: Prefetch 单轮交互（_on_text 同步预取并注入 memory-context）

约束：必须在 import numpy/memos 之前设置 OPENBLAS/OMP 线程数，防 OpenBLAS 分配失败。
"""
import os
import sys
import time
import json
import sqlite3
import argparse
import urllib.request

# ── 真实 LLM 直连（DeepSeek，与 self_evolution_test / llm 节点同源配置）──
API_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = "sk-REVOKED"
MODEL = "deepseek-v4-flash"
TEMPERATURE = 0.7
MAX_TOKENS = 2048


def llm_infer(prompt: str) -> str:
    # 偶发空响应/超时重试（最多 3 次），保证 P0 真 LLM 结果可信
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
            print(f"WARN: LLM 返回空内容，重试 {attempt+1}/3", flush=True)
        except Exception as e:
            print(f"WARN: LLM 调用异常 {e!r}，重试 {attempt+1}/3", flush=True)
            time.sleep(2)
    return ""


def _setup_openblas():
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
    os.environ.setdefault("OMP_NUM_THREADS", "2")


# ── 种子记忆（两版共用，保证检索输入一致）────────────────────
SEED_MEMORIES = [
    ("用户喜欢电影《星际穿越》，这是他最喜欢的电影，看过很多遍", "电影"),
    ("用户养了一只猫，名字叫二饼，是一只橘猫，很粘人", "宠物"),
    ("用户正在备考专升本，目标专业是计算机科学与技术", "学习"),
]
SEED_KEYWORDS = ["星际穿越", "二饼", "专升本", "计算机"]


def seed_memories(dbp):
    """幂等播种：先清空本脚本的种子（source='cmp_seed'），再插入相同记忆"""
    conn = sqlite3.connect(dbp)
    try:
        conn.execute("DELETE FROM long_term_memory WHERE source='cmp_seed'")
        for content, _tag in SEED_MEMORIES:
            conn.execute(
                "INSERT INTO long_term_memory"
                "(conversation_id, identity_key, source, role, content, importance, created_at)"
                " VALUES('default','gui:default','cmp_seed','combined',?,5,"
                "datetime('now','localtime'))",
                (content,),
            )
        conn.commit()
    finally:
        conn.close()


# ── 指标辅助 ──────────────────────────────────────────────────
def estimate_tokens(text: str) -> float:
    """Token 估算：中文约 1.5 字/token，英文约 0.25 词/token（与 ContextEngine 规则一致）"""
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cn
    return round(cn * 1.5 + other * 0.25, 1)


def analyze_prompt(text: str) -> dict:
    """检测 prompt 是否含记忆注入 + 命中种子关键词"""
    has_memory = ("memory-context" in text) or ("记忆检索结果" in text)
    kws = [k for k in SEED_KEYWORDS if k in text]
    return {
        "has_memory": has_memory,
        "keywords": kws,
        "tokens": estimate_tokens(text),
        "char_len": len(text),
    }


def fake_full_reply() -> str:
    """假 LLM 完整回复（节标记格式，兼容两版 parser 解析）"""
    return (
        "【自然回复】\n我记得你说过这件事，我们一起聊过的。\n"
        "【心情】\n平静\n"
        "【情绪调整】\n0.0\n"
        "【想法】\n回忆起之前的对话细节\n"
        "【事件摘要】\n用户询问记忆中的信息 [重要性:3]\n"
        "【自我认知】\n\n"
        "【他人认知】\n\n"
        "【用户信息】\n\n"
        "【自我信息】\n\n"
        "【记忆归档】\n\n"
        "【归档标签】\n日常"
    )


def extract_reply(result) -> str:
    """从 _on_parsed 返回值（dict 或 list）中提取 reply 文本"""
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


# ── 对话场景（两版共用）───────────────────────────────────────
# expected: 记忆问答场景的正确答案关键词（real 模式判定答对依据）
SCENARIO = [
    {"content": "你还记得我喜欢什么电影吗？", "retrieval_kw": "用户喜欢的电影",
     "expected": ["星际穿越"]},
    {"content": "我的猫叫什么名字？", "retrieval_kw": "我的猫",
     "expected": ["二饼"]},
    {"content": "最近天气怎么样", "retrieval_kw": "最近天气",
     "expected": []},
    {"content": "我上次说的考试还记得吗？", "retrieval_kw": "备考考试",
     "expected": ["专升本", "计算机"]},
]


def check_answer(turn: dict, expected: list) -> dict:
    """判定该轮回复是否答对（real 模式）：reply 或 LLM 原始回执含期望关键词"""
    text = (turn.get("reply", "") or "") + "\n" + "\n".join(turn.get("raws", []))
    found = [k for k in expected if k in text]
    return {"expected": expected, "found": found,
            "correct": bool(expected) and len(found) > 0,
            "n_expected": len(expected)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--node-dir", required=True, help="节点代码目录")
    ap.add_argument("--db-path", required=True, help="独立测试 DB 路径")
    ap.add_argument("--mode", choices=["old", "new"], required=True)
    ap.add_argument("--out", required=True, help="结果 JSON 输出路径")
    ap.add_argument("--seed", action="store_true", help="是否执行种子播种")
    ap.add_argument("--skip-retrieval", action="store_true",
                    help="仅 old 模式：模拟 LLM 忘记触发【语意检索】，直接完整回复")
    ap.add_argument("--real", action="store_true",
                    help="使用真实 LLM（DeepSeek）回执，而非假 LLM 模板")
    args = ap.parse_args()

    _setup_openblas()
    sys.path.insert(0, args.node_dir)
    os.chdir(args.node_dir)  # 保证 config.py 的相对路径 resolve 基于版本目录

    import main as node_main
    import memos
    import db as db_mod
    import parser as node_psr
    from config import load_config

    dbp = args.db_path
    db_mod.ensure(dbp)
    if args.seed:
        seed_memories(dbp)

    # ── 重建 MemOS 语义索引（阻塞等待模型就绪）──────
    memos.load_index(dbp)
    if memos._embeddings is None or len(memos._entry_ids) == 0:
        memos.rebuild_index(dbp)
    t_wait = time.time()
    while memos._get_model(timeout=0) is None:
        time.sleep(0.2)
        if time.time() - t_wait > 300:
            print("WARN: 等待 MemOS 模型就绪超时", flush=True)
            break

    node = node_main.MyNode()
    cfg = load_config()

    results = []
    for i, s in enumerate(SCENARIO):
        rid = f"cmp_{i}"
        turn = {"idx": i, "user_text": s["content"],
                "round_trips": 0, "prompts": [], "reply": "", "raws": [],
                "elapsed_ms": 0.0}
        t0 = time.time()

        # ── 第 0 步：_on_text → 返回 prompt ──────
        out = node._on_text(
            {"data_type": "text", "source": "gui", "content": s["content"],
             "request_id": rid, "conversation_id": "cmp", "identity_key": "gui:default"},
            dbp,
        )
        if isinstance(out, dict) and out.get("_port") == "prompt":
            turn["prompts"].append(analyze_prompt(out["content"]))
            turn["round_trips"] += 1
            first_prompt = out["content"]
        else:
            first_prompt = ""
            print(f"WARN turn{i}: _on_text 未返回 prompt: {out}", flush=True)

        def _parsed(rid_, content_):
            """构造 LLM 回执 data 并调用 _on_parsed"""
            return node._on_parsed(
                {"data_type": "parsed", "source": "llm", "content": content_,
                 "request_id": rid_, "conversation_id": "cmp",
                 "identity_key": "gui:default"},
                dbp, cfg,
            )

        if args.mode == "old":
            if args.real:
                # 真实 LLM：第一轮回执由模型自主决定是否触发【语意检索】
                raw1 = llm_infer(first_prompt)
                turn["raws"].append(raw1)
                r1 = _parsed(rid, raw1)
                if isinstance(r1, dict) and r1.get("_port") == "prompt":
                    turn["prompts"].append(analyze_prompt(r1["content"]))
                    turn["round_trips"] += 1
                    turn["retrieval_triggered"] = True
                    raw2 = llm_infer(r1["content"])
                    turn["raws"].append(raw2)
                    r2 = _parsed(r1.get("request_id", rid), raw2)
                    turn["reply"] = extract_reply(r2)
                else:
                    turn["retrieval_triggered"] = "语意检索" in raw1
                    turn["reply"] = extract_reply(r1)
            elif args.skip_retrieval:
                # 模拟真实 LLM 忘记触发【语意检索】→ 第一轮直接完整回复（无记忆注入）
                r2 = _parsed(rid, fake_full_reply())
                turn["reply"] = extract_reply(r2)
                turn["retrieval_triggered"] = False
            else:
                # 假 LLM：第一轮强制输出【语意检索】→ 第二轮带记忆
                r1 = _parsed(rid, f"【语意检索】\n{s['retrieval_kw']}")
                if isinstance(r1, dict) and r1.get("_port") == "prompt":
                    turn["prompts"].append(analyze_prompt(r1["content"]))
                    turn["round_trips"] += 1
                    turn["retrieval_triggered"] = True
                    r2 = _parsed(r1.get("request_id", rid), fake_full_reply())
                    turn["reply"] = extract_reply(r2)
                else:
                    turn["retrieval_triggered"] = False
                    turn["reply"] = extract_reply(r1)
        else:
            if args.real:
                # 新版单轮：prompt 已带 memory-context → 真实 LLM 直接完整回复
                raw1 = llm_infer(first_prompt)
                turn["raws"].append(raw1)
                r2 = _parsed(rid, raw1)
                turn["reply"] = extract_reply(r2)
            else:
                r2 = _parsed(rid, fake_full_reply())
                turn["reply"] = extract_reply(r2)

        turn["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
        turn["memory_present"] = any(p["has_memory"] for p in turn["prompts"])
        turn["memory_keywords"] = sorted({
            k for p in turn["prompts"] for k in p["keywords"]
        })
        turn["answer"] = check_answer(turn, s["expected"])
        results.append(turn)

    summary = {
        "node_dir": args.node_dir,
        "mode": args.mode,
        "real": args.real,
        "db_path": dbp,
        "round_trips_total": sum(t["round_trips"] for t in results),
        "tokens_total": sum(p["tokens"] for t in results for p in t["prompts"]),
        "turns_with_memory": sum(1 for t in results if t["memory_present"]),
        "answers_correct": sum(1 for t in results if t["answer"]["correct"]),
        "turns": results,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"OK mode={args.mode} real={args.real} round_trips={summary['round_trips_total']} "
          f"tokens={summary['tokens_total']} memory_turns={summary['turns_with_memory']} "
          f"answers_correct={summary['answers_correct']}",
          flush=True)


if __name__ == "__main__":
    main()
