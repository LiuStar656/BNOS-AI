# -*- coding: utf-8 -*-
"""整句涟漪——句级复述/唤起（回应"整个句子进入网络产生的涟漪"）。

哲学：不把句子稀碎成"前缀→下一个词"的概率，而是整句进网络泛起一片
涟漪（整句激活痕迹的累积），句记忆存的是"整句涟漪"（一句一条）。
推断：半句涟漪 → 唤起最像的一整句 → 续写 = 把那一整句的后续"说完整"
（模式完成，海马体式唤起）。

对照：_sent_mem.py（稀碎版，逐位置签名-续词对）——本脚本是整句单元。

用法：python _sent_ripple.py [--model runs/xxx/net_clean.npz] [--mem-sub 10000]
"""
import argparse
import json
import pickle
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from schema_net import _word_pattern
from sparse_net import load_net
from _accept_scale20w import CORPUS, EVAL_SUB_TEST, GRP_TAGS, K, N, SEED, gname
from _sent_mem import SigExtractor, topk_ids


def ripple_sig(ex, toks, k):
    """整句涟漪：逐词推进，累积 Σ pre_trace → top-k 签名（整句激活痕迹）。"""
    acc = np.zeros(ex.ng.n)
    for w in toks:
        acc += ex.step(w)
    return topk_ids(acc, k)


def build_memory(ng, pats, vocab, train_toks, k, log_every=2000):
    """每句一个涟漪签名 + 整句词序列。返回 (sigs, toks_list, inv)。"""
    vtab = {w: i for i, w in enumerate(vocab)}
    ex = SigExtractor(ng, pats)
    sigs, toks_list = [], []
    inv = defaultdict(list)
    t0 = time.time()
    for si, toks in enumerate(train_toks):
        tf = [w for w in toks if w in vtab]
        if not tf:
            continue
        ex.reset()
        sig = ripple_sig(ex, tf, k)
        if len(sig) == 0:
            continue
        j = len(sigs)
        sigs.append(sig)
        toks_list.append(tf)
        for neu in sig:
            inv[int(neu)].append(j)
        if (si + 1) % log_every == 0:
            print(f"  句 {si+1}/{len(train_toks)}  记忆 {len(sigs)}  "
                  f"({time.time()-t0:.0f}s)", flush=True)
    return sigs, toks_list, inv


def retrieve(inv, sig, m):
    """涟漪签名 → 倒排 → 候选句重叠计数 → top-m (句id, 重叠数)。"""
    votes = Counter()
    for neu in sig:
        for j in inv.get(int(neu), ()):
            votes[j] += 1
    return votes.most_common(m)


def align_next(mem_toks, prefix):
    """对齐：prefix 的最长后缀在记忆句中的最后出现位置，返回其后一词。
    None=该记忆句不包含 prefix 的延续（弃权）。"""
    maxL = min(len(prefix), len(mem_toks))
    for L in range(maxL, 0, -1):
        tail = prefix[-L:]
        for pos in range(len(mem_toks) - L, -1, -1):
            if mem_toks[pos:pos + L] == tail:
                if pos + L < len(mem_toks):
                    return mem_toks[pos + L]
                return None
    return None


def eval_layer(ng, pats, vocab, inv, mem_toks, toks_list, k, m, tag):
    """位置分层：句内顺序推进，位置 t 的累积涟漪 → 唤起 → 对齐续写。"""
    vtab = {w: i for i, w in enumerate(vocab)}
    ex = SigExtractor(ng, pats)
    hits, total = Counter(), Counter()
    for toks in toks_list:
        tf = [w for w in toks if w in vtab]
        if not tf:
            continue
        ex.reset()
        acc = np.zeros(ng.n)
        for t in range(len(tf) - 1):
            acc += ex.step(tf[t])
            if t == 0:
                continue
            sig = topk_ids(acc, k)
            wvote = Counter()
            for j, sc in retrieve(inv, sig, m):
                nxt = align_next(mem_toks[j], tf[:t + 1])
                if nxt is not None:
                    wvote[nxt] += sc
            pred = wvote.most_common(1)
            g = gname(t + 1)
            total[g] += 1
            if pred and pred[0][0] not in tf[:t + 1] and pred[0][0] == tf[t + 1]:
                hits[g] += 1
    return {GRP_TAGS[i]: (hits[i] / total[i] if total[i] else None)
            for i in range(len(GRP_TAGS))}, int(sum(total.values()))


def complete_sentence(ex, inv, mem_toks, sig, prefix, m):
    """涟漪唤起整句，返回记忆句在 prefix 后的完整后续（一次性说出）。"""
    cands = retrieve(inv, sig, m)
    for j, sc in cands:
        nxt = align_next(mem_toks[j], prefix)
        if nxt is not None:
            pos = len(mem_toks[j]) - len(mem_toks[j])  # 找对齐后起点
            # 重新定位：align_next 给的是续词，此处返回整句后续
            maxL = min(len(prefix), len(mem_toks[j]))
            for L in range(maxL, 0, -1):
                tail = prefix[-L:]
                for p in range(len(mem_toks[j]) - L, -1, -1):
                    if mem_toks[j][p:p + L] == tail:
                        return mem_toks[j][p + L:], j
    return [], None


def recall_rate(ng, pats, vocab, inv, mem_toks, sigs, k, m, n_sample):
    """训练集复述率：输入整句 → 涟漪 → top1 唤起是否是它自己（句级记忆验证）。"""
    ex = SigExtractor(ng, pats)
    vtab = {w: i for i, w in enumerate(vocab)}
    h = n = 0
    for j, toks in enumerate(mem_toks[:n_sample]):
        sig = sigs[j]
        cands = retrieve(inv, sig, m)
        if cands:
            n += 1
            if cands[0][0] == j:
                h += 1
    return h, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="runs/20260809_160027/net_clean.npz")
    ap.add_argument("--mem-sub", type=int, default=10000, help="句记忆句数")
    ap.add_argument("--k", type=int, default=25, help="签名神经元数")
    ap.add_argument("--m", type=int, default=5, help="top 记忆句数")
    ap.add_argument("--eval-n", type=int, default=500, help="评估句数")
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
    ev_eval = ev_te[:args.eval_n]

    # ── 构建整句涟漪记忆（带缓存，重跑免 8 分钟构建）──
    cache_path = Path("runs") / f"_ripple_cache_{Path(args.model).stem}_" \
        f"{args.mem_sub}_k{args.k}.pkl"
    if cache_path.exists():
        print(f"加载缓存: {cache_path}", flush=True)
        with open(cache_path, "rb") as f:
            sigs, mem_toks, inv = pickle.load(f)
    else:
        print(f"构建整句涟漪记忆（{args.mem_sub} 句）...", flush=True)
        sigs, mem_toks, inv = build_memory(ng, pats, vocab, train_toks,
                                           args.k)
        with open(cache_path, "wb") as f:
            pickle.dump((sigs, mem_toks, inv), f)
        print(f"缓存: {cache_path}", flush=True)
    print(f"记忆句 {len(sigs)}，倒排神经元 {len(inv)}", flush=True)

    # ── 训练集复述率（句级记忆验证）──
    h, n = recall_rate(ng, pats, vocab, inv, mem_toks, sigs, args.k, args.m, 300)
    print(f"\n训练集复述率（整句→涟漪→唤起自己）: {h}/{n} = "
          f"{h/n if n else 0:.3f}", flush=True)

    # ── 位置分层（测试集，泛化）──
    print("\n── 位置分层（评估子集）──", flush=True)
    vtab = {w: i for i, w in enumerate(vocab)}
    m_tab, m_n = eval_layer(ng, pats, vocab, inv, mem_toks, ev_eval, args.k,
                            args.m, "整句涟漪")
    m_avg = sum(v for v in m_tab.values() if v is not None) / \
        sum(1 for v in m_tab.values() if v is not None)
    print(f"{'涟漪':>8s}  " + "  ".join(
        f"{m_tab[g]:6.4f}" if m_tab[g] is not None else '  --  '
        for g in GRP_TAGS) + f"   {m_avg:.4f}", flush=True)

    # ── 生成对比：涟漪唤起整句，一次说出后续 ──
    print("\n── 生成对比（涟漪唤起整句的后续）──", flush=True)
    gen_pairs = []
    ex = SigExtractor(ng, pats)
    g_by_last = defaultdict(list)
    for toks in ev_te:
        tf = [w for w in toks if w in vtab]
        for t in range(2, len(tf)):
            g_by_last[vtab[tf[t - 1]]].append((tf[:t], tf[t]))
    used_groups = 0
    for last, lst in sorted(g_by_last.items(), key=lambda x: -len(x[1])):
        if len(lst) < 2 or used_groups >= 3:
            continue
        a = lst[0][0]
        b = None
        for pids, _ in lst[1:]:
            if pids != a and "<UNK>" not in a + pids:
                b = pids
                break
        if b is None:
            continue
        acc = np.zeros(ng.n)
        ex.reset()
        for w in a:
            acc += ex.step(w)
        restA, jA = complete_sentence(ex, inv, mem_toks, topk_ids(acc, args.k),
                                      a, args.m)
        acc = np.zeros(ng.n)
        ex.reset()
        for w in b:
            acc += ex.step(w)
        restB, jB = complete_sentence(ex, inv, mem_toks, topk_ids(acc, args.k),
                                      b, args.m)
        print(f"\n同末词『{last}』")
        print(f"  A: {' '.join(a)} → {' '.join(restA)}  "
              f"(唤起句#{jA}: {' '.join(mem_toks[jA][:12])}...)" if jA is not None
              else f"  A: {' '.join(a)} → (无唤起)", flush=True)
        print(f"  B: {' '.join(b)} → {' '.join(restB)}  "
              f"(唤起句#{jB}: {' '.join(mem_toks[jB][:12])}...)" if jB is not None
              else f"  B: {' '.join(b)} → (无唤起)", flush=True)
        gen_pairs.append({"last": last, "A": a, "B": b, "restA": restA,
                          "restB": restB})
        used_groups += 1

    # ── 留档 ──
    out_dir = Path("runs") / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "tag": "整句涟漪概念验证（句级复述/唤起，整句记忆单元）",
        "model": args.model, "mem_sub": args.mem_sub, "k": args.k, "m": args.m,
        "mem_sents": len(sigs), "inv_neurons": len(inv),
        "recall_rate": {"hits": h, "n": n,
                        "rate": round(h / n, 4) if n else None},
        "top1_layer": {g: (round(m_tab[g], 4) if m_tab[g] is not None else None)
                       for g in GRP_TAGS},
        "avg": round(m_avg, 4), "eval_n": len(ev_eval),
        "gens": gen_pairs,
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {out_dir}/result.json", flush=True)


if __name__ == "__main__":
    main()
