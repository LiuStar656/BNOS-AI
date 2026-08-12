# -*- coding: utf-8 -*-
"""用 _tmp_diag_e6.run_one 直接单跑中性组，逐阶段打点定位塌陷。"""
import numpy as np
from schema_net import build_pulse
from sparse_net import SparseSchemaNet, allocate_pats

N = 1024
K = 16
WTA_K = 8
INJECT_EVERY = 5
WINDOW = 2
INJECT_AMP = 1.0
BEHAVE_MIN = 5

rng = np.random.default_rng(42 * 100 + 2)
ng = SparseSchemaNet(n=N, slots=1, theta=1.0, membrane_decay=0.9, eta=0.1,
                     w_max=16.0, wta_k=WTA_K, noise_p=0.05, noise_amp=0.3,
                     refractory=1, stdp_pre=0.1, std_dep=0.5, std_rec=0.85,
                     refract_clear=True, rng=rng)
pats, _ = allocate_pats(ng, ["X", "B"], K)
x_n = list(pats["X"])
b_n = list(pats["B"])
b_mask = np.zeros(N, dtype=bool)
b_mask[b_n] = True

for _ in range(3):
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
    return tot, n_e


def run_cycles(n_cycles, tag, learn_gate, learn_mode):
    ng.learn_gate = learn_gate
    events = bg_fire = bg = 0
    for _ in range(n_cycles):
        fired = False
        for si in range(INJECT_EVERY):
            if si == 0:
                ng.step(build_pulse(N, x_n, INJECT_AMP), slot=0)
            else:
                ng.step(np.zeros(N), slot=0)
                bg += 1
                if np.any(ng.spikes > 0):
                    bg_fire += 1
            if not fired and si < WINDOW and np.count_nonzero(ng.spikes[b_mask]) >= BEHAVE_MIN:
                fired = True
                if learn_mode != "none":
                    ng.release_da(+0.5 if learn_mode == "reward" else -0.5)
        if fired:
            events += 1
    w, ne = w_xb()
    print(f"  {tag}: f={events/n_cycles*100:5.1f}% chaos={bg_fire/bg:.2f} "
          f"w={w:7.1f}({ne:3d}边) da={ng.da:.2f} elig={len(ng._elig_pairs)}")


print("预学习后:", w_xb())
run_cycles(40, "P1基线(冻结, none)", False, "none")
run_cycles(80, "P2干预(开学习, none)", True, "none")
run_cycles(10, "P3测试(冻结, none)", False, "none")
run_cycles(10, "P3b再测(冻结, none)", False, "none")
