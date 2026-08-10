# -*- coding: utf-8 -*-
"""自然语言质量评估工具（2026-08-10 用户定稿："以后必须评估网络的
回答质量，从自然语言的角度"）。

对卷二（域内自由读）全卷 155 题做**语言质量评估**（不是分数）：
  ① 开口正确率：第 1 跳 ∈ 该题期望集（back 前 2 词 ∪ 合理关系词）
  ② 链延续率：第 2 跳 ∈ back ∪ 关系词（接得上话）
  ③ 整句率：链 ≥3 跳且无循环/黑洞（说得出完整话）
  ④ 循环率：[黑洞]/[循环] 占比（刻板言语指标）
  ⑤ 多样性：唯一输出模式数 / 题数（模板复读指标）
  ⑥ 开口类型分布：内容词 / 关系词 / 其他（开口像不像话）

输出：质量报告（文本 + JSON 留档 runs/_quality/）。

用法：python _eval_quality.py [快照版本]
"""

import json
import sys
import time
from pathlib import Path

from snapshot import load_version
from _grow_v16 import direct_next_multi
from _exam_big import A_PAIRS, B_SENTS, C_SENTS, D_SENTS, H_SENTS, I_SENTS
from _exam_free import FUNC, free_read, build_domain, build_teach_out

DATA = Path(__file__).parent / "data" / "curriculum"
RUNS = Path(__file__).parent / "runs"
VER = sys.argv[1] if len(sys.argv) > 1 else "26.1"

# 合理开口关系词（句式/问答起句）
REL = {"所以", "但是", "然后", "因为", "虽然", "先", "为什么", "如果"}


def main():
    t0 = time.time()
    ng, vocab, pats, cursor = load_version(VER)
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    from _grow_cat import build_cats
    from _grow_qa_s3 import build_pool as qa_build_pool
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)

    # 题表（front, back 期望）
    items = [("「%s」" % a, [a], [b]) for a, b in A_PAIRS]
    items += [(s, f, b) for s, f, b in B_SENTS]
    items += [(s, f, b) for s, f, b in C_SENTS]
    items += [(s, f, b) for s, f, b in D_SENTS]
    items += [(ask, [kw], exp) for ask, kw, exp, layer in q_pool[:15]]
    from _grow_self_express import STATES, FCT_ITEMS, CAUSE_ITEMS
    items += [(f"你觉得{st}", [st], d["expr"]) for st, d in STATES.items()]
    items += [(f"情境：{n}", [kw], ch) for n, ch, kw, t in FCT_ITEMS[:4]]
    items += [(f"情境：{CAUSE_ITEMS[0][0]}", [CAUSE_ITEMS[0][2]],
               CAUSE_ITEMS[0][1])]
    from _grow_s3_ask import NEW_ASKS, RHET_ITEMS
    items += [(q, [kw], qch) for q, kw, qch, ach in NEW_ASKS]
    items += [(f"（教师说：{n}）", [ch[0]], ch[1:]) for n, ch, k in RHET_ITEMS]
    items += [(s, f, b) for s, f, b in H_SENTS]
    items += [(s, f, b) for s, f, b in I_SENTS]

    # ── 全卷自由读 → 质量指标 ─────────────────────────
    n_open_ok = n_chain_ok = n_sent = n_loop = n_legal = 0
    n_adj = 0
    templates = {}
    open_types = {"content": 0, "rel": 0, "other": 0}
    samples_bad = []
    for i, (label, front, back) in enumerate(items, 1):
        read = free_read(ng, pats, n2w, front, domain,
                          teach_out=teach_out)
        toks = [x.split("(")[0] for x in read]
        # ① 开口
        first = toks[0] if toks else ""
        expect_open = set(back[:2]) | REL
        ok_open = first in expect_open
        n_open_ok += ok_open
        # ⑥ 类型
        if first in REL:
            open_types["rel"] += 1
        elif first and first not in FUNC:
            open_types["content"] += 1
        else:
            open_types["other"] += 1
        # ② 链延续（第 2 跳）
        if len(toks) >= 2 and toks[1] in set(back) | REL:
            n_chain_ok += 1
        # ③ 整句（≥3 跳且无循环）
        if len(toks) >= 3 and not any(x.startswith("[") for x in toks):
            n_sent += 1
        # ④ 循环
        if any(x.startswith("[") for x in toks):
            n_loop += 1
        # ⑤ 模板
        tpl = "/".join(toks[:3])
        templates[tpl] = templates.get(tpl, 0) + 1
        # ⑦ 链合法率（口径优化 2026-08-10）：链相邻对 ∈ 教学链的
        #   比例——自由读的"教学链内行走"纯度（不要求 ∈ 期望 back，
        #   只要求每步都在教学链上）
        for a, b in zip(toks[:-1], toks[1:]):
            n_adj += 1
            if b in teach_out.get(a, set()):
                n_legal += 1
        if not ok_open and len(samples_bad) < 12:
            samples_bad.append((label, first, "/".join(toks[:4])))

    n = len(items)
    report = {
        "version": VER,
        "n_items": n,
        "open_rate": round(n_open_ok / n, 3),
        "chain_rate": round(n_chain_ok / n, 3),
        "sentence_rate": round(n_sent / n, 3),
        "loop_rate": round(n_loop / n, 3),
        "chain_legality": round(n_legal / n_adj, 3) if n_adj else 0,
        "diversity": round(len(templates) / n, 3),
        "n_templates": len(templates),
        "open_types": open_types,
        "top_templates": sorted(templates.items(),
                                key=lambda x: -x[1])[:8],
    }

    # ── 输出 ──────────────────────────────────────────
    print(f"═══ 自然语言质量评估（v{VER}，{n} 题自由读）═══\n")
    print(f"① 开口正确率：{n_open_ok}/{n} = {report['open_rate']:.3f}"
          f"（第 1 跳 ∈ 期望∪关系词）")
    print(f"② 链延续率：  {n_chain_ok}/{n} = {report['chain_rate']:.3f}"
          f"（第 2 跳接得上）")
    print(f"③ 整句率：    {n_sent}/{n} = {report['sentence_rate']:.3f}"
          f"（≥3 跳无循环）")
    print(f"④ 循环率：    {n_loop}/{n} = {report['loop_rate']:.3f}"
          f"（刻板言语指标）")
    print(f"⑦ 链合法率：  {n_legal}/{n_adj} = {report['chain_legality']:.3f}"
          f"（链相邻对 ∈ 教学链——自由读行走纯度）")
    print(f"⑤ 多样性：    {report['n_templates']} 模板 / {n} 题"
          f" = {report['diversity']:.3f}（越接近 1 越多样）")
    print(f"⑥ 开口类型：  内容词 {open_types['content']} · 关系词 "
          f"{open_types['rel']} · 其他 {open_types['other']}")
    print("\n[常见模板（前 8）]：")
    for tpl, c in report["top_templates"]:
        print(f"  {tpl} ×{c}")
    if samples_bad:
        print("\n[开口失败样例]：")
        for label, first, chain in samples_bad:
            print(f"  「{label}」→ {first or '∅'}（{chain}）")

    # ── 留档（固化流程：每次评估自动留档）────────────
    out = RUNS / "_quality" / f"{VER}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"\n[留档] {out}（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
