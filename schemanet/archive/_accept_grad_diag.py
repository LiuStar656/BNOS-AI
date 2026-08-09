# -*- coding: utf-8 -*-
"""grad 增益诊断（攻关第一步）：位置分层 top-1 + 口径统一 + MAXLEN 扩展。

背景：有偏语料（句长 ~4）grad +0.047 兑现；真实语料（句长 14.3）grad 不兑现
（0.0778 vs wsum 0.1081）。机制假设：
  ① 位置截断：_logits_w/_grads 只取最近 maxlen 位置——MAXLEN=8 时句长 14.3 的
     t≥9 位置预测用不到远端上下文，ctx_wgt 学不到 pos8+；
  ② 口径混用：111545 评估里 wsum/trace 读出"训练前 S"、grad 读出"扰动后 W"，
     三路口径不一致；
  ③ 位置分层：grad 的上下文增益应随前缀长度（t）递增，短位置被 wsum 压。

实验：
  A. 加载 111545 模型（W 扰动后 + ctx8），统一用"扰动后 S"三路位置分层 top-1
  B. MAXLEN=16 重训 train_w（同参 lr=0.02/5ep/subsample=2000，ctx16），再分层对比

用法：python _accept_grad_diag.py     （留档 runs/时间戳/result.json）
"""
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from schema_net import _word_pattern, build_pulse
from sparse_net import (load_net, _pats_matrix, outsum_sparse, build_score_mat)
from grad_readout import GradReadout

N, K = 8192, 16
SEED = 42
CORPUS = "data/corpus_open.json"
NET = "runs/20260809_111545/net.npz"
DELTA_OFF = 0.02
EVAL_N = 600
TRAIN_W_EPOCHS = 5
TRAIN_W_LR = 0.02
GRPS = ((1, 1), (2, 2), (3, 3), (4, 5), (6, 8), (9, 30))
GRP_TAGS = ["t1", "t2", "t3", "t4-5", "t6-8", "t9+"]


def gname(t):
    for i, (lo, hi) in enumerate(GRPS):
        if lo <= t <= hi:
            return i
    return len(GRPS) - 1


def build_positions(tokenized, vocab_idx):
    pos = []
    for toks in tokenized:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(1, len(ids)):
            pos.append((ids[:t], ids[t]))
    return pos


def tab(hits, total):
    return {GRP_TAGS[i]: (hits[i] / total[i] if total[i] else None)
            for i in range(len(GRPS))}, int(sum(total.values()))


def eval_wsum_g(S, vocab, toks_list, norm_base):
    vtab = {w: i for i, w in enumerate(vocab)}
    hits, total = Counter(), Counter()
    for toks in toks_list:
        for t in range(1, len(toks)):
            last = toks[t - 1]
            p = S[:, vtab[last]].copy()
            den = norm_base.get(last, 0.0) if norm_base else 0.0
            if den > 0:
                p /= den
            used = set(toks[:t])
            cands = [(vocab[wi], float(p[wi])) for wi in range(len(vocab))
                     if p[wi] > 0 and vocab[wi] not in used]
            cands.sort(key=lambda x: -x[1])
            pred = cands[0][0] if cands else None
            g = gname(t)
            total[g] += 1
            if pred == toks[t]:
                hits[g] += 1
    return tab(hits, total)


def eval_grad_g(ro, toks_list):
    hits, total = Counter(), Counter()
    for toks in toks_list:
        ids = [ro.vocab_idx[w] for w in toks if w in ro.vocab_idx]
        for t in range(1, len(ids)):
            logits = ro._logits_w(ids[:t]).copy()
            logits[logits <= 0] = -np.inf
            for wid in ids[:t]:
                logits[wid] = -np.inf
            pred = ro.vocab[int(np.argmax(logits))]
            g = gname(t)
            total[g] += 1
            if pred == toks[t]:
                hits[g] += 1
    return tab(hits, total)


def eval_trace_g(ng, toks_list, S, pats, vocab, norm_base, delta_off):
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
            g = gname(t)
            total[g] += 1
            if pred == toks[t]:
                hits[g] += 1
    return tab(hits, total)


def main():
    os_env = None
    try:
        import os
        os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
        os.environ.setdefault("OMP_NUM_THREADS", "2")
    except Exception:   # noqa: BLE001
        pass

    tokenized = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
    freq = Counter(w for toks in tokenized for w in toks)
    vocab = ["<UNK>"] + [w for w, _ in freq.most_common(3000 + 100) if w != "<UNK>"][:2999]
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    rng = np.random.default_rng(SEED + 9000)
    perm = rng.permutation(len(tokenized))
    n_train = int(len(tokenized) * 0.8)
    train_toks = [tokenized[i] for i in perm[:n_train]]
    test_toks = [tokenized[i] for i in perm[n_train:]]
    ev_te = [test_toks[i] for i in
             rng.choice(len(test_toks), min(EVAL_N, len(test_toks)), replace=False)]

    ng, vocab_loaded, ctx8 = load_net(NET, seed=SEED, return_ctx=True)
    ng.learn_gate = False          # 评估纯检索
    pats = {w: _word_pattern(ng.n, ng.wta_k, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)
    outsum = outsum_sparse(ng, pats, vocab, slot=0)
    S = build_score_mat(ng, pats, vocab, pats_mat, slot=0)   # 扰动后 W → 干净口径
    print(f"加载 {NET}: ctx8={np.round(ctx8, 4)}  W 非零 {len(vocab_loaded)} 词表", flush=True)

    ro8 = GradReadout(ng, pats, vocab, pats_mat, maxlen=8)
    ro8.ctx_wgt = ctx8

    t0 = time.time()
    w_tab, w_n = eval_wsum_g(S, vocab, ev_te, outsum)
    print(f"A1 wsum（扰动后 S，干净口径）: {w_tab}  n={w_n}  [{time.time()-t0:.0f}s]", flush=True)
    t0 = time.time()
    tr_tab, tr_n = eval_trace_g(ng, ev_te, S, pats, vocab, outsum, DELTA_OFF)
    print(f"A2 trace: {tr_tab}  n={tr_n}  [{time.time()-t0:.0f}s]", flush=True)
    t0 = time.time()
    g8_tab, g8_n = eval_grad_g(ro8, ev_te)
    print(f"A3 grad(maxlen=8): {g8_tab}  n={g8_n}  [{time.time()-t0:.0f}s]", flush=True)

    # ── B：MAXLEN=16 重训 train_w（同参），位置覆盖整句 14.3 ──
    positions = build_positions(train_toks, vocab_idx)
    ro16 = GradReadout(ng, pats, vocab, pats_mat, maxlen=16)
    t0 = time.time()
    t16 = ro16.train_w(positions, lr=TRAIN_W_LR, epochs=TRAIN_W_EPOCHS, seed=SEED,
                       subsample=2000)
    ro16.ctx_wgt = np.clip(ro16.ctx_wgt, 0.0, None)
    s = float(ro16.ctx_wgt.sum())
    if s > 0:
        ro16.ctx_wgt = ro16.ctx_wgt / s
    print(f"B1 train_w(maxlen=16, {TRAIN_W_EPOCHS}ep×2000) {round(time.time()-t0,1)}s  "
          f"ctx16={np.round(ro16.ctx_wgt, 4)}", flush=True)
    t0 = time.time()
    g16_tab, g16_n = eval_grad_g(ro16, ev_te)
    print(f"B2 grad(maxlen=16): {g16_tab}  n={g16_n}  [{time.time()-t0:.0f}s]", flush=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("runs") / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "tag": "grad 增益诊断：位置分层 + 口径统一 + MAXLEN 8→16",
        "net": NET, "delta_off": DELTA_OFF, "eval_n": len(ev_te),
        "pos_groups": GRP_TAGS,
        "wsum": {"table": w_tab, "n": w_n},
        "trace": {"table": tr_tab, "n": tr_n},
        "grad_m8": {"table": g8_tab, "n": g8_n, "ctx": [float(x) for x in ctx8]},
        "grad_m16": {"table": g16_tab, "n": g16_n,
                     "ctx": [round(float(x), 4) for x in ro16.ctx_wgt],
                     "train_w_sec": round(float(t16), 1)},
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {out_dir}/result.json")


if __name__ == "__main__":
    main()
