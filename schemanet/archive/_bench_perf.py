# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""临时性能测量：定式网络（SchemaNet）内存与耗时实测（n=2048 语言实验）。"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import jieba

from schema_net import SchemaNet, _word_pattern, _learn_sentence
from schema_net import _evaluate_schemanet, _BigramModel, _evaluate_ngram
from collections import Counter

try:
    import psutil
    HAVE_PSUTIL = True
except ImportError:
    HAVE_PSUTIL = False


def rss_mb():
    if HAVE_PSUTIL:
        return psutil.Process(os.getpid()).memory_info().rss / 1024 ** 2
    return -1.0


def theoretical_mb(n, slots, dtype_bytes=8):
    w = n * slots * n * dtype_bytes / 1024 ** 2          # W[n, slots, n]
    v = n * slots * dtype_bytes / 1024 ** 2               # v[n, slots]
    misc = (n * dtype_bytes * 2 + n * 4 * 2) / 1024 ** 2  # spikes+pre_trace+refractory+last_k
    return w, v, misc


n, k, kv, split = 2048, 8, 300, 80
corpus = json.loads(Path("data/corpus.json").read_text(encoding="utf-8"))
tokenized = [jieba.lcut(s) for s in corpus]
freq = Counter(w for toks in tokenized for w in toks)
vocab = [w for w, _ in freq.most_common(kv)]
pats = {w: _word_pattern(n, k, w) for w in vocab}
rng_split = np.random.default_rng(42 + 9000)
perm = rng_split.permutation(len(tokenized))
train_toks = [tokenized[i] for i in perm[:split]]
test_toks = [tokenized[i] for i in perm[split:]]

print(f"=== 理论内存（n={n}, slots=4, float64）===")
w, v, m = theoretical_mb(n, 4)
print(f"  W = {w:.1f} MB | v = {v:.2f} MB | 杂项 = {m:.2f} MB")
w32, _, _ = theoretical_mb(32, 4)
print(f"  对照 n=32: W = {w32:.1f} MB")
print(f"  psutil 可用: {HAVE_PSUTIL}  当前进程 RSS: {rss_mb():.1f} MB")

ng = SchemaNet(n=n, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
               w_max=16.0, wta_k=8, noise_p=0.06, noise_amp=0.5,
               weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
               refractory=1, rng=np.random.default_rng(42 + 5000))

# ── 训练计时 ──
t0 = time.perf_counter()
for toks in train_toks:
    _learn_sentence(ng, toks, pats, slot=0)
t_train = time.perf_counter() - t0
nz = int((ng.W != 0).sum())
total = ng.W.size
print(f"\n=== 训练（{split} 句）===")
print(f"  耗时: {t_train:.2f}s")
print(f"  W 非零元素: {nz:,} / {total:,} = {nz/total*100:.2f}%")
print(f"  训练后 RSS: {rss_mb():.1f} MB")

ng.learn_gate = False

# ── 评估计时 ──
outsum = {a: sum(float(np.sum(ng.W[j, 0, src]))
                 for j in range(n) for src in pats[a])
          for a in vocab}
t0 = time.perf_counter()
sn_echo_train = _evaluate_schemanet(ng, train_toks, pats, vocab,
                                    min_cov=0.4, readout="echo")
t_echo = time.perf_counter() - t0
t0 = time.perf_counter()
sn_wsum_train = _evaluate_schemanet(ng, train_toks, pats, vocab, readout="wsum")
t_wsum = time.perf_counter() - t0
t0 = time.perf_counter()
bi = _BigramModel(train_toks)
bi_train = _evaluate_ngram(bi, train_toks)
t_bi = time.perf_counter() - t0
print("\n=== 评估（80 训练句全位置）===")
print(f"  回响读出: {t_echo:.2f}s  准确率 {sn_echo_train[0]:.3f}")
print(f"  W聚合读出: {t_wsum:.2f}s  准确率 {sn_wsum_train[0]:.3f}")
print(f"  bigram: {t_bi:.2f}s  准确率 {bi_train[0]:.3f}")

# ── 稀疏性分布：按神经元/槽的非零行分布 ──
per_slot = []
for s in range(4):
    per_slot.append(int((ng.W[:, s, :] != 0).sum()))
print(f"\n=== W 非零分布（按槽）===")
for s, cnt in enumerate(per_slot):
    print(f"  槽{s}: {cnt:,} ({cnt/ng.W[:, s, :].size*100:.2f}%)")
print(f"  结束 RSS: {rss_mb():.1f} MB")
