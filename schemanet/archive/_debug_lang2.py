# -*- coding: utf-8 -*-
"""二次诊断：'无聊' 14.0 的根源 —— 真连接 vs 共享神经元污染。

核心问题：语料中'无聊'只出现在"我觉得无聊"一句，且该句里'我'与'无聊'
相隔一个'觉得'（trace 衰减 0.5³=0.125 < 0.3 被滤掉），理论上 W[无聊←我]
应为 0。但实测 14.0。

假设：分布式编码下所有词共享神经元，STDP 在其它句子里把连接强化到了
'无聊'模式神经元上（因为其它词的模式与'无聊'模式碰巧共享神经元）——
这叫"共享神经元污染"，与真实转移无关。

消融实验：把含'无聊'的句子从训练集剔除，若 W[我→无聊] 仍 ≈14.0 →
纯污染实锤。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
import jieba

from schema_net import SchemaNet, _word_pattern, _learn_sentence

cfg = {"n": 2048, "slots": 4, "theta": 1.0, "membrane_decay": 0.9, "eta": 0.1,
       "w_max": 2.0, "noise_p": 0.06, "noise_amp": 0.5, "seed": 42,
       "lang_stdp_pre": 0.5, "lang_split": 80}
n, k = 2048, 8

corpus = json.loads(Path("data/corpus.json").read_text(encoding="utf-8"))
tokenized = [jieba.lcut(s) for s in corpus]
from collections import Counter
freq = Counter(w for toks in tokenized for w in toks)
vocab = [w for w, _ in freq.most_common(300)]
pats = {w: _word_pattern(n, k, w) for w in vocab}

rng_split = np.random.default_rng(42 + 9000)
perm = rng_split.permutation(len(tokenized))
train_idx, test_idx = perm[:80], perm[80:]
train_toks = [tokenized[i] for i in train_idx]

# 找出训练集里含"无聊"的句子
bored_sents = [(i, toks) for i, toks in enumerate(train_toks) if "无聊" in toks]
print(f"训练集含'无聊'的句子: {len(bored_sents)}")
for i, toks in bored_sents:
    print(f"  #{i}: {toks}")
train_no_bored = [toks for toks in train_toks if "无聊" not in toks]
print(f"剔除后训练句数: {len(train_no_bored)}")

# ── 训练两个网络：完整 vs 剔除'无聊' ──
def train(toks_list):
    ng = SchemaNet(n=n, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                   w_max=2.0, wta_k=8, noise_p=0.06, noise_amp=0.5,
                   weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                   refractory=1,
                   rng=np.random.default_rng(42 + 5000))
    for toks in toks_list:
        _learn_sentence(ng, toks, pats, slot=0)
    return ng


def edge_strength(ng, src_word, tgt_word):
    """sum_{j in tgt} W[j, 0, src] / len(tgt) —— 与 _predict_cands_wsum 同口径"""
    src, tgt = pats[src_word], pats[tgt_word]
    return sum(float(np.sum(ng.W[j, 0, src])) for j in tgt) / len(tgt)


print("\n════ 消融：'无聊'句子剔除前后 ════")
ng_full = train(train_toks)
ng_abl = train(train_no_bored)
for src in ("我", "你", "想", "吃", "觉得", "一起", "保重"):
    f = edge_strength(ng_full, src, "无聊")
    a = edge_strength(ng_abl, src, "无聊")
    print(f"  W[{src}→无聊]  完整={f:8.3f}  剔除={a:8.3f}  差={f-a:7.3f}")

# 对照：'觉得'（真实转移，句内相邻）在剔除前后
print("\n  对照真实转移（'我'直接前驱词的强度）:")
for src, tgt in (("我", "觉得"), ("觉得", "无聊"), ("我", "想")):
    f = edge_strength(ng_full, src, tgt)
    a = edge_strength(ng_abl, src, tgt)
    print(f"  W[{src}→{tgt}]  完整={f:8.3f}  剔除={a:8.3f}")

# ── 共享神经元检查：'无聊'的模式与各高频词模式交集 ──
print("\n════ 模式共享神经元（与'无聊'交集）════")
pb = set(pats["无聊"])
for w in ("我", "你", "想", "吃", "觉得", "一起", "保重", "欢迎", "听", "做", "下次", "出去", "好"):
    inter = pb & set(pats[w])
    if inter:
        print(f"  {w}: 共享 {sorted(inter)}")

# ── 模式重叠：我/你/想/吃 是否共享神经元 ──
print("\n════ 模式两两交集（我/你/想/吃）════")
words = ["我", "你", "想", "吃", "觉得", "无聊"]
for a in range(len(words)):
    for b in range(a + 1, len(words)):
        w1, w2 = words[a], words[b]
        inter = set(pats[w1]) & set(pats[w2])
        if inter:
            print(f"  {w1}∩{w2}: {sorted(inter)}")

# ── 原始 W 明细：'无聊'每个目标神经元收到的入边 ──
print("\n════ W['无聊'模式, 槽0, :] 非零明细 ════")
pb_list = pats["无聊"]
tot_nonzero = 0
for j in pb_list:
    row = ng_full.W[j, 0]
    nz = np.where(row > 0)[0]
    if len(nz):
        tot_nonzero += len(nz)
        top = sorted(zip(nz.tolist(), row[nz].tolist()), key=lambda x: -x[1])[:6]
        print(f"  神经元{j}: {len(nz)} 个入边, top: " +
              ", ".join(f"{s}:{v:.2f}" for s, v in top))
print(f"  共 {tot_nonzero} 条非零入边")

# ── 我→无聊 逐神经元矩阵：哪些源神经元、什么强度 ──
print("\n════ W[无聊_j, 0, 我_i] 矩阵（源=我的8神经元）════")
me, bored = pats["我"], pats["无聊"]
for j in bored:
    vals = [float(ng_full.W[j, 0, i]) for i in me]
    print(f"  无聊神经元{j} ← 我{me}: {[round(v,2) for v in vals]}")

# ── 关键验证：这些源神经元(30,61,107,140,266,370,364)属于哪些词的模式？ ──
print("\n════ top 源神经元属于哪些词的模式（在词表内搜索）════")
probe = [30, 61, 107, 140, 266, 370, 364]
for s in probe:
    owners = [w for w in vocab if s in pats[w]]
    print(f"  神经元{s} ∈ {owners[:8]}{'...' if len(owners)>8 else ''} (共{len(owners)}词)")

# ── 噪声卫生真值检查（与 step() 一致的单一 rng + WTA + 复位）──
print("\n════ 噪声卫生（真实 step 动力学）════")
ng0 = SchemaNet(n=n, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                w_max=2.0, wta_k=8, noise_p=0.06, noise_amp=0.5,
                weight_decay=0.0, slot_cap=0.0, stdp_pre=0.0, stdp_neg=0.0,
                rng=np.random.default_rng(1))
fired_total = set()
for step_i in range(19):
    sp = ng0.step(np.zeros(n), slot=0)
    fired_total |= set(np.where(sp > 0)[0])
print(f"  纯噪声 19 步（真实 step）累计发放神经元数: {len(fired_total)}")

# 旧 buggy 版本对照（每步重建同一 rng → 同神经元连击）
v = np.zeros((n, 4))
for _ in range(19):
    v = v * 0.9 + (np.random.default_rng(1).random((n, 4)) < 0.06) * 0.5
print(f"  旧版（每步同 rng）越阈: {(v.max(axis=1) >= 1.0).sum()}")
