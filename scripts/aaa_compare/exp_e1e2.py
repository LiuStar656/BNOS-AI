"""
E1 注入噪声消融 + E2 命中-使用 gap 实验（真 LLM，可控注入变量）

E1（--exp E1）注入噪声消融：
  变量（组）：top_k 数量(1/3/5) / 相关性阈值(0.4) / 排序标注 / 输入侧判定
  场景：3 有答案记忆场景 + 3 无关对照组（天气/工作/闲聊）
  指标：有答案场景正确率、无关场景无关联想率（回复含种子实体词）

E2（--exp E2）命中-使用 gap：
  变量（组）：memory-context 四种格式
    F1 现状平铺 / F2 带相关度分值 / F3 排序+最高置顶 / F4 关键词前置强调
  场景：3 有答案记忆场景（固定 top_k=5 检索结果）
  指标：提取成功率（回复含期望答案关键词）

用法（项目根目录，AAA 节点 venv）：
  python scripts/aaa_compare/exp_e1e2.py --exp E1 [--repeats 3]
  python scripts/aaa_compare/exp_e1e2.py --exp E2 [--repeats 3]
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
from config import load_config

# 注：不能 patch rebuild_index —— main() 需它把种子记忆真正编入索引，
# 否则 retrieve_raw 恒为空、实验全部失效。仅禁无关后台聚合。
memos.rebuild_knowledge_index = lambda *a, **k: None
db._aggregate_mood = lambda *a, **k: None

# ── 种子记忆（同 aaa_cmp / E4）──
SEED_MEMORIES = [
    ("用户喜欢电影《星际穿越》，这是他最喜欢的电影，看过很多遍", "电影"),
    ("用户养了一只猫，名字叫二饼，是一只橘猫，很粘人", "宠物"),
    ("用户正在备考专升本，目标专业是计算机科学与技术", "学习"),
]
SEED_KEYWORDS = ["星际穿越", "二饼", "专升本", "计算机", "橘猫"]

# ── E1 场景：有答案 + 无关对照 ──
E1_SCENARIOS = [
    {"content": "你还记得我喜欢什么电影吗？", "expected": ["星际穿越"], "has_answer": True},
    {"content": "我的猫叫什么名字？", "expected": ["二饼"], "has_answer": True},
    {"content": "我上次说的考试还记得吗？", "expected": ["专升本", "计算机"], "has_answer": True},
    {"content": "最近天气怎么样", "expected": [], "has_answer": False},
    {"content": "你觉得我应该怎么规划找工作？", "expected": [], "has_answer": False},
    {"content": "今天心情有点烦，陪我聊聊天吧", "expected": [], "has_answer": False},
]

# ── E2 场景：固定检索结果（top_k=5 原样）──
E2_SCENARIOS = [
    {"content": "你还记得我喜欢什么电影吗？", "expected": ["星际穿越"]},
    {"content": "我的猫叫什么名字？", "expected": ["二饼"]},
    {"content": "我上次说的考试还记得吗？", "expected": ["专升本", "计算机"]},
]

# ── E1 组定义 ──
# 每个组返回一个 "构造 memory-context 文本" 的函数
def _raw_results(query, top_k, dbp, threshold=0.3):
    """结构化检索结果（retrieve_raw 已带 0.3 阈值）"""
    raw = memos.retrieve_raw(query, top_k=top_k * 3, identity_key="gui:default")
    rows = []
    for r in raw:
        if r["score"] < threshold:
            continue
        conn = sqlite3.connect(dbp)
        try:
            row = conn.execute(
                f"SELECT content FROM [{r['table']}] WHERE id=?", (r["entry_id"],)
            ).fetchone()
        finally:
            conn.close()
        if row:
            rows.append({"content": row[0][:200], "score": r["score"]})
        if len(rows) >= top_k:
            break
    return rows


def fmt_plain(rows):
    return "\n".join(f"[{r['score']:.2f}] {r['content']}" for r in rows)


def fmt_ranked(rows):
    rows = sorted(rows, key=lambda r: r["score"], reverse=True)
    return "\n".join(f"[相关度 {r['score']:.2f}] {r['content']}" for r in rows)


def fmt_emphasized(rows):
    rows = sorted(rows, key=lambda r: r["score"], reverse=True)
    lines = []
    for i, r in enumerate(rows, 1):
        if i == 1:
            lines.append(f"记忆1（与当前问题最相关）：{r['content']}")
        else:
            lines.append(f"记忆{i}：{r['content']}")
    return "\n".join(lines)


def fmt_threshold(rows, thr=0.4):
    return fmt_plain([r for r in rows if r["score"] >= thr])


# ── 输入侧判定：向量锚点门控（v1.4 规划，与 E6 共用意图原型）──
# 阈值按当前 embedding 模型实测标定：0.78 下 3 个有答案场景全过门，
# 无关场景「天气 0.598 / 闲聊 0.691」被拦截，「规划找工作 0.904」误放行
# （all-MiniLM-L6-v2 中文相似度虚高，这是门控的能力边界，如实记录）。
GATE_THRESHOLD = 0.78

INTENT_PROTOTYPES = [
    "你还记得我之前说过的事情吗",
    "你记得我喜欢什么吗",
    "我的猫叫什么名字",
    "我之前说的考试你还记得吗",
    "我们之前聊过什么",
    "你还记得我的事吗",
]
_PROTO_VECS = None


def _ensure_proto_vecs():
    global _PROTO_VECS
    if _PROTO_VECS is None:
        _PROTO_VECS = np.array(
            [v for v in (memos._encode(p) for p in INTENT_PROTOTYPES) if v is not None])
    return _PROTO_VECS


def gate_input(text: str) -> bool:
    """向量锚点门控：输入与意图原型最大余弦 >= 阈值 → 预取。
    模型未就绪时保守返回 True（预取）。"""
    if _PROTO_VECS is None or len(_PROTO_VECS) == 0:
        return True
    qv = memos._encode(text)
    if qv is None:
        return True
    return float((_PROTO_VECS @ qv).max()) >= GATE_THRESHOLD


# ── Prompt 构造（复用生产模板，仅替换 memory 段）──
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", choices=["E1", "E2"], required=True)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--db", default=os.path.join(PROJECT_ROOT, "_tmp_evo_io", "e1e2.db"))
    ap.add_argument("--runs-root", default=os.path.join(PROJECT_ROOT, "docs",
                                                        "experiments", "aaa_fullchain"))
    args = ap.parse_args()

    run_dir = os.path.join(args.runs_root,
                           time.strftime("%Y%m%d_%H%M%S") + f"_{args.exp}")
    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.db), exist_ok=True)

    dbp = args.db
    if os.path.exists(dbp):
        os.remove(dbp)
    db.ensure(dbp)
    conn = sqlite3.connect(dbp)
    try:
        # 临时库由 ensure 新建，long_term_memory 无 identity_key 列
        # （生产库该列来自 v6.0 多用户改造的历史迁移），这里补上，
        # 否则种子插入 SQL 与 memos.rebuild_index 都会报列不存在。
        try:
            conn.execute(
                "ALTER TABLE long_term_memory ADD COLUMN identity_key TEXT DEFAULT 'gui:default'")
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

    memos.load_index(dbp)
    print(f"[{args.exp}] 启动 run_dir={run_dir} db={args.db}", flush=True)
    # 清理旧索引残留：npz 的 entry_ids 与新建临时库自增 id 撞车，
    # 会令新种子被判「已存在」而跳过索引（E1 首次空检索的根因）。
    # 注：load_index 必须先于删除，否则拿不到 npz 路径可删。
    old_idx = os.path.join(os.path.dirname(dbp), "memos_index.npz")
    if os.path.exists(old_idx) and memos._index_path == old_idx:
        os.remove(old_idx)
        memos.load_index(dbp)
        print(f"[{args.exp}] 已清除旧索引残留 {old_idx}", flush=True)
    if memos._embeddings is None or len(memos._entry_ids) == 0:
        memos.rebuild_index(dbp)  # 内部阻塞加载模型
    memos._get_model()  # 确保模型就绪（timeout=0 非阻塞查询不会触发加载）
    _ensure_proto_vecs()
    print(f"[{args.exp}] 索引条目={len(memos._entry_ids)} 原型向量="
          f"{_PROTO_VECS.shape}", flush=True)

    results = []
    if args.exp == "E1":
        # 组：top1 / top3 / top5 / thr0.4 / 排序标注 / 输入侧判定
        groups = {
            "G1_top1": lambda q: fmt_plain(_raw_results(q, 1, dbp)),
            "G2_top3": lambda q: fmt_plain(_raw_results(q, 3, dbp)),
            "G3_top5": lambda q: fmt_plain(_raw_results(q, 5, dbp)),
            "G4_thr04": lambda q: fmt_threshold(_raw_results(q, 5, dbp), 0.4),
            "G5_ranked": lambda q: fmt_ranked(_raw_results(q, 5, dbp)),
            "G6_gate": lambda q: (fmt_plain(_raw_results(q, 5, dbp))
                                  if gate_input(q) else ""),
        }
        for gid, mk in groups.items():
            for s in E1_SCENARIOS:
                for rep in range(args.repeats):
                    mem_text = mk(s["content"])
                    prompt_text = build_prompt(s["content"], mem_text)
                    raw = llm_infer(prompt_text)
                    if psr.is_truncated(raw or ""):
                        raw = llm_infer(prompt_text + "\n\n（注意：上次输出被截断，请完整输出全部小节。）")
                    reply = extract_reply(raw)
                    found = [k for k in s["expected"] if k in reply]
                    noise = [k for k in SEED_KEYWORDS
                             if k in reply and k not in s["expected"]]
                    results.append({
                        "group": gid, "scenario": s["content"],
                        "has_answer": s["has_answer"], "rep": rep,
                        "memory_injected": bool(mem_text),
                        "reply": reply[:200], "correct": bool(s["expected"]) and len(found) > 0,
                        "found": found, "noise_keywords": noise,
                        "prompt_tokens": _est_tokens(prompt_text),
                    })
                    print(f"[{gid}] {s['content'][:16]} rep{rep} "
                          f"correct={results[-1]['correct']} noise={noise}",
                          flush=True)
    else:
        # E2：固定 top_k=5 检索结果，4 种格式
        formats = {
            "F1_plain": fmt_plain,
            "F2_scored": fmt_plain,      # 现状已有 [score] 前缀
            "F3_ranked": fmt_ranked,
            "F4_emphasized": fmt_emphasized,
        }
        for fid, fmt_fn in formats.items():
            for s in E2_SCENARIOS:
                rows = _raw_results(s["content"], 5, dbp)
                for rep in range(args.repeats):
                    mem_text = fmt_fn(rows)
                    prompt_text = build_prompt(s["content"], mem_text)
                    raw = llm_infer(prompt_text)
                    if psr.is_truncated(raw or ""):
                        raw = llm_infer(prompt_text + "\n\n（注意：上次输出被截断，请完整输出全部小节。）")
                    reply = extract_reply(raw)
                    found = [k for k in s["expected"] if k in reply]
                    results.append({
                        "format": fid, "scenario": s["content"], "rep": rep,
                        "reply": reply[:200], "correct": len(found) > 0,
                        "found": found,
                        "prompt_tokens": _est_tokens(prompt_text),
                    })
                    print(f"[{fid}] {s['content'][:16]} rep{rep} "
                          f"correct={results[-1]['correct']} found={found}",
                          flush=True)

    # ── 汇总统计 ──
    summary = _summarize(args.exp, results)
    out_json = os.path.join(run_dir, f"{args.exp}_result.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"run_dir": run_dir, "model": MODEL, "repeats": args.repeats,
                   "summary": summary, "results": results},
                  f, ensure_ascii=False, indent=1)

    print("\n════════ " + ("E1 注入噪声消融" if args.exp == "E1"
                           else "E2 命中-使用 gap") + " ════════", flush=True)
    for k, v in summary.items():
        print(f"  {k}: {v}", flush=True)
    print(f"[result] {out_json}", flush=True)


def _est_tokens(text: str) -> float:
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cn
    return round(cn * 1.5 + other * 0.25, 1)


def _summarize(exp, results):
    if exp == "E1":
        out = {}
        for gid in ("G1_top1", "G2_top3", "G3_top5", "G4_thr04", "G5_ranked", "G6_gate"):
            g = [r for r in results if r["group"] == gid]
            ans = [r for r in g if r["has_answer"]]
            noa = [r for r in g if not r["has_answer"]]
            correct = sum(1 for r in ans if r["correct"])
            noise = sum(1 for r in noa if r["noise_keywords"])
            out[gid] = {
                "答案正确率": f"{correct}/{len(ans)}",
                "无关联想率": f"{noise}/{len(noa)}",
                "注入轮数": f"{sum(1 for r in g if r['memory_injected'])}/{len(g)}",
            }
        return out
    out = {}
    for fid in ("F1_plain", "F2_scored", "F3_ranked", "F4_emphasized"):
        g = [r for r in results if r["format"] == fid]
        correct = sum(1 for r in g if r["correct"])
        out[fid] = {"提取成功率": f"{correct}/{len(g)}",
                    "正确": [r["found"] for r in g if r["correct"]],
                    "全部": [[r["scenario"][:10], r["correct"], r["found"]] for r in g]}
    return out


if __name__ == "__main__":
    main()
