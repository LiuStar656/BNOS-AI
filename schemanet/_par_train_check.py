# -*- coding: utf-8 -*-
"""并行 Hebbian 训练可行性验证：分块训练 + W 合并 vs 顺序训练，对比 top-1。

背景：Hebbian 学习是加法可交换的（同对共现多次 = 强度累加），句子间顺序
理论上不影响最终权重。但 WTA 竞争依赖当前 W 状态（先学连接影响后续发放），
分块并行会让每块在"不同初始 W"上学习 → 连接集可能偏差。本脚本量化偏差：
若 top-1 差异 < 2%（噪声窗口），并行方案成立 → L1 20 万句可 8 进程 ~8 分钟。

流程：
  ① 顺序训练 8000 句 → W_seq → top-1（wsum，测试子集）
  ② 4 进程 × 2000 句并行 → 合并 W_par（Σ，clip w_max）→ top-1
  ③ 对比 + W 结构差异（连接数、权重分布）

用法：python _par_train_check.py
"""
import json
import multiprocessing as mp
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from schema_net import _word_pattern, _learn_sentence
from sparse_net import (SparseSchemaNet, _pats_matrix, outsum_sparse,
                        build_score_mat, evaluate_wsum_smat)

N, K = 8192, 16
KV = 3000
UNK = "<UNK>"
SEED = 42
N_TRAIN = 8000          # 验证规模
N_PARTS = 4             # 并行分块数
ETA = 0.1
W_MAX = 16.0

with open(Path("data/corpus_open.json"), encoding="utf-8") as f:
    _corpus = json.load(f)


def _build():
    freq = Counter(w for toks in _corpus for w in toks)
    vocab = [UNK] + [w for w, _ in freq.most_common(KV + 100) if w != UNK][:KV - 1]
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    return vocab, pats


_VOCAB, _PATS = _build()


def mk_net(seed):
    return SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=ETA,
                           w_max=W_MAX, wta_k=K, noise_p=0.06, noise_amp=0.5,
                           weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5,
                           stdp_neg=0.0, refractory=1,
                           rng=np.random.default_rng(seed))


def train_chunk(chunk, seed):
    ng = mk_net(seed)
    for toks in chunk:
        _learn_sentence(ng, toks, _PATS, slot=0)
    return ng


def merge(W_list, sf_list):
    n, slots = N, 4
    W_out = [[{} for _ in range(slots)] for _ in range(n)]
    slot_freq = np.zeros((n, slots), dtype=np.int32)
    for W, sf in zip(W_list, sf_list):
        for i in range(n):
            for k in range(slots):
                row = W[i][k]
                if row:
                    out = W_out[i][k]
                    for j, w in row.items():
                        out[j] = min(out.get(j, 0.0) + w, W_MAX)
        slot_freq += sf
    return W_out, slot_freq


def main():
    t_all = time.time()
    rng = np.random.default_rng(SEED + 9)
    perm = rng.permutation(len(_corpus))
    n_train = int(len(_corpus) * 0.8)
    train = [_corpus[i] for i in perm[:n_train]][:N_TRAIN]
    test = [_corpus[i] for i in perm[n_train:]]
    ev = [test[i] for i in
          rng.choice(len(test), min(600, len(test)), replace=False)]
    print(f"验证规模：训练 {len(train)} 句，测试 {len(ev)} 句", flush=True)

    # ── ① 顺序训练 ──
    t0 = time.time()
    ng_seq = mk_net(SEED + 5000)
    for toks in train:
        _learn_sentence(ng_seq, toks, _PATS, slot=0)
    dt_seq = time.time() - t0
    ng_seq.learn_gate = False
    pats_mat = _pats_matrix(_PATS, _VOCAB)
    outsum = outsum_sparse(ng_seq, _PATS, _VOCAB, slot=0)
    S = build_score_mat(ng_seq, _PATS, _VOCAB, pats_mat, slot=0)
    top1_seq = evaluate_wsum_smat(S, _VOCAB, ev, norm_base=outsum)[0]
    nnz_seq = sum(len(row) for i in range(N) for row in [ng_seq.W_out[i][0]])
    print(f"① 顺序训练 {dt_seq:.1f}s  top-1={top1_seq:.4f}  nnz={nnz_seq}", flush=True)

    # ── ② 并行分块训练 + 合并 ──
    k = len(train) // N_PARTS
    chunks = [train[i * k:(i + 1) * k] for i in range(N_PARTS)]
    chunks[-1] = train[(N_PARTS - 1) * k:]
    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ctx.Pool(N_PARTS) as pool:
        nets = pool.starmap(train_chunk,
                            [(list(c), SEED + 5000 + 1000 * i)
                             for i, c in enumerate(chunks)])
    dt_par = time.time() - t0
    W_list = [ng.W_out for ng in nets]
    sf_list = [ng.slot_freq for ng in nets]
    W_out, slot_freq = merge(W_list, sf_list)

    ng_par = mk_net(0)                      # 占位（立即覆盖）
    ng_par.W_out = W_out
    ng_par.slot_freq = slot_freq
    ng_par.learn_gate = False
    outsum_p = outsum_sparse(ng_par, _PATS, _VOCAB, slot=0)
    Sp = build_score_mat(ng_par, _PATS, _VOCAB, pats_mat, slot=0)
    top1_par = evaluate_wsum_smat(Sp, _VOCAB, ev, norm_base=outsum_p)[0]
    nnz_par = sum(len(row) for i in range(N) for row in [W_out[i][0]])
    print(f"② 并行 {N_PARTS} 进程（训练+合并）{dt_par:.1f}s  top-1={top1_par:.4f}  "
          f"nnz={nnz_par}", flush=True)

    # ── ③ 对比 ──
    d = top1_par - top1_seq
    ok = abs(d) < 0.02
    print(f"\ntop-1: 顺序 {top1_seq:.4f} vs 并行合并 {top1_par:.4f}  "
          f"Δ={d:+.4f}（{'✓ <2% 成立' if ok else '✗ 偏差过大'}）")
    print(f"nnz: 顺序 {nnz_seq} vs 并行 {nnz_par}（{100 * nnz_par / max(1, nnz_seq) - 100:+.1f}%）")
    print(f"总耗时 {time.time() - t_all:.1f}s")


if __name__ == "__main__":
    main()
