# -*- coding: utf-8 -*-
"""E6 reward 组 f16=0 定位（v2，含完整干预）：seed 44 复现完整协议，
Phase 2 干预插桩（标记次数/w 增长），Phase 3 逐 cycle B 发放数。"""
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
NP, NA, SP, BM, PR, DC = 0.05, 0.3, 0.15, 8, 2, 0.3
SEED = 44

rng = np.random.default_rng(SEED * 100 + 0)  # reward mode_idx=0
ng = SparseSchemaNet(n=N, slots=1, theta=1.0, membrane_decay=0.9, eta=0.1,
                     w_max=16.0, wta_k=WTA_K, noise_p=NP, noise_amp=NA,
                     refractory=1, stdp_pre=SP, std_dep=0.5, std_rec=0.85,
                     refract_clear=True, rng=rng)
pats, _ = allocate_pats(ng, ["X", "B"], K)
x_n = list(pats["X"])
b_n = list(pats["B"])
b_mask = np.zeros(N, dtype=bool)
b_mask[b_n] = True
for _ in range(PR):
    ng.release_da(DA_PRE)
    ng.step(build_pulse(N, x_n, INJECT_AMP), slot=0)
    ng.step(build_pulse(N, b_n, INJECT_AMP), slot=0)
ng.da = 0.0
ng.da_expected = 0.0
ng._elig_pairs.clear()


def w_sum():
    return sum(ng.W_out[i][0].get(j, 0.0) for i in x_n for j in b_n
               if ng.W_out[i][0].get(j, 0.0) > 0)


def run(n_cycles, label, inter, report_every=25):
    """inter: True=reward 干预（mark_elig + release_da(+DC)）。返回事件数。"""
    events = 0
    marks = 0
    for c in range(n_cycles):
        fired = False
        for si in range(INJECT_EVERY):
            if si == 0:
                ng.step(build_pulse(N, x_n, INJECT_AMP), slot=0)
            else:
                ng.step(np.zeros(N), slot=0)
            if not fired and si < WINDOW and np.count_nonzero(ng.spikes[b_mask]) >= BM:
                fired = True
                if inter:
                    for i in x_n:
                        row = ng.W_out[i][0]
                        if row:
                            for j in b_n:
                                if row.get(j, 0.0) > 0:
                                    ng._elig_pairs[(int(i), int(j))] = 1.0
                    marks += 1
                    ng.release_da(+DC)
        if fired:
            events += 1
        if report_every and (c + 1) % report_every == 0:
            print(f"  {label} c{c+1}: f={events/(c+1)*100:.0f}%  "
                  f"w(X→B)={w_sum():.0f}  marks={marks}  fatB={np.mean(ng.fat[b_n]):.3f}")
    return events


print(f"═══ seed {SEED} reward（w_pre={w_sum():.0f}）═══")
ng.learn_gate = False
run(P1_CYCLES, "P1", inter=False)
ng.learn_gate = True
run(P2_CYCLES, "P2", inter=True)
ng.learn_gate = False
ng.da = 0.0
ng.da_expected = 0.0
ng._elig_pairs.clear()
print(f"干预后 w(X→B)={w_sum():.0f}")

# Phase 3 逐 cycle：B 发放神经元数（si=1，传播后）
hits = 0
for c in range(P3_CYCLES):
    fired = False
    nb_si0 = nb_si1 = 0
    for si in range(INJECT_EVERY):
        if si == 0:
            ng.step(build_pulse(N, x_n, INJECT_AMP), slot=0)
            nb_si0 = int(np.count_nonzero(ng.spikes[b_mask]))
        else:
            ng.step(np.zeros(N), slot=0)
            if si == 1:
                nb_si1 = int(np.count_nonzero(ng.spikes[b_mask]))
            if not fired and si < WINDOW and nb_si1 >= BM:
                fired = True
                hits += 1
    if (c + 1) % 5 == 0:
        print(f"P3 c{c+1}: 达标 {hits}/{c+1}  B发放 si0={nb_si0}/si1={nb_si1}  "
              f"fatB={np.mean(ng.fat[b_n]):.3f}")
