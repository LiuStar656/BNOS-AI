# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""真实语料 step() 分节计时：定位传播/写入/WTA 各自占比。
用法：python _bench_step2.py
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema_net import _word_pattern, build_pulse
from sparse_net import SparseSchemaNet

N, K = 8192, 16
KV = 3000
UNK = "<UNK>"
SEED = 42

corpus = json.loads(Path("data/corpus_open.json").read_text(encoding="utf-8"))[:4000]
freq = Counter(w for toks in corpus for w in toks)
vocab = [UNK] + [w for w, _ in freq.most_common(KV + 100) if w != UNK][:KV - 1]
pats = {w: _word_pattern(N, K, w) for w in vocab}

ng = SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                     w_max=16.0, wta_k=K, noise_p=0.06, noise_amp=0.5,
                     weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                     refractory=1, rng=np.random.default_rng(SEED + 5000))

t_prop = t_wta = t_write = t_noise = 0.0
n_steps = 0


def step_timed(ng, input_pulse, slot=0):
    global t_prop, t_wta, t_write, t_noise, n_steps
    slot = min(slot, ng.slots - 1)
    t0 = time.perf_counter()
    noise = (ng.rng.random(ng.n) < ng.noise_p) * ng.noise_amp
    ng.v = ng.v * ng.membrane_decay + noise[:, None]
    ng.v[:, slot] += input_pulse
    t1 = time.perf_counter()
    if ng.spikes.any():
        for k in range(ng.slots):
            senders = np.where((ng.spikes > 0) & (ng.last_k_star == k))[0]
            if len(senders):
                drive = np.zeros(ng.n)
                for i in senders:
                    e = ng._edge_row(i, k)
                    if e is not None:
                        drive[e[0]] += e[1]
                ng.v[:, k] += drive
    t2 = time.perf_counter()
    k_star = ng.v.argmax(axis=1)
    vmax = ng.v[np.arange(ng.n), k_star]
    eligible = np.ones(ng.n, dtype=bool)
    if ng.refractory > 0:
        eligible = ng.refractory_left == 0
    candidates = np.where((vmax >= ng.theta) & eligible)[0]
    if len(candidates) > ng.wta_k:
        top = candidates[np.argsort(vmax[candidates])[::-1][: ng.wta_k]]
    else:
        top = candidates
    new_spikes = np.zeros(ng.n)
    if len(top):
        new_spikes[top] = 1.0
        if ng.learn_gate:
            for a in top:
                ka = int(k_star[a])
                for c in top:
                    if a == c:
                        continue
                    row = ng.W_out[c][ka]
                    nv = row.get(a, 0.0) + ng.eta
                    row[a] = nv if nv < ng.w_max else ng.w_max
                    ng._edge_dirty[c][ka] = True
            if (ng.stdp_pre > 0 or ng.stdp_neg > 0) and ng.pre_trace.any():
                pre_idx = np.where(ng.pre_trace > ng.trace_thres)[0]
                if ng.stdp_pre > 0 and len(pre_idx):
                    for jj in top:
                        kj = int(k_star[jj])
                        for pp in pre_idx:
                            if jj == pp:
                                continue
                            row = ng.W_out[pp][kj]
                            nv = row.get(jj, 0.0) + ng.stdp_pre
                            row[jj] = nv if nv < ng.w_max else ng.w_max
                            ng._edge_dirty[pp][kj] = True
    t3 = time.perf_counter()
    ng.v[top, :] = 0.0
    if ng.learn_gate and len(top):
        ng.slot_freq[top, k_star[top]] += 1
    ng.spikes = new_spikes
    ng.last_k_star = k_star
    ng.pre_trace = ng.pre_trace * ng.trace_decay + new_spikes
    if ng.refractory > 0:
        ng.refractory_left = np.maximum(ng.refractory_left - 1, 0)
        if len(top):
            ng.refractory_left[top] = ng.refractory
    t4 = time.perf_counter()
    t_noise += t1 - t0
    t_prop += t2 - t1
    t_wta += t3 - t2
    t_write += t4 - t3
    n_steps += 1
    return new_spikes


t0 = time.time()
for toks in corpus:
    for w in toks:
        step_timed(ng, build_pulse(N, pats[w]), slot=0)
        step_timed(ng, np.zeros(N), slot=0)
dt = time.time() - t0
nnz = sum(len(row) for i in range(N) for row in [ng.W_out[i][0]])
print(f"真实语料 {len(corpus)} 句 {dt:.1f}s（{dt / len(corpus) * 1000:.1f}ms/句，"
      f"{n_steps} 步，{dt / n_steps * 1000:.3f}ms/步）W 非零 {nnz}")
print(f"分节占比: noise {t_noise * 100 / dt:.1f}%  prop {t_prop * 100 / dt:.1f}%  "
      f"wta+write {t_wta * 100 / dt:.1f}%  reset {t_write * 100 / dt:.1f}%")
print(f"分节 ms/步: noise {t_noise / n_steps * 1000:.3f}  prop {t_prop / n_steps * 1000:.3f}  "
      f"wta+write {t_wta / n_steps * 1000:.3f}  reset {t_write / n_steps * 1000:.3f}")
