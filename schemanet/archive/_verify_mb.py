# -*- coding: utf-8 -*-
"""mini-batch 重构快速验证：batch=1（原语义）vs batch=32（重构）。
小规模子集跑通：时间对比 + top-1 对比 + W 结构不变 + 语义等价性检查。"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import jieba

from schema_net import _word_pattern, _learn_sentence
from sparse_net import (SparseSchemaNet, _pats_matrix, outsum_sparse,
                        evaluate_schemanet_sparse)
from grad_readout import GradReadout

N, K, KV = 8192, 16, 2000
MAXLEN = 5
SEED = 42


def build_net_and_positions(n_train_max=None):
    corpus = json.loads(Path("data/corpus_large.json").read_text(encoding="utf-8"))
    tokenized = [jieba.lcut(s) for s in corpus]
    freq = Counter(w for toks in tokenized for w in toks)
    vocab = [w for w, _ in freq.most_common(KV)]
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    rng = np.random.default_rng(SEED + 9000)
    perm = rng.permutation(len(tokenized))
    n_train = int(len(tokenized) * 0.8)
    train_toks = [tokenized[i] for i in perm[:n_train]]
    test_toks = [tokenized[i] for i in perm[n_train:]]
    if n_train_max:
        train_toks = train_toks[:n_train_max]
        test_toks = test_toks[:max(20, n_train_max // 4)]
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)
    ng = SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=16.0, wta_k=K, noise_p=0.06, noise_amp=0.5,
                         weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                         refractory=1, rng=np.random.default_rng(SEED + 5000))
    for toks in train_toks:
        _learn_sentence(ng, toks, pats, slot=0)
    ng.learn_gate = False
    pos = []
    for toks in train_toks:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(1, len(ids)):
            pos.append((ids[:t], ids[t]))
    return ng, pats, vocab, vocab_idx, pats_mat, pos, test_toks, train_toks


def run_train_w(batch_size, pos, ng, pats, vocab, pats_mat, test_toks):
    ro = GradReadout(ng, pats, vocab, pats_mat, maxlen=MAXLEN)
    ro.snapshot_w()
    nnz0 = ro.nnz()
    ro.train_ctx(pos, lr=0.5, epochs=20, seed=SEED)
    t0 = time.time()
    t_w = ro.train_w(pos, lr=0.05, epochs=10, seed=SEED,
                     ctx_init=ro.ctx_wgt, subsample=500, batch_size=batch_size)
    nnz1 = ro.nnz()
    wd = ro.w_delta()
    acc, hits, total, _ = ro.evaluate_w(test_toks)
    return t_w, acc, hits, total, nnz0, nnz1, wd, ro


def main():
    print("构建语料（子集 300 句）...")
    ng1, pats, vocab, vocab_idx, pats_mat, pos, test_toks, _ = build_net_and_positions(300)

    # 同一初始 W 的两份拷贝（Hebbian 后冻结），各自 train_w
    import copy
    ng2 = copy.deepcopy(ng1)

    t1, acc1, h1, tot1, z01, z11, wd1, ro1 = run_train_w(1, pos, ng1, pats, vocab,
                                                         pats_mat, test_toks)
    print(f"batch=1 : {t1}s  留出 top-1 {acc1:.4f} ({h1}/{tot1})  结构 {z01}->{z11} "
          f"扰动 {wd1['n_changed']}/{wd1['n_tot']}")

    import copy as _c
    ng8 = _c.deepcopy(ng1)
    t8, acc8, h8, tot8, z08, z18, wd8, ro8 = run_train_w(8, pos, ng8, pats, vocab,
                                                         pats_mat, test_toks)
    print(f"batch=8 : {t8}s  留出 top-1 {acc8:.4f} ({h8}/{tot8})  结构 {z08}->{z18} "
          f"扰动 {wd8['n_changed']}/{wd8['n_tot']}")

    t32, acc32, h32, tot32, z032, z132, wd32, ro32 = run_train_w(32, pos, ng2, pats, vocab,
                                                                  pats_mat, test_toks)
    print(f"batch=32: {t32}s  留出 top-1 {acc32:.4f} ({h32}/{tot32})  结构 {z032}->{z132} "
          f"扰动 {wd32['n_changed']}/{wd32['n_tot']}")

    print(f"\n提速(batch=8): {t1 / t8:.1f}×（{t1}s -> {t8}s）  top-1 差 {acc8 - acc1:+.4f}")
    print(f"提速(batch=32): {t1 / t32:.1f}×（{t1}s -> {t32}s）  top-1 差 {acc32 - acc1:+.4f}")


if __name__ == "__main__":
    main()
