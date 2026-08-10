# -*- coding: utf-8 -*-
"""追踪：喂 3 词后结尾回响 4 步，每步发放与新增边（验证噪声累积发放假说）。"""
from snapshot import load_version
from schema_net import build_pulse
import numpy as np


def snap(ng):
    return {(i, k, j): w for i in range(ng.n) for k in range(ng.slots)
            for j, w in ng.W_out[i][k].items()}


ng, v, pats, c = load_version("16.0")
n2w = {j: w for w, ns in pats.items() for j in ns}
before = snap(ng)
seq = ["不错", "什么", "中国"]
ng.v = np.zeros((ng.n, ng.slots))
ng.spikes = np.zeros(ng.n)
ng.pre_trace = np.zeros(ng.n)
for w in seq:
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.step(build_pulse(ng.n, pats[w]), slot=0)
    ng.spikes = np.zeros(ng.n)
    ng.step(np.zeros(ng.n), slot=0)
print("=== 结尾回响 4 步（v 不清，spikes 清）===")
cur = snap(ng)
for t in range(4):
    ng.spikes = np.zeros(ng.n)
    sp = ng.step(np.zeros(ng.n), slot=0)
    fired = np.where(sp > 0)[0]
    nxt = snap(ng)
    new = [k for k in nxt if k not in cur]
    names = sorted({n2w.get(i, "?") for i in fired})[:3]
    print(f"回响步{t}: 发放 {len(fired)} 神经元 {names}，新增边 {len(new)}")
    cur = nxt
