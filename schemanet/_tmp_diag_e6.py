# -*- coding: utf-8 -*-
"""E6 完整协议探针：基线→干预(奖惩)→冻结测试，验证调节是否生效。
机制修复（v2.0 两个根因）：
  1. 预学习后清 da + 基线/测试期 learn_gate=False —— 防残留学习写边自振；
  2. 干预期行为发生时对活跃 X→B 突触打资格标 + release_da(±) ——
     Δw=DA×e 兑现（惩罚经资格迹 LTD，engine 原语义，不碰引擎代码）。"""
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from schema_net import build_pulse
from sparse_net import SparseSchemaNet, allocate_pats

N = 1024
K = 16
WTA_K = 8
PRE_ROUNDS = 3
P1_CYCLES = 40
P2_CYCLES = 80
P3_CYCLES = 10
INJECT_EVERY = 5
WINDOW = 2
INJECT_AMP = 1.0
DA_PRE = 1.0
DA_CTRL_GLOBAL = 0.5
VARIANTS = (16, 12, 8, 4)


def run_one(seed, mode, noise_p, noise_amp, stdp_pre, behave_min, pre_rounds=3, da_ctrl=0.5):
    rng = np.random.default_rng(seed * 100 + {"reward": 0, "punish": 1, "neutral": 2}[mode])
    ng = SparseSchemaNet(n=N, slots=1, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=16.0, wta_k=WTA_K, noise_p=noise_p, noise_amp=noise_amp,
                         refractory=1, stdp_pre=stdp_pre, std_dep=0.5, std_rec=0.85,
                         refract_clear=True, rng=rng)
    pats, _ = allocate_pats(ng, ["X", "B"], K)
    x_n = list(pats["X"])
    b_n = list(pats["B"])
    b_mask = np.zeros(N, dtype=bool)
    b_mask[b_n] = True
    pool = [i for i in range(N) if i not in set(x_n) | set(b_n)]

    # 预学习：STDP 时序教学（X 先发 → B 后发 → 单向 X→B 边）
    for _ in range(pre_rounds):
        ng.release_da(DA_PRE)
        ng.step(build_pulse(N, x_n, INJECT_AMP), slot=0)
        ng.step(build_pulse(N, b_n, INJECT_AMP), slot=0)
    # 根因①：清残留 da，防测量期无奖惩也写边（v2.0 chaos=1.0 根因）
    ng.da = 0.0
    ng.da_expected = 0.0
    ng._elig_pairs.clear()

    def w_xb():
        tot = 0.0
        for i in x_n:
            row = ng.W_out[i][0]
            if row:
                for j in b_n:
                    tot += row.get(j, 0.0)
        return tot

    w_pre = w_xb()

    def behave_event():
        return int(np.count_nonzero(ng.spikes[b_mask]) >= behave_min)

    def run_cycles(n_cycles, inject_pulse, learn_mode, mark_elig):
        """注入周期序列；奖惩在行为发生时注入。mark_elig=True 时对活跃
        X→B 突触打资格标（Δw=DA×e 兑现对象——惩罚必需，奖励同效）。"""
        events = 0
        bg_fire = bg_steps = 0
        for _ in range(n_cycles):
            fired_win = False
            for si in range(INJECT_EVERY):
                if si == 0:
                    ng.step(build_pulse(N, inject_pulse, INJECT_AMP), slot=0)
                else:
                    ng.step(np.zeros(N), slot=0)
                    bg_steps += 1
                    if bool(np.any(ng.spikes > 0)):
                        bg_fire += 1
                if not fired_win and si < WINDOW and behave_event():
                    fired_win = True
                    if learn_mode != "none":
                        if mark_elig:
                            for i in x_n:
                                row = ng.W_out[i][0]
                                if row:
                                    for j in b_n:
                                        if row.get(j, 0.0) > 0:
                                            ng._elig_pairs[(int(i), int(j))] = 1.0
                        ng.release_da(+da_ctrl if learn_mode == "reward" else -da_ctrl)
            if fired_win:
                events += 1
        chaos = bg_fire / bg_steps if bg_steps else 0.0
        return events, chaos

    # Phase 1 基线（冻结学习——纯测量）
    ng.learn_gate = False
    f_base, chaos_ratio = run_cycles(P1_CYCLES, x_n, "none", False)
    # Phase 2 干预（学习开启 + 奖惩注入；neutral 组 learn_mode="none" 纯复读零改动）
    ng.learn_gate = True
    ng.da = 0.0
    ng.da_expected = 0.0
    lm = "none" if mode == "neutral" else mode
    f_inter, _ = run_cycles(P2_CYCLES, x_n, lm, True)
    # Phase 3 冻结测试（含变体）
    ng.learn_gate = False
    ng.da = 0.0
    variants = {k: (x_n if k == 16 else make_variant(rng, x_n, pool, k))
                for k in VARIANTS}
    f_test = {}
    for k in VARIANTS:
        ev, _ = run_cycles(P3_CYCLES, variants[k], "none", False)
        f_test[k] = ev / P3_CYCLES * 100.0
    return {
        "chaos": round(chaos_ratio, 3),
        "w_pre": round(w_pre, 2), "w_post": round(w_xb(), 2),
        "f_base": round(f_base / P1_CYCLES * 100.0, 1),
        "f_inter": round(f_inter / P2_CYCLES * 100.0, 1),
        "f16": f_test[16], "f12": f_test[12], "f8": f_test[8], "f4": f_test[4],
    }


def make_variant(rng, x_neurons, pool, k):
    keep = set(int(i) for i in rng.choice(x_neurons, k, replace=False))
    need = K - len(keep)
    new = set(int(i) for i in rng.choice(pool, need, replace=False))
    return sorted(keep | new)


REGS = [
    # (noise_p, noise_amp, stdp_pre, behave_min, pre_rounds, da_ctrl)
    (0.05, 0.3, 0.1, 6, 1, 0.3),    # w~9 弱边（预期 f_base 低）
    (0.05, 0.3, 0.1, 6, 2, 0.3),
    (0.05, 0.3, 0.1, 6, 3, 0.3),
    (0.05, 0.3, 0.05, 6, 3, 0.3),
    (0.05, 0.3, 0.05, 6, 5, 0.3),
    (0.05, 0.3, 0.1, 8, 3, 0.3),
    (0.05, 0.3, 0.05, 8, 5, 0.3),
    (0.05, 0.3, 0.15, 8, 2, 0.3),
]

print("═══ E6 完整协议探针（seed=42）═══")
for np_, na, sp, bm, pr, dc in REGS:
    print(f"\n--- regime: noise_p={np_} noise_amp={na} stdp_pre={sp} behave_min={bm} preR={pr} da_ctrl={dc} ---")
    print(f"{'mode':>7} | {'chaos':>5} {'w_pre':>6} {'w_post':>6} | "
          f"{'f_base':>6} {'f_inter':>6} | {'f16':>5} {'f12':>5} {'f8':>5} {'f4':>5}")
    row = {}
    for m in ("reward", "punish", "neutral"):
        r = run_one(42, m, np_, na, sp, bm, pr, dc)
        row[m] = r
        print(f"{m:>7} | {r['chaos']:>5} {r['w_pre']:>6} {r['w_post']:>6} | "
              f"{r['f_base']:>5.0f}% {r['f_inter']:>5.0f}% | "
              f"{r['f16']:>4.0f}% {r['f12']:>4.0f}% {r['f8']:>4.0f}% {r['f4']:>4.0f}%")
    d_rew = row["reward"]["f16"] - row["neutral"]["f16"]
    d_pun = row["punish"]["f16"] - row["neutral"]["f16"]
    ok = (row["reward"]["f16"] > row["neutral"]["f16"] + 15
          and row["punish"]["f16"] < row["neutral"]["f16"] - 15)
    print(f"       Δreward={d_rew:+.1f}  Δpunish={d_pun:+.1f}  "
          f"→ {'✅ 双向调节' if ok else '✗ 无区分'}")
