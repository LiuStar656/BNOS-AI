# -*- coding: utf-8 -*-
"""Regime 8 稳健性验证：3 seeds × 3 modes。"""
import numpy as np
from schema_net import build_pulse
from sparse_net import SparseSchemaNet, allocate_pats

N = 1024
K = 16
WTA_K = 8
P1_CYCLES = 40
P2_CYCLES = 100
P3_CYCLES = 20
INJECT_EVERY = 5
WINDOW = 2
INJECT_AMP = 1.0
DA_PRE = 1.0
VARIANTS = (16, 12, 8, 4)
NP, NA, SP, BM, PR, DC = 0.05, 0.3, 0.15, 8, 2, 0.3


def make_variant(rng, x_neurons, pool, k):
    keep = set(int(i) for i in rng.choice(x_neurons, k, replace=False))
    need = K - len(keep)
    new = set(int(i) for i in rng.choice(pool, need, replace=False))
    return sorted(keep | new)


def run_one(seed, mode):
    rng = np.random.default_rng(seed * 100 + {"reward": 0, "punish": 1, "neutral": 2}[mode])
    ng = SparseSchemaNet(n=N, slots=1, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=16.0, wta_k=WTA_K, noise_p=NP, noise_amp=NA,
                         refractory=1, stdp_pre=SP, std_dep=0.5, std_rec=0.85,
                         refract_clear=True, rng=rng)
    pats, _ = allocate_pats(ng, ["X", "B"], K)
    x_n = list(pats["X"])
    b_n = list(pats["B"])
    b_mask = np.zeros(N, dtype=bool)
    b_mask[b_n] = True
    pool = [i for i in range(N) if i not in set(x_n) | set(b_n)]
    for _ in range(PR):
        ng.release_da(DA_PRE)
        ng.step(build_pulse(N, x_n, INJECT_AMP), slot=0)
        ng.step(build_pulse(N, b_n, INJECT_AMP), slot=0)
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

    def run_cycles(n_cycles, inject_pulse, learn_mode):
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
                if not fired_win and si < WINDOW and np.count_nonzero(ng.spikes[b_mask]) >= BM:
                    fired_win = True
                    if learn_mode != "none":
                        for i in x_n:
                            row = ng.W_out[i][0]
                            if row:
                                for j in b_n:
                                    if row.get(j, 0.0) > 0:
                                        ng._elig_pairs[(int(i), int(j))] = 1.0
                        ng.release_da(+DC if learn_mode == "reward" else -DC)
            if fired_win:
                events += 1
        return events, bg_fire / bg_steps

    ng.learn_gate = False
    w_pre = round(w_xb(), 1)
    f_base, chaos = run_cycles(P1_CYCLES, x_n, "none")
    # Phase 2 干预（方案 C）：保持 learn_gate=False——隔离"纯奖惩经资格迹
    # 兑现"效应（release_da 直接写边、不受 learn_gate 控制），无 Hebbian
    # "使用增强"混杂 → 不触发马太坍缩（E6d 定位：learn_gate=True 时
    # Hebbian+兑现双重强化 → 少数 B 神经元垄断 → 行为解体的根因）。
    # neutral 组 learn_mode 必须为 "none"——否则落入惩罚分支自我惩罚
    lm = "none" if mode == "neutral" else mode
    f_inter, _ = run_cycles(P2_CYCLES, x_n, lm)
    # Phase 3 冻结测试：关闭学习门 + 清残留 da
    ng.learn_gate = False
    ng.da = 0.0
    ng.da_expected = 0.0
    ng._elig_pairs.clear()
    w_post = round(w_xb(), 1)
    variants = {k: (x_n if k == 16 else make_variant(rng, x_n, pool, k)) for k in VARIANTS}
    f_test = {k: run_cycles(P3_CYCLES, variants[k], "none")[0] / P3_CYCLES * 100.0
              for k in VARIANTS}
    return {"chaos": round(chaos, 3), "w_pre": w_pre, "w_post": w_post,
            "f_base": f_base / P1_CYCLES * 100,
            "f_inter": f_inter / P2_CYCLES * 100, "w": round(w_xb(), 1), "ft": f_test}


print(f"regime: noise_p={NP} amp={NA} stdp_pre={SP} bm={BM} preR={PR} da_ctrl={DC}")
for seed in (42, 43, 44):
    res = {m: run_one(seed, m) for m in ("reward", "punish", "neutral")}
    d16 = {m: res[m]["ft"][16] for m in ("reward", "punish", "neutral")}
    for m in ("reward", "punish", "neutral"):
        r = res[m]
        print(f"seed {seed} {m:>7}: w {r['w_pre']:>6}->{r['w_post']:>6}  "
              f"f_b {r['f_base']:>3.0f}% f_i {r['f_inter']:>3.0f}% f16 {d16[m]:>3.0f}%")
    print(f"seed {seed}: f16 R/P/N = {d16['reward']:.0f}/{d16['punish']:.0f}/{d16['neutral']:.0f}  "
          f"ΔR={d16['reward']-d16['neutral']:+.0f} ΔP={d16['punish']-d16['neutral']:+.0f}")
