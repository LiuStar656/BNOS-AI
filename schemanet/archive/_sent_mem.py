# -*- coding: utf-8 -*-
"""句记忆检索注意力——概念验证（回应"注意力不应该是一整个句子吗"）。

核心：定式网络训练时句子被压成词→词转移（W），句子单元被抹平。本脚本给网络
补"句记忆"：
  1. 构建：对训练子集逐句重放，逐位置取神经签名（pre_trace 的 top-k 神经元 =
     该前缀激活的神经痕迹），签名 → 续词，写入倒排索引（neuron → 记忆单元）。
  2. 检索：推断时前缀重放取签名 → 倒排收集候选单元 → 按神经元重叠数加权 →
     续词投票。注意力作用在"一整句记忆"上，而非散词。
  3. 检验：位置分层 top-1 + 同末词命中率（vs wsum）+ 生成对比（是否终于连贯）。

用法：python _sent_mem.py [--model runs/xxx/net_clean.npz] [--mem-sub 20000] [--k 25] [--m 5]
"""
import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from schema_net import _word_pattern, build_pulse
from sparse_net import _pats_matrix, load_net
from grad_readout import GradReadout
from _accept_scale20w import (CORPUS, EVAL_SUB_TEST, GRP_TAGS, K, MAXLEN, N,
                              SEED, gname)


# ── 神经签名提取（与 _trace_logits 相同重放）─────────────────────────

class SigExtractor:
    """顺序重放网络，逐步取当前神经签名（pre_trace top-k 神经元 id）。"""

    def __init__(self, ng, pats):
        self.ng = ng
        self.pats = pats
        self.reset()

    def reset(self):
        self.ng.v = np.zeros((self.ng.n, self.ng.slots))
        self.ng.spikes = np.zeros(self.ng.n)
        self.ng.pre_trace = np.zeros(self.ng.n)
        self.ng.refractory_left = np.zeros(self.ng.n, dtype=int)
        self.ng.last_k_star = np.zeros(self.ng.n, dtype=int)

    def step(self, word):
        """推进一个词，返回该步后的签名（top-k 神经元 id，按痕迹降序）。"""
        pw = self.pats[word]
        self.ng.v = np.zeros((self.ng.n, self.ng.slots))
        self.ng.step(build_pulse(self.ng.n, pw), slot=0)
        self.ng.v = np.zeros((self.ng.n, self.ng.slots))
        self.ng.step(np.zeros(self.ng.n), slot=0)
        return self.ng.pre_trace


def topk_ids(pre_trace, k):
    """pre_trace 中最大的 k 个神经元 id（按痕迹降序；过滤零痕迹）。"""
    n = len(pre_trace)
    kk = min(k, n, int(np.count_nonzero(pre_trace)))
    if kk == 0:
        return np.empty(0, dtype=np.int64)
    idx = np.argpartition(pre_trace, -kk)[-kk:]
    return idx[np.argsort(-pre_trace[idx])]


# ── 句记忆构建（倒排索引）───────────────────────────────────────────

def build_memory(ng, pats, vocab, train_toks, k, log_every=20000):
    """对训练子集逐句重放：每位置存 (签名 top-k 神经元, 续词)。
    返回 (inv, nexts, n_units)：inv[neuron]=np.array(unit_id)（检索向量化）；
    nexts[unit_id]=续词 id。"""
    vtab = {w: i for i, w in enumerate(vocab)}
    inv = defaultdict(list)
    nexts = []
    ex = SigExtractor(ng, pats)
    n_units = 0
    t0 = time.time()
    for si, toks in enumerate(train_toks):
        ids = [vtab[w] for w in toks if w in vtab]
        if not ids:
            continue
        ex.reset()
        for t in range(len(ids)):
            sig = topk_ids(ex.step(vocab[ids[t]]), k)
            if t + 1 < len(ids):
                unit = len(nexts)
                nexts.append(ids[t + 1])
                for neu in sig:
                    inv[neu].append(unit)
                n_units += 1
        if (si + 1) % log_every == 0:
            print(f"  句 {si+1}/{len(train_toks)}  单元 {n_units}  "
                  f"({time.time()-t0:.0f}s)", flush=True)
    inv = {neu: np.array(units, dtype=np.int64)
           for neu, units in inv.items()}
    return inv, np.array(nexts, dtype=np.int64), n_units


# ── 检索注意力：前缀签名 → 倒排 → 续词投票 ─────────────────────────

def retrieve_next(ex, inv, nexts, vocab, word, k, m):
    """推进词 word 后，用当前签名检索记忆，返回 (续词 top-1, 投票分布)。
    numpy 向量化：倒排并集 → np.unique 计数 → top-m 单元 → 续词加权。"""
    sig = topk_ids(ex.step(word), k)
    if len(sig) == 0:
        return None, {}
    parts = [inv[int(neu)] for neu in sig if int(neu) in inv]
    if not parts:
        return None, {}
    allu = np.concatenate(parts)
    uniq, counts = np.unique(allu, return_counts=True)
    if m >= len(uniq):
        top = np.arange(len(uniq))[::-1]
    else:
        top = np.argpartition(counts, -m)[-m:]
    top = top[np.argsort(-counts[top])]
    wvote = Counter()
    for ui in top[:m]:
        wvote[vocab[int(nexts[int(uniq[ui])])]] += int(counts[ui])
    return wvote.most_common(1)[0][0], dict(wvote)


def eval_sent_mem(ng, pats, vocab, inv, nexts, toks_list, k, m, tag="句记忆"):
    """位置分层 top-1（同 GRPS 口径）。
    对齐：看到 toks_f[:t+1] 后的签名预测 toks_f[t+1]（t 从 0 起）。"""
    ex = SigExtractor(ng, pats)
    vtab = {w: i for i, w in enumerate(vocab)}
    hits, total = Counter(), Counter()
    for toks in toks_list:
        tf = [w for w in toks if w in vtab]
        if not tf:
            continue
        ex.reset()
        for t in range(len(tf) - 1):
            pred, _ = retrieve_next(ex, inv, nexts, vocab, tf[t], k, m)
            used = set(tf[:t + 1])
            g = gname(t + 1)
            total[g] += 1
            if pred is not None and pred not in used and pred == tf[t + 1]:
                hits[g] += 1
    return {GRP_TAGS[i]: (hits[i] / total[i] if total[i] else None)
            for i in range(len(GRP_TAGS))}, int(sum(total.values()))


def same_tail_rate(ng, pats, vocab, inv, nexts, groups, k, m):
    """同末词命中率（vs wsum 基线）。groups: [(last, [(pids, tgt)])]。"""
    ex = SigExtractor(ng, pats)
    vtab = {w: i for i, w in enumerate(vocab)}
    h = n = 0
    for last, lst in groups:
        for pids, tgt in lst:
            ex.reset()
            pred = None
            for wid in pids:
                pred, _ = retrieve_next(ex, inv, nexts, vocab, vocab[wid], k, m)
            n += 1
            if pred is not None and pred not in {vocab[i] for i in pids} \
                    and pred == vocab[tgt]:
                h += 1
    return h, n


def gen_continuation(ng, pats, vocab, inv, nexts, prefix, k, m, n_words):
    """贪心续写 n_words 词（句记忆检索）。"""
    ex = SigExtractor(ng, pats)
    cur = list(prefix)
    used = set(cur)
    out = []
    for w in cur:
        retrieve_next(ex, inv, nexts, vocab, w, k, m)
    for _ in range(n_words):
        w = cur[-1]
        pred, _ = retrieve_next(ex, inv, nexts, vocab, w, k, m)
        if pred is None or pred in used:
            break
        out.append(pred)
        used.add(pred)
        cur.append(pred)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="runs/20260809_160027/net_clean.npz")
    ap.add_argument("--mem-sub", type=int, default=20000, help="句记忆训练子集句数")
    ap.add_argument("--k", type=int, default=25, help="签名神经元数")
    ap.add_argument("--m", type=int, default=5, help="top 记忆单元数")
    ap.add_argument("--eval-n", type=int, default=500,
                    help="位置分层评估句数（网络重放慢，控制规模）")
    ap.add_argument("--st-n", type=int, default=2500,
                    help="同末词评估样本数上限（控制规模）")
    args = ap.parse_args()

    ng, vocab, ctx = load_net(args.model, seed=42, return_ctx=True)
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    print(f"模型: {args.model}  N={ng.n} 词汇 {len(vocab)}", flush=True)

    tokenized = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
    rng = np.random.default_rng(SEED + 9000)
    perm = rng.permutation(len(tokenized))
    n_train = int(len(tokenized) * 0.8)
    train_toks = [tokenized[i] for i in perm[:args.mem_sub]]
    test_toks = [tokenized[i] for i in perm[n_train:]]
    ev_te = [test_toks[i] for i in
             rng.choice(len(test_toks), min(EVAL_SUB_TEST, len(test_toks)),
                        replace=False)]

    # ── 构建句记忆 ──
    print(f"构建句记忆（{args.mem_sub} 句，签名 k={args.k}）...", flush=True)
    inv, nexts, n_units = build_memory(ng, pats, vocab, train_toks, args.k)
    print(f"记忆单元 {n_units}（≈{args.mem_sub}句×位置），倒排神经元 {len(inv)}",
          flush=True)

    # ── 位置分层（评估子集，--eval-n 控制句数）──
    print("\n── 位置分层（评估子集）──", flush=True)
    ev_eval = ev_te[:args.eval_n]
    vtab = {w: i for i, w in enumerate(vocab)}
    # wsum 参考
    S = GradReadout(ng, pats, vocab, _pats_matrix(pats, vocab),
                    maxlen=MAXLEN).build_score_matrix()
    Sn = S / S.max() if S.max() > 0 else S
    wh, wt = Counter(), Counter()
    for toks in ev_eval:
        tf = [w for w in toks if w in vtab]
        if not tf:
            continue
        for t in range(1, len(tf)):
            lg = Sn[:, vtab[tf[t - 1]]].copy()
            used = set(vtab[w] for w in tf[:t])
            order = np.argsort(-lg)
            cand = next((wi for wi in order if lg[wi] > 0 and wi not in used),
                        None)
            g = gname(t)
            wt[g] += 1
            if cand is not None and vocab[cand] == tf[t]:
                wh[g] += 1
    w_tab = {GRP_TAGS[i]: (wh[i] / wt[i] if wt[i] else None)
             for i in range(len(GRP_TAGS))}
    w_avg = sum(v for v in w_tab.values() if v is not None) / \
        sum(1 for v in w_tab.values() if v is not None)
    m_tab, m_n = eval_sent_mem(ng, pats, vocab, inv, nexts, ev_eval, args.k,
                               args.m)
    m_avg = sum(v for v in m_tab.values() if v is not None) / \
        sum(1 for v in m_tab.values() if v is not None)
    print(f"{'wsum':>8s}  " + "  ".join(f"{w_tab[g]:6.4f}" for g in GRP_TAGS)
          + f"   {w_avg:.4f}", flush=True)
    print(f"{'句记忆':>8s}  "
          + "  ".join(f"{m_tab[g]:6.4f}" if m_tab[g] is not None else '  --  '
                      for g in GRP_TAGS) + f"   {m_avg:.4f}", flush=True)

    # ── 同末词命中率 ──
    print("\n── 同末词命中率（> wsum 才证明用上下文提升正确性）──", flush=True)
    g_by_last = defaultdict(list)
    for toks in ev_te:
        tf = [w for w in toks if w in vtab]
        if not tf:
            continue
        for t in range(2, len(tf)):
            g_by_last[vtab[tf[t - 1]]].append((tuple(vtab[w] for w in tf[:t]),
                                               vtab[tf[t]]))
    groups = []
    for last, lst in g_by_last.items():
        if 3 <= len(lst) <= 20 and len({t for _, t in lst}) >= 2:
            groups.append((last, lst))
    groups.sort(key=lambda x: -len(x[1]))
    # 控制同末词评估规模（网络重放慢）
    acc = 0
    groups_cut = []
    for g in groups:
        acc += len(g[1])
        if acc > args.st_n:
            break
        groups_cut.append(g)
    groups = groups_cut
    n_groups = len(groups)
    n_samp = sum(len(lst) for _, lst in groups)
    print(f"组数 {n_groups} / 样本 {n_samp}", flush=True)

    def w_pred(ids):
        lg = Sn[:, ids[-1]].copy()
        used = set(ids)
        order = np.argsort(-lg)
        wi = next((w for w in order if w > 0 and lg[w] > 0 and w not in used),
                  None)
        return vocab[wi] if wi is not None else None

    whh = wnn = 0
    for _, lst in groups:
        for pids, tgt in lst:
            wnn += 1
            if w_pred(pids) == vocab[tgt]:
                whh += 1
    wrate = whh / wnn
    h, n = same_tail_rate(ng, pats, vocab, inv, nexts, groups, args.k,
                          args.m)
    rate = h / n
    p = (rate * n + wrate * wnn) / (n + wnn)
    se = (p * (1 - p) * (1 / n + 1 / wnn)) ** 0.5
    z = (rate - wrate) / se if se > 0 else None
    print(f"wsum:  {wrate:.4f} ({whh}/{wnn})", flush=True)
    print(f"句记忆: {rate:.4f} ({h}/{n})   vs wsum {rate-wrate:+.4f}  "
          f"z={z if z is not None else 0:.2f}", flush=True)

    # ── 生成对比（同末词对，直接看连贯性）──
    print("\n── 生成对比（贪心续写 8 词）──", flush=True)
    gen_pairs = []
    unk = "<UNK>"
    for last, lst in groups[:3]:
        a = [vocab[i] for i in lst[0][0]]
        # 找另一个同末词不同前缀
        b = None
        for pids, _ in lst[1:]:
            cand = [vocab[i] for i in pids]
            if cand != a and unk not in cand and unk not in a:
                b = cand
                break
        if b is None:
            continue
        ga = gen_continuation(ng, pats, vocab, inv, nexts, a, args.k, args.m, 8)
        gb = gen_continuation(ng, pats, vocab, inv, nexts, b, args.k, args.m, 8)
        print(f"\n同末词『{last}』")
        print(f"  A: {' '.join(a)} → {' '.join(ga)}", flush=True)
        print(f"  B: {' '.join(b)} → {' '.join(gb)}", flush=True)
        gen_pairs.append({"last": last, "A": a, "B": b, "genA": ga, "genB": gb})

    # ── 留档 ──
    out_dir = Path("runs") / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "tag": "句记忆检索注意力概念验证",
        "model": args.model, "mem_sub": args.mem_sub, "k": args.k, "m": args.m,
        "mem_units": n_units, "inv_neurons": len(inv),
        "top1_layer": {"wsum": {g: round(v, 4) if v is not None else None
                                for g, v in w_tab.items()},
                       "sent_mem": {g: round(v, 4) if v is not None else None
                                    for g, v in m_tab.items()}},
        "same_tail": {"wsum": {"rate": round(wrate, 4), "hits": whh,
                               "n": wnn},
                      "sent_mem": {"rate": round(rate, 4), "hits": h, "n": n,
                                   "diff": round(rate - wrate, 4),
                                   "z": round(z, 2) if z is not None else None}},
        "gens": gen_pairs,
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {out_dir}/result.json", flush=True)


if __name__ == "__main__":
    main()
