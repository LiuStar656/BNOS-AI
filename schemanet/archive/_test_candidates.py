# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""grad + 候选 B/C 对照测试（v1.1 方向：主引擎候选谱系）。

对同一干净 W（--model，默认预验证净 W，20 万定案后可换）：
  1. 六引擎 top-1 位置分层：wsum / trace / pahe / grad / candB / candC
  2. 主题保持/切换测试（内容压缩式遗忘）：对句预测 + JS 区分度差
  3. 留档 runs/时间戳/result.json

用法：python _test_candidates.py [--model runs/xxx/net_clean.npz]
      [--beta 2.0] [--w-b 0.5]
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema_net import _word_pattern
from sparse_net import _pats_matrix, load_net, outsum_sparse
from grad_readout import GradReadout
from _accept_scale20w import (CORPUS, EVAL_SUB_TEST, K, MAXLEN, N, SEED,
                              eval_pahe_g, eval_trace_g, eval_wsum_g, GRP_TAGS,
                              gname)
from _accept_clean_cmp import eval_grad_g
from _cand_readout import (centrality, eval_cand_b_g, eval_cand_c_g,
                           pair_test, sharpness)

DELTA_OFF = 0.005
SWITCH_T = 4

# 手工 keep 对（词表内高频词）：同主题异细节，应预测一致
KEEP_PAIRS = [
    (["我", "很", "好"], ["你", "也", "好"]),
    (["我", "要", "买"], ["你", "要", "买"]),
    (["这个", "很", "好"], ["我", "都", "好"]),
]


def _auto_switch_pairs(ev_te, vocab_set, n=6):
    """从真实语料抽同末词对（末词相同、前缀不同）→ 不同上下文应预测不同。"""
    by_last = {}
    for toks in ev_te:
        if len(toks) >= 3 and toks[-1] in vocab_set:
            by_last.setdefault(toks[-1], []).append(toks)
    pairs = []
    for last, lst in by_last.items():
        if len(lst) < 2:
            continue
        for a in lst:
            for b in lst:
                if a == b or a[:-1] == b[:-1]:
                    continue
                pairs.append(("switch", a, b))
                if len(pairs) >= n:
                    return pairs
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="runs/20260809_145042/net_clean.npz")
    ap.add_argument("--beta", type=float, default=2.0, help="候选 C 门控强度")
    ap.add_argument("--w-b", type=float, default=0.5, help="候选 B 非末词总权重")
    args = ap.parse_args()

    ng, vocab, ctx = load_net(args.model, seed=42, return_ctx=True)
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)
    V = len(vocab)

    # 同评估子集（与 L1 一致）
    tokenized = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
    rng = np.random.default_rng(SEED + 9000)
    perm = rng.permutation(len(tokenized))
    n_train = int(len(tokenized) * 0.8)
    test_toks = [tokenized[i] for i in perm[n_train:]]
    ev_te = [test_toks[i] for i in
             rng.choice(len(test_toks), min(EVAL_SUB_TEST, len(test_toks)),
                        replace=False)]
    print(f"模型: {args.model}  词表 {V}  评估 {len(ev_te)} 句", flush=True)

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
    print(f"grad ctx_wgt: {np.round(ro.ctx_wgt, 4)}", flush=True)

    # ── 六引擎 top-1 位置分层 ──
    print("\n── 六引擎 top-1 位置分层（干净 W，同评估子集）──", flush=True)
    res = {}
    w_tab, w_n = eval_wsum_g(S, vocab, ev_te, outsum)
    tr_tab, tr_n = eval_trace_g(ng, ev_te, S, pats, vocab, outsum, DELTA_OFF)
    pa_tab, pa_n = eval_pahe_g(ng, ev_te, S, pats, vocab, outsum, DELTA_OFF,
                               SWITCH_T)
    gr_tab, gr_n = eval_grad_g(ro, ev_te)
    b_tab, b_n = eval_cand_b_g(S_norm, sharp, vocab, ev_te, args.w_b)
    c_tab, c_n = eval_cand_c_g(ng, ev_te, S, S_norm, pats, vocab, outsum,
                               DELTA_OFF, cent, args.beta)
    res["wsum"], res["trace"], res["pahe"] = w_tab, tr_tab, pa_tab
    res["grad"], res["candB"], res["candC"] = gr_tab, b_tab, c_tab
    avg = lambda t: sum(v for v in t.values() if v is not None) / \
        sum(1 for v in t.values() if v is not None)
    print("位置   ", "  ".join(f"{e:6s}" for e in res))
    for g in GRP_TAGS:
        print(f"{g:6s} ", "  ".join(
            f"{avg({g: res[e][g] if res[e][g] is not None else None}):.4f}"
            if res[e][g] is not None else f"{'--':>6s}"
            for e in res).replace("nan", " --"))
    print("总平均 ", "  ".join(f"{avg(res[e]):.4f}" for e in res), flush=True)

    # ── 主题保持/切换测试 ──
    print("\n── 主题保持/切换测试（内容压缩式遗忘）──", flush=True)
    pairs = ([("keep", a, b) for a, b in KEEP_PAIRS]
             + _auto_switch_pairs(ev_te, set(vocab), n=6))
    diff = pair_test(ng, ro, pats, vocab, S, S_norm, sharp, cent, outsum,
                     pairs, DELTA_OFF, args.beta)

    # ── 留档 ──
    out_dir = Path("runs") / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "tag": "候选谱系对照：grad + 候选 B/C（干净 W）",
        "model": args.model, "beta": args.beta, "w_b": args.w_b,
        "eval_n": len(ev_te), "delta_off": DELTA_OFF,
        "top1": {e: {g: res[e][g] for g in GRP_TAGS} for e in res},
        "avg": {e: avg(res[e]) for e in res},
        "pair_diff": diff,
        "pairs": [{"tag": t, "a": a, "b": b} for t, a, b in pairs],
        "ctx_wgt": [round(float(x), 4) for x in ro.ctx_wgt],
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {out_dir}/result.json", flush=True)


if __name__ == "__main__":
    main()
