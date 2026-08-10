# -*- coding: utf-8 -*-
"""阶段 1 正式版：质量引导闭环（w_max 提升版，2026-08-10）。

关键修复（验证确认）：边权饱和 256 = 4×4 神经元边 × w_max 16 的物理
上限——饱和边间质量奖励失效（并列 50% 漂移）。提升 w_max 16→64：
旧饱和边可继续涨（教学边 448 > 散文饱和 256——区分度反而更大），
质量引导真正生效。

机制：奖励闭环 8 轮（"饿"情境）：
  free_read（想到就说）→ LLM 评估（一致性+自然度）
  → ≥80 ×3 固化 / ≥60 ×1 / <60 教师示范跟读 ×2（引导）
加载 v29.2 → 快照 v30.0（w_max=64 新基准）。用法：python _grow_live4.py
"""

import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from _grow_v11 import _load_key, _llm_chat

DATA = Path(__file__).parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).parent / "runs"
N_ROUNDS = 12
EXPECT = ["饿", "了", "就", "吃", "饭"]   # "饿了就吃饭"（自由读从饿出发的自然完整句——"我"开头路径受桥禁限制）


def llm_eval(trace, toks):
    mind = " → ".join(
        f"想到「{t['state']}」，心里冒出 {t['cands']}，"
        f"选了「{t['chosen']}」" for t in trace) or "（无）"
    said = "".join(toks) or "（说不出话）"
    q = (f"你是一个只能听和说的语言评估者（面对一个自闭症儿童，"
         f"它没有视觉，只能听和说）。\n"
         f"情境：你感到饿了（饥饿感积累到阈值）\n"
         f"孩子开口前的内心活动：{mind}\n"
         f"孩子说出口的话：「{said}」\n"
         f"请输出：\n"
         f"【一致性】0-10（说出口的和心里想的贴不贴）\n"
         f"【自然度】0-10（像不像人话：语法/语义/连贯）\n"
         f"【一句话评语】≤20 字")
    txt = _llm_chat([{"role": "user", "content": q}])
    if not txt:
        return None
    out = {"cons": None, "nat": None, "note": ""}
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("【一致性】"):
            out["cons"] = float("".join(c for c in line if c.isdigit()
                                        or c == ".")[:3] or 0)
        elif line.startswith("【自然度】"):
            out["nat"] = float("".join(c for c in line if c.isdigit()
                                       or c == ".")[:3] or 0)
        elif line.startswith("【一句话评语】"):
            out["note"] = line.replace("【一句话评语】", "").strip()
    if out["cons"] is None or out["nat"] is None:
        return None
    return out


def main():
    from _exam_free import FUNC, free_read, build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool
    from _grow_cat import build_cats
    import json

    has_llm = bool(_load_key())
    t0 = time.time()
    print("═══ 阶段 1：质量引导闭环（w_max 16→64 修复版）═══\n")

    ng, vocab, pats, cursor = load_version("29.2")
    ng.w_max = 64.0                    # 关键修复：饱和 256 之上可继续涨
    n2w = {j: w for w, ns in pats.items() for j in ns}
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)

    curve = []
    for rnd in range(1, N_ROUNDS + 1):
        trace = []
        read = free_read(ng, pats, n2w, ["饿"], domain,
                         teach_out=teach_out, trace=trace)
        raw = [x.split("(")[0] for x in read]
        # 表达去重：循环前截断（"就/吃/饭/就/吃/饭" → "就/吃/饭"——
        # 循环尾巴是反向边回声，不是表达内容）
        toks = []
        for w in raw:
            if w.startswith("["):
                break
            if w in toks:
                break
            toks.append(w)
        # 自发表达含起点词（内感受）："饿"+"了就吃饭" = "饿了就吃饭"
        # ——free_read 从"饿"出发不输出起点，但表达需要它（网络
        # "感到饿"说"饿了…"）
        said = "/".join(["饿"] + toks) if toks else "（说不出话）"

        got = llm_eval(trace, toks) if has_llm else None
        if got is None:
            cons = sum(1 for t in trace
                       if t["chosen"] in [c for c, _ in t["cands"]]
                       ) / max(len(trace), 1) * 10
            nat = 7.0 if any(w in toks for w in ("吃", "饭")) else 2.0
            got = {"cons": cons, "nat": nat, "note": "（规则回退）"}
        score = got["cons"] * got["nat"]               # 一致性×自然度（门槛×高度）
        curve.append(round(score, 1))

        if score >= 80:
            r = 3
            act = "高奖励 ×3（固化）"
        elif score >= 60:
            r = 1
            act = "低奖励 ×1"
        else:
            r = 2
            act = "不奖励 → 教师示范跟读 ×2（引导）"
        for _ in range(r):
            _learn_sentence(ng, EXPECT, pats, slot=0)

        print(f"轮{rnd:2d} 说：「{said}」"
              f"  一致性 {got['cons']:.1f} · 自然度 {got['nat']:.1f}"
              f" → {score:5.1f}/100  {act}")
        print(f"     {got['note']}")

    print(f"\n═══ 质量曲线（想到就说 → 引导正确）═══")
    print("  轮次: " + " ".join(f"{i:4d}" for i in range(1, N_ROUNDS + 1)))
    print("  分数: " + " ".join(f"{s:4.0f}" for s in curve))
    print(f"  首轮 {curve[0]:.0f} → 末轮 {curve[-1]:.0f}"
          f"（{'↑ 显著提升' if curve[-1] - curve[0] > 20 else '→ 持平'}）")

    save_snapshot(ng, parent="29.2",
                  tag="阶段 1 质量引导闭环：w_max 16→64（饱和 256 之上"
                      "可涨）+ 8 轮 LLM 质量评估奖励（饿 情境）",
                  metrics={"curve": curve, "w_max": 64.0,
                           "rounds": N_ROUNDS},
                  vocab=vocab, pats=pats, cursor=cursor)
    print(f"[完成] v30.0 已存（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
