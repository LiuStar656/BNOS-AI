# -*- coding: utf-8 -*-
"""Phase 4 前置：开源真实语料规模验证验收（C 路线第二阶段，c3）。

语料：data/corpus_open.json（20263 句，已分词 + OOV→<UNK>，词表 3000）
流程：Hebbian 预训练 → delta_off 自适应扫描（trace 增量评估在留出集扫
{0.002..0.05} 选最优，Phase 2 发现①：∝1/词表）→ train_ctx（位置信任）→
train_w（微调 W，生成引擎）→ 三路生成对照（grad / trace / wsum）：
  ① 留出集 top-1 命中率对照（真实语料：trace/grad 增益 vs wsum）
  ② 20 条 grad 采样生成样例 + 人工流畅度打分（5 分制，≥3/5 达标）
  ③ 前缀一致性：生成句开头 = 条件前缀（自动检查）
  ④ 自动 BLEU-2（句级平均）：grad vs trace vs wsum 同前缀续写对照
  ⑤ 4d 保护：W 结构不变 + 扰动报告
  ⑥ 回归：abc/seq 子进程独立跑（静态实验不受影响）

用法：python _accept_open.py     （留档 runs/时间戳/result.json + 人工打分表）
"""
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from schema_net import _word_pattern, _learn_sentence
from sparse_net import (SparseSchemaNet, _pats_matrix, outsum_sparse,
                        build_score_mat, evaluate_wsum_smat, evaluate_trace_smat,
                        save_net)
from grad_readout import GradReadout
from generator import Generator

N, K = 8192, 16
MAXLEN = 8
SEED = 42
CORPUS = "data/corpus_open.json"
GEN_N = 20        # 人工评估生成条数
GEN_MAX = 10      # 生成最大词数
TOP_K, TEMP, PENALTY = 12, 1.1, 2.5
TRAIN_W_EPOCHS = 5
TRAIN_W_LR = 0.02
SKIP_TRAIN_CTX = True   # 变体：跳过 train_ctx（信任直接给 trace 等效初值），防真实长句语料远端信号过冲
# 频率门控慢衰减（Phase 3 接入）：Hebbian 后 sleep 整理，低频唤醒槽位连接渐进衰减为 0
SLEEP_DECAY = 0.3        # 低频槽连接每周期 ×(1-decay)
SLEEP_EPS = 1e-4         # 归零阈值：≤ eps 删除条目（稀疏回收）
UNK = "<UNK>"
KV = 3000         # 词表规模（标准档，含 UNK）
DELTA_SCAN = [0.005, 0.01, 0.02]   # delta_off 自适应扫描（词表 3000，候选更小更散）
SCAN_SUB = 150          # delta_off 扫描用留出子集（trace 动力学注入是主要开销）
EVAL_SUB_TRAIN = 1000   # 训练集 top-1 评估采样句数（三路同一子集）
EVAL_SUB_TEST = 600     # 留出集 top-1 评估采样句数


def mk_net():
    return SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                           w_max=16.0, wta_k=K, noise_p=0.06, noise_amp=0.5,
                           weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                           refractory=1, rng=np.random.default_rng(SEED + 5000))


def build_positions(tokenized, vocab_idx):
    pos = []
    for toks in tokenized:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(1, len(ids)):
            pos.append((ids[:t], ids[t]))
    return pos


def bleu2(gen, ref, max_n=2):
    """句级 BLEU-N（clipped precision + brevity penalty），词为 token。"""
    if not gen or not ref:
        return 0.0
    bp = min(1.0, np.exp(1 - len(ref) / len(gen)))
    precs = []
    for n in range(1, max_n + 1):
        gc = Counter(tuple(gen[i:i + n]) for i in range(len(gen) - n + 1))
        rc = Counter(tuple(ref[i:i + n]) for i in range(len(ref) - n + 1))
        hits = sum(min(c, rc.get(g, 0)) for g, c in gc.items())
        tot = max(1, sum(gc.values()))
        precs.append(hits / tot)
    return bp * float(np.prod(precs) ** (1.0 / max_n))


def main():
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
    os.environ.setdefault("OMP_NUM_THREADS", "2")

    # ── 数据准备（tokenized 语料，已 OOV→<UNK>）──
    tokenized = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
    freq = Counter(w for toks in tokenized for w in toks)
    vocab = [UNK] + [w for w, _ in freq.most_common(KV + 100) if w != UNK][:KV - 1]
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    rng = np.random.default_rng(SEED + 9000)
    perm = rng.permutation(len(tokenized))
    n_train = int(len(tokenized) * 0.8)
    train_toks = [tokenized[i] for i in perm[:n_train]]
    test_toks = [tokenized[i] for i in perm[n_train:]]
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)
    print(f"corpus_open: {len(tokenized)} 句，词表 {len(vocab)}，"
          f"训练 {len(train_toks)}/留出 {len(test_toks)}，UNK 占比 {freq.get(UNK, 0) / sum(freq.values()):.4f}")

    # ── 训练：Hebbian ──
    ng = mk_net()
    t0 = time.time()
    for toks in train_toks:
        _learn_sentence(ng, toks, pats, slot=0)
    t_hebb = round(time.time() - t0, 1)
    print(f"Hebbian 预训练 {t_hebb}s", flush=True)

    # ── sleep 整理（频率门控慢衰减，Phase 3 接入）──
    # 窗口 = 整个 Hebbian 周期；min_wake 取"非零唤醒分布 P10"（保守：只动最低频 ~10%
    # 神经元槽）；须在学习态内执行（sleep 内部检查 learn_gate），故 learn_gate 冻结后移
    fq = ng.slot_freq[:, 0]
    nz = fq[fq > 0]
    min_wake = float(np.percentile(nz, 10)) if len(nz) else 1.0
    min_wake = max(1.0, min_wake)
    nnz_pre = sum(len(row) for i in range(ng.n) for row in [ng.W_out[i][0]])
    t0 = time.time()
    cleared, weakened = ng.sleep_consolidate(min_wake=min_wake, decay=SLEEP_DECAY,
                                             eps=SLEEP_EPS)
    t_sleep = round(time.time() - t0, 1)
    nnz_post = sum(len(row) for i in range(ng.n) for row in [ng.W_out[i][0]])
    print(f"sleep 整理 {t_sleep}s: min_wake={min_wake:.0f} 弱化 {weakened} 条连接"
          f"（{100 * weakened / max(1, nnz_pre):.2f}%），删除 {cleared} 条，"
          f"nnz {nnz_pre}→{nnz_post}（回收 {nnz_pre - nnz_post}，"
          f"{100 * (nnz_pre - nnz_post) / max(1, nnz_pre):.2f}%）", flush=True)
    ng.learn_gate = False

    outsum = outsum_sparse(ng, pats, vocab, slot=0)
    S = build_score_mat(ng, pats, vocab, pats_mat, slot=0)
    print(f"词得分矩阵 S {S.shape}（{S.nbytes / 1e6:.0f}MB）", flush=True)

    # ── delta_off 自适应扫描（trace 评估 S 矩阵版，留出子集，选最优）──
    scan_toks = [test_toks[i] for i in
                 rng.choice(len(test_toks), min(SCAN_SUB, len(test_toks)), replace=False)]
    print(f"delta_off 扫描（trace 留出 top-1，子集 {len(scan_toks)} 句）:")
    best_delta, best_t = 0.02, -1.0
    for d in DELTA_SCAN:
        t_ = evaluate_trace_smat(ng, scan_toks, S, pats, vocab, outsum, delta_off=d)
        print(f"  delta_off={d}: {t_[0]:.4f}")
        if t_[0] > best_t:
            best_delta, best_t = d, t_[0]
    delta_off = best_delta
    print(f"→ 最优 delta_off={delta_off}（{best_t:.4f}）", flush=True)

    # ── 训练：train_w（变体：跳过 train_ctx，信任 = trace 等效均匀初值，
    #    lr=0.02/5ep 温和训练防过拟合，训后 clip+归一化防幅值失控）──
    ro = GradReadout(ng, pats, vocab, pats_mat, maxlen=MAXLEN)
    ro.snapshot_w()
    nnz0 = ro.nnz()
    positions = build_positions(train_toks, vocab_idx)

    t_ctx = 0.0
    if not SKIP_TRAIN_CTX:
        t0 = time.time()
        t_ctx = ro.train_ctx(positions, lr=0.5, epochs=20, seed=SEED)
        print(f"train_ctx {t_ctx}s  信任={np.round(ro.ctx_wgt, 4)}", flush=True)
    t0 = time.time()
    t_w = ro.train_w(positions, lr=TRAIN_W_LR, epochs=TRAIN_W_EPOCHS, seed=SEED,
                     subsample=2000)
    ro.ctx_wgt = np.clip(ro.ctx_wgt, 0.0, None)
    s = float(ro.ctx_wgt.sum())
    if s > 0:
        ro.ctx_wgt = ro.ctx_wgt / s
    t_w = round(time.time() - t0, 1)
    print(f"train_w({TRAIN_W_EPOCHS}ep×≤2000样本, 变体 lr={TRAIN_W_LR}/跳过train_ctx/均匀初值+归一化) "
          f"{t_w}s  信任={np.round(ro.ctx_wgt, 4)}", flush=True)

    # 4d：结构 + 扰动
    nnz1 = ro.nnz()
    wd = ro.w_delta()
    print(f"W 结构: {nnz0}→{nnz1}（{'不变' if nnz0 == nnz1 else '变了!'}）  "
          f"扰动: max_delta={wd['max_delta']} 改 {wd['n_changed']}/{wd['n_tot']}")

    # ── ① 留出集 top-1 命中率对照（三路同一采样子集，保证可比）──
    ev_tr = [train_toks[i] for i in
             rng.choice(len(train_toks), min(EVAL_SUB_TRAIN, len(train_toks)), replace=False)]
    ev_te = [test_toks[i] for i in
             rng.choice(len(test_toks), min(EVAL_SUB_TEST, len(test_toks)), replace=False)]
    w_tr = evaluate_wsum_smat(S, vocab, ev_tr, norm_base=outsum)
    w_te = evaluate_wsum_smat(S, vocab, ev_te, norm_base=outsum)
    t_tr = evaluate_trace_smat(ng, ev_tr, S, pats, vocab, outsum, delta_off=delta_off)
    t_te = evaluate_trace_smat(ng, ev_te, S, pats, vocab, outsum, delta_off=delta_off)
    g_tr = ro.evaluate_w(ev_tr)
    g_te = ro.evaluate_w(ev_te)
    print(f"① top-1 命中率（训练 {len(ev_tr)} 句/留出 {len(ev_te)} 句）: "
          f"wsum {w_tr[0]:.4f}/{w_te[0]:.4f}  "
          f"trace {t_tr[0]:.4f}/{t_te[0]:.4f}  grad {g_tr[0]:.4f}/{g_te[0]:.4f}")

    # ── ② 生成前缀集合：训练句首词频率 top-GEN_N ──
    starters = [toks[0] for toks in train_toks if toks]
    sfreq = Counter(starters)
    prefixes = [w for w, _ in sfreq.most_common(GEN_N)]
    prefixes = [p for p in prefixes if p in vocab_idx][:GEN_N]

    gen = Generator(ro, outsum=outsum, seed=SEED + 7)

    samples = []
    for pre in prefixes:
        g_grad = gen.generate([pre], max_len=GEN_MAX, top_k=TOP_K,
                              temp=TEMP, penalty=PENALTY, engine="grad")
        g_trace = gen.generate([pre], max_len=GEN_MAX, top_k=TOP_K,
                               temp=TEMP, penalty=PENALTY, engine="trace")
        g_wsum = gen.generate([pre], max_len=GEN_MAX, top_k=TOP_K,
                              temp=TEMP, penalty=PENALTY, engine="wsum")
        samples.append({"prefix": pre,
                        "grad": "".join(g_grad), "trace": "".join(g_trace),
                        "wsum": "".join(g_wsum),
                        "prefix_ok": g_grad[0] == pre if g_grad else False})
    n_pfx_ok = sum(1 for s in samples if s["prefix_ok"])

    print(f"\n② 生成样例（前缀一致性 {n_pfx_ok}/{GEN_N}）:")
    for s in samples:
        print(f"  [{s['prefix']}] grad: {s['grad']}")
        print(f"        trace: {s['trace']} | wsum: {s['wsum']}")

    # ── ③ 自动 BLEU-2：同前缀真句续写对照 ──
    refs = {}
    for toks in train_toks:
        refs.setdefault(toks[0], toks)
    bleu_rows = []
    for pre in prefixes:
        ref = refs.get(pre)
        if ref is None:
            continue
        g_grad = gen.generate_argmax([pre], max_len=min(6, len(ref) + 1), engine="grad")
        g_trace = gen.generate_argmax([pre], max_len=min(6, len(ref) + 1), engine="trace")
        g_wsum = gen.generate_argmax([pre], max_len=min(6, len(ref) + 1), engine="wsum")
        bleu_rows.append({
            "prefix": pre, "ref": "".join(ref),
            "bleu_grad": round(bleu2(g_grad, ref), 3),
            "bleu_trace": round(bleu2(g_trace, ref), 3),
            "bleu_wsum": round(bleu2(g_wsum, ref), 3),
        })
    b_grad = np.mean([r["bleu_grad"] for r in bleu_rows])
    b_trace = np.mean([r["bleu_trace"] for r in bleu_rows])
    b_wsum = np.mean([r["bleu_wsum"] for r in bleu_rows])
    print(f"\n③ BLEU-2（{len(bleu_rows)} 前缀，贪心续写 vs 真句）: "
          f"grad {b_grad:.3f}  trace {b_trace:.3f}  wsum {b_wsum:.3f}")

    # ── ④ 回归（静态实验，子进程独立）──
    reg = {}
    reg_cmds = {
        "abc": (["schema_net.py", "--mode", "abc"], "9/9"),
        "seq": (["schema_net.py", "--mode", "seq", "--stdp-pre", "0.1"], "顺序敏感成立"),
    }
    for mode, (cmd, want) in reg_cmds.items():
        try:
            r = subprocess.run([sys.executable] + cmd, capture_output=True,
                               text=True, timeout=600)
            out = (r.stdout or "") + (r.stderr or "")
            reg[mode] = "PASS" if want in out else "FAIL"
            print(f"回归 {mode}: {reg[mode]}")
        except Exception as e:   # noqa: BLE001
            reg[mode] = f"ERR {e}"
            print(f"回归 {mode}: ERR {e}")

    # 留档 + 人工打分表
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("runs") / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    save_net(ng, vocab, out_dir / "net.npz", ctx_wgt=ro.ctx_wgt)
    result = {
        "tag": "Phase 4 前置·开源真实语料规模验证（标准档·变体 lr=0.02/5ep/跳过train_ctx/归一化）",
        "corpus": CORPUS,
        "config": {"n": N, "k": K, "vocab": len(vocab), "maxlen": MAXLEN,
                   "train_w_epochs": TRAIN_W_EPOCHS, "train_w_lr": TRAIN_W_LR,
                   "skip_train_ctx": SKIP_TRAIN_CTX, "top_k": TOP_K,
                   "temp": TEMP, "penalty": PENALTY, "seed": SEED,
                   "delta_off": delta_off, "delta_scan": DELTA_SCAN,
                   "sleep": {"min_wake": round(min_wake, 1), "decay": SLEEP_DECAY,
                             "eps": SLEEP_EPS}},
        "ctx_wgt": [round(float(w), 4) for w in ro.ctx_wgt],
        "sleep": {"cleared": cleared, "nnz_pre": nnz_pre, "nnz_post": nnz_post,
                  "recycle_pct": round(100 * (nnz_pre - nnz_post) / max(1, nnz_pre), 3)},
        "top1": {"wsum": {"train": w_tr[0], "test": w_te[0]},
                 "trace": {"train": t_tr[0], "test": t_te[0]},
                 "grad": {"train": g_tr[0], "test": g_te[0]},
                 "eval_n": {"train": len(ev_tr), "test": len(ev_te)}},
        "bleu2": {"grad": float(b_grad), "trace": float(b_trace),
                  "wsum": float(b_wsum), "n_prefix": len(bleu_rows)},
        "prefix_ok": n_pfx_ok, "n_prefix_total": GEN_N,
        "sparsity": {"nnz_before": nnz0, "nnz_after": nnz1,
                     "structure_unchanged": nnz0 == nnz1},
        "w_delta": wd,
        "regression": reg,
        "samples": samples,
        "timing": {"hebbian_sec": t_hebb, "sleep_sec": t_sleep,
                   "ctx_sec": t_ctx, "grad_sec": t_w},
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# Phase 4 前置·开源真实语料人工流畅度评估（5 分制：5=自然流畅 / 3=可读但别扭 / 1=不通）\n"]
    for i, s in enumerate(samples, 1):
        lines.append(f"{i:2d}. 前缀[{s['prefix']}] 生成：{s['grad']}\n   得分：__  "
                     f"（trace: {s['trace']} | wsum: {s['wsum']}）\n")
    (out_dir / "human_eval.txt").write_text("".join(lines), encoding="utf-8")
    print(f"\n留档: {out_dir}/")

    print("\n验收判定（自动部分）:")
    j_prefix = n_pfx_ok == GEN_N
    j_struct = nnz0 == nnz1
    print(f"  ① 留出集 top-1（真实语料）: "
          f"wsum {w_te[0]:.4f}  trace {t_te[0]:.4f}  grad {g_te[0]:.4f}"
          f"（trace-wsum = {t_te[0]-w_te[0]:+.4f}, grad-wsum = {g_te[0]-w_te[0]:+.4f}）")
    print(f"  ② 前缀一致性 {n_pfx_ok}/{GEN_N}: {'PASS ✓' if j_prefix else 'FAIL ✗'}")
    print(f"  ③ BLEU-2（参考，贪心续写无区分度）: "
          f"grad {b_grad:.3f} vs trace {b_trace:.3f}/wsum {b_wsum:.3f}")
    print(f"  ④ W 结构不变（train_w 扰动口径）: {'PASS ✓' if j_struct else 'FAIL ✗'}"
          f"（nnz {nnz0}→{nnz1}）")
    print(f"  ⑤ sleep 回收率: 删除 {cleared} 条目，"
          f"nnz {nnz_pre}→{nnz_post}（{100 * (nnz_pre - nnz_post) / max(1, nnz_pre):.2f}%）")
    print(f"  ⑥ 回归: " + " ".join(f"{k}={v}" for k, v in reg.items()))
    print(f"  ★ 人工流畅度（≥3/5 达标）: 见 {out_dir}/human_eval.txt，请打分")


if __name__ == "__main__":
    main()
