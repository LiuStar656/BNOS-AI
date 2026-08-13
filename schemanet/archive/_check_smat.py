# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""对拍：S 矩阵版评估器（build_score_mat + evaluate_wsum_smat + evaluate_trace_smat）
vs 原版（evaluate_schemanet_sparse / evaluate_schemanet_trace_inc）逐位一致。

用 corpus.json（100 句小语料，n=2048/k=8）快速验证语义等价。
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jieba

from schema_net import _word_pattern, _learn_sentence
from sparse_net import (SparseSchemaNet, _pats_matrix, outsum_sparse,
                        evaluate_schemanet_sparse, evaluate_schemanet_trace_inc,
                        build_score_mat, evaluate_wsum_smat, evaluate_trace_smat)

N, K = 2048, 8


def main():
    corpus = json.loads(Path("data/corpus.json").read_text(encoding="utf-8"))
    tokenized = [jieba.lcut(s) for s in corpus]
    vocab = list(dict.fromkeys(w for toks in tokenized for w in toks))
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)

    ng = SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=16.0, wta_k=K, noise_p=0.06, noise_amp=0.5,
                         weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                         refractory=1, rng=np.random.default_rng(42))
    for toks in tokenized:
        _learn_sentence(ng, toks, pats, slot=0)
    ng.learn_gate = False
    outsum = outsum_sparse(ng, pats, vocab, slot=0)

    S = build_score_mat(ng, pats, vocab, pats_mat, slot=0)
    print(f"词表 {len(vocab)}，S {S.shape}（{S.nbytes / 1e6:.1f}MB）")

    # wsum 对拍（norm_base=outsum）
    r_old = evaluate_schemanet_sparse(ng, tokenized, pats, vocab, pats_mat,
                                      readout="wnorm", norm_base=outsum)
    r_new = evaluate_wsum_smat(S, vocab, tokenized, norm_base=outsum)
    ok_w = r_old[1] == r_new[1]
    print(f"wsum: 原 {r_old[1]}/{r_old[2]} vs S版 {r_new[1]}/{r_new[2]}  {'PASS ✓' if ok_w else 'FAIL ✗'}")

    # trace 对拍（S 版 vs 原版）
    r_old = evaluate_schemanet_trace_inc(ng, tokenized, pats, vocab, pats_mat,
                                         norm_base=outsum, delta_off=0.02)
    r_new = evaluate_trace_smat(ng, tokenized, S, pats, vocab, outsum,
                                delta_off=0.02)
    ok_t = r_old[1] == r_new[1]
    print(f"trace: 原 {r_old[1]}/{r_old[2]} vs S版 {r_new[1]}/{r_new[2]}  {'PASS ✓' if ok_t else 'FAIL ✗'}")
    if not (ok_w and ok_t):
        for i, (a, b) in enumerate(zip(r_old[3], r_new[3])):
            if a != b:
                print(f"  差异@{i}: old={a} new={b}")
                break


if __name__ == "__main__":
    main()
