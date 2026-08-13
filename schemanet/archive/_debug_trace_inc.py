# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""单句级调试：定位增量 trace 与重放 trace 的逐位差异（noise_p=0 排除 RNG 因素）。"""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jieba

from schema_net import _word_pattern, _learn_sentence, build_pulse
from sparse_net import (SparseSchemaNet, _pats_matrix, outsum_sparse,
                        predict_cands_trace_sparse, _trace_cands_from_state)

N, K, KV = 8192, 16, 2000
SEED = 42


def main():
    corpus = json.loads(Path("data/corpus_biased.json").read_text(encoding="utf-8"))
    tokenized = [jieba.lcut(s) for s in corpus[:100]]
    freq = Counter(w for toks in tokenized for w in toks)
    vocab = [w for w, _ in freq.most_common(KV)]
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)

    ng = SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=16.0, wta_k=K, noise_p=0.0, noise_amp=0.5,
                         weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                         refractory=1, rng=np.random.default_rng(SEED + 5000))
    for toks in tokenized:
        _learn_sentence(ng, toks, pats, slot=0)
    ng.learn_gate = False
    outsum = outsum_sparse(ng, pats, vocab, slot=0)

    # 重放版逐句评估，记录每位置 pred 和 ng 状态快照
    n_diff = 0
    for s_idx, toks in enumerate(tokenized):
        for t in range(1, len(toks)):
            # 重放版
            cands_old = predict_cands_trace_sparse(ng, toks[:t], pats, vocab, pats_mat,
                                                   slot=0, norm_base=outsum,
                                                   delta_off=0.02)
            pred_old = cands_old[0][0] if cands_old else None
            # 状态快照（重放版留下）：v/spikes/pre_trace 已在调用内清+重放
            # 增量版：从干净状态重放前缀（模拟单句内增量 = 从空逐词注入）
            ng.v = np.zeros((ng.n, ng.slots))
            ng.spikes = np.zeros(ng.n)
            ng.pre_trace = np.zeros(ng.n)
            for w in toks[:t]:
                ng.v = np.zeros((ng.n, ng.slots))
                ng.step(build_pulse(N, pats[w]), slot=0)
                ng.step(np.zeros(N), slot=0)
            cands_new = _trace_cands_from_state(ng, toks[t - 1], toks[:t], pats,
                                                vocab, pats_mat, 0, outsum, 0.1, 0.02)
            pred_new = cands_new[0][0] if cands_new else None
            if pred_old != pred_new:
                n_diff += 1
                print(f"[{s_idx}] t={t} ctx={' '.join(toks[:t])} truth={toks[t]} "
                      f"old={pred_old} new={pred_new}")
                if n_diff > 10:
                    return
    print(f"共 {n_diff} 处差异")


if __name__ == "__main__":
    import os
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    main()
