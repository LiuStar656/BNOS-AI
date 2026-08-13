# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""工作记忆结构实验：循环回路（吸引子维持）vs 无循环（2026-08-11）。

用户："有没有办法让网络学会工作记忆"——工作记忆的神经机制 =
前额叶持续发放（delay activity）——靠循环连接自我维持。
网络现状：Hebbian 排除自连接——"饿"发放后衰减（3 tick 消失）。
实验：建循环回路（自连接/互连——W_out 直接建边）→ 注入后自持？

测量：注入「饿」→ 空白 N tick → 饿 的发放次数/激活（维持时长）
对照：无循环（基线衰减）
清除：注入新刺激 → 饿 是否被抑制（可清除性）

用法：python _exp_wm.py（纯内存）
"""

import numpy as np
from schema_net import build_pulse
from snapshot import load_version


def run(tag, ng, pats, n2w, build_loop=False, clear_at=None):
    if build_loop:
        # 建循环：饿 自连接（发放后自我驱动——delay activity）
        for i in pats["饿"]:
            for j in pats["饿"]:
                if i != j:
                    ng.W_out[i][0][j] = 2.0    # > θ=1.0——自持阈值
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)
    ng.step(build_pulse(ng.n, pats["饿"]), slot=0)   # 注入饿（发放）
    fires = []
    for t in range(1, 13):
        ng.step(np.zeros(ng.n), slot=0)              # 空白推进（不清 spikes）
        if clear_at and t == clear_at:               # 清除：注入新刺激
            ng.v = np.zeros((ng.n, ng.slots))
            ng.spikes = np.zeros(ng.n)
            ng.step(build_pulse(ng.n, pats["妈妈"]), slot=0)
            ng.step(np.zeros(ng.n), slot=0)
        fired = np.where(ng.spikes > 0)[0]
        e_hit = sum(1 for i in fired if i in set(pats["饿"]))
        fires.append(e_hit)
    return fires


def main():
    print("═══ 工作记忆结构实验（循环回路维持 vs 无循环衰减）═══\n")
    print("（纯内存——不保存快照）\n")
    ng, vocab, pats, cursor = load_version("35.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}

    print("── 对照：无循环（基线——'饿'发放后自然衰减）──")
    f1 = run("baseline", ng, pats, n2w)
    print(f"  饿 的发放（t1-12）：{f1}")
    print(f"  维持：{sum(1 for x in f1 if x > 0)} tick（前 {sum(f1)} 次发放）")

    print("\n── 实验：建循环回路（饿 自连接 w=2.0——delay activity）──")
    f2 = run("loop", ng, pats, n2w, build_loop=True)
    print(f"  饿 的发放（t1-12）：{f2}")
    n_hold = sum(1 for x in f2 if x > 0)
    print(f"  维持：{n_hold}/12 tick（总 {sum(f2)} 次发放）")

    print("\n── 清除测试：t6 注入「妈妈」→ 饿 是否被抑制 ──")
    f3 = run("clear", ng, pats, n2w, build_loop=True, clear_at=6)
    print(f"  饿 的发放（t1-12）：{f3}")
    print(f"  t6 后饿 发放：{sum(f3[5:])}（{'✅ 被清除（新信息覆盖）' if sum(f3[5:]) < sum(f3[:5]) else '⚠️ 未清除（持续自持）'}）")

    print(f"\n═══ 结论 ═══")
    print(f"  无循环：维持 {sum(1 for x in f1 if x > 0)} tick（衰减消失）")
    print(f"  有循环：维持 {sum(1 for x in f2 if x > 0)}/12 tick"
          f"（{'✅ 结构工作记忆涌现' if sum(1 for x in f2 if x > 0) > sum(1 for x in f1 if x > 0) else '❌ 未维持'}）")


if __name__ == "__main__":
    main()
