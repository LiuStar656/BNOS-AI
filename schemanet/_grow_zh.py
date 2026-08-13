# -*- coding: utf-8 -*-
"""Stage 0-1 增量成长：先学常用字，再学常用词（同一网络增量训练）。

需求（用户 2026-08-09）："先收集常用汉字表、常用词组表来训练，
就像人先学字、再学词、再学句一样，然后模型要增量训练。"

- Stage 0（字级）：3500 常用字，分配制模式（k=4/字），跟读复述
  → 快照 v1.0 = a（字级）
- Stage 1（词级）：神经元扩容（分配制自动 expand）→ 10000 常用词
  分配模式，词训练 = 注入 词模式 ∪ 组成字模式 → 学词↔字双向连接
  （"苹果" ↔ "苹""果"；输入"苹果"唤起组成字，输入"苹"唤起"苹果"）
  → 快照 v2.0 = a+1（词级，字级知识 100% 保留）
- 增量验收：词复述 ≥0.95 + 词→字唤起 + 字复述不回退（零遗忘）

2026-08-09 性能修正（级联放大根因）：
  wta_k 必须等于注入目标神经元数（字=4，词∪字=词4+组成字4×字长），
  否则 WTA 会把无关神经元拉入共发放，Hebbian 全连接 → 边数爆炸；
  跟读是独立事件，注入前清 pre_trace，防上一个词的 STDP 痕迹污染；
  训练只注入一步共发放（max_steps=1）——传播是检索阶段的动作，
  训练阶段传播会把共享字词模式（"果"→苹果/果汁/如果）级联唤起，
  造成 O(级联²) 的 Hebbian 写入。

用法：python _grow_zh.py
"""

import json
import time
from pathlib import Path

import numpy as np

from schema_net import build_pulse
from snapshot import save_snapshot
from sparse_net import SparseSchemaNet, allocate_pats

DATA = Path(__file__).parent / "data" / "curriculum"

K = 4              # 每字/词模式神经元数
N0 = 16384         # Stage 0 初始神经元（3500 字 × 4 = 14000，留余量）
R0 = 10            # 字跟读轮数（"读的越多印象越足"）
R1 = 8             # 词跟读轮数
WTA_WORD_MAX = 20  # 词训练 WTA 上限（词4 + 最长 4 字 × 4 = 20）
EVAL_N = 200       # 字复述验收抽样
EVAL_W = 300       # 词复述验收抽样
SEED = 42


def run_train(ng, pulse):
    """跟读训练：注入一步共发放即学（目标神经元共发放 → Hebbian 学模式内/词↔字）。

    关键：不传播、清跨词 trace——传播/痕迹会让共享字的其它词模式
    混入共发放，Hebbian 把它们全部两两连接（边数爆炸）。"""
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)          # 跟读独立事件，防 STDP 跨词污染
    ng.step(pulse, slot=0)


def run_recall(ng, pulse, max_steps=10):
    """冻结态检索：注入 + 传播至收敛，返回发放神经元集合（零学习改动）。"""
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)
    gate = ng.learn_gate
    ng.learn_gate = False                  # 检索冻结：物理零改动
    fired = set()
    ng.step(pulse, slot=0)
    fired |= set(np.where(ng.spikes > 0)[0])
    for _ in range(max_steps):
        ng.step(np.zeros(ng.n), slot=0)
        now = set(np.where(ng.spikes > 0)[0])
        fired |= now
        if not now:
            break
    ng.learn_gate = gate
    return fired


def fire_ratio(fired, neurons):
    return len(fired & set(neurons)) / max(1, len(neurons))


def recall_words(ng, pats, units, wta_k):
    """复述率：输入单元模式 → 该单元模式神经元回响比例（抽样均值）。"""
    ng.wta_k = wta_k
    tot = hit = 0
    for u in units:
        p = np.array(pats[u])
        fired = run_recall(ng, build_pulse(ng.n, p))
        tot += 1
        hit += fire_ratio(fired, p)
    return hit / max(1, tot)


def word_to_chars(ng, pats, words, wta_k):
    """词→字唤起：输入词模式 → 组成字模式被唤起的比例。"""
    ng.wta_k = wta_k
    tot = hit = 0
    for w in words:
        chars = [c for c in w if c in pats]
        if not chars:
            continue
        fired = run_recall(ng, build_pulse(ng.n, pats[w]))
        tot += len(chars)
        hit += sum(fire_ratio(fired, pats[c]) for c in chars)
    return hit / max(1, tot)


def main():
    hanzi = json.loads((DATA / "stage0_hanzi.json").read_text(encoding="utf-8"))
    words = json.loads((DATA / "stage1_common_words.json").read_text(encoding="utf-8"))
    print(f"常用字 {len(hanzi)}，常用词 {len(words)}")

    ng = SparseSchemaNet(n=N0, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=16.0, wta_k=K, noise_p=0.06, noise_amp=0.5,
                         refractory=1, rng=np.random.default_rng(SEED))

    # ══ Stage 0：字级（分配制 + 跟读复述）══
    pats, cursor = allocate_pats(ng, hanzi, K)
    print(f"\n[Stage 0] 字模式分配: {len(pats)} 字 × k={K}，cursor={cursor}，n={ng.n}")
    t0 = time.time()
    for r in range(R0):
        for ch in hanzi:
            ng.wta_k = K                   # 字训练：WTA = 模式规模（无干扰名额）
            run_train(ng, build_pulse(ng.n, pats[ch]))
        print(f"  [Stage0] 轮 {r + 1}/{R0} 完成（{time.time() - t0:.0f}s）", flush=True)

    # Stage 0 验收 + 快照 v1.0（a：字级）
    eval_hanzi = list(np.random.default_rng(7).choice(hanzi, EVAL_N, replace=False))
    r0 = recall_words(ng, pats, eval_hanzi, K)
    print(f"[Stage 0] 字复述率（抽样 {EVAL_N}）: {r0:.3f}")
    metrics = {"char_recall": round(r0, 4), "char_total": len(hanzi)}
    save_snapshot(ng, tag="1.0 = a 字级（3500 常用字跟读）", metrics=metrics,
                  vocab=hanzi, pats=pats, cursor=cursor)

    # ══ Stage 1：词级（扩容 + 词↔字连接）══
    pats_w, cursor = allocate_pats(ng, words, K, cursor)   # 自动 expand
    pats.update(pats_w)
    print(f"\n[Stage 1] 词模式分配: {len(pats_w)} 词 × k={K}，cursor={cursor}，"
          f"n={ng.n}（扩容 {ng.n - N0}）")
    t1 = time.time()
    for r in range(R1):
        for w in words:
            chars = [c for c in w if c in pats]
            neurons = list(pats[w]) + [i for c in chars for i in pats[c]]
            ng.wta_k = len(neurons)        # 词训练：WTA = 目标数（词4 + 组成字）
            run_train(ng, build_pulse(ng.n, neurons))
        print(f"  [Stage1] 轮 {r + 1}/{R1} 完成（{time.time() - t1:.0f}s）", flush=True)

    # Stage 1 验收 + 快照 v2.0（a+1：词级）
    eval_words = list(np.random.default_rng(8).choice(words, EVAL_W, replace=False))
    rw = recall_words(ng, pats, eval_words, WTA_WORD_MAX)
    w2c = word_to_chars(ng, pats, eval_words, WTA_WORD_MAX)
    r0_after = recall_words(ng, pats, eval_hanzi, K)       # 零遗忘：字复述不回退
    print(f"\n[Stage 1] 词复述率（抽样 {EVAL_W}）: {rw:.3f}")
    print(f"[Stage 1] 词→字唤起率: {w2c:.3f}（学到的「苹果」↔「苹」「果」连接）")
    print(f"[Stage 1] 字复述率（零遗忘验收，Stage0={r0:.3f}）: {r0_after:.3f} "
          f"{'✅ 不回退' if r0_after >= r0 - 0.01 else '❌ 回退!'}")
    metrics = {"char_recall": round(r0_after, 4),
               "char_recall_before": round(r0, 4),
               "word_recall": round(rw, 4), "word_to_char": round(w2c, 4),
               "word_total": len(words), "n": ng.n}
    save_snapshot(ng, tag="2.0 = a+1 词级（10000 常用词跟读，扩容增量）",
                  metrics=metrics, vocab=hanzi + words, pats=pats,
                  cursor=cursor)


if __name__ == "__main__":
    main()
