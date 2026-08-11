# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""临时 debug：trace vs wsum 训练集差异位置（trace 为什么 0.442 < wsum 0.500）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import jieba

from schema_net import SchemaNet, _word_pattern, _learn_sentence
from schema_net import _predict_cands_wsum, _predict_cands_trace
from collections import Counter

n, k, kv, split = 2048, 8, 300, 80
corpus = json.loads(Path("data/corpus.json").read_text(encoding="utf-8"))
tokenized = [jieba.lcut(s) for s in corpus]
freq = Counter(w for toks in tokenized for w in toks)
vocab = [w for w, _ in freq.most_common(kv)]
pats = {w: _word_pattern(n, k, w) for w in vocab}
rng_split = np.random.default_rng(42 + 9000)
perm = rng_split.permutation(len(tokenized))
train_toks = [tokenized[i] for i in perm[:split]]

ng = SchemaNet(n=n, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
               w_max=16.0, wta_k=8, noise_p=0.06, noise_amp=0.5,
               weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
               refractory=1, rng=np.random.default_rng(42 + 5000))
for toks in train_toks:
    _learn_sentence(ng, toks, pats, slot=0)
ng.learn_gate = False

outsum = {a: sum(float(np.sum(ng.W[j, 0, src]))
                 for j in range(n) for src in pats[a])
          for a in vocab}

# 对比：逐位置 wsum vs trace，统计四种情况 + 具体样例
both_ok = trace_ok_wsum_bad = wsum_ok_trace_bad = both_bad = 0
trace_bad_samples = []
wsum_bad_samples = []
total = 0
for toks in train_toks:
    for t in range(1, len(toks)):
        cw = _predict_cands_wsum(ng, toks[:t], pats, vocab, slot=0)
        ct = _predict_cands_trace(ng, toks[:t], pats, vocab, slot=0, norm_base=outsum)
        pw = cw[0][0] if cw else None
        pt = ct[0][0] if ct else None
        truth = toks[t]
        total += 1
        if pw == truth and pt == truth:
            both_ok += 1
        elif pt == truth:
            trace_ok_wsum_bad += 1
            wsum_bad_samples.append(("".join(toks[:t]), truth, pt, [c[0] for c in cw[:3]]))
        elif pw == truth:
            wsum_ok_trace_bad += 1
            trace_bad_samples.append(("".join(toks[:t]), truth, pw, [c[0] for c in ct[:3]]))
        else:
            both_bad += 1

print(f"total={total}")
print(f"  both_ok={both_ok} ({both_ok/total:.3f})")
print(f"  trace_ok_wsum_bad={trace_ok_wsum_bad}  wsum_ok_trace_bad={wsum_ok_trace_bad}  both_bad={both_bad}")
print(f"\n【wsum 错而 trace 对】{len(wsum_bad_samples)} 例，前 12：")
for ctx, truth, pt, cw3 in wsum_bad_samples[:12]:
    print(f"  '{ctx}' → 真值={truth}  trace预测={pt}  wsum top3={cw3}")
print(f"\n【trace 错而 wsum 对】{len(trace_bad_samples)} 例，前 12：")
for ctx, truth, pw, ct3 in trace_bad_samples[:12]:
    print(f"  '{ctx}' → 真值={truth}  wsum预测={pw}  trace top3={ct3}")
