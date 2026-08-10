# -*- coding: utf-8 -*-
"""诊断：batch ≠ 逐句 的差异边来源定位（构造句，秒级）。

背景：smoke 等价性对拍失败（一致 15052880/18467460，差异 0.1/0.5 两类）。
纯计数批量（相邻 bigram + 词内互连）不等价 → 用构造句定位差异从哪类句子来。
"""
import numpy as np
from snapshot import load_version
from schema_net import _learn_sentence
from _probe_expose_prose import (learn_bigram_batch, learn_hebbian_batch,
                                 collect_bigram_counts)

ng, _, pats, _ = load_version("16.0")
n2w = {j: w for w, ns in pats.items() for j in ns}

# 选 6 个模式神经元互不重叠的真实词
cands = [w for w in pats if len(w) >= 2]
words, used = [], set()
for w in cands:
    if all(i not in used for i in pats[w]):
        words.append(w)
        used |= set(pats[w])
    if len(words) >= 6:
        break
A, B, C, D, E, F = words
print(f"选用词：{A} {B} {C} {D} {E} {F}")


def snap(ng):
    return {(i, k, j): w for i in range(ng.n) for k in range(ng.slots)
            for j, w in ng.W_out[i][k].items()}


seqs = [
    [A, B, C],          # 0 普通相邻三连
    [A, B, A, C],       # 1 重复词（A 出现 2 次）
    [A, B, C, D, E],    # 2 长句
    [B, B],             # 3 相邻重复（自环）
    [C, D, E, C, F],    # 4 重复词 + 长句
]

# 每句单独对拍：定位差异来源
for n, seq in enumerate(seqs):
    g1, _, p1, _ = load_version("16.0")
    g2, _, p2, _ = load_version("16.0")
    _learn_sentence(g1, seq, p1, slot=0)
    c, wc = collect_bigram_counts([seq])
    learn_bigram_batch(g2, p2, c, slot=0)
    learn_hebbian_batch(g2, p2, wc, slot=0)
    e1, e2 = snap(g1), snap(g2)
    ks = set(e1) | set(e2)
    dd = [(k, e1.get(k, 0.0), e2.get(k, 0.0)) for k in ks
          if abs(e1.get(k, 0.0) - e2.get(k, 0.0)) > 1e-9]
    print(f"\n句{n} {' '.join(seq)} → 差异 {len(dd)}")
    for (i, k, j), va, vb in dd[:8]:
        print(f"    {n2w.get(i, '?')}({i}) → {n2w.get(j, '?')}({j}): "
              f"逐句 {va} vs 批量 {vb}")
