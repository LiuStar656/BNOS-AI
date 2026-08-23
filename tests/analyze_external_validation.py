# -*- coding: utf-8 -*-
"""外部效标验证结果分析：观测投影 vs 裁判评分一致性

输出：
- 逐维 Spearman 相关（obs vs judge）
- 裁判分按条件分组（B2 vs B2NEG）对比：warmth/directness 方向性
- 跨模型一致性
"""
import json
import glob
import os

DIMS = ["warmth", "playfulness", "directness", "curiosity"]


def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    def rank(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return float("nan")
    return cov / (vx * vy) ** 0.5


def main():
    latest = sorted(glob.glob(os.path.join(
        "docs", "experiments", "cognitive_evolution_test", "runs", "*_extval", "extval_results.json")))[-1]
    results = json.load(open(latest, encoding="utf-8"))
    print(f"样本：{len(results)}（{latest}）\n")

    # 1) 逐维 Spearman：obs vs judge
    print("=" * 70)
    print("1. 逐维 Spearman 相关（观测投影 obs vs 裁判分）")
    print("=" * 70)
    for d in DIMS:
        rho = spearman([s["obs"][d] for s in results], [s["judge"][d] for s in results])
        print(f"  {d:12s} rho = {rho:+.3f}")
    print()

    # 2) 裁判分按条件分组对比（跨模型合并）
    print("=" * 70)
    print("2. 裁判分：B2（跟随） vs B2NEG（背离），跨模型合并")
    print("=" * 70)
    for d in DIMS:
        b2 = [s["judge"][d] for s in results if s["cond"] == "B2"]
        neg = [s["judge"][d] for s in results if s["cond"] == "B2NEG"]
        mb2, mneg = sum(b2) / len(b2), sum(neg) / len(neg)
        print(f"  {d:12s} B2={mb2:.3f}  B2NEG={mneg:.3f}  Δ={mb2 - mneg:+.3f}  "
              f"(方向预期: {'B2>NEG' if d in ('warmth', 'playfulness', 'curiosity') else 'B2<NEG'})")
    print()

    # 3) 分模型 warmth/directness 方向
    print("=" * 70)
    print("3. 分模型：裁判 warmth / directness 按条件")
    print("=" * 70)
    for model in ["DeepSeek", "GLM-5.2", "Qwen3.7-max"]:
        row = [s for s in results if s["model"] == model]
        b2 = [s for s in row if s["cond"] == "B2"]
        neg = [s for s in row if s["cond"] == "B2NEG"]
        w_b2 = sum(s["judge"]["warmth"] for s in b2) / len(b2)
        w_neg = sum(s["judge"]["warmth"] for s in neg) / len(neg)
        d_b2 = sum(s["judge"]["directness"] for s in b2) / len(b2)
        d_neg = sum(s["judge"]["directness"] for s in neg) / len(neg)
        print(f"  {model:12s} warmth B2={w_b2:.3f} NEG={w_neg:.3f} (Δ={w_b2 - w_neg:+.3f})   "
              f"directness B2={d_b2:.3f} NEG={d_neg:.3f} (Δ={d_b2 - d_neg:+.3f})")
    print()

    # 4) 长度/投入度分析：裁判分是否由回复长度（投入度线索）中介
    print("=" * 70)
    print("4. 回复长度（投入度）：条件间对比 + 裁判分 vs 长度 Spearman")
    print("=" * 70)
    for s in results:
        s["_len"] = len(s.get("reply") or "")
    b2l = [s["_len"] for s in results if s["cond"] == "B2"]
    negl = [s["_len"] for s in results if s["cond"] == "B2NEG"]
    print(f"  B2   : n={len(b2l)} 平均 {sum(b2l)/len(b2l):.0f} 字符  中位 {sorted(b2l)[len(b2l)//2]}  min={min(b2l)} max={max(b2l)}")
    print(f"  B2NEG: n={len(negl)} 平均 {sum(negl)/len(negl):.0f} 字符  中位 {sorted(negl)[len(negl)//2]}  min={min(negl)} max={max(negl)}")
    L = [s["_len"] for s in results]
    for d in DIMS:
        rho = spearman([s["judge"][d] for s in results], L)
        print(f"  裁判 {d:12s} vs 长度 rho = {rho:+.3f}")


if __name__ == "__main__":
    main()
