# -*- coding: utf-8 -*-
"""逐行复刻 _tmp_diag_e6.run_one 的中性组路径，逐阶段打印 w，定位塌陷阶段。"""
import numpy as np
from schema_net import build_pulse
from sparse_net import SparseSchemaNet, allocate_pats

N = 1024
K = 16
WTA_K = 8
P1_CYCLES = 40
P2_CYCLES = 80
P3_CYCLES = 10
INJECT_EVERY = 5
WINDOW = 2
INJECT_AMP = 1.0
DA_CTRL = 0.5
VARIANTS = (16, 12, 8, 4)


def make_variant(rng, x_neurons, pool, k):
    keep = set(int(i) for i in rng.choice(x_neurons, k, replace=False))
    need = K - len(keep)
    new = set(int(i) for i in rng.choice(pool, need, replace=False))
    return sorted(keep | new)


mode = "neutral"
seed = 42
rng = np.random.default_rng(seed * 100 + {"reward": 0, "punish": 1, "neutral": 2}[mode])
ng = SparseSchemaNet(n=N, slots=1, theta=1.0, membrane_decay=0.9, eta=0.1,
                     w_max=16.0, wta_k=WTA_K, noise_p=0.05, noise_amp=0.3,
                     refractory=1, stdp_pre=0.1, std_dep=0.5, std_rec=0.85,
                     refract_clear=True, rng=rng)
pats, _ = allocate_pats(ng, ["X", "B"], K)
x_n = list(pats["X"])
b_n = list(pats["B"])
b_mask = np.zeros(N, dtype=bool)
b_mask[b_n] = True
pool = [i for i in range(N) if i not in set(x_n) | set(b_n)]

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
    return round(tot, 2), n_e


def behave_event():
    return int(np.count_nonzero(ng.spikes[b_mask]) >= 5)


def run_cycles(n_cycles, inject_pulse, learn_mode, mark_elig):
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
                    ng.release_da(+DA_CTRL if learn_mode == "reward" else -DA_CTRL)
        if fired_win:
            events += 1
    chaos = bg_fire / bg_steps if bg_steps else 0.0
    return events, chaos


print("预学习后 w:", w_xb())
ng.learn_gate = False
f_base, c1 = run_cycles(P1_CYCLES, x_n, "none", False)
print(f"P1 后: f_base={f_base/P1_CYCLES*100:.1f}% chaos={c1:.2f} w={w_xb()}")
ng.learn_gate = True
ng.da = 0.0
ng.da_expected = 0.0
lm = "none" if mode == "neutral" else mode
f_inter, c2 = run_cycles(P2_CYCLES, x_n, lm, True)
print(f"P2 后: f_inter={f_inter/P2_CYCLES*100:.1f}% chaos={c2:.2f} w={w_xb()} da={ng.da:.2f}")
ng.learn_gate = False
ng.da = 0.0
variants = {k: (x_n if k == 16 else make_variant(rng, x_n, pool, k)) for k in VARIANTS}
for k in VARIANTS:
    ev, _ = run_cycles(P3_CYCLES, variants[k], "none", False)
    print(f"P3 k={k}: f={ev/P3_CYCLES*100:.0f}% w={w_xb()}")
print("最终 w:", w_xb())
