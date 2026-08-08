# -*- coding: utf-8 -*-
"""三次诊断：修复后语言实验读出的实际行为。"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
import jieba
from schema_net import SchemaNet, _word_pattern, _learn_sentence, _predict_cands, _predict_cands_wsum, _evoke_prefix

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

ng = SchemaNet(n=n, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
               w_max=16.0, wta_k=8, noise_p=0.06, noise_amp=0.5,
               weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
               refractory=1, rng=np.random.default_rng(42 + 5000))
for toks in train_toks:
    _learn_sentence(ng, toks, pats, slot=0)

# 直接 W 边
def edge(ng, s, t):
    src, tgt = pats[s], pats[t]
    return sum(float(np.sum(ng.W[j, 0, src])) for j in tgt) / len(tgt)

print("【直接 W 边】我→?")
for w in ["喜欢", "想", "觉得", "吗", "好", "饿", "很", "无聊", "你"]:
    print(f"  W[我→{w}] = {edge(ng, '我', w):.3f}")

print("\n【回响1步】注入'我'，各步发放：")
ng2 = SchemaNet(n=n, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                w_max=16.0, wta_k=8, noise_p=0.06, noise_amp=0.5,
                weight_decay=0.0, slot_cap=0.0, stdp_pre=0.0, stdp_neg=0.0,
                refractory=1, rng=np.random.default_rng(99))
ng2.W = ng.W.copy()  # 复用学到的权重
ng2.v = np.zeros((n, 4)); ng2.spikes = np.zeros(n); ng2.pre_trace = np.zeros(n)
ng2.step(build_pulse := (lambda n, idxs: np.array([1.0 if i in idxs else 0.0 for i in range(n)]))(n, pats["我"]))
def word_of(sp, pats):
    words = []
    for w, p in pats.items():
        if set(p) <= set(np.where(sp > 0)[0]):
            words.append(w)
    return words
print("  注入'我'后 spikes 的完整词归属:", word_of(ng2.spikes, pats))
fired_all = set(np.where(ng2.spikes > 0)[0])
for step_i in range(3):
    sp = ng2.step(np.zeros(n))
    fired_all |= set(np.where(sp > 0)[0])
    print(f"  回响步{step_i+1}: 发放 {int(sp.sum())} 神经元 → 完整词: {word_of(sp, pats)}")
print(f"  3步并集: {len(fired_all)} 神经元")
for w in ["喜欢", "想", "吗", "好", "饿", "觉得", "你"]:
    cov = len(fired_all & set(pats[w])) / k
    print(f"    覆盖率[{w}] = {cov:.2f}")

print("\n【预测接口】")
print("  echo:", [(w, s) for w, s in _predict_cands(ng, ["我"], pats, vocab, min_cov=0.4, steps=1)[:6]])
print("  wsum:", [(w, s) for w, s in _predict_cands_wsum(ng, ["我"], pats, vocab)[:6]])

print("\n【喜欢→? 直接 W 边】")
for w in ["想", "吃", "喝茶", "音乐", "看书", "跑步"]:
    print(f"  W[喜欢→{w}] = {edge(ng, '喜欢', w):.3f}")
print("  W[喜欢→想]明细:", {f"{i}": float(ng.W[j, 0, i]) for j in pats["想"] for i in pats["喜欢"] if ng.W[j,0,i]>0} if any(ng.W[j,0,i]>0 for j in pats["想"] for i in pats["喜欢"]) else "全0")
print("\n【我喜欢 回响1步 fired 的完整词归属】")
ng3 = SchemaNet(n=n, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                w_max=16.0, wta_k=8, noise_p=0.06, noise_amp=0.5,
                weight_decay=0.0, slot_cap=0.0, stdp_pre=0.0, stdp_neg=0.0,
                refractory=1, rng=np.random.default_rng(7))
ng3.W = ng.W.copy()
f = _evoke_prefix(ng3, ["我", "喜欢"], pats, slot=0, steps=1)
for w in ["喜欢", "想", "吃", "喝茶", "音乐", "看书", "跑步", "散步"]:
    cov = len(f & set(pats[w])) / k
    if cov > 0:
        print(f"  {w}: cov={cov:.2f} 交集={sorted(f & set(pats[w]))}")

# ── 完整复刻真实 eval 路径 ──
from schema_net import _evaluate_schemanet
test_toks = [tokenized[i] for i in perm[80:]]
print("\n【真实 eval 路径】留出句 echo / wsum")
r_echo = _evaluate_schemanet(ng, test_toks, pats, vocab, min_cov=0.4, readout="echo")
r_wsum = _evaluate_schemanet(ng, test_toks, pats, vocab, readout="wsum")
print(f"  echo: acc={r_echo[0]:.3f} hits={r_echo[1]}/{r_echo[2]}")
for s in r_echo[3]:
    print(f"    前缀[{s['ctx']}] 真值={s['truth']} 预测={s['pred']} top3={s['top3']}")
print(f"  wsum: acc={r_wsum[0]:.3f} hits={r_wsum[1]}/{r_wsum[2]}")
for s in r_wsum[3]:
    print(f"    前缀[{s['ctx']}] 真值={s['truth']} 预测={s['pred']} top3={s['top3']}")
print("\n【训练集 echo】")
r_tr = _evaluate_schemanet(ng, train_toks, pats, vocab, min_cov=0.4, readout="echo")
print(f"  echo: acc={r_tr[0]:.3f} hits={r_tr[1]}/{r_tr[2]}")
