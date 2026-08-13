# -*- coding: utf-8 -*-
"""事件总线：平台内部发布/订阅。

用于消息池 → 采集器、仲裁器 → 采集器之间的解耦通信。
事件类型（对齐方案 F6/F8）：
    message_enqueued / message_duplicate_dropped / batch_dispatched
    speech_requested / speech_output_started / speech_queued
    speech_dropped / speech_cancelled / speech_finished
"""


class EventBus:
    """轻量发布/订阅总线（同步调用 handler，handler 异常不阻塞其他订阅者）。"""

    def __init__(self):
        self._subscribers: dict[str, list] = {}

    def subscribe(self, event_type: str, handler):
        """订阅事件。handler 签名：handler(event_type=..., **payload)。"""
        self._subscribers.setdefault(event_type, []).append(handler)

    def publish(self, event_type: str, **payload):
        """发布事件：按订阅顺序同步调用所有 handler。"""
        for handler in self._subscribers.get(event_type, ()):
            try:
                handler(event_type=event_type, **payload)
            except Exception:
                # 单个订阅者异常不影响其他订阅者与发布方
                continue
