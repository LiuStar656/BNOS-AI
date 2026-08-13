# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""逐句对比：新旧 trace 评估在完全相同 rng 下逐位置 pred 对比（可传句数）。

注意：ng.step 内 Hebbian 会改 W，run_old/run_new 必须从同一初始 W 出发，
故每条句前恢复 W 快照（否则第二次运行 W 被第一次污染）。"""
import json
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema_net import _word_pattern, build_pulse
from sparse_net import _pats_matrix, build_score_mat, load_net, outsum_sparse

MODEL = "runs/20260809_125334/net.npz"
CORPUS = "data/corpus_open20w.json"
DELTA_OFF = 0.005
N = int(sys.argv[1]) if len(sys.argv) > 1 else 200


def run_old(ng, toks, S, pats, vocab, outsum, delta_off):
    vtab = {w: i for i, w in enumerate(vocab)}
    V = len(vocab)
    preds = []
    for tok in toks:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.refractory_left = np.zeros(ng.n, dtype=int)
        ng.last_k_star = np.zeros(ng.n, dtype=int)
        for t in range(1, len(tok)):
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(build_pulse(ng.n, pats[tok[t - 1]]), slot=0)
            ng.step(np.zeros(ng.n), slot=0)
            last = tok[t - 1]
            p_last = S[:, vtab[last]].copy()
            den = outsum.get(last, 0.0)
            if den > 0:
                p_last /= den
            used = set(tok[:t])
            order = np.argsort(-p_last)
            top_idx = [wi for wi in order if p_last[wi] > 0 and vocab[wi] not in used]
            if len(top_idx) >= 2 and p_last[top_idx[0]] - p_last[top_idx[1]] >= delta_off:
                cands = [(vocab[wi], round(float(p_last[wi]), 6)) for wi in top_idx]
            else:
                last_pats = pats[last]
                trace_last = float(np.max(ng.pre_trace[last_pats])) if last_pats else 0.0
                mix = np.zeros(V)
                for src_w in tok[:t]:
                    tr = float(np.max(ng.pre_trace[pats[src_w]])) if pats[src_w] else 0.0
                    wgt = tr / trace_last if trace_last > 0 else tr
                    if src_w != last:
                        wgt *= 0.1
                    if wgt <= 0:
                        continue
                    p = S[:, vtab[src_w]].copy()
                    d2 = outsum.get(src_w, 0.0)
                    if d2 > 0:
                        p /= d2
                    mix += wgt * p
                cands = [(vocab[wi], round(float(mix[wi]), 6)) for wi in range(V)
                         if mix[wi] > 0 and vocab[wi] not in used]
                cands.sort(key=lambda x: -x[1])
            preds.append((cands[0][0] if cands else None, tok[t], t))
    return preds


def run_new(ng, toks, S, pats, vocab, outsum, delta_off):
    vtab = {w: i for i, w in enumerate(vocab)}
    V = len(vocab)
    preds = []
    norm_arr = np.zeros(V)
    for wi, w in enumerate(vocab):
        norm_arr[wi] = outsum.get(w, 0.0)
    for tok in toks:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.refractory_left = np.zeros(ng.n, dtype=int)
        ng.last_k_star = np.zeros(ng.n, dtype=int)
        M1 = np.zeros(V)
        C = np.zeros(V)
        for t in range(1, len(tok)):
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(build_pulse(ng.n, pats[tok[t - 1]]), slot=0)
            _inc(ng, M1, C, tok[:t], pats, S, vtab, norm_arr)
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(np.zeros(ng.n), slot=0)
            _inc(ng, M1, C, tok[:t], pats, S, vtab, norm_arr)
            last = tok[t - 1]
            p_last = S[:, vtab[last]].copy()
            den = norm_arr[vtab[last]]
            if den > 0:
                p_last /= den
            used = set(tok[:t])
            order = np.argsort(-p_last)
            top_idx = [wi for wi in order if p_last[wi] > 0 and vocab[wi] not in used]
            if len(top_idx) >= 2 and p_last[top_idx[0]] - p_last[top_idx[1]] >= delta_off:
                cands = [(vocab[wi], round(float(p_last[wi]), 6)) for wi in top_idx]
            else:
                last_pats = pats[last]
                trace_last = float(np.max(ng.pre_trace[last_pats])) if last_pats else 0.0
                cnt_last = tok[:t].count(last)
                mix = ((0.1 * M1 + 0.9 * cnt_last * trace_last * p_last) / trace_last
                       if trace_last > 0 else 0.1 * M1 + 0.9 * cnt_last * trace_last * p_last)
                cands = [(vocab[wi], round(float(mix[wi]), 6)) for wi in range(V)
                         if mix[wi] > 0 and vocab[wi] not in used]
                cands.sort(key=lambda x: -x[1])
            preds.append((cands[0][0] if cands else None, tok[t], t))
    return preds


def _inc(ng, M1, C, toks_t, pats, S, vtab, norm_arr):
    decay = float(ng.trace_decay)
    M1 *= decay
    seen = set()
    for w in toks_t:
        wi = vtab.get(w)
        if wi is not None and wi not in seen:
            seen.add(wi)
            C[wi] *= decay
    top = np.where(ng.spikes > 0)[0]
    if len(top) == 0:
        return
    top_set = set(top.tolist())
    for w in toks_t:
        wi = vtab.get(w)
        if wi is None:
            continue
        pw = pats[w]
        if not pw or not any(j in top_set for j in pw):
            continue
        tr_new = float(np.max(ng.pre_trace[pw]))
        c_new = tr_new * toks_t.count(w)
        d = c_new - C[wi]
        if d == 0:
            continue
        p = S[:, wi].copy()
        d2 = norm_arr[wi]
        if d2 > 0:
            p /= d2
        M1 += d * p
        C[wi] = c_new


def main():
    ng, vocab = load_net(MODEL, seed=42)
    pats = {w: _word_pattern(ng.n, 16, w) for w in vocab}
    vtab = {w: i for i, w in enumerate(vocab)}
    pats_mat = _pats_matrix(pats, vocab)
    outsum = outsum_sparse(ng, pats, vocab, slot=0)
    S = build_score_mat(ng, pats, vocab, pats_mat, slot=0)
    tokenized = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
    ev = [toks for toks in tokenized if all(w in vtab for w in toks)
          and len(toks) >= 2][:N]
    print(f"逐句对比 {len(ev)} 句", flush=True)
    print("ev[0]:", " ".join(ev[0]), flush=True)
    snap = pickle.dumps(ng.W_out)   # 初始 W 快照（Hebbian 污染后恢复用）
    ndiff = 0
    for si, tok in enumerate(ev):
        ng.W_out = pickle.loads(snap)
        ng.rng = np.random.default_rng(777 + si)
        p_old = run_old(ng, [tok], S, pats, vocab, outsum, DELTA_OFF)
        ng.W_out = pickle.loads(snap)
        ng.rng = np.random.default_rng(777 + si)
        p_new = run_new(ng, [tok], S, pats, vocab, outsum, DELTA_OFF)
        for (po, to_, t), (pn, tn, tt) in zip(p_old, p_new):
            if po != pn:
                ndiff += 1
                if ndiff <= 10:
                    print(f"句{si} t={t} 旧={po} 新={pn} 真={to_}", flush=True)
    print(f"总差异位置: {ndiff}", flush=True)


if __name__ == "__main__":
    main()
