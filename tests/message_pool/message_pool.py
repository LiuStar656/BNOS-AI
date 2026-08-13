# -*- coding: utf-8 -*-
"""聊天室消息池（对齐 Lumi_Nox SpeakerScheduler，消息按时间顺序排队）。

- enqueue_input(...)：消息入队，不打断 Agent 当前处理。
- pop_all_inputs(max_items)：批量取出，同人同文去重；洪流按
  「优先级 > 最新 > 单用户配额」取舍（付费/@ 点名可提高优先级）。

去重：同一用户 `dedup_window_s` 窗口内相同文本只保留第一条，
重复消息发布 message_duplicate_dropped 事件（计数信息供实验分析）。
"""
import time


class Message:
    """单条聊天室消息。

    reply_to: v6.4 引用链——本条消息"回应谁"（决策的【回应对象】）。
              渲染给 LLM 决策上下文，让 Agent 看到谁在回应谁。
    """

    __slots__ = ("text", "source", "user_id", "priority", "ts", "seq", "reply_to")

    def __init__(self, text, source="sim", user_id="", priority=0, ts=None,
                 seq=0, reply_to=""):
        self.text = text
        self.source = source
        self.user_id = user_id
        self.priority = priority
        self.ts = ts if ts is not None else time.time()
        self.seq = seq
        self.reply_to = reply_to

    def to_dict(self) -> dict:
        """转平台派发格式（AAA _on_pool_batch 消费）。

        v6.6 P0-1 批次顺序事实源统一：携带 seq（消息池全局单调递增序号）——
        decisions.batch_context 与 events.batch_dispatched 均可按 seq 关联，
        批次"原始到达顺序"与"各 Agent 实际所见顺序"不再互相矛盾。
        """
        return {
            "content": self.text,
            "source": self.source,
            "user_id": self.user_id,
            "priority": self.priority,
            "ts": self.ts,
            "seq": self.seq,
            "reply_to": self.reply_to,
        }

    def __repr__(self):
        return f"<Message {self.user_id}:{self.text[:20]}>"


class MessagePool:
    """聊天室消息池（多人按时间顺序发言，Agent 订阅并按批消费）。"""

    def __init__(self, bus=None, dedup_window_s=60.0, per_user_quota=3):
        self._bus = bus
        self._dedup_window_s = dedup_window_s
        self._per_user_quota = per_user_quota
        self._queue: list[Message] = []
        self._seq = 0
        # 去重记录：(user_id, 规范化文本) -> 最近 ts
        self._last_seen: dict[tuple[str, str], float] = {}

    # ── 入队 ───────────────────────────────────────────────
    def enqueue_input(self, text, source="sim", user_id="", priority=0, ts=None,
                      publish=True, dedup=True, reply_to=""):
        """消息入队。

        Args:
            dedup: 是否参与同人同文去重（默认 True）。Agent 发言回投（source=agent）
                   传 False——每次发言都是 agent 间对话的实际一轮，不受去重误伤。
            reply_to: v6.4 引用链——本条消息回应谁（决策的【回应对象】）。

        Returns:
            Message 成功入队；None 表示窗口内重复被丢弃。
        """
        ts = ts if ts is not None else time.time()
        if dedup:
            norm = " ".join(str(text).split())
            key = (str(user_id), norm)
            last = self._last_seen.get(key)
            if last is not None and ts - last < self._dedup_window_s:
                if publish and self._bus:
                    self._bus.publish("message_duplicate_dropped",
                                      user_id=user_id, content=text, ts=ts)
                return None
            self._last_seen[key] = ts
        self._seq += 1
        msg = Message(text, source, user_id, priority, ts, self._seq, reply_to)
        self._queue.append(msg)
        if publish and self._bus:
            self._bus.publish("message_enqueued",
                              user_id=user_id, content=text,
                              priority=priority, ts=ts)
        return msg

    # ── 批量取出 ───────────────────────────────────────────
    def pop_all_inputs(self, max_items=10):
        """批量取出：priority 降序 → ts 升序 → 单用户配额截断。

        Returns:
            list[Message] 本批消息（已从队列移除）。
        """
        if not self._queue:
            return []
        self._queue.sort(key=lambda m: (-m.priority, m.ts))
        quota: dict[str, int] = {}
        picked: list[Message] = []
        for m in self._queue:
            uid = m.user_id or "anonymous"
            if quota.get(uid, 0) >= self._per_user_quota:
                continue
            quota[uid] = quota.get(uid, 0) + 1
            picked.append(m)
            if len(picked) >= max_items:
                break
        picked_ids = {id(m) for m in picked}
        self._queue = [m for m in self._queue if id(m) not in picked_ids]
        if self._bus:
            self._bus.publish("batch_dispatched",
                              n=len(picked),
                              contents=[m.to_dict() for m in picked])
        return picked

    def __len__(self) -> int:
        return len(self._queue)

    def __repr__(self):
        return f"<MessagePool queue={len(self._queue)}>"
