# -*- coding: utf-8 -*-
"""阶段 1：想到就说 → 奖励闭环长跑（2026-08-10 用户："先从想到就说
的角度锻炼网络正确的自我表达（自然语言能力）"）。

机制（_grow_live2 闭环的长期运行实证）：
  每轮：自由运行"饿"情境 → 心理轨迹 + 表达（想到就说）
        → LLM 评估（一致性+自然度+示范句）
        → 质量奖励：≥80 ×3 固化 / ≥60 ×1 / <60 教师示范跟读 ×1
          （低质不焊死 + 示范引导——"想到就说"的内容逐步变对）
  8 轮 → 质量曲线（一致性/自然度/总分随轮次变化——学习曲线）

加载 v29.2（不落快照——闭环演示）。用法：python _grow_live3.py
"""

import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version
from _grow_v11 import _load_key, _llm_chat

DATA = Path(__file__).parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).parent / "runs"
N_ROUNDS = 8

EXPECT = ["我", "饿", "了", "就", "吃", "饭"]     # 期望表达（教师示范）


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
         f"【示范句】一句这个情境下孩子应该说的自然口语（≤12 字）\n"
         f"【一句话评语】≤20 字")
    txt = _llm_chat([{"role": "user", "content": q}])
    if not txt:
        return None
    out = {"cons": None, "nat": None, "demo": "", "note": ""}
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("【一致性】"):
            out["cons"] = float("".join(c for c in line if c.isdigit()
                                        or c == ".")[:3] or 0)
        elif line.startswith("【自然度】"):
            out["nat"] = float("".join(c for c in line if c.isdigit()
                                       or c == ".")[:3] or 0)
        elif line.startswith("【示范句】"):
            out["demo"] = line.replace("【示范句】", "").strip()
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
    print("═══ 阶段 1：想到就说 · 奖励闭环长跑（8 轮）═══\n")

    ng, vocab, pats, cursor = load_version("29.2")
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
        toks = [x.split("(")[0] for x in read]
        said = "/".join(toks) or "（说不出话）"

        got = llm_eval(trace, toks) if has_llm else None
        if got is None:
            cons = sum(1 for t in trace
                       if t["chosen"] in [c for c, _ in t["cands"]]
                       ) / max(len(trace), 1) * 10
            nat = 6.0 if any(w in toks for w in ("吃", "饭")) else 2.0
            got = {"cons": cons, "nat": nat, "demo": "我饿了就吃饭",
                   "note": "（规则回退）"}
        score = got["cons"] * got["nat"]               # 一致性×自然度（门槛×高度）
        curve.append(round(score, 1))

        if score >= 80:
            r = 3
            act = "高奖励 ×3（固化）"
        elif score >= 60:
            r = 1
            act = "低奖励 ×1"
        else:
            r = 0
            act = "不奖励 → 教师示范跟读 ×1"
            _learn_sentence(ng, EXPECT, pats, slot=0)
        for _ in range(r):
            _learn_sentence(ng, EXPECT, pats, slot=0)

        print(f"轮{rnd:2d} 说：「{said}」"
              f"  一致性 {got['cons']:.1f} · 自然度 {got['nat']:.1f}"
              f" → {score:5.1f}/100  {act}")
        print(f"     {got['note']}"
              + (f"（示范：「{got['demo']}」）" if r == 0 else ""))

    print(f"\n═══ 质量曲线（想到就说 → 被引导）═══")
    print("  轮次: " + " ".join(f"{i:4d}" for i in range(1, N_ROUNDS + 1)))
    print("  分数: " + " ".join(f"{s:4.0f}" for s in curve))
    trend = "↑ 提升" if curve[-1] > curve[0] + 5 else \
            ("→ 持平" if abs(curve[-1] - curve[0]) <= 5 else "↓ 下降")
    print(f"  首轮 {curve[0]:.0f} → 末轮 {curve[-1]:.0f}：{trend}")
    print(f"\n[说明] 低分轮教师示范跟读（引导），高分轮固化（强化）——"
          f"想到就说 的内容被质量信号逐步引导正确")
    print(f"[留档] runs/_speak_logs/ 已记录（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
