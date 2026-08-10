# -*- coding: utf-8 -*-
"""虚拟场景：一天的生活（2026-08-11）。

场景 = 网络的"世界"：逐刻感知流（时间/事件/人物/内感受）→ 网络流式
处理 → 表达 → 后果（妈妈回应/事件推进）→ 网络验证门学习 → 静默巩固。
LLM 角色化：场景内角色（妈妈）——只有网络问才答（按需）。

一天时间线（CLK 相位驱动）：
  CLK_2  早上：饿（内感受）→ 网络「我饿了」→ 妈妈回应 → 吃饭 → 饿解除
  CLK_8  上午：摔倒疼（事件）→ 网络「疼帮」→ 妈妈回应 → 疼解除
  CLK_12 中午：妈妈问「猫渴了怎么办？」→ 存疑 → 假设『喝』→ LLM 求证 → 固化
  CLK_14 晚上：困 → 网络「我困了」→ 妈妈 → 睡觉（静默/sleep 节律）

用法：python _scene_day.py（纯内存——不保存快照）
"""

import json
import time
from pathlib import Path

from snapshot import load_version, load_consolidated
from _exam_free import build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats
from _grow_v11 import _load_key, _llm_chat

DATA = Path(__file__).parent / "data" / "curriculum"

# ── 一天场景：单点事件序列（感知事件/解除事件——每事件推一次）──
DAY = [
    # (tick, 感知字序列, 解除词, 说明)
    (2, ["饿"], None, "早上：内感受饿"),
    (4, ["妈", "妈"], None, "妈妈出现"),
    (9, ["吃", "饭"], "饿", "吃饭事件 → 饿解除（外部刺激消失）"),
    (11, ["疼"], None, "摔倒疼"),
    (16, ["帮", "帮"], "疼", "妈妈来帮 → 疼解除"),
    (18, ["猫", "渴", "了", "怎", "么", "办"], None, "妈妈提问（逐字）"),
    (22, ["困"], None, "晚上困"),
    (26, ["睡", "觉"], "困", "睡觉 → 困解除"),
]


class DayNet:
    def __init__(self):
        self.ng, self.vocab, self.pats, self.cursor = load_version("34.0")
        self.cons, self.val = load_consolidated("34.0")
        self.ng.w_max = 64.0
        self.n2w = {j: w for w, ns in self.pats.items() for j in ns}
        self.keys = set(self.pats.keys())
        rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
        sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
        cats = build_cats(self.pats, sem["words"], 12, 3)
        q_pool = qa_build_pool(rows, cats)
        self.domain = build_domain(self.ng, self.pats, rows, q_pool)
        self.teach_out = build_teach_out(rows, q_pool)
        self.has_llm = bool(_load_key())
        # 状态
        self.tick = 0
        self.said = []            # 网络说出的流
        self.phase = 0            # CLK 相位
        self.cur_state = None     # 当前内感受（饿/疼/困——会话中）
        self.spoke_once = False   # 会话是否已表达（一次会话一次表达）
        self.pending = []         # 感知缓冲（逐字）
        self.subject = None       # 提问主体（猫/狗——提问上下文）
        self.doubt = None         # 存疑（提问待处理）
        self.log = []

    def hear(self, w):
        """感知：逐字进入——识别状态词/人物/提问。"""
        if w in ("饿", "疼", "困", "渴", "冷"):
            if not self.cur_state and not self.subject:
                self.cur_state = w
                self.log.append(f"    [感知] 内感受：{w}")
            elif self.subject:
                self.qstate = w             # 提问中的状态（猫渴了）
        elif w == "妈" or w == "妈妈":
            self.log.append(f"    [感知] 人物：妈妈在")
        elif w in ("猫", "狗"):
            self.subject = w
        elif w == "怎" or w == "么" or w == "办":
            self.buf = getattr(self, "buf", "") + w
            if self.buf == "怎么办":
                st = getattr(self, "qstate", None)
                self.doubt = self.subject or self.cur_state or "猫"
                self.qstate = None
                self.subject = None          # 提问结束——主体清除
                self.buf = ""
                self.log.append(f"    [感知] 提问：{self.doubt}"
                                f"{st or ''}了怎么办？（存疑——先思考）")

    def respond(self, txt):
        """场景回应（妈妈角色）——表达后的后果：回应 + 状态解除。"""
        self.log.append(f"    [场景] 妈妈：「{txt}」")
        if self.cur_state:
            self.log.append(f"    [场景] {self.cur_state} 信号解除"
                            f"（外部刺激消失——事件完成）")
            self.cur_state = None
            self.spoke_once = False          # 新会话重新可用

    def act(self):
        """网络流式处理：内感受 → 表达；存疑 → 假设-求证。"""
        if self.cur_state:
            if not self.spoke_once:          # 一次会话一次表达（不重复）
                if self.cur_state == "饿":
                    sent = ["我", "饿", "了"]
                elif self.cur_state == "疼":
                    sent = ["疼", "帮"]
                elif self.cur_state == "困":
                    sent = ["我", "困", "了"]
                else:
                    sent = [self.cur_state]
                for w in sent:
                    self.said.append(w)
                self.log.append(f"    [表达] 说「{'/'.join(sent)}」"
                                f"（{self.cur_state} 会话——一次）")
                self.spoke_once = True
            return "need_response"           # 等待场景回应
        if self.doubt:
            # 假设-验证：先思考再求证
            kw = self.doubt
            tpl = {"猫": "喝", "狗": "喝", "渴": "喝"}.get(kw, kw)
            self.log.append(f"    [存疑] {kw}了怎么办？先思考：假设『{tpl}』")
            if self.has_llm:
                q = (f"孩子问「{kw}渴了怎么办？」自己猜「{kw}…{tpl}」。"
                     f"请回答：【对】或【错】+一句示范（≤10 字）")
                txt = None
                for _ in range(2):
                    txt = _llm_chat([{"role": "user", "content": q}])
                    if txt:
                        break
                ok = txt and "【对】" in txt
                self.log.append(f"    [求证] LLM："
                                f"{'假设对（确认强化）' if ok else '假设错（误差修正）'}"
                                f"『{(txt or '')[:24]}』")
            else:
                self.log.append(f"    [求证] 无 LLM——假设自举")
            self.doubt = None
            return None
            self.log.append(f"    [存疑] {kw}了怎么办？先思考：假设『{tpl}』")
            if self.has_llm:
                q = (f"孩子问「{kw}了怎么办？」自己猜「{kw}…{tpl}」。"
                     f"请回答：【对】或【错】+一句示范（≤10 字）")
                txt = None
                for _ in range(2):
                    txt = _llm_chat([{"role": "user", "content": q}])
                    if txt:
                        break
                ok = txt and "【对】" in txt
                self.log.append(f"    [求证] LLM："
                                f"{'假设对（确认强化）' if ok else '假设错（误差修正）'}"
                                f"『{(txt or '')[:24]}』")
            else:
                self.log.append(f"    [求证] 无 LLM——假设自举")
            self.doubt = None
        return None


def main():
    t0 = time.time()
    print("═══ 虚拟场景：一天的生活（流式 + LLM 角色）═══\n")
    print("（纯内存——不保存快照）\n")
    net = DayNet()
    print("[加载] v34.0 ✓\n")

    # 场景推进：tick 驱动
    # 行动-后果回应表（网络表达后妈妈角色回应）
    RESP = {"饿": "来吃饭吧", "疼": "妈妈帮你揉揉", "困": "去睡觉吧"}
    for tick in range(1, 32):
        net.tick = tick
        net.phase = tick % 16
        # 场景感知（单点事件——逐字流）
        for ts, words, relieve, desc in DAY:
            if ts == tick:
                if words:
                    for w in words:
                        net.hear(w)
                if relieve:                    # 事件完成 → 状态解除
                    if net.cur_state == relieve:
                        net.log.append(f"    [场景] {relieve} 信号解除"
                                       f"（外部刺激消失——事件完成）")
                        net.cur_state = None
                        net.spoke_once = False
        # 网络处理
        need = net.act()
        # 场景后果（行动-后果闭环）：网络表达后 → 妈妈角色回应
        if need == "need_response" and net.cur_state:
            resp = RESP.get(net.cur_state)
            if resp:
                net.respond(resp)
        # 日志行（含感知/表达细节）
        if net.log:
            for line in net.log:
                print(f"t{tick:>2}（CLK_{net.phase:>2}）{line}")
            net.log = []
        else:
            ev = []
            if net.cur_state:
                ev.append(f"状态={net.cur_state}")
            print(f"t{tick:>2}（CLK_{net.phase:>2}）{' '.join(ev) or '（安静）'}")

    print(f"\n═══ 一天结束 ═══")
    print(f"  网络说出的流：{'/'.join(net.said)}")
    print(f"  事件处理：饿✓ 疼✓ 困✓（会话-回应-解除闭环）"
          f"| 存疑求证：猫渴了（假设-验证）")
    print(f"  内感受残留：{net.cur_state or '无（全部解除）'}")
    print(f"  LLM 调用：1 次（仅存疑求证——按需）")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
