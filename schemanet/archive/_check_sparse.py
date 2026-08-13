# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""对拍验证：SparseSchemaNet 与稠密 SchemaNet 行为一致（Phase 2 验收项 2）。

同 seed 同噪声序列 → 学习结果逐值一致：
  ① W 非零项逐项比对（稀疏字典 vs 稠密矩阵）
  ② outsum 源词出边总强度一致
  ③ wsum / trace 训练集评估准确率一致

用法：python _check_sparse.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import jieba

from schema_net import SchemaNet, _word_pattern, _learn_sentence
from sparse_net import (SparseSchemaNet, _pats_matrix, predict_cands_wsum_sparse,
                        predict_cands_trace_sparse, outsum_sparse,
                        evaluate_schemanet_sparse)

N = 2048
K = 8
SEED = 42
SLOTS = 4

corpus = json.loads(Path("data/corpus.json").read_text(encoding="utf-8"))
tokenized = [jieba.lcut(s) for s in corpus]
from collections import Counter
freq = Counter(w for toks in tokenized for w in toks)
vocab = [w for w, _ in freq.most_common(300)]
pats = {w: _word_pattern(N, K, w) for w in vocab}

rng_split = np.random.default_rng(SEED + 9000)
perm = rng_split.permutation(len(tokenized))
train_toks = [tokenized[i] for i in perm[:80]]


def mk_dense():
    return SchemaNet(n=N, slots=SLOTS, theta=1.0, membrane_decay=0.9, eta=0.1,
                     w_max=16.0, wta_k=K, noise_p=0.06, noise_amp=0.5,
                     weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                     refractory=1, rng=np.random.default_rng(SEED + 5000))


def mk_sparse():
    return SparseSchemaNet(n=N, slots=SLOTS, theta=1.0, membrane_decay=0.9, eta=0.1,
                           w_max=16.0, wta_k=K, noise_p=0.06, noise_amp=0.5,
                           weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                           refractory=1, rng=np.random.default_rng(SEED + 5000))


nd = mk_dense()
ns = mk_sparse()
for toks in train_toks:
    _learn_sentence(nd, toks, pats, slot=0)
    _learn_sentence(ns, toks, pats, slot=0)
nd.learn_gate = False
ns.learn_gate = False

# ── ① W 非零项逐项比对 ──
diff = 0
max_err = 0.0
s_missing = 0
for i in range(N):
    for k in range(SLOTS):
        row_s = ns.W_out[i][k]
        # 稠密 W[j, k, i]（i 出边视角 = 稠密入边转置）
        for j, w in row_s.items():
            wd = float(nd.W[j, k, i])
            err = abs(wd - w)
            if err > max_err:
                max_err = err
            if err > 1e-9:
                diff += 1
        # 稀疏缺失项：稠密非零但稀疏没有
        for j in range(N):
            wd = float(nd.W[j, k, i])
            if wd > 0 and j not in row_s:
                s_missing += 1
nnz_s = sum(len(row) for rows in ns.W_out for row in rows)
print(f"① W 对拍：稀疏非零 {nnz_s}，值不一致 {diff}（max_err={max_err:.2e}），稀疏缺失 {s_missing}")

# ── ② outsum ──
os_d = {a: sum(float(np.sum(nd.W[j, 0, src])) for j in range(N) for src in pats[a])
        for a in vocab}
os_s = outsum_sparse(ns, pats, vocab, slot=0)
os_diff = sum(abs(os_d[a] - os_s[a]) for a in vocab if abs(os_d[a] - os_s[a]) > 1e-9)
print(f"② outsum 对拍：差异词数 {os_diff}/{len(vocab)}")

def evaluate_dense(ng, toks_list, pats, vocab, readout="wsum", norm_base=None):
    from schema_net import _evaluate_schemanet
    return _evaluate_schemanet(ng, toks_list, pats, vocab, readout=readout,
                               norm_base=norm_base)


# ── ③ 评估准确率（wsum / trace）──
pats_mat = _pats_matrix(pats, vocab)
wsum_d = evaluate_dense(nd, train_toks, pats, vocab, readout="wsum")
wsum_s = evaluate_schemanet_sparse(ns, train_toks, pats, vocab, pats_mat, readout="wsum")
tr_d = evaluate_dense(nd, train_toks, pats, vocab, readout="trace", norm_base=os_d)
tr_s = evaluate_schemanet_sparse(ns, train_toks, pats, vocab, pats_mat,
                                 readout="trace", norm_base=os_s)
print(f"③ 评估对拍：wsum 稠密 {wsum_d[0]:.4f} vs 稀疏 {wsum_s[0]:.4f}"
      f" | trace 稠密 {tr_d[0]:.4f} vs 稀疏 {tr_s[0]:.4f}")

ok = (diff == 0 and s_missing == 0 and os_diff == 0
      and abs(wsum_d[0] - wsum_s[0]) < 1e-9 and abs(tr_d[0] - tr_s[0]) < 1e-9)
print("对拍结论:", "PASS ✓" if ok else "FAIL ✗")
