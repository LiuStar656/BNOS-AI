"""事件总线系统 — 从 BNOS 参考源码复用，去除 logger 依赖"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal


class EventBus(QObject):
    """事件总线 — 发布-订阅模式，组件间解耦通信。"""

    event_signal = Signal(str, object)

    def __init__(self):
        super().__init__()
        self._handlers: dict[str, list[Callable]] = {}
        self._lock = threading.Lock()
        self.event_signal.connect(self._dispatch)

    def subscribe(self, event_type: str, handler: Callable):
        with self._lock:
            self._handlers.setdefault(event_type, [])
            if handler not in self._handlers[event_type]:
                self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Callable):
        with self._lock:
            handlers = self._handlers.get(event_type, [])
            try:
                handlers.remove(handler)
            except ValueError:
                pass

    def publish(self, event_type: str, data: Any = None):
        self.event_signal.emit(event_type, data)

    def _dispatch(self, event_type: str, data: Any):
        with self._lock:
            handlers = list(self._handlers.get(event_type, []))
        for handler in handlers:
            try:
                handler(data)
            except Exception as e:
                print(f"[EventBus] Error handling '{event_type}': {e}")


event_bus = EventBus()
