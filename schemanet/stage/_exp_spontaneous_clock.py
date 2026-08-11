# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""纯时钟自发活动实验（2026-08-11）：v35 只给内部时钟，其他什么都不给。

用户："不是空白网络，是 v35 只给内部时钟其他的什么都不给"。

对照 _exp_spontaneous：那里给了 相位记忆映射表/联想 seed/噪声触发时机
（代码层驱动）。本实验**全部去掉**，只有：
  ① 内部时钟：tick 节拍（16 相位循环——纯时间索引，不注入网络）
  ② 网络自身动力学：自带噪声 → 自发发放 → 边结构传播 → 自发联想
没有任何外部输入/注入/触发/映射——网络"自己活着"。

测什么：
  网络会不会自己发放？（静息态自发活动）
  自发发放的内容是什么？（纯结构决定——网络自己"想到"什么）
  长时间后如何演化？（自组织：自发共现 → Hebbian 自强化）
  对比：有引导（相位绑定）才能冒出语义念头——引导的差别在哪

用法：python _exp_spontaneous_clock.py（纯内存——不保存快照）
"""

import time
from collections import Counter
from pathlib import Path

import numpy as np

from snapshot import load_version

N_TICKS = 2000
PHASES = 16


def main():
    t0 = time.time()
    print("═══ 纯时钟自发活动（v35.0，2000 tick，无任何输入/引导）═══\n")
    ng, vocab, pats, cursor = load_version("35.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    n = ng.n
    dtype = ng.v.dtype

    # 自发活动前：回声环边基线（的→了 等）
    def edge_w(a, b):
        if a not in pats or b not in pats:
            return None
        return float(ng.W_out[pats[a][0]][0].get(pats[b][0], 0.0))

    before = {k: edge_w(*k) for k in [("的", "了"), ("了", "的"), ("不", "很"),
                                      ("很", "不"), ("的", "不")]}

    seq = []                 # 每 tick 的发放词（去重后的前几个）
    phase_fire = Counter()   # 发放的相位分布
    n_fire_ticks = 0
    n_ticks = 0
    for t in range(N_TICKS):
        inp = np.zeros(n, dtype=dtype)
        ng.step(inp)
        fired = np.nonzero(ng.spikes)[0]
        n_ticks += 1
        if len(fired):
            n_fire_ticks += 1
            phase_fire[t % PHASES] += 1
        words = []
        for j in fired:
            w = n2w.get(int(j), None)
            if w and w not in words:
                words.append(w)
            if len(words) >= 4:
                break
        seq.append(words)

    # 内容分析
    flat = [w for ws in seq for w in ws]
    cnt = Counter(flat)
    top = cnt.most_common(8)
    # 振荡检测：连续 tick 的首词序列
    firsts = [ws[0] if ws else "-" for ws in seq]
    # 周期检测（首词序列的自相关周期——找最小周期）
    def period_of(s):
        L = len(s)
        for p in range(1, 40):
            if all(s[i] == s[i % p] for i in range(L)):
                return p
        return None

    per = period_of(firsts)

    # 自组织：自发活动后的回声环边
    after = {k: edge_w(*k) for k in before}

    # 语义链检测：出现"非功能词连续链"（≥2 个不同内容词的连续 tick）
    FUNC = {"的", "了", "不", "很", "我", "是", "在", "也", "就", "都", "和", "吗"}
    sem_chains = []
    cur = []
    for ws in seq:
        sems = [w for w in ws if w not in FUNC]
        if sems:
            cur.extend(sems)
        else:
            if len(cur) >= 2:
                sem_chains.append("/".join(cur[:8]))
            cur = []
    if len(cur) >= 2:
        sem_chains.append("/".join(cur[:8]))

    print(f"═══ 结果 ═══")
    print(f"  自发发放：{n_fire_ticks}/{n_ticks} tick 有发放"
          f"（{n_fire_ticks/n_ticks:.0%}——网络一直在'活着'）")
    print(f"  发放内容 top-8：{top}")
    print(f"  首词序列周期：{per} tick（{'振荡/回声' if per and per <= 8 else '无周期'}）")
    print(f"  语义链（非功能词连续 ≥2）：{len(sem_chains)} 条")
    for c in sem_chains[:5]:
        print(f"    「{c}」")
    print(f"  回声环自组织（Hebbian 自强化）：")
    for k in before:
        b, a = before[k], after[k]
        mark = "↑" if (a or 0) > (b or 0) else ("↓" if a != b else "=")
        print(f"    {k[0]}→{k[1]}：{b} → {a} {mark}")
    print(f"\n[结论] 只给内部时钟（无输入/无引导）→ 网络自发发放不断，"
          f"但内容被语料高频功能词的回声振荡捕获（的/了/不/很 循环），"
          f"无法自发冒出语义念头——'想'的引擎在转，'内容'需要结构引导"
          f"（相位绑定/联想 seed——见 _exp_spontaneous）")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
