# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""临时：第二波新内核分支全覆盖对拍（refractory≥2 / std_dep / refract_clear / 唤起传播路径）。
v13.0 参数不覆盖这些分支（refractory=1 饱和、std_dep=0、refract_clear=False、学习无传播），
本轮新增内核必须证明在激活组合下仍与参考实现逐位一致。测完即删。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from schema_net import build_pulse
from snapshot import load_snapshot, RUNS
from _check_speed_opt import step_ref

VERSIONS = [
    dict(refractory=1, std_dep=0.6, std_rec=0.85, refract_clear=False,
         inh_loose=0.3, edge_min=0.3, inh_norm=4.0),   # 全机制开
    dict(refractory=2, std_dep=0.0, refract_clear=True),  # 双递减曾分叉的组合
    dict(refractory=3, std_dep=0.5, std_rec=0.9, refract_clear=True,
         inh_loose=0.5, edge_min=0.2),                  # 双递减 + 疲劳 + 硬清
    dict(refractory=1, stdp_neg=0.5, weight_decay=0.01),  # LTD 新键截断（波3修复）
]


def diff_all(ng_a, ng_b):
    diff = 0
    for i in range(ng_a.n):
        for k in range(ng_a.slots):
            ra, rb = ng_a.W_out[i][k], ng_b.W_out[i][k]
            if len(ra) != len(rb):
                diff += len(ra) + len(rb)
                continue
            if len(ra) == 0:
                continue
            if not np.array_equal(ra.dst, rb.dst):
                diff += 1
            elif not np.array_equal(ra.w, rb.w):
                diff += 1
    return diff


def learn_mixed(ng, pats, pairs, step_fn, rounds=2):
    """学习 + 唤起混合序列：唤起步（不 reset spikes）走传播路径，触发 else 分支。"""
    step = step_fn
    for x, y in pairs:
        for _ in range(rounds):
            ng.v = np.zeros((ng.n, ng.slots))
            ng.spikes = np.zeros(ng.n)
            ng.pre_trace = np.zeros(ng.n)
            for w in (x, y):
                ng.v = np.zeros((ng.n, ng.slots))
                ng.spikes = np.zeros(ng.n)
                step(ng, build_pulse(ng.n, pats[w]), slot=0)
                ng.spikes = np.zeros(ng.n)
                step(ng, np.zeros(ng.n), slot=0)
            # 唤起段：spikes 不 reset → 传播路径 + STDP 全开
            step(ng, build_pulse(ng.n, pats[x]), slot=0)
            for _ in range(3):
                step(ng, np.zeros(ng.n), slot=0)


def main():
    ng0, vocab, pats, cursor = load_snapshot(RUNS / "v13_0_20260810_111247" / "net.npz")
    rng = np.random.default_rng(7)
    words = list(pats.keys())
    rng.shuffle(words)
    pairs = [(words[i], words[i + 1]) for i in range(0, 40, 2)]

    for i, over in enumerate(VERSIONS):
        # 两份独立副本 + 叠加机制参数
        from sparse_net import SparseSchemaNet
        ng_new, _, _, _ = load_snapshot(RUNS / "v13_0_20260810_111247" / "net.npz")
        ng_ref, _, _, _ = load_snapshot(RUNS / "v13_0_20260810_111247" / "net.npz")
        for ngx in (ng_new, ng_ref):
            for k, v in over.items():
                setattr(ngx, k, v)
            ngx.rng = np.random.default_rng(42)   # 同种子 → 同噪声序列
        ng_new.rng = np.random.default_rng(42)
        ng_ref.rng = np.random.default_rng(42)

        learn_mixed(ng_new, pats, pairs, lambda ng2, p, slot=0: ng2.step(p, slot))
        learn_mixed(ng_ref, pats, pairs, step_ref)
        diff = diff_all(ng_new, ng_ref)
        st = {k: v for k, v in over.items()}
        print(f"[组合{i + 1}] {st}")
        print(f"  → 差异边数 = {diff}  {'✅ 一致' if diff == 0 else '❌ 分叉'}")
        if diff:
            return


if __name__ == "__main__":
    main()
