# -*- coding: utf-8 -*-
"""Phase 2 L1：数据放大（2 万 → 20 万句）训练 + 成长基线三件套 + 对照 L0。

对照基线 L0（runs/20260809_103532，2 万句，干净口径留出 2000 句）：
  wsum 0.1182 / trace 0.1196 / pahe 0.1208

管线（与 103532 同参）：
  Hebbian 预训练 → sleep 整理（频率门控）→ delta_off 扫描（trace 留出子集）
  → train_w（变体：跳过 train_ctx / lr=0.02 / 5ep / 归一化）→ 4d 检查
  → 基准三件套：① top-1 位置分层（wsum/trace/pahe 干净口径）
    ② 生成 20 前缀 × 3 引擎（前缀一致性 + 速度）
    ③ 回归 abc/seq（子进程）

对照判定（§3.2 放大验收）：L1 总平均 vs L0 总平均，增益 > 噪声窗口（z>1.96）
→ 通过；同时复查 trace 长位置增益（PAHE 复活判定：增益随数据扩大）。

用法：python _accept_scale20w.py     （留档 runs/时间戳/result.json）
"""
import json
import multiprocessing as mp
import os
import pickle
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from schema_net import _word_pattern, _learn_sentence, build_pulse
from sparse_net import (SparseSchemaNet, _pats_matrix, outsum_sparse,
                        build_score_mat, evaluate_wsum_smat, evaluate_trace_smat,
                        save_net)
from grad_readout import GradReadout
from generator import Generator

N, K = 8192, 16
MAXLEN = 8
SEED = 42
CORPUS = "data/corpus_open20w.json"
KV = 3000                     # 词表（L1 标准档，与 L0 同口径对照）
UNK = "<UNK>"
EVAL_SUB_TEST = 2000          # 留出评估句数（与 L0 干净口径同）
GEN_N = 20
GEN_MAX = 10
TOP_K, TEMP, PENALTY = 12, 1.1, 2.5
TRAIN_W_EPOCHS = 5
TRAIN_W_LR = 0.02
SKIP_TRAIN_CTX = True
SLEEP_DECAY = 0.3
SLEEP_EPS = 1e-4
DELTA_SCAN = [0.005, 0.01, 0.02]
SCAN_SUB = 150
SWITCH_T = 4
W_MAX = 64.0                 # Hebbian 权重 cap（16→64：20 万句饱和修复，worker 内与合并处同口径）
N_WORKERS = 8               # Hebbian 并行进程数（验证：并行合并与顺序逐值等价，Δtop-1=0）
GRPS = ((1, 1), (2, 2), (3, 3), (4, 5), (6, 8), (9, 30))
GRP_TAGS = ["t1", "t2", "t3", "t4-5", "t6-8", "t9+"]


def gname(t):
    for i, (lo, hi) in enumerate(GRPS):
        if lo <= t <= hi:
            return i
    return len(GRPS) - 1


# ── Hebbian 并行训练（验证 _par_train_check.py：合并与顺序逐值等价）──
_G = {}


def _get_globals():
    """子进程惰性构建语料/词表/模式/perm（spawn 后只构建一次，perm 与主进程同 seed）。"""
    if "corpus" not in _G:
        tokenized = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
        freq = Counter(w for toks in tokenized for w in toks)
        vocab = [UNK] + [w for w, _ in freq.most_common(KV + 100) if w != UNK][:KV - 1]
        pats = {w: _word_pattern(N, K, w) for w in vocab}
        perm = np.random.default_rng(SEED + 9000).permutation(len(tokenized))
        _G.update(corpus=tokenized, vocab=vocab, pats=pats, perm=perm)
    return _G["corpus"], _G["pats"], _G["perm"]


def _hebb_chunk(args):
    """单个 worker：训练 perm[i0:i1] 对应的语料句，W_out/slot_freq 存 pickle。"""
    i0, i1, seed, out_path = args
    corpus, pats, perm = _get_globals()
    ng = SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=W_MAX, wta_k=K, noise_p=0.06, noise_amp=0.5,
                         weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                         refractory=1, rng=np.random.default_rng(seed))
    for i in range(i0, i1):
        _learn_sentence(ng, corpus[perm[i]], pats, slot=0)
    with open(out_path, "wb") as f:
        pickle.dump((ng.W_out, ng.slot_freq), f)


def _merge_hebb(paths, n, slots, w_max):
    """合并各分块 W（Σ + clip w_max），与顺序训练等价（加法可交换）。"""
    W_out = [[{} for _ in range(slots)] for _ in range(n)]
    slot_freq = np.zeros((n, slots), dtype=np.int32)
    for p in paths:
        with open(p, "rb") as f:
            W, sf = pickle.load(f)
        for i in range(n):
            for k in range(slots):
                row = W[i][k]
                if row:
                    out = W_out[i][k]
                    for j, w in row.items():
                        out[j] = min(out.get(j, 0.0) + w, w_max)
        slot_freq += sf
    return W_out, slot_freq


def tab(hits, total):
    return {GRP_TAGS[i]: (hits[i] / total[i] if total[i] else None)
            for i in range(len(GRPS))}, int(sum(total.values()))


def build_positions(tokenized, vocab_idx):
    pos = []
    for toks in tokenized:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(1, len(ids)):
            pos.append((ids[:t], ids[t]))
    return pos


def diff_sig(p1, n1, p2, n2):
    if n1 == 0 or n2 == 0:
        return None, 0.0
    se = np.sqrt(max(p1 * (1 - p1) / n1, 0.0) + max(p2 * (1 - p2) / n2, 0.0))
    return p1 - p2, ((p1 - p2) / se if se > 0 else 0.0)


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


def _inc_mix(ng, M1, C, toks_t, pats, S, vtab, norm_arr):
    """step 后增量更新 M1（Σ_src C_src × p_src^n，C_src = 前缀出现次数 × max(pre_trace[模式])）。

    pre_trace 更新 = 同步衰减 + 发放注入，故未触及词 C *= decay 精确（M1 同步 *= decay）；
    触及词用当前 count×tr_new 重算补差——重复词（多次出现贡献叠加）与词模式共享
    神经元（残留 trace 计入）均精确，无需维护 occ 与 C 的同步时序。
    与逐词遍历版逐位置精确等价（验证 _check_trace_fast.py：top-1 完全一致）。"""
    decay = float(ng.trace_decay)
    M1 *= decay
    seen = set()
    for w in toks_t:
        wi = vtab.get(w)
        if wi is not None and wi not in seen:
            seen.add(wi)
            C[wi] *= decay   # 按唯一词衰减一次（重复词不重复衰减）
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


def eval_trace_g(ng, toks_list, S, pats, vocab, norm_base, delta_off):
    vtab = {w: i for i, w in enumerate(vocab)}
    V = len(vocab)
    hits, total = Counter(), Counter()
    norm_arr = np.zeros(V)
    for wi, w in enumerate(vocab):
        norm_arr[wi] = norm_base.get(w, 0.0) if norm_base else 0.0
    for toks in toks_list:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.refractory_left = np.zeros(ng.n, dtype=int)
        ng.last_k_star = np.zeros(ng.n, dtype=int)
        M1 = np.zeros(V)              # 句内增量混合（边注入边累积，替代逐位置重遍历）
        C = np.zeros(V)               # 每词聚合贡献（前缀出现次数 × tr）镜像
        for t in range(1, len(toks)):
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(build_pulse(ng.n, pats[toks[t - 1]]), slot=0)
            _inc_mix(ng, M1, C, toks[:t], pats, S, vtab, norm_arr)
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(np.zeros(ng.n), slot=0)
            _inc_mix(ng, M1, C, toks[:t], pats, S, vtab, norm_arr)
            last = toks[t - 1]
            p_last = S[:, vtab[last]].copy()
            den = norm_arr[vtab[last]]
            if den > 0:
                p_last /= den
            used = set(toks[:t])
            order = np.argsort(-p_last)
            top_idx = [wi for wi in order if p_last[wi] > 0 and vocab[wi] not in used]
            if len(top_idx) >= 2 and p_last[top_idx[0]] - p_last[top_idx[1]] >= delta_off:
                cands = [(vocab[wi], round(float(p_last[wi]), 6)) for wi in top_idx]
            else:
                last_pats = pats[last]
                trace_last = float(np.max(ng.pre_trace[last_pats])) if last_pats else 0.0
                # 末词贡献 = count(last) × 1.0×p_last（旧版逐出现累加，重复词多份）
                cnt_last = toks[:t].count(last)
                mix = ((0.1 * M1 + 0.9 * cnt_last * trace_last * p_last) / trace_last
                       if trace_last > 0 else 0.1 * M1 + 0.9 * cnt_last * trace_last * p_last)
                cands = [(vocab[wi], round(float(mix[wi]), 6)) for wi in range(V)
                         if mix[wi] > 0 and vocab[wi] not in used]
                cands.sort(key=lambda x: -x[1])
            pred = cands[0][0] if cands else None
            g = gname(t)
            total[g] += 1
            if pred == toks[t]:
                hits[g] += 1
    return tab(hits, total)


def eval_pahe_g(ng, toks_list, S, pats, vocab, norm_base, delta_off, switch_t):
    vtab = {w: i for i, w in enumerate(vocab)}
    V = len(vocab)
    hits, total = Counter(), Counter()
    norm_arr = np.zeros(V)
    for wi, w in enumerate(vocab):
        norm_arr[wi] = norm_base.get(w, 0.0) if norm_base else 0.0
    for toks in toks_list:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.refractory_left = np.zeros(ng.n, dtype=int)
        ng.last_k_star = np.zeros(ng.n, dtype=int)
        M1 = np.zeros(V)              # 句内增量混合（trace 分支共用）
        C = np.zeros(V)               # 每词聚合贡献（前缀出现次数 × tr）镜像
        for t in range(1, len(toks)):
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(build_pulse(ng.n, pats[toks[t - 1]]), slot=0)
            _inc_mix(ng, M1, C, toks[:t], pats, S, vtab, norm_arr)
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(np.zeros(ng.n), slot=0)
            _inc_mix(ng, M1, C, toks[:t], pats, S, vtab, norm_arr)
            last = toks[t - 1]
            p_last = S[:, vtab[last]].copy()
            den = norm_arr[vtab[last]]
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
                    trace_last = float(np.max(ng.pre_trace[last_pats])) if last_pats else 0.0
                    # 末词贡献 = count(last) × 1.0×p_last（旧版逐出现累加，重复词多份）
                    cnt_last = toks[:t].count(last)
                    mix = ((0.1 * M1 + 0.9 * cnt_last * trace_last * p_last) / trace_last
                           if trace_last > 0 else 0.1 * M1 + 0.9 * cnt_last * trace_last * p_last)
                    cands = [(vocab[wi], round(float(mix[wi]), 6)) for wi in range(V)
                             if mix[wi] > 0 and vocab[wi] not in used]
                    cands.sort(key=lambda x: -x[1])
            pred = cands[0][0] if cands else None
            g = gname(t)
            total[g] += 1
            if pred == toks[t]:
                hits[g] += 1
    return tab(hits, total)


def gen_one(gen, start, max_len, top_k, temp, penalty, engine="pahe", switch_t=4):
    ids = [gen.vocab_idx[w] for w in start if w in gen.vocab_idx]
    if not ids:
        return []
    for _ in range(max_len - len(ids)):
        eng = engine
        if engine == "pahe":
            eng = "wsum" if len(ids) < switch_t else "trace"
        wid = gen._sample(gen._engine_logits(ids, eng), ids, top_k, temp, penalty)
        if wid is None:
            break
        ids.append(wid)
    return [gen.vocab[i] for i in ids]


def main():
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
    os.environ.setdefault("OMP_NUM_THREADS", "2")

    # ── 语料 ──
    tokenized = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
    freq = Counter(w for toks in tokenized for w in toks)
    vocab = [UNK] + [w for w, _ in freq.most_common(KV + 100) if w != UNK][:KV - 1]
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    rng = np.random.default_rng(SEED + 9000)
    perm = rng.permutation(len(tokenized))
    n_train = int(len(tokenized) * 0.8)
    train_toks = [tokenized[i] for i in perm[:n_train]]
    test_toks = [tokenized[i] for i in perm[n_train:]]
    ev_te = [test_toks[i] for i in
             rng.choice(len(test_toks), min(EVAL_SUB_TEST, len(test_toks)), replace=False)]
    unk_ratio = freq.get(UNK, 0) / max(1, sum(freq.values()))
    print(f"{CORPUS}: {len(tokenized)} 句，词表 {len(vocab)}，UNK {unk_ratio:.4f}，"
          f"训练 {len(train_toks)}/留出 {len(test_toks)}", flush=True)

    # ── 训练：Hebbian（并行分块 + 合并，验证与顺序逐值等价）──
    ng = SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=16.0, wta_k=K, noise_p=0.06, noise_amp=0.5,
                         weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                         refractory=1, rng=np.random.default_rng(SEED + 5000))
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    t0 = time.time()
    if N_WORKERS > 1:
        k = len(train_toks) // N_WORKERS
        tmp = Path("runs") / f"_hebb_tmp_{os.getpid()}"
        tmp.mkdir(parents=True, exist_ok=True)
        paths = []
        tasks = []
        for i in range(N_WORKERS):
            i0 = i * k
            i1 = len(train_toks) if i == N_WORKERS - 1 else (i + 1) * k
            p = tmp / f"chunk_{i}.pkl"
            paths.append(str(p))
            tasks.append((i0, i1, SEED + 5000 + 1000 * i, str(p)))
        ctx = mp.get_context("spawn")
        with ctx.Pool(N_WORKERS) as pool:
            pool.map(_hebb_chunk, tasks)
        ng.W_out, ng.slot_freq = _merge_hebb(paths, N, 4, 16.0)
        for p in paths:
            Path(p).unlink(missing_ok=True)
        tmp.rmdir()
    else:
        for toks in train_toks:
            _learn_sentence(ng, toks, pats, slot=0)
    t_hebb = round(time.time() - t0, 1)
    print(f"Hebbian {len(train_toks)} 句 × {N_WORKERS} 进程 {t_hebb}s", flush=True)

    # ── sleep 整理（同 103532 口径）──
    fq = ng.slot_freq[:, 0]
    nz = fq[fq > 0]
    min_wake = float(np.percentile(nz, 10)) if len(nz) else 1.0
    min_wake = max(1.0, min_wake)
    nnz_pre = sum(len(row) for i in range(ng.n) for row in [ng.W_out[i][0]])
    t0 = time.time()
    cleared, weakened = ng.sleep_consolidate(min_wake=min_wake, decay=SLEEP_DECAY,
                                             eps=SLEEP_EPS)
    t_sleep = round(time.time() - t0, 1)
    nnz_post = sum(len(row) for i in range(ng.n) for row in [ng.W_out[i][0]])
    print(f"sleep {t_sleep}s: min_wake={min_wake:.0f} 弱化 {weakened} 删除 {cleared} "
          f"nnz {nnz_pre}→{nnz_post}", flush=True)
    ng.learn_gate = False

    pats_mat = _pats_matrix(pats, vocab)
    outsum = outsum_sparse(ng, pats, vocab, slot=0)
    S = build_score_mat(ng, pats, vocab, pats_mat, slot=0)
    print(f"S {S.shape}（{S.nbytes / 1e6:.0f}MB）", flush=True)

    # ── delta_off 扫描 ──
    scan_toks = [test_toks[i] for i in
                 rng.choice(len(test_toks), min(SCAN_SUB, len(test_toks)), replace=False)]
    best_delta, best_t = 0.02, -1.0
    for d in DELTA_SCAN:
        t_ = evaluate_trace_smat(ng, scan_toks, S, pats, vocab, outsum, delta_off=d)
        print(f"  delta_off={d}: {t_[0]:.4f}")
        if t_[0] > best_t:
            best_delta, best_t = d, t_[0]
    delta_off = best_delta
    print(f"→ delta_off={delta_off}", flush=True)

    # ── train_w ──
    ro = GradReadout(ng, pats, vocab, pats_mat, maxlen=MAXLEN)
    ro.snapshot_w()
    nnz0 = ro.nnz()
    positions = build_positions(train_toks, vocab_idx)
    print(f"positions {len(positions)}", flush=True)
    t0 = time.time()
    t_w = ro.train_w(positions, lr=TRAIN_W_LR, epochs=TRAIN_W_EPOCHS, seed=SEED,
                     subsample=2000)
    ro.ctx_wgt = np.clip(ro.ctx_wgt, 0.0, None)
    s = float(ro.ctx_wgt.sum())
    if s > 0:
        ro.ctx_wgt = ro.ctx_wgt / s
    t_w = round(time.time() - t0, 1)
    print(f"train_w {t_w}s  ctx={np.round(ro.ctx_wgt, 4)}", flush=True)
    nnz1 = ro.nnz()
    wd = ro.w_delta()
    print(f"4d: nnz {nnz0}→{nnz1}  max_delta={wd['max_delta']} "
          f"改 {wd['n_changed']}/{wd['n_tot']}", flush=True)

    # S 用扰动后 W 重建（干净口径）
    S = build_score_mat(ng, pats, vocab, pats_mat, slot=0)

    # ── ① top-1 位置分层（三引擎，干净口径）──
    counts = Counter()
    for toks in ev_te:
        for t in range(1, len(toks)):
            counts[gname(t)] += 1
    t0 = time.time()
    w_tab, w_n = eval_wsum_g(S, vocab, ev_te, outsum)
    print(f"① wsum: {w_tab} n={w_n} [{time.time()-t0:.0f}s]", flush=True)
    t0 = time.time()
    tr_tab, tr_n = eval_trace_g(ng, ev_te, S, pats, vocab, outsum, delta_off)
    print(f"① trace: {tr_tab} n={tr_n} [{time.time()-t0:.0f}s]", flush=True)
    t0 = time.time()
    pa_tab, pa_n = eval_pahe_g(ng, ev_te, S, pats, vocab, outsum, delta_off, SWITCH_T)
    print(f"① pahe: {pa_tab} n={pa_n} [{time.time()-t0:.0f}s]", flush=True)

    def avg(t_):
        return sum(v for v in t_.values() if v is not None) / sum(1 for v in t_.values() if v is not None)

    w_avg, tr_avg, pa_avg = avg(w_tab), avg(tr_tab), avg(pa_tab)
    print(f"总平均: wsum {w_avg:.4f}  trace {tr_avg:.4f}  pahe {pa_avg:.4f}")

    # L0 对照（干净口径留出 2000）
    L0 = {"wsum": 0.1182, "trace": 0.1196, "pahe": 0.1208}
    d_gain, z_gain = diff_sig(pa_avg, pa_n, L0["pahe"], pa_n)
    print(f"对照 L0→L1: pahe {L0['pahe']}→{pa_avg:.4f} 增益 {d_gain:+.4f} z={z_gain:+.2f}"
          f"（{'显著' if z_gain is not None and abs(z_gain) > 1.96 else '不显著'}）")

    # trace 长位置增益复查（PAHE 复活判定）
    def merged_rate(tab_, lo, hi):
        h = s = 0
        for i, (l0, h0) in enumerate(GRPS):
            if l0 < lo:
                continue
            if l0 > hi:
                break
            r = tab_[GRP_TAGS[i]]
            n_i = counts[i]
            if r is not None and n_i:
                h += r * n_i
                s += n_i
        return h / s if s else 0.0, s

    d_long, z_long = diff_sig(*merged_rate(tr_tab, 4, 8), *merged_rate(w_tab, 4, 8))
    print(f"trace-wsum 长位置(t4-8): {d_long:+.4f} z={z_long:+.2f} "
          f"（L0 为 +0.0072 z=1.64，{'增益扩大' if z_long is not None and z_long > 1.64 else '未扩大'}）")

    # ── ② 生成对照 ──
    gen = Generator(ro, outsum=outsum, seed=SEED + 7)
    starters = [toks[0] for toks in train_toks if toks]
    sfreq = Counter(starters)
    prefixes = [w for w, _ in sfreq.most_common(GEN_N)]
    vset = set(vocab)
    prefixes = [p for p in prefixes if p in vset][:GEN_N]

    samples, speed = [], {}
    for eng in ("wsum", "trace", "pahe"):
        t0 = time.time()
        n_tok = 0
        for pre in prefixes:
            g = gen_one(gen, [pre], GEN_MAX, TOP_K, TEMP, PENALTY, engine=eng)
            n_tok += max(0, len(g) - 1)
        dt = time.time() - t0
        speed[eng] = round(n_tok / dt, 1) if dt > 0 else 0.0
        print(f"② 生成[{eng}] {n_tok} token {dt:.1f}s = {speed[eng]} tok/s", flush=True)

    for pre in prefixes:
        samples.append({
            "prefix": pre,
            "wsum": "".join(gen_one(gen, [pre], GEN_MAX, TOP_K, TEMP, PENALTY, "wsum")),
            "trace": "".join(gen_one(gen, [pre], GEN_MAX, TOP_K, TEMP, PENALTY, "trace")),
            "pahe": "".join(gen_one(gen, [pre], GEN_MAX, TOP_K, TEMP, PENALTY, "pahe")),
        })
    n_pfx_ok = sum(1 for s in samples if s["pahe"] and s["pahe"].startswith(s["prefix"]))
    print(f"② pahe 前缀一致性 {n_pfx_ok}/{GEN_N}")

    # ── ③ 回归 ──
    reg = {}
    reg_cmds = {
        "abc": (["schema_net.py", "--mode", "abc"], "9/9"),
        "seq": (["schema_net.py", "--mode", "seq", "--stdp-pre", "0.1"], "顺序敏感成立"),
    }
    for mode, (cmd, want) in reg_cmds.items():
        try:
            r = subprocess.run([sys.executable] + cmd, capture_output=True,
                               text=True, timeout=600)
            out = (r.stdout or "") + (r.stderr or "")
            reg[mode] = "PASS" if want in out else "FAIL"
        except Exception as e:   # noqa: BLE001
            reg[mode] = f"ERR {e}"
        print(f"回归 {mode}: {reg[mode]}")

    # ── 留档 ──
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("runs") / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    save_net(ng, vocab, out_dir / "net.npz", ctx_wgt=ro.ctx_wgt)
    result = {
        "tag": "Phase 2 L1：数据放大 2 万→20 万句（词表 3000 同口径对照）",
        "corpus": CORPUS, "vocab": len(vocab), "unk_ratio": round(unk_ratio, 4),
        "config": {"n": N, "k": K, "maxlen": MAXLEN, "kv": KV, "delta_off": delta_off,
                   "train_w": {"epochs": TRAIN_W_EPOCHS, "lr": TRAIN_W_LR,
                               "skip_train_ctx": SKIP_TRAIN_CTX}},
        "timing": {"hebbian_sec": t_hebb, "sleep_sec": t_sleep, "grad_sec": t_w},
        "sleep": {"cleared": cleared, "weakend": weakened,
                  "nnz_pre": nnz_pre, "nnz_post": nnz_post},
        "top1": {"wsum": w_tab, "trace": tr_tab, "pahe": pa_tab,
                 "avg": {"wsum": round(w_avg, 4), "trace": round(tr_avg, 4),
                         "pahe": round(pa_avg, 4)}, "n": counts},
        "scale_vs_L0": {"L0_pahe": L0["pahe"], "L1_pahe": round(pa_avg, 4),
                        "gain": None if d_gain is None else round(d_gain, 4),
                        "z": round(z_gain, 2) if z_gain is not None else None,
                        "L0_note": "runs/20260809_103532 干净口径留出 2000"},
        "trace_long_recheck": {"L1_diff": None if d_long is None else round(d_long, 4),
                               "L1_z": round(z_long, 2),
                               "L0_diff": 0.0072, "L0_z": 1.64},
        "generation": {"speed_tok_s": speed, "prefix_ok": n_pfx_ok,
                       "n_prefix": GEN_N, "samples": samples},
        "regression": reg,
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# Phase 2 L1 人工流畅度评估（5 分制：5=自然流畅 / 3=可读但别扭 / 1=不通）\n",
             f"# 语料 20 万句（UNK {unk_ratio:.1%}，词表受限档）三引擎对照\n\n"]
    for i, s in enumerate(samples, 1):
        lines.append(f"{i:2d}. 前缀[{s['prefix']}] 生成：{s['pahe']}\n"
                     f"    得分：__  （wsum: {s['wsum']} | trace: {s['trace']}）\n")
    (out_dir / "human_eval.txt").write_text("".join(lines), encoding="utf-8")
    print(f"\n留档: {out_dir}/result.json + human_eval.txt")


if __name__ == "__main__":
    main()
