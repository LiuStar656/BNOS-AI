# -*- coding: utf-8 -*-
"""E6 neutral 组塌陷定位：追踪 Phase 1→2→3 的 B 组发放频率与疲劳（fat）轨迹。
对比 learn_gate=True / False 两种 Phase 2 状态——定位塌陷是疲劳累积、
状态漂移还是 learn_gate 影响。"""
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
NP, NA, SP, BM, PR = 0.05, 0.3, 0.15, 8, 2


def make_net(seed, gate):
    rng = np.random.default_rng(seed * 100 + 2)
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
    return ng, x_n, b_n, b_mask, pool


def trace(ng, x_n, b_n, b_mask, n_cycles, label, show_fat):
    """跑 n_cycles 注入，每 10 cycles 记录 f 与 B 组 fat 均值。返回发放事件。"""
    events = 0
    out = []
    for c in range(n_cycles):
        fired = False
        for si in range(INJECT_EVERY):
            if si == 0:
                ng.step(build_pulse(N, x_n, INJECT_AMP), slot=0)
            else:
                ng.step(np.zeros(N), slot=0)
            if not fired and si < WINDOW and np.count_nonzero(ng.spikes[b_mask]) >= BM:
                fired = True
        if fired:
            events += 1
        if (c + 1) % 10 == 0:
            fat = float(np.mean(ng.fat[b_n])) if show_fat else float("nan")
            out.append(f"{label} c{c+1:>3}: f={events/(c+1)*100:5.1f}%  fatB={fat:.3f}")
    return events, out


for gate in (False, True):
    ng, x_n, b_n, b_mask, pool = make_net(42, gate)
    print(f"\n═══ neutral 组 learn_gate(Phase2)={gate} ═══")
    w_xb = sum(ng.W_out[i][0].get(j, 0.0) for i in x_n
               for j in b_n if ng.W_out[i][0].get(j, 0.0) > 0)
    print(f"预学习后 w(X→B)={w_xb:.1f}")
    ng.learn_gate = False
    ev1, tr1 = trace(ng, x_n, b_n, b_mask, P1_CYCLES, "P1", True)
    ng.learn_gate = gate
    ev2, tr2 = trace(ng, x_n, b_n, b_mask, P2_CYCLES, "P2", True)
    ng.learn_gate = False
    ng.da = 0.0
    ev3, tr3 = trace(ng, x_n, b_n, b_mask, P3_CYCLES, "P3", True)
    print("\n".join(tr1))
    print("\n".join(tr2))
    print("\n".join(tr3))
    w_xb2 = sum(ng.W_out[i][0].get(j, 0.0) for i in x_n
                for j in b_n if ng.W_out[i][0].get(j, 0.0) > 0)
    print(f"结束后 w(X→B)={w_xb2:.1f}  f P1={ev1/P1_CYCLES*100:.0f}% "
          f"P2={ev2/P2_CYCLES*100:.0f}% P3={ev3/P3_CYCLES*100:.0f}%")
