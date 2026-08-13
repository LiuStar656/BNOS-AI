# -*- coding: utf-8 -*-
"""发言仲裁器（对齐 Lumi_Nox SpeechOutputArbiter）。

全局单实例语义：同一时刻一个 Agent 持有发言权。
策略：
    POLICY_QUEUE（默认）    当前有人发言则排队，发言结束后按序补位。
    POLICY_DROP             发言中则丢弃本次输出（Agent 已处理、不发言）。
    POLICY_INTERRUPT        高优先级消息（如 @ 点名）打断当前发言。

仲裁事件发布到 EventBus（供 F8 采集）：
    speech_requested / speech_output_started / speech_queued
    speech_dropped / speech_cancelled / speech_finished
"""
from collections import deque
from enum import StrEnum


class ArbiterPolicy(StrEnum):
    QUEUE = "queue"
    DROP = "drop"
    INTERRUPT = "interrupt"


class SpeechOutputArbiter:
    """同一时刻至多一个 Agent 发言的仲裁器。"""

    def __init__(self, bus=None, default_policy=ArbiterPolicy.QUEUE,
                 interrupt_priority=10, max_queue=10):
        self._bus = bus
        self._default_policy = default_policy
        self._interrupt_priority = interrupt_priority
        self._max_queue = max_queue
        self._current = None   # {"agent_id", "content"}
        self._queue: deque[dict] = deque()

    # ── 只读状态 ───────────────────────────────────────────
    @property
    def current_speaker(self):
        """当前持有发言权的 Agent（无则 None）。"""
        return self._current["agent_id"] if self._current else None

    @property
    def current_content(self):
        return self._current["content"] if self._current else None

    @property
    def queued(self):
        """排队中的 agent_id 列表（按补位顺序）。"""
        return [q["agent_id"] for q in self._queue]

    @property
    def is_busy(self) -> bool:
        return self._current is not None

    # ── 请求 / 释放 ────────────────────────────────────────
    def request_speech(self, agent_id, content, priority=0, policy=None,
                       reply_to=""):
        """请求发言权。

        Args:
            reply_to: v6.4 引用链——本条发言回应谁（决策的【回应对象】），
                      随仲裁项透传，排队补位广播时保留。

        Returns:
            True = 立即获得（含打断获得）；False = 排队/丢弃/队列满。
        """
        policy = policy or self._default_policy
        self._pub("speech_requested", agent=agent_id, priority=priority,
                  policy=str(policy))
        if self._current is None:
            self._grant(agent_id, content, reply_to)
            return True
        # 当前有人发言
        if policy == ArbiterPolicy.INTERRUPT and priority >= self._interrupt_priority:
            old = self._current["agent_id"]
            self._pub("speech_cancelled", agent=old, interrupted_by=agent_id)
            self._grant(agent_id, content, reply_to)
            return True
        if policy == ArbiterPolicy.DROP:
            self._pub("speech_dropped", agent=agent_id, policy=str(policy))
            return False
        # QUEUE
        if len(self._queue) >= self._max_queue:
            self._pub("speech_dropped", agent=agent_id, policy="queue_full")
            return False
        self._queue.append({"agent_id": agent_id, "content": content,
                            "priority": priority, "reply_to": reply_to})
        self._pub("speech_queued", agent=agent_id)
        return False

    def release(self):
        """当前发言结束：发布 speech_finished 并从队列补位。

        Returns:
            dict | None：被释放的当前发言者 {"agent_id", "content"}；
            无人在发言则 None。（排队补位者已成为新的 current，由下一次
            release 返回——保证排队者的发言被逐个释放/广播，不丢失。）
        """
        if self._current is None:
            return None
        finished = self._current
        self._current = None
        self._pub("speech_finished", agent=finished["agent_id"])
        self._serve_next()
        return finished

    def drain(self):
        """依次清空队列（每次返回被释放的发言者，供实验主循环逐步广播）。"""
        while self._current is not None:
            released = self.release()
            if released is None:
                break
            yield released

    # ── 内部 ───────────────────────────────────────────────
    def _grant(self, agent_id, content, reply_to=""):
        self._current = {"agent_id": agent_id, "content": content,
                         "reply_to": reply_to}
        self._pub("speech_output_started", agent=agent_id)

    def _serve_next(self):
        if self._current is not None or not self._queue:
            return None
        items = sorted(self._queue, key=lambda q: -q["priority"])
        self._queue = deque(items[1:])
        # v6.6 P1-5 修复：排队补位时透传 reply_to（原实现漏传导致
        # 排队发言的引用链丢失，批次上下文标注"回应谁"缺位）
        self._grant(items[0]["agent_id"], items[0]["content"],
                    items[0].get("reply_to", ""))
        return self._current

    def _pub(self, event_type, **payload):
        if self._bus:
            self._bus.publish(event_type, **payload)
