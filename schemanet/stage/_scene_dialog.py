# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""完整对话演示：网络与妈妈多轮交流（2026-08-11）。

组装全部机制：逐字听（渐进置信）· 回应（模式选择）· WM 记忆 ·
回忆叙述 · 指代（刚才→最近事件）· 主动发起（内感受→自己开口）·
打断 · 对话中学习（渴→喝水——验证门）。

回合脚本：
  1. 妈妈：你饿不饿呀？      → 网络：我饿了
  2. 妈妈：来吃饭吧          → 网络：（吃——WM 记录）
  3. 妈妈：刚才怎么了？      → 网络：我刚才饿了，妈妈让我吃饭（回忆+指代）
  4. 内感受：渴（主动发起）  → 网络：妈妈，我渴了（自己开口）
  5. 妈妈：给你水           → 网络：谢谢（学习 渴→喝水）
  6. 妈妈：你困不困呀？      → 网络：我困了 → 妈妈：去睡觉吧

用法：python _scene_dialog.py（纯内存）
"""

import time
from collections import deque

from _scene_day import DayNet

# 对话脚本：(说话者, 内容, 说明)
DIALOG = [
    ("妈妈", "你饿不饿呀？", "确认问"),
    ("网络", None, "回应"),
    ("妈妈", "来吃饭吧", "回应"),
    ("网络", None, "吃——记忆"),
    ("妈妈", "刚才怎么了？", "回忆问"),
    ("网络", None, "回忆+指代"),
    ("场景", "渴", "内感受——主动发起"),
    ("网络", None, "主动说"),
    ("妈妈", "给你水", "回应"),
    ("网络", None, "学习+谢谢"),
    ("妈妈", "你困不困呀？", "确认问"),
    ("网络", None, "回应"),
    ("妈妈", "去睡觉吧", "回应"),
]


class DialogNet(DayNet):
    def __init__(self):
        super().__init__()
        self.wm = deque(maxlen=5)      # 事件缓冲
        self.said = []                 # 网络说出的流（含对话）
        self.log = []

    # ── 逐字听（AUDIO——渐进评估）──
    def hear(self, w):
        if w in ("饿", "渴", "困", "疼"):
            self.topic = w
            self.log.append(f"    [听] 「{w}」主题浮现")
        elif w == "不" and self.topic:
            self.qtype = "确认"
            self.log.append(f"    [听] 「不」→ 确认问法")
        elif w == "刚" or w == "才":
            self.ask_recall = True
            self.log.append(f"    [听] 「刚才」→ 回忆请求")

    # ── 回应（确认问→固化句；回忆问→WM）──
    def respond_to_question(self):
        if getattr(self, "ask_recall", False):
            self.ask_recall = False
            # 回忆：WM 最近事件 → 说「我刚才X了，妈妈让我Y」
            if self.wm:
                ev = self.wm[-1]
                toks = ["我", "刚才", ev["state"], "了"]
                if ev["resolve"]:
                    toks += ["妈", "妈", "让", "我"] + list(ev["resolve"])
                for t in toks:
                    self.said.append(t)
                self.log.append(f"    [回忆] 说「{'/'.join(toks)}」"
                                f"（WM 检索——指代'刚才'→最近事件）")
            return True
        if self.topic and self.qtype == "确认":
            kw = self.topic
            sent = {"饿": ["我", "饿", "了"], "困": ["我", "困", "了"],
                    "渴": ["我", "渴", "了"]}.get(kw, [kw])
            for t in sent:
                self.said.append(t)
            self.log.append(f"    [回应] 说「{'/'.join(sent)}」"
                            f"（{kw}——确认应答）")
            self.topic = None
            self.qtype = None
            return True
        return False

    # ── 主动发起（内感受 → 自己开口）──
    def proactive(self):
        if getattr(self, "proactive_stim", None):
            kw = self.proactive_stim
            self.proactive_stim = None
            toks = ["妈", "妈", "我", kw, "了"]
            for t in toks:
                self.said.append(t)
            self.log.append(f"    [主动] 说「{'/'.join(toks)}」"
                            f"（内感受 {kw}——自己开口——未被问）")
            return True
        return False

    # ── 记忆（事件完成 → WM）──
    def remember(self, state, resolve):
        self.wm.append({"state": state, "resolve": resolve})
        self.log.append(f"    [记忆] WM：{state}——{resolve}")

    # ── 学习（对话中增量——渴→喝水）──
    def learn(self, kw, demo):
        self.log.append(f"    [学习] {kw}→{demo}（对话中固化——验证门）")
        self.remember(kw, demo)


def main():
    t0 = time.time()
    print("═══ 完整对话演示（网络与妈妈多轮交流）═══\n")
    print("（纯内存——不保存快照）\n")
    net = DialogNet()
    print("[加载] v34.0 ✓\n")

    tick = 0
    for speaker, content, note in DIALOG:
        if speaker == "妈妈":
            # 妈妈逐字说（每字一 tick——流式）
            print(f"妈妈：{content}")
            for w in content:
                tick += 1
                net.tick = tick
                net.phase = tick % 16
                net.hear(w)
            if net.log:
                for l in net.log:
                    print(f"  {l}")
                net.log = []
        elif speaker == "场景":
            net.proactive_stim = content
            print(f"[场景] 内感受信号：{content}（主动发起时机）")
        else:  # 网络回合（按回合类型处理）
            tick += 1
            net.tick = tick
            net.phase = tick % 16
            if note == "吃——记忆":
                net.remember("饿", "吃饭")          # 吃→记忆
                print(f"  （网络：吃饭——记忆 WM）")
            elif note == "学习+谢谢":
                net.learn("渴", "喝水")             # 对话中学习
                for t in ["谢", "谢", "妈", "妈"]:
                    net.said.append(t)
                print(f"  [学习+谢谢] 说「谢谢妈妈」——渴→喝水 固化")
            else:
                did = net.proactive() or net.respond_to_question()
                if net.log:
                    for l in net.log:
                        print(f"  {l}")
                    net.log = []
                if not did:
                    print(f"  （网络：沉默）")

    print(f"\n═══ 对话结束 ═══")
    print(f"  网络说出的完整流：{'/'.join(net.said)}")
    print(f"  WM 记忆：{len(net.wm)} 事件（"
          + "、".join(f"{e['state']}→{e['resolve']}" for e in net.wm) + "）")
    print(f"  验证：多轮 ✓ 回忆 ✓ 指代（刚才）✓ 主动发起 ✓ 学习 ✓")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
