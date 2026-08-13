# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""时间定位实验：知道事件是什么时候的、哪个远哪个近（2026-08-11）。

用户："1tick 饿，1000tick 解决，5000tick 时网络知道饿是什么时候的
吗？什么时候解决的吗？哪个远哪个近？"

问题：CLK 相位（模 16）折叠远度——t1 与 t5001 同相位（"远变近"）。
方案：天计数（相位回绕计数——tick//16）——事件时间戳（天+相位）
→ 距离 = 现在天 - 事件天（远近）→ 排序（顺序）。

机制（诚实标注）：天计数 = 运行时时钟机制（外部计数——网络的时间
感知通道）；距离/顺序 = 时间戳计算（网络"知道"通过该机制）。

用法：python _exp_time.py（纯内存）
"""

import time


class TimeNet:
    def __init__(self):
        self.tick = 0
        self.day = 0            # 天计数（相位回绕 +1）
        self.phase = 0
        self.events = {}        # 事件时间戳 {名称: (tick, day, phase)}
        self.said = []
        self.log = []

    def advance(self, n=1):
        """时间推进：tick/相位/天计数（CLK 回绕 → 天+1）。"""
        for _ in range(n):
            self.tick += 1
            self.phase = self.tick % 16
            if self.phase == 0:
                self.day += 1     # 回绕 → 新的一天

    def record(self, name, note=""):
        """事件发生 → 时间戳（天+相位——什么时候）。"""
        self.events[name] = (self.tick, self.day, self.phase)
        self.log.append(f"t{self.tick}（天{self.day} 相位{self.phase}）"
                        f"[事件] {name} 发生——时间戳已记{note}")

    def ask_when(self, name):
        """问：X 是什么时候的？→ 回忆时间戳（天）。"""
        tick, day, phase = self.events[name]
        ago = self.day - day
        self.said.append(f"{name}是第{day}天的事（{ago}天前）")
        self.log.append(f"t{self.tick} [回答]「{name}是第{day}天的事，"
                        f"{ago}天前」——时间戳回忆")

    def ask_far_near(self, a, b):
        """问：哪个远哪个近？→ 距离比较（现在-事件天）。"""
        da = self.day - self.events[a][1]
        db = self.day - self.events[b][1]
        if da > db:
            ans = f"{a}更远（{da}天前），{b}更近（{db}天前）"
        else:
            ans = f"{b}更远（{db}天前），{a}更近（{da}天前）"
        self.said.append(ans)
        self.log.append(f"t{self.tick} [回答]「{ans}」——距离比较")

    def ask_order(self, a, b):
        """问：先发生什么？→ 时间戳排序。"""
        first = a if self.events[a][1] < self.events[b][1] else b
        self.said.append(f"先发生的是{first}")
        self.log.append(f"t{self.tick} [回答]「先发生的是{first}」——顺序")


def main():
    t0 = time.time()
    print("═══ 时间定位实验（什么时候/哪个远近/顺序）═══\n")
    print("（纯内存——不保存快照）\n")
    net = TimeNet()

    # ── 场景：t1 饿 → t1000 解决 → t5000 提问 ──
    net.record("饿")
    net.advance(999)          # → t1000
    net.record("解决")
    net.advance(4000)         # → t5000
    print(f"现在：t{net.tick}（第{net.day}天 相位{net.phase}）\n")

    print("── 提问 ──")
    net.ask_when("饿")
    net.ask_when("解决")
    net.ask_far_near("饿", "解决")
    net.ask_order("饿", "解决")
    for l in net.log:
        print(f"  {l}")

    # ── 验证（真实值）──
    print(f"\n═══ 验证 ═══")
    d_e = net.day - net.events["饿"][1]
    d_s = net.day - net.events["解决"][1]
    print(f"  真实：饿=第{net.events['饿'][1]}天（{d_e}天前）"
          f"解决=第{net.events['解决'][1]}天（{d_s}天前）")
    ok_when = (d_e == 312) and (d_s == 250)
    ok_far = d_e > d_s
    ok_order = net.events["饿"][1] < net.events["解决"][1]
    print(f"  时间戳回忆：{'✅' if ok_when else '❌'}（饿 312 天前/"
          f"解决 250 天前）")
    print(f"  远近判断：{'✅' if ok_far else '❌'}（饿 远/解决 近）")
    print(f"  顺序判断：{'✅' if ok_order else '❌'}（先饿后解决）")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
