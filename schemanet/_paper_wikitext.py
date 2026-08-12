# -*- coding: utf-8 -*-
"""投稿补全实验 E4：标准数据集 PTB（Penn Treebank）全方法同口径对比。

数据：data/wikitext2/ptb.{train,valid,test}.txt（空格分词，自带 <unk>）
处理：<unk> → <UNK> 统一；词表 = 高频 3000 + <UNK>（与 corpus_open KV=3000 契约一致）
方法：SchemaNet 三路（wsum/trace/grad）top-1 + PPL vs bigram/trigram/KN/LSTM 基线

用法：python _paper_wikitext.py            # 单次全流程（seed=42）
"""
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _paper_eval as pe  # noqa: E402  复用公共函数（训练流水线/PPL/基线）

DATA = Path("data/wikitext2")
SEED = 42
EVAL_SUB_TEST = 600
UNK = "<UNK>"


def load_ptb():
    """加载 PTB 三划分；<unk> → <UNK>。返回 (train_toks, valid_toks, test_toks)。"""
    out = {}
    for split in ("train", "valid", "test"):
        toks_list = []
        for line in (DATA / f"ptb.{split}.txt").read_text(encoding="utf-8").splitlines():
            toks = line.strip().split()
            if toks:
                toks_list.append([UNK if t == "<unk>" else t for t in toks])
        out[split] = toks_list
    return out["train"], out["valid"], out["test"]


def build_vocab(train_toks):
    freq = Counter(w for toks in train_toks for w in toks)
    vocab = [UNK] + [w for w, _ in freq.most_common(pe.KV + 100) if w != UNK][:pe.KV - 1]
    return vocab, {w: i for i, w in enumerate(vocab)}


def main():
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    t_start = time.time()
    train_toks, valid_toks, test_toks = load_ptb()
    vocab, vocab_idx = build_vocab(train_toks)

    # 词表外 token 统一替换为 <UNK>（与 corpus_open 契约一致：语料内所有词 ∈ 词表∪{UNK}）
    def _oov_to_unk(toks_list):
        return [[w if w in vocab_idx else UNK for w in toks] for toks in toks_list]

    train_toks = _oov_to_unk(train_toks)
    valid_toks = _oov_to_unk(valid_toks)
    test_toks = _oov_to_unk(test_toks)

    unk_ids = {vocab_idx[UNK]}
    n_tok = sum(len(t) for t in train_toks)
    print(f"PTB: train {len(train_toks)} 句 / {n_tok} token | valid {len(valid_toks)} | "
          f"test {len(test_toks)} | 词表 {len(vocab)} | UNK 占比 "
          f"{sum(1 for t in train_toks for w in t if w == UNK) / n_tok:.4f}", flush=True)

    # SchemaNet 训练（复用 pe.train_schemanet；delta 扫描用 valid 子集）
    pats = {w: pe._word_pattern(pe.N, pe.K, w) for w in vocab}  # noqa: SLF001
    rng_scan = np.random.default_rng(SEED + 9002)
    scan_toks = [valid_toks[i] for i in
                 rng_scan.choice(len(valid_toks), min(pe.SCAN_SUB, len(valid_toks)), replace=False)]
    r = pe.train_schemanet(train_toks, vocab, SEED, scan_toks=scan_toks)
    ng, ro, S, outsum, delta_off = (r["ng"], r["ro"], r["S"], r["outsum"], r["delta_off"])
    print(f"Hebbian {r['timing']['hebbian']}s | sleep {r['timing']['sleep']}s | "
          f"delta_off={delta_off} | train_w {r['timing']['train_w']}s", flush=True)

    rng = np.random.default_rng(SEED + 9001)
    ev_te = [test_toks[i] for i in
             rng.choice(len(test_toks), min(EVAL_SUB_TEST, len(test_toks)), replace=False)]

    # 三路 top-1
    w_te = pe.evaluate_wsum_smat(S, vocab, ev_te, norm_base=outsum)
    t_te = pe.evaluate_trace_smat(ng, ev_te, S, pats, vocab, outsum, delta_off=delta_off)
    g_te = ro.evaluate_w(ev_te)
    print(f"E4 top-1: wsum {w_te[0]:.4f}  trace {t_te[0]:.4f}  grad {g_te[0]:.4f}", flush=True)

    # 三路 PPL
    ppl = {
        "wsum": pe.ppl_wsum(S, outsum, ev_te, vocab, vocab_idx, unk_ids),
        "trace": pe.ppl_trace(ng, S, outsum, ev_te, pats, vocab, vocab_idx, unk_ids, delta_off),
        "grad": pe.ppl_grad(ro, ev_te, vocab, vocab_idx, unk_ids, use_w=True),
    }
    for k, (a, nu, na, nn) in ppl.items():
        print(f"E4 PPL[{k}]: all {a:.1f} / no-unk {nu:.1f} (n={na})", flush=True)

    # 基线
    bl = pe.baseline_ngram(train_toks, test_toks, vocab, vocab_idx, unk_ids)
    print(f"E4 n-gram: bigram top1 {bl['bigram_top1']:.4f} ppl {bl['bigram_ppl_all']:.1f} | "
          f"trigram top1 {bl['trigram_top1']:.4f} ppl {bl['trigram_ppl_all']:.1f}", flush=True)
    try:
        bl.update(pe.baseline_kneser_ney(train_toks, test_toks, vocab, vocab_idx, unk_ids))
        print(f"E4 KN: top1 {bl['kn_top1']:.4f} ppl {bl['kn_ppl_all']:.1f}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"E4 KN failed: {e}", flush=True)
        bl["kn_error"] = str(e)
    try:
        bl.update(pe.baseline_lstm(train_toks, test_toks, vocab, vocab_idx, unk_ids, seed=SEED))
        print(f"E4 LSTM: top1 {bl['lstm_top1']:.4f} ppl {bl['lstm_ppl_all']:.1f} "
              f"ep {bl['lstm_epochs']}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"E4 LSTM failed: {e}", flush=True)
        bl["lstm_error"] = str(e)

    result = {
        "tag": "E4 PTB 标准数据集全方法对比", "corpus": "PTB (Penn Treebank)",
        "seed": SEED, "delta_off": delta_off,
        "vocab": len(vocab), "train_tokens": n_tok,
        "top1": {"wsum": w_te[0], "trace": t_te[0], "grad": g_te[0], "eval_n": len(ev_te)},
        "ppl": {k: {"all": float(v[0]), "no_unk": float(v[1]), "n": v[2]}
                for k, v in ppl.items()},
        "baselines": bl,
        "timing": r["timing"], "w_delta": r["w_delta"], "nnz_unchanged": r["nnz_unchanged"],
        "elapsed_sec": round(time.time() - t_start, 1),
    }
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("runs") / f"paper_ptb_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pe.save_net(ng, vocab, out_dir / "net.npz", ctx_wgt=ro.ctx_wgt)
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print(f"留档: {out_dir}/  elapsed {result['elapsed_sec']}s", flush=True)


if __name__ == "__main__":
    main()
