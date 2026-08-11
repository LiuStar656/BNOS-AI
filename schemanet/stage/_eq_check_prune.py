# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""v34 ↔ v35 剪枝行为等价性严格比对（2026-08-11）。

背景：v35 = v34 执行 sleep_consolidate(min_wake=5, decay=0.3, eps=1.0)
剪枝沉淀（98% 边被删，151MB→2.2MB），meta 声称"能力等价"。本脚本
对两版本做**行为级**逐条对拍：

  ① 结构正确性：v35 每条边必须存在于 v34，且强度一致（抽样 20 万条）
  ② 读边层：edge_between 采样词对数值对比
  ③ 读出层：direct_next_multi top-8 候选/排序/权重对比
  ④ 行为层：free_read 域内自由读泛化题输出链逐词对比
  ⑤ 注册表：consolidated / validation 两版本一致性

判定：free_read 输出链相同 + direct_next 候选集合/顺序相同 → 行为等价；
edge_between/权重允许数值差异但不得改变 top-k 排序。

用法：python _eq_check_prune.py
留档：runs/_eq_check_prune_{ts}/result.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snapshot import load_version, load_consolidated
from _exam_free import free_read, build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats
from _grow_v16 import direct_next_multi, edge_between

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
VERS = ("34.0", "35.0")

# 读边采样词对（感受链 + 教学链 + 泛化链；全单词，无多词短语）
EDGE_PAIRS = [
    ("饿", "吃"), ("渴", "喝"), ("累", "休息"), ("冷", "穿"), ("困", "睡"),
    ("饿", "了"), ("渴", "了"), ("累", "了"), ("冷", "了"), ("困", "了"),
    ("吃", "饭"), ("喝", "水"), ("穿", "衣服"), ("睡", "觉"),
    ("我", "饿"), ("我", "累"), ("我", "渴"), ("我", "冷"), ("我", "困"),
    ("所以", "饿"), ("所以", "累"), ("但是", "我"), ("然后", "我"),
    ("疼", "不要"), ("饿", "怎么办"), ("冷", "怎么办"), ("累", "怎么办"),
    ("猫", "睡觉"), ("狗", "喝水"),
]

DECAY = 0.3  # sleep 低频槽衰减因子（×0.7）

# 读出层关键词
NEXT_WORDS = ["饿", "渴", "累", "冷", "困", "穿", "我", "所以", "但是", "猫"]

# 行为层泛化题（与 _bench_prune 同源，追加复合题）
READ_ITEMS = [
    ("饿", "确认"), ("渴", "确认"), ("累", "确认"), ("困", "确认"),
    ("冷", "确认"), ("穿", "确认"),
    ("饿", "怎么办"), ("渴", "怎么办"), ("累", "怎么办"), ("冷", "怎么办"),
    ("困", "怎么办"), ("疼", "怎么办"),
]


def build_env(ver):
    ng, vocab, pats, cursor = load_version(ver)
    cons, val = load_consolidated(ver)
    n2w = {j: w for w, ns in pats.items() for j in ns}
    return dict(ng=ng, pats=pats, n2w=n2w, cons=cons, val=val)


def tok_of(t):
    """free_read 输出项 '我(1024)' → (词, 权重)"""
    if "(" not in t:
        return t, None
    w, v = t.rsplit("(", 1)
    return w, float(v.rstrip(")"))


def main():
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))

    envs = {}
    for ver in VERS:
        t0 = time.perf_counter()
        e = build_env(ver)
        cats = build_cats(e["pats"], sem["words"], 12, 3)
        q_pool = qa_build_pool(rows, cats)
        e["domain"] = build_domain(e["ng"], e["pats"], rows, q_pool)
        e["teach_out"] = build_teach_out(rows, q_pool)
        e["q_pool"] = q_pool
        e["load_s"] = time.perf_counter() - t0
        envs[ver] = e
        print(f"[加载] v{ver} {e['load_s']:.1f}s  边="
              f"{sum(len(e['ng'].W_out[i][0]) for i in range(e['ng'].n)):,}")

    A, B = envs["34.0"], envs["35.0"]
    rep = {"meta": {"ts": time.strftime("%Y%m%d_%H%M%S"),
                    "prune": "sleep(min_wake=5, decay=0.3, eps=1.0)"},
           "load_s": {"v34": A["load_s"], "v35": B["load_s"]},
           "sections": {}}

    # ── ① 结构正确性：v35 边 ⊆ v34；强度比 ∈ {1.0（高频槽保留）, 0.7（低频衰减）} ──
    ngA, ngB = A["ng"], B["ng"]
    sa, sb = ngA.W_out, ngB.W_out
    E_A = sum(len(r[0]) for r in sa)
    E_B = sum(len(r[0]) for r in sb)
    rng = np.random.default_rng(20260811)
    n_smp = 200000
    cnt_exist, ratio_ok, miss, ratios = 0, 0, [], []
    # v35 全边索引数组（src_i/slot_k/dst_j/vals 与 .items() 等价）
    for i in range(ngB.n):
        row = sb[i][0]
        if not row:
            continue
        n_i = len(row.dst)
        take = rng.integers(0, n_i, size=min(n_i, 3))  # 每行最多抽 3 条
        for idx in take:
            j = int(row.dst[idx])
            w = float(row.w[idx])
            rowA = sa[i][0]
            wa = rowA.get(j, 0.0) if rowA else 0.0
            if wa == 0.0:
                miss.append((i, j, w))
            else:
                cnt_exist += 1
                r = w / wa
                ratios.append(r)
                if abs(r - 1.0) < 1e-6 or abs(r - (1 - DECAY)) < 1e-6:
                    ratio_ok += 1
                elif len(miss) < 5:
                    miss.append(("ratio", i, j, wa, w))
    total_smp = cnt_exist + len(miss)
    import collections
    r_hist = collections.Counter()
    for r in ratios:
        r_hist[round(r, 2)] += 1
    sec1 = {
        "E_v34": E_A, "E_v35": E_B, "prune_rate": 1 - E_B / E_A,
        "sampled": total_smp, "exists_in_v34": cnt_exist,
        "ratio_ok": ratio_ok,
        "ratio_hist_top": r_hist.most_common(6),
        "miss_samples": miss[:5],
    }
    rep["sections"]["1_structure"] = sec1
    print(f"\n═══ ① 结构正确性（v35 边 ⊆ v34，强度比 ∈ {{1.0, {1-DECAY:.1f}}}）═══")
    print(f"  E v34={E_A:,} → v35={E_B:,}（剪枝率 {1-E_B/E_A:.1%}）")
    print(f"  抽样 {total_smp:,} 条：存在于 v34 = {cnt_exist:,} "
          f"（{cnt_exist/total_smp:.2%}），强度比合规 = {ratio_ok:,}")
    print(f"  强度比分布: {dict(r_hist.most_common(6))}")
    if miss:
        print(f"  异常样例: {miss[:3]}")

    # ── ② 读边层：edge_between 数值对比（合规比 ∈ {0.7 衰减, 1.0 保留}）──
    sec2 = {"pairs": []}
    n_diff = 0
    print(f"\n═══ ② edge_between 采样 {len(EDGE_PAIRS)} 对（合规比 {1-DECAY}/1.0）═══")
    for s, d in EDGE_PAIRS:
        if s not in A["pats"] or d not in A["pats"]:
            sec2["pairs"].append({"s": s, "d": d, "skip": "词不在 pats"})
            print(f"  [SKIP] {s}→{d}（词不在 pats）")
            continue
        va = edge_between(ngA, A["pats"], s, d)
        vb = edge_between(ngB, B["pats"], s, d)
        if va > 0 and vb > 0:
            r = vb / va
            ok = abs(r - (1 - DECAY)) < 1e-6 or abs(r - 1.0) < 1e-6
            tag = f"×{r:.3f}"
        elif va == 0 and vb == 0:
            ok, r, tag = True, None, "双边 0（词对无边）"
        elif va > 0 and vb == 0:
            ok, r, tag = False, 0.0, "v34 有边 v35 被删（>eps 误删？）"
        else:
            ok, r, tag = False, None, "v34 无边 v35 出现（新增？）"
        n_diff += 0 if ok else 1
        sec2["pairs"].append({"s": s, "d": d, "v34": va, "v35": vb,
                              "ratio": r, "ok": ok})
        if not ok:
            print(f"  [DIFF] {s}→{d}: {va:.2f} vs {vb:.2f}（{tag}）")
    sec2["diff_count"] = n_diff
    rep["sections"]["2_edge"] = sec2
    print(f"  差异 {n_diff}/{len(EDGE_PAIRS)}")

    # ── ③ 读出层：direct_next_multi top-8 对比 ──
    sec3 = {"words": []}
    n_diff3 = 0
    print(f"\n═══ ③ direct_next_multi top-8（{len(NEXT_WORDS)} 词）═══")
    domA, domB = A["domain"], B["domain"]
    for w in NEXT_WORDS:
        ta = direct_next_multi(ngA, A["pats"], A["n2w"], [w], k=8, domain=domA)
        tb = direct_next_multi(ngB, B["pats"], B["n2w"], [w], k=8, domain=domB)
        wa = [x for x, _ in ta]
        wb = [x for x, _ in tb]
        same = (wa == wb)
        n_diff3 += 0 if same else 1
        sec3["words"].append({"w": w, "top8_v34": wa, "top8_v35": wb,
                              "same": same})
        if not same:
            print(f"  [DIFF] {w}: v34={wa[:5]}…  v35={wb[:5]}…")
    sec3["diff_count"] = n_diff3
    rep["sections"]["3_next"] = sec3
    print(f"  差异 {n_diff3}/{len(NEXT_WORDS)}")

    # ── ④ 行为层：free_read 泛化题全链对比 ──
    sec4 = {"items": []}
    n_diff4 = 0
    print(f"\n═══ ④ free_read 域内自由读（{len(READ_ITEMS)} 题）═══")
    for kw, ctx in READ_ITEMS:
        ra = free_read(ngA, A["pats"], A["n2w"], [kw], A["domain"],
                       teach_out=A["teach_out"], consolidated=A["cons"],
                       validation=A["val"], ctx=ctx)
        rb = free_read(ngB, B["pats"], B["n2w"], [kw], B["domain"],
                       teach_out=B["teach_out"], consolidated=B["cons"],
                       validation=B["val"], ctx=ctx)
        ta = [tok_of(x)[0] for x in ra]
        tb = [tok_of(x)[0] for x in rb]
        same = (ta == tb)
        n_diff4 += 0 if same else 1
        sec4["items"].append({"kw": kw, "ctx": ctx, "v34": ta, "v35": tb,
                              "same": same})
        mark = "OK " if same else "DIFF"
        print(f"  [{mark}] {kw}/{ctx}: v34={'/'.join(ta) or '∅'}  "
              f"v35={'/'.join(tb) or '∅'}")
    sec4["diff_count"] = n_diff4
    rep["sections"]["4_read"] = sec4
    print(f"  差异 {n_diff4}/{len(READ_ITEMS)}")

    # ── ⑤ 注册表：consolidated / validation 一致性 ──
    ca, cb = A["cons"], B["cons"]
    va_, vb_ = A["val"], B["val"]
    same_cons = (ca == cb)
    same_val = (va_ == vb_)
    sec5 = {"cons_same": same_cons, "val_same": same_val,
            "cons_n": (len(ca), len(cb)), "val_n": (len(va_), len(vb_))}
    rep["sections"]["5_registry"] = sec5
    print(f"\n═══ ⑤ 注册表一致性 ═══")
    print(f"  consolidated: {len(ca)} vs {len(cb)}  {'相同' if same_cons else 'DIFF'}")
    print(f"  validation:   {len(va_)} vs {len(vb_)}  {'相同' if same_val else 'DIFF'}")

    # ── 汇总 ──
    d2 = sec2["diff_count"]
    d3 = sec3["diff_count"]
    d4 = sec4["diff_count"]
    verdict = "行为等价" if (d3 == 0 and d4 == 0) else "存在行为差异"
    sec_sum = {
        "edge_diff": d2, "next_diff": d3, "read_diff": d4,
        "structure_pass": len(miss) == 0,
        "registry_same": same_cons and same_val,
        "verdict": verdict,
    }
    rep["sections"]["summary"] = sec_sum
    print(f"\n═══ 汇总 ═══")
    print(f"  结构: {'PASS' if len(miss)==0 else 'FAIL'}（缺失/异常 {len(miss)} 条）")
    print(f"  读边(数值): {d2}/{len(EDGE_PAIRS)} 差异 | 读出(top-k): "
          f"{d3}/{len(NEXT_WORDS)} 差异 | 行为(free_read): {d4}/{len(READ_ITEMS)} 差异")
    print(f"  注册表: {'一致' if same_cons and same_val else 'DIFF'}")
    print(f"  结论: {verdict}")

    # ── 留档 ──
    out = Path(__file__).resolve().parent.parent / "runs" / f"_eq_check_prune_{time.strftime('%Y%m%d_%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {out}")


if __name__ == "__main__":
    main()
