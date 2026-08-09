# -*- coding: utf-8 -*-
"""生成 Phase 2 数据放大语料 corpus_open20w.json（20 万句，tokenized）。

复用 gen_corpus_open.py 的下载/清洗/分词/词表/OOV 管线（缓存命中，不重复下载），
仅调整数据源配比与目标句数：
  - toutiao（38 万头条标题，短文本、质量高）：抽 160000
  - online_shopping_10_cats（6 万商品评论，长句）：抽 40000
  - 合计 200000 句，词表 KV=3000（与 L0 corpus_open 同口径，便于 scaling 对照）

输出：corpus_open20w.json（tokenized 句列表）+ corpus_open20w_meta.json（统计）。
用法：python gen_corpus_open20w.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent
sys.path.insert(0, str(DATA))

from gen_corpus_open import SOURCES, fetch, load_texts, clean, PUNCT_KEEP, MIN_LEN, MAX_LEN, KV, UNK, SEED

N_TARGET = 200000
N_PER_SRC = {"toutiao": 160000, "online": 40000}


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

    # ── 3. 按目标抽样（每源 N_PER_SRC）──
    sampled = []
    for name, kept in kept_all.items():
        n = min(N_PER_SRC[name], len(kept))
        idx = rng.choice(len(kept), n, replace=False)
        for i in sorted(idx):
            sampled.append(kept[i])
        print(f"[{name}] 抽样 {n} 句", flush=True)
    print(f"合计抽样 {len(sampled)} 句（目标 {N_TARGET}）", flush=True)

    # ── 4. 词表 top-KV（强制含 <UNK>）──
    freq = Counter(t for toks in sampled for t in toks)
    vocab = [UNK] + [w for w, _ in freq.most_common(KV + 100) if w != UNK][:KV - 1]
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    covered = sum(freq[w] for w in vocab)
    oov_tot = sum(c for w, c in freq.items() if w not in vocab_idx)
    print(f"词表 {len(vocab)}（含 {UNK}），token 覆盖率 {covered / sum(freq.values()):.4f}",
          flush=True)

    # ── 5. OOV → <UNK> ──
    out = [[t if t in vocab_idx else UNK for t in toks] for toks in sampled]

    # ── 6. 统计 ──
    lens = [len(t) for t in out]
    unk_ratio = sum(t == UNK for toks in out for t in toks) / max(1, sum(lens))
    stats = {
        "tag": "Phase 2 数据放大语料（L1：2 万 → 20 万句）",
        "n_sent": len(out), "vocab": len(vocab), "kv_target": KV,
        "token_cover": round(covered / sum(freq.values()), 4),
        "unk_ratio": round(unk_ratio, 4),
        "len_min": min(lens), "len_mean": round(sum(lens) / len(lens), 1),
        "len_max": max(lens),
        "top20": [f"{w}:{c}" for w, c in freq.most_common(20)],
        "seed": SEED,
    }
    print("\n[corpus_open20w] 统计:", json.dumps(stats, ensure_ascii=False))

    # ── 7. 输出 ──
    out_path = DATA / "corpus_open20w.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    (DATA / "corpus_open20w_meta.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写出: {out_path}（{len(out)} 句，{out_path.stat().st_size / 1e6:.1f}MB）")


if __name__ == "__main__":
    main()
