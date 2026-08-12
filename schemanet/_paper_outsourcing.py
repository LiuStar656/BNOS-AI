# -*- coding: utf-8 -*-
"""投稿补全实验 E5：能力外置对照（纯动力学回响 vs 代码层读出）。

核心问题（论文立场）：语言预测能力来自**代码层读出**（S 矩阵直读 / 梯度
读出层），而非**模型动力学层**（积分-发放回响本身）。

对照：
  A. 纯动力学：freeze 态注入前缀 → _evoke_prefix(steps=1) 回响 → 激活神经元
     集合（模糊、无词级清晰输出）。指标：
       - recall：目标词模式被激活覆盖率 |fired ∩ pats[w_t]| / |pats[w_t]|
       - 硬解析 top-1：把激活集按"神经元→词反查"多数投票解析为预测词
       - 续推成功率：回响完全无发放的比例（动力学不产出 = 无法续推）
  B. 代码层：wsum（E1 已测，seed=42：top-1 0.1125 / PPL 600.8）——清晰词级
     概率分布，可做 top-1 与 PPL。

用法：python _paper_outsourcing.py
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _paper_eval as pe
from schema_net import _word_pattern, _evoke_prefix
from sparse_net import _pats_matrix, save_net

SEED = 42
EVAL_SUB_TEST = 600


def run_one(seed):
    """单 seed 完整 E5 流程（训练 + 动力学回响 + 代码层 wsum），返回 result dict。"""
    SEED = seed
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    t_start = time.time()
    print(f"── E5 能力外置对照（seed={SEED}）──", flush=True)

    # 训练（与 E1 同一流水线，保证同网络同词表同划分）
    train_toks, test_toks, vocab, vocab_idx = pe.load_corpus(SEED)
    pats = {w: _word_pattern(pe.N, pe.K, w) for w in vocab}
    pats_mat = _pats_matrix(pats, vocab)
    r = pe.train_schemanet(train_toks, vocab, SEED, scan_toks=None)
    ng = r["ng"]
    S, outsum = r["S"], r["outsum"]
    print(f"Hebbian {r['timing']['hebbian']}s | train_w {r['timing']['train_w']}s | "
          f"delta_off={r['delta_off']}", flush=True)

    # 评估子集（与 E1 同 rng 同数量）
    rng = np.random.default_rng(SEED + 9001)
    ev_te = [test_toks[i] for i in
             rng.choice(len(test_toks), min(EVAL_SUB_TEST, len(test_toks)), replace=False)]

    # 神经元 → 词反查（多数投票解析用）
    words_of = defaultdict(list)
    for w, ns in pats.items():
        for n_ in ns:
            words_of[n_].append(w)
    # 词频（并列投票时取高频词）
    freq = Counter(w for toks in train_toks for w in toks)

    # A. 纯动力学回响
    n_pos = 0
    recall_sum = 0.0
    dyn_hits = dyn_total = 0        # 硬解析 top-1 命中
    fired_empty = 0                  # 回响无任何发放的位置数
    for toks in ev_te:
        ids = [vocab_idx[w] for w in toks if w in vocab_idx]
        for t in range(1, len(ids)):
            fired = _evoke_prefix(ng, [vocab[i] for i in ids[:t]], pats, slot=0, steps=1)
            target_pats = pats[vocab[ids[t]]]
            # recall：目标词模式覆盖率
            recall = len(fired & set(target_pats)) / len(target_pats)
            recall_sum += recall
            n_pos += 1
            if not fired:
                fired_empty += 1
                dyn_total += 1
                continue
            # 硬解析：激活集神经元反查词 → 多数投票（并列取词频高者）
            cnt = Counter()
            for n_ in fired:
                for w in words_of[n_]:
                    cnt[w] += 1
            pred = max(cnt.items(), key=lambda kv: (kv[1], freq.get(kv[0], 0)))[0]
            dyn_total += 1
            if pred == vocab[ids[t]]:
                dyn_hits += 1

    recall_mean = recall_sum / n_pos if n_pos else 0.0
    dyn_top1 = dyn_hits / dyn_total if dyn_total else 0.0
    empty_ratio = fired_empty / n_pos if n_pos else 0.0

    # B. 代码层 wsum（同子集重测，避免引用旧留档）
    w_te = pe.evaluate_wsum_smat(S, vocab, ev_te, norm_base=outsum)
    wsum_top1 = w_te[0]

    print(f"\nA 纯动力学回响（{n_pos} 位置）:")
    print(f"  目标词模式覆盖率 recall: {recall_mean:.4f}")
    print(f"  硬解析 top-1（神经元多数投票）: {dyn_top1:.4f}")
    print(f"  回响无发放占比（无法续推）: {empty_ratio:.4f}")
    print(f"B 代码层 wsum 读出（同子集）: top-1 {wsum_top1:.4f}")
    print(f"  外置增益（wsum - 动力学硬解析）: {wsum_top1 - dyn_top1:+.4f}", flush=True)

    result = {
        "tag": "E5 能力外置对照：纯动力学回响 vs 代码层读出",
        "seed": SEED, "n_pos": n_pos, "eval_n": len(ev_te),
        "dynamics": {"recall": round(recall_mean, 4),
                     "top1_hard_parse": round(dyn_top1, 4),
                     "no_fire_ratio": round(empty_ratio, 4)},
        "code_layer": {"wsum_top1": round(wsum_top1, 4),
                       "outsourcing_gain": round(wsum_top1 - dyn_top1, 4)},
        "elapsed_sec": round(time.time() - t_start, 1),
    }
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("runs") / f"paper_e5_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    save_net(ng, vocab, out_dir / "net.npz", ctx_wgt=r["ro"].ctx_wgt)
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {out_dir}/  elapsed {result['elapsed_sec']}s", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", nargs="+", type=int, default=None,
                    help="多 seed 循环（默认只跑 SEED=42）")
    args = ap.parse_args()
    seeds = args.seeds or [SEED]
    results = [run_one(s) for s in seeds]
    if len(seeds) > 1:
        dyn = np.array([r["dynamics"]["top1_hard_parse"] for r in results])
        cod = np.array([r["code_layer"]["wsum_top1"] for r in results])
        gain = np.array([r["code_layer"]["outsourcing_gain"] for r in results])
        summary = {
            "seeds": seeds,
            "dynamics_top1_hard_parse": [round(float(dyn.mean()), 4), round(float(dyn.std()), 4)],
            "code_wsum_top1": [round(float(cod.mean()), 4), round(float(cod.std()), 4)],
            "outsourcing_gain": [round(float(gain.mean()), 4), round(float(gain.std()), 4)],
        }
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path("runs") / f"paper_e5_multi_{ts}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n多 seed 汇总留档: {out_dir}/summary.json", flush=True)
        print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)


if __name__ == "__main__":
    main()
