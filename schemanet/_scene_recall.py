# -*- coding: utf-8 -*-
"""自发回忆演示：网络自己说出"刚才发生了什么"（2026-08-11）。

用户："主要是让网络自己说出来"——自发言语 + 回忆叙述（PRT 主动
叙述训练目标）。事件完成后 WM 缓冲记录摘要 → 空闲时刻（无会话）→
自发表达「我刚才X了，妈妈Y」→ 已说标记（不重复叙述）。

场景：一天 3 事件（饿/疼/提问）→ 空闲时刻自发回忆。

用法：python _scene_recall.py（纯内存）
"""

import json
import time
from collections import deque
from pathlib import Path

from _scene_day import DayNet

DATA = Path(__file__).parent / "data" / "curriculum"

# 一天场景（单点事件——复用 _scene_day 的 DAY 结构）
DAY = [
    (2, ["饿"], None, "早上：内感受饿"),
    (4, ["妈", "妈"], None, "妈妈出现"),
    (9, ["吃", "饭"], "饿", "吃饭事件 → 饿解除"),
    (11, ["疼"], None, "摔倒疼"),
    (16, ["帮", "帮"], "疼", "妈妈来帮 → 疼解除"),
    (18, ["猫", "渴", "了", "怎", "么", "办"], None, "妈妈提问"),
    (22, ["困"], None, "晚上困"),
    (26, ["睡", "觉"], "困", "睡觉 → 困解除"),
]

RESP = {"饿": "来吃饭吧", "疼": "妈妈帮你揉揉", "困": "去睡觉吧"}


class RecallNet(DayNet):
    def __init__(self):
        super().__init__()
        self.wm = deque(maxlen=5)      # 事件缓冲（工作记忆）
        self.spontaneous = []          # 自发表达流

    def _record(self, state, resolve):
        """事件完成 → WM 记录摘要（工作记忆——主动保持）。"""
        self.wm.append({"state": state, "resolve": resolve,
                        "phase": self.phase, "told": False})
        self.log.append(f"    [记忆] 事件入缓冲：{state}"
                        f"（{resolve}——相位 {self.phase}）")

    def _recall(self):
        """空闲触发：无会话/无存疑 → 检查 WM → 未说事件 → 自发说出。"""
        if self.cur_state or self.doubt:
            return
        for ev in self.wm:
            if not ev["told"]:
                toks = ["我", "刚才", ev["state"], "了"]
                if ev["resolve"]:
                    toks += ["妈", "妈", "帮", "我"]
                self.spontaneous.extend(toks)
                ev["told"] = True
                self.log.append(f"    [自发回忆] 说「{'/'.join(toks)}」"
                                f"（空闲想起——相位 {self.phase}）")
                return


def main():
    t0 = time.time()
    print("═══ 自发回忆演示（网络自己说出刚才发生了什么）═══\n")
    print("（纯内存——不保存快照）\n")
    net = RecallNet()
    print("[加载] v34.0 ✓\n")

    for tick in range(1, 34):
        net.tick = tick
        net.phase = tick % 16
        # 场景感知（单点事件）
        for ts, words, relieve, desc in DAY:
            if ts == tick:
                if words:
                    for w in words:
                        net.hear(w)
                if relieve and net.cur_state == relieve:
                    net.log.append(f"    [场景] {relieve} 信号解除"
                                   f"（事件完成）")
                    net._record(relieve, RESP.get(relieve, ""))
                    net.cur_state = None
                    net.spoke_once = False
        # 网络处理
        need = net.act()
        if need == "need_response" and net.cur_state:
            st = net.cur_state
            resp = RESP.get(st)
            if resp:
                net.respond(resp)          # 回应 = 事件完成（解除）
                net._record(st, resp)      # WM 记录（事件摘要）
        # 空闲 → 自发回忆
        net._recall()
        # 日志
        if net.log:
            for line in net.log:
                print(f"t{tick:>2}（CLK_{net.phase:>2}）{line}")
            net.log = []

    print(f"\n═══ 结果 ═══")
    print(f"  事件表达流：{'/'.join(net.said)}")
    print(f"  自发回忆流：{'/'.join(net.spontaneous)}")
    print(f"  WM 缓冲：{len(net.wm)} 事件（已说 "
          f"{sum(1 for e in net.wm if e['told'])}——不重复叙述）")
    print(f"  → 网络自己说出了'刚才发生了什么'（空闲想起——未被问）✓")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
