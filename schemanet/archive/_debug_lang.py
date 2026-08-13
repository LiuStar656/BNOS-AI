# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""临时 debug v2：与语言实验完全对齐参数，核对 W 结构 / 回响 / 真实噪声行为。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import jieba

from schema_net import SchemaNet, _word_pattern, _learn_sentence, _predict_cands, build_pulse

n, k = 2048, 8
corpus = json.loads(Path("data/corpus.json").read_text(encoding="utf-8"))
tokenized = [jieba.lcut(s) for s in corpus]
from collections import Counter
freq = Counter(w for toks in tokenized for w in toks)
vocab = [w for w, _ in freq.most_common(300)]
pats = {w: _word_pattern(n, k, w) for w in vocab}

rng_split = np.random.default_rng(42 + 9000)
perm = rng_split.permutation(len(tokenized))
train_toks = [tokenized[i] for i in perm[:80]]

# ── 与 run_language_experiment 完全一致的构造参数 ──
ng = SchemaNet(n=n, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
               w_max=16.0, wta_k=8, noise_p=0.06, noise_amp=0.5,
               weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
               refractory=1, rng=np.random.default_rng(42 + 5000))
for toks in train_toks:
    _learn_sentence(ng, toks, pats, slot=0)
ng.learn_gate = False


def w_out(src_word, tgt_word):
    """W[tgt ← src]：目标词模式平均承接源词模式的转移总强度。"""
    src = pats[src_word]
    tgt = pats[tgt_word]
    return sum(float(np.sum(ng.W[j, 0, src])) for j in tgt) / len(tgt)


print("=== W 转移强度（教学式学习后）===")
for s, t in [("我", "喜欢"), ("我", "想"), ("我", "觉得"), ("我", "无聊"),
             ("觉得", "无聊"), ("我", "今天"), ("我", "有点"), ("我", "很")]:
    print(f"  W[{t} ← {s}] = {w_out(s, t):.2f}")

print("\n=== '我' 的出边 top-10（应: 喜欢>想>有点>今天>觉得...，无聊不该在列）===")
rows = sorted(((w, w_out("我", w)) for w in vocab if w != "我"), key=lambda x: -x[1])
for w, t in rows[:10]:
    print(f"  {w}: {t:.3f}")

print("\n=== 注入'我' 回响 1 步 top-5（评估同口径）===")
fired = _predict_cands(ng, ["我"], pats, vocab, min_cov=0.0, steps=1)
print("  " + "  ".join(f"{w}({s})" for w, s in fired[:5]))

print("\n=== 真实网络 19 步零输入（纯噪声动力学，连续 rng）===")
ng2 = SchemaNet(n=n, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                w_max=16.0, wta_k=8, noise_p=0.06, noise_amp=0.5,
                weight_decay=0.0, slot_cap=0.0, stdp_pre=0.0, stdp_neg=0.0,
                refractory=1, rng=np.random.default_rng(1))
ng2.learn_gate = False
ng2.v = np.zeros((n, 4))
ng2.spikes = np.zeros(n)
ng2.pre_trace = np.zeros(n)
fired_all = set()
step_counts = []
for _ in range(19):
    s = ng2.step(np.zeros(n), slot=0)
    step_counts.append(int((s > 0).sum()))
    fired_all |= set(np.where(s > 0)[0])
print(f"  单步发放数: {step_counts}")
print(f"  累计唯一发放神经元: {len(fired_all)} / {n}")
