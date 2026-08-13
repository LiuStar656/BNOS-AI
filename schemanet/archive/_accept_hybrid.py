# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""Phase 0：PAHE（位置感知混合引擎）验证——短前缀 wsum + 长前缀 trace。

背景（成长路线方案 §3.1）：诊断 runs/20260809_113206 证明——trace（无参数
动力学）在 t4-8 中长位置反超 wsum（+0.017/+0.007），grad8/16 全线不兑现。
候选核心机制 = 按前缀长度选引擎：
    t ≤ 3 → wsum（短上下文基线最稳）
    t ≥ 4 → trace（长上下文增益承载者）

验证内容：
  ① 三引擎位置分层 top-1（干净口径：扰动后 W，即 103532 最终模型 W）
  ② 增益统计显著性：trace-wsum 差值 vs 二项合并 CI（|z|>1.96 显著）
     —— 判定 trace 长位置增益是真实信号而非采样噪声
  ③ 生成对照：20 前缀 × {wsum / trace / pahe}，前缀一致性 + 速度计时
  ④ 人工流畅度表留档（human_eval.txt，AI 代打 + 人工复核）

判定标准（§3.1 四条，自动部分）：
  P1 总平均 PAHE ≥ max(wsum, trace)        （按构造满足，记录）
  P2 长位置（t4-5+t6-8）trace-wsum 差 > 0 且 |z|>1.96
  P3 短位置（t1-3）wsum 不劣于 trace        （记录 z，供参考）
  P4 生成：pahe 前缀一致性 = 20/20，速度不劣于单引擎

用法：python _accept_hybrid.py     （留档 runs/时间戳/result.json）
"""
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema_net import _word_pattern, build_pulse
from sparse_net import (load_net, _pats_matrix, outsum_sparse, build_score_mat,
                        predict_cands_wsum_sparse, predict_cands_trace_sparse)
from grad_readout import GradReadout

N, K = 8192, 16
SEED = 42
CORPUS = "data/corpus_open.json"
NET = "runs/20260809_103532/net.npz"   # 最终模型（Hebbian+sleep+train_w）
DELTA_OFF = 0.02
EVAL_N = 2000             # 加大样本：验证 trace 长位置增益显著性（600→2000）
SWITCH_T = 4            # t ≥ SWITCH_T 切 trace（t1-3 用 wsum）
GEN_N = 20
GEN_MAX = 10
TOP_K, TEMP, PENALTY = 12, 1.1, 2.5
GRPS = ((1, 1), (2, 2), (3, 3), (4, 5), (6, 8), (9, 30))
GRP_TAGS = ["t1", "t2", "t3", "t4-5", "t6-8", "t9+"]


def gname(t):
    for i, (lo, hi) in enumerate(GRPS):
        if lo <= t <= hi:
            return i
    return len(GRPS) - 1


def tab(hits, total):
    return {GRP_TAGS[i]: (hits[i] / total[i] if total[i] else None)
            for i in range(len(GRPS))}, int(sum(total.values()))


def diff_sig(p1, n1, p2, n2):
    """两命中率差值统计显著性（二项合并 z 检验）。返回 (diff, z)。"""
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


def eval_trace_g(ng, toks_list, S, pats, vocab, norm_base, delta_off):
    vtab = {w: i for i, w in enumerate(vocab)}
    V = len(vocab)
    hits, total = Counter(), Counter()
    for toks in toks_list:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.refractory_left = np.zeros(ng.n, dtype=int)
        ng.last_k_star = np.zeros(ng.n, dtype=int)
        for t in range(1, len(toks)):
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(build_pulse(ng.n, pats[toks[t - 1]]), slot=0)
            ng.step(np.zeros(ng.n), slot=0)
            last = toks[t - 1]
            p_last = S[:, vtab[last]].copy()
            den = norm_base.get(last, 0.0) if norm_base else 0.0
            if den > 0:
                p_last /= den
            used = set(toks[:t])
            order = np.argsort(-p_last)
            top_idx = [wi for wi in order if p_last[wi] > 0 and vocab[wi] not in used]
            if len(top_idx) >= 2 and p_last[top_idx[0]] - p_last[top_idx[1]] >= delta_off:
                cands = [(vocab[wi], round(float(p_last[wi]), 6)) for wi in top_idx]
            else:
                last_pats = pats[last]
                trace_last = float(ng.pre_trace[last_pats].max()) if len(last_pats) else 0.0
                mix = np.zeros(V)
                for src_w in toks[:t]:
                    tr = float(ng.pre_trace[pats[src_w]].max()) if pats[src_w] else 0.0
                    wgt = tr / trace_last if trace_last > 0 else tr
                    if src_w != last:
                        wgt *= 0.1
                    if wgt <= 0:
                        continue
                    p = S[:, vtab[src_w]].copy()
                    d2 = norm_base.get(src_w, 0.0) if norm_base else 0.0
                    if d2 > 0:
                        p /= d2
                    mix += wgt * p
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
    """PAHE：同一注入循环，每位置按 t 选引擎（t<switch_t → wsum，否则 trace）。"""
    vtab = {w: i for i, w in enumerate(vocab)}
    V = len(vocab)
    hits, total = Counter(), Counter()
    for toks in toks_list:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.refractory_left = np.zeros(ng.n, dtype=int)
        ng.last_k_star = np.zeros(ng.n, dtype=int)
        for t in range(1, len(toks)):
            # 注入 t-1 词（trace 分支需要完整动力学历史，wsum 分支注入无害）
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(build_pulse(ng.n, pats[toks[t - 1]]), slot=0)
            ng.step(np.zeros(ng.n), slot=0)
            last = toks[t - 1]
            p_last = S[:, vtab[last]].copy()
            den = norm_base.get(last, 0.0) if norm_base else 0.0
            if den > 0:
                p_last /= den
            used = set(toks[:t])
            if t < switch_t:
                # ── wsum 分支 ──
                cands = [(vocab[wi], float(p_last[wi])) for wi in range(V)
                         if p_last[wi] > 0 and vocab[wi] not in used]
                cands.sort(key=lambda x: -x[1])
            else:
                # ── trace 分支（同 eval_trace_g）──
                order = np.argsort(-p_last)
                top_idx = [wi for wi in order if p_last[wi] > 0 and vocab[wi] not in used]
                if len(top_idx) >= 2 and p_last[top_idx[0]] - p_last[top_idx[1]] >= delta_off:
                    cands = [(vocab[wi], round(float(p_last[wi]), 6)) for wi in top_idx]
                else:
                    last_pats = pats[last]
                    trace_last = float(ng.pre_trace[last_pats].max()) if len(last_pats) else 0.0
                    mix = np.zeros(V)
                    for src_w in toks[:t]:
                        tr = float(ng.pre_trace[pats[src_w]].max()) if pats[src_w] else 0.0
                        wgt = tr / trace_last if trace_last > 0 else tr
                        if src_w != last:
                            wgt *= 0.1
                        if wgt <= 0:
                            continue
                        p = S[:, vtab[src_w]].copy()
                        d2 = norm_base.get(src_w, 0.0) if norm_base else 0.0
                        if d2 > 0:
                            p /= d2
                        mix += wgt * p
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
    """生成：engine='pahe' 时每步按已生成长度切换 wsum/trace。"""
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

    # ── 语料切分（与 113206/103532 同口径：SEED+9000 排列 80/20）──
    tokenized = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
    rng = np.random.default_rng(SEED + 9000)
    perm = rng.permutation(len(tokenized))
    n_train = int(len(tokenized) * 0.8)
    train_toks = [tokenized[i] for i in perm[:n_train]]
    test_toks = [tokenized[i] for i in perm[n_train:]]
    ev_te = [test_toks[i] for i in
             rng.choice(len(test_toks), min(EVAL_N, len(test_toks)), replace=False)]

    # ── 加载最终模型（103532）+ 扰动后 W 构建 S（干净口径）──
    ng, vocab, _ctx = load_net(NET, seed=SEED, return_ctx=True)
    ng.learn_gate = False
    pats = {w: _word_pattern(ng.n, ng.wta_k, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)
    outsum = outsum_sparse(ng, pats, vocab, slot=0)
    S = build_score_mat(ng, pats, vocab, pats_mat, slot=0)
    print(f"加载 {NET}: 词表 {len(vocab)}，S {S.shape}，留出评估 {len(ev_te)} 句",
          flush=True)

    # ── ① 三引擎位置分层 top-1 ──
    t0 = time.time()
    w_tab, w_n = eval_wsum_g(S, vocab, ev_te, outsum)
    print(f"① wsum: {w_tab}  n={w_n}  [{time.time()-t0:.0f}s]", flush=True)
    t0 = time.time()
    tr_tab, tr_n = eval_trace_g(ng, ev_te, S, pats, vocab, outsum, DELTA_OFF)
    print(f"① trace: {tr_tab}  n={tr_n}  [{time.time()-t0:.0f}s]", flush=True)
    t0 = time.time()
    pa_tab, pa_n = eval_pahe_g(ng, ev_te, S, pats, vocab, outsum, DELTA_OFF, SWITCH_T)
    print(f"① pahe: {pa_tab}  n={pa_n}  [{time.time()-t0:.0f}s]", flush=True)

    def avg(t_):
        return sum(v for v in t_.values() if v is not None) / sum(1 for v in t_.values() if v is not None)

    w_avg, tr_avg, pa_avg = avg(w_tab), avg(tr_tab), avg(pa_tab)
    print(f"总平均: wsum {w_avg:.4f}  trace {tr_avg:.4f}  pahe {pa_avg:.4f}")

    # ── ② 显著性（trace vs wsum，长/短位置合并）──
    counts = Counter()
    for toks in ev_te:
        for t in range(1, len(toks)):
            counts[gname(t)] += 1

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
    d_short, z_short = diff_sig(*merged_rate(tr_tab, 1, 3), *merged_rate(w_tab, 1, 3))
    sig_long = d_long is not None and d_long > 0 and abs(z_long) > 1.96
    sig_short = d_short is not None and abs(z_short) > 1.96
    print(f"② trace-wsum 长位置(t4-8): {d_long:+.4f} z={z_long:+.2f} "
          f"{'显著 ✓' if sig_long else '不显著'}")
    print(f"② trace-wsum 短位置(t1-3): {d_short:+.4f} z={z_short:+.2f} "
          f"({'wsum 优势' if d_short < 0 else 'trace 优势'})")

    # ── ③ 生成对照 + 速度 ──
    ro = GradReadout(ng, pats, vocab, pats_mat, maxlen=8)
    from generator import Generator
    gen = Generator(ro, outsum=outsum, seed=SEED + 7)
    starters = [toks[0] for toks in train_toks if toks]
    sfreq = Counter(starters)
    prefixes = [w for w, _ in sfreq.most_common(GEN_N)]
    prefixes = [p for p in prefixes if p in {w: 0 for w in vocab}][:GEN_N]

    samples, speed = [], {}
    for eng in ("wsum", "trace", "pahe"):
        t0 = time.time()
        n_tok = 0
        for pre in prefixes:
            g = gen_one(gen, [pre], GEN_MAX, TOP_K, TEMP, PENALTY, engine=eng)
            n_tok += max(0, len(g) - 1)
        dt = time.time() - t0
        speed[eng] = round(n_tok / dt, 1) if dt > 0 else 0.0
        print(f"③ 生成[{eng}] 20 前缀 {n_tok} token {dt:.1f}s = {speed[eng]} token/s",
              flush=True)

    for pre in prefixes:
        samples.append({
            "prefix": pre,
            "wsum": "".join(gen_one(gen, [pre], GEN_MAX, TOP_K, TEMP, PENALTY, "wsum")),
            "trace": "".join(gen_one(gen, [pre], GEN_MAX, TOP_K, TEMP, PENALTY, "trace")),
            "pahe": "".join(gen_one(gen, [pre], GEN_MAX, TOP_K, TEMP, PENALTY, "pahe")),
        })
    n_pfx_ok = sum(1 for s in samples if s["pahe"] and s["pahe"].startswith(s["prefix"]))
    print(f"③ pahe 前缀一致性 {n_pfx_ok}/{GEN_N}")

    # ── 判定 ──
    p1 = pa_avg >= max(w_avg, tr_avg) - 1e-9
    p2 = sig_long
    p3 = d_short is None or d_short < 0 or z_short > -1.96  # 短位置 wsum 不吃亏
    p4 = n_pfx_ok == GEN_N
    verdict = "PASS" if (p1 and p2 and p3 and p4) else "FAIL"
    print(f"\n判定: P1总平均≥max {p1}  P2长位置增益显著 {p2}  "
          f"P3短位置wsum不吃亏 {p3}  P4前缀一致 {p4}  → {verdict}")

    # ── 留档 ──
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("runs") / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "tag": "Phase 0 PAHE 验证（短前缀 wsum + 长前缀 trace）",
        "net": NET, "delta_off": DELTA_OFF, "switch_t": SWITCH_T,
        "eval_n": len(ev_te), "pos_groups": GRP_TAGS,
        "top1": {"wsum": w_tab, "trace": tr_tab, "pahe": pa_tab,
                 "avg": {"wsum": round(w_avg, 4), "trace": round(tr_avg, 4),
                         "pahe": round(pa_avg, 4)}, "n": counts},
        "sig": {"trace_vs_wsum": {
            "long_t4_8": {"diff": None if d_long is None else round(d_long, 4),
                          "z": round(z_long, 2), "significant": bool(sig_long)},
            "short_t1_3": {"diff": None if d_short is None else round(d_short, 4),
                           "z": round(z_short, 2)}}},
        "generation": {"speed_tok_s": speed, "prefix_ok": n_pfx_ok,
                       "n_prefix": GEN_N, "samples": samples},
        "verdict": verdict,
        "checks": {"P1_total": bool(p1), "P2_long_sig": bool(p2),
                   "P3_short": bool(p3), "P4_prefix": bool(p4)},
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# Phase 0 PAHE 人工流畅度评估（5 分制：5=自然流畅 / 3=可读但别扭 / 1=不通）\n",
             "# 三引擎对照：wsum / trace / pahe（pahe 为候选主引擎）\n\n"]
    for i, s in enumerate(samples, 1):
        lines.append(f"{i:2d}. 前缀[{s['prefix']}] 生成：{s['pahe']}\n"
                     f"    得分：__  （wsum: {s['wsum']} | trace: {s['trace']}）\n")
    (out_dir / "human_eval.txt").write_text("".join(lines), encoding="utf-8")
    print(f"\n留档: {out_dir}/result.json + human_eval.txt")


if __name__ == "__main__":
    main()
