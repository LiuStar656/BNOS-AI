# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""trace β 扫描：有偏语料下放大混合分支非末词权重，验证 trace 破局是否参数问题。

加载 runs/20260809_064139/net.npz（train_w 精调后 W，与 _accept_gen 同源），
对留出集跑 trace 增量评估，β ∈ {0.1, 0.3, 0.5, 0.8, 1.0}。
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jieba

from schema_net import _word_pattern
from sparse_net import (load_net, _pats_matrix, outsum_sparse,
                        evaluate_schemanet_trace_inc)

N, K = 8192, 16
SEED = 42
NET = Path("runs/20260809_064139/net.npz")


def main():
    ng, vocab = load_net(NET)
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)
    outsum = outsum_sparse(ng, pats, vocab, slot=0)

    corpus = json.loads(Path("data/corpus_biased.json").read_text(encoding="utf-8"))
    tokenized = [jieba.lcut(s) for s in corpus]
    freq = Counter(w for toks in tokenized for w in toks)
    vocab_set = set(vocab)
    toks_in = [[w for w in toks if w in vocab_set] for toks in tokenized]
    toks_in = [t for t in toks_in if len(t) >= 2]
    rng = np.random.default_rng(SEED + 9000)
    perm = rng.permutation(len(toks_in))
    n_train = int(len(toks_in) * 0.8)
    test_toks = [toks_in[i] for i in perm[n_train:]]
    print(f"留出集 {len(test_toks)} 句")

    for beta in [0.1, 0.3, 0.5, 0.8, 1.0]:
        t0 = time.time()
        r = evaluate_schemanet_trace_inc(ng, test_toks, pats, vocab, pats_mat,
                                         norm_base=outsum, delta_off=0.02,
                                         trace_beta=beta)
        print(f"trace β={beta}: top-1 {r[0]:.4f}  ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    import os
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    main()
