# -*- coding: utf-8 -*-
"""定式网络（SchemaNet）稀疏实现 —— Phase 2 规模扩展专用。

背景：n 大幅扩大后（8192+），稠密 W[n, slots, n] 内存爆炸（8192²×4×8B≈2GB），
必须稀疏存储。实测语言实验 W 非零率仅 0.11%（Hebbian/STDP 只强化共现对），
稀疏化收益是数量级：W 从 2GB → MB 级，传播/更新只碰非零行（O(非零)）。

SparseSchemaNet 与 schema_net.SchemaNet 的 step() 动力学**完全一致**
（积分-发放 + WTA + Hebbian + STDP + 痕迹 + 不应期 + 学习门），仅 W 存储
从稠密矩阵改为稀疏字典：

    W_out[i][k] = {j: w}   神经元 i 槽 k → 神经元 j 的出边权重
    （语义 = 稠密 SchemaNet.W[j, k, i]，j 的入连接来自 i）

RNG 调用点与稠密完全一致（仅 noise 一步）→ 同种子同噪声序列 → 学习结果
逐值一致（_check_sparse.py 对拍验证）。

用法：
    python sparse_net.py --corpus data/corpus_large.json --n 8192 --k 16 --kv 2000
"""

import argparse
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

from schema_net import (SchemaNet, _word_pattern, _learn_sentence, _evoke_prefix,
                        _BigramModel, _TrigramModel, _evaluate_ngram, build_pulse,
                        _generate)


# ════════════════════════════════════════════════════════════════
#  稀疏网络核心（动力学对齐 schema_net.SchemaNet）
# ════════════════════════════════════════════════════════════════

class SparseSchemaNet:
    """定式网络稀疏版：与 SchemaNet.step() 动力学完全一致，W 稀疏存储。

    语言实验只用 slot=0，但为行为对齐保留多槽完整实现（噪声打所有槽、
    Hebbian/STDP 写到主导槽 k_star、传播按主导槽分桶）。
    """

    def __init__(self, n=8192, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                 w_max=16.0, wta_k=16, noise_p=0.06, noise_amp=0.5,
                 weight_decay=0.0, slot_cap=0.0, learn_gate=True,
                 stdp_pre=0.5, stdp_neg=0.0, trace_decay=0.5, refractory=1,
                 rng=None):
        self.n = n
        self.slots = slots
        self.theta = theta
        self.membrane_decay = membrane_decay
        self.eta = eta
        self.w_max = w_max
        self.wta_k = wta_k
        self.noise_p = noise_p
        self.noise_amp = noise_amp
        self.weight_decay = weight_decay
        self.slot_cap = slot_cap
        self.learn_gate = learn_gate
        self.stdp_pre = stdp_pre
        self.stdp_neg = stdp_neg
        self.trace_decay = trace_decay
        self.trace_thres = 0.3
        self.refractory = refractory
        self.rng = rng or np.random.default_rng()
        self.reset()

    def reset(self):
        self.v = np.zeros((self.n, self.slots))
        self.spikes = np.zeros(self.n)
        self.last_k_star = np.zeros(self.n, dtype=int)
        self.pre_trace = np.zeros(self.n)
        self.refractory_left = np.zeros(self.n, dtype=int)
        self.evictions = 0
        # 稀疏出边：W_out[i][k] = {j: w}，语义 = 稠密 W[j, k, i]
        self.W_out = [[{} for _ in range(self.slots)] for _ in range(self.n)]

    # ── W 访问兼容：稠密版读出函数用 ng.W[j, slot, i]，这里按需提供等价读取 ──
    def w_get(self, j, slot, i):
        """等价稠密 ng.W[j, slot, i]（j 的入连接来自 i）。"""
        return self.W_out[i][slot].get(j, 0.0)

    def w_rowsum(self, src, slot=0):
        """等价 Σ_j 稠密 W[j, slot, src]（源神经元出边总强度）。"""
        return sum(self.W_out[src][slot].values())

    def step(self, input_pulse, slot=0):
        """单步动力学：与 SchemaNet.step 逐行对齐（详见 schema_net.py 的注释）。"""
        slot = min(slot, self.slots - 1)
        noise = (self.rng.random(self.n) < self.noise_p) * self.noise_amp
        self.v = self.v * self.membrane_decay + noise[:, None]
        self.v[:, slot] += input_pulse

        # 分槽传播（稀疏：只遍历发放神经元出边的非零行）
        if self.spikes.any():
            for k in range(self.slots):
                senders = np.where((self.spikes > 0) & (self.last_k_star == k))[0]
                if len(senders):
                    drive = np.zeros(self.n)
                    for i in senders:
                        row = self.W_out[i][k]
                        if row:
                            for j, w in row.items():
                                drive[j] += w
                    self.v[:, k] += drive

        # 主导槽 + WTA
        k_star = self.v.argmax(axis=1)
        vmax = self.v[np.arange(self.n), k_star]

        eligible = np.ones(self.n, dtype=bool)
        if self.refractory > 0:
            eligible = self.refractory_left == 0
        candidates = np.where((vmax >= self.theta) & eligible)[0]
        if len(candidates) > self.wta_k:
            top = candidates[np.argsort(vmax[candidates])[::-1][: self.wta_k]]
        else:
            top = candidates

        new_spikes = np.zeros(self.n)
        if len(top):
            new_spikes[top] = 1.0
            if self.learn_gate:
                # Hebbian：共同发放对 (a, c) → W[a, kstar_a, c] += eta（排除自连接）
                # 稀疏：W_out[c][kstar_a][a] += eta
                for a in top:
                    ka = int(k_star[a])
                    for c in top:
                        if a == c:
                            continue
                        row = self.W_out[c][ka]
                        row[a] = min(row.get(a, 0.0) + self.eta, self.w_max)
                # STDP：前驱痕迹 → 当前发放，学 W[后继 ← 前驱]（只正向）
                if (self.stdp_pre > 0 or self.stdp_neg > 0) and self.pre_trace.any():
                    pre_idx = np.where(self.pre_trace > self.trace_thres)[0]
                    if self.stdp_pre > 0 and len(pre_idx):
                        for jj in top:
                            kj = int(k_star[jj])
                            for pp in pre_idx:
                                if jj == pp:
                                    continue
                                row = self.W_out[pp][kj]
                                row[jj] = min(row.get(jj, 0.0) + self.stdp_pre, self.w_max)
                    if self.stdp_neg > 0 and len(pre_idx):
                        # LTD：当前发放（后发）→ 前驱入连接反序弱化
                        # W[pre_i, kstar_pre_i, top_j] -= stdp_neg
                        for pp in pre_idx:
                            kp = int(k_star[pp])
                            for jj in top:
                                if pp == jj:
                                    continue
                                row = self.W_out[jj][kp]
                                nv = row.get(pp, 0.0) - self.stdp_neg
                                row[pp] = max(nv, 0.0)
                if self.weight_decay:
                    for i in range(self.n):
                        for k in range(self.slots):
                            row = self.W_out[i][k]
                            if row:
                                for j, w in list(row.items()):
                                    row[j] = max(w * (1.0 - self.weight_decay), 0.0)

        self.v[top, :] = 0.0
        self.spikes = new_spikes
        self.last_k_star = k_star
        self.pre_trace = self.pre_trace * self.trace_decay + new_spikes
        if self.refractory > 0:
            self.refractory_left = np.maximum(self.refractory_left - 1, 0)
            if len(top):
                self.refractory_left[top] = self.refractory
        return new_spikes


# ════════════════════════════════════════════════════════════════
#  向量化稀疏读出（等价 schema_net._predict_cands_wsum / _predict_cands_trace）
# ════════════════════════════════════════════════════════════════

def _pats_matrix(pats, vocab):
    """词模式 → (V, k) 神经元索引数组（纯 numpy 向量化读出）。"""
    return np.array([pats[w] for w in vocab], dtype=int)


def _out_edges_accum(ng, src_idxs, slot):
    """源神经元集合 → 出边聚合向量（n 维）。"""
    acc = np.zeros(ng.n)
    for i in src_idxs:
        row = ng.W_out[i][slot]
        if row:
            for j, w in row.items():
                acc[j] += w
    return acc


def predict_cands_wsum_sparse(ng, prefix, pats, vocab, pats_mat, slot=0, norm_base=None):
    """等价 schema_net._predict_cands_wsum（向量化）。"""
    last = prefix[-1]
    used = set(prefix)
    acc = _out_edges_accum(ng, pats[last], slot)
    scores = acc[pats_mat].sum(axis=1) / pats_mat.shape[1]
    denom = norm_base.get(last, 0.0) if norm_base else 0.0
    if denom > 0:
        scores = scores / denom
    cands = [(vocab[wi], float(scores[wi])) for wi in range(len(vocab))
             if scores[wi] > 0 and vocab[wi] not in used]
    cands.sort(key=lambda x: -x[1])
    return cands


def predict_cands_trace_sparse(ng, prefix, pats, vocab, pats_mat, slot=0, norm_base=None,
                               trace_beta=0.1, delta_off=0.05):
    """等价 schema_net._predict_cands_trace（向量化）。"""
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)
    for w in prefix:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.step(build_pulse(ng.n, pats[w]), slot=slot)
        ng.step(np.zeros(ng.n), slot=slot)
    last = prefix[-1]
    used = set(prefix)
    k = pats_mat.shape[1]

    def cond_vec(src_idxs):
        acc = _out_edges_accum(ng, src_idxs, slot)
        raw = acc[pats_mat].sum(axis=1) / k
        denom = norm_base.get(prefix[-1], 0.0) if norm_base else 0.0
        return raw / denom if denom > 0 else raw

    # 末词条件分布 → δ 判定
    p_last = cond_vec(pats[last])
    order = np.argsort(-p_last)
    top_idx = [wi for wi in order if p_last[wi] > 0 and vocab[wi] not in used]
    if len(top_idx) >= 2 and p_last[top_idx[0]] - p_last[top_idx[1]] >= delta_off:
        return [(vocab[wi], round(float(p_last[wi]), 6)) for wi in top_idx]

    # 末词平局：整条前缀加权混合
    last_pats = pats[last]
    trace_last = float(ng.pre_trace[last_pats].max()) if len(last_pats) else 0.0
    mix = np.zeros(len(vocab))
    for src_w in prefix:
        tr = float(ng.pre_trace[pats[src_w]].max()) if pats[src_w] else 0.0
        wgt = tr / trace_last if trace_last > 0 else tr
        if src_w != last:
            wgt *= trace_beta
        if wgt <= 0:
            continue
        acc = _out_edges_accum(ng, pats[src_w], slot)
        raw = acc[pats_mat].sum(axis=1) / k
        denom = norm_base.get(src_w, 0.0) if norm_base else 0.0
        p = raw / denom if denom > 0 else raw
        mix += wgt * p
    cands = [(vocab[wi], round(float(mix[wi]), 6)) for wi in range(len(vocab))
             if mix[wi] > 0 and vocab[wi] not in used]
    cands.sort(key=lambda x: -x[1])
    return cands


def outsum_sparse(ng, pats, vocab, slot=0):
    """等价稠密 outsum：源词模式所有神经元的出边总强度。"""
    return {a: sum(ng.w_rowsum(src, slot) for src in pats[a]) for a in vocab}


def evaluate_schemanet_sparse(ng, toks_list, pats, vocab, pats_mat, slot=0,
                              readout="wsum", norm_base=None, n_samples=8,
                              delta_off=0.05):
    """稀疏版 next-token 评估（readout: wsum / wnorm / trace）。"""
    hits = total = 0
    samples = []
    for toks in toks_list:
        for t in range(1, len(toks)):
            if readout == "wsum":
                cands = predict_cands_wsum_sparse(ng, toks[:t], pats, vocab, pats_mat,
                                                  slot=slot)
            elif readout == "wnorm":
                cands = predict_cands_wsum_sparse(ng, toks[:t], pats, vocab, pats_mat,
                                                  slot=slot, norm_base=norm_base)
            else:
                cands = predict_cands_trace_sparse(ng, toks[:t], pats, vocab, pats_mat,
                                                   slot=slot, norm_base=norm_base,
                                                   delta_off=delta_off)
            pred = cands[0][0] if cands else None
            total += 1
            if pred == toks[t]:
                hits += 1
            elif len(samples) < n_samples:
                samples.append({"ctx": "".join(toks[:t]), "truth": toks[t], "pred": pred,
                                "top3": [c[0] for c in cands[:3]]})
    return (hits / total if total else 0.0), hits, total, samples


# ════════════════════════════════════════════════════════════════
#  规模实验主流程
# ════════════════════════════════════════════════════════════════

def run_sparse_language_experiment(args):
    data_dir = Path(__file__).parent / "data"
    corpus = json.loads((data_dir / args.corpus).read_text(encoding="utf-8"))

    import jieba
    t0 = time.time()
    tokenized = [jieba.lcut(s) for s in corpus]
    freq = Counter(w for toks in tokenized for w in toks)
    vocab = [w for w, _ in freq.most_common(args.kv)]
    vocab_set = set(vocab)
    oov = sum(1 for toks in tokenized for w in toks if w not in vocab_set)
    t_token = time.time() - t0

    # ── 编码预检：碰撞对（k 中 ≥2 个重叠的词对占比）──
    t0 = time.time()
    pats = {w: _word_pattern(args.n, args.k, w) for w in vocab}
    coll_ge2 = 0
    vlist = list(vocab)
    for i in range(len(vlist)):
        pi = set(pats[vlist[i]])
        for j in range(i + 1, len(vlist)):
            if len(pi & set(pats[vlist[j]])) >= 2:
                coll_ge2 += 1
    pairs = len(vlist) * (len(vlist) - 1) // 2
    t_encode = time.time() - t0

    # ── 数据划分 ──
    rng_split = np.random.default_rng(args.seed + 9000)
    perm = rng_split.permutation(len(tokenized))
    n_train = int(len(tokenized) * args.split)
    train_toks = [tokenized[i] for i in perm[:n_train]]
    test_toks = [tokenized[i] for i in perm[n_train:]]

    # ── 学习（稀疏）──
    t0 = time.time()
    ng = SparseSchemaNet(n=args.n, slots=4, theta=1.0, membrane_decay=0.9,
                         eta=0.1, w_max=args.wmax, wta_k=args.k,
                         noise_p=0.06, noise_amp=0.5, weight_decay=0.0,
                         slot_cap=0.0, stdp_pre=args.stdp_pre, stdp_neg=0.0,
                         refractory=1, rng=np.random.default_rng(args.seed + 5000))
    for toks in train_toks:
        _learn_sentence(ng, toks, pats, slot=0)
    ng.learn_gate = False  # 评估冻结
    t_learn = time.time() - t0

    # ── W 非零率 / 内存 ──
    nnz = sum(len(row) for rows in ng.W_out for row in rows)
    nnz_ratio = nnz / (args.n * 4 * args.n)  # slots=4 硬编码（与构造一致）
    w_mem = nnz * (8 + 8 + 24)  # 每非零项约：key 8B + value 8B + dict 开销 ~24B（粗略）
    rss_mb = _rss_mb()

    # ── 评估 ──
    pats_mat = _pats_matrix(pats, vocab)
    outsum = outsum_sparse(ng, pats, vocab, slot=0)
    t0 = time.time()
    wsum_train = evaluate_schemanet_sparse(ng, train_toks, pats, vocab, pats_mat,
                                           readout="wsum")
    wsum_test = evaluate_schemanet_sparse(ng, test_toks, pats, vocab, pats_mat,
                                          readout="wsum")
    tr_train = evaluate_schemanet_sparse(ng, train_toks, pats, vocab, pats_mat,
                                         readout="trace", norm_base=outsum,
                                         delta_off=args.delta_off)
    tr_test = evaluate_schemanet_sparse(ng, test_toks, pats, vocab, pats_mat,
                                        readout="trace", norm_base=outsum,
                                        delta_off=args.delta_off)
    bi = _BigramModel(train_toks)
    tri = _TrigramModel(train_toks)
    bi_train = _evaluate_ngram(bi, train_toks)
    bi_test = _evaluate_ngram(bi, test_toks)
    tri_train = _evaluate_ngram(tri, train_toks)
    tri_test = _evaluate_ngram(tri, test_toks)
    t_eval = time.time() - t0

    # ── 消歧（trace）──
    disambig = []
    for cue, truth in [("我觉得", "很"), ("我今天", "很"), ("我想", "吃"), ("我喜欢吃", "苹果")]:
        cands = predict_cands_trace_sparse(ng, jieba.lcut(cue), pats, vocab, pats_mat,
                                           norm_base=outsum, delta_off=args.delta_off)
        disambig.append({"cue": cue, "truth": truth,
                         "top": [w for w, _ in cands[:5]],
                         "hit": bool(cands) and cands[0][0] == truth})

    # ── 生成样例 ──
    generations = []
    for start in ("你好", "我", "今天"):
        gen = _generate(ng, start, pats, vocab, max_len=12, min_cov=0.4)
        generations.append({"start": start, "seq": gen})

    return {
        "args": vars(args),
        "corpus": {"n_sent": len(corpus), "n_train": len(train_toks),
                   "n_test": len(test_toks), "vocab_size": len(vocab),
                   "oov": oov, "tokens_total": sum(len(t) for t in tokenized)},
        "encoding": {"n": args.n, "k": args.k, "collisions_ge2": coll_ge2,
                     "pairs": pairs},
        "freq_top10": freq.most_common(10),
        "scale": {"nnz": nnz, "nnz_ratio": nnz_ratio, "w_mem_bytes": w_mem,
                  "rss_mb": rss_mb},
        "timing": {"tokenize": t_token, "encode": t_encode, "learn": t_learn,
                   "eval": t_eval},
        "wsum": {"train": wsum_train, "test": wsum_test},
        "trace": {"train": tr_train, "test": tr_test},
        "bigram": {"train": bi_train, "test": bi_test},
        "trigram": {"train": tri_train, "test": tri_test},
        "disambig_trace": disambig,
        "generation": generations,
    }


# ════════════════════════════════════════════════════════════════
#  序列化（Phase 3 生成调参用：train_w 一次，反复调生成参数免重训）
# ════════════════════════════════════════════════════════════════

def save_net(ng, vocab, path):
    """序列化稀疏网络（W_out + 构造参数）+ 词表。npz 压缩。"""
    src_i, slot_k, dst_j, vals = [], [], [], []
    for i in range(ng.n):
        for k in range(ng.slots):
            for j, w in ng.W_out[i][k].items():
                src_i.append(i)
                slot_k.append(k)
                dst_j.append(j)
                vals.append(w)
    params = {"n": ng.n, "slots": ng.slots, "theta": ng.theta,
              "membrane_decay": ng.membrane_decay, "eta": ng.eta, "w_max": ng.w_max,
              "wta_k": ng.wta_k, "noise_p": ng.noise_p, "noise_amp": ng.noise_amp,
              "weight_decay": ng.weight_decay, "slot_cap": ng.slot_cap,
              "stdp_pre": ng.stdp_pre, "stdp_neg": ng.stdp_neg,
              "trace_decay": ng.trace_decay, "refractory": ng.refractory,
              "learn_gate": ng.learn_gate}
    np.savez_compressed(path,
                        src_i=np.array(src_i, dtype=np.int32),
                        slot_k=np.array(slot_k, dtype=np.int8),
                        dst_j=np.array(dst_j, dtype=np.int32),
                        vals=np.array(vals, dtype=np.float32),
                        params=json.dumps(params).encode("utf-8"),
                        vocab=json.dumps(vocab, ensure_ascii=False).encode("utf-8"))


def load_net(path, seed=42):
    """反序列化：返回 (SparseSchemaNet, vocab)。"""
    z = np.load(path, allow_pickle=False)
    params = json.loads(z["params"].tobytes().decode("utf-8"))
    vocab = json.loads(z["vocab"].tobytes().decode("utf-8"))
    ng = SparseSchemaNet(rng=np.random.default_rng(seed), **params)
    src_i, slot_k, dst_j, vals = z["src_i"], z["slot_k"], z["dst_j"], z["vals"]
    for i, k, j, w in zip(src_i, slot_k, dst_j, vals):
        ng.W_out[int(i)][int(k)][int(j)] = float(w)
    return ng, vocab


def _rss_mb():
    """进程常驻内存（Windows 兼容，见 memory 踩坑：GetProcessMemoryInfo 需 argtypes）。"""
    try:
        import ctypes
        from ctypes import wintypes
        psapi = ctypes.windll.psapi
        kernel32 = ctypes.windll.kernel32
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        handle = kernel32.GetCurrentProcess()
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                               ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                                               wintypes.DWORD]
        psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        return round(counters.WorkingSetSize / (1024 * 1024), 1)
    except Exception:
        return None


def print_scale_report(r):
    a = r["args"]
    print("=" * 62)
    print(f"定式网络规模实验（Phase 2 稀疏版） n={a['n']} k={a['k']} 词表={r['corpus']['vocab_size']}")
    print("=" * 62)
    c = r["corpus"]
    print(f"语料：{c['n_sent']} 句（训练 {c['n_train']} / 留出 {c['n_test']}），token 总量 {c['tokens_total']}，OOV {c['oov']}")
    e = r["encoding"]
    print(f"编码预检：碰撞对(≥2重叠) {e['collisions_ge2']}/{e['pairs']} "
          f"({e['collisions_ge2']/e['pairs']*100:.3f}%)")
    s = r["scale"]
    print(f"W 稀疏：非零 {s['nnz']}（比例 {s['nnz_ratio']*100:.4f}%），"
          f"估计内存 {s['w_mem_bytes']/1e6:.1f}MB，进程 RSS {s['rss_mb']}MB")
    print(f"耗时：分词 {r['timing']['tokenize']:.1f}s 编码 {r['timing']['encode']:.1f}s "
          f"学习 {r['timing']['learn']:.1f}s 评估 {r['timing']['eval']:.1f}s")
    print("-" * 62)
    print(f"{'模型':<14}{'训练集':<10}{'留出':<10}{'hits/total'}")
    for name, d in [("SchemaNet-wsum", r["wsum"]), ("SchemaNet-trace", r["trace"]),
                    ("bigram", r["bigram"]), ("trigram", r["trigram"])]:
        acc, hits, total, _ = d["train"]
        acc2, _, _, _ = d["test"]
        print(f"{name:<14}{acc:<10.4f}{acc2:<10.4f}{hits}/{total}")
    print("-" * 62)
    print("trace 消歧：", "  ".join(
        f"{d['cue']}→{'✓' if d['hit'] else '✗'}({d['top'][0] if d['top'] else '-'})" for d in r["disambig_trace"]))
    print("生成样例：")
    for g in r["generation"]:
        print(f"  '{g['start']}' → {' '.join(g['seq'])}")
    print("=" * 62)


def save_scale_run(r, args):
    runs = Path(__file__).parent / "runs"
    runs.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = runs / f"{ts}"
    out.mkdir(exist_ok=True)
    (out / "result.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return str(out)


def main():
    p = argparse.ArgumentParser(description="定式网络规模实验（稀疏，Phase 2）")
    p.add_argument("--corpus", default="corpus_large.json")
    p.add_argument("--n", type=int, default=8192)
    p.add_argument("--k", type=int, default=16)
    p.add_argument("--kv", type=int, default=2000)
    p.add_argument("--split", type=float, default=0.8)
    p.add_argument("--stdp-pre", type=float, default=0.5)
    p.add_argument("--wmax", type=float, default=16.0)
    p.add_argument("--delta-off", type=float, default=0.05, dest="delta_off")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    r = run_sparse_language_experiment(args)
    print_scale_report(r)
    path = save_scale_run(r, args)
    print(f"留档：{path}")


if __name__ == "__main__":
    main()
