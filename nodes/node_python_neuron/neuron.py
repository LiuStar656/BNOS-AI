# -*- coding: utf-8 -*-
"""
BNOS 定式网络（SchemaNet）第一版 — 复现"反复经历形成定式"

核心命题：反复输入同一个数据，第一次可能跑偏，次数多了就会形成一个定式。

机制（全部矩阵运算，numpy 向量化）：
  ① 积分-发放：v = v·λ + 注入 + W@spikes；v≥θ 且 WTA 选前 k 强 → 发放，发放后复位
  ② Hebbian：共同发放 → 连接强化（排除自连接，w_max 截断）
  ③ 噪声探索：每步低概率弱脉冲，让空神经元有机会参与竞争
  ④ 初始全 0 权重：权重从交互中产生，不提前赋予
  ⑤ 满槽覆盖：每神经元槽容量有限（slot_cap），容量没满 → 定式原样保留
     （久不复习也不洗掉，封存保留可复活）；满了 → 从最弱连接开始挤掉
     （人脑装不下所有知识，容量压力下旧弱记忆被篡改/覆盖）

实验：模式 A × 20 → 模式 B × 20 → 模式 C（与 A/B 部分重叠）× 20 → 混合验证
指标：组装纯度、A/B 保留率（串扰）、空神经元转化曲线、枯竭。

用法：python schema_net.py
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np


# ════════════════════════════════════════════════════════════════
#  定式网络（SchemaNet）核心
# ════════════════════════════════════════════════════════════════

class SchemaNet:
    """动态定式网络（SchemaNet）：积分-发放 + WTA + Hebbian + 噪声探索 + 内部多槽。

    内部多槽（slots>1）：每个神经元内部有 m 个独立状态槽，不同情境的输入
    打到不同槽，Hebbian 只强化主导槽 → 同一神经元可同时承载多个模式而不
    互相覆盖（"神经元内部的空间"）。slots=1 时退化为单槽（原版行为）。
    """

    def __init__(self, n=32, slots=1, theta=1.0, membrane_decay=0.9, eta=0.1,
                 w_max=2.0, wta_k=3, noise_p=0.06, noise_amp=0.6,
                 weight_decay=0.0, slot_cap=0.0, learn_gate=True,
                 stdp_pre=0.0, stdp_neg=0.0, trace_decay=0.5, rng=None):
        self.n = n
        self.slots = slots
        self.theta = theta
        self.membrane_decay = membrane_decay
        self.eta = eta
        self.w_max = w_max
        self.wta_k = wta_k
        self.noise_p = noise_p
        self.noise_amp = noise_amp
        self.weight_decay = weight_decay  # 旧机制：慢衰减（默认 0，已被满槽覆盖取代）
        self.slot_cap = slot_cap          # 满槽覆盖：每神经元槽的连接总强度上限（0=不设限）
        self.learn_gate = learn_gate      # 学习门：True=学习态（权重实时更新）；
                                          # False=冻结态（纯检索，权重物理零改动）
        self.stdp_pre = stdp_pre          # STDP 时序：前驱(上步发放)→后继(当前发放) 强化幅度
                                          # （0=关闭；学序列 token 转移用，默认全关不影响静态实验）
        self.stdp_neg = stdp_neg          # STDP 反序弱化（LTD）幅度（0=关闭）
        self.trace_decay = trace_decay    # 发放痕迹衰减：STDP 前驱 = 最近几步发放的衰减痕迹
                                          # （eligibility trace 简化版；痕迹按阈值筛选 → 只学相邻转移）
        self.trace_thres = 0.3            # 痕迹筛选阈值（< 阈值的陈旧痕迹不参与 STDP）
        self.rng = rng or np.random.default_rng()
        self.reset()

    def reset(self):
        """初始空白：权重全 0，权重从交互中产生。"""
        self.v = np.zeros((self.n, self.slots))
        self.W = np.zeros((self.n, self.slots, self.n))  # [神经元, 槽, 入连接]
        self.spikes = np.zeros(self.n)
        self.last_k_star = np.zeros(self.n, dtype=int)  # 上一步各神经元主导槽
        self.pre_trace = np.zeros(self.n)  # 发放痕迹（STDP 前驱）：最近几步发放的衰减累积
        self.evictions = 0  # 累计被挤掉的连接数（覆盖强度观测）

    def step(self, input_pulse, slot=0):
        """单步动力学：积分 → WTA 发放 → 主导槽 Hebbian 强化。

        input_pulse 打在指定 slot（情境通道）；噪声驱动所有槽。
        传播按主导槽分桶：发放神经元只把信号传给同槽接收方（情境化传播，
        防止跨情境拖动）。
        """
        slot = min(slot, self.slots - 1)  # 槽越界保护（单槽时所有输入都进槽 0）
        noise = (self.rng.random(self.n) < self.noise_p) * self.noise_amp
        self.v = self.v * self.membrane_decay + noise[:, None]
        self.v[:, slot] += input_pulse

        # 分槽传播：上一发放步中主导槽为 k 的神经元，只驱动接收方的槽 k
        if self.spikes.any():
            drive = np.zeros((self.n, self.slots))
            for k in range(self.slots):
                senders = self.spikes * (self.last_k_star == k)
                if senders.any():
                    drive[:, k] += self.W[:, k, :] @ senders
            self.v += drive

        # 主导槽：每个神经元取电位最强的槽
        k_star = self.v.argmax(axis=1)
        vmax = self.v[np.arange(self.n), k_star]

        candidates = np.where(vmax >= self.theta)[0]
        if len(candidates) > self.wta_k:
            top = candidates[np.argsort(vmax[candidates])[::-1][: self.wta_k]]
        else:
            top = candidates

        new_spikes = np.zeros(self.n)
        if len(top):
            new_spikes[top] = 1.0
            if self.learn_gate:  # 学习态才改权重；冻结态只读（识别/检索照常）
                # Hebbian：共同发放对 (i,j)，强化 i 的主导槽 → j 的连接
                a = top[:, None]          # 发放神经元 i
                b = k_star[top][:, None]  # i 的主导槽
                c = top[None, :]          # 发放神经元 j
                vals = np.full((len(top), len(top)), self.eta)
                np.fill_diagonal(vals, 0.0)  # 排除自连接
                self.W[a, b, c] += vals
                # STDP 时序：上一步及更早的发放痕迹（前驱，先发）→ 当前发放（后继，后发）
                # 强化 W[后继 ← 前驱]，学"先 X 后 Y"的转移；反序弱化压 LTD 污染。
                # 前驱用发放痕迹（trace，衰减累积）而非严格上一步：间隔步内定式
                # 可能不发放，痕迹能跨步保留前驱；阈值筛选掉非相邻的陈旧痕迹
                # （trace_decay=0.5 → 只学相邻转移，二级转移痕迹被滤掉）。
                if (self.stdp_pre > 0 or self.stdp_neg > 0) and self.pre_trace.any():
                    pre_idx = np.where(self.pre_trace > self.trace_thres)[0]  # 先发的前驱痕迹
                    # ① 前驱→后继：W[top_j, k_j, pre_i] += stdp_pre
                    if self.stdp_pre > 0:
                        jj = top[:, None]                       # 后继神经元
                        kk = k_star[top][:, None]               # 后继主导槽
                        pp = pre_idx[None, :]                   # 前驱
                        sp_vals = np.full((len(top), len(pre_idx)), self.stdp_pre)
                        sp_vals[jj == pp] = 0.0                 # 排除自连接（同一神经元连发放）
                        self.W[jj, kk, pp] += sp_vals
                    # ② LTD：当前发放（后发）→ 前驱的入连接反序弱化
                    #    W[pre_i, k_i, top_j] -= stdp_neg（顺序反了 → 压下去）
                    if self.stdp_neg > 0:
                        ii = pre_idx[:, None]                   # 前驱神经元
                        kk = k_star[pre_idx][:, None]           # 前驱主导槽
                        jj = top[None, :]                       # 后继
                        neg_vals = np.full((len(pre_idx), len(top)), self.stdp_neg)
                        neg_vals[ii == jj] = 0.0                # 排除自连接
                        self.W[ii, kk, jj] -= neg_vals
                self.W = np.clip(self.W, 0.0, self.w_max)
                if self.weight_decay:
           return new_spikes # pyright: ignore[reportUndefinedVariable] (1.0 - self.weight_decay)  # 旧机制（仅显式 --decay 时启用）
                if self.slot_cap > 0:
                    self._enforce_slot_capacity()        # 满槽覆盖：容量内不动，满了挤掉最弱

        self.v[top, :] = 0.0  # 发放神经元全槽复位
        self.spikes = new_spikes
        self.last_k_star = k_star
        self.pre_trace = self.pre_trace * self.trace_decay + new_spikes  # 发放痕迹累积
        return new_spikes

    def _enforce_slot_capacity(self):
        """满槽覆盖：神经元槽的连接总强度超过 slot_cap 时，从最弱连接开始
        挤掉，直到回到上限内。

        设计（取代慢衰减，对应"人的大脑不可能装下所有知识，可以被篡改"）：
          - 容量没满 → 权重原样保留。久不复习的定式不会被慢慢洗掉（封存保留、
            可复活），遗忘不是线性衰减，是"装得下就不动"。
          - 容量满了 → 新学习挤掉最弱连接（"槽满了就覆盖"），旧弱记忆被篡改。
        """
        sums = self.W.sum(axis=2)  # [n, slots] 每神经元槽连接总强度
        over = np.argwhere(sums > self.slot_cap)
        for i, k in over:
            row = self.W[i, k]
            if row.sum() <= self.slot_cap:
                continue
            order = np.argsort(row)  # 最弱在前
            s = row.sum()
            for j in order:
                if s <= self.slot_cap:
                    break
                s -= row[j]
                if row[j] > 0:
                    self.evictions += 1
                row[j] = 0.0

    def run_experience(self, input_pulse, slot=0, max_steps=10):
        """喂入一个经历：注入 + 内部传播至收敛，返回本经历激活的神经元集合。

        经历间从静息开始（v 清零），静息步仍保留噪声（背景活动）。
        """
        self.v = np.zeros((self.n, self.slots))
        self.spikes = np.zeros(self.n)

        fired = set()
        self.step(input_pulse, slot=slot)
        fired |= set(np.where(self.spikes > 0)[0])

        for _ in range(max_steps):
            self.step(np.zeros(self.n), slot=slot)
            now = set(np.where(self.spikes > 0)[0])
            fired |= now
            if not now:  # 无发放 → 稳定
                break
        return fired


# ════════════════════════════════════════════════════════════════
#  实验
# ════════════════════════════════════════════════════════════════

CONFIG = {
    "n": 32,
    "slots": 4,            # 每神经元内部槽数（多槽为基本架构，单槽已废弃：
                           # 实验证明单槽下组合不可表示——要么融合成超组装要么爆炸）
    "theta": 1.0,
    "membrane_decay": 0.9,
    "eta": 0.1,
    "w_max": 2.0,
    "wta_k": 2,
    "noise_p": 0.06,
    "noise_amp": 0.5,    # 噪声卫生：0.9×0.5+0.5=0.95<θ，杜绝连续两步噪声越过阈值
                         # 触发伪发放（0.6 时会越过；decay=0 后伪发放的微小连接永久累积）
    "weight_decay": 0.0,   # 旧机制：慢衰减（默认关闭，见 slot_cap）
    "slot_cap": 8.0,       # 满槽覆盖：每神经元槽连接总强度上限（0=不设限）。
                           # 容量没满 → 定式原样保留（不复习也不洗掉）；
                           # 满了 → 从最弱连接开始挤掉（槽满了就覆盖）。
    "seed": 42,
    "times_per_phase": 20,   # 每阶段反复经历次数
    "verify_rounds": 3,      # 混合验证每模式轮数
    "alphabet_k": 2,         # 字母实验中每个字母的稀疏神经元数
    # 模式定义（与 A/B 部分重叠：C 与 A 共享 3，与 B 共享 25）
    "pattern_a": [3, 17],
    "pattern_b": [9, 25],
    "pattern_c": [3, 25],
    # 情境槽映射：不同情境的输入打到神经元内部不同槽
    "slot_a": 0,
    "slot_b": 0,
    "slot_c": 1,
}


def jaccard(a, b):
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def build_pulse(n, idxs):
    p = np.zeros(n)
    p[idxs] = 1.0
    return p


def run_experiment(cfg):
    rng = np.random.default_rng(cfg["seed"])
    ng = SchemaNet(n=cfg["n"], slots=cfg.get("slots", 1), theta=cfg["theta"],
                     membrane_decay=cfg["membrane_decay"],
                     eta=cfg["eta"], w_max=cfg["w_max"], wta_k=cfg["wta_k"],
                     noise_p=cfg["noise_p"], noise_amp=cfg["noise_amp"],
                     weight_decay=cfg.get("weight_decay", 0.0),
                     slot_cap=cfg.get("slot_cap", 0.0), rng=rng)

    patterns = {
        "A": build_pulse(cfg["n"], cfg["pattern_a"]),
        "B": build_pulse(cfg["n"], cfg["pattern_b"]),
        "C": build_pulse(cfg["n"], cfg["pattern_c"]),
    }
    slots = {"A": cfg.get("slot_a", 0), "B": cfg.get("slot_b", 0),
             "C": cfg.get("slot_c", 0)}

    # ── 阶段训练：A × N → B × N → C × N ──
    records = {}
    assemblies = {}
    for phase in ["A", "B", "C"]:
        records[phase] = []
        for _ in range(cfg["times_per_phase"]):
            fired = ng.run_experience(patterns[phase], slot=slots[phase])
            records[phase].append(set(fired))
        assemblies[phase] = records[phase][-1]  # 该阶段定式快照

    # ── 指标 ──
    ga, gb, gc = assemblies["A"], assemblies["B"], assemblies["C"]

    # 空神经元转化：按经历次序累计首次激活
    seen = set()
    novelty_curve = []
    for phase in ["A", "B", "C"]:
        for s in records[phase]:
            seen |= s
            novelty_curve.append(len(seen))

    # A 阶段纯度：S_t 与定式 GA 的 Jaccard
    purity_a = [jaccard(s, ga) for s in records["A"]]
    # B 阶段：对 GB 收敛 + 对 GA 保留
    converge_b = [jaccard(s, gb) for s in records["B"]]
    retain_a_in_b = [jaccard(s, ga) for s in records["B"]]
    # C 阶段：对 GC 收敛 + 与 A/B 串扰
    converge_c = [jaccard(s, gc) for s in records["C"]]
    cross_ab_in_c = [max(jaccard(s, ga), jaccard(s, gb)) for s in records["C"]]
    # C 阶段空神经元征用：C 激活中不属于 A/B 组装的新神经元数（专属权重的种子）
    c_novel = [len(s - ga - gb) for s in records["C"]]

    # ── 混合验证：A B C 交替各 3 轮，测归属 ──
    verify = []
    order = ["A", "B", "C"] * cfg["verify_rounds"]
    for true_phase in order:
        fired = ng.run_experience(patterns[true_phase], slot=slots[true_phase])
        sims = {p: jaccard(fired, assemblies[p]) for p in ["A", "B", "C"]}
        pred = max(sims, key=sims.get) if max(sims.values()) >= 0.5 else "?"
        verify.append({
            "true": true_phase, "fired": sorted(int(x) for x in fired),
            "sim_A": round(sims["A"], 3), "sim_B": round(sims["B"], 3),
            "sim_C": round(sims["C"], 3), "pred": pred,
        })

    # ── 神经元身份倾向：每神经元对各槽的权重总强度（= 倾向谁）──
    propensity = ng.W.sum(axis=2)  # [n, slots]
    identity = {
        "matrix": propensity.tolist(),
        "active_neurons": [int(x) for x in seen],
    }

    return {
        "config": cfg,
        "assemblies": {p: [int(x) for x in v] for p, v in assemblies.items()},
        "records": {p: [[int(x) for x in s] for s in rec] for p, rec in records.items()},
        "purity_a": [round(x, 3) for x in purity_a],
        "converge_b": [round(x, 3) for x in converge_b],
        "retain_a_in_b": [round(x, 3) for x in retain_a_in_b],
        "converge_c": [round(x, 3) for x in converge_c],
        "cross_ab_in_c": [round(x, 3) for x in cross_ab_in_c],
        "c_novel": c_novel,
        "novelty_curve": novelty_curve,
        "empty_neurons": cfg["n"] - len(seen),
        "verify": verify,
        "identity": identity,
    }


# ════════════════════════════════════════════════════════════════
#  26 字母学习实验
# ════════════════════════════════════════════════════════════════

def gen_alphabet_patterns(cfg):
    """26 个字母，每字母 k 个随机稀疏神经元（固定种子，可复现）。

    26×2=52 个神经元位置会随机重叠 → 天然测试共享神经元下的容量与倾向性。
    """
    rng = np.random.default_rng(cfg["seed"] + 1000)
    k = cfg.get("alphabet_k", 2)
    letters = list("abcdefghijklmnopqrstuvwxyz")
    pats = {}
    for ch in letters:
        pats[ch] = sorted(rng.choice(cfg["n"], k, replace=False).tolist())
    return pats


def run_alphabet_experiment(cfg):
    """26 字母顺序学习 a→z：反复经历形成定式，验证倾向性激活与容量/遗忘。

    核心命题：输入 a 第一次可能跑偏，反复后稳定只激活"有 a 的神经元"。
    附带测试：26 模式共存容量、顺序学习的灾难性遗忘。
    """
    rng = np.random.default_rng(cfg["seed"])
    ng = SchemaNet(n=cfg["n"], slots=cfg.get("slots", 1), theta=cfg["theta"],
                     membrane_decay=cfg["membrane_decay"],
                     eta=cfg["eta"], w_max=cfg["w_max"], wta_k=cfg["wta_k"],
                     noise_p=cfg["noise_p"], noise_amp=cfg["noise_amp"],
                     weight_decay=cfg.get("weight_decay", 0.0),
                     slot_cap=cfg.get("slot_cap", 0.0), rng=rng)

    letters = list("abcdefghijklmnopqrstuvwxyz")
    pats = gen_alphabet_patterns(cfg)                     # {ch: [神经元]}
    pulses = {ch: build_pulse(cfg["n"], pats[ch]) for ch in letters}
    slots_n = cfg.get("slots", 1)

    def _slot(i):
        return i % slots_n                                # 字母 i 的情境槽

    # ── 顺序训练 a→z，每字母反复 times 次 ──
    records, assemblies = {}, {}
    for i, ch in enumerate(letters):
        records[ch] = []
        for _ in range(cfg["times_per_phase"]):
            fired = ng.run_experience(pulses[ch], slot=_slot(i))
            records[ch].append(set(fired))
        assemblies[ch] = records[ch][-1]                  # 该字母定式快照

    # ── 首字母 a 的倾向性：激活集合里有多少是"有 a 的神经元" ──
    set_a = set(pats["a"])
    tend_a = [round(len(s & set_a) / len(s), 3) if s else 1.0 for s in records["a"]]

    # ── 全局验证：a→z 全部学完后，26 字母各测 1 次判读 ──
    verify = []
    for i, ch in enumerate(letters):
        fired = ng.run_experience(pulses[ch], slot=_slot(i))
        sims = {c2: jaccard(fired, assemblies[c2]) for c2 in letters}
        pred = max(sims, key=sims.get) if max(sims.values()) >= 0.5 else "?"
        verify.append({
            "true": ch, "pred": pred,
            "fired": sorted(int(x) for x in fired),
            "tend": round(len(fired & set(pats[ch])) / len(fired), 3) if fired else 1.0,
        })

    seen = set()
    for rec in records.values():
        for s in rec:
            seen |= s

    # ── 组合测试：学完单字母后，一次输入两个字母会发生什么 ──
    # 组合输入 = 两字母神经元并集脉冲，打槽 0（编码器不知情，最贴近真实）
    combo_pairs = [("a", "b"), ("c", "d"), ("a", "z"), ("m", "n")]
    combos = []
    for ca, cb in combo_pairs:
        idxs = sorted(set(pats[ca]) | set(pats[cb]))
        fired = ng.run_experience(build_pulse(cfg["n"], idxs), slot=0)
        sims = {ch: jaccard(fired, assemblies[ch]) for ch in letters}
        best = max(sims, key=sims.get)
        combos.append({
            "pair": ca + cb, "fired": sorted(int(x) for x in fired),
            "sim_a": round(sims[ca], 3), "sim_b": round(sims[cb], 3),
            "best": best, "best_sim": round(sims[best], 3),
        })

    correct = sum(1 for v in verify if v["pred"] == v["true"])
    return {
        "config": cfg,
        "patterns": pats,
        "assemblies": {ch: [int(x) for x in v] for ch, v in assemblies.items()},
        "tend_a": tend_a,
        "verify": verify,
        "combos": combos,
        "correct": correct,
        "total": len(letters),
        "activated_neurons": len(seen),
    }


def print_alphabet_report(result):
    c = result["config"]
    print("=" * 62)
    print(f"26 字母学习实验  seed={c['seed']}  n={c['n']}  槽数={c['slots']}  "
          f"wta_k={c['wta_k']}  衰减={c['weight_decay']}  每字母次数={c['times_per_phase']}")
    print(f"每字母 {c.get('alphabet_k', 2)} 个随机神经元（52 个位置会随机重叠），顺序训练 a→z")
    print("=" * 62)

    print("\n【首字母 a 倾向性】激活集合中属于 a 目标神经元的比例（1=只激活有 a 的神经元）")
    ta = result["tend_a"]
    marks = [0, 4, 9, 19]
    marks = [t for t in marks if t < len(ta)]
    print("  " + "  ".join(f"第{t+1}次:{ta[t]}" for t in marks))
    print(f"  均值: {sum(ta)/len(ta):.3f}  末值: {ta[-1]}")

    print("\n【全局验证】26 字母在 a→z 全部学完后重测判读")
    wrong = [v for v in result["verify"] if v["pred"] != v["true"]]
    print(f"  正确: {result['correct']}/{result['total']}  错误: {len(wrong)}  "
          f"已激活神经元: {result['activated_neurons']}/{c['n']}")
    for v in wrong:
        print(f"    {v['true']} → 判定为 {v['pred']}  激活={v['fired']}  倾向性={v['tend']}")
    if not wrong:
        print("    （全部正确，无灾难性遗忘）")
    tend_all = [v["tend"] for v in result["verify"]]
    print(f"  26 字母平均倾向性: {sum(tend_all)/len(tend_all):.3f}")

    print("\n【组合测试】学完单字母后，一次输入两个字母（并集脉冲，打槽0）")
    print(f"  {'组合':<6}{'激活集合':<28}{'sim首字母':<10}{'sim次字母':<10}{'最匹配':<8}{'sim'}")
    for v in result["combos"]:
        print(f"  {v['pair']:<7}{str(v['fired']):<30}{v['sim_a']:<10}{v['sim_b']:<10}"
              f"{v['best']:<8}{v['best_sim']}")
    print("\n" + "=" * 62)


# ════════════════════════════════════════════════════════════════
#  组合学习实验：先学 abc 原子，再学组合序列（aa…ba）
# ════════════════════════════════════════════════════════════════

COMBO_SEQUENCE = ["aa", "bb", "cc", "ab", "ac", "bc",
                  "abc", "bca", "acb", "bac", "cab", "cb", "ca", "ba"]


def run_combo_experiment(cfg):
    """先学习 a/b/c 三个原子定式，再按序列反复输入组合。

    组合输入 = 成分字母神经元的并集脉冲（多集表示，天然顺序无关）。
    多槽架构：原子独占槽 0/1/2；非排列组合独占新槽；5 个排列共享一槽
    （并集输入等价，同一模式只学一遍）。组装判读用权重倾向矩阵
    （槽内显著连接），而非单次激活快照（WTA 单步只保留 2 个会抖动）。
    """
    rng = np.random.default_rng(cfg["seed"] + 2000)  # 独立于字母实验的模式

    # 槽分配：原子 0/1/2；排列共享槽 3；其余组合独占槽 4+
    slot_of = {"a": 0, "b": 1, "c": 2}
    perms = ("abc", "bca", "acb", "bac", "cab")
    perm_slot = 3
    next_slot = 4
    for token in COMBO_SEQUENCE:
        if token in perms:
            slot_of[token] = perm_slot
        else:
            slot_of[token] = next_slot
            next_slot += 1
    need_slots = next_slot
    cfg = dict(cfg)
    cfg["slots"] = max(cfg.get("slots", 1), need_slots)  # 多槽自适应

    ng = SchemaNet(n=cfg["n"], slots=cfg["slots"], theta=cfg["theta"],
                     membrane_decay=cfg["membrane_decay"], eta=cfg["eta"],
                     w_max=cfg["w_max"], wta_k=cfg["wta_k"],
                     noise_p=cfg["noise_p"], noise_amp=cfg["noise_amp"],
                     weight_decay=cfg.get("weight_decay", 0.0),
                     slot_cap=cfg.get("slot_cap", 0.0), rng=rng)

    # 原子 a/b/c：每字母 2 个随机神经元
    pats = {ch: sorted(rng.choice(cfg["n"], 2, replace=False).tolist()) for ch in "abc"}
    pulses = {ch: build_pulse(cfg["n"], pats[ch]) for ch in "abc"}

    def _pulse_for(token):
        idxs = sorted({i for ch in token for i in pats[ch]})
        return build_pulse(cfg["n"], idxs)

    # ── 阶段 1：先学原子 a、b、c（各占独立槽）──
    for ch in "abc":
        for _ in range(cfg["times_per_phase"]):
            ng.run_experience(pulses[ch], slot=slot_of[ch])

    # ── 阶段 2：按序列反复输入组合 ──
    for token in COMBO_SEQUENCE:
        for _ in range(cfg["times_per_phase"]):
            ng.run_experience(_pulse_for(token), slot=slot_of[token])

    # ── 权重倾向组装：槽内显著连接（>= 0.5×槽内最大）的神经元集合 ──
    propensity = ng.W.sum(axis=2)  # [n, slots]

    def assembly_of(k):
        col = propensity[:, k]
        mx = float(col.max())
        if mx <= 0:
            return set()
        return set(np.where(col >= 0.5 * mx)[0].tolist())

    atoms = {ch: assembly_of(slot_of[ch]) for ch in "abc"}
    combos = {t: assembly_of(slot_of[t]) for t in COMBO_SEQUENCE}

    # ── 原子保留：组合学习后单字母重测。判读用"首响应"（第一步输入的直接激活
    # 集合），而非 10 步回响并集——强自连接会让定式持续回响并把伪发放累积进并集
    # （仿真伪影：网络无抑制/不应期），首响应才是"认出 a"的自然读数。──
    atom_after = {}
    for ch in "abc":
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        first = ng.step(pulses[ch], slot=slot_of[ch])
        fired = set(np.where(first > 0)[0])
        atom_after[ch] = round(jaccard(fired, atoms[ch]), 3)

    # ── 排列响应：共享槽输入 5 种排列 → 激活集合是否一致（顺序无关）。
    # 用回响并集而非首响应：并集脉冲有 5 个候选，WTA 单步只留 2 个，需
    # 多步回响收集完整组装才能比较集合一致性。──
    perm_response = {}
    for p in perms:
        fired = ng.run_experience(_pulse_for(p), slot=slot_of[p])
        perm_response[p] = sorted(int(x) for x in fired)

    # ── 组合成分：覆盖度（组装含多少成分）与纯度（组装里多少是成分）──
    purity_cover, purity_in = {}, {}
    for token in COMBO_SEQUENCE:
        idxs = {i for ch in token for i in pats[ch]}
        s = combos[token]
        purity_cover[token] = round(len(s & idxs) / len(idxs), 3) if idxs else 1.0
        purity_in[token] = round(len(s & idxs) / len(s), 3) if s else 1.0

    # 槽总量 = 每槽连接总强度（propensity.sum(axis=0)），观测容量压力分布
    return {
        "config": cfg,
        "patterns": pats,
        "slot_of": slot_of,
        "atoms": {ch: sorted(v) for ch, v in atoms.items()},
        "combos": {t: sorted(v) for t, v in combos.items()},
        "atom_after": atom_after,
        "perm_response": perm_response,
        "perms": list(perms),
        "purity_cover": purity_cover,
        "purity_in": purity_in,
        "evictions": int(ng.evictions),
        "slot_totals": [round(x, 2) for x in propensity.sum(axis=0).tolist()],
    }


def print_combo_report(result):
    c = result["config"]
    print("=" * 62)
    print(f"组合学习实验  seed={c['seed']}  n={c['n']}  槽数={c['slots']}  "
          f"wta_k={c['wta_k']}  衰减={c['weight_decay']}  槽容量={c.get('slot_cap')}  "
          f"每组合次数={c['times_per_phase']}")
    print(f"原子 a/b/c={result['patterns']} → 阶段2 按序列反复输入组合")
    print("=" * 62)

    print("\n【原子定式】（权重倾向组装，>=0.5×槽内最大）")
    for ch, s in result["atoms"].items():
        print(f"  {ch}: {s}")

    print("\n【组合定式】（权重倾向组装）")
    print(f"  {'组合':<6}{'定式组装':<26}{'覆盖':<6}{'纯度'}")
    for t in COMBO_SEQUENCE:
        s = result["combos"][t]
        print(f"  {t:<7}{str(s):<28}{result['purity_cover'][t]:<6}{result['purity_in'][t]}")

    print("\n【排列响应】共享槽输入 5 种排列（并集输入等价 → 激活应一致，顺序无关）")
    resp = result["perm_response"]
    sets = [set(v) for v in resp.values()]
    for p, fired in resp.items():
        print(f"  {p}: {fired}")
    if all(s == sets[0] for s in sets):
        print("  → 5 种排列激活一致（顺序无关成立）")
    else:
        print("  → 5 种排列激活不一致！")

    print("\n【原子保留】组合学习后单字母重测（1=原子层未被覆盖）")
    print("  " + "  ".join(f"{ch}={v}" for ch, v in result["atom_after"].items()))

    print("\n【满槽覆盖观测】")
    totals = result["slot_totals"]
    print("  各槽连接总强度: " + "  ".join(f"槽{k}={v}" for k, v in enumerate(totals)))
    print(f"  累计挤掉连接数: {result['evictions']}"
          f"  （>0 说明有槽被撑满后发生了覆盖）")
    print("\n" + "=" * 62)


# ════════════════════════════════════════════════════════════════
#  冻结/学习双状态实验（学习门 learn_gate）
# ════════════════════════════════════════════════════════════════

def run_freeze_experiment(cfg):
    """冻结/学习双状态对照实验。

    设计：A、B 先学成定式（槽 0）→ C（与 A/B 各共享一个神经元）在同一槽
    反复输入制造干扰。
      组1 一直学习态：C 阶段权重照常更新 → 容量压力下 A/B 可能被篡改
      组2 冻结免疫：C 阶段 learn_gate=False → 权重物理零改动，A/B 原样
    两组从同一种子出发（噪声序列完全一致），唯一变量 = 学习门。

    指标：
      - A/B 组装保留率（倾向矩阵判读：干扰前后组装 Jaccard）
      - 冻结阶段 W 最大绝对差值（=0 → 物理零改动）
      - 冻结中 A 识别照常（首响应激活，检索不依赖学习门）
      - 解冻后 C 沉淀（槽 0 连接总强度上升 → 门可重新打开）
    """
    rng_seed = cfg["seed"] + 3000
    slot = 0  # A/B/C 全部打槽 0 → 同槽才有容量压力（干扰的本质）
    T = cfg["times_per_phase"]

    patterns = {
        "A": build_pulse(cfg["n"], cfg["pattern_a"]),
        "B": build_pulse(cfg["n"], cfg["pattern_b"]),
        "C": build_pulse(cfg["n"], cfg["pattern_c"]),
    }

    def _mk(seed):
        return SchemaNet(n=cfg["n"], slots=max(cfg.get("slots", 1), 1),
                           theta=cfg["theta"], membrane_decay=cfg["membrane_decay"],
                           eta=cfg["eta"], w_max=cfg["w_max"], wta_k=cfg["wta_k"],
                           noise_p=cfg["noise_p"], noise_amp=cfg["noise_amp"],
                           weight_decay=cfg.get("weight_decay", 0.0),
                           slot_cap=cfg.get("slot_cap", 0.0),
                           rng=np.random.default_rng(seed))

    def _assembly(ng):
        prop = ng.W.sum(axis=2)
        col = prop[:, slot]
        mx = float(col.max())
        if mx <= 0:
            return set()
        return set(np.where(col >= 0.5 * mx)[0].tolist())

    def _first_response(ng, key):
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        first = ng.step(patterns[key], slot=slot)
        return set(np.where(first > 0)[0])

    def _learn(ng, key, times):
        for _ in range(times):
            ng.run_experience(patterns[key], slot=slot)

    results = {}
    # 专属连接（方向：i 收 j 的信号强度）：C 干扰下最容易被挤/被稀释的弱链
    a_edges = [(cfg["pattern_a"][0], cfg["pattern_a"][1]),
               (cfg["pattern_a"][1], cfg["pattern_a"][0])]
    b_edges = [(cfg["pattern_b"][0], cfg["pattern_b"][1]),
               (cfg["pattern_b"][1], cfg["pattern_b"][0])]

    def _edges(ng):
        return {e: float(ng.W[e[0], slot, e[1]]) for e in a_edges + b_edges}

    for group in ("always_learn", "freeze"):
        ng = _mk(rng_seed)          # 同种子 → 两组噪声序列完全一致
        _learn(ng, "A", T)
        _learn(ng, "B", T)
        W_pre = ng.W.copy()
        asm_a_pre = _assembly(ng)
        asm_b_pre = _assembly(ng)
        evict_pre = ng.evictions
        edges_pre = _edges(ng)
        slot0_pre = float(ng.W.sum(axis=2)[:, slot].sum())
        recog_frozen = None

        if group == "freeze":
            ng.learn_gate = False            # 冻结：纯检索，权重零改动
            recog_frozen = [int(x) for x in _first_response(ng, "A")]  # 冻结中识别照常

        _learn(ng, "C", T)                   # 干扰（学习态 or 冻结态）
        W_post = ng.W.copy()
        evict_post = ng.evictions
        if group == "freeze":
            ng.learn_gate = True             # 解冻

        results[group] = {
            "frozen": group == "freeze",
            "asm_a_pre": sorted(asm_a_pre),
            "asm_a_post": sorted(_assembly(ng)),
            "asm_b_pre": sorted(asm_b_pre),
            "asm_b_post": sorted(_assembly(ng)),
            "retain_a": round(jaccard(asm_a_pre, _assembly(ng)), 3),
            "retain_b": round(jaccard(asm_b_pre, _assembly(ng)), 3),
            "w_max_diff_during_c": float(np.abs(W_post - W_pre).max())
                                   if group == "freeze" else None,
            "evictions_during_c": evict_post - evict_pre,
            "recog_a_frozen": recog_frozen,
            # 干扰前后专属连接保留率（post/pre：挤掉→0，强化→>1，未动→1）
            "edge_keep_a": [round(_edges(ng)[e] / max(edges_pre[e], 1e-9), 3)
                            for e in a_edges],
            "edge_keep_b": [round(_edges(ng)[e] / max(edges_pre[e], 1e-9), 3)
                            for e in b_edges],
            # 槽0 总强度变化：>0 → C 沉淀进了槽0（学习态），=0 → C 被挡在外面（冻结态）
            "slot0_delta": round(float(ng.W.sum(axis=2)[:, slot].sum()) - slot0_pre, 2),
        }

    # ── 解冻后继续学习：冻结期 C 不沉淀 → 解冻后 C 沉淀（门可重新打开）──
    ng2 = _mk(rng_seed + 1)
    _learn(ng2, "A", T)
    _learn(ng2, "B", T)
    ng2.learn_gate = False
    _learn(ng2, "C", T)          # 冻结期：C 不写权重
    slot0_frozen = float(ng2.W.sum(axis=2)[:, slot].sum())
    ng2.learn_gate = True        # 解冻
    _learn(ng2, "C", T)          # 解冻期：C 应沉淀
    slot0_reopen = float(ng2.W.sum(axis=2)[:, slot].sum())
    results["reopen"] = {
        "slot0_after_frozen_c": round(slot0_frozen, 2),
        "slot0_after_reopen_c": round(slot0_reopen, 2),
        "delta": round(slot0_reopen - slot0_frozen, 2),
        "asm_c": sorted(_assembly(ng2)),
    }
    results["config"] = cfg
    return results


def print_freeze_report(result):
    c = result["config"]
    T = c["times_per_phase"]
    print("=" * 62)
    print(f"冻结/学习双状态实验  seed={c['seed']}  n={c['n']}  "
          f"槽容量={c.get('slot_cap')}  每阶段次数={T}")
    print(f"A/B/C 全部打槽 0（同槽才有容量压力）；C 与 A/B 各共享一个神经元 = 干扰源")
    print("=" * 62)

    for label, key in (("组1 一直学习态", "always_learn"), ("组2 冻结免疫", "freeze")):
        g = result[key]
        print(f"\n【{label}】A×{T} → B×{T} → C×{T}")
        print(f"  A 组装: {g['asm_a_pre']} → {g['asm_a_post']}   保留={g['retain_a']}")
        print(f"  B 组装: {g['asm_b_pre']} → {g['asm_b_post']}   保留={g['retain_b']}")
        print(f"  A 专属连接保留: {g['edge_keep_a']}   B 专属连接保留: {g['edge_keep_b']}")
        print(f"  C 阶段 evictions（挤掉连接数）: {g['evictions_during_c']}"
              f"  槽0 强度增量: {g['slot0_delta']}（>0=C 沉淀进了槽0，=0=C 被挡在外面）")
        if g["frozen"]:
            print(f"  冻结阶段 W 最大绝对差值: {g['w_max_diff_during_c']}（0=物理零改动）")
            print(f"  冻结中 A 识别激活: {g['recog_a_frozen']}（检索不依赖学习门）")

    r = result["reopen"]
    print(f"\n【解冻后继续学习】冻结期 C×{T} → 解冻 → C×{T}")
    print(f"  槽0 连接总强度: 冻结期后={r['slot0_after_frozen_c']} → "
          f"解冻期后={r['slot0_after_reopen_c']}  增量={r['delta']}（>0=解冻后学习重新生效）")
    print(f"  C 组装: {r['asm_c']}")
    print("\n" + "=" * 62)


# ════════════════════════════════════════════════════════════════
#  序列学习实验（STDP 时序：token 转移）
# ════════════════════════════════════════════════════════════════

def run_sequence_experiment(cfg):
    """序列学习实验：验证定式网络（SchemaNet）能否学"先 X 后 Y"的 token 转移。

    机制：同步 STDP（δt=1 最近邻）——上一步发放的神经元（前驱）→ 当前
    发放（后继）强化 W[后继←前驱]。只强化正向 → "喂 a 唤起 b"成立、
    "喂 b 唤起 a"不成立（W[a←b] 从未强化）→ 顺序自动可区分。

    四组对照：
      组A 学 "ab"：前向唤起 b / 反向唤起 a（应≈0）
      组B 学 "ba"：镜像（控制组）
      组C 无 STDP：同结构学 "ab"，前向唤起应≈0（证明顺序记忆来自 STDP）
      链式 学 "abc"：喂 a → 逐级唤起 b、c（转移链）
    """
    rng = np.random.default_rng(cfg["seed"] + 4000)
    pats = {ch: sorted(rng.choice(cfg["n"], 2, replace=False).tolist()) for ch in "abc"}
    pulses = {ch: build_pulse(cfg["n"], pats[ch]) for ch in "abc"}
    slot = 0
    T = cfg["times_per_phase"]
    stdp_pre = cfg.get("stdp_pre", 0.0)
    stdp_neg = cfg.get("stdp_neg", 0.0)

    def _mk(pre, neg):
        return SchemaNet(n=cfg["n"], slots=max(cfg.get("slots", 1), 1),
                           theta=cfg["theta"], membrane_decay=cfg["membrane_decay"],
                           eta=cfg["eta"], w_max=cfg["w_max"], wta_k=cfg["wta_k"],
                           noise_p=cfg["noise_p"], noise_amp=cfg["noise_amp"],
                           weight_decay=cfg.get("weight_decay", 0.0),
                           slot_cap=cfg.get("slot_cap", 0.0),
                           stdp_pre=pre, stdp_neg=neg,
                           rng=np.random.default_rng(cfg["seed"] + 4001))

    def _learn_seq(ng, seq, times):
        for _ in range(times):
            ng.v = np.zeros((ng.n, ng.slots))
            ng.spikes = np.zeros(ng.n)
            ng.pre_trace = np.zeros(ng.n)            # 经历间清痕迹（防跨经历反向串扰）
            for ch in seq:
                ng.v = np.zeros((ng.n, ng.slots))    # 注入前清膜电位残留（防噪声越阈挤掉目标）
                ng.step(pulses[ch], slot=slot)       # 注入当前符号 → 发放
                ng.step(np.zeros(ng.n), slot=slot)   # 间隔步：痕迹衰减一步（只留相邻前驱）
            for _ in range(4):                       # 结尾回响收敛
                ng.step(np.zeros(ng.n), slot=slot)

    def _evoke(ng, ch, steps=2):
        """注入 cue，回响 steps 步，返回激活集合（不累积到噪声污染的程度）。"""
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.step(pulses[ch], slot=slot)
        fired = set(np.where(ng.spikes > 0)[0])
        for _ in range(steps):
            ng.step(np.zeros(ng.n), slot=slot)
            fired |= set(np.where(ng.spikes > 0)[0])
        return fired

    def _cover(ng, cue, target):
        fired = _evoke(ng, cue)
        return round(len(fired & set(pats[target])) / len(pats[target]), 3)

    def _edge_sum(ng, src, dst):
        return round(float(sum(ng.W[i, slot, j]
                               for i in pats[dst] for j in pats[src])), 2)

    results = {}
    for label, seq in (("A 学ab", "ab"), ("B 学ba", "ba")):
        ng = _mk(stdp_pre, stdp_neg)
        _learn_seq(ng, seq, T)
        results[label] = {
            "seq": seq, "pre": stdp_pre, "neg": stdp_neg,
            "fwd_evoke": _cover(ng, seq[0], seq[1]),   # 学过的方向：X → 唤起 Y
            "rev_evoke": _cover(ng, seq[1], seq[0]),   # 反方向：Y → 唤起 X
            "fwd_edge": _edge_sum(ng, seq[0], seq[1]),
            "rev_edge": _edge_sum(ng, seq[1], seq[0]),
        }

    ng = _mk(0.0, 0.0)          # 无 STDP 对照
    _learn_seq(ng, "ab", T)
    results["C 无STDP"] = {
        "seq": "ab", "pre": 0.0, "neg": 0.0,
        "fwd_evoke": _cover(ng, "a", "b"),
        "rev_evoke": _cover(ng, "b", "a"),
        "fwd_edge": _edge_sum(ng, "a", "b"),
        "rev_edge": _edge_sum(ng, "b", "a"),
    }

    ng = _mk(stdp_pre, stdp_neg)
    _learn_seq(ng, "abc", T)    # 链式：a→b→c 同时沉淀
    results["链式 abc"] = {
        "seq": "abc", "pre": stdp_pre, "neg": stdp_neg,
        "ab_evoke": _cover(ng, "a", "b"),
        "ac_evoke": _cover(ng, "a", "c"),   # b 被唤起后经 b→c 链路再唤起 c
        "bc_evoke": _cover(ng, "b", "c"),
        "ab_edge": _edge_sum(ng, "a", "b"),
        "bc_edge": _edge_sum(ng, "b", "c"),
        "ac_edge": _edge_sum(ng, "a", "c"),  # 无相邻经历 → 应≈0（只学相邻转移）
    }

    results["patterns"] = pats
    results["config"] = cfg
    return results


def print_seq_report(result):
    c = result["config"]
    T = c["times_per_phase"]
    print("=" * 62)
    print(f"序列学习实验  seed={c['seed']}  n={c['n']}  STDP前驱={c.get('stdp_pre',0)}  "
          f"LTD={c.get('stdp_neg',0)}  每序列次数={T}")
    print(f"符号 a/b/c = {result['patterns']}（各 2 个稀疏神经元，不重叠）")
    print("=" * 62)

    print("\n【顺序区分】fwd=学过的方向唤起  rev=反方向唤起（应≈0）")
    print(f"  {'组':<10}{'序列':<5}{'fwd唤起':<9}{'rev唤起':<9}{'fwd连接':<9}{'rev连接'}")
    for label in ("A 学ab", "B 学ba", "C 无STDP"):
        g = result[label]
        print(f"  {label:<11}{g['seq']:<6}{g['fwd_evoke']:<10}{g['rev_evoke']:<10}"
              f"{g['fwd_edge']:<10}{g['rev_edge']}")
    print("  （fwd 高、rev 低 → 顺序敏感成立；无 STDP 组 fwd 低 → 顺序记忆来自 STDP）")

    g = result["链式 abc"]
    print("\n【链式记忆】学 abc → 喂 a 逐级唤起")
    print(f"  a→b 唤起: {g['ab_evoke']}   a→c 唤起（经 b 链）: {g['ac_evoke']}   b→c 唤起: {g['bc_evoke']}")
    print(f"  转移连接强度: a→b={g['ab_edge']}  b→c={g['bc_edge']}  a→c={g['ac_edge']}"
          f"（a→c 无相邻经历 → 应≈0，只学相邻转移）")
    print("\n" + "=" * 62)


# ════════════════════════════════════════════════════════════════
#  输出：留档 + 控制台
# ════════════════════════════════════════════════════════════════

def save_run(result):
    """每次运行独立时间戳目录留档，禁止覆盖历史数据。"""
    run_dir = Path(__file__).parent / "runs" / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return run_dir


def print_report(result):
    c = result["config"]
    print("=" * 62)
    print(f"定式网络（SchemaNet）实验  seed={c['seed']}  n={c['n']}  槽数={c['slots']}  "
          f"wta_k={c['wta_k']}  η={c['eta']}  w_max={c['w_max']}  衰减={c['weight_decay']}")
    print(f"模式 A={c['pattern_a']}(槽{c.get('slot_a',0)})  B={c['pattern_b']}(槽{c.get('slot_b',0)})  "
          f"C={c['pattern_c']}(槽{c.get('slot_c',0)})  (C 与 A/B 各共享一个神经元)")
    print("=" * 62)

    print("\n【定式快照】（各阶段最后一次经历的激活集合）")
    for p, s in result["assemblies"].items():
        print(f"  {p}: {s}")

    print("\n【A 阶段纯度】S_t 与定式 A 的 Jaccard（1=完全重合）")
    pa = result["purity_a"]
    print(f"  第 1 次: {pa[0]}  第 5 次: {pa[4]}  第 10 次: {pa[9]}  "
          f"第 20 次: {pa[-1]}")
    print(f"  均值: {sum(pa)/len(pa):.3f}")

    print("\n【B 阶段】对定式 B 收敛 / 对定式 A 保留（串扰）")
    cb, ra = result["converge_b"], result["retain_a_in_b"]
    for t in (0, 4, 9, 19):
        print(f"  第 {t+1} 次: 收敛B={cb[t]:.3f}  保留A={ra[t]:.3f}")
    print(f"  收敛B均值: {sum(cb)/len(cb):.3f}  保留A均值: {sum(ra)/len(ra):.3f}")

    print("\n【C 阶段】对定式 C 收敛 / 与 A、B 串扰 / 空神经元征用")
    cc, xab = result["converge_c"], result["cross_ab_in_c"]
    for t in (0, 4, 9, 19):
        print(f"  第 {t+1} 次: 收敛C={cc[t]:.3f}  串扰AB={xab[t]:.3f}  "
              f"征用空神经元={result['c_novel'][t]}")
    print(f"  收敛C均值: {sum(cc)/len(cc):.3f}  串扰AB均值: {sum(xab)/len(xab):.3f}  "
          f"征用空神经元总和: {sum(result['c_novel'])}")

    print("\n【空神经元转化】累积已激活神经元数（0→32）")
    nv = result["novelty_curve"]
    marks = [0, 9, 19, 20, 29, 39, 40, 49, 59]
    line = "  " + " → ".join(str(nv[i]) for i in marks if i < len(nv))
    print(line)
    print(f"  最终已激活 {nv[-1]}，空神经元剩余 {result['empty_neurons']}（枯竭）")

    print("\n【混合验证】A B C 交替各 3 轮，按 Jaccard 判定归属")
    print(f"  {'真值':<4}{'激活集合':<24}{'simA':<6}{'simB':<6}{'simC':<6}{'判定':<5}")
    for v in result["verify"]:
        print(f"  {v['true']:<5}{str(v['fired']):<26}{v['sim_A']:<6}{v['sim_B']:<6}"
              f"{v['sim_C']:<6}{v['pred']:<5}")
    correct = sum(1 for v in result["verify"] if v["pred"] == v["true"])
    print(f"  归属正确率: {correct}/{len(result['verify'])}")

    print("\n【神经元身份倾向】每神经元对各槽的权重总强度（= 倾向谁）")
    ident = result["identity"]
    matrix = ident["matrix"]
    slots = result["config"]["slots"]
    head = "  神经元  " + "  ".join(f"槽{k}" for k in range(slots)) + "  主身份"
    print(head)
    for i in ident["active_neurons"]:
        row = [f"{matrix[i][k]:.2f}".rjust(5) for k in range(slots)]
        main = int(np.argmax(matrix[i]))
        print(f"  {i:>3}   {' '.join(row)}   槽{main}")

    print("\n" + "=" * 62)


if __name__ == "__main__":
    # 命令行可覆盖配置：python schema_net.py --wta_k 2 --decay 0 --seed 7
    parser = argparse.ArgumentParser(description="定式网络（SchemaNet）定式实验")
    parser.add_argument("--mode", choices=["abc", "alphabet", "combo", "freeze", "seq"],
                        default="abc",
                        help="abc=A/B/C；alphabet=26 字母；combo=先学 abc 再学组合；"
                             "freeze=冻结/学习双状态对照；seq=序列学习（STDP token 转移）")
    parser.add_argument("--n", type=int, default=None, help="神经元数量")
    parser.add_argument("--slots", type=int, default=None, help="每神经元内部槽数")
    parser.add_argument("--wta_k", type=int, default=None)
    parser.add_argument("--decay", type=float, default=None, help="权重慢衰减（旧机制）")
    parser.add_argument("--slot-cap", type=float, default=None, help="每神经元槽容量上限（0=不设限）")
    parser.add_argument("--stdp-pre", type=float, default=None, help="STDP 前驱→后继强化幅度（0=关）")
    parser.add_argument("--stdp-neg", type=float, default=None, help="STDP 反序弱化 LTD 幅度（0=关）")
    parser.add_argument("--noise_p", type=float, default=None, help="噪声概率")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--times", type=int, default=None, help="每阶段经历次数")
    parser.add_argument("--alphabet_k", type=int, default=None, help="每字母神经元数")
    args = parser.parse_args()

    cfg = dict(CONFIG)
    if args.n is not None:
        cfg["n"] = args.n
    if args.slots is not None:
        cfg["slots"] = args.slots
    if args.wta_k is not None:
        cfg["wta_k"] = args.wta_k
    if args.decay is not None:
        cfg["weight_decay"] = args.decay
    if args.slot_cap is not None:
        cfg["slot_cap"] = args.slot_cap
    if args.noise_p is not None:
        cfg["noise_p"] = args.noise_p
    if args.stdp_pre is not None:
        cfg["stdp_pre"] = args.stdp_pre
    if args.stdp_neg is not None:
        cfg["stdp_neg"] = args.stdp_neg
    if args.seed is not None:
        cfg["seed"] = args.seed
    if args.times is not None:
        cfg["times_per_phase"] = args.times
    if args.alphabet_k is not None:
        cfg["alphabet_k"] = args.alphabet_k

    # 实验留档：独立时间戳目录
    if args.mode == "alphabet":
        result = run_alphabet_experiment(cfg)
        print_alphabet_report(result)
    elif args.mode == "combo":
        result = run_combo_experiment(cfg)
        print_combo_report(result)
    elif args.mode == "freeze":
        result = run_freeze_experiment(cfg)
        print_freeze_report(result)
    elif args.mode == "seq":
        result = run_sequence_experiment(cfg)
        print_seq_report(result)
    else:
        result = run_experiment(cfg)
        print_report(result)
    run_dir = save_run(result)
    print(f"结果已留档: {run_dir}")
