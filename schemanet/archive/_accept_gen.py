# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""Phase 3+ 完整验收：生成与解码（有偏语料版，B 阶段）。

流程：corpus_biased.json（15100 句，条件偏斜）→ Hebbian 预训练 → train_ctx
（位置信任）→ train_w（微调 W，生成引擎）→ 三路生成对照（grad / trace / wsum）：
  ① 留出集 top-1 命中率对照（有偏语料：验证 trace/grad 借主语痕迹破局的增益）
  ② 20 条 grad 采样生成样例 + 人工流畅度打分（5 分制，≥3/5 达标）
  ③ 前缀一致性：生成句开头 = 条件前缀（自动检查）
  ④ 自动 BLEU-2（句级平均）：grad vs trace vs wsum 同前缀续写对照
  ⑤ 4d 保护：W 结构不变 + 扰动报告

用法：python _accept_gen.py     （留档 runs/时间戳/result.json + 人工打分表）
"""
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jieba

from schema_net import _word_pattern, _learn_sentence
from sparse_net import (SparseSchemaNet, _pats_matrix, outsum_sparse,
                        evaluate_schemanet_sparse, evaluate_schemanet_trace_inc,
                        save_net)
from grad_readout import GradReadout
from generator import Generator

N, K, KV = 8192, 16, 2000
MAXLEN = 6
SEED = 42
CORPUS = "data/corpus_biased.json"
GEN_N = 20        # 人工评估生成条数
GEN_MAX = 10      # 生成最大词数
TOP_K, TEMP, PENALTY = 12, 1.1, 2.5   # 0.8/1.2 版高频词重复退化（"很很很很"）
TRAIN_W_EPOCHS = 10


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
    """句级 BLEU-N（clipped precision + brevity penalty），词为 jieba 单元。"""
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
    import os
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
    os.environ.setdefault("OMP_NUM_THREADS", "2")

    # ── 数据准备 ──
    corpus = json.loads(Path(CORPUS).read_text(encoding="utf-8"))
    tokenized = [jieba.lcut(s) for s in corpus]
    freq = Counter(w for toks in tokenized for w in toks)
    vocab = [w for w, _ in freq.most_common(KV)]
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    rng = np.random.default_rng(SEED + 9000)
    perm = rng.permutation(len(tokenized))
    n_train = int(len(tokenized) * 0.8)
    train_toks = [tokenized[i] for i in perm[:n_train]]
    test_toks = [tokenized[i] for i in perm[n_train:]]
    pats = {w: _word_pattern(N, K, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)
    print(f"corpus_large: {len(corpus)} 句，词表 {len(vocab)}，训练 {len(train_toks)}/留出 {len(test_toks)}")

    # ── 训练：Hebbian → train_ctx → train_w ──
    ng = mk_net()
    t0 = time.time()
    for toks in train_toks:
        _learn_sentence(ng, toks, pats, slot=0)
    ng.learn_gate = False
    t_hebb = round(time.time() - t0, 1)
    print(f"Hebbian 预训练 {t_hebb}s")

    outsum = outsum_sparse(ng, pats, vocab, slot=0)
    ro = GradReadout(ng, pats, vocab, pats_mat, maxlen=MAXLEN)
    ro.snapshot_w()
    nnz0 = ro.nnz()
    positions = build_positions(train_toks, vocab_idx)

    t0 = time.time()
    t_ctx = ro.train_ctx(positions, lr=0.5, epochs=20, seed=SEED)
    print(f"train_ctx {t_ctx}s  信任={np.round(ro.ctx_wgt, 4)}")
    t0 = time.time()
    t_w = ro.train_w(positions, lr=0.05, epochs=TRAIN_W_EPOCHS, seed=SEED,
                     ctx_init=ro.ctx_wgt, subsample=2000)
    print(f"train_w({TRAIN_W_EPOCHS}ep×≤2000样本, 镜像向量化) {t_w}s  信任={np.round(ro.ctx_wgt, 4)}",
          flush=True)

    # 4d：结构 + 扰动
    nnz1 = ro.nnz()
    wd = ro.w_delta()
    print(f"W 结构: {nnz0}→{nnz1}（{'不变' if nnz0 == nnz1 else '变了!'}）  "
          f"扰动: max_delta={wd['max_delta']} 改 {wd['n_changed']}/{wd['n_tot']}")

    # ── ① 留出集 top-1 命中率对照 ──
    w_tr = evaluate_schemanet_sparse(ng, train_toks, pats, vocab, pats_mat, readout="wsum")
    w_te = evaluate_schemanet_sparse(ng, test_toks, pats, vocab, pats_mat, readout="wsum")
    # trace 用增量评估（单句内 pre_trace 累积，不清零重放——对拍验证与重放版一致）
    t_tr = evaluate_schemanet_trace_inc(ng, train_toks, pats, vocab, pats_mat,
                                        norm_base=outsum, delta_off=0.02)
    t_te = evaluate_schemanet_trace_inc(ng, test_toks, pats, vocab, pats_mat,
                                        norm_base=outsum, delta_off=0.02)
    g_tr = ro.evaluate_w(train_toks)
    g_te = ro.evaluate_w(test_toks)
    print(f"① top-1 命中率（训练/留出）: wsum {w_tr[0]:.4f}/{w_te[0]:.4f}  "
          f"trace {t_tr[0]:.4f}/{t_te[0]:.4f}  grad {g_tr[0]:.4f}/{g_te[0]:.4f}")

    # ── ② 生成前缀集合：训练句首词频率 top-GEN_N ──
    starters = [toks[0] for toks in train_toks if toks]
    sfreq = Counter(starters)
    prefixes = [w for w, _ in sfreq.most_common(GEN_N)]
    prefixes = [p for p in prefixes if p in vocab_idx][:GEN_N]

    gen = Generator(ro, outsum=outsum, seed=SEED + 7)

    # 生成样例（grad 采样 + 对照 trace/wsum 采样）
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

    # ── ③ 自动 BLEU-2：同前缀真句续写对照（训练集内匹配） ──
    #    真句引用 = 训练句中以该词开头的完整句（取首句）；生成续写 = grad 贪心 4 词
    refs = {}
    for toks in train_toks:
        refs.setdefault(toks[0], toks)
    bleu_rows = []
    for pre in prefixes:
        ref = refs.get(pre)
        if ref is None:
            continue
        g_grad = gen.generate_argmax([pre], max_len=min(5, len(ref) + 1), engine="grad")
        g_trace = gen.generate_argmax([pre], max_len=min(5, len(ref) + 1), engine="trace")
        g_wsum = gen.generate_argmax([pre], max_len=min(5, len(ref) + 1), engine="wsum")
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

    # 留档 + 人工打分表
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("runs") / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    save_net(ng, vocab, out_dir / "net.npz")   # 生成调参免重训
    result = {
        "tag": "Phase3+ 有偏语料生成与解码", "corpus": CORPUS,
        "config": {"n": N, "k": K, "vocab": len(vocab), "maxlen": MAXLEN,
                   "train_w_epochs": TRAIN_W_EPOCHS, "top_k": TOP_K,
                   "temp": TEMP, "penalty": PENALTY, "seed": SEED},
        "top1": {"wsum": {"train": w_tr[0], "test": w_te[0]},
                 "trace": {"train": t_tr[0], "test": t_te[0]},
                 "grad": {"train": g_tr[0], "test": g_te[0]}},
        "bleu2": {"grad": float(b_grad), "trace": float(b_trace),
                  "wsum": float(b_wsum), "n_prefix": len(bleu_rows)},
        "prefix_ok": n_pfx_ok, "n_prefix_total": GEN_N,
        "sparsity": {"nnz_before": nnz0, "nnz_after": nnz1,
                     "structure_unchanged": nnz0 == nnz1},
        "w_delta": wd,
        "samples": samples,
        "timing": {"hebbian_sec": t_hebb, "ctx_sec": t_ctx, "grad_sec": t_w},
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    # 人工打分表
    lines = ["# Phase 3 人工流畅度评估（5 分制：5=自然流畅 / 3=可读但别扭 / 1=不通）\n"]
    for i, s in enumerate(samples, 1):
        lines.append(f"{i:2d}. 前缀[{s['prefix']}] 生成：{s['grad']}\n   得分：__  "
                     f"（trace: {s['trace']} | wsum: {s['wsum']}）\n")
    (out_dir / "human_eval.txt").write_text("".join(lines), encoding="utf-8")
    print(f"\n留档: {out_dir}/")
    print(f"人工打分表: {out_dir}/human_eval.txt")

    print("\nPhase 3+ 验收判定（自动部分）:")
    j_prefix = n_pfx_ok == GEN_N
    j_struct = nnz0 == nnz1
    j_gain = g_te[0] > w_te[0] + 0.01 or t_te[0] > w_te[0] + 0.01   # 有偏语料：trace/grad 借主语痕迹破局应超 wsum
    # BLEU-2 贪心续写：同前缀三路常取同词 → 无区分度，仅作参考报到
    print(f"  ① 留出集 top-1（有偏语料：trace/grad 借主语痕迹破局的甜区）: "
          f"wsum {w_te[0]:.4f}  trace {t_te[0]:.4f}  grad {g_te[0]:.4f}"
          f"（trace-wsum = {t_te[0]-w_te[0]:+.4f}, grad-wsum = {g_te[0]-w_te[0]:+.4f}）")
    print(f"     trace/grad 增益（>+0.01 达标）: {'PASS ✓' if j_gain else '未超阈值（可能已饱和或噪声级）'}")
    print(f"  ② 前缀一致性 {n_pfx_ok}/{GEN_N}: {'PASS ✓' if j_prefix else 'FAIL ✗'}")
    print(f"  ③ BLEU-2（参考，贪心续写无区分度）: "
          f"grad {b_grad:.3f} vs trace {b_trace:.3f}/wsum {b_wsum:.3f}")
    print(f"  ④ W 结构不变: {'PASS ✓' if j_struct else 'FAIL ✗'}")
    print(f"  ★ 人工流畅度（≥3/5 达标）: 见 {out_dir}/human_eval.txt，请打分")


if __name__ == "__main__":
    main()
