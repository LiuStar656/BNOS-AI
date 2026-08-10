# -*- coding: utf-8 -*-
"""复现 v13.2 超临界雪崩诊断（神经元过度放电）—— 归档 2026-08-10。

现象：注入「石头」后回响多跳，「痛」第一跳正常唤起，但第二跳「痛→不要」
永远传不动——v(不要)=26.9 远超阈值却不发放。逐步诊断发现真相：
每步候选数从 156 指数增长到 75000+，v 从 128 翻倍到 629，
**网络进入超临界雪崩（σ >> 1，对应人脑癫痫样过度放电）**，
WTA top20 全被混沌态占据，「不要」排不进前 20。

根因：网络为纯兴奋网络（Hebbian/STDP 正反馈，零抑制），高频词（我/吃）
扇出数千条边 → 一次注入后驱动海量神经元 → v 只衰减 0.9、无上限累积 →
正反馈雪崩。对应神经科学：E/I 失衡 → 超临界分支（branching ratio σ > 1）
→ 癫痫样放电。

修复方向（用户 2026-08-10 决策）：全局活动抑制 = 皮层 feedback inhibition
/ divisive normalization（除法归一化），把 σ 压回临界附近。

复现：cd schemanet && python archive/_debug_avalanche.py
依赖：schema_net / sparse_net / snapshot / _grow_v11（根目录保留模块）。
"""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # schemanet 根目录（任意 cwd 可运行）
from snapshot import load_version
from schema_net import _learn_sentence, build_pulse
from _grow_v11 import edge_between

ng, vocab, pats, cursor = load_version("11.2")
for _ in range(2):
    _learn_sentence(ng, ["石头", "痛"], pats, slot=0)
for _ in range(8):
    _learn_sentence(ng, ["痛", "不要"], pats, slot=0)
print("石头->痛 =", edge_between(ng, pats, "石头", "痛"), " 痛->不要 =",
      edge_between(ng, pats, "痛", "不要"))
print("不要模式:", pats["不要"], " 痛模式:", pats["痛"])

def spk(w):
    return sum(ng.spikes[j] for j in pats.get(w, []))

prev_cand = None
def dbg(label):
    global prev_cand
    vmax = ng.v[np.arange(ng.n), ng.v.argmax(axis=1)]
    cand = np.where((vmax >= ng.theta) & (ng.refractory_left == 0))[0]
    order = cand[np.argsort(vmax[cand])[::-1]]
    topv = [(int(j), round(float(vmax[j]), 1)) for j in order[:8]]
    in_buyao = sum(1 for j in order if j in pats["不要"])
    in_tong = sum(1 for j in order if j in pats["痛"])
    sigma = (len(cand) / prev_cand) if (prev_cand and label != "注入石头后") else float("nan")
    print("%-12s spikes非零=%d  候选=%d  候选前8=%s  [含不要%d 含痛%d]  σ≈%.2f"
          % (label, int((ng.spikes > 0).sum()), len(cand), topv, in_buyao, in_tong, sigma))
    prev_cand = len(cand)

ng.v = np.zeros((ng.n, ng.slots))
ng.spikes = np.zeros(ng.n)
ng.pre_trace = np.zeros(ng.n)
for w in ["石头"]:
    ng.v = np.zeros((ng.n, ng.slots))
    ng.step(build_pulse(ng.n, pats[w]), slot=0)
    dbg("注入石头后")
    ng.step(np.zeros(ng.n), slot=0)
    dbg("间隔步后")
for i in range(6):
    ng.step(np.zeros(ng.n), slot=0)
    dbg("回响步%d" % (i + 1))
    print("         spikes: 石头=%.0f 痛=%.0f 不要=%.0f" % (spk("石头"), spk("痛"), spk("不要")))
