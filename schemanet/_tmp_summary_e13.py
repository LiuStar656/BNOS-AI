# -*- coding: utf-8 -*-
"""E1-E3 汇总：5 seeds top1/ppl mean±std + 配对检验 + E3 基线（seed42 完整版）。
只汇总 paper_2026* 留档；每 seed 取最新（075545 早期版缺 ppl，跳过）。"""
import glob
import json
from pathlib import Path

import numpy as np

rows = []
for p in sorted(glob.glob("runs/paper_2026*/result.json")):
    d = json.loads(Path(p).read_text(encoding="utf-8"))
    if "top1" not in d:
        continue
    rows.append(d)
by_seed = {}
for d in rows:
    by_seed.setdefault(d["seed"], []).append(d)
sel = {s: sorted(v, key=lambda r: r.get("elapsed_sec", 0))[-1] for s, v in by_seed.items()}
seeds = sorted(sel)
print(f"留档 {len(rows)} 个 → 按 seed 去重取最新 {len(sel)} 个: {seeds}")

print("\n=== E1 top-1（test，mean±std）===")
e1 = {}
for k in ("wsum", "trace", "grad"):
    vals = np.array([sel[s]["top1"][k]["test"] for s in seeds])
    e1[k] = vals
    print(f"  {k:6s}: {vals.mean():.4f} ± {vals.std(ddof=1):.4f}  {[round(x, 4) for x in vals.tolist()]}")

print("\n=== E2 PPL（test）===")
e2 = {}
for k in ("wsum", "trace", "grad"):
    for sub in ("all", "no_unk"):
        vals = np.array([sel[s]["ppl"][k][sub] for s in seeds])
        e2[f"{k}_{sub}"] = vals
        print(f"  {k:6s} {sub:7s}: {vals.mean():.1f} ± {vals.std(ddof=1):.1f}")

print("\n=== 配对检验（test top-1）===")
n = int(np.mean([sel[s]["top1"]["eval_n"]["test"] for s in seeds]))
for a, b in (("trace", "wsum"), ("grad", "wsum"), ("grad", "trace")):
    da = float(e1[a].mean() - e1[b].mean())
    p_avg = (float(e1[a].mean()) + float(e1[b].mean())) / 2
    se = np.sqrt(2 * p_avg * (1 - p_avg) / n) if 0 < p_avg < 1 else 1e-9
    z = da / se if se > 0 else float("nan")
    print(f"  {a} - {b}: Δ={da:+.4f}  z={z:+.2f}  (n={n})")

print("\n=== E3 基线（seed42 完整版同词表同划分）===")
b42 = sel[42].get("baselines", {})
for k in ("bigram_top1", "trigram_top1", "kn_top1", "lstm_top1",
          "bigram_ppl_all", "trigram_ppl_all", "kn_ppl_all", "lstm_ppl_all"):
    print(f"  {k}: {b42.get(k, 'N/A')}")

# 汇总表输出 JSON
summary = {
    "E1_top1_test": {k: {"mean": round(float(e1[k].mean()), 4),
                         "std": round(float(e1[k].std(ddof=1)), 4),
                         "vals": [round(float(x), 4) for x in e1[k].tolist()]}
                    for k in e1},
    "E2_ppl": {k: {"mean": round(float(v.mean()), 1),
                   "std": round(float(v.std(ddof=1)), 1)} for k, v in e2.items()},
    "E3_baselines": b42,
    "seeds": seeds, "eval_n_test": n,
}
(out_p := Path("runs") / "paper_e13_summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n汇总表留档: {out_p}")
