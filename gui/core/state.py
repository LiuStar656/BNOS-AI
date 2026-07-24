"""全局应用状态管理 — Singleton 模式"""

from __future__ import annotations

from typing import Any


class Singleton(type):
    _instances: dict = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


_engine_status_values = ("offline", "starting", "online", "error")
_send_state_values = ("idle", "sending")


class AppState(metaclass=Singleton):
    """全局应用状态。

    属性变更时自动通过 event_bus 发布事件。
    """

    def __init__(self):
        self._engine_status: str = "offline"
        self._current_model: str = ""
        self._nodes: dict[str, dict] = {}
        self._send_state: str = "idle"
        self._listeners: dict[str, list] = {}

    def on_change(self, key: str, callback) -> None:
        self._listeners.setdefault(key, []).append(callback)

    def _notify(self, key: str, value: Any) -> None:
        for cb in self._listeners.get(key, []):
            try:
                cb(value)
            except Exception:
                pass

    @property
    def engine_status(self) -> str:
        return self._engine_status

    @engine_status.setter
    def engine_status(self, value: str) -> None:
        if value in _engine_status_values and value != self._engine_status:
            self._engine_status = value
            self._notify("engine_status", value)

    @property
    def current_model(self) -> str:
        return self._current_model

    @current_model.setter
    def current_model(self, value: str) -> None:
        if value != self._current_model:
            self._current_model = value
            self._notify("current_model", value)

    @property
    def nodes(self) -> dict[str, dict]:
        return self._nodes

    @nodes.setter
    def nodes(self, value: dict[str, dict]) -> None:
        self._nodes = value
        self._notify("nodes", value)

    @property
    def send_state(self) -> str:
        return self._send_state

    @send_state.setter
    def send_state(self, value: str) -> None:
        if value in _send_state_values and value != self._send_state:
            self._send_state = value
            self._notify("send_state", value)
