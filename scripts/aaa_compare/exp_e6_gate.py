"""
E6 检索门控（输入侧向量锚点）实验（真 LLM）

对照四组（config.retrieval_gate.mode 驱动同一生产模块 retrieval_gate.py）：
  G_off     关闭门控，每轮强制预取（v4.0 现状 = baseline）
  G_symbol  符号规则兜底
  G_single  向量锚点单阈值（t1=0.78，E1 标定值）
  G_dual    双阈值 t1/t2（0.75/0.95）+ 模糊区 LLM 精判

场景三类 9 个：
  正例-回忆询问 3 个（期望预取 → 答对）：电影 / 猫名 / 考试
  负例-写入型   3 个（新信息，期望拦截）：换工作 / 养狗 / 学钢琴
  负例-无关闲聊 3 个（期望拦截）：天气 / 心情烦 / 找工作

指标：
  拦截率（门控 skip 轮次占比）、模糊区占比、LLM 精判调用数
  正例答对率（回忆询问被预取且答对）、负例联想率（无关场景回复含种子实体）
  写入型误触发率（写入型被放行预取占比，规划判定 ≤ 10%）

用法（项目根目录，AAA 节点 venv）：
  python scripts/aaa_compare/exp_e6_gate.py --calibrate   # 只打门控分数，不调 LLM
  python scripts/aaa_compare/exp_e6_gate.py --repeats 3   # 全量
"""
import os
import sys
import time
import json
import sqlite3
import argparse
import urllib.request

import numpy as np

os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")

PROJECT_ROOT = r"e:\杂项\BNOS_AI_project"
NODE_DIR = os.path.join(PROJECT_ROOT, "nodes", "node_python_aaa_cognition")

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


sys.path.insert(0, NODE_DIR)
os.chdir(NODE_DIR)
import db
import memos
import parser as psr
import prompt as pmt
import personality as prs
import retrieval_gate
from config import load_config

# 防后台聚合（本脚本不走节点全链路）
memos.rebuild_knowledge_index = lambda *a, **k: None
db._aggregate_mood = lambda *a, **k: None

# ── 种子记忆（同 E1/E2）──
SEED_MEMORIES = [
    ("用户喜欢电影《星际穿越》，这是他最喜欢的电影，看过很多遍", "电影"),
    ("用户养了一只猫，名字叫二饼，是一只橘猫，很粘人", "宠物"),
    ("用户正在备考专升本，目标专业是计算机科学与技术", "学习"),
]
SEED_KEYWORDS = ["星际穿越", "二饼", "专升本", "计算机", "橘猫"]

# ── E6 场景：正例回忆询问 / 负例写入型 / 负例无关闲聊 ──
E6_SCENARIOS = [
    {"content": "你还记得我喜欢什么电影吗？", "expected": ["星际穿越"], "kind": "pos"},
    {"content": "我的猫叫什么名字？", "expected": ["二饼"], "kind": "pos"},
    {"content": "我上次说的考试还记得吗？", "expected": ["专升本", "计算机"], "kind": "pos"},
    {"content": "我最近换工作了，从广州调到上海", "expected": [], "kind": "write"},
    {"content": "我新养了一只狗，叫来福", "expected": [], "kind": "write"},
    {"content": "我准备学钢琴了", "expected": [], "kind": "write"},
    {"content": "最近天气怎么样", "expected": [], "kind": "noise"},
    {"content": "今天心情有点烦，陪我聊聊天吧", "expected": [], "kind": "noise"},
    {"content": "你觉得我应该怎么规划找工作？", "expected": [], "kind": "noise"},
]

# ── 模糊区 LLM 精判（dual 模式）──
def llm_judge(text: str) -> bool:
    prompt = ("判断下面的用户输入是否在回忆或询问 AI 之前记住的关于用户的信息"
              "（如之前说过的事、名字、喜好、计划、宠物）。只回复两个字：需要 或 不需要。\n\n"
              f"输入：{text}")
    r = (llm_infer(prompt) or "").strip()
    # 必须先判「不需要」：'需要' in '不需要' 为 True（首轮 G_dual 学钢琴/找工作
    # 被误放行的根因），判序反了会把 LLM 的否定回答当成肯定
    if "不需要" in r:
        return False
    return "需要" in r


def build_prompt(user_text, memory_text):
    ctx = {
        "identity_key": "probe",
        "fixed_cognition": "", "self_cognition": "", "other_cognition": "",
        "recent_feelings": "", "mood_trend": "", "perception": "",
        "location_section": "", "attachment_context": "", "reflection_section": "",
        "history_summary": "", "user_info": "", "self_info": "",
        "user_text": user_text,
        "user_text_section": f"### 用户输入\n{user_text}",
        "current_date": "2026-08-08", "current_time": "12:00:00",
        "personality": prs.build_personality_section(
            {"warmth": 0.6, "playfulness": 0.4, "directness": 0.5, "curiosity": 0.5}, ""),
        "mood": prs.build_mood_section(0.0),
        "pool_batch_section": "", "db_path": "", "user_id": "probe",
        "memos_top5": memory_text if memory_text else "",
    }
    return pmt.build_direct(ctx)


def extract_reply(raw: str) -> str:
    parsed = psr.parse_llm_output(raw)
    return parsed.get("自然回复", "") or ""


def _fetch_memories(query, dbp):
    """检索 top5 并格式化（与生产 prefetch 同一检索路径）"""
    raw = memos.retrieve(query, top_k=5, db_path=dbp, identity_key="gui:default")
    return raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--group", default="",
                    help="只跑指定组（G_off/G_symbol/G_single/G_dual），默认全部")
    ap.add_argument("--calibrate", action="store_true",
                    help="只打印各场景门控分数与判定，不调 LLM")
    ap.add_argument("--db", default=os.path.join(PROJECT_ROOT, "_tmp_evo_io", "e6.db"))
    ap.add_argument("--runs-root", default=os.path.join(PROJECT_ROOT, "docs",
                                                        "experiments", "aaa_fullchain"))
    args = ap.parse_args()

    # ── 初始化临时库（种子记忆 + 索引）──
    dbp = args.db
    if os.path.exists(dbp):
        os.remove(dbp)
    db.ensure(dbp)
    conn = sqlite3.connect(dbp)
    try:
        try:
            conn.execute("ALTER TABLE long_term_memory ADD COLUMN identity_key TEXT DEFAULT 'gui:default'")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        for content, _tag in SEED_MEMORIES:
            conn.execute(
                "INSERT INTO long_term_memory"
                "(conversation_id, identity_key, source, role, content, importance, created_at)"
                " VALUES('default','gui:default','cmp_seed','combined',?,5,"
                "datetime('now','localtime'))", (content,))
        conn.commit()
    finally:
        conn.close()

    # 清旧索引残留（id 撞车会令新种子不被索引，E1 首跑教训）
    old_idx = os.path.join(os.path.dirname(dbp), "memos_index.npz")
    memos.load_index(dbp)
    if os.path.exists(old_idx) and memos._index_path == old_idx:
        os.remove(old_idx)
        memos.load_index(dbp)
    if memos._embeddings is None or len(memos._entry_ids) == 0:
        memos.rebuild_index(dbp)  # 阻塞加载模型
    memos._get_model()
    retrieval_gate.reset_proto_vecs()
    retrieval_gate._ensure_proto_vecs()
    print(f"[E6] 索引条目={len(memos._entry_ids)} 原型就绪", flush=True)

    if args.calibrate:
        print("\n── 门控分数标定（t1=0.75 / t2=0.95，阈值可改 config 后重跑）──", flush=True)
        for s in E6_SCENARIOS:
            sc = retrieval_gate.gate_score(s["content"])
            print(f"  [{s['kind']:5s}] {s['content'][:18]:20s} score={sc} "
                  f"t1跳过={sc is not None and sc < 0.75} t2放行={sc is not None and sc > 0.95} "
                  f"模糊区={sc is not None and 0.75 <= sc <= 0.95}", flush=True)
        return

    run_dir = os.path.join(args.runs_root,
                           time.strftime("%Y%m%d_%H%M%S") + "_E6")
    os.makedirs(run_dir, exist_ok=True)

    # 组定义：覆盖 config 切换生产门控模式（同模块同代码路径）
    groups = {
        "G_off": {"mode": "off"},
        "G_symbol": {"mode": "symbol"},
        "G_single": {"mode": "single", "t1": 0.78},
        "G_dual": {"mode": "dual", "t1": 0.75, "t2": 0.95},
    }
    if args.group:
        groups = {gid: gcfg for gid, gcfg in groups.items() if gid == args.group}
        if not groups:
            print(f"未知组 {args.group}，可选 {list(groups)}", flush=True)
            return
    results = []
    for gid, gcfg in groups.items():
        _cfg_mod = __import__("config")
        _cfg_mod._config = dict(load_config())
        _cfg_mod._config["retrieval_gate"] = dict(gcfg)
        retrieval_gate.reset_proto_vecs()
        retrieval_gate.set_llm_judge(llm_judge if gid == "G_dual" else None)
        print(f"[{gid}] mode={gcfg['mode']}", flush=True)
        for s in E6_SCENARIOS:
            for rep in range(args.repeats):
                should, info = retrieval_gate.should_prefetch(s["content"])
                memory_text = ""
                if should:
                    memory_text = _fetch_memories(s["content"], dbp)
                prompt_text = build_prompt(s["content"], memory_text)
                raw = llm_infer(prompt_text)
                if psr.is_truncated(raw or ""):
                    raw = llm_infer(prompt_text + "\n\n（注意：上次输出被截断，请完整输出全部小节。）")
                reply = extract_reply(raw)
                found = [k for k in s["expected"] if k in reply]
                noise = [k for k in SEED_KEYWORDS
                         if k in reply and k not in s["expected"]]
                results.append({
                    "group": gid, "scenario": s["content"], "kind": s["kind"],
                    "rep": rep, "gate_decision": info.get("decision"),
                    "gate_score": info.get("score"), "gate_layer": info.get("layer"),
                    "gate_judge": info.get("judge", ""),
                    "memory_injected": bool(memory_text),
                    "reply": reply[:160], "correct": len(found) > 0,
                    "found": found, "noise_keywords": noise,
                })
                print(f"[{gid}] [{s['kind'][:4]}] {s['content'][:14]} rep{rep} "
                      f"gate={info.get('decision')} correct={results[-1]['correct']} "
                      f"noise={noise}", flush=True)

    # ── 汇总 ──
    summary = _summarize(results)
    out_json = os.path.join(run_dir, "E6_result.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"run_dir": run_dir, "model": MODEL, "repeats": args.repeats,
                   "summary": summary, "results": results},
                  f, ensure_ascii=False, indent=1)
    print("\n════════ E6 检索门控 ════════", flush=True)
    for k, v in summary.items():
        print(f"  {k}: {v}", flush=True)
    print(f"[result] {out_json}", flush=True)


def _summarize(results):
    out = {}
    for gid in ("G_off", "G_symbol", "G_single", "G_dual"):
        g = [r for r in results if r["group"] == gid]
        pos = [r for r in g if r["kind"] == "pos"]
        write = [r for r in g if r["kind"] == "write"]
        noise = [r for r in g if r["kind"] == "noise"]
        pos_correct = sum(1 for r in pos if r["correct"])
        noise_rate = sum(1 for r in noise if r["noise_keywords"])
        write_false = sum(1 for r in write if r["memory_injected"])
        intercept = sum(1 for r in g if r["gate_decision"] == "skip")
        gray = sum(1 for r in g if r.get("gate_layer") == "gray")
        judge_calls = sum(1 for r in g if r.get("gate_judge") == "llm")
        out[gid] = {
            "正例答对率": f"{pos_correct}/{len(pos)}",
            "无关联想率": f"{noise_rate}/{len(noise)}",
            "写入型误触发率": f"{write_false}/{len(write)}",
            "拦截率": f"{intercept}/{len(g)}",
            "模糊区占比": f"{gray}/{len(g)}",
            "LLM精判调用": judge_calls,
            "注入轮数": f"{sum(1 for r in g if r['memory_injected'])}/{len(g)}",
        }
    return out


if __name__ == "__main__":
    main()
