# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""trace 句内一次性注入验证：增量 M1 版 vs 逐词遍历版（L1 原版）。

同一 ng / S / outsum / 评估子集，逐位置 pred 完全一致 + 命中表一致 + 计时。
（一次性验证脚本，验证后删除。）

注意：ng.step 内 Hebbian 会改 W，旧/新评估必须从同一初始 W 出发，
故每轮前恢复 W 快照（否则第二轮 W 被第一轮污染）。

用法：python _check_trace_fast.py [评估句数]
"""
import json
import pickle
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema_net import _word_pattern, build_pulse
from sparse_net import (SparseSchemaNet, _pats_matrix, build_score_mat,
                        load_net, outsum_sparse)
from _accept_scale20w import (GRP_TAGS, eval_pahe_g as eval_pahe_new,
                              eval_trace_g as eval_trace_new)

MODEL = "runs/20260809_125334/net.npz"
CORPUS = "data/corpus_open20w.json"
DELTA_OFF = 0.005
SWITCH_T = 4
N_EVAL = int(sys.argv[1]) if len(sys.argv) > 1 else 2000


# ── 旧实现（逐词遍历，L1 原版，改动前逐字复制）──────────────────────

def eval_trace_old(ng, toks_list, S, pats, vocab, norm_base, delta_off):
    vtab = {w: i for i, w in enumerate(vocab)}
    V = len(vocab)
    hits, total = Counter(), Counter()
    for toks in toks_list:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.refractory_left = np.zeros(ng.n, dtype=int)
        ng.last_k_star = np.zeros(ng.n, dtype=int)
        for t in range(1, len(toks)):
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(build_pulse(ng.n, pats[toks[t - 1]]), slot=0)
            ng.step(np.zeros(ng.n), slot=0)
            last = toks[t - 1]
            p_last = S[:, vtab[last]].copy()
            den = norm_base.get(last, 0.0) if norm_base else 0.0
            if den > 0:
                p_last /= den
            used = set(toks[:t])
            order = np.argsort(-p_last)
            top_idx = [wi for wi in order if p_last[wi] > 0 and vocab[wi] not in used]
            if len(top_idx) >= 2 and p_last[top_idx[0]] - p_last[top_idx[1]] >= delta_off:
                cands = [(vocab[wi], round(float(p_last[wi]), 6)) for wi in top_idx]
            else:
                last_pats = pats[last]
                trace_last = float(ng.pre_trace[last_pats].max()) if len(last_pats) else 0.0
                mix = np.zeros(V)
                for src_w in toks[:t]:
                    tr = float(ng.pre_trace[pats[src_w]].max()) if pats[src_w] else 0.0
                    wgt = tr / trace_last if trace_last > 0 else tr
                    if src_w != last:
                        wgt *= 0.1
                    if wgt <= 0:
                        continue
                    p = S[:, vtab[src_w]].copy()
                    d2 = norm_base.get(src_w, 0.0) if norm_base else 0.0
                    if d2 > 0:
                        p /= d2
                    mix += wgt * p
                cands = [(vocab[wi], round(float(mix[wi]), 6)) for wi in range(V)
                         if mix[wi] > 0 and vocab[wi] not in used]
                cands.sort(key=lambda x: -x[1])
            pred = cands[0][0] if cands else None
            g = GRP_TAGS[[i for i, (lo, hi) in
                          enumerate(((1, 1), (2, 2), (3, 3), (4, 5), (6, 8), (9, 30)))
                          if lo <= t <= hi][0]] if any(
                lo <= t <= hi for lo, hi in
                ((1, 1), (2, 2), (3, 3), (4, 5), (6, 8), (9, 30))) else "t9+"
            total[g] += 1
            if pred == toks[t]:
                hits[g] += 1
    return tab_like(hits, total)


def eval_pahe_old(ng, toks_list, S, pats, vocab, norm_base, delta_off, switch_t):
    vtab = {w: i for i, w in enumerate(vocab)}
    V = len(vocab)
    hits, total = Counter(), Counter()
    for toks in toks_list:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.refractory_left = np.zeros(ng.n, dtype=int)
        ng.last_k_star = np.zeros(ng.n, dtype=int)
        for t in range(1, len(toks)):
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(build_pulse(ng.n, pats[toks[t - 1]]), slot=0)
            ng.step(np.zeros(ng.n), slot=0)
            last = toks[t - 1]
            p_last = S[:, vtab[last]].copy()
            den = norm_base.get(last, 0.0) if norm_base else 0.0
            if den > 0:
                p_last /= den
            used = set(toks[:t])
            if t < switch_t:
                cands = [(vocab[wi], float(p_last[wi])) for wi in range(V)
                         if p_last[wi] > 0 and vocab[wi] not in used]
                cands.sort(key=lambda x: -x[1])
            else:
                order = np.argsort(-p_last)
                top_idx = [wi for wi in order if p_last[wi] > 0 and vocab[wi] not in used]
                if len(top_idx) >= 2 and p_last[top_idx[0]] - p_last[top_idx[1]] >= delta_off:
                    cands = [(vocab[wi], round(float(p_last[wi]), 6)) for wi in top_idx]
                else:
                    last_pats = pats[last]
                    trace_last = float(ng.pre_trace[last_pats].max()) if len(last_pats) else 0.0
                    mix = np.zeros(V)
                    for src_w in toks[:t]:
                        tr = float(ng.pre_trace[pats[src_w]].max()) if pats[src_w] else 0.0
                        wgt = tr / trace_last if trace_last > 0 else tr
                        if src_w != last:
                            wgt *= 0.1
                        if wgt <= 0:
                            continue
                        p = S[:, vtab[src_w]].copy()
                        d2 = norm_base.get(src_w, 0.0) if norm_base else 0.0
                        if d2 > 0:
                            p /= d2
                        mix += wgt * p
                    cands = [(vocab[wi], round(float(mix[wi]), 6)) for wi in range(V)
                             if mix[wi] > 0 and vocab[wi] not in used]
                    cands.sort(key=lambda x: -x[1])
            pred = cands[0][0] if cands else None
            g = GRP_TAGS[[i for i, (lo, hi) in
                          enumerate(((1, 1), (2, 2), (3, 3), (4, 5), (6, 8), (9, 30)))
                          if lo <= t <= hi][0]] if any(
                lo <= t <= hi for lo, hi in
                ((1, 1), (2, 2), (3, 3), (4, 5), (6, 8), (9, 30))) else "t9+"
            total[g] += 1
            if pred == toks[t]:
                hits[g] += 1
    return tab_like(hits, total)


def tab_like(hits, total):
    tags = ["t1", "t2", "t3", "t4-5", "t6-8", "t9+"]
    return {tags[i]: (hits[tags[i]] / total[tags[i]] if total[tags[i]] else None)
            for i in range(6)}, int(sum(total.values()))


# ── 主流程 ──────────────────────────────────────────────────────

def main():
    os = __import__("os")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
    os.environ.setdefault("OMP_NUM_THREADS", "2")

    ng, vocab = load_net(MODEL, seed=42)
    print(f"模型 {MODEL}: n={ng.n} 词表 {len(vocab)}", flush=True)
    pats = {w: _word_pattern(ng.n, 16, w) for w in vocab}
    vtab = {w: i for i, w in enumerate(vocab)}
    pats_mat = _pats_matrix(pats, vocab)
    outsum = outsum_sparse(ng, pats, vocab, slot=0)
    S = build_score_mat(ng, pats, vocab, pats_mat, slot=0)
    print("S 矩阵构建完成", flush=True)

    tokenized = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
    ev = [toks for toks in tokenized if all(w in vtab for w in toks)
          and len(toks) >= 2][:N_EVAL]
    print(f"评估 {len(ev)} 句（全在词表内）", flush=True)

    for name, old_fn, new_fn in (
            ("trace", eval_trace_old, eval_trace_new),
            ("pahe", eval_pahe_old, eval_pahe_new)):
        snap = pickle.dumps(ng.W_out)   # 初始 W 快照（Hebbian 污染后恢复用）
        ng.W_out = pickle.loads(snap)
        ng.rng = np.random.default_rng(777)   # 新旧同一起点噪声序列（step 消耗 rng）
        t0 = time.time()
        old_tab, old_n = old_fn(ng, ev, S, pats, vocab, outsum, DELTA_OFF,
                                SWITCH_T) if name == "pahe" else \
            old_fn(ng, ev, S, pats, vocab, outsum, DELTA_OFF)
        t_old = round(time.time() - t0, 1)
        ng.W_out = pickle.loads(snap)
        ng.rng = np.random.default_rng(777)   # 新版同一起点（旧版已消耗 rng）
        t0 = time.time()
        new_tab, new_n = new_fn(ng, ev, S, pats, vocab, outsum, DELTA_OFF,
                                SWITCH_T) if name == "pahe" else \
            new_fn(ng, ev, S, pats, vocab, outsum, DELTA_OFF)
        t_new = round(time.time() - t0, 1)
        same = old_tab == new_tab and old_n == new_n
        print(f"[{name}] 旧 {t_old}s  新 {t_new}s  加速 {t_old/max(t_new,1):.1f}x  "
              f"命中表一致={same}", flush=True)
        if not same:
            print("  旧:", old_tab)
            print("  新:", new_tab)
        else:
            print("  top-1:", {k: round(v, 4) for k, v in new_tab.items()},
                  f"n={new_n}", flush=True)


if __name__ == "__main__":
    main()
