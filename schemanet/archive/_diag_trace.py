# -*- coding: utf-8 -*-
"""诊断：M1 增量 vs 暴力重算 Σ tr*p，逐位置对比（单句）。"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from schema_net import _word_pattern, build_pulse
from sparse_net import _pats_matrix, build_score_mat, load_net, outsum_sparse
from _accept_scale20w import _inc_mix

MODEL = "runs/20260809_125334/net.npz"
CORPUS = "data/corpus_open20w.json"


def main():
    ng, vocab = load_net(MODEL, seed=42)
    pats = {w: _word_pattern(ng.n, 16, w) for w in vocab}
    vtab = {w: i for i, w in enumerate(vocab)}
    pats_mat = _pats_matrix(pats, vocab)
    outsum = outsum_sparse(ng, pats, vocab, slot=0)
    S = build_score_mat(ng, pats, vocab, pats_mat, slot=0)
    V = len(vocab)
    norm_arr = np.zeros(V)
    for wi, w in enumerate(vocab):
        norm_arr[wi] = outsum.get(w, 0.0)

    tokenized = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
    toks = next(t for t in tokenized if all(w in vtab for w in t) and len(t) >= 2)
    print("句:", " ".join(toks), flush=True)
    ng.rng = np.random.default_rng(777)

    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)
    ng.refractory_left = np.zeros(ng.n, dtype=int)
    ng.last_k_star = np.zeros(ng.n, dtype=int)
    M1 = np.zeros(V)
    C = np.zeros(V)

    for t in range(1, len(toks)):
        ng.v = np.zeros((ng.n, ng.slots))
        ng.step(build_pulse(ng.n, pats[toks[t - 1]]), slot=0)
        if t == 5:
            print(f"  step#1 注入 {toks[t-1]}  top1={np.where(ng.spikes>0)[0].tolist()}", flush=True)
            for w in toks[:t]:
                wi = vtab[w]
                inter = [j for j in pats[w] if ng.spikes[j] > 0]
                tr = float(np.max(ng.pre_trace[pats[w]])) if pats[w] else 0.0
                print(f"    w={w} 模式交集={inter}  tr={tr:.4f}  count={toks[:t].count(w)}", flush=True)
        _inc_mix(ng, M1, C, toks[:t], pats, S, vtab, norm_arr)
        if t == 5:
            print(f"    更新后 C[<UNK>]={C[vtab['<UNK>']]:.4f}", flush=True)
        ng.v = np.zeros((ng.n, ng.slots))
        ng.step(np.zeros(ng.n), slot=0)
        if t == 5:
            print(f"  step#2 空脉冲 top2={np.where(ng.spikes>0)[0].tolist()}", flush=True)
            for w in toks[:t]:
                wi = vtab[w]
                inter = [j for j in pats[w] if ng.spikes[j] > 0]
                tr = float(np.max(ng.pre_trace[pats[w]])) if pats[w] else 0.0
                print(f"    w={w} 模式交集={inter}  tr={tr:.4f}  count={toks[:t].count(w)}", flush=True)
        _inc_mix(ng, M1, C, toks[:t], pats, S, vtab, norm_arr)
        if t == 5:
            print(f"    更新后 C[<UNK>]={C[vtab['<UNK>']]:.4f}", flush=True)

        # 暴力重算
        M1_ref = np.zeros(V)
        for src_w in toks[:t]:
            tr = float(np.max(ng.pre_trace[pats[src_w]])) if pats[src_w] else 0.0
            if tr <= 0:
                continue
            p = S[:, vtab[src_w]].copy()
            d2 = norm_arr[vtab[src_w]]
            if d2 > 0:
                p /= d2
            M1_ref += tr * p
        d = float(np.abs(M1 - M1_ref).max())

        # 新旧 mix 逐位置对比
        last = toks[t - 1]
        p_last = S[:, vtab[last]].copy()
        den = norm_arr[vtab[last]]
        if den > 0:
            p_last /= den
        used = set(toks[:t])
        last_pats = pats[last]
        trace_last = float(np.max(ng.pre_trace[last_pats])) if last_pats else 0.0
        cnt_last = toks[:t].count(last)
        mix_new = ((0.1 * M1 + 0.9 * cnt_last * trace_last * p_last) / trace_last
                   if trace_last > 0 else 0.1 * M1 + 0.9 * cnt_last * trace_last * p_last)
        mix_old = np.zeros(V)
        for src_w in toks[:t]:
            tr = float(np.max(ng.pre_trace[pats[src_w]])) if pats[src_w] else 0.0
            wgt = tr / trace_last if trace_last > 0 else tr
            if src_w != last:
                wgt *= 0.1
            if wgt <= 0:
                continue
            p = S[:, vtab[src_w]].copy()
            d2 = norm_arr[vtab[src_w]]
            if d2 > 0:
                p /= d2
            mix_old += wgt * p
        md = float(np.abs(mix_new - mix_old).max())
        # 候选（同 eval 口径）
        cand_n = [(vocab[wi], round(float(mix_new[wi]), 6)) for wi in range(V)
                  if mix_new[wi] > 0 and vocab[wi] not in used]
        cand_o = [(vocab[wi], round(float(mix_old[wi]), 6)) for wi in range(V)
                  if mix_old[wi] > 0 and vocab[wi] not in used]
        cand_n.sort(key=lambda x: -x[1])
        cand_o.sort(key=lambda x: -x[1])
        pn = cand_n[0][0] if cand_n else None
        po = cand_o[0][0] if cand_o else None
        flag = "  ★DIFF" if pn != po else ""
        print(f"t={t} M1_maxdiff={d:.3e} mix_maxdiff={md:.3e} "
              f"pred 新={pn} 旧={po} 真={toks[t]}{flag}", flush=True)
        if pn != po:
            print("   新 top3:", cand_n[:3])
            print("   旧 top3:", cand_o[:3])


if __name__ == "__main__":
    main()
