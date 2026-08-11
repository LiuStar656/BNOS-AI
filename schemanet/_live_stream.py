# -*- coding: utf-8 -*-
"""流式主循环运行时——全部改造整合（2026-08-11）。

把 4.4-4.13 的所有机制装成"活着的网络"：
  逐字听（渐进置信/提前开口）· 逐词说（全双工）· 打断/挂起恢复
  · salience 竞争 · 多维评估（模式选择）· 事件会话（时间线）
  · 存疑队列（假设-验证→自举/求证）· 时钟节律

主循环（每 tick）：
  感知（逐字/新刺激）→ 渐进评估 → 打断检查 → 会话推进 → 逐词表达
  → 存疑处理（任务间隙）→ 时钟推进

用法：python _live_stream.py（纯内存——不保存快照）
"""

import json
import time
from pathlib import Path

from snapshot import load_version, load_consolidated
from _exam_free import build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats
from _grow_v11 import _load_key, _llm_chat
from _grow_v16 import edge_between

DATA = Path(__file__).parent / "data" / "curriculum"

STATES = {"饿", "渴", "累", "冷", "困", "疼", "开心", "怕"}
NEG = {"疼", "饿", "累", "冷", "怕"}
HIGH = {"疼", "饿", "怕"}
URGENCY = {"求助": 3, "需求": 2, "探索": 1, "背景": 0}
HOW_WORDS = {"怎么办", "会怎样"}
# 自助链（饿→了→就→吃——需求可自助）
SELF = {"饿": "吃", "渴": "喝", "累": "睡", "冷": "穿", "困": "睡"}


class LiveNet:
    def __init__(self):
        self.ng, self.vocab, self.pats, self.cursor = load_version("35.0")
        self.cons, self.validation = load_consolidated("34.0")
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
        # 运行状态
        self.tick_n = 0
        self.session = None      # (主题, 模式, 句子list, 进度idx, 等待tick)
        self.queue = []          # 打断挂起会话
        self.doubt = []          # 存疑队列
        self.topic = None        # 听的主题（渐进）
        self.qtype = None        # 听的问法
        self.conf = 0.0
        self.spoken = []
        self.pending_stim = None  # 完整新刺激（打断候选）
        self.listening = []      # 正在听的字
        self.subject = None      # 主体累积（猫/狗/他——"猫渴了"的主体）
        self.log = []

    # ── 感知：逐字听（4.13）────────────────────────────
    def _hear(self, w):
        self.listening.append(w)
        # 词缓冲：单字聚合（怎+么+办 → 怎么办）
        self.buf = getattr(self, "buf", "")
        self.buf += w
        if self.buf in ("怎么办", "会怎样"):
            if self.topic:
                self.qtype = "怎么办"
                self.conf = max(self.conf, 0.7)
                self.log.append(f"  [词缓冲] 「{self.buf}」→ 问法=怎么办型"
                                f"（置信 {self.conf:.1f}）")
            self.buf = ""
            return
        if len(self.buf) > 2:
            self.buf = self.buf[-2:]
        if w in STATES:
            if self.session:
                # 有会话 → 状态词是打断候选（疼——紧急）
                self.pending_stim = w
                self.log.append(f"  收「{w}」[打断候选] 状态刺激（会话中）")
            else:
                self.topic = w
                self.conf = max(self.conf, 0.4)
                self.log.append(f"  收「{w}」[主题] 浮现=「{w}」"
                                f"（置信 {self.conf:.1f}）")
        elif w == "不" and self.topic:
            self.qtype = "确认"
            self.conf = max(self.conf, 0.7)
            self.log.append(f"  收「{w}」[问法] 确认型（置信 {self.conf:.1f}）")
        elif w in ("猫", "狗", "他", "她"):
            self.subject = w          # 主体累积
            self.log.append(f"  收「{w}」[主体] 累积（{w}渴了/饿了…）")
        elif w not in ("你", "我", "呀", "吗", "了", "的", "呢",
                       "怎", "么", "办"):
            self.pending_stim = w      # 完整刺激词（打断候选）
            self.log.append(f"  收「{w}」[新刺激] 完整信号进入")

    # ── 多维评估 → 模式（4.8）──────────────────────────
    def _mode_of(self, kw):
        top = edge_between(self.ng, self.pats, kw, "帮")
        if kw in NEG and kw in HIGH:
            if kw in SELF and all(
                    edge_between(self.ng, self.pats, a, b) > 0
                    for a, b in [(kw, "了"), ("了", "就"),
                                 ("就", SELF[kw])]):
                return "需求", URGENCY["需求"]
            return "求助", URGENCY["求助"]
        return "探索", URGENCY["探索"]

    # ── 打断检查（4.12）────────────────────────────────
    def _interrupt(self):
        s = self.pending_stim
        self.pending_stim = None
        if s not in self.pats:
            return
        mode, urg = self._mode_of(s)
        if mode == "求助":
            self._open_session(s, mode)
            self.log.append(f"  [打断] 「{s}」{mode} 紧急——直接建立会话")
            return
        cur_urg = self.session[1][1] if self.session else 0
        self.log.append(f"  [评估] 「{s}」= {mode}({urg}) vs 当前"
                        f"（{self.session[0] if self.session else '无'}）")
        if urg > cur_urg:
            if self.session:
                self.queue.append(self.session)
                self.log.append(f"  [打断] 挂起当前会话 → 处理「{s}」")
            self._open_session(s, mode)
        else:
            self.log.append(f"  [继续] 「{s}」不更紧急——不打断")

    # ── 事件会话（4.11）────────────────────────────────
    def _open_session(self, kw, mode):
        if mode == "求助":
            sent = ["疼", "帮"]
        else:
            sent = next((e[0] for e in self.cons.get(kw, [])
                         if e[2] == "怎么办"), None) or [kw]
        self.session = [kw, (mode, URGENCY[mode]), sent, 0, 0]
        self.log.append(f"  [会话] 建立「{kw}」{mode}——句「{'/'.join(sent)}」")

    def _advance(self):
        if not self.session:
            return
        kw, (mode, _), sent, idx, wait = self.session
        if mode == "求助":
            wait += 1
            self.session[4] = wait
            if wait == 3:   # 等待升级（无回应——tick 节律）
                self.log.append(f"  [等待] 「{kw}」仍无回应——升级求助"
                                f"（等待 {wait} tick）")
        if self.session[3] >= len(sent):
            self.log.append(f"  [完成] 「{kw}」会话结束（表达完成）")
            self.session = None
            if self.queue:
                self.session = self.queue.pop(0)
                self.log.append(f"  [恢复] 继续挂起会话「{self.session[0]}」")

    # ── 逐词表达（4.12）────────────────────────────────
    def _speak(self):
        if not self.session:
            return
        sent = self.session[2]
        idx = self.session[3]
        if idx < len(sent):
            w = sent[idx]
            self.spoken.append(w)
            self.log.append(f"  [说] 「{w}」")
            self.session[3] = idx + 1

    # ── 存疑处理：假设-验证（4.6）───────────────────────
    def _process_doubt(self):
        if not self.doubt or self.session:
            return      # 任务间隙才处理
        kw = self.doubt.pop(0)
        tpl = {"渴": "喝", "饿": "吃", "猫": "喝"}.get(kw)
        guess = tpl or kw
        self.log.append(f"  [存疑] 处理「{kw}」——先思考：假设『{guess}』")
        if self.has_llm:
            q = (f"孩子问「{kw}了怎么办？」自己猜「{kw}…{guess}」。"
                 f"请回答：【对】或【错】+一句示范（≤10 字）")
            txt = None
            for _ in range(2):
                txt = _llm_chat([{"role": "user", "content": q}])
                if txt:
                    break
            ok = txt and "【对】" in txt
            self.log.append(f"  [求证] LLM：{'假设对（确认）' if ok else '假设错（修正）'}"
                            f"『{(txt or '')[:20]}』")
        else:
            self.log.append(f"  [求证] 无 LLM——假设『{guess}』自举尝试")

    # ── 主循环 tick ────────────────────────────────────
    def tick(self, word=None, note=""):
        self.tick_n += 1
        phase = self.tick_n % 16
        t = f"t{self.tick_n}"
        self.log.append(f"── {t}（时钟相位 {phase}）{note}")
        if word:
            self._hear(word)
        if self.pending_stim:
            self._interrupt()
        if not self.session and self.topic and self.conf >= 0.7 \
                and self.qtype:
            # 提前开口：主题+问法确定（4.13——不等整句）
            kw = self.topic
            mode, urg = self._mode_of(kw)
            if mode == "需求":
                sent = next((e[0] for e in self.cons.get(kw, [])
                             if e[2] == "确认"), None) or [kw]
                self.session = [kw, (mode, urg), sent, 0, 0]
                self.log.append(f"  [开口] 确认应答「{'/'.join(sent)}」"
                                f"（不等句子说完）")
            self.topic = None
            self.qtype = None
            self.conf = 0.0
        self._advance()
        self._speak()
        if self.tick_n % 8 == 0:
            self._process_doubt()


def main():
    t0 = time.time()
    print("═══ 流式主循环运行时（全部机制整合）═══\n")
    print("（纯内存——不保存快照）\n")
    net = LiveNet()
    print("[加载] v34.0 + 固化/验证恢复 ✓\n")

    # ── 场景：教师逐字说话 + 中途打断 + 存疑求证 ──
    scene = [
        ("你", ""), ("饿", ""), ("不", ""), ("饿", ""),
        (None, "（说「饿」后、说「了」前——注入「疼」——打断测试）"),
        ("疼", ""), ("呀", ""), (None, ""), (None, ""), (None, ""),
        (None, "（教师问「猫渴了怎么办？」——逐字）"),
        ("猫", ""), ("渴", ""), ("了", ""), ("怎", ""), ("么", ""),
        ("办", ""), (None, ""), (None, ""), (None, ""),
    ]
    for word, note in scene:
        net.tick(word, note)
    # 存疑队列：猫渴了（主题=渴——假设"喝水"——模板 渴→喝）
    net.doubt.append("渴")

    # 运行到完成
    for _ in range(12):
        net.tick(None, "（继续运行——会话推进/存疑处理）")

    print("═══ 运行日志 ═══")
    for line in net.log:
        print(line)
    print(f"\n═══ 结果 ═══")
    print(f"  运行 {net.tick_n} tick，说出的流：{'/'.join(net.spoken)}")
    print(f"  打断挂起队列：{len(net.queue)}，存疑队列：{len(net.doubt)}")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
