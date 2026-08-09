# -*- coding: utf-8 -*-
"""step() 热点 profile：跑 200 句 Hebbian 训练，定位时间分布。
用法：python _bench_step.py
"""
import cProfile
import io
import pstats
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from schema_net import _word_pattern, _learn_sentence
from sparse_net import SparseSchemaNet

N, K = 8192, 16
SEED = 42

rng = np.random.default_rng(SEED + 5)
vocab = [f"w{i}" for i in range(3000)]
pats = {w: _word_pattern(N, K, w) for w in vocab}

# 模拟语料：随机句（词频 Zipf 分布，贴近真实）
freq = np.random.zipf(1.5, 200000)
maxf = int(freq.max())
corpus = []
for _ in range(200):
    n_tok = int(np.random.randint(3, 15))
    toks = []
    for _ in range(n_tok):
        toks.append(vocab[freq[np.random.randint(len(freq))] % len(vocab)])
    corpus.append(toks)

ng = SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                     w_max=16.0, wta_k=K, noise_p=0.06, noise_amp=0.5,
                     weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                     refractory=1, rng=np.random.default_rng(SEED + 5000))

t0 = time.time()
for toks in corpus:
    _learn_sentence(ng, toks, pats, slot=0)
dt = time.time() - t0
nnz = sum(len(row) for i in range(N) for row in [ng.W_out[i][0]])
print(f"200 句训练 {dt:.2f}s，W 非零 {nnz}（{nnz / (N * N):.4%}），"
      f"平均每句 {dt / 200 * 1000:.1f}ms", flush=True)

# 全程 profile（再跑一遍抓统计）
ng2 = SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                      w_max=16.0, wta_k=K, noise_p=0.06, noise_amp=0.5,
                      weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                      refractory=1, rng=np.random.default_rng(SEED + 5000))


def run():
    for toks in corpus:
        _learn_sentence(ng2, toks, pats, slot=0)


pr = cProfile.Profile()
pr.enable()
run()
pr.disable()
s = io.StringIO()
ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
ps.print_stats(18)
print(s.getvalue())
