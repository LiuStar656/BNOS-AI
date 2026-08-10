# -*- coding: utf-8 -*-
"""验证：rng 状态传递的进程切块 ≡ 串行逐句（逐边对拍）。

背景（2026-08-10 已证）：_learn_sentence 每句结尾回响 4 步，v 不清零 →
噪声连续累积越阈发放（每句 ~3600 条随机边），噪声序列由 rng 决定 →
纯统计批量（不跑动力学）永远不等价。

切块方案：主进程预生成每块边界 rng state（只跑 random 不学习，秒级），
各块进程从对应 state 恢复 rng 再喂自己的句子块 → 块内噪声序列与串行中
该段逐位一致 → 各块增量边合并 = 串行结果。对拍铁律：切块 ≡ 串行 逐边验证。
"""
import copy
from collections import Counter
from snapshot import load_version
from schema_net import _learn_sentence
import numpy as np

# ── 测试句子（合成：词表内随机句，长短不一含重复词）────────
ng0, _, pats, _ = load_version("16.0")
n2w = {j: w for w, ns in pats.items() for j in ns}
import random as rnd
rnd.seed(1)
words = [w for w in pats if len(w) >= 2]
N_SENTS = 100
seqs = [[rnd.choice(words) for _ in range(rnd.randint(3, 8))] for _ in range(N_SENTS)]


def snap(ng):
    return {(i, k, j): w for i in range(ng.n) for k in range(ng.slots)
            for j, w in ng.W_out[i][k].items()}


def make_ng(state=None):
    ng, _, p, _ = load_version("16.0")
    if state is not None:
        ng.rng.bit_generator.state = copy.deepcopy(state)
    return ng, p


def steps_per_sentence(L):
    return 2 * L + 4  # 每词注入+间隔，结尾回响 4 步


def rng_boundaries(state0, n_blocks, per):
    """主进程：从 state0 出发逐句推进 rng（不学习），记录每块边界 state。"""
    ng, _ = make_ng(state0)
    bnds = []
    for i, seq in enumerate(seqs):
        for _ in range(steps_per_sentence(len(seq))):
            ng.rng.random(ng.n)
        if (i + 1) % per == 0 and (i + 1) < N_SENTS:
            bnds.append(copy.deepcopy(ng.rng.bit_generator.state))
    return bnds


t0 = __import__("time").time()
INIT = copy.deepcopy(make_ng()[0].rng.bit_generator.state)

# ── 路径 A：串行（单一 rng 连续）──────────────────────────────
ngA, pA = make_ng(INIT)
for seq in seqs:
    _learn_sentence(ngA, seq, pA, slot=0)
eA = snap(ngA)
print(f"[A 串行] 完成 {N_SENTS} 句")

# ── 路径 B：2 块 + rng state 传递 ─────────────────────────────
n_blocks = 2
per = -(-N_SENTS // n_blocks)
bnds = rng_boundaries(INIT, n_blocks, per)
base, _, _, _ = load_version("16.0")
eBase = snap(base)

merged = dict(eBase)
for blk, (s, e) in enumerate([(0, per), (per, N_SENTS)]):
    start_state = INIT if blk == 0 else bnds[blk - 1]
    ngB, pB = make_ng(start_state)
    for seq in seqs[s:e]:
        _learn_sentence(ngB, seq, pB, slot=0)
    eB = snap(ngB)
    # 增量合并（块间独立，合并时统一 w_max 封顶）
    for k, w in eB.items():
        merged[k] = merged.get(k, 0.0) + (w - eBase.get(k, 0.0))
    print(f"[B 块{blk}] 完成 {e - s} 句（{s}-{e}）")

wmax = ng0.w_max
merged = {k: (w if w <= wmax else wmax) for k, w in merged.items()}

# ── 对拍 ──────────────────────────────────────────────────────
allk = set(eA) | set(merged)
diffs = [(k, eA.get(k, 0.0), merged.get(k, 0.0)) for k in allk
         if abs(eA.get(k, 0.0) - merged.get(k, 0.0)) > 1e-9]
print(f"\n[等价性] 边总数 {len(allk)}，一致 {len(allk) - len(diffs)}，"
      f"差异 {len(diffs)}")
if diffs:
    from collections import Counter
    cc = Counter()
    for (i, k, j), va, vb in diffs:
        cc[(round(va, 1), round(vb, 1))] += 1
    print("  差异值分布:", dict(cc))
    print("  样例:", diffs[:5])
    ok = False
else:
    ok = True
    print("  ✅ 切块 ≡ 串行 逐边等价")
print(f"  耗时 {__import__('time').time() - t0:.0f}s，结论：{'✅ 可切块' if ok else '❌ 不等价'}")
