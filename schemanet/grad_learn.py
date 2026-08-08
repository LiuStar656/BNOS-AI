# -*- coding: utf-8 -*-
"""Phase 4a 梯度可行性实验：定式网络获得参数级梯度学习能力的最小验证。

前向（可微读出）：
    logits[w_t] = Σ_pos ctx_wgt[pos] × score(w_t, prefix[last-pos])
    score(w, src) = Σ_{j∈pats[w]} W[j,0,src] / k
    probs = softmax(logits/T) → 交叉熵

梯度天然稀疏：
    score 只在已有连接处非零 → ∂L/∂W 只在 W 非零位置有值 → 稀疏性自动保持
    （新增连接永远无梯度，W 结构不动 = 定式动力学保留）

两个实验：
  实验 1（精调验证）：corpus.json（100 句，n=2048）——梯度微调 W 非零 + ctx_wgt
  实验 2（能力验证）：corpus_large.json（1814 句，n=8192）——只训 ctx_wgt（W 冻结），
      对标 Phase 2 的 trace 失败场景（均匀分布平局最大化）：梯度学到的上下文权重
      能否超过固定 trace 权重（0.280）甚至 wsum（0.384）

用法：
    python grad_learn.py --exp1          # 实验 1
    python grad_learn.py --exp2          # 实验 2
"""

import argparse
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

from schema_net import _word_pattern, _learn_sentence, _BigramModel, _TrigramModel, _evaluate_ngram
from sparse_net import (SparseSchemaNet, _pats_matrix, _out_edges_accum, outsum_sparse,
                        evaluate_schemanet_sparse, predict_cands_wsum_sparse)

MAXLEN = 5  # 上下文最大长度（pos 0 = 末词）


# ════════════════════════════════════════════════════════════════
#  数据与位置构建
# ════════════════════════════════════════════════════════════════

def load_and_vocab(corpus_path, kv):
    import jieba
    corpus = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
    tokenized = [jieba.lcut(s) for s in corpus]
    freq = Counter(w for toks in tokenized for w in toks)
    vocab = [w for w, _ in freq.most_common(kv)]
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    return corpus, tokenized, freq, vocab, vocab_idx


def build_positions(tokenized, vocab_idx):
    """所有 (prefix_idxs, target_idx)；只保留前缀词在词表内的位置。"""
    pos = []
    for toks in tokenized:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(1, len(ids)):
            pos.append((ids[:t], ids[t]))
    return pos


# ════════════════════════════════════════════════════════════════
#  前向 / 反向（纯 numpy，稀疏梯度）
# ════════════════════════════════════════════════════════════════

def score_vec(ng, src_idxs, pats_mat):
    """V 维：score[w] = Σ_{j∈pats[w]} W[j,0,src]/k（src 为词模式的神经元集合）。"""
    acc = _out_edges_accum(ng, src_idxs, 0)
    return acc[pats_mat].sum(axis=1) / pats_mat.shape[1]


def logits_of(ng, ctx_wgt, prefix_ids, vocab, pats, pats_mat):
    """前向 logits（V 维）：Σ_pos ctx_wgt[pos] × score(w, prefix[last-pos])。"""
    V = pats_mat.shape[0]
    logits = np.zeros(V)
    for pos, wid in enumerate(reversed(prefix_ids)):
        if pos >= MAXLEN:
            break
        logits += ctx_wgt[pos] * score_vec(ng, pats[vocab[wid]], pats_mat)
    return logits


def grads_of(ng, ctx_wgt, prefix_ids, target, vocab, pats, pats_mat, T=1.0):
    """反向：返回 (d_ctx_wgt[L], dW 稀疏累积 dict) 与 logits 统计。
    dW: {i: {j: g}}——i=源神经元、j=目标神经元（已有连接才更新，保持稀疏）。"""
    V = pats_mat.shape[0]
    logits = logits_of(ng, ctx_wgt, prefix_ids, vocab, pats, pats_mat)
    ex = np.exp((logits - logits.max()) / T)
    probs = ex / ex.sum()
    dL = probs.copy()
    dL[target] -= 1.0  # V 维 CE 梯度

    d_wgt = np.zeros(MAXLEN)
    dW = {}
    # 神经元聚合：g_n[j] = Σ_{w: j∈pats[w]} dL[w] / k
    g_n = np.zeros(ng.n)
    np.add.at(g_n, pats_mat.ravel(), np.repeat(dL, pats_mat.shape[1]))
    g_n /= pats_mat.shape[1]

    for pos, wid in enumerate(reversed(prefix_ids)):
        if pos >= MAXLEN:
            break
        s = score_vec(ng, pats[vocab[wid]], pats_mat)
        d_wgt[pos] += float(s @ dL)
        cw = ctx_wgt[pos]
        # dW 对 src 词模式的每个神经元 i：W[i → j] 梯度 = cw × g_n[j]（j 只在已有连接更新）
        for i in pats[vocab[wid]]:
            row = ng.W_out[i][0]
            if not row:
                continue
            gi = dW.setdefault(i, {})
            for j, w in row.items():
                g = cw * g_n[j]
                if g != 0.0:
                    gi[j] = gi.get(j, 0.0) + g
    return d_wgt, dW, probs


def apply_grads(ng, ctx_wgt, d_wgt, dW, lr, freeze_w):
    ctx_wgt -= lr * d_wgt / (1 if freeze_w else 1)  # ctx_wgt 总是训练
    if not freeze_w:
        for i, gi in dW.items():
            row = ng.W_out[i][0]
            for j, g in gi.items():
                if j in row:
                    row[j] = min(max(row[j] - lr * g, 0.0), ng.w_max)


# ════════════════════════════════════════════════════════════════
#  评估（与 wsum/trace 同口径 top-1）
# ════════════════════════════════════════════════════════════════

def evaluate_grad(ng, ctx_wgt, toks_list, vocab_idx, vocab, pats, pats_mat,
                  n_samples=8):
    hits = total = 0
    samples = []
    for toks in toks_list:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(1, len(ids)):
            logits = logits_of(ng, ctx_wgt, ids[:t], vocab, pats, pats_mat)
            logits = logits.copy()
            logits[logits <= 0] = -np.inf  # 无转移信号 → 不参与候选（与 wsum 的 scores>0 过滤同口径）
            for wid in ids[:t]:  # 排除前缀内已现词（与 wsum/trace 同口径）
                logits[wid] = -np.inf
            cand_idx = int(np.argmax(logits))
            pred = vocab[cand_idx]
            total += 1
            if pred == toks[t]:
                hits += 1
            elif len(samples) < n_samples:
                order = np.argsort(-logits)
                top3 = [vocab[i] for i in order[:3]]
                samples.append({"ctx": "".join(toks[:t]), "truth": toks[t],
                                "pred": pred, "top3": top3})
    return (hits / total if total else 0.0), hits, total, samples


def softmax(x):
    ex = np.exp(x - x.max())
    return ex / ex.sum()


def train_fast(ctx_wgt, positions, S, lr, epochs, seed):
    """快速路径：冻结 W 时预计算 score 矩阵 S[V,V]，只训练上下文权重。
    ctx_wgt 为自由参数（非 softmax：softmax 梯度与 wgt 成正比 → 尾巴权重收敛
    不到严格 0，微小扰动在 score 近似平局处翻转决策——exp2 踩坑 0.0001 尾巴）。
    每步：wgt=ctx_wgt[:Ln]/sum（单纯形投影，语义=位置信任分布）→ logits →
    CE 梯度 d_wgt 直接更新 ctx_wgt → clip 非负 + 归一化。
    梯度裁剪（norm≤1）兜底防 logits 尺度漂移正反馈。"""
    t0 = time.time()
    for ep in range(epochs):
        rng = np.random.default_rng(seed + ep)
        perm = rng.permutation(len(positions))
        for idx in perm:
            pidxs, target = positions[idx]
            Ln = min(MAXLEN, len(pidxs))
            cw = ctx_wgt[:Ln]
            s = cw.sum()
            wgt = cw / s if s > 0 else cw
            logits = S[:, pidxs[-Ln:]] @ wgt
            ex = np.exp(logits - logits.max())
            probs = ex / ex.sum()
            dL = probs.copy()
            dL[target] -= 1.0
            d_wgt = np.array([float(S[:, wid] @ dL)
                              for wid in reversed(pidxs[-Ln:])])
            nrm = float(np.linalg.norm(d_wgt))
            if nrm > 1.0:
                d_wgt = d_wgt / nrm
            cw -= lr * d_wgt
            np.clip(cw, 0.0, None, out=cw)  # 就地写回（cw 是 ctx_wgt[:Ln] 视图）
            s = cw.sum()
            if s > 0:
                cw /= s
    return round(time.time() - t0, 1)


def build_score_matrix(ng, pats, vocab, pats_mat):
    """S[V, V]：S[w][src] = score(w, src) = Σ_{j∈pats[w]} W[j,0,src]/k。"""
    V = pats_mat.shape[0]
    S = np.zeros((V, V))
    for si, w in enumerate(vocab):
        acc = _out_edges_accum(ng, pats[w], 0)
        S[:, si] = acc[pats_mat].sum(axis=1) / pats_mat.shape[1]
    return S


def logits_from_S(S, ctx_wgt, prefix_ids):
    """ctx_wgt 为自由参数（信任分布，和为 1）；wgt=ctx_wgt[:Ln]/sum 后加权。
    位置语义：pos0 = 末词（列反转对齐，否则 ctx_wgt[0] 错乘前缀首词）。"""
    Ln = min(MAXLEN, len(prefix_ids))
    cw = ctx_wgt[:Ln]
    s = cw.sum()
    wgt = cw / s if s > 0 else cw
    cols = prefix_ids[-Ln:][::-1]  # 末词在列首
    return S[:, cols] @ wgt


def evaluate_grad_fast(S, ctx_wgt, toks_list, vocab_idx, vocab, n_samples=8):
    hits = total = 0
    samples = []
    for toks in toks_list:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(1, len(ids)):
            logits = logits_from_S(S, ctx_wgt, ids[:t]).copy()
            logits[logits <= 0] = -np.inf  # 无转移信号 → 不参与候选（与 wsum 的 scores>0 过滤同口径）
            for wid in ids[:t]:
                logits[wid] = -np.inf
            cand_idx = int(np.argmax(logits))
            pred = vocab[cand_idx]
            total += 1
            if pred == toks[t]:
                hits += 1
            elif len(samples) < n_samples:
                order = np.argsort(-logits)
                top3 = [vocab[i] for i in order[:3]]
                samples.append({"ctx": "".join(toks[:t]), "truth": toks[t],
                                "pred": pred, "top3": top3})
    return (hits / total if total else 0.0), hits, total, samples


# ════════════════════════════════════════════════════════════════
#  实验主流程
# ════════════════════════════════════════════════════════════════

def run_experiment(args, corpus_path, n, k, kv, split, seed, freeze_w, epochs,
                   lr, tag, delta_off=0.05):
    t_start = time.time()
    corpus, tokenized, freq, vocab, vocab_idx = load_and_vocab(corpus_path, kv)
    rng_split = np.random.default_rng(seed + 9000)
    perm = rng_split.permutation(len(tokenized))
    n_train = int(len(tokenized) * split)
    train_toks = [tokenized[i] for i in perm[:n_train]]
    test_toks = [tokenized[i] for i in perm[n_train:]]
    train_pos = build_positions(train_toks, vocab_idx)
    test_pos = build_positions(test_toks, vocab_idx)

    pats = {w: _word_pattern(n, k, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)

    # ── Hebbian 预训练 ──
    ng = SparseSchemaNet(n=n, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=16.0, wta_k=k, noise_p=0.06, noise_amp=0.5,
                         weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                         refractory=1, rng=np.random.default_rng(seed + 5000))
    for toks in train_toks:
        _learn_sentence(ng, toks, pats, slot=0)
    ng.learn_gate = False
    nnz_before = sum(len(row) for rows in ng.W_out for row in rows)

    # ── 基线（纯 Hebbian 读出）──
    outsum = outsum_sparse(ng, pats, vocab, slot=0)
    wsum_tr = evaluate_schemanet_sparse(ng, train_toks, pats, vocab, pats_mat,
                                        readout="wsum")
    wsum_te = evaluate_schemanet_sparse(ng, test_toks, pats, vocab, pats_mat,
                                        readout="wsum")
    tr_tr = evaluate_schemanet_sparse(ng, train_toks, pats, vocab, pats_mat,
                                      readout="trace", norm_base=outsum,
                                      delta_off=delta_off)
    tr_te = evaluate_schemanet_sparse(ng, test_toks, pats, vocab, pats_mat,
                                      readout="trace", norm_base=outsum,
                                      delta_off=delta_off)

    # ── 梯度训练 ──
    t0 = time.time()
    if freeze_w:
        # 快速路径（exp2）：冻结 W → 预计算 S[V,V] → 温度归一化（÷max，argmax
        # 不变、评估口径不受影响，只稳定训练动力）→ 只训 ctx_wgt（自由参数，
        # clip 非负 + 归一化 → 信任分布）
        S = build_score_matrix(ng, pats, vocab, pats_mat)
        s_max = float(S.max())
        S_norm = S / s_max if s_max > 0 else S
        # 初值 = 信任末词（数据支持才拉起远端权重）：uniform 语料（Phase 2 已知
        # trace 最不利场景）下远端无统计信息 → 梯度保持末词独裁 = wsum 水平，
        # 直接修正 trace 过度信任远端的缺陷；有偏语料下远端权重会被梯度拉起。
        ctx_wgt = np.array([1.0] + [0.0] * (MAXLEN - 1))
        train_fast(ctx_wgt, train_pos, S_norm, lr, epochs, seed)
        grad_tr = evaluate_grad_fast(S_norm, ctx_wgt, train_toks, vocab_idx, vocab)
        grad_te = evaluate_grad_fast(S_norm, ctx_wgt, test_toks, vocab_idx, vocab)
        s = ctx_wgt.sum()
        if s > 0:
            ctx_wgt = ctx_wgt / s
    else:
        ctx_wgt = np.array([1.0] + [0.05 * 0.5 ** i for i in range(1, MAXLEN)],
                           dtype=float)  # trace 等效初值
        for ep in range(epochs):
            rng = np.random.default_rng(seed + ep)
            perm2 = rng.permutation(len(train_pos))
            for idx in perm2:
                pidxs, target = train_pos[idx]
                d_wgt, dW, _ = grads_of(ng, ctx_wgt, pidxs, target, vocab, pats, pats_mat)
                apply_grads(ng, ctx_wgt, d_wgt, dW, lr, freeze_w)
        ctx_wgt = np.clip(ctx_wgt, 0.0, None)
        grad_tr = evaluate_grad(ng, ctx_wgt, train_toks, vocab_idx, vocab, pats, pats_mat)
        grad_te = evaluate_grad(ng, ctx_wgt, test_toks, vocab_idx, vocab, pats, pats_mat)
    t_grad = time.time() - t0

    nnz_after = sum(len(row) for rows in ng.W_out for row in rows)

    return {
        "tag": tag, "corpus": corpus_path, "n": n, "k": k,
        "vocab_size": len(vocab),
        "n_train": len(train_toks), "n_test": len(test_toks),
        "n_pos_train": len(train_pos), "n_pos_test": len(test_pos),
        "freeze_w": freeze_w, "epochs": epochs, "lr": lr, "delta_off": delta_off,
        "baseline": {
            "wsum": {"train": wsum_tr[0], "test": wsum_te[0]},
            "trace": {"train": tr_tr[0], "test": tr_te[0]},
        },
        "grad": {"train": grad_tr[0], "test": grad_te[0]},
        "ctx_wgt": [round(float(x), 4) for x in ctx_wgt],
        "sparsity": {"nnz_before": nnz_before, "nnz_after": nnz_after,
                     "structure_unchanged": nnz_before == nnz_after},
        "timing": {"grad_train_sec": round(t_grad, 1),
                   "total_sec": round(time.time() - t_start, 1)},
        "samples": {"train": grad_tr[3][:3], "test": grad_te[3][:3]},
    }


def print_report(r):
    print("=" * 64)
    print(f"Phase 4a 梯度可行性 [{r['tag']}]  n={r['n']} k={r['k']} 词表={r['vocab_size']} "
          f"freeze_w={r['freeze_w']}")
    print(f"语料 {r['corpus']}：训练 {r['n_train']} 句（{r['n_pos_train']} 位置）/ "
          f"留出 {r['n_test']} 句（{r['n_pos_test']} 位置）")
    print("-" * 64)
    b = r["baseline"]
    g = r["grad"]
    print(f"{'模型':<22}{'训练集':<10}{'留出':<10}")
    print(f"{'Hebbian wsum（纯读）':<22}{b['wsum']['train']:<10.4f}{b['wsum']['test']:<10.4f}")
    print(f"{'Hebbian trace（固定权重）':<22}{b['trace']['train']:<10.4f}{b['trace']['test']:<10.4f}")
    print(f"{'梯度读出（Phase 4a）':<22}{g['train']:<10.4f}{g['test']:<10.4f}")
    print("-" * 64)
    print(f"学到的上下文信任分布（末词→远端）: {r['ctx_wgt']}")
    print(f"W 结构不变（非零数 {r['sparsity']['nnz_before']} → {r['sparsity']['nnz_after']}）: "
          f"{'✓' if r['sparsity']['structure_unchanged'] else '✗'}")
    print(f"梯度训练耗时 {r['timing']['grad_train_sec']}s / 总 {r['timing']['total_sec']}s")
    print("=" * 64)


def save_run(r):
    runs = Path(__file__).parent / "runs"
    runs.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = runs / f"{ts}"
    out.mkdir(exist_ok=True)
    (out / "result.json").write_text(json.dumps(r, ensure_ascii=False, indent=2,
                                                 default=str), encoding="utf-8")
    return str(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--exp1", action="store_true", help="实验 1：corpus.json n=2048 微调 W")
    p.add_argument("--exp2", action="store_true", help="实验 2：冻结 W 只训 ctx_wgt")
    p.add_argument("--corpus", type=str, default=None,
                   help="exp2 语料（默认 data/corpus_large.json；用 data/corpus_ctx.json 验证二阶依赖）")
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--lr", type=float, default=0.5)
    args = p.parse_args()

    if args.exp1:
        r = run_experiment(args, "data/corpus.json", 2048, 8, 300, 0.8, 42,
                           freeze_w=False, epochs=args.epochs, lr=args.lr,
                           tag="exp1 精调验证")
    elif args.exp2:
        corpus_path = args.corpus or "data/corpus_large.json"
        r = run_experiment(args, corpus_path, 8192, 16, 2000, 0.8, 42,
                           freeze_w=True, epochs=args.epochs, lr=args.lr,
                           tag=f"exp2 {corpus_path}", delta_off=0.02)
    else:
        p.error("需指定 --exp1 或 --exp2")
    print_report(r)
    path = save_run(r)
    print(f"留档：{path}")


if __name__ == "__main__":
    main()
