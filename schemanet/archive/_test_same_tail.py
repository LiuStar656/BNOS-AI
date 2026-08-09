# -*- coding: utf-8 -*-
"""同末词子集命中率（严格理解增益检验）。

背景（用户质疑"top-1 区分度可能是无效指标"后确立的判据）：
  wsum 只盯末词——对"同末词、异前缀、异真实下一词"的样本组，它组内
  全预测同一词（末词最高频转移），命中率 ≈ 组内多数类占比，无区分能力。
  若上下文引擎真利用前缀提升正确性，其命中率应显著高于 wsum。
  高出部分 = "利用上下文提升正确性"的直接证据，而非指标噪音。

用法：python _test_same_tail.py [--model runs/xxx/net_clean.npz]
      [--min-group 3] [--max-group 20] [--beta 2.0] [--w-b 0.5]
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from schema_net import _word_pattern
from sparse_net import _pats_matrix, load_net, outsum_sparse
from grad_readout import GradReadout
from _accept_scale20w import CORPUS, EVAL_SUB_TEST, K, MAXLEN, N, SEED
from _cand_readout import (_top1, _trace_logits, cand_b_logits, centrality,
                           sharpness)

DELTA_OFF = 0.005


def build_samples(toks_list, vocab_idx, min_len=3):
    """位置样本 [(prefix_ids, target, last_id)]，只取 t>=2（前缀长度>=2，
    末词前有上下文可资利用；t=1 同末词即同首词，无差异可区分）。"""
    samples = []
    for toks in toks_list:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(2, len(ids)):
            samples.append((tuple(ids[:t]), ids[t], ids[t - 1]))
    return samples


def group_samples(samples, min_group, max_group):
    """按末词分组；保留组内样本数在 [min_group, max_group] 且真实下一词
    不止一个的组（同末词异目标才有区分可言）。"""
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
    ap.add_argument("--model", default=None,
                    help="net_clean.npz 路径（默认= runs 下最新 net_clean.npz）")
    ap.add_argument("--min-group", type=int, default=3)
    ap.add_argument("--max-group", type=int, default=20)
    ap.add_argument("--beta", type=float, default=2.0)
    ap.add_argument("--w-b", type=float, default=0.5)
    args = ap.parse_args()

    if args.model is None:
        cands = sorted(Path("runs").glob("*/net_clean.npz"),
                       key=lambda p: p.stat().st_mtime)
        args.model = str(cands[-1]) if cands else None
    if not args.model:
        raise SystemExit("未找到 net_clean.npz，请用 --model 指定")
    print(f"模型: {args.model}", flush=True)

    ng, vocab, ctx = load_net(args.model, seed=42, return_ctx=True)
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)
    V = len(vocab)
    vocab_idx = {w: i for i, w in enumerate(vocab)}

    # 同评估子集（与 L1 一致）
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
    S, S_norm = ro.S, ro.S_norm
    outsum = outsum_sparse(ng, pats, vocab, slot=0)
    if ctx is not None:
        ro.ctx_wgt = np.array(ctx, dtype=float)
        s = float(ro.ctx_wgt.sum())
        if s > 0:
            ro.ctx_wgt = ro.ctx_wgt / s
    sharp = sharpness(S_norm)
    cent = centrality(S)
    norm_arr = np.zeros(V)
    for wi, w in enumerate(vocab):
        norm_arr[wi] = outsum.get(w, 0.0) if outsum else 0.0
    print(f"grad ctx_wgt: {np.round(ro.ctx_wgt, 4)}", flush=True)

    # ── 同末词组构建 ──
    samples = build_samples(ev_te, vocab_idx)
    groups = group_samples(samples, args.min_group, args.max_group)
    n_groups = len(groups)
    n_samp = sum(len(lst) for _, lst in groups)
    print(f"位置样本 {len(samples)} → 同末词组 {n_groups} 组 / {n_samp} 样本"
          f"（min_group={args.min_group}, max_group={args.max_group}）",
          flush=True)
    if not groups:
        raise SystemExit("无合格同末词组，放宽 --min-group/--max-group")

    # ── 各引擎逐样本 top-1 ──
    def p_wsum(ids):
        return _top1(S_norm[:, ids[-1]].copy(), vocab, set(ids))

    def p_grad(ids):
        lg = ro.logits(ids).copy()
        lg[lg <= 0] = -np.inf
        for wid in ids:
            lg[wid] = -np.inf
        return _top1(lg, vocab, set(ids))

    def p_candb(ids):
        return _top1(cand_b_logits(S_norm, sharp, list(ids), args.w_b), vocab,
                     set(ids))

    def p_trace(word_list):
        m = _trace_logits(ng, pats, vocab, vocab_idx, S, norm_arr, word_list,
                          DELTA_OFF, focus=False)
        return _top1(m, vocab, set(word_list)) if m is not None else None

    def p_candc(word_list):
        m = _trace_logits(ng, pats, vocab, vocab_idx, S, norm_arr, word_list,
                          DELTA_OFF, focus=True, cent_norm=cent, beta=args.beta)
        return _top1(m, vocab, set(word_list)) if m is not None else None

    # 收集组级明细（示例输出用）
    engines = ["wsum", "grad", "candB", "trace", "candC"]
    hits = Counter()
    total = Counter()
    detail = []          # 前 8 组明细（组内命中对比）
    for gi, (last, lst) in enumerate(groups):
        last_word = vocab[last]
        g_hits = Counter()
        rows = []
        for pids, tgt in lst:
            tgt_w = vocab[tgt]
            preds = {"wsum": p_wsum(pids), "grad": p_grad(pids),
                     "candB": p_candb(pids)}
            words = [vocab[w] for w in pids]
            preds["trace"] = p_trace(words)
            preds["candC"] = p_candc(words)
            for e in engines:
                total[e] += 1
                if preds[e] == tgt_w:
                    hits[e] += 1
                    g_hits[e] += 1
            rows.append({"ctx": "".join(words), "truth": tgt_w,
                         "preds": preds})
        if gi < 8:
            detail.append({"last": last_word, "n": len(lst),
                           "g_hits": {e: g_hits[e] for e in engines},
                           "rows": rows})

    # ── 汇总 ──
    def z_diff(a, na, b, nb):
        p = (a * na + b * nb) / (na + nb)
        se = (p * (1 - p) * (1 / na + 1 / nb)) ** 0.5
        return (a - b, (a - b) / se) if se > 0 else (a - b, None)

    n = total["wsum"]
    print("\n── 同末词子集命中率（> wsum 才算'利用上下文提升正确性'）──")
    print(f"{'引擎':6s} {'命中率':>8s} {'vs wsum':>10s} {'z':>6s}")
    tab = {}
    for e in engines:
        hr = hits[e] / total[e]
        d, z = z_diff(hr, total[e], hits["wsum"] / n, n)
        tab[e] = {"hits": int(hits[e]), "n": int(total[e]),
                  "rate": round(hr, 4), "diff": round(d, 4),
                  "z": round(z, 2) if z is not None else None}
        sig = "  ★显著优于wsum" if z is not None and z > 1.96 else ""
        print(f"{e:6s} {hr:8.4f} {d:+10.4f} {z if z is not None else 0:6.2f}{sig}")

    # ── 组级明细示例 ──
    print(f"\n── 前 {len(detail)} 组明细（含组内命中）──")
    for d in detail:
        print(f"\n末词『{d['last']}』 n={d['n']}  组内命中 "
              f"{ {e: v for e, v in d['g_hits'].items()} }")
        for r in d["rows"]:
            print(f"  {r['ctx']}|真={r['truth']}   "
                  f"{'  '.join(f'{e}={r['preds'][e]}' for e in engines)}")

    # ── 留档 ──
    out_dir = Path("runs") / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "tag": "同末词子集命中率（严格理解增益检验）",
        "model": args.model, "beta": args.beta, "w_b": args.w_b,
        "min_group": args.min_group, "max_group": args.max_group,
        "eval_n": len(ev_te), "n_groups": n_groups, "n_samples": n_samp,
        "top1": {e: {k: tab[e][k] for k in ("hits", "n", "rate", "diff", "z")}
                 for e in engines},
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {out_dir}/result.json", flush=True)


if __name__ == "__main__":
    main()
