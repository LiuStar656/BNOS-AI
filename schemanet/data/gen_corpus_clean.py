# -*- coding: utf-8 -*-
"""生成 v2.0 干净原料语料 corpus_clean.json（数据专门化基建 Phase A）。

问题诊断：corpus_open20w.json 词表 KV=3000（token 覆盖 72.9%，UNK 27.1%），
**93.5% 的句子含 <UNK>**——它是"训练 tf 的数据"，污染严重，不能作为分级
纯净数据的抽取源（v2.0 铁律 1：训练什么就用什么数据，UNK 是噪声不是数据）。

本脚本复用 gen_corpus_open 的下载/清洗/分词管线（raw 缓存命中，不重复下载），
词表从"固定 KV=3000"改为**覆盖率 ≥98% 动态决定**（不设死词表大小），
把 UNK 率压到 2% 以下，输出 v2.0 分级抽取（Stage 0-5）的原料库。

输出：corpus_clean.json（tokenized 句列表）+ corpus_clean_meta.json（统计）。
用法：python gen_corpus_clean.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent
sys.path.insert(0, str(DATA))

from gen_corpus_open import SOURCES, fetch, load_texts, clean, PUNCT_KEEP, MIN_LEN, MAX_LEN, UNK, SEED

N_PER_SRC = {"toutiao": 160000, "online": 40000}   # 与 corpus_open20w 同规模配比
COVER_TARGET = 0.98                               # 词表 token 覆盖率目标


def main():
    import jieba

    rng = np.random.default_rng(SEED)

    # ── 1. 下载（缓存命中）+ 解析 + 清洗 ──
    per_src = {}
    for name in N_PER_SRC:
        repo, path, fmt = SOURCES[name]
        raw = fetch(repo, path)
        reviews = [clean(s) for s in load_texts(raw, fmt)]
        uniq = list(dict.fromkeys(r for r in reviews if r))
        print(f"[{name}] 原始 {len(reviews)} → 去空去重 {len(uniq)}", flush=True)
        per_src[name] = uniq

    # ── 2. 分词 + 标点/长度过滤 ──
    kept_all = {}
    for name, uniq in per_src.items():
        kept = []
        for s in uniq:
            toks = [t for t in jieba.lcut(s)
                    if t and (t.strip() or t in PUNCT_KEEP)]
            toks = [t for t in toks if t[0].isalnum() or t in PUNCT_KEEP]
            if MIN_LEN <= len(toks) <= MAX_LEN:
                kept.append(toks)
        kept_all[name] = kept
        print(f"[{name}] 分词+长度过滤后 {len(kept)} 句", flush=True)

    # ── 3. 按目标抽样 ──
    sampled = []
    for name, kept in kept_all.items():
        n = min(N_PER_SRC[name], len(kept))
        idx = rng.choice(len(kept), n, replace=False)
        for i in sorted(idx):
            sampled.append(kept[i])
        print(f"[{name}] 抽样 {n} 句", flush=True)
    print(f"合计抽样 {len(sampled)} 句（目标 {sum(N_PER_SRC.values())}）", flush=True)

    # ── 4. 词表：覆盖率 ≥ COVER_TARGET 动态决定（不设死 KV）──
    freq = Counter(t for toks in sampled for t in toks)
    total = sum(freq.values())
    vocab = [UNK]
    cum = 0
    for w, c in freq.most_common():
        if w == UNK:
            continue                      # UNK 仅作 OOV 兜底，不主动入选
        vocab.append(w)
        cum += c
        if cum / total >= COVER_TARGET:
            break
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    covered = sum(freq[w] for w in vocab)
    oov_tot = sum(c for w, c in freq.items() if w not in vocab_idx)
    print(f"词表 {len(vocab)}（含 {UNK}），token 覆盖率 {covered / total:.4f}，"
          f"OOV {oov_tot} token", flush=True)

    # ── 5. OOV → <UNK> ──
    out = [[t if t in vocab_idx else UNK for t in toks] for toks in sampled]

    # ── 6. 统计 ──
    lens = [len(t) for t in out]
    n_unk_sent = sum(UNK in t for t in out)
    unk_ratio = sum(t == UNK for toks in out for t in toks) / max(1, sum(lens))
    stats = {
        "tag": "v2.0 干净原料语料（数据专门化基建 Phase A）",
        "n_sent": len(out), "vocab": len(vocab), "cover_target": COVER_TARGET,
        "token_cover": round(covered / total, 4),
        "unk_ratio": round(unk_ratio, 4),
        "sent_with_unk": n_unk_sent,
        "sent_with_unk_ratio": round(n_unk_sent / len(out), 4),
        "len_min": min(lens), "len_mean": round(sum(lens) / len(lens), 1),
        "len_max": max(lens),
        "top20": [f"{w}:{c}" for w, c in freq.most_common(20)],
        "seed": SEED,
    }
    print("\n[corpus_clean] 统计:", json.dumps(stats, ensure_ascii=False), flush=True)

    # ── 7. 输出 ──
    out_path = DATA / "corpus_clean.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    (DATA / "corpus_clean_meta.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写出: {out_path}（{len(out)} 句，{out_path.stat().st_size / 1e6:.1f}MB）")


if __name__ == "__main__":
    main()
