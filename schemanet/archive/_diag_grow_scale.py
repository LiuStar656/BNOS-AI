# -*- coding: utf-8 -*-
"""诊断4：训练 max_steps=1（注入一步共发放即学）vs 传播的边数与混入。"""
import json
import time
from pathlib import Path

import numpy as np

from schema_net import build_pulse
from sparse_net import SparseSchemaNet, allocate_pats

DATA = Path(__file__).parent / "data" / "curriculum"
K, SEED = 4, 42


def run_train(ng, pulse, max_steps, clear_trace=True):
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    if clear_trace:
        ng.pre_trace = np.zeros(ng.n)   # 跟读是独立事件，不留跨词痕迹（防 STDP 污染）
    ng.step(pulse, slot=0)
    for _ in range(max_steps - 1):
        ng.step(np.zeros(ng.n), slot=0)
        if not ng.spikes.any():
            break


def edge_count(ng):
    return sum(len(r) for rows in ng.W_out for r in rows)


def main():
    hanzi = json.loads((DATA / "stage0_hanzi.json").read_text(encoding="utf-8"))
    words = json.loads((DATA / "stage1_common_words.json").read_text(encoding="utf-8"))[:1000]
    for ms in (1, 3, 10):
        ng = SparseSchemaNet(n=16384, slots=4, theta=1.0, wta_k=4, noise_p=0.06,
                             noise_amp=0.5, refractory=1, rng=np.random.default_rng(SEED))
        pats, cursor = allocate_pats(ng, hanzi, K)
        pats_w, cursor = allocate_pats(ng, words, K, cursor)
        pats.update(pats_w)
        t0 = time.time()
        for w in words:
            chars = [c for c in w if c in pats]
            neurons = list(pats[w]) + [i for c in chars for i in pats[c]]
            ng.wta_k = len(neurons)
            run_train(ng, build_pulse(ng.n, neurons), ms, clear_trace=True)
        dt = time.time() - t0
        print(f"max_steps={ms} 清trace: 1 轮 {dt:.1f}s ({dt/len(words)*1000:.0f}ms/词)  边数={edge_count(ng)}", flush=True)


if __name__ == "__main__":
    main()
