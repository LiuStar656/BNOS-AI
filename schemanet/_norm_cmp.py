# -*- coding: utf-8 -*-
"""归一化变体对比（20 万干净 W，饱和修复零成本试）：
   验证：wsum 的 top-1 是否真的与列归一化无关（纯排序）？
         grad/candB 的混合读出是否受归一化影响（哪版最好）？

变体：colsum（现状，S 原始）/ colmax / softmax(τ=1) / softmax(τ=0.5)。
用法：python _norm_cmp.py [--model runs/20260809_151121/net_clean.npz]
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from schema_net import _word_pattern
from sparse_net import _pats_matrix, load_net
from grad_readout import GradReadout
from _accept_scale20w import (CORPUS, EVAL_SUB_TEST, K, MAXLEN, N, SEED,
                              GRP_TAGS, gname)
from _cand_readout import col_entropy, sharpness


def _softmax_cols(S, tau):
    x = S / tau
    e = np.exp(x - x.max(axis=0, keepdims=True))
    return e / e.sum(axis=0, keepdims=True)


def eval_wsum_top1(S, vocab, toks_list):
    """wsum 纯排序 top-1（无归一化，验证排序不变性）。"""
    vtab = {w: i for i, w in enumerate(vocab)}
    hits, total = Counter(), Counter()
    for toks in toks_list:
        for t in range(1, len(toks)):
            last = toks[t - 1]
            p = S[:, vtab[last]]
            used = set(toks[:t])
            order = np.argsort(-p)
            cand = next((wi for wi in order if p[wi] > 0 and wi not in used), None)
            g = gname(t)
            total[g] += 1
            if cand is not None and vocab[cand] == toks[t]:
                hits[g] += 1
    return {GRP_TAGS[i]: (hits[i] / total[i] if total[i] else None)
            for i in range(len(GRP_TAGS))}, int(sum(total.values()))


def eval_grad_top1(ro, toks_list):
    hits, total = Counter(), Counter()
    for toks in toks_list:
        ids = [ro.vocab_idx[w] for w in toks if w in ro.vocab_idx]
        for t in range(1, len(ids)):
            logits = ro.logits(ids[:t]).copy()
            logits[logits <= 0] = -np.inf
            for wid in ids[:t]:
                logits[wid] = -np.inf
            g = gname(t)
            total[g] += 1
            if ro.vocab[int(np.argmax(logits))] == toks[t]:
                hits[g] += 1
    return {GRP_TAGS[i]: (hits[i] / total[i] if total[i] else None)
            for i in range(len(GRP_TAGS))}, int(sum(total.values()))


def eval_candb_top1(Sn, sharp, vocab, toks_list, w_b=0.5):
    vtab = {w: i for i, w in enumerate(vocab)}
    hits, total = Counter(), Counter()
    for toks in toks_list:
        ids = [vtab[w] for w in toks if w in vtab]
        for t in range(1, len(ids)):
            pids = ids[:t]
            Ln = len(pids)
            if Ln == 1:
                logits = Sn[:, pids[0]].copy()
            else:
                sh = sharp[pids[:-1]]
                s = float(sh.sum())
                w = (sh / s) * w_b if s > 0 else np.zeros_like(sh)
                logits = Sn[:, pids[-1]].copy() + Sn[:, pids[:-1]] @ w
            used = set(pids)
            order = np.argsort(-logits)
            cand = next((wi for wi in order if logits[wi] > 0 and wi not in used),
                        None)
            g = gname(t)
            total[g] += 1
            if cand is not None and vocab[cand] == toks[t]:
                hits[g] += 1
    return {GRP_TAGS[i]: (hits[i] / total[i] if total[i] else None)
            for i in range(len(GRP_TAGS))}, int(sum(total.values()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="runs/20260809_151121/net_clean.npz")
    args = ap.parse_args()

    ng, vocab, ctx = load_net(args.model, seed=42, return_ctx=True)
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)

    tokenized = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
    rng = np.random.default_rng(SEED + 9000)
    perm = rng.permutation(len(tokenized))
    n_train = int(len(tokenized) * 0.8)
    test_toks = [tokenized[i] for i in perm[n_train:]]
    ev_te = [test_toks[i] for i in
             rng.choice(len(test_toks), min(EVAL_SUB_TEST, len(test_toks)),
                        replace=False)]

    ro = GradReadout(ng, pats, vocab, pats_mat, maxlen=MAXLEN)
    ro.build_score_matrix()
    S = ro.S
    if ctx is not None:
        ro.ctx_wgt = np.array(ctx, dtype=float)
        s = float(ro.ctx_wgt.sum())
        if s > 0:
            ro.ctx_wgt = ro.ctx_wgt / s
    print(f"模型: {args.model}  ctx_wgt={np.round(ro.ctx_wgt, 4)}", flush=True)

    variants = {
        "colsum": S,                                   # 现状（无归一化，排序等价）
        "colmax": S / S.max(axis=0, keepdims=True),    # 每列除以列 max
        "softmax_t1": _softmax_cols(S, 1.0),
        "softmax_t0.5": _softmax_cols(S, 0.5),
    }
    for name, Sn in variants.items():
        # wsum（排序不变性验证）
        w_tab, w_n = eval_wsum_top1(S, vocab, ev_te)
        w_avg = sum(v for v in w_tab.values() if v is not None) / \
            sum(1 for v in w_tab.values() if v is not None)
        # grad（替换 ro.S_norm 为变体）
        ro.S_norm = Sn
        g_tab, g_n = eval_grad_top1(ro, ev_te)
        g_avg = sum(v for v in g_tab.values() if v is not None) / \
            sum(1 for v in g_tab.values() if v is not None)
        # candB（变体列 + 变体 sharp）
        sh = sharpness(Sn)
        b_tab, b_n = eval_candb_top1(Sn, sh, vocab, ev_te)
        b_avg = sum(v for v in b_tab.values() if v is not None) / \
            sum(1 for v in b_tab.values() if v is not None)
        print(f"[{name}] wsum {w_avg:.4f}  grad {g_avg:.4f}  "
              f"candB {b_avg:.4f}  (n={w_n})", flush=True)


if __name__ == "__main__":
    main()
