# -*- coding: utf-8 -*-
"""对拍：增量 trace 评估（evaluate_schemanet_trace_inc）vs 重放 trace
（evaluate_schemanet_sparse readout='trace'）——验证语义逐位一致。"""
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
                        evaluate_schemanet_sparse, evaluate_schemanet_trace_inc)

N, K, KV = 8192, 16, 2000
SEED = 42


def main():
    import os
    noise_p = float(os.environ.get("CHECK_NOISE", "0.06"))
    corpus = json.loads(Path("data/corpus_biased.json").read_text(encoding="utf-8"))
    tokenized = [jieba.lcut(s) for s in corpus[:300]]
    freq = Counter(w for toks in tokenized for w in toks)
    vocab = [w for w, _ in freq.most_common(KV)]
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)

    ng = SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=16.0, wta_k=K, noise_p=noise_p, noise_amp=0.5,
                         weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                         refractory=1, rng=np.random.default_rng(SEED + 5000))
    for toks in tokenized:
        _learn_sentence(ng, toks, pats, slot=0)
    ng.learn_gate = False
    outsum = outsum_sparse(ng, pats, vocab, slot=0)

    t0 = time.time()
    r_old = evaluate_schemanet_sparse(ng, tokenized, pats, vocab, pats_mat,
                                      readout="trace", norm_base=outsum, delta_off=0.02)
    t_old = time.time() - t0
    t0 = time.time()
    r_new = evaluate_schemanet_trace_inc(ng, tokenized, pats, vocab, pats_mat,
                                         norm_base=outsum, delta_off=0.02)
    t_new = time.time() - t0
    print(f"noise_p={noise_p}  重放 trace: {r_old[0]:.4f} ({t_old:.1f}s)  "
          f"增量 trace: {r_new[0]:.4f} ({t_new:.1f}s)")
    print(f"hits {r_old[1]} == {r_new[1]}?  total {r_old[2]} == {r_new[2]}?")
    ok = r_old[1] == r_new[1] and r_old[2] == r_new[2]
    for a, b in zip(r_old[3], r_new[3]):
        if a != b:
            ok = False
            print(f"  不一致: {a} vs {b}")
    print(f"对拍 {'PASS' if ok else 'FAIL（差异应为噪声级 RNG 序列，noise_p=0 时需逐位一致）'}")


if __name__ == "__main__":
    import os
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    main()
