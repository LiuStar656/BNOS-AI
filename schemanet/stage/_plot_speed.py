# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""速度基准画图：训练/推理速度随训练语句量 N 的对照曲线。

数据源：runs/_speed_bench.json（_probe_speed.py 产出）
输出：runs/fig_speed_bench.png（3 子图）：
  - 子图1：每教学秒 vs N（固定开销=平线；随结构退化=爬升）
  - 子图2：唤起毫秒/次 vs N（推理速度）
  - 子图3：边数增长 vs N（退化归因：传播随边数变宽）
"""
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

RUNS = Path(__file__).resolve().parent.parent / "runs"


def main():
    fp = RUNS / "_speed_bench.json"
    if not fp.exists():
        print(f"[中止] 缺少 {fp}（先跑 python -u _probe_speed.py）")
        return
    out = json.loads(fp.read_text(encoding="utf-8"))
    cs = out["cases"]
    ns = [int(k) for k in cs]
    ns.sort()
    sec = [cs[str(n)]["sec_per_teach"] for n in ns]
    ev = [cs[str(n)]["evoke_ms"] for n in ns]
    nnz = [cs[str(n)]["nnz_after"] / 1e6 for n in ns]

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    fig.suptitle(f"速度基准：训练语句量 N → 训练/推理速度（v{out['version']}，"
                 f"{out['n_rounds']} 轮/句）", fontsize=13)

    # 子图1：每教学秒（训练吞吐核心）
    ax = axes[0]
    ax.plot(ns, sec, "o-", color="#c0392b", lw=2)
    ax.set_xlabel("训练语句量 N（句）")
    ax.set_ylabel("每教学秒（秒/次）")
    ax.set_title("训练速度：每教学秒随 N")
    ax.grid(alpha=0.3)

    # 子图2：唤起毫秒（推理速度）
    ax = axes[1]
    ax.plot(ns, ev, "s-", color="#2980b9", lw=2)
    ax.set_xlabel("训练语句量 N（句）")
    ax.set_ylabel("唤起毫秒/次（ms）")
    ax.set_title("推理速度：唤起毫秒随 N")
    ax.grid(alpha=0.3)

    # 子图3：边数增长（退化归因）
    ax = axes[2]
    ax.plot(ns, nnz, "^-", color="#27ae60", lw=2)
    ax.set_xlabel("训练语句量 N（句）")
    ax.set_ylabel("学习后边数（百万）")
    ax.set_title("结构规模：边数随 N 增长")
    ax.grid(alpha=0.3)

    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(RUNS / "fig_speed_bench.png", dpi=150)
    print(f"[保存] {RUNS / 'fig_speed_bench.png'}")

    # 判读打印
    v = out.get("verdict", {})
    print("\n═══ 判读 ═══")
    for k, val in v.items():
        print(f"  {k}: {val}")


if __name__ == "__main__":
    main()
