# -*- coding: utf-8 -*-
"""E6 中性组塌陷调试：逐段跟踪 w_xb + B 发放率，定位 Phase 2 塌陷时刻与原因。"""
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
    tot = 0.0
    n_e = 0
    for i in x_n:
        row = ng.W_out[i][0]
        if row:
            for j in b_n:
                w = row.get(j, 0.0)
                if w > 0:
                    tot += w
                    n_e += 1
    return tot, n_e


def chunk(n_cycles, tag, learn):
    ng.learn_gate = learn
    ev = bg_fire = bg = 0
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
        if fired:
            ev += 1
    w, ne = w_xb()
    print(f"  {tag}: f={ev/n_cycles*100:5.1f}%  chaos={bg_fire/bg:.2f}  "
          f"w={w:7.1f} (n_edges={ne:3d})  da={ng.da:.2f} elig={len(ng._elig_pairs)}")


print("预学习后:", w_xb())
ng.learn_gate = False
chunk(40, "P1基线(冻结)", False)
chunk(10, "P2-1(开学习)", True)
chunk(10, "P2-2", True)
chunk(10, "P2-3", True)
chunk(10, "P2-4", True)
chunk(10, "P2-5", True)
chunk(10, "P2-6", True)
chunk(10, "P2-7", True)
chunk(10, "P2-8", True)
