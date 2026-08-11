# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""主题注意力（TA）网格检验：参数变体 × 位置分层 + 同末词命中率。

判据（同末词严格测试确立）：
  - 位置分层：总 top-1（参考，可能被词频污染）
  - 同末词命中率：> wsum（0.1141）才证明"利用上下文提升正确性"

网格：tau ∈ {1,2,4} × decay ∈ {0,0.3} × residual ∈ {0,0.5} = 12 组合。
用法：python _test_ta.py [--model runs/xxx/net_clean.npz]
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema_net import _word_pattern
from sparse_net import _pats_matrix, load_net
from grad_readout import GradReadout
from _accept_scale20w import (CORPUS, EVAL_SUB_TEST, K, MAXLEN, N, SEED,
                              GRP_TAGS, gname)
from _cand_readout import _top1, ta_logits

VARIANT_GRID = [(tau, decay, res) for tau in (1, 2, 4)
                for decay in (0.0, 0.3) for res in (0.0, 0.5)]


def build_samples(toks_list, vocab_idx):
    """位置样本 [(prefix_ids, target, last_id)]，只取 t>=2。"""
    samples = []
    for toks in toks_list:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(2, len(ids)):
            samples.append((tuple(ids[:t]), ids[t], ids[t - 1]))
    return samples


def group_samples(samples, min_group=3, max_group=20):
    g = defaultdict(list)
    for pids, tgt, last in samples:
        g[last].append((pids, tgt))
    out = []
    for last, lst in g.items():
        if not (min_group <= len(lst) <= max_group):
            continue
        if len({t for _, t in lst}) < 2:
            continue
        out.append((last, lst))
    out.sort(key=lambda x: -len(x[1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="runs/20260809_160027/net_clean.npz")
    args = ap.parse_args()

    ng, vocab, ctx = load_net(args.model, seed=42, return_ctx=True)
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)
    V = len(vocab)
    vocab_idx = {w: i for i, w in enumerate(vocab)}

    tokenized = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
    rng = np.random.default_rng(SEED + 9000)
    perm = rng.permutation(len(tokenized))
    n_train = int(len(tokenized) * 0.8)
    test_toks = [tokenized[i] for i in perm[n_train:]]
    ev_te = [test_toks[i] for i in
             rng.choice(len(test_toks), min(EVAL_SUB_TEST, len(test_toks)),
                        replace=False)]

    ro = GradReadout(ng, pats, vocab, pats_mat, maxlen=MAXLEN)
    ro.build_score_matrix()
    S_norm = ro.S_norm
    print(f"模型: {args.model}  评估 {len(ev_te)} 句", flush=True)

    # ── 位置分层：wsum + 12 变体 ──
    print("\n── 位置分层（全评估子集）──", flush=True)
    print(f"{'变体':>22s}  " + "  ".join(f"{g:6s}" for g in GRP_TAGS) + "   avg",
          flush=True)
    layer = {"wsum": None}
    # wsum 参考（末词列直读，等价 eval_wsum_g 纯排序）
    hits, total = Counter(), Counter()
    for toks in ev_te:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(1, len(ids)):
            lg = S_norm[:, ids[t - 1]].copy()
            used = set(ids[:t])
            order = np.argsort(-lg)
            cand = next((wi for wi in order if lg[wi] > 0 and wi not in used),
                        None)
            g = gname(t)
            total[g] += 1
            if cand is not None and vocab[cand] == toks[t]:
                hits[g] += 1
    w_tab = {GRP_TAGS[i]: (hits[i] / total[i] if total[i] else None)
             for i in range(len(GRP_TAGS))}
    wsum_avg = sum(v for v in w_tab.values() if v is not None) / \
        sum(1 for v in w_tab.values() if v is not None)
    layer["wsum"] = w_tab
    print(f"{'wsum':>22s}  "
          f"{'  '.join(f'{w_tab[g]:6.4f}' if w_tab[g] is not None else '  --  ' for g in GRP_TAGS)}"
          f"   {wsum_avg:.4f}", flush=True)
    layer_tab = {}
    for tau, dec, res in VARIANT_GRID:
        ht, tt = Counter(), Counter()
        for toks in ev_te:
            ids = [vocab_idx[w] for w in toks if w in vocab_idx]
            for t in range(1, len(ids)):
                lg = ta_logits(S_norm, ids[:t], tau, dec, res)
                used = set(ids[:t])
                order = np.argsort(-lg)
                cand = next((wi for wi in order if lg[wi] > 0 and wi not in used),
                            None)
                g = gname(t)
                tt[g] += 1
                if cand is not None and vocab[cand] == toks[t]:
                    ht[g] += 1
        tb = {GRP_TAGS[i]: (ht[i] / tt[i] if tt[i] else None)
              for i in range(len(GRP_TAGS))}
        avg = sum(v for v in tb.values() if v is not None) / \
            sum(1 for v in tb.values() if v is not None)
        layer_tab[(tau, dec, res)] = tb
        print(f"τ={tau:.0f} d={dec:.1f} r={res:.1f}   "
              f"{'  '.join(f'{tb[g]:6.4f}' if tb[g] is not None else '  --  ' for g in GRP_TAGS)}"
              f"   {avg:.4f}", flush=True)

    # ── 同末词命中率：wsum + 12 变体 ──
    samples = build_samples(ev_te, vocab_idx)
    groups = group_samples(samples)
    n_groups = len(groups)
    n_samp = sum(len(lst) for _, lst in groups)
    print(f"\n── 同末词命中率（{n_groups} 组 / {n_samp} 样本；wsum 基线=多数类）──",
          flush=True)
    print(f"{'变体':>22s}  {'命中率':>8s}  {'hits':>6s}  {'vs wsum':>10s}  {'z':>6s}",
          flush=True)

    def z_diff(a, na, b, nb):
        p = (a * na + b * nb) / (na + nb)
        se = (p * (1 - p) * (1 / na + 1 / nb)) ** 0.5
        return (a - b, (a - b) / se) if se > 0 else (a - b, None)

    # wsum 同末词
    def pred_w(ids):
        return _top1(S_norm[:, ids[-1]].copy(), vocab, set(ids))

    def pred_ta(ids, tau, dec, res):
        return _top1(ta_logits(S_norm, ids, tau, dec, res), vocab, set(ids))

    wh = wtotal = 0
    for _, lst in groups:
        for pids, tgt in lst:
            wtotal += 1
            if pred_w(pids) == vocab[tgt]:
                wh += 1
    wrate = wh / wtotal
    print(f"{'wsum':>22s}  {wrate:8.4f}  {wh:6d}  {'':>10s}  {'':>6s}",
          flush=True)
    same_tail = {}
    for tau, dec, res in VARIANT_GRID:
        h = n = 0
        for _, lst in groups:
            for pids, tgt in lst:
                n += 1
                if pred_ta(pids, tau, dec, res) == vocab[tgt]:
                    h += 1
        rate = h / n
        d, z = z_diff(rate, n, wrate, wtotal)
        same_tail[(tau, dec, res)] = {"hits": h, "n": n, "rate": round(rate, 4),
                                      "diff": round(d, 4),
                                      "z": round(z, 2) if z is not None else None}
        sig = "  ★" if z is not None and z > 1.96 else ""
        print(f"τ={tau:.0f} d={dec:.1f} r={res:.1f}   {rate:8.4f}  {h:6d}  "
              f"{d:+10.4f}  {z if z is not None else 0:6.2f}{sig}", flush=True)

    # ── 留档 ──
    out_dir = Path("runs") / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "tag": "主题注意力 TA 网格检验（位置分层 + 同末词命中率）",
        "model": args.model,
        "eval_n": len(ev_te), "n_groups": n_groups, "n_samples": n_samp,
        "top1_layer": {("wsum" if k is None else f"t{k[0]}_d{k[1]}_r{k[2]}"):
                       {g: (round(v, 4) if v is not None else None)
                        for g, v in (w_tab if k is None else layer_tab[k]).items()}
                       for k in [None] + VARIANT_GRID},
        "same_tail": {("wsum" if k is None else f"t{k[0]}_d{k[1]}_r{k[2]}"): v
                      for k, v in ([None, {"hits": wh, "n": wtotal,
                                           "rate": round(wrate, 4),
                                           "diff": 0.0, "z": 0.0}] +
                                   list(same_tail.items()))},
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {out_dir}/result.json", flush=True)


if __name__ == "__main__":
    main()
