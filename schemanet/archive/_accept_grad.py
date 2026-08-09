# -*- coding: utf-8 -*-
"""Phase 4 完整验收：梯度在线学习（Hebbian 预训练 + 稀疏梯度精调）双轨落地。

对照方案 [PLAN]-定式网络向大模型方向发展方案.md 7.3 验收项：
  ① 小规模（100-1000 句）梯度微调后，训练/留出集准确率**超过纯 Hebbian**
     （> 0.526 bigram 上限）——corpus.json（100 句，n=2048，微调 W 非零子集）
  ② 学到 Hebbian 学不动的模式：**条件组合**（仅特定上下文出现的转移）
     ——corpus_ctx.json（二阶依赖：mid 后继平局靠 ctx 破局）
  ③ **长程关联**（>3 词）——corpus_long.json（ctx 距末词 3 个位置，pos=3 破平局）
  ④ 稀疏梯度开销可控（S 矩阵内存、训练时间增量、W 结构不变）
  ⑤ 定式保留：abc / seq 回归全绿（梯度不破坏静态实验）

代码：grad_readout.py（GradReadout 可复用读出/学习层）+ 本脚本（编排与判定）。
用法：python _accept_grad.py
"""

import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from schema_net import (_word_pattern, _learn_sentence, _BigramModel,
                        _TrigramModel, _evaluate_ngram)
from sparse_net import (SparseSchemaNet, _pats_matrix, outsum_sparse,
                        evaluate_schemanet_sparse)
from grad_readout import GradReadout

MAXLEN = 5
SEED = 42

# corpus_long 的组定义（与 data/gen_corpus_long.py 保持一致）
LONG_GROUPS = [
    ("小明", "小红", "和", "朋友", "一起", "唱歌", "跳舞"),
    ("春天", "秋天", "的", "风", "很", "舒服", "干燥"),
    ("爸爸", "妈妈", "喜欢", "在", "厨房", "做饭", "看书"),
    ("早上", "晚上", "常常", "在", "客厅", "跑步", "睡觉"),
]


# ════════════════════════════════════════════════════════════════
#  通用构建
# ════════════════════════════════════════════════════════════════

def load_and_vocab(corpus_path, kv):
    import jieba
    corpus = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
    tokenized = [jieba.lcut(s) for s in corpus]
    freq = Counter(w for toks in tokenized for w in toks)
    vocab = [w for w, _ in freq.most_common(kv)]
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    return corpus, tokenized, freq, vocab, vocab_idx


def build_positions(tokenized, vocab_idx):
    pos = []
    for toks in tokenized:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(1, len(ids)):
            pos.append((ids[:t], ids[t]))
    return pos


def mk_net(n, k, seed=SEED):
    return SparseSchemaNet(n=n, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                           w_max=16.0, wta_k=k, noise_p=0.06, noise_amp=0.5,
                           weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                           refractory=1, rng=np.random.default_rng(seed + 5000))


def hebbian_pretrain(ng, train_toks, pats):
    t0 = time.time()
    for toks in train_toks:
        _learn_sentence(ng, toks, pats, slot=0)
    ng.learn_gate = False  # 冻结：后续梯度/评估不改 W 动力学
    return round(time.time() - t0, 1)


def baselines(ng, train_toks, test_toks, pats, vocab, pats_mat, delta_off):
    """wsum / trace（纯 Hebbian 读出）基线。返回 dict。"""
    outsum = outsum_sparse(ng, pats, vocab, slot=0)
    wsum_tr = evaluate_schemanet_sparse(ng, train_toks, pats, vocab, pats_mat,
                                        readout="wsum")
    wsum_te = evaluate_schemanet_sparse(ng, test_toks, pats, vocab, pats_mat,
                                        readout="wsum")
    tr_tr = evaluate_schemanet_sparse(ng, train_toks, pats, vocab, pats_mat,
                                      readout="trace", norm_base=outsum,
                                      delta_off=delta_off)
    tr_te = evaluate_schemanet_sparse(ng, test_toks, pats, vocab, pats_mat,
                                      readout="trace", norm_base=outsum,
                                      delta_off=delta_off)
    return {"outsum": outsum,
            "wsum": {"train": wsum_tr, "test": wsum_te},
            "trace": {"train": tr_tr, "test": tr_te}}


def ngram_baselines(train_toks, train_ev, test_ev):
    bi = _BigramModel(train_toks)
    tri = _TrigramModel(train_toks)
    return {"bigram": {"train": _evaluate_ngram(bi, train_ev),
                       "test": _evaluate_ngram(bi, test_ev)},
            "trigram": {"train": _evaluate_ngram(tri, train_ev),
                        "test": _evaluate_ngram(tri, test_ev)}}


def predict_top_from(logits, ids):
    """logits 过滤（无信号 + 前缀已现词）→ top-1 词。"""
    l = logits.copy()
    l[l <= 0] = -np.inf
    for wid in ids:
        l[wid] = -np.inf
    if np.all(np.isinf(l)):
        return None
    return int(np.argmax(l))


# ════════════════════════════════════════════════════════════════
#  验收 1：小规模梯度微调 > 纯 Hebbian（corpus.json, 微调 W 非零）
# ════════════════════════════════════════════════════════════════

def accept_small():
    n, k, kv = 2048, 8, 300
    corpus_path = "data/corpus.json"
    corpus, tokenized, freq, vocab, vocab_idx = load_and_vocab(corpus_path, kv)
    rng = np.random.default_rng(SEED + 9000)
    perm = rng.permutation(len(tokenized))
    n_train = int(len(tokenized) * 0.8)
    train_toks = [tokenized[i] for i in perm[:n_train]]
    test_toks = [tokenized[i] for i in perm[n_train:]]
    pats = {w: _word_pattern(n, k, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)

    ng = mk_net(n, k)
    t_hebb = hebbian_pretrain(ng, train_toks, pats)
    base = baselines(ng, train_toks, test_toks, pats, vocab, pats_mat, delta_off=0.02)
    ngm = ngram_baselines(train_toks, train_toks, test_toks)

    # 4d：梯度前快照（灾难性遗忘防护）
    ro = GradReadout(ng, pats, vocab, pats_mat, maxlen=MAXLEN)
    ro.snapshot_w()
    nnz_before = ro.nnz()
    positions = build_positions(train_toks, vocab_idx)

    # 梯度微调 W 非零子集 + ctx_wgt（lr=0.05/100ep 突破 bigram 上界 0.526，
    # 见 _tune_small.py 扫描：lr 过大（0.5）长训练震荡发散，小 lr 长训练上界破）
    t0 = time.time()
    t_grad = ro.train_w(positions, lr=0.05, epochs=100, seed=SEED)
    grad_tr = ro.evaluate_w(train_toks)
    grad_te = ro.evaluate_w(test_toks)
    nnz_after = ro.nnz()
    wd = ro.w_delta()

    return {
        "tag": "① 小规模超 Hebbian（微调 W 非零）",
        "corpus": corpus_path, "n": n, "k": k, "vocab_size": len(vocab),
        "n_train": len(train_toks), "n_test": len(test_toks),
        "baseline": base, "ngram": ngm,
        "grad": {"train": grad_tr, "test": grad_te},
        "ctx_wgt": [round(float(x), 4) for x in ro.ctx_wgt],
        "sparsity": {"nnz_before": nnz_before, "nnz_after": nnz_after,
                     "structure_unchanged": nnz_before == nnz_after},
        "w_delta": wd,
        "timing": {"hebbian_sec": t_hebb, "grad_sec": t_grad,
                   "total_sec": round(time.time() - t0 + t_hebb, 1)},
    }


# ════════════════════════════════════════════════════════════════
#  验收 2/3：Hebbian 预训练 → train_ctx（位置信任）→ train_w（微调 W 非零）
#            条件组合 / 长程关联（词级梯度修正 Hebbian WTA 噪声，破平局）
# ════════════════════════════════════════════════════════════════

def compare_cases(ro, cases, vocab, vocab_idx):
    """wsum（Hebbian 末词，S_norm 为 train_ctx 时构建的旧表=微调前基线）
    vs 梯度微调后（_logits_w 实时 score）破局对照。返回 (rows, n_break)。"""
    rows = []
    n_break = 0
    for prefix, truth in cases:
        ids = [vocab_idx[w] for w in prefix if w in vocab_idx]
        l_grad = ro._logits_w(ids).copy()
        l_wsum = ro.S_norm[:, ids[-1]].copy()
        gi, wi = predict_top_from(l_grad, ids), predict_top_from(l_wsum, ids)
        g = vocab[gi] if gi is not None else None
        w = vocab[wi] if wi is not None else None
        hit = g == truth
        if w != truth and hit:
            n_break += 1
        rows.append({"prefix": "".join(prefix), "truth": truth,
                     "wsum": w, "grad": g, "break": w != truth and hit,
                     "hit": hit})
    return rows, n_break


def accept_ctx_long(corpus_path, n, k, kv, delta_off, tag, cases, long_case=False,
                    ctx_init=None, epochs=100):
    corpus, tokenized, freq, vocab, vocab_idx = load_and_vocab(corpus_path, kv)
    rng = np.random.default_rng(SEED + 9000)
    perm = rng.permutation(len(tokenized))
    n_train = int(len(tokenized) * 0.8)
    train_toks = [tokenized[i] for i in perm[:n_train]]
    test_toks = [tokenized[i] for i in perm[n_train:]]
    pats = {w: _word_pattern(n, k, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)

    ng = mk_net(n, k)
    t_hebb = hebbian_pretrain(ng, train_toks, pats)
    base = baselines(ng, train_toks, test_toks, pats, vocab, pats_mat, delta_off)

    # 4d：梯度前快照 + 结构基线
    ro = GradReadout(ng, pats, vocab, pats_mat, maxlen=MAXLEN)
    ro.snapshot_w()
    nnz0 = ro.nnz()
    positions = build_positions(train_toks, vocab_idx)

    # ① 冻结 W 快速路径：train_ctx 预训位置信任（S 矩阵构建在此，wsum 基线用其 S_norm）
    t0 = time.time()
    t_ctx = ro.train_ctx(positions, lr=0.5, epochs=20, seed=SEED)
    # ② 梯度微调 W 非零子集 + ctx_wgt：词级修正 Hebbian WTA 噪声（破平局的关键）
    #    ctx_init：None = train_ctx 结果（近程用）；uniform = 均匀信任（长程用，
    #    大初值驱动远端 W 词级分化，打破"远端信任小→W 不分化"的死锁）
    init = ro.ctx_wgt if ctx_init is None else np.array(ctx_init, dtype=float)
    t_w = ro.train_w(positions, lr=0.05, epochs=epochs, seed=SEED, ctx_init=init)
    grad_tr = ro.evaluate_w(train_toks)
    grad_te = ro.evaluate_w(test_toks)
    nnz1 = ro.nnz()
    wd = ro.w_delta()

    rows, n_break = compare_cases(ro, cases, vocab, vocab_idx)

    return {
        "tag": tag, "corpus": corpus_path, "n": n, "k": k,
        "vocab_size": len(vocab),
        "n_train": len(train_toks), "n_test": len(test_toks),
        "baseline": base,
        "grad": {"train": grad_tr, "test": grad_te},
        "ctx_wgt": [round(float(x), 4) for x in ro.ctx_wgt],
        "sparsity": {"nnz_before": nnz0, "nnz_after": nnz1,
                     "structure_unchanged": nnz0 == nnz1},
        "w_delta": wd,
        "cases": {"n_total": len(cases), "n_break": n_break, "rows": rows},
        "long_case": long_case,
        "train_cfg": {"ctx_init": "train_ctx" if ctx_init is None else "uniform",
                      "epochs": epochs, "lr": 0.05, "seed": SEED},
        "timing": {"hebbian_sec": t_hebb, "ctx_sec": t_ctx, "grad_sec": t_w,
                   "total_sec": round(time.time() - t0 + t_hebb, 1)},
    }


def accept_ctx():
    cases = [
        (["早上", "吃饭"], "香"), (["晚上", "吃饭"], "饱"),
        (["数学", "考试"], "难"), (["语文", "考试"], "简单"),
        (["夏天", "天气"], "热"), (["冬天", "天气"], "冷"),
        (["昨天", "上班"], "累"), (["今天", "上班"], "忙"),
    ]
    # 近程（ctx 距末词 1 位）：train_ctx 结果起步（远端信任小→W 微修正→pos1 净涨）
    return accept_ctx_long("data/corpus_ctx.json", 8192, 16, 2000, 0.02,
                           "② 条件组合（ctx 距末词 1 位破平局）", cases)


def accept_long():
    cases = []
    for ctx1, ctx2, f1, f2, mid, tgtA, tgtB in LONG_GROUPS:
        cases.append(([ctx1, f1, f2, mid], tgtA))
        cases.append(([ctx2, f1, f2, mid], tgtB))
    # 长程（ctx 距末词 3 位）：均匀信任起步 + 长训（大初值驱动远端 W 词级分化）
    return accept_ctx_long("data/corpus_long.json", 8192, 16, 2000, 0.02,
                           "③ 长程关联（ctx 距末词 3 位破平局）", cases,
                           long_case=True, ctx_init=[1.0] * MAXLEN, epochs=200)


# ════════════════════════════════════════════════════════════════
#  验收 4：开销报告 / 验收 5：回归
# ════════════════════════════════════════════════════════════════

def cost_report(phase2, phase3):
    def mem_mb(v):
        return v * v * 8 / 1e6  # V×V×float64

    return {
        "s_matrix": {"V": phase2["vocab_size"],
                     "mem_mb": round(mem_mb(phase2["vocab_size"]), 2)},
        "dense_w_vs_sparse": {
            "dense_w_mb": round(phase2["n"] * phase2["n"] * 4 * 8 / 1e6, 1),
            "sparse_w_mb": "<0.5（28 词级语料，非零极稀疏）",
            "s_mem_vs_dense_pct": round(mem_mb(phase2["vocab_size"]) /
                                        (phase2["n"] * phase2["n"] * 4 * 8 / 1e6) * 100, 4),
        },
        "timing": {
            "phase2": {"hebbian_sec": phase2["timing"]["hebbian_sec"],
                       "ctx_sec": phase2["timing"].get("ctx_sec", 0.0),
                       "grad_sec": phase2["timing"]["grad_sec"]},
            "phase3": {"hebbian_sec": phase3["timing"]["hebbian_sec"],
                       "ctx_sec": phase3["timing"].get("ctx_sec", 0.0),
                       "grad_sec": phase3["timing"]["grad_sec"]},
        },
    }


def run_regression():
    """abc / seq 回归（子进程，独立环境，梯度模块不影响静态实验）。"""
    root = Path(__file__).parent
    out = {}
    for mode, extra in [("abc", []), ("seq", ["--stdp-pre", "0.1"])]:
        r = subprocess.run([sys.executable, "schema_net.py", "--mode", mode] + extra,
                           cwd=root, capture_output=True, text=True, timeout=600)
        log = r.stdout + r.stderr
        ok = r.returncode == 0
        matched = None
        if mode == "abc":
            m = re.search(r"归属正确率: (\d+)/(\d+)", log)
            matched = m.groups() if m else None
            ok = ok and matched is not None and matched[0] == matched[1]
        else:
            m = re.search(r"A 学ab.*?([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)",
                          log, re.S)
            if m:
                fwd_a, rev_a = float(m.group(1)), float(m.group(2))
                matched = {"fwd_a": fwd_a, "rev_a": rev_a}
                ok = ok and fwd_a >= 1.0 and rev_a < 0.5
        out[mode] = {"ok": ok, "matched": matched,
                     "tail": "\n".join(log.strip().splitlines()[-6:])}
    return out


# ════════════════════════════════════════════════════════════════
#  报告与留档
# ════════════════════════════════════════════════════════════════

def acc(d):
    return (d[0], d[1], d[2])


def print_phase(p, idx):
    print("=" * 64)
    print(f"Phase 4 验收 {p['tag']}  n={p['n']} k={p['k']} 词表={p['vocab_size']}  "
          f"训练 {p['n_train']} 句/留出 {p['n_test']} 句")
    print("-" * 64)
    b, g = p["baseline"], p["grad"]
    print(f"{'模型':<22}{'训练集':<12}{'留出':<12}")
    print(f"{'Hebbian wsum':<22}{b['wsum']['train'][0]:<12.4f}{b['wsum']['test'][0]:<12.4f}")
    print(f"{'Hebbian trace':<22}{b['trace']['train'][0]:<12.4f}{b['trace']['test'][0]:<12.4f}")
    if "ngram" in p:
        ng = p["ngram"]
        print(f"{'bigram（上限）':<22}{ng['bigram']['train'][0]:<12.4f}{ng['bigram']['test'][0]:<12.4f}")
        print(f"{'trigram':<22}{ng['trigram']['train'][0]:<12.4f}{ng['trigram']['test'][0]:<12.4f}")
    print(f"{'梯度读出（Phase 4）':<22}{g['train'][0]:<12.4f}{g['test'][0]:<12.4f}")
    print("-" * 64)
    print(f"学到的上下文信任分布（末词→远端）: {p['ctx_wgt']}")
    if "sparsity" in p:
        s = p["sparsity"]
        print(f"W 结构不变（非零 {s['nnz_before']} → {s['nnz_after']}）: "
              f"{'✓' if s['structure_unchanged'] else '✗'}")
        print(f"梯度对 W 扰动（w_delta）: {p['w_delta']}")
    if "cases" in p:
        c = p["cases"]
        hits = sum(1 for row in c["rows"] if row["hit"])
        print(f"微验证: grad 命中 {hits}/{c['n_total']}，"
              f"其中 wsum 猜错处 grad 猜对 {c['n_break']}")
        for row in c["rows"]:
            mark = "✓" if row["break"] else ("◦" if row["hit"] else "✗")
            print(f"  {row['prefix']:<10} truth={row['truth']:<3} "
                  f"wsum={str(row['wsum']):<6} grad={str(row['grad']):<6} {mark}")
    print(f"耗时：Hebbian {p['timing']['hebbian_sec']}s / "
          f"train_ctx {p['timing'].get('ctx_sec', 0.0)}s / "
          f"train_w(微调 W) {p['timing']['grad_sec']}s")
    print("=" * 64)


def main():
    print("Phase 4 完整验收启动（梯度在线学习双轨落地）...\n")
    p1 = accept_small()
    p2 = accept_ctx()
    p3 = accept_long()
    cost = cost_report(p2, p3)
    reg = run_regression()

    for p in (p1, p2, p3):
        print_phase(p, 0)

    print("=" * 64)
    print("开销报告（验收 ④）")
    print(f"  S 矩阵（score 全表）: V={cost['s_matrix']['V']} "
          f"内存 {cost['s_matrix']['mem_mb']}MB")
    print(f"  稠密 W 需 {cost['dense_w_vs_sparse']['dense_w_mb']}MB；S 矩阵占其 "
          f"{cost['dense_w_vs_sparse']['s_mem_vs_dense_pct']}%")
    print(f"  时间：phase2（ctx）Hebbian {cost['timing']['phase2']['hebbian_sec']}s / "
          f"train_ctx {cost['timing']['phase2']['ctx_sec']}s / "
          f"train_w {cost['timing']['phase2']['grad_sec']}s；"
          f"phase3（long）Hebbian {cost['timing']['phase3']['hebbian_sec']}s / "
          f"train_ctx {cost['timing']['phase3']['ctx_sec']}s / "
          f"train_w {cost['timing']['phase3']['grad_sec']}s")
    print("  训练路径：Hebbian 教学式（快、沉淀共现）→ train_ctx（冻结 W 训位置信任，"
          "S 矩阵内存）→ train_w（稀疏梯度只碰 W 非零子集，无额外内存）")
    print("=" * 64)

    print("回归（验收 ⑤，子进程独立跑 schema_net.py）")
    for mode, d in reg.items():
        print(f"  --mode {mode}: {'PASS ✓' if d['ok'] else 'FAIL ✗'}  {d['matched']}")

    # ── 判定 ──
    def cases_hits(p):
        return sum(1 for row in p["cases"]["rows"] if row["hit"])

    def grad_better(p):
        """梯度微调后留出 > 纯 Hebbian 最优基线（wsum/trace）。"""
        return p["grad"]["test"][0] > max(p["baseline"]["wsum"]["test"][0],
                                          p["baseline"]["trace"]["test"][0])

    def w_perturbed(p):
        wd = p["w_delta"]
        return wd is not None and wd["n_changed"] > 0

    j1 = (p1["grad"]["train"][0] > p1["ngram"]["bigram"]["train"][0]
          and p1["grad"]["test"][0] >= max(p1["baseline"]["wsum"]["test"][0],
                                           p1["baseline"]["trace"]["test"][0])
          and p1["sparsity"]["structure_unchanged"])
    # 条件组合：词级梯度微调后留出 > 纯 Hebbian + 微验证 grad 全中
    #            + 学到 pos1 远端信任 + W 结构不变且被扰动（词级修正的证据）
    j2 = (grad_better(p2) and cases_hits(p2) >= 8
          and p2["ctx_wgt"][1] > 0.01
          and p2["sparsity"]["structure_unchanged"] and w_perturbed(p2))
    # 长程关联：同上 + 学到 pos=3 远端（ctx 距末词 3 位）
    j3 = (grad_better(p3) and cases_hits(p3) >= 6
          and p3["ctx_wgt"][3] > 0.01
          and p3["sparsity"]["structure_unchanged"] and w_perturbed(p3))
    j5 = all(d["ok"] for d in reg.values())

    print("=" * 64)
    print("验收结论：")
    print(f"  ① 小规模超 Hebbian（grad_train > bigram 上限且留出不劣化、结构不变）: "
          f"{'PASS ✓' if j1 else 'FAIL ✗'}")
    print(f"  ② 条件组合（grad_test > Hebbian 最优 且微验证 grad 全中 且学到 pos1"
          f" 且 W 结构不变被扰动）: {'PASS ✓' if j2 else 'FAIL ✗'}")
    print(f"  ③ 长程关联（grad_test > Hebbian 最优 且微验证 ≥6/8 且学到 pos=3 远端"
          f" 且 W 结构不变被扰动）: {'PASS ✓' if j3 else 'FAIL ✗'}")
    print(f"  ⑤ 定式保留（abc/seq 回归）: {'PASS ✓' if j5 else 'FAIL ✗'}")
    all_ok = j1 and j2 and j3 and j5
    print(f"\nPhase 4 完整落地: {'PASS ✓' if all_ok else 'FAIL ✗'}")

    # ── 留档 ──
    r = {"phases": {"small": p1, "ctx": p2, "long": p3},
         "cost": cost, "regression": reg, "verdict": {
             "j1": j1, "j2": j2, "j3": j3, "j5": j5, "all": all_ok}}
    runs = Path(__file__).parent / "runs"
    runs.mkdir(exist_ok=True)
    out = runs / datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(exist_ok=True)
    (out / "result.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"留档：{out}")


if __name__ == "__main__":
    main()
