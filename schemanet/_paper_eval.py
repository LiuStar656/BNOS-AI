# -*- coding: utf-8 -*-
"""投稿补全实验 E1-E3（corpus_open）：多 seed 稳定性 + 困惑度 + 外部基线。

E1 多 seed：wsum/trace/grad 三路 top-1 × N seed → mean±std + 配对检验
E2 困惑度：三路在留出集上的 PPL（全位置 / 非 <UNK> 位置双口径，δ 平滑防零概率）
E3 外部基线：bigram / trigram MLE（+δ 平滑）、Kneser-Ney trigram（nltk）、
             LSTM 小模型（torch）——与 SchemaNet 同词表、同划分、同 UNK 处理

用法：
  python _paper_eval.py --seed 42                # 单 seed 全流程（对拍验证）
  python _paper_eval.py --seeds 42,43,44,45,46   # 多 seed（每 seed 独立留档，可中断续跑）
  python _paper_eval.py --summary                # 汇总已有留档 → mean±std + 配对检验
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema_net import _word_pattern, _learn_sentence, _BigramModel, _TrigramModel
from sparse_net import (SparseSchemaNet, _pats_matrix, outsum_sparse, build_score_mat,
                        evaluate_wsum_smat, evaluate_trace_smat, build_pulse, save_net)
from grad_readout import GradReadout

# ── 公共配置（与 _accept_open 标准档一致）────────────────────────────
N, K = 8192, 16
MAXLEN = 8
SEED_DEF = 42
CORPUS = "data/corpus_open.json"
KV = 3000
UNK = "<UNK>"
DELTA_SCAN = [0.005, 0.01, 0.02]
SCAN_SUB = 150
EVAL_SUB_TRAIN = 1000
EVAL_SUB_TEST = 600
SLEEP_DECAY = 0.3
SLEEP_EPS = 1e-4
TRAIN_W_EPOCHS = 5
TRAIN_W_LR = 0.02
PPL_DELTA = 1e-6          # PPL 平滑 δ
TRACE_BETA = 0.1          # trace 平局混合压降


def load_corpus(seed):
    """语料加载 + 词表 + 划分（rng = seed+9000）。返回 (train_toks, test_toks, vocab, vocab_idx)。"""
    tokenized = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
    freq = Counter(w for toks in tokenized for w in toks)
    vocab = [UNK] + [w for w, _ in freq.most_common(KV + 100) if w != UNK][:KV - 1]
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    rng = np.random.default_rng(seed + 9000)
    perm = rng.permutation(len(tokenized))
    n_train = int(len(tokenized) * 0.8)
    train_toks = [tokenized[i] for i in perm[:n_train]]
    test_toks = [tokenized[i] for i in perm[n_train:]]
    return train_toks, test_toks, vocab, vocab_idx


def build_positions(tokenized, vocab_idx):
    pos = []
    for toks in tokenized:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(1, len(ids)):
            pos.append((ids[:t], ids[t]))
    return pos


def train_schemanet(train_toks, vocab, seed, scan_toks=None, pats_fn=None):
    """完整训练流水线：Hebbian → sleep → delta 扫描 → train_w。返回评估所需对象。
    scan_toks: delta_off 扫描用句子集（None=跳过扫描，delta_off=0.02）。
    pats_fn: 模式生成器 fn(n, k, word)；None 用默认 _word_pattern（crc32 哈希，E7 对照组）。"""
    pats = {w: pats_fn(N, K, w) for w in vocab} if pats_fn is not None \
        else {w: _word_pattern(N, K, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    ng = SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=16.0, wta_k=K, noise_p=0.06, noise_amp=0.5,
                         weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                         refractory=1, rng=np.random.default_rng(seed + 5000))
    t0 = time.time()
    for toks in train_toks:
        ng.da = 1.0  # R-STDP 门控（2026-08-11）：mod=da_gain×da，da=0 不写边；教学=教师示范=正奖赏
        _learn_sentence(ng, toks, pats, slot=0)
    t_hebb = round(time.time() - t0, 1)

    fq = ng.slot_freq[:, 0]
    nz = fq[fq > 0]
    min_wake = float(np.percentile(nz, 10)) if len(nz) else 1.0
    min_wake = max(1.0, min_wake)
    nnz_pre = sum(len(ng.W_out[i][0]) for i in range(ng.n))
    t0 = time.time()
    cleared, weakened = ng.sleep_consolidate(min_wake=min_wake, decay=SLEEP_DECAY, eps=SLEEP_EPS)
    t_sleep = round(time.time() - t0, 1)
    nnz_post = sum(len(ng.W_out[i][0]) for i in range(ng.n))
    ng.learn_gate = False

    outsum = outsum_sparse(ng, pats, vocab, slot=0)
    S = build_score_mat(ng, pats, vocab, pats_mat, slot=0)

    # delta_off 扫描（独立 rng，不与评估采样子集共享）
    best_delta, best_t = 0.02, -1.0
    if scan_toks is not None and len(scan_toks) > 0:
        for d in DELTA_SCAN:
            t_ = evaluate_trace_smat(ng, scan_toks, S, pats, vocab, outsum, delta_off=d)
            if t_[0] > best_t:
                best_delta, best_t = d, t_[0]
    delta_off = best_delta

    # train_w（与 _accept_open 变体一致：跳过 train_ctx、lr=0.02/5ep/subsample=2000）
    ro = GradReadout(ng, pats, vocab, pats_mat, maxlen=MAXLEN)
    ro.snapshot_w()
    nnz0 = ro.nnz()
    positions = build_positions(train_toks, vocab_idx)
    t0 = time.time()
    ro.train_w(positions, lr=TRAIN_W_LR, epochs=TRAIN_W_EPOCHS, seed=seed, subsample=2000)
    ro.ctx_wgt = np.clip(ro.ctx_wgt, 0.0, None)
    s = float(ro.ctx_wgt.sum())
    if s > 0:
        ro.ctx_wgt = ro.ctx_wgt / s
    t_w = round(time.time() - t0, 1)
    nnz1 = ro.nnz()
    wd = ro.w_delta()
    ro.build_score_matrix()   # train_w（batch=1）不建 S；evaluate/logits 依赖 S_norm → 训练后重建

    return {"ng": ng, "ro": ro, "S": S, "outsum": outsum, "pats": pats,
            "pats_mat": pats_mat, "delta_off": delta_off, "vocab": vocab,
            "timing": {"hebbian": t_hebb, "sleep": t_sleep, "train_w": t_w,
                       "min_wake": round(min_wake, 1), "cleared": cleared,
                       "weakened": weakened, "nnz_pre": nnz_pre, "nnz_post": nnz_post},
            "w_delta": wd, "nnz_unchanged": nnz0 == nnz1}


# ── E2 困惑度核心：三路概率分布 ─────────────────────────────────────

def _sm(probs):
    """δ 平滑 + 归一化（防零概率）。"""
    p = probs + PPL_DELTA
    return p / p.sum()


def _nll_and_ppl(probs_by_pos, targets, unk_ids):
    """probs_by_pos: 每位置归一化概率（V 维）；targets: 每位置目标 id。返回 (ppl_all, ppl_no_unk, n_all, n_no_unk)。"""
    nll_all, nll_nu, n_all, n_nu = 0.0, 0.0, 0, 0
    for p, tgt in zip(probs_by_pos, targets):
        lp = -np.log(max(p[tgt], 1e-300))
        nll_all += lp
        n_all += 1
        if tgt not in unk_ids:
            nll_nu += lp
            n_nu += 1
    ppl_all = float(np.exp(nll_all / n_all)) if n_all else float("nan")
    ppl_nu = float(np.exp(nll_nu / n_nu)) if n_nu else float("nan")
    return ppl_all, ppl_nu, n_all, n_nu


def ppl_wsum(S, outsum, toks_list, vocab, vocab_idx, unk_ids):
    """P(w|last) = S[:,last]/outsum[last]，δ 平滑。"""
    V = len(vocab)
    probs, targets = [], []
    for toks in toks_list:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(1, len(ids)):
            last_w = vocab[ids[t - 1]]
            p = S[:, ids[t - 1]].astype(float).copy()
            den = outsum.get(last_w, 0.0) if outsum else 0.0
            if den > 0:
                p /= den
            probs.append(_sm(p))
            targets.append(ids[t])
    return _nll_and_ppl(probs, targets, unk_ids)


def ppl_trace(ng, S, outsum, toks_list, pats, vocab, vocab_idx, unk_ids,
              delta_off, trace_beta=TRACE_BETA):
    """trace：末词 δ 直判分布；平局时整条前缀痕迹混合（与 evaluate_trace_smat 同逻辑，
    但保留完整分布、不排除已见词）。需逐句推进网络状态累积 pre_trace。"""
    V = len(vocab)
    probs, targets = [], []
    for toks in toks_list:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.refractory_left = np.zeros(ng.n, dtype=int)
        ng.last_k_star = np.zeros(ng.n, dtype=int)
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(1, len(ids)):
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(build_pulse(ng.n, pats[vocab[ids[t - 1]]]), slot=0)
            ng.step(np.zeros(ng.n), slot=0)
            last_w = vocab[ids[t - 1]]
            p_last = S[:, ids[t - 1]].astype(float).copy()
            den = outsum.get(last_w, 0.0) if outsum else 0.0
            if den > 0:
                p_last /= den
            order = np.argsort(-p_last)
            top_idx = [wi for wi in order if p_last[wi] > 0]
            if len(top_idx) >= 2 and p_last[top_idx[0]] - p_last[top_idx[1]] >= delta_off:
                mix = p_last
            else:
                mix = np.zeros(V)
                last_pats = pats[last_w]
                trace_last = float(ng.pre_trace[last_pats].max()) if len(last_pats) else 0.0
                for src_w in toks[:t]:
                    if src_w not in vocab_idx:
                        continue
                    tr = float(ng.pre_trace[pats[src_w]].max()) if pats[src_w] else 0.0
                    wgt = tr / trace_last if trace_last > 0 else tr
                    if src_w != last_w:
                        wgt *= trace_beta
                    if wgt <= 0:
                        continue
                    p = S[:, vocab_idx[src_w]].astype(float).copy()
                    d2 = outsum.get(src_w, 0.0) if outsum else 0.0
                    if d2 > 0:
                        p /= d2
                    mix += wgt * p
            probs.append(_sm(mix))
            targets.append(ids[t])
    return _nll_and_ppl(probs, targets, unk_ids)


def ppl_grad(ro, toks_list, vocab, vocab_idx, unk_ids, use_w=False):
    """grad：softmax(logits)，δ 平滑。use_w=True 走微调 W 动态前向（原始尺度，
    与 evaluate_w 同口径——argmax/PPL 不受 S_norm 归一化影响）。"""
    probs, targets = [], []
    for toks in toks_list:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(1, len(ids)):
            if use_w:
                logits = ro._logits_w(ids[:t]).astype(float).copy()  # noqa: SLF001
            else:
                logits = ro.logits(ids[:t]).astype(float).copy()
            ex = np.exp(logits - logits.max())
            probs.append(_sm(ex / ex.sum()))
            targets.append(ids[t])
    return _nll_and_ppl(probs, targets, unk_ids)


# ── E3 外部基线 ─────────────────────────────────────────────────────

def _smooth_ppl_from_counts(cnt, toks_list, vocab_idx, unk_ids, order):
    """n-gram MLE + δ 平滑 PPL。cnt: (V^n) 前缀→Counter（MLE）。order=1 bigram / 2 trigram。"""
    V = len(vocab_idx)
    prefix_cnt = Counter()      # 前缀出现次数（用于归一化）
    for (pref, c) in cnt.items():
        pass
    probs, targets = [], []
    for toks in toks_list:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(order + 1, len(ids)):
            key = tuple(ids[t - order:t])
            row = cnt.get(key, {})
            tot = sum(row.values())
            if tot > 0:
                p = np.full(V, PPL_DELTA)
                for wid, c in row.items():
                    p[wid] = c / tot + PPL_DELTA
                p = p / p.sum()
            else:
                p = np.full(V, 1.0 / V)
            probs.append(p)
            targets.append(ids[t])
    return _nll_and_ppl(probs, targets, unk_ids)


def baseline_ngram(train_toks, test_toks, vocab, vocab_idx, unk_ids):
    """bigram / trigram MLE：top-1（复用 _BigramModel/_TrigramModel）+ δ 平滑 PPL。"""
    out = {}
    bm = _BigramModel(train_toks)
    tm = _TrigramModel(train_toks)

    def _top1(model, toks_list):
        hits = total = 0
        for toks in toks_list:
            ids = [vocab_idx[w] for w in toks if w in vocab_idx]
            for t in range(1, len(ids)):
                pred = model.predict(toks[:t])
                total += 1
                if pred == toks[t]:
                    hits += 1
        return hits / total if total else 0.0

    out["bigram_top1"] = _top1(bm, test_toks)
    out["trigram_top1"] = _top1(tm, test_toks)
    big_cnt = defaultdict(Counter)
    tri_cnt = defaultdict(Counter)
    for toks in train_toks:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for a, b in zip(ids, ids[1:]):
            big_cnt[(a,)][b] += 1
        for a, b, c in zip(ids, ids[1:], ids[2:]):
            tri_cnt[(a, b)][c] += 1
    out["bigram_ppl_all"], out["bigram_ppl_nu"], _, _ = _smooth_ppl_from_counts(
        big_cnt, test_toks, vocab_idx, unk_ids, 1)
    out["trigram_ppl_all"], out["trigram_ppl_nu"], _, _ = _smooth_ppl_from_counts(
        tri_cnt, test_toks, vocab_idx, unk_ids, 2)
    return out


def baseline_kneser_ney(train_toks, test_toks, vocab, vocab_idx, unk_ids):
    """插值 Kneser-Ney trigram（自实现，Chen & Goodman 1998 简化版，固定折扣 d=0.75）。
    优化：tot/n_plus 预计算查表；PPL 只算目标词概率（免 V 维分布构造）；
    top-1 全遍历 argmax（免归一化——单调不变）。"""
    V = len(vocab_idx)
    c_unigram = Counter()
    c_bigram = defaultdict(Counter)   # h(1) -> {w: c}
    c_trigram = defaultdict(Counter)  # h(2) -> {w: c}
    cont_bigram = defaultdict(Counter)  # continuation: (h,) -> {w: n(w 的后缀计数)}
    n1_plus = Counter()               # (h) -> 不同 w 的数目

    def _w1_count(w):  # 一元 continuation count：出现在多少个不同前缀后
        return len(cont_bigram[(w,)])

    for toks in train_toks:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for w in ids:
            c_unigram[w] += 1
        for a, b in zip(ids, ids[1:]):
            c_bigram[(a,)][b] += 1
            cont_bigram[(b,)][a] += 1   # b 出现在 a 后 → b 的一元 continuation
        for a, b, c in zip(ids, ids[1:], ids[2:]):
            c_trigram[(a, b)][c] += 1
    for h, cnt in c_bigram.items():
        n1_plus[h] = len(cnt)
    for h, cnt in c_trigram.items():
        n1_plus[h] = len(cnt)

    d = 0.75
    n1_uni = len(c_unigram)
    total_uni = sum(c_unigram.values())

    # 预计算查表（KN 每次调用避免 sum(values()) 的 O(n) 开销）
    tri_tot = {h: sum(cnt.values()) for h, cnt in c_trigram.items()}
    bi_tot = {h: sum(cnt.values()) for h, cnt in c_bigram.items()}

    def kn_uni(w):
        return _w1_count(w) / n1_uni if n1_uni else 1.0 / V

    def kn_bi(w, h):
        cnt = c_bigram.get((h,), {})
        c = cnt.get(w, 0)
        n_plus = n1_plus.get((h,), 0)
        tot = bi_tot.get((h,), 0)
        if tot == 0:
            return kn_uni(w)
        lam = (d * n_plus) / tot
        return max(c - d, 0.0) / tot + lam * kn_uni(w)

    def kn_tri(w, h1, h2):
        cnt = c_trigram.get((h1, h2), {})
        c = cnt.get(w, 0)
        n_plus = n1_plus.get((h1, h2), 0)
        tot = tri_tot.get((h1, h2), 0)
        if tot == 0:
            return kn_bi(w, h2)
        lam = (d * n_plus) / tot
        return max(c - d, 0.0) / tot + lam * kn_bi(w, h2)

    nll_all, nll_nu, n_all, n_nu = 0.0, 0.0, 0, 0
    top1_hits = top1_total = 0
    for toks in test_toks:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(1, len(ids)):
            w = ids[t]
            h1 = ids[t - 1]
            h2 = ids[t - 2] if t >= 2 else None
            p_w = kn_tri(w, h1, h2) if h2 is not None else kn_bi(w, h1)
            p_w += 1e-12
            lp = -np.log(p_w)
            nll_all += lp
            n_all += 1
            if w not in unk_ids:
                nll_nu += lp
                n_nu += 1
            # top-1：全遍历 argmax（未归一化分布 argmax 不变）
            top1_total += 1
            if h2 is not None:
                best = max(range(V), key=lambda wid: kn_tri(wid, h1, h2))
            else:
                best = max(range(V), key=lambda wid: kn_bi(wid, h1))
            if best == w:
                top1_hits += 1
    ppl_all = float(np.exp(nll_all / n_all)) if n_all else float("nan")
    ppl_nu = float(np.exp(nll_nu / n_nu)) if n_nu else float("nan")
    return {"kn_top1": top1_hits / top1_total if top1_total else 0.0,
            "kn_ppl_all": ppl_all, "kn_ppl_nu": ppl_nu}


def baseline_lstm(train_toks, test_toks, vocab, vocab_idx, unk_ids, seed=42, max_epochs=10):
    """LSTM 小模型：embed=128/hidden=128/1层，Adam，段切分训练。同词表同划分。"""
    import torch
    import torch.nn as nn

    V = len(vocab)
    EMB, HID, LAYERS = 128, 128, 1
    DROP = 0.0 if LAYERS == 1 else 0.2   # 单层 LSTM 无 dropout 位置（torch 警告）
    SEQ = 35
    BATCH = 64

    def to_ids(toks_list):
        return [vocab_idx[w] for w in toks_list if w in vocab_idx]

    train_ids = to_ids([w for toks in train_toks for w in toks])
    # 训练集内再切 10% 作验证（按 token 数）
    n_val = int(len(train_ids) * 0.1)
    val_ids = train_ids[-n_val:]
    tr_ids = train_ids[:-n_val]

    class LSTMLM(nn.Module):
        def __init__(self):
            super().__init__()
            self.embed = nn.Embedding(V, EMB)
            self.lstm = nn.LSTM(EMB, HID, LAYERS, dropout=DROP, batch_first=True)
            self.fc = nn.Linear(HID, V)

        def forward(self, x):
            h = self.lstm(self.embed(x))[0]
            return self.fc(h)

    def chunks(ids, length=SEQ):
        return [ids[i:i + length] for i in range(0, len(ids) - length + 1, length)]

    tr_ch = chunks(tr_ids)
    val_ch = chunks(val_ids)
    te_ch = chunks(to_ids([w for toks in test_toks for w in toks]))

    torch.manual_seed(seed)
    model = LSTMLM()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    lossf = nn.CrossEntropyLoss()

    def run_epoch(data, train=True):
        model.train(train)
        tot_nll, n = 0.0, 0
        rng = np.random.default_rng(seed)
        perm = rng.permutation(len(data))
        for b0 in range(0, len(perm), BATCH):
            batch = [data[i] for i in perm[b0:b0 + BATCH]]
            x = torch.tensor([ch[:-1] for ch in batch])
            y = torch.tensor([ch[1:] for ch in batch])
            if train:
                opt.zero_grad()
                out = model(x)
                loss = lossf(out.reshape(-1, V), y.reshape(-1))
                loss.backward()
                opt.step()
                tot_nll += float(loss.item()) * y.numel()
            else:
                with torch.no_grad():
                    out = model(x)
                    loss = lossf(out.reshape(-1, V), y.reshape(-1))
                    tot_nll += float(loss.item()) * y.numel()
            n += y.numel()
        return float(np.exp(tot_nll / n))

    best_ppl, best_ep = None, 0
    t0 = time.time()
    for ep in range(1, max_epochs + 1):
        tr_ppl = run_epoch(tr_ch, train=True)
        val_ppl = run_epoch(val_ch, train=False)
        if best_ppl is None or val_ppl < best_ppl:
            best_ppl, best_ep = val_ppl, ep
            torch.save(model.state_dict(), Path(__file__).resolve().parent / "runs/_lstm_best.pt")
    model.load_state_dict(torch.load(Path(__file__).resolve().parent / "runs/_lstm_best.pt",
                                     map_location="cpu", weights_only=True))
    t_lstm = round(time.time() - t0, 1)

    # 测试集 PPL + top-1（逐段）
    model.eval()
    tot_nll, n = 0.0, 0
    top1_hits = top1_total = 0
    with torch.no_grad():
        for ch in te_ch:
            x = torch.tensor([ch[:-1]])
            y = torch.tensor(ch[1:])
            out = model(x)[0]
            lsm = torch.log_softmax(out, dim=-1)
            tot_nll += float(-lsm[torch.arange(len(y)), y].sum())
            n += len(y)
            preds = out.argmax(dim=-1).tolist()
            top1_hits += sum(1 for p, t in zip(preds, y.tolist()) if p == t)
            top1_total += len(y)
    return {"lstm_ppl_all": float(np.exp(tot_nll / n)), "lstm_top1": top1_hits / max(1, top1_total),
            "lstm_epochs": best_ep, "lstm_val_ppl": best_ppl, "lstm_sec": t_lstm}


# ── E5 能力外置（分离脚本调用，此处只留接口）────────────────────────
def main_single(seed):
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    t_start = time.time()
    print(f"── seed={seed} ──", flush=True)
    train_toks, test_toks, vocab, vocab_idx = load_corpus(seed)
    unk_ids = {vocab_idx[UNK]} if UNK in vocab_idx else set()
    print(f"corpus_open: train {len(train_toks)} / test {len(test_toks)}，词表 {len(vocab)}", flush=True)

    rng_scan = np.random.default_rng(seed + 9002)
    scan_toks = [test_toks[i] for i in
                 rng_scan.choice(len(test_toks), min(SCAN_SUB, len(test_toks)), replace=False)]
    r = train_schemanet(train_toks, vocab, seed, scan_toks=scan_toks)
    ng, ro, S, outsum, delta_off = (r["ng"], r["ro"], r["S"], r["outsum"], r["delta_off"])
    print(f"Hebbian {r['timing']['hebbian']}s | sleep {r['timing']['sleep']}s "
          f"(min_wake={r['timing']['min_wake']}) | delta_off={delta_off} | "
          f"train_w {r['timing']['train_w']}s", flush=True)

    # 评估采样子集（独立 rng，不参与 delta 扫描）
    rng = np.random.default_rng(seed + 9001)
    ev_tr = [train_toks[i] for i in
             rng.choice(len(train_toks), min(EVAL_SUB_TRAIN, len(train_toks)), replace=False)]
    ev_te = [test_toks[i] for i in
             rng.choice(len(test_toks), min(EVAL_SUB_TEST, len(test_toks)), replace=False)]

    # E1：三路 top-1
    w_tr = evaluate_wsum_smat(S, vocab, ev_tr, norm_base=outsum)
    w_te = evaluate_wsum_smat(S, vocab, ev_te, norm_base=outsum)
    t_tr = evaluate_trace_smat(ng, ev_tr, S, r["pats"], vocab, outsum, delta_off=delta_off)
    t_te = evaluate_trace_smat(ng, ev_te, S, r["pats"], vocab, outsum, delta_off=delta_off)
    g_tr = ro.evaluate_w(ev_tr)
    g_te = ro.evaluate_w(ev_te)
    top1 = {"wsum": {"train": w_tr[0], "test": w_te[0]},
            "trace": {"train": t_tr[0], "test": t_te[0]},
            "grad": {"train": g_tr[0], "test": g_te[0]},
            "eval_n": {"train": len(ev_tr), "test": len(ev_te)}}
    print(f"E1 top-1: wsum {w_tr[0]:.4f}/{w_te[0]:.4f}  trace {t_tr[0]:.4f}/{t_te[0]:.4f}  "
          f"grad {g_tr[0]:.4f}/{g_te[0]:.4f}", flush=True)

    # E2：三路 PPL（留出集，双口径）
    ppl = {}
    ppl["wsum"] = ppl_wsum(S, outsum, ev_te, vocab, vocab_idx, unk_ids)
    ppl["trace"] = ppl_trace(ng, S, outsum, ev_te, r["pats"], vocab, vocab_idx, unk_ids, delta_off)
    ppl["grad"] = ppl_grad(ro, ev_te, vocab, vocab_idx, unk_ids, use_w=True)
    for k, (a, nu, na, nn) in ppl.items():
        print(f"E2 PPL[{k}]: all {a:.1f} / no-unk {nu:.1f} (n={na})", flush=True)

    # E3：基线（bigram/trigram 只在 seed=42 跑，KN/LSTM 同理——同一词表/划分，跨 seed 只变划分，
    #      为省时基线段默认仅首个 seed 计算，汇总时共享）
    baselines = {}
    if seed == SEED_DEF:
        baselines.update(baseline_ngram(train_toks, test_toks, vocab, vocab_idx, unk_ids))
        print(f"E3 n-gram: bigram top1 {baselines['bigram_top1']:.4f} "
              f"ppl {baselines['bigram_ppl_all']:.1f} | trigram top1 {baselines['trigram_top1']:.4f} "
              f"ppl {baselines['trigram_ppl_all']:.1f}", flush=True)
        try:
            baselines.update(baseline_kneser_ney(train_toks, test_toks, vocab, vocab_idx, unk_ids))
            print(f"E3 KN: top1 {baselines['kn_top1']:.4f} ppl {baselines['kn_ppl_all']:.1f}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"E3 KN failed: {e}", flush=True)
            baselines["kn_error"] = str(e)
        try:
            baselines.update(baseline_lstm(train_toks, test_toks, vocab, vocab_idx, unk_ids, seed=seed))
            print(f"E3 LSTM: top1 {baselines['lstm_top1']:.4f} ppl {baselines['lstm_ppl_all']:.1f} "
                  f"ep {baselines['lstm_epochs']}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"E3 LSTM failed: {e}", flush=True)
            baselines["lstm_error"] = str(e)

    result = {
        "seed": seed, "corpus": CORPUS, "delta_off": delta_off,
        "config": {"n": N, "k": K, "vocab": len(vocab), "maxlen": MAXLEN,
                   "train_w_epochs": TRAIN_W_EPOCHS, "train_w_lr": TRAIN_W_LR,
                   "seed": seed},
        "timing": r["timing"], "w_delta": r["w_delta"], "nnz_unchanged": r["nnz_unchanged"],
        "top1": top1,
        "ppl": {k: {"all": float(v[0]), "no_unk": float(v[1]), "n": v[2]}
                for k, v in ppl.items()},
        "baselines": baselines,
        "elapsed_sec": round(time.time() - t_start, 1),
    }
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("runs") / f"paper_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    save_net(ng, vocab, out_dir / "net.npz", ctx_wgt=ro.ctx_wgt)
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print(f"留档: {out_dir}/  elapsed {result['elapsed_sec']}s", flush=True)


def main_summary():
    """汇总 runs/paper_* 留档：三路 top-1/PPL 的 mean±std + 三路两两配对检验。"""
    import glob
    rows = []
    for p in sorted(glob.glob("runs/paper_*/result.json")):
        rows.append(json.loads(Path(p).read_text(encoding="utf-8")))
    if not rows:
        print("无 paper_* 留档。先运行 --seed / --seeds。")
        return
    seeds = sorted({r["seed"] for r in rows})
    print(f"共 {len(rows)} 个留档，seed: {seeds}")

    def stats(key, sub="test"):
        vals = [r["top1"][key][sub] for r in rows]
        return np.mean(vals), np.std(vals), vals

    print("\n=== E1 top-1（test，mean±std，n=%d）===" % len(rows))
    for k in ("wsum", "trace", "grad"):
        m, s, v = stats(k)
        print(f"  {k:6s}: {m:.4f} ± {s:.4f}   {[round(x, 4) for x in v]}")

    print("\n=== E2 PPL（test）===")
    for k in ("wsum", "trace", "grad"):
        for sub in ("all", "no_unk"):
            vals = [r["ppl"][k][sub] for r in rows]
            print(f"  {k:6s} {sub:7s}: {np.mean(vals):.1f} ± {np.std(vals):.1f}")

    # 配对检验：三路两两（binomial 近似 z）
    print("\n=== 配对检验（test top-1，McNemar 近似 z）===")
    v = {k: [r["top1"][k]["test"] for r in rows] for k in ("wsum", "trace", "grad")}
    for a, b in (("trace", "wsum"), ("grad", "wsum"), ("grad", "trace")):
        da = np.mean(v[a]) - np.mean(v[b])
        # 合并 n 估算 z（以平均 eval_n 计）
        n = int(np.mean([r["top1"]["eval_n"]["test"] for r in rows]))
        p_avg = (np.mean(v[a]) + np.mean(v[b])) / 2
        se = np.sqrt(2 * p_avg * (1 - p_avg) / n) if 0 < p_avg < 1 else 1e-9
        z = da / se if se > 0 else float("nan")
        print(f"  {a} - {b}: Δ={da:+.4f}  z={z:+.2f}")

    if any("baselines" in r and r["baselines"] for r in rows):
        b0 = next(r["baselines"] for r in rows if r["baselines"])
        print("\n=== E3 基线（seed=%d 同词表同划分）===" % SEED_DEF)
        for k, val in b0.items():
            if not k.startswith("lstm_sec") and not k.endswith("_error"):
                print(f"  {k}: {val}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--seeds", type=str, default=None)
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args()
    if a.summary:
        main_summary()
        return
    if a.seeds:
        seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    elif a.seed is not None:
        seeds = [a.seed]
    else:
        seeds = [SEED_DEF]
    for s in seeds:
        main_single(s)


if __name__ == "__main__":
    main()
