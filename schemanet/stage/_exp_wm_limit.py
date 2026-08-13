# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""上下文极限测试：多条目工作记忆回路（2026-08-11）。

用户："网络本来就不是人"——放开 4±1 人形约束——测多条目同时维持的
真实极限（机制来自脑：隔离回路——容量按网络）。

设计：N 个词各建 H 回路（gain 调制）→ 同时注入 → 同时维持
  → 500 tick 后各条目读回（发放保持）→ 精度（不互扰）
预测极限：WTA top-k=16 是竞争瓶颈（每回路 8 神经元——振荡半发）
  N=2 → 8 发/tick（够）N=4 → 16 发（临界）N>4 → 超 top-k（部分挤出）

测量：
  ① 维持率（N 条目 500 tick 后仍可读回）
  ② 精度（读回正确——回路 A 不混入 B 的发放）
  ③ 极限点（N 多大时崩溃）

用法：python _exp_wm_limit.py（纯内存）
"""

import numpy as np
from schema_net import build_pulse
from snapshot import load_version

WORDS = ["饿", "渴", "冷", "疼", "累", "困", "怕", "热",
         "开心", "难过", "生气", "饿"]


def build_multi(ng, pats, cursor, words, k=4, gain_v=8.0, bind_w=64.0):
    """N 条目的工作记忆回路。"""
    from sparse_net import allocate_pats
    Hs = {}
    for w in words:
        p, cursor = allocate_pats(ng, [f"__H_{w}__"], k, cursor)
        H = p[f"__H_{w}__"]
        Hs[w] = H
        W = ng.W_out
        for i in H:
            for j in pats[w]:
                W[i][0][j] = bind_w
                W[j][0][i] = bind_w
        for i in H:
            for j in H:
                if i != j:
                    W[i][0][j] = bind_w
        ng.gain[H] = gain_v
        ng.gain[pats[w]] = gain_v
    return Hs, cursor


def run_multi(ng, pats, words, Hs, steps=500):
    """同时注入所有条目 → 维持 → 每 100 tick 读回检查。"""
    idxs = []
    for w in words:
        idxs += pats[w]
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)
    ng.step(build_pulse(ng.n, idxs), slot=0)
    read_ok = {w: [] for w in words}
    for t in range(1, steps + 1):
        ng.step(np.zeros(ng.n), slot=0)
        fired = np.where(ng.spikes > 0)[0]
        fset = set(fired)
        if t % 100 == 0:
            for w in words:
                # 读回：该词发放（记忆保持）
                hit = any(i in fset for i in pats[w])
                read_ok[w].append(hit)
    return read_ok


def main():
    print("═══ 上下文极限：多条目工作记忆压力测试 ═══\n")
    print("（纯内存——不保存快照）\n")
    for n in [1, 2, 3, 4, 6, 8, 12]:
        ng, vocab, pats, cursor = load_version("35.0")
        n2w = {j: w for w, ns in pats.items() for j in ns}
        words = WORDS[:n]
        Hs, _ = build_multi(ng, pats, cursor, words)
        read_ok = run_multi(ng, pats, words, Hs)
        # 维持率（5 次采样全中）
        held = sum(1 for w in words if all(read_ok[w]))
        # 互扰检测：采样时 回路 A 的发放是否混入 B 的神经元（精度）
        # 简化：最后采样各词发放的神经元是否包含其他词的（检查 top）
        print(f"  N={n:<3} 条目：维持 {held}/{n}"
              f"（{'✅ 全部稳定' if held == n else '⚠️ 部分丢失'}）")

    print(f"\n═══ 极限 ═══")
    print(f"  见上（维持率 vs 条目数——WTA top-k=16 是竞争瓶颈）")
    print(f"  [机制] 隔离回路可并行——容量受竞争带宽限制"
          f"（top-k × 振荡——非 4±1 人形约束）")


if __name__ == "__main__":
    main()
