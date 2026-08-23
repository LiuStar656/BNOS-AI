# -*- coding: utf-8 -*-
"""生成论文附录 E 抽样表（每轨迹首/中/末）与条件对比表数据。"""
import json
from collections import OrderedDict

P = r"docs\experiments\cognitive_evolution_test\runs\20260816_015735_extval\extval_results.json"
R = json.load(open(P, encoding="utf-8"))

G = OrderedDict()
for s in R:
    G.setdefault((s["model"], s["cond"]), []).append(s)

print("=== E.4 抽样：每轨迹 首/中/末 ===")
for k, v in G.items():
    v.sort(key=lambda s: s["round"])
    idx = [0, len(v) // 2, len(v) - 1]
    for i in idx:
        s = v[i]
        j = s["judge"]
        print(f"| {s['model']} | {s['cond']} | {s['round']} | {j['warmth']:.2f} | {j['playfulness']:.2f} | {j['directness']:.2f} | {j['curiosity']:.2f} |")

print("\n=== 各轨迹样本数 ===")
for k, v in G.items():
    print(f"{k[0]:12s} {k[1]:5s} n={len(v)}")

print("\n=== E.2 条件对比（跨模型合并）===")
DIMS = ["warmth", "playfulness", "directness", "curiosity"]
for d in DIMS:
    b2 = [s["judge"][d] for s in R if s["cond"] == "B2"]
    neg = [s["judge"][d] for s in R if s["cond"] == "B2NEG"]
    mb2, mneg = sum(b2) / len(b2), sum(neg) / len(neg)
    print(f"| {d} | {mb2:.3f} | {mneg:.3f} | {mb2 - mneg:+.3f} |")

print("\n=== E.3 分模型 warmth/directness ===")
for model in ["DeepSeek", "GLM-5.2", "Qwen3.7-max"]:
    row = [s for s in R if s["model"] == model]
    b2 = [s for s in row if s["cond"] == "B2"]
    neg = [s for s in row if s["cond"] == "B2NEG"]
    wb = sum(s["judge"]["warmth"] for s in b2) / len(b2)
    wn = sum(s["judge"]["warmth"] for s in neg) / len(neg)
    db = sum(s["judge"]["directness"] for s in b2) / len(b2)
    dn = sum(s["judge"]["directness"] for s in neg) / len(neg)
    print(f"| {model} | {wb:.3f} | {wn:.3f} | {wb - wn:+.3f} | {db:.3f} | {dn:.3f} | {db - dn:+.3f} |")
