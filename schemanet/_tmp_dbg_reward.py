# -*- coding: utf-8 -*-
"""E6 奖励组干预轨迹：每 10 周期打点 f/w，看行为频率随权重增长的轨迹。"""
import numpy as np
from schema_net import build_pulse
from sparse_net import SparseSchemaNet, allocate_pats

N = 1024
K = 16
WTA_K = 8
INJECT_EVERY = 5
WINDOW = 2
INJECT_AMP = 1.0
BEHAVE_MIN = 8
DA_CTRL = 0.3

rng = np.random.default_rng(42 * 100 + 0)  # reward
ng = SparseSchemaNet(n=N, slots=1, theta=1.0, membrane_decay=0.9, eta=0.1,
                     w_max=16.0, wta_k=WTA_K, noise_p=0.05, noise_amp=0.3,
                     refractory=1, stdp_pre=0.15, std_dep=0.5, std_rec=0.85,
                     refract_clear=True, rng=rng)
pats, _ = allocate_pats(ng, ["X", "B"], K)
x_n = list(pats["X"])
b_n = list(pats["B"])
b_mask = np.zeros(N, dtype=bool)
b_mask[b_n] = True

for _ in range(1):
    ng.release_da(1.0)
    ng.step(build_pulse(N, x_n, INJECT_AMP), slot=0)
    ng.step(build_pulse(N, b_n, INJECT_AMP), slot=0)
ng.da = 0.0
ng.da_expected = 0.0
ng._elig_pairs.clear()


def w_xb():
    tot = n_e = 0
    for i in x_n:
        row = ng.W_out[i][0]
        if row:
            for j in b_n:
                w = row.get(j, 0.0)
                if w > 0:
                    tot += w
                    n_e += 1
    return round(tot, 1), n_e


def block(n_cycles, tag, learn_mode, mark):
    events = 0
    for _ in range(n_cycles):
        fired = False
        for si in range(INJECT_EVERY):
            if si == 0:
                ng.step(build_pulse(N, x_n, INJECT_AMP), slot=0)
            else:
                ng.step(np.zeros(N), slot=0)
            if not fired and si < WINDOW and np.count_nonzero(ng.spikes[b_mask]) >= BEHAVE_MIN:
                fired = True
                if learn_mode != "none":
                    if mark:
                        for i in x_n:
                            row = ng.W_out[i][0]
                            if row:
                                for j in b_n:
                                    if row.get(j, 0.0) > 0:
                                        ng._elig_pairs[(int(i), int(j))] = 1.0
                    ng.release_da(+DA_CTRL if learn_mode == "reward" else -DA_CTRL)
        if fired:
            events += 1
    w, ne = w_xb()
    print(f"  {tag}: f={events/n_cycles*100:4.0f}%  w={w:7.1f} ({ne}边) da={ng.da:.2f}")
    return events / n_cycles


print("预学习后 w:", w_xb())
ng.learn_gate = False
block(40, "P1 基线", "none", False)
for k in range(10):
    block(10, f"P2 干预{k}", "reward", True)
block(20, "P3 测试X", "none", False)
