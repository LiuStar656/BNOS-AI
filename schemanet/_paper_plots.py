# -*- coding: utf-8 -*-
"""投稿补全实验汇总图表：
  图1 E6：奖惩三组行为频率（f16/f12/f8/f4）+ 泛化梯度
  图2 E1-E3：SchemaNet 三路 top-1 vs 外部基线
  图3 E1-E3：PPL 对比（log 轴）
  图4 E5：纯动力学回响 vs 代码层读出
输出：runs/fig_e6_behavior.png, fig_e13_top1.png, fig_e13_ppl.png, fig_e5_outsourcing.png
数据：runs/paper_e6_*/result.json（最新）、runs/paper_e13_summary.json、runs/paper_e5_*/result.json（最新）
"""
import glob
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"


def newest(pattern):
    files = sorted(glob.glob(str(RUNS / pattern)), key=lambda p: Path(p).stat().st_mtime)
    return json.loads(Path(files[-1]).read_text(encoding="utf-8")) if files else None


# ── 图1：E6 三组行为频率 ──
d6 = newest("paper_e6_*/result.json")
if d6:
    modes = {m: d6["summary"]["modes"][m] for m in ("reward", "neutral", "punish")}
    ks = ("16", "12", "8", "4")
    colors = {"reward": "#d9534f", "neutral": "#7f7f7f", "punish": "#5cb85c"}
    x = np.arange(len(ks))
    w = 0.25
    fig, ax = plt.subplots(figsize=(8, 5))
    for i, m in enumerate(("reward", "neutral", "punish")):
        means = [modes[m]["f_test"][k][0] for k in ks]
        errs = [modes[m]["f_test"][k][1] for k in ks]
        ax.bar(x + (i - 1) * w, means, w, yerr=errs, capsize=3,
               label={"reward": "奖励", "neutral": "中性", "punish": "惩罚"}[m],
               color=colors[m], alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(["k=16 (原X)", "k=12", "k=8", "k=4"])
    ax.set_ylim(0, 115)
    ax.set_ylabel("行为频率（%，mean±std, n=5 seeds）")
    ax.set_xlabel("输入相似度（保留 X 神经元数）")
    ax.set_title("E6 混沌环境中奖惩对行为频率的定向调节（R-STDP Δw=DA×e）")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(RUNS / "fig_e6_behavior.png", dpi=150)
    plt.close(fig)
    print("fig_e6_behavior.png 已生成")

# ── 图2：E1-E3 top-1 vs 基线 ──
s13 = json.loads((RUNS / "paper_e13_summary.json").read_text(encoding="utf-8"))
methods = ["wsum", "trace", "grad"]
m_labels = {"wsum": "SchemaNet wsum", "trace": "SchemaNet trace", "grad": "SchemaNet grad"}
bl_keys = {"bigram": "bigram_top1", "trigram": "trigram_top1", "kn": "kn_top1", "lstm": "lstm_top1"}
bl_labels = {"bigram": "Bigram", "trigram": "Trigram", "kn": "Kneser-Ney", "lstm": "LSTM"}
means = [s13["E1_top1_test"][m]["mean"] for m in methods]
stds = [s13["E1_top1_test"][m]["std"] for m in methods]
bl_means = [s13["E3_baselines"][bl_keys[k]] for k in bl_keys]
all_lab = [m_labels[m] for m in methods] + [bl_labels[k] for k in bl_keys]
all_means = means + bl_means
all_stds = stds + [0.0] * 4
fig, ax = plt.subplots(figsize=(9, 5))
cols = ["#5b9bd5"] * 3 + ["#ed7d31"] * 4
bars = ax.bar(range(len(all_means)), all_means, yerr=all_stds, capsize=3,
              color=cols, alpha=0.9)
ax.set_xticks(range(len(all_means)))
ax.set_xticklabels(all_lab, rotation=20, ha="right")
ax.set_ylabel("top-1 准确率（test，mean±std, n=5 seeds）")
ax.set_title("E1-E3：SchemaNet 三路 vs 外部基线（corpus_open，同词表同划分）")
for i, v in enumerate(all_means):
    ax.text(i, v + 0.005, f"{v:.3f}", ha="center", fontsize=8)
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(RUNS / "fig_e13_top1.png", dpi=150)
plt.close(fig)
print("fig_e13_top1.png 已生成")

# ── 图3：E1-E3 PPL（log 轴）──
ppl_vals = [s13["E2_ppl"]["wsum_all"]["mean"], s13["E2_ppl"]["trace_all"]["mean"],
            s13["E2_ppl"]["grad_all"]["mean"]]
bl_ppl = {"bigram": "bigram_ppl_all", "trigram": "trigram_ppl_all",
          "kn": "kn_ppl_all", "lstm": "lstm_ppl_all"}
bl_ppl_vals = [s13["E3_baselines"][bl_ppl[k]] for k in bl_ppl]
all_ppl_lab = [m_labels[m] for m in methods] + [bl_labels[k] for k in bl_ppl]
all_ppl = ppl_vals + bl_ppl_vals
fig, ax = plt.subplots(figsize=(9, 5))
bars = ax.bar(range(len(all_ppl)), all_ppl, color=cols, alpha=0.9)
ax.set_yscale("log")
ax.set_xticks(range(len(all_ppl)))
ax.set_xticklabels(all_ppl_lab, rotation=20, ha="right")
ax.set_ylabel("PPL（test，log 轴，越低越好）")
ax.set_title("E2-E3：SchemaNet 三路 vs 外部基线 困惑度（corpus_open）")
for i, v in enumerate(all_ppl):
    ax.text(i, v * 1.15, f"{v:,.0f}", ha="center", fontsize=8)
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(RUNS / "fig_e13_ppl.png", dpi=150)
plt.close(fig)
print("fig_e13_ppl.png 已生成")

# ── 图4：E5 能力外置 ──
d5 = newest("paper_e5_*/result.json")
if d5:
    dyn = d5["dynamics"]
    cod = d5["code_layer"]
    labels = ["纯动力学回响\n(top-1 hard)", "动力学\n(recall@4)", "代码层读出\n(wsum top-1)"]
    vals = [dyn["top1_hard_parse"], dyn["recall"], cod["wsum_top1"]]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar(range(3), vals, color=["#5b9bd5", "#5b9bd5", "#ed7d31"], alpha=0.9)
    ax.set_xticks(range(3))
    ax.set_xticklabels(labels)
    ax.set_ylabel("指标值（seed=42）")
    ax.set_title(f"E5 能力外置对照：动力学回响 vs 代码层读出\n"
                 f"外置增益 = {cod['outsourcing_gain']:+.4f}（负=未带来增益）")
    for i, v in enumerate(vals):
        ax.text(i, v + 0.005, f"{v:.4f}", ha="center", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(RUNS / "fig_e5_outsourcing.png", dpi=150)
    plt.close(fig)
    print("fig_e5_outsourcing.png 已生成")

# ── 图5：E4 PTB 标准数据集对比 ──
d4 = newest("paper_ptb_*/result.json")
if d4:
    methods4 = ["wsum", "trace", "grad"]
    m4_labels = {"wsum": "SchemaNet wsum", "trace": "SchemaNet trace", "grad": "SchemaNet grad"}
    bl4_keys = {"bigram": "bigram_top1", "trigram": "trigram_top1",
                "kn": "kn_top1", "lstm": "lstm_top1"}
    bl4_ppl = {"bigram": "bigram_ppl_all", "trigram": "trigram_ppl_all",
               "kn": "kn_ppl_all", "lstm": "lstm_ppl_all"}
    top4 = [d4["top1"][m] for m in methods4]
    ppl4 = [d4["ppl"][m]["all"] for m in methods4]
    bl4_top = [d4["baselines"][bl4_keys[k]] for k in bl4_keys]
    bl4_ppl_vals = [d4["baselines"][bl4_ppl[k]] for k in bl4_ppl]
    all_lab4 = [m4_labels[m] for m in methods4] + [bl_labels[k] for k in bl4_keys]
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6))
    a = axes[0]
    a.bar(range(7), top4 + bl4_top, color=cols, alpha=0.9)
    a.set_xticks(range(7)); a.set_xticklabels(all_lab4, rotation=20, ha="right")
    a.set_ylabel("top-1（test, seed=42）")
    a.set_title("E4 PTB：SchemaNet 三路 vs 基线 top-1")
    for i, v in enumerate(top4 + bl4_top):
        a.text(i, v + 0.005, f"{v:.3f}", ha="center", fontsize=8)
    a.grid(axis="y", alpha=0.3)
    b = axes[1]
    all_ppl4 = ppl4 + bl4_ppl_vals
    b.bar(range(7), all_ppl4, color=cols, alpha=0.9)
    b.set_yscale("log")
    b.set_xticks(range(7)); b.set_xticklabels(all_lab4, rotation=20, ha="right")
    b.set_ylabel("PPL（log 轴，越低越好）")
    b.set_title("E4 PTB：困惑度对比")
    for i, v in enumerate(all_ppl4):
        b.text(i, v * 1.15, f"{v:,.0f}", ha="center", fontsize=8)
    b.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(RUNS / "fig_e4_ptb.png", dpi=150)
    plt.close(fig)
    print("fig_e4_ptb.png 已生成")

print("全部图表完成 →", RUNS)
