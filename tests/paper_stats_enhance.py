# -*- coding: utf-8 -*-
"""论文统计增强：在已有聚合统计基础上补充 95% 置信区间与轨迹动态指标。

内容（不重跑实验，只用已归档数据）：
1. §6.1 四注入格式 Cohen's d 的 95% CI（正态近似，两组 n=100 均衡设计）
2. 各格式 directness 均值 95% CI（mean ± 1.96·sd/√n）
3. 条件 B 六条轨迹的稳态区间：末 40 轮各维 mean±std（>60 轮后），及 60 轮后振幅

用法（项目根目录）：
    python tests/paper_stats_enhance.py

输出：print 即生成论文可直接粘贴的 markdown 表格。
"""
import json
import math
import os

ROOT = r"E:\杂项\BNOS_AI_project"
RUNS = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test", "runs")
FORMAT_AB = os.path.join(RUNS, "20260815_232810_formatAB", "formatAB_results.json")

# 条件 B 六条轨迹（与论文 §6.3/表 4 采用的数据文件一致；
# DeepSeek B2 必须为 194649——192348 为收敛到 0.5 的早期版本，勿用）
TRAJECTORIES = [
    ("DeepSeek", "B2", "20260812_condB_194649", "condB_B2_rounds.json"),
    ("DeepSeek", "B2NEG", "20260812_condB_195954", "condB_B2NEG_rounds.json"),
    ("GLM-5.2", "B2", "20260812_multimodel_201814", "glm5.2_B2_rounds.json"),
    ("GLM-5.2", "B2NEG", "20260812_multimodel_201814", "glm5.2_B2NEG_rounds.json"),
    ("Qwen3.7-max", "B2", "20260812_multimodel_201814", "qwen3.7max_B2_rounds.json"),
    ("Qwen3.7-max", "B2NEG", "20260812_multimodel_201814", "qwen3.7max_B2NEG_rounds.json"),
]
DIMS = ["warmth", "playfulness", "directness", "curiosity"]
Z = 1.959963984540054  # 95% 正态近似


def cohen_d_ci(d, n1, n2):
    """Cohen's d 的 95% CI（正态近似 SE）."""
    se = math.sqrt((n1 + n2) / (n1 * n2) + d * d / (2 * (n1 + n2)))
    return d - Z * se, d + Z * se


def mean_ci(mean, sd, n):
    return mean - Z * sd / math.sqrt(n), mean + Z * sd / math.sqrt(n)


def main():
    print("=" * 78)
    print("A. §6.1 注入格式 2×2 对照：Cohen's d 的 95% CI（正态近似，n=100/组）")
    print("=" * 78)
    data = json.load(open(FORMAT_AB, encoding="utf-8"))
    n1 = n2 = data["repeats"] * data["inputs"]  # 100
    print("\n| 注入格式 | Cohen's d | 95% CI | 跨 0？ |")
    print("|---|---|---|---|")
    for fmt in data["formats"]:
        r = data["results"][fmt]
        d = r["directness_d"]
        lo, hi = cohen_d_ci(d, n1, n2)
        cross = "是" if (lo < 0) != (hi < 0) else ("否（全>0）" if lo > 0 else "否（全<0）")
        print(f"| {fmt} | {d:+.3f} | [{lo:+.3f}, {hi:+.3f}] | {cross} |")

    print("\n" + "=" * 78)
    print("B. 各格式 directness 均值 95% CI（low=0.1 组 / high=0.9 组）")
    print("=" * 78)
    print("\n| 注入格式 | low 均值 (95% CI) | high 均值 (95% CI) | 区间重叠？ |")
    print("|---|---|---|---|")
    for fmt in data["formats"]:
        r = data["results"][fmt]
        lm, ls = r["low_stats"]["directness"]
        hm, hs = r["high_stats"]["directness"]
        l_lo, l_hi = mean_ci(lm, ls, n1)
        h_lo, h_hi = mean_ci(hm, hs, n2)
        overlap = "是" if l_hi > h_lo and h_hi > l_lo else "否"
        print(f"| {fmt} | {lm:.3f} [{l_lo:.3f}, {l_hi:.3f}] | {hm:.3f} [{h_lo:.3f}, {h_hi:.3f}] | {overlap} |")

    print("\n" + "=" * 78)
    print("C. 条件 B 六条轨迹稳态区间（末 25% 轮段 mean±std）与段内振幅")
    print("=" * 78)
    for model, cond, run, fname in TRAJECTORIES:
        with open(os.path.join(RUNS, run, fname), encoding="utf-8") as f:
            data = json.load(f)
        log = [r for r in data["log"] if r.get("vector")]  # Qwen B2 末 5 条缺 vector
        n = len(log)
        tail = log[-max(1, n // 4):]
        amp = {}
        for d in DIMS:
            vals = [v["vector"][d] for v in tail]
            m = sum(vals) / len(vals)
            sd = math.sqrt(sum((x - m) ** 2 for x in vals) / (len(vals) - 1)) if len(vals) > 1 else 0.0
            amp[d] = (m, sd)
        span = {}
        for d in DIMS:
            vals = [v["vector"][d] for v in tail]
            span[d] = max(vals) - min(vals) if vals else float("nan")
        rng = f"r{tail[0]['round']}~r{tail[-1]['round']}"
        mstr = "  ".join(f"{d[:4]}={m:.3f}±{s:.3f}" for d, (m, s) in amp.items())
        sstr = "  ".join(f"{d[:4]}={s:.3f}" for d, s in span.items())
        print(f"\n{model:12s} {cond:5s} 总{n}轮 末25%({rng}): {mstr}")
        print(f"            段内振幅: {sstr}")


if __name__ == "__main__":
    main()
