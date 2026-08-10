# -*- coding: utf-8 -*-
"""并发训练边界探针——图表绘制。

读 runs/_concurrent_boundary.json，生成 2 张图：
  图1：并发量 G vs 成功率 / 最大串扰 / 均激活（同槽 vs 轮转）
  图2：并发量 G vs 学习耗时 / RSS 占用（同槽）
输出：runs/fig_concurrent_boundary_1.png, _2.png
"""
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).parent


def load_data():
    fp = ROOT / "runs" / "_concurrent_boundary.json"
    return json.loads(fp.read_text(encoding="utf-8"))


def series(data, mode, key):
    d = data.get(mode, {})
    gs = sorted(int(g) for g in d)
    return gs, [d[str(g)][key] for g in gs]


def main():
    data = load_data()
    ver = data["version"]
    if not data.get("same_slot"):
        print("[中止] json 无 same_slot 数据（实验未完成）")
        return

    # ── 图1：保真度与稳定性 ──
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))
    fig.suptitle(f"定式网络并发训练边界探针 v{ver}\n"
                 f"（每组 {data['n_rounds']} 轮教学，成功率阈值 {data['success_threshold']}）",
                 fontsize=12, fontweight="bold")

    for ax, key, ylab, ylim in [
        (axes[0], "success_rate", "唤起成功率", (0.9, 1.01)),
        (axes[1], "max_cross", "最大串扰（唤起比例）", (0, 1.0)),
        (axes[2], "mean_scale", "均激活规模（发放神经元数）", None),
    ]:
        for mode, lab, mk in [("same_slot", "同槽 slot=0", "o-"),
                              ("rotated", "轮转 4 槽", "s--")]:
            if not data.get(mode):
                continue
            gs, ys = series(data, mode, key)
            ax.plot(gs, ys, mk, label=lab, lw=1.8)
        ax.set_xlabel("并发组数 G")
        ax.set_ylabel(ylab)
        ax.set_xscale("log", base=2)
        ax.set_xticks([1, 2, 4, 8, 16, 32, 64, 128])
        ax.set_xticklabels([1, 2, 4, 8, 16, 32, 64, 128])
        ax.grid(alpha=0.3)
        if ylim:
            ax.set_ylim(ylim)
        ax.legend(fontsize=9)

    # 崩溃阈值线
    axes[0].axhline(data["success_threshold"], color="red", ls=":", lw=1)
    axes[0].annotate("崩溃阈值", (axes[0].get_xlim()[0], data["success_threshold"]),
                     fontsize=9, color="red", va="bottom")
    plt.tight_layout()
    p1 = ROOT / "runs" / "fig_concurrent_boundary_1.png"
    fig.savefig(p1, dpi=150, bbox_inches="tight")
    print(f"[图1] {p1}")

    # ── 图2：性能与内存 ──
    fig2, axes2 = plt.subplots(1, 3, figsize=(15, 4.4))
    fig2.suptitle(f"并发量 vs 学习耗时 / 内存占用（同槽）v{ver}", fontsize=12, fontweight="bold")

    gs, learn = series(data, "same_slot", "learn_sec")
    axes2[0].plot(gs, learn, "o-", lw=1.8)
    axes2[0].set_xlabel("并发组数 G"); axes2[0].set_ylabel("学习耗时（秒）")
    axes2[0].set_xscale("log", base=2); axes2[0].grid(alpha=0.3)
    axes2[0].set_xticks(gs); axes2[0].set_xticklabels(gs)

    gs2, rss = series(data, "same_slot", "rss_learned_mb")
    axes2[1].plot(gs2, rss, "o-", color="tab:green", lw=1.8, label="学习后 RSS")
    axes2[1].set_xlabel("并发组数 G"); axes2[1].set_ylabel("RSS（MB）")
    axes2[1].set_xscale("log", base=2); axes2[1].grid(alpha=0.3)
    axes2[1].set_xticks(gs2); axes2[1].set_xticklabels(gs2)

    gs3, delta = series(data, "same_slot", "rss_delta_mb")
    axes2[2].plot(gs3, delta, "^--", color="tab:purple", lw=1.8, label="RSS 增量")
    axes2[2].set_xlabel("并发组数 G"); axes2[2].set_ylabel("RSS 增量（MB）")
    axes2[2].set_xscale("log", base=2); axes2[2].grid(alpha=0.3)
    axes2[2].set_xticks(gs3); axes2[2].set_xticklabels(gs3)
    for ax in axes2:
        if ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=9)
    plt.tight_layout()
    p2 = ROOT / "runs" / "fig_concurrent_boundary_2.png"
    fig2.savefig(p2, dpi=150, bbox_inches="tight")
    print(f"[图2] {p2}")


if __name__ == "__main__":
    main()
