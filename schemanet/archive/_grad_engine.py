# -*- coding: utf-8 -*-
"""grad(train_ctx 冻结 W) 引擎 top-1 评估：与 wsum/trace/pahe 同口径（同 W 同评估子集）。

对照值（runs/20260809_125334，train_w 后 W 上评估）：
  wsum 0.0722 / trace 0.0850 / pahe 0.0780（n=24866）

用法：python _grad_engine.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from schema_net import _word_pattern
from sparse_net import _pats_matrix, load_net
from grad_readout import GradReadout
from _accept_scale20w import CORPUS, EVAL_SUB_TEST, K, MAXLEN, N, SEED

MODEL = "runs/20260809_125334/net.npz"
GRPS = ((1, 1), (2, 2), (3, 3), (4, 5), (6, 8), (9, 30))
TAGS = ["t1", "t2", "t3", "t4-5", "t6-8", "t9+"]


def gname(t):
    for i, (lo, hi) in enumerate(GRPS):
        if lo <= t <= hi:
            return i
    return len(GRPS) - 1


def main():
    ng, vocab, ctx = load_net(MODEL, seed=42, return_ctx=True)
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)

    # 复现 125334 同评估子集（rng(SEED+9000) 同序列）
    tokenized = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
    rng = np.random.default_rng(SEED + 9000)
    perm = rng.permutation(len(tokenized))
    n_train = int(len(tokenized) * 0.8)
    test_toks = [tokenized[i] for i in perm[n_train:]]
    ev_te = [test_toks[i] for i in
             rng.choice(len(test_toks), min(EVAL_SUB_TEST, len(test_toks)),
                        replace=False)]
    print(f"评估 {len(ev_te)} 句（与 125334 同子集）", flush=True)

    ro = GradReadout(ng, pats, vocab, pats_mat, maxlen=MAXLEN)
    ro.build_score_matrix()
    if ctx is not None:
        ro.ctx_wgt = np.array(ctx, dtype=float)
        s = float(ro.ctx_wgt.sum())
        if s > 0:
            ro.ctx_wgt = ro.ctx_wgt / s
    print(f"ctx_wgt(模型保存): {np.round(ro.ctx_wgt, 4)}", flush=True)

    acc, hits, total, samples = ro.evaluate(ev_te)
    print(f"grad(train_ctx 快路径) top-1 总: {acc:.4f}  n={total}", flush=True)

    # 位置分层（同 GRPS 口径）
    h, tot = Counter(), Counter()
    for toks in ev_te:
        ids = [ro.vocab_idx[w] for w in toks if w in ro.vocab_idx]
        for t in range(1, len(ids)):
            logits = ro.logits(ids[:t]).copy()
            logits[logits <= 0] = -np.inf
            for wid in ids[:t]:
                logits[wid] = -np.inf
            cand = int(np.argmax(logits))
            g = gname(t)
            tot[g] += 1
            if ro.vocab[cand] == toks[t]:
                h[g] += 1
    print("位置分层:", {TAGS[i]: (round(h[i] / tot[i], 4) if tot[i] else None)
                       for i in range(6)}, flush=True)
    print("对照 125334（同 W 同评估）: wsum 0.0722 / trace 0.0850 / pahe 0.0780",
          flush=True)


if __name__ == "__main__":
    main()
