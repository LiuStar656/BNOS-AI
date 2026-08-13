# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""事件记忆遗忘实验：什么时候忘？（2026-08-11）

用户："但是什么时候忘呢？"——事件时间戳不能无限增长——遗忘必须存在。

遗忘机制（Ebbinghaus 遗忘曲线——指数衰减）：
  事件记忆强度：初始 1.0 → 每 tick ×decay（指数衰减）
  遗忘阈值：强度 < θ（如 0.1）→ 事件遗忘（时间戳删除——"不记得了"）
  巩固/复习：事件被回顾（提问/重复）→ 强度恢复（间隔复习效应）
  容量：事件数上限（满了删最弱）

测量：
  ① 遗忘时刻：强度 < 阈值的 t（不同 decay——半衰期/遗忘点）
  ② 复习效应：回顾后强度恢复——遗忘推迟
  ③ 对比 Ebbinghaus 曲线（指数衰减）

用法：python _exp_forget.py（纯内存）
"""

import time


class ForgetNet:
    def __init__(self, decay=0.999, theta=0.1):
        self.tick = 0
        self.day = 0
        self.phase = 0
        self.decay = decay          # 每 tick 衰减因子（指数遗忘）
        self.theta = theta          # 遗忘阈值
        self.events = {}            # {名称: (tick, day, strength)}
        self.forgotten = []         # 遗忘记录
        self.log = []

    def advance(self, n=1):
        for _ in range(n):
            self.tick += 1
            self.phase = self.tick % 16
            if self.phase == 0:
                self.day += 1
            # 所有事件强度衰减（遗忘曲线）
            for k in list(self.events):
                tick, day, s = self.events[k]
                s *= self.decay
                if s < self.theta:          # 遗忘阈值 → 删除
                    del self.events[k]
                    self.forgotten.append((k, self.tick, day))
                else:
                    self.events[k] = (tick, day, s)

    def record(self, name):
        self.events[name] = (self.tick, self.day, 1.0)
        self.log.append(f"t{self.tick}（天{self.day}）[记] {name}")

    def recall(self, name):
        """回忆：强度够 → 记得（时间戳）；不够 → 忘了。"""
        if name in self.events:
            tick, day, s = self.events[name]
            # 复习效应：回顾 → 强度恢复（+0.5——间隔复习）
            self.events[name] = (tick, day, min(1.0, s + 0.5))
            self.log.append(f"t{self.tick} [忆] {name}：第{day}天的事"
                            f"（强度 {s:.2f}→{s+0.5:.2f}——复习恢复）")
            return True
        self.log.append(f"t{self.tick} [忘] {name}：不记得了"
                        f"（已遗忘——第{self.tick}天前的事？）")
        return False


def main():
    t0 = time.time()
    print("═══ 事件记忆遗忘实验（什么时候忘？）═══\n")
    print("（纯内存——不保存快照）\n")

    # ── ① 遗忘曲线：不同 decay 的遗忘时刻 ──
    print("── ① 遗忘时刻（decay 参数扫描）──")
    print(f"  {'decay':<10}{'半衰期':<10}{'遗忘点(θ=0.1)':<16}{'说明'}")
    for decay in [0.99, 0.999, 0.9999]:
        half = 0.693 / (1 - decay)          # 半衰期 = ln2/衰减率
        t_forget = (1 - decay) and (0.1 and 0.0)
        # 遗忘点：强度 1.0 → 0.1：0.1 = decay^n → n = ln(0.1)/ln(decay)
        n = 2.3026 / (1 - decay) if decay < 1 else float("inf")
        print(f"  {decay:<10}{half:<10.0f}{n:<16.0f}"
              f"（t={n:.0f} 后忘了）")

    # ── ② 实际模拟：饿 t1 记 → 什么时候忘（decay=0.999）──
    print("\n── ② 模拟：饿 在 t1 记录——何时遗忘 ──")
    net = ForgetNet(decay=0.999, theta=0.1)
    net.record("饿")
    forget_at = None
    for _ in range(10000):
        net.advance()
        if "饿" not in net.events:
            forget_at = net.tick
            break
    print(f"  饿 的记忆强度 1.0 → 0.1（θ）→ 遗忘")
    print(f"  遗忘时刻：t={forget_at}（第{forget_at//16}天）"
          f"——饿 的事在 {forget_at//16} 天后忘了")
    print(f"  理论值 ≈ t=2303（2.3026/0.001——指数衰减）"
          f"{'✅ 吻合' if forget_at and abs(forget_at - 2303) < 100 else ''}")

    # ── ③ 复习效应：回顾 → 遗忘推迟 ──
    print("\n── ③ 复习效应（回顾 → 强度恢复 → 遗忘推迟）──")
    net2 = ForgetNet(decay=0.999, theta=0.1)
    net2.record("疼")
    # 每 1000 tick 复习一次
    for i in range(6):
        for _ in range(1000):
            net2.advance()
            if "疼" not in net2.events:
                break
        if "疼" in net2.events:
            net2.recall("疼")      # 复习（强度恢复）
    alive = "疼" in net2.events
    print(f"  每 1000 tick 复习：疼痛记忆 t=6000 时"
          f"{'✅ 仍记得（复习推迟遗忘）' if alive else '❌ 忘了'}")
    print(f"  对比不复习：t≈2303 遗忘——复习 6 次 → 6000 仍记得"
          f"（间隔复习效应——Ebbinghaus）")

    print(f"\n═══ 结论 ═══")
    print(f"  遗忘时刻 = f(decay, θ)——指数衰减（Ebbinghaus 曲线）")
    print(f"  decay=0.999：约 2300 tick（144 天）后忘")
    print(f"  decay=0.99：约 230 tick（14 天）后忘")
    print(f"  复习（回顾）→ 强度恢复——遗忘推迟（间隔复习）")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
