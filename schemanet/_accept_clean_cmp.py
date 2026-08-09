# -*- coding: utf-8 -*-
"""Phase 2 L1 干净对照：train_w 前后三路 + 同语料纯量（2 万子集 vs 20 万全量）。

回答三个口径问题（L1 报告 §五）：
  Q1: train_w 是否损害 wsum/基础转移？
      → 同一 2 万子集、同一评估子集，train_w 前后三路对照
  Q2: 同语料纯量 scaling（真实数据增益）？
      → 2 万子集（train_w 后） vs L1-20 万（runs/20260809_125334，train_w 后）
      同词表（全量 3000）、同评估子集（rng(SEED+9000) 复现）、同 train_w 口径
  Q3: 干净 W（train_w 前）上 trace 增益是否依然显著？
      → train_w 前 wsum vs trace（同 2 万子集）

2 万子集 = perm[:20000]（L1 训练集前 2 万句，严格同源子集）。

用法：python _accept_clean_cmp.py     （留档 runs/时间戳/result.json）
"""
import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from _accept_scale20w import (CORPUS, DELTA_SCAN, GRP_TAGS, K, KV, MAXLEN, N,
                              SEED, SCAN_SUB, SKIP_TRAIN_CTX, SWITCH_T,
                              TRAIN_W_EPOCHS, TRAIN_W_LR, UNK, _hebb_chunk,
                              _merge_hebb, build_positions, eval_pahe_g,
                              eval_trace_g, eval_wsum_g, gname)
from schema_net import _word_pattern
from sparse_net import (SparseSchemaNet, _pats_matrix, build_score_mat,
                        evaluate_trace_smat, outsum_sparse, save_net)
from grad_readout import GradReadout

SUB_N = 20000                 # 同源训练子集（--sub 可覆盖，如 160000 = 20 万全量）
W_MAX = 64.0                  # w_max 16→64：20 万句 Hebbian 权重 cap 顶满饱和，放大 cap 修复区分度塌缩
N_WORKERS = 16                # 16 进程（机器 20 核；分块合并加法可交换，逐值等价）
CTX_EPOCHS = 20
CTX_LR = 0.5
CTX_SUBSAMPLE = 2000          # train_ctx 每 epoch 抽样（全量 128 万样本太慢，抽样已验证等效口径）
EVAL_SUB_TEST = 2000          # 评估子集（与 L1 完全一致）
L1_REF = "runs/20260809_125334/result.json"
SLEEP_DECAY, SLEEP_EPS = 0.3, 1e-4


def mk_net(seed):
    return SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                           w_max=W_MAX, wta_k=K, noise_p=0.06, noise_amp=0.5,
                           weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5,
                           stdp_neg=0.0, refractory=1,
                           rng=np.random.default_rng(seed))


def eval_grad_g(ro, toks_list):
    """grad 引擎 top-1 位置分层（与三路同 GRPS 口径）。"""
    _, _, total, _ = ro.evaluate(toks_list)
    h, tot = Counter(), Counter()
    for toks in toks_list:
        ids = [ro.vocab_idx[w] for w in toks if w in ro.vocab_idx]
        for t in range(1, len(ids)):
            logits = ro.logits(ids[:t]).copy()
            logits[logits <= 0] = -np.inf
            for wid in ids[:t]:
                logits[wid] = -np.inf
            g = gname(t)
            tot[g] += 1
            if ro.vocab[int(np.argmax(logits))] == toks[t]:
                h[g] += 1
    return {GRP_TAGS[i]: (h[i] / tot[i] if tot[i] else None)
            for i in range(len(GRP_TAGS))}, total


def train_ctx_ro(ng, pats, vocab, pats_mat, positions, tag):
    """冻结 W 训 ctx_wgt（grad 引擎读出参数），4d 验收（W 零扰动）。
    返回 (GradReadout, nnz0, nnz1)。"""
    ro = GradReadout(ng, pats, vocab, pats_mat, maxlen=MAXLEN)
    nnz0 = ro.nnz()
    t_c = ro.train_ctx(positions, lr=CTX_LR, epochs=CTX_EPOCHS, seed=SEED,
                       subsample=CTX_SUBSAMPLE)
    nnz1 = ro.nnz()
    print(f"train_ctx[{tag}] {t_c}s  ctx={np.round(ro.ctx_wgt, 4)}  "
          f"4d: nnz {nnz0}→{nnz1} 一致={nnz0 == nnz1}", flush=True)
    return ro, nnz0, nnz1


def eval_all(ng, S, pats, vocab, outsum, ev_te, delta_off, tag, ro=None):
    """四路评估 + 位置分层表（同 L1 口径）。返回 dict。"""
    w_tab, w_n = eval_wsum_g(S, vocab, ev_te, outsum)
    tr_tab, tr_n = eval_trace_g(ng, ev_te, S, pats, vocab, outsum, delta_off)
    pa_tab, pa_n = eval_pahe_g(ng, ev_te, S, pats, vocab, outsum, delta_off, SWITCH_T)
    avg = lambda t: sum(v for v in t.values() if v is not None) / \
        sum(1 for v in t.values() if v is not None)
    line = f"{tag}: wsum {avg(w_tab):.4f}  trace {avg(tr_tab):.4f}  " \
           f"pahe {avg(pa_tab):.4f}  n={w_n}"
    res = {"wsum": w_tab, "trace": tr_tab, "pahe": pa_tab,
           "avg": {"wsum": avg(w_tab), "trace": avg(tr_tab), "pahe": avg(pa_tab)},
           "n": w_n}
    if ro is not None:
        gr_tab, gr_n = eval_grad_g(ro, ev_te)
        res["grad"] = gr_tab
        res["avg"]["grad"] = avg(gr_tab)
        res["grad_n"] = gr_n
        line += f"  grad {avg(gr_tab):.4f}"
    print(line, flush=True)
    return res


def diff_sig(a, na, b, nb):
    """两比例之差 z 检验（同口径同样本量）。"""
    p = (a * na + b * nb) / (na + nb)
    se = (p * (1 - p) * (1 / na + 1 / nb)) ** 0.5
    return (a - b, (a - b) / se) if se > 0 else (a - b, None)


def main():
    global SUB_N
    ap = argparse.ArgumentParser()
    ap.add_argument("--sub", type=int, default=20000,
                    help="训练句数（20000=同源子集；160000=20 万全量干净 W 补测）")
    ap.add_argument("--no-train-w", action="store_true",
                    help="跳过 train_w，只跑干净 W 四路（grad 主引擎定案用，省 ~16 分钟）")
    args = ap.parse_args()
    SUB_N = args.sub
    DO_TRAIN_W = not args.no_train_w
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
    os.environ.setdefault("OMP_NUM_THREADS", "2")

    # ── 全量语料 + 词表（同 L1 口径）──
    tokenized = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
    freq = Counter(w for toks in tokenized for w in toks)
    vocab = [UNK] + [w for w, _ in freq.most_common(KV + 100) if w != UNK][:KV - 1]
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    rng = np.random.default_rng(SEED + 9000)
    perm = rng.permutation(len(tokenized))
    n_train = int(len(tokenized) * 0.8)
    test_toks = [tokenized[i] for i in perm[n_train:]]
    # 评估子集：与 L1 完全一致（同一 rng 序列）
    ev_te = [test_toks[i] for i in
             rng.choice(len(test_toks), min(EVAL_SUB_TEST, len(test_toks)),
                        replace=False)]
    # 训练子集：L1 训练集前 2 万句（严格同源子集）
    train_toks_sub = [tokenized[i] for i in perm[:SUB_N]]
    print(f"子集 {SUB_N} 句（同源，perm 前 {SUB_N}）/ 评估 {len(ev_te)} 句（与 L1 同子集）",
          flush=True)

    pats = {w: _word_pattern(N, K, w) for w in vocab}

    # ── Hebbian 并行（8 进程，2 万句）──
    ng = mk_net(SEED + 5000)
    t0 = time.time()
    tmp = Path("runs") / f"_cmp_tmp_{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    k = SUB_N // N_WORKERS
    tasks = [(i * k, SUB_N if i == N_WORKERS - 1 else (i + 1) * k,
              SEED + 5000 + 1000 * i, str(tmp / f"c{i}.pkl"))
             for i in range(N_WORKERS)]
    ctx = mp.get_context("spawn")
    with ctx.Pool(N_WORKERS) as pool:
        pool.map(_hebb_chunk, tasks)
    paths = [str(tmp / f"c{i}.pkl") for i in range(N_WORKERS)]
    ng.W_out, ng.slot_freq = _merge_hebb(paths, N, 4, W_MAX)
    for p in paths:
        Path(p).unlink(missing_ok=True)
    tmp.rmdir()
    t_hebb = round(time.time() - t0, 1)
    print(f"Hebbian {SUB_N} 句 × {N_WORKERS} 进程 {t_hebb}s", flush=True)

    # ── sleep 整理（同 L1 口径）──
    fq = ng.slot_freq[:, 0]
    nz = fq[fq > 0]
    min_wake = max(1.0, float(np.percentile(nz, 10))) if len(nz) else 1.0
    cleared, weakened = ng.sleep_consolidate(min_wake=min_wake,
                                             decay=SLEEP_DECAY, eps=SLEEP_EPS)
    ng.learn_gate = False
    print(f"sleep: min_wake={min_wake:.0f} 弱化 {weakened} 删除 {cleared}", flush=True)

    pats_mat = _pats_matrix(pats, vocab)
    outsum = outsum_sparse(ng, pats, vocab, slot=0)
    S = build_score_mat(ng, pats, vocab, pats_mat, slot=0)

    # ── delta_off 扫描（与 L1 同 rng 序列：perm → choice(ev_te 2000) → choice(scan 150)）──
    scan_idx = rng.choice(len(test_toks), min(SCAN_SUB, len(test_toks)),
                          replace=False)
    scan_toks = [test_toks[i] for i in scan_idx]
    best_delta, best_t = 0.02, -1.0
    for d in DELTA_SCAN:
        t_ = evaluate_trace_smat(ng, scan_toks, S, pats, vocab, outsum, delta_off=d)
        print(f"  delta_off={d}: {t_[0]:.4f}")
        if t_[0] > best_t:
            best_delta, best_t = d, t_[0]
    delta_off = best_delta
    print(f"→ delta_off={delta_off}", flush=True)

    # ── 留档目录提前（净 W 中间态要先存）──
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("runs") / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── ① train_w 前（干净 W）四路：train_ctx 冻结 W 训 ctx_wgt ──
    positions = build_positions(train_toks_sub, vocab_idx)
    ro_pre, nnz_pre0, nnz_pre1 = train_ctx_ro(ng, pats, vocab, pats_mat,
                                              positions, "净W")
    res_pre = eval_all(ng, S, pats, vocab, outsum, ev_te, delta_off,
                       "train_w 前", ro=ro_pre)

    # 干净 W 上 grad vs wsum 判定（Phase 2b 主引擎预验证）
    g0, wsum0 = res_pre["avg"]["grad"], res_pre["avg"]["wsum"]
    d_g, z_g = diff_sig(g0, res_pre["n"], wsum0, res_pre["n"])
    print(f"── 干净 W 上 grad-wsum: {d_g:+.4f} z={z_g if z_g is not None else 0:.2f} "
          f"（{'grad 优' if z_g is not None and z_g > 1.96 else '未显著优'}）──", flush=True)
    # 干净 W 中间态保存（train_w 前；以后同类对照直接加载，免重训）
    save_net(ng, vocab, out_dir / "net_clean.npz", ctx_wgt=ro_pre.ctx_wgt)
    print(f"净 W 中间态: {out_dir}/net_clean.npz", flush=True)

    if DO_TRAIN_W:
        # ── ② train_w（同 L1 参数）→ 4d → S 重建 → 四路 ──
        ro_w = GradReadout(ng, pats, vocab, pats_mat, maxlen=MAXLEN)
        ro_w.snapshot_w()
        nnz0 = ro_w.nnz()
        t0 = time.time()
        ro_w.train_w(positions, lr=TRAIN_W_LR, epochs=TRAIN_W_EPOCHS, seed=SEED,
                     subsample=2000)
        ro_w.ctx_wgt = np.clip(ro_w.ctx_wgt, 0.0, None)
        s = float(ro_w.ctx_wgt.sum())
        if s > 0:
            ro_w.ctx_wgt = ro_w.ctx_wgt / s
        t_w = round(time.time() - t0, 1)
        nnz1 = ro_w.nnz()
        wd = ro_w.w_delta()
        print(f"train_w {t_w}s  ctx={np.round(ro_w.ctx_wgt, 4)}", flush=True)
        print(f"4d: nnz {nnz0}→{nnz1}  max_delta={wd['max_delta']} "
              f"改 {wd['n_changed']}/{wd['n_tot']}", flush=True)
        S = build_score_mat(ng, pats, vocab, pats_mat, slot=0)
        ro_post, _, _ = train_ctx_ro(ng, pats, vocab, pats_mat, positions,
                                     "train_w后")
        res_post = eval_all(ng, S, pats, vocab, outsum, ev_te, delta_off,
                            "train_w 后", ro=ro_post)
    else:
        print("── --no-train-w：跳过 train_w（只干净 W 四路定案）──", flush=True)
        res_post = None
        t_w, nnz0, nnz1, wd = 0.0, nnz_pre0, nnz_pre1, None

    # ── 对照输出 ──
    def tbl(r):
        return {k: ({kk: round(vv, 4) for kk, vv in v.items()}
                    if isinstance(v, dict) else v) for k, v in r.items()}

    if DO_TRAIN_W:
        # Q1: train_w 前后（同子集）
        q1 = {e: {"pre": res_pre["avg"][e], "post": res_post["avg"][e],
                  "diff": round(res_post["avg"][e] - res_pre["avg"][e], 4)}
              for e in ("wsum", "trace", "pahe", "grad")}
        # Q2: 纯量 scaling（子集 train_w 后 vs L1-20 万 train_w 后）
        ref = json.loads(Path(L1_REF).read_text(encoding="utf-8")) if Path(L1_REF).exists() else None
        q2 = {}
        if ref:
            for e in ("wsum", "trace", "pahe"):
                r20 = ref["top1"]["avg"][e]
                r2 = res_post["avg"][e]
                d, z = diff_sig(r2, res_post["n"], r20, ref["top1"]["n"]["0"] +
                                ref["top1"]["n"]["1"] + ref["top1"]["n"]["2"] +
                                ref["top1"]["n"]["3"] + ref["top1"]["n"]["4"] +
                                ref["top1"]["n"]["5"])
                q2[e] = {"sub20k": r2, "full200k": r20, "diff": round(d, 4),
                         "z": round(z, 2) if z is not None else None}
        print("\n── Q1 train_w 前后（同子集，同评估）──")
        for e, v in q1.items():
            print(f"  {e}: {v['pre']:.4f} → {v['post']:.4f}  Δ={v['diff']:+.4f}")
        print("── Q2 纯量 scaling（子集 vs 20 万全量，均 train_w 后）──")
        for e, v in q2.items():
            print(f"  {e}: {v['sub20k']:.4f} → {v['full200k']:.4f}  "
                  f"Δ={v['diff']:+.4f} z={v['z']}")
    else:
        q1 = q2 = None
    # Q3: 干净 W（train_w 前）trace 增益（无论是否 train_w 都算）
    w0, tr0 = res_pre["avg"]["wsum"], res_pre["avg"]["trace"]
    d0, z0 = diff_sig(tr0, res_pre["n"], w0, res_pre["n"])
    q3 = {"trace_minus_wsum_clean": round(d0, 4), "z": round(z0, 2) if z0 else None}
    print(f"── Q3 干净 W 上 trace-wsum: {q3['trace_minus_wsum_clean']:+.4f} "
          f"z={q3['z']} ──")

    # ── 留档 ──
    result = {
        "tag": "Phase 2 L1 干净对照：train_w 前后四路 + grad(train_ctx) 主引擎定案",
        "corpus": CORPUS, "sub_n": SUB_N, "eval_n": len(ev_te),
        "delta_off": delta_off,
        "train_w": {"run": DO_TRAIN_W, "epochs": TRAIN_W_EPOCHS, "lr": TRAIN_W_LR,
                    "skip_train_ctx": SKIP_TRAIN_CTX},
        "train_ctx": {"epochs": CTX_EPOCHS, "lr": CTX_LR,
                      "subsample": CTX_SUBSAMPLE},
        "sleep": {"min_wake": round(min_wake, 1), "weakened": weakened,
                  "cleared": cleared},
        "timing": {"hebbian_sec": t_hebb, "train_w_sec": t_w},
        "4d": {"nnz0": nnz0, "nnz1": nnz1,
               "max_delta": wd["max_delta"] if wd else 0.0,
               "n_changed": wd["n_changed"] if wd else 0,
               "n_tot": wd["n_tot"] if wd else 0,
               "train_ctx_zero_perturb": nnz_pre0 == nnz_pre1},
        "top1_pre_train_w": tbl(res_pre),
        "top1_post_train_w": tbl(res_post) if res_post else None,
        "grad_vs_wsum_clean": {"diff": round(d_g, 4),
                               "z": round(z_g, 2) if z_g is not None else None},
        "Q1_train_w_impact": q1,
        "Q2_scaling_sub_vs_full": q2,
        "Q3_trace_clean": q3,
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    save_net(ng, vocab, out_dir / "net.npz",
             ctx_wgt=ro_pre.ctx_wgt if not DO_TRAIN_W else ro_post.ctx_wgt)
    print(f"\n留档: {out_dir}/（net_clean.npz + net.npz + result.json）")


if __name__ == "__main__":
    main()
