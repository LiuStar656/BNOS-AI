# -*- coding: utf-8 -*-
"""调试：叫→爸爸 边存在（16.0）但「叫」唤起带不出爸爸——定位传播断点。"""
import numpy as np
from schema_net import build_pulse
from snapshot import load_snapshot
from sparse_net import allocate_pats

BASE = "runs/v52_2_20260811_183718"
ng, vocab, pats, cursor = load_snapshot(BASE)
ng, vocab, pats, cursor = load_snapshot(BASE)
K = 4

def teach_once(seq, amps):
    ng.v = np.zeros((ng.n, ng.slots)); ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)
    ng.release_da(2.0)
    for w, amp in zip(seq, amps):
        ng.spikes = np.zeros(ng.n)
        ng.step(build_pulse(ng.n, pats[w], amp), slot=0)
        ng.spikes = np.zeros(ng.n)
        ng.step(np.zeros(ng.n), slot=0)
    ng.release_da(2.0)

# 教学 3 次
for _ in range(3):
    teach_once(["叫", "爸爸"], [1.0, 4.0])

baba = np.array(pats["爸爸"]); jiao = np.array(pats["叫"])
print("叫→爸爸 边:")
for i in jiao:
    row = ng.W_out[i][0]
    print(f"  {i}: {[(int(j), w) for j, w in row.items() if int(j) in baba]}")

# 冻结检索逐步调试
ng.v = np.zeros((ng.n, ng.slots)); ng.spikes = np.zeros(ng.n); ng.pre_trace = np.zeros(ng.n)
gate = ng.learn_gate; ng.learn_gate = False

print("\n-- 注入叫 --")
s = ng.step(build_pulse(ng.n, jiao, 1.0), slot=0)
fired = set(np.where(ng.spikes > 0)[0])
print("  spikes:", sorted(fired))
print("  爸爸 v:", ng.v[baba, 0])

print("\n-- 空拍1 --")
ng.spikes = np.zeros(ng.n)
s = ng.step(np.zeros(ng.n), slot=0)
fired = set(np.where(ng.spikes > 0)[0])
print("  spikes:", sorted(fired), "  爸爸 v:", ng.v[baba, 0])

print("\n-- 空拍2 --")
ng.spikes = np.zeros(ng.n)
s = ng.step(np.zeros(ng.n), slot=0)
fired = set(np.where(ng.spikes > 0)[0])
print("  spikes:", sorted(fired), "  爸爸 v:", ng.v[baba, 0])
ng.learn_gate = gate

# 直接看传播 drive
print("\n-- 手动传播检查 --")
ng.v = np.zeros((ng.n, ng.slots)); ng.spikes = np.zeros(ng.n); ng.pre_trace = np.zeros(ng.n)
ng.step(build_pulse(ng.n, jiao, 1.0), slot=0)
print("  注入拍后 _drive_any[爸爸]:", ng._drive_any[baba])
print("  注入拍后 v[爸爸]:", ng.v[baba, 0])
print("  注入拍 spikes:", sorted(set(np.where(ng.spikes > 0)[0])))
