# -*- coding: utf-8 -*-
"""第六波推理优化图表：逐步优化曲线 + edge_min 参数扫描（数据留档）。"""
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sysp = Path(__file__).parent
plt.rcParams.update({"font.family": "Microsoft YaHei", "font.size": 10,
                     "axes.unicode_minus": False})

data = json.loads((sysp / "runs" / "_infer_bench.json").read_text(encoding="utf-8"))
scan = json.loads((sysp / "runs" / "_edge_min_scan.json").read_text(encoding="utf-8"))

STEPS = [("baseline", "基线\n（第五波后）"), ("step1_pre_trace", "Step1\n痕迹就地"),
         ("step2_fire_idx", "Step2\n分桶免扫"), ("step3_spikes_buf", "Step3\n发放缓冲"),
         ("step4_localize", "Step4\n属性局部化")]
labels = [s[1] for s in STEPS]
vals = [data[k]["evoke"]["min_ms"] for k, _ in STEPS]
hits = [data[k]["hit"]["rate"] for k, _ in STEPS]

fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))

# ── 图1：逐步优化曲线 ──
ax = axes[0]
bars = ax.bar(labels, vals, color="#4C72B0", width=0.62)
for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.5, f"{v:.1f}", ha="center", fontsize=9)
ax.set_ylabel("唤起耗时（ms/次，3 步，取最快）")
ax.set_title("逐步优化：唤起耗时（基线 35.2 → 25.6，-27%）")
ax.set_ylim(0, 42)
ax2 = axes[0].twinx()
ax2.plot(labels, hits, "o-", color="#C44E52", lw=1.5)
ax2.set_ylabel("强边命中率", color="#C44E52")
ax2.tick_params(axis="y", labelcolor="#C44E52")
ax2.set_ylim(0, 0.2)
for i, h in enumerate(hits):
    ax2.annotate(f"{h:.3f}", (i, h), textcoords="offset points", xytext=(0, 6),
                 ha="center", fontsize=8, color="#C44E52")

# ── 图2：单步构成对比（基线 vs Step4）──
ax = axes[1]
comps = ["prop", "noise", "topk", "wta", "where", "collect"]
base_c = [data["baseline"]["profile"][c] for c in comps]
step_c = [data["step4_localize"]["profile"][c] for c in comps]
x = np.arange(len(comps))
w = 0.36
b1 = ax.bar(x - w / 2, base_c, w, label="基线", color="#DD8452")
b2 = ax.bar(x + w / 2, step_c, w, label="Step4 后", color="#4C72B0")
for b in list(b1) + list(b2):
    ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.05,
            f"{b.get_height():.2f}", ha="center", fontsize=8)
ax.set_xticks(x)
ax.set_xticklabels([{"prop": "传播", "noise": "噪声+衰减", "topk": "WTA排序",
                     "wta": "候选收集", "where": "槽分桶", "collect": "边收集"}[c] for c in comps])
ax.set_ylabel("ms/步")
ax.set_title("单步构成对比（计时段）")
ax.legend()

# ── 图3：edge_min 参数扫描 ──
ax = axes[2]
ems = list(scan.keys())
ev = [scan[e]["evoke_ms"] for e in ems]
ht = [scan[e]["hit"] for e in ems]
bars = ax.bar(ems, ev, color="#55A868", width=0.55)
for b, v in zip(bars, ev):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.5, f"{v:.1f}", ha="center", fontsize=9)
ax.set_xlabel("edge_min（弱边修剪阈值）")
ax.set_ylabel("唤起耗时（ms/次）")
ax.set_title("edge_min 参数扫描：速度与命中率")
ax.set_ylim(0, 42)
ax3 = ax.twinx()
ax3.plot(ems, ht, "o-", color="#C44E52", lw=1.5)
ax3.set_ylabel("强边命中率", color="#C44E52")
ax3.tick_params(axis="y", labelcolor="#C44E52")
ax3.set_ylim(0, 0.2)
for i, h in enumerate(ht):
    ax3.annotate(f"{h:.3f}", (i, h), textcoords="offset points", xytext=(0, 6),
                 ha="center", fontsize=8, color="#C44E52")

plt.tight_layout()
out = sysp / "runs" / "fig_infer_opt.png"
plt.savefig(out, dpi=130)
print(f"[图] {out}")
