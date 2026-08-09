# -*- coding: utf-8 -*-
"""引擎生成质量对比（用户视角的直接判断，不靠指标）。

设计（回应"只看指标是无效指标"）：
  1. 同末词、异前缀样本对：wsum 只盯末词 → 两组生成应完全一样（跑偏铁证）；
     上下文引擎若真利用上下文 → 生成应不同且贴合各自前缀主题。
  2. 每引擎贪心续写 N 词（确定性、可对比），排除前缀+已生成词。
  3. 输出表格由人直接读文本判断，不计算任何分数。

引擎：wsum / grad / candB / candC / trace / TA（τ=2, d=0.3, r=0.5）
用法：python _gen_cmp.py [--model runs/xxx/net_clean.npz] [--n 8] [--pairs 3]
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from schema_net import _word_pattern
from sparse_net import _pats_matrix, load_net, outsum_sparse
from grad_readout import GradReadout
from _accept_scale20w import CORPUS, EVAL_SUB_TEST, K, MAXLEN, N, SEED
from _cand_readout import (_top1, _trace_logits, cand_b_logits, centrality,
                           sharpness, ta_logits)

ENGINES = ["wsum", "grad", "candB", "candC", "trace", "TA"]


def build_pairs(toks_pool, vocab_set, n=3, min_len=6):
    """从真实语料抽同末词、异前缀、词表内、长度足够的对。
    优先严格模式（全句不含 <UNK>）；不足 n 组时回退到宽松模式
    （允许 <UNK>，仅保证末词与其余词在词表内）。"""
    unk = "<UNK>"

    def collect(strict):
        by_last = defaultdict(list)
        for toks in toks_pool:
            if len(toks) < min_len:
                continue
            if not all(w in vocab_set for w in toks):
                continue
            if strict and unk in toks:
                continue
            by_last[toks[-1]].append(toks)
        return by_last

    pairs = []
    for strict in (True, False):
        by_last = collect(strict)
        for last, lst in by_last.items():
            if len(lst) < 2:
                continue
            for a in lst:
                for b in lst:
                    if a == b or a[:-1] == b[:-1]:
                        continue
                    pairs.append((last, a, b))
                    if len(pairs) >= n:
                        return pairs
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="runs/20260809_160027/net_clean.npz")
    ap.add_argument("--n", type=int, default=8, help="每引擎续写词数")
    ap.add_argument("--pairs", type=int, default=3, help="同末词对组数")
    args = ap.parse_args()

    ng, vocab, ctx = load_net(args.model, seed=42, return_ctx=True)
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)
    V = len(vocab)
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    vtab = vocab_idx

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
    print(f"模型: {args.model}  ctx_wgt={np.round(ro.ctx_wgt, 4)}", flush=True)

    # ── 引擎 logits 工厂 ──
    def f_wsum(ids):
        return S_norm[:, ids[-1]].copy()

    def f_grad(ids):
        lg = ro.logits(ids).copy()
        lg[lg <= 0] = -np.inf
        return lg

    def f_candb(ids):
        return cand_b_logits(S_norm, sharp, ids)

    def f_ta(ids):
        return ta_logits(S_norm, ids, tau=2.0, decay=0.3, residual=0.5)

    def f_trace(word_list):
        m = _trace_logits(ng, pats, vocab, vtab, S, norm_arr, word_list,
                          delta_off=0.01, focus=False)
        return m

    def f_candc(word_list):
        m = _trace_logits(ng, pats, vocab, vtab, S, norm_arr, word_list,
                          delta_off=0.01, focus=True, cent_norm=cent, beta=2.0)
        return m

    FACT = {"wsum": lambda wl: f_wsum([vtab[w] for w in wl if w in vtab]),
            "grad": lambda wl: f_grad([vtab[w] for w in wl if w in vtab]),
            "candB": lambda wl: f_candb([vtab[w] for w in wl if w in vtab]),
            "TA": lambda wl: f_ta([vtab[w] for w in wl if w in vtab]),
            "trace": f_trace, "candC": f_candc}

    def gen(eng, word_list, n):
        """贪心续写 n 词（排除前缀+已生成，logits>0 限制）。"""
        cur = list(word_list)
        used = set(cur)
        out = []
        for _ in range(n):
            lg = FACT[eng](cur)
            if lg is None:
                break
            order = np.argsort(-lg)
            cand = next((wi for wi in order
                         if wi > 0 and lg[wi] > 0 and vocab[wi] not in used),
                        None)
            if cand is None:
                break
            w = vocab[cand]
            out.append(w)
            used.add(w)
            cur.append(w)
        return out

    # ── 同末词对构建（优先全词表内无 <UNK>，池子用全部留出集）──
    vocab_set = set(vocab)
    pairs = build_pairs(test_toks, vocab_set, n=args.pairs)
    print(f"同末词对 {len(pairs)} 组", flush=True)

    out_dir = Path("runs") / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    res_pairs = []
    for last, a, b in pairs:
        print(f"\n{'=' * 78}\n同末词『{last}』  A={' '.join(a)}  |  B={' '.join(b)}",
              flush=True)
        pa = {}
        for eng in ENGINES:
            ga = gen(eng, a, args.n)
            gb = gen(eng, b, args.n)
            ta_ = " ".join(a + ga)
            tb_ = " ".join(b + gb)
            same = (ga == gb)
            mark = "  ★同末词生成不同（用了上下文）" if not same else "  （与B相同→只盯末词）"
            print(f"  {eng:6s} A→ {ta_}  |  B→ {tb_}{mark}", flush=True)
            pa[eng] = {"genA": " ".join(ga), "genB": " ".join(gb),
                       "same": same}
        res_pairs.append({"last": last, "A": a, "B": b, "gens": pa})

    result = {"tag": "引擎生成质量对比（用户直接判断，无指标）",
              "model": args.model, "n": args.n, "pairs": res_pairs}
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    # 人类可读 txt 导出（生成内容是最重要的证据数据，需可直接阅读/留存）
    lines = [
        "═" * 72,
        "引擎生成质量对比（用户直接判断，无指标）",
        f"模型: {args.model}",
        f"续写: {args.n} 词/引擎 | 解码: 贪心（排除前缀+已生成，候选排除 <UNK>）",
        "═" * 72,
        "",
    ]
    for i, (last, a, b) in enumerate(pairs, 1):
        rp = res_pairs[i - 1]
        lines.append(f"[对 {i}] 同末词『{last}』")
        lines.append(f"  A: {' '.join(a)}")
        lines.append(f"  B: {' '.join(b)}")
        for eng in ENGINES:
            ga, gb, same = rp["gens"][eng]["genA"], rp["gens"][eng]["genB"], \
                rp["gens"][eng]["same"]
            mark = "★同末词生成不同（对前缀敏感）" if not same else "（同末词生成相同 → 只盯末词）"
            lines.append(f"  {eng:6s} A→ {ga}")
            lines.append(f"        B→ {gb}   {mark}")
        lines.append("")
    (out_dir / "result.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n留档: {out_dir}/result.json + result.txt", flush=True)


if __name__ == "__main__":
    main()
