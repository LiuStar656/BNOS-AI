# -*- coding: utf-8 -*-
"""E6 方案 B 验证：行为 = 指定 4 元 B 子集全部发放（固定组合）。
奖励强化该组合入边 → 组合频率升；惩罚压制 → 降；neutral 基线。
对比原"≥8 任意 B"（马太坍缩）。"""
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
NP, NA, SP, PR, DC = 0.05, 0.3, 0.15, 2, 0.3
TARGET_K = 4


def run_one(seed, mode):
    rng = np.random.default_rng(seed * 100 + {"reward": 0, "punish": 1, "neutral": 2}[mode])
    ng = SparseSchemaNet(n=N, slots=1, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=16.0, wta_k=WTA_K, noise_p=NP, noise_amp=NA,
                         refractory=1, stdp_pre=SP, std_dep=0.5, std_rec=0.85,
                         refract_clear=True, rng=rng)
    pats, _ = allocate_pats(ng, ["X", "B"], K)
    x_n = list(pats["X"])
    b_n = list(pats["B"])
    tgt = b_n[:TARGET_K]                      # 指定行为组合（前 4 个 B 神经元）
    t_mask = np.zeros(N, dtype=bool)
    t_mask[tgt] = True
    pool = [i for i in range(N) if i not in set(x_n) | set(b_n)]
    for _ in range(PR):
        ng.release_da(DA_PRE)
        ng.step(build_pulse(N, x_n, INJECT_AMP), slot=0)
        ng.step(build_pulse(N, b_n, INJECT_AMP), slot=0)
    ng.da = 0.0
    ng.da_expected = 0.0
    ng._elig_pairs.clear()

    def w_tgt():
        return sum(ng.W_out[i][0].get(j, 0.0) for i in x_n for j in tgt
                   if ng.W_out[i][0].get(j, 0.0) > 0)

    def behave():
        return int(np.count_nonzero(ng.spikes[t_mask])) >= TARGET_K

    def run_cycles(n_cycles, inject_pulse, lm):
        events = 0
        for _ in range(n_cycles):
            fired = False
            for si in range(INJECT_EVERY):
                if si == 0:
                    ng.step(build_pulse(N, inject_pulse, INJECT_AMP), slot=0)
                else:
                    ng.step(np.zeros(N), slot=0)
                if not fired and si < WINDOW and behave():
                    fired = True
                    if lm != "none":
                        for i in x_n:
                            row = ng.W_out[i][0]
                            if row:
                                for j in tgt:
                                    if row.get(j, 0.0) > 0:
                                        ng._elig_pairs[(int(i), int(j))] = 1.0
                        ng.release_da(+DC if lm == "reward" else -DC)
            if fired:
                events += 1
        return events

    ng.learn_gate = False
    w_pre = round(w_tgt(), 1)
    f_base = run_cycles(P1_CYCLES, x_n, "none")
    ng.learn_gate = True
    lm = "none" if mode == "neutral" else mode
    f_inter = run_cycles(P2_CYCLES, x_n, lm)
    ng.learn_gate = False
    ng.da = 0.0
    ng.da_expected = 0.0
    ng._elig_pairs.clear()
    w_post = round(w_tgt(), 1)

    def make_variant(rng, x_neurons, pool, k):
        keep = set(int(i) for i in rng.choice(x_neurons, k, replace=False))
        need = K - len(keep)
        new = set(int(i) for i in rng.choice(pool, need, replace=False))
        return sorted(keep | new)

    variants = {k: (x_n if k == 16 else make_variant(rng, x_n, pool, k)) for k in (16, 12, 8, 4)}
    f_test = {k: run_cycles(20, variants[k], "none") for k in variants}
    return {"w_pre": w_pre, "w_post": w_post, "f_base": f_base / P1_CYCLES * 100,
            "f_inter": f_inter / P2_CYCLES * 100,
            "f16": f_test[16] / 20 * 100, "f12": f_test[12] / 20 * 100,
            "f8": f_test[8] / 20 * 100, "f4": f_test[4] / 20 * 100}


print("═══ E6 方案 B：行为=指定4元B组合（seed 42/43/44 × 3 modes）═══")
for seed in (42, 43, 44):
    res = {m: run_one(seed, m) for m in ("reward", "punish", "neutral")}
    for m in ("reward", "punish", "neutral"):
        r = res[m]
        print(f"seed {seed} {m:>7}: w {r['w_pre']:>6}->{r['w_post']:>7}  "
              f"f_b {r['f_base']:>3.0f}% f_i {r['f_inter']:>3.0f}%  "
              f"f16 {r['f16']:>3.0f}% f12 {r['f12']:>3.0f}% f8 {r['f8']:>3.0f}% f4 {r['f4']:>3.0f}%")
    dr = res["reward"]["f16"] - res["neutral"]["f16"]
    dp = res["punish"]["f16"] - res["neutral"]["f16"]
    print(f"        Δreward={dr:+.0f}  Δpunish={dp:+.0f}")
