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
        self._conversations: list[dict] = []
        self._archived_conversations: list[dict] = []
        self._current_conversation_id: str = ""
        self._listeners: dict[str, list] = {}

        # 初始化默认对话
        self._init_default_conversation()

    def _init_default_conversation(self):
        import uuid
        conv_id = str(uuid.uuid4())[:8]
        self._current_conversation_id = conv_id
        self._conversations.append({
            "id": conv_id,
            "name": "新对话",
            "last_message": "",
            "timestamp": 0,
        })

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

    # ─── 对话管理 ──────────────────────────────────

    @property
    def conversations(self) -> list[dict]:
        return self._conversations

    @conversations.setter
    def conversations(self, value: list[dict]) -> None:
        self._conversations = value
        self._notify("conversations", value)

    @property
    def current_conversation_id(self) -> str:
        return self._current_conversation_id

    @current_conversation_id.setter
    def current_conversation_id(self, value: str) -> None:
        if value != self._current_conversation_id:
            self._current_conversation_id = value
            self._notify("current_conversation_id", value)

    def add_conversation(self, name: str = "新对话") -> str:
        """添加新对话并返回其 id"""
        import uuid
        conv_id = str(uuid.uuid4())[:8]
        self._conversations.append({
            "id": conv_id,
            "name": name,
            "last_message": "",
            "timestamp": 0,
        })
        self._notify("conversations", self._conversations)
        return conv_id

    def remove_conversation(self, conv_id: str) -> None:
        self._conversations = [c for c in self._conversations if c["id"] != conv_id]
        self._notify("conversations", self._conversations)

    def archive_conversation(self, conv_id: str) -> dict | None:
        """将对话从主列表移至归档列表（软删除）"""
        conv = self.get_conversation(conv_id)
        if not conv:
            return None
        self._conversations = [c for c in self._conversations if c["id"] != conv_id]
        # 加入归档（避免重复）
        if not any(c["id"] == conv_id for c in self._archived_conversations):
            self._archived_conversations.append(conv)
        self._notify("conversations", self._conversations)
        self._notify("archived_conversations", self._archived_conversations)
        return conv

    def restore_conversation(self, conv_id: str) -> bool:
        """从归档列表恢复对话至主列表"""
        conv = self.get_archived_conversation(conv_id)
        if not conv:
            return False
        self._archived_conversations = [
            c for c in self._archived_conversations if c["id"] != conv_id
        ]
        self._conversations.append(conv)
        self._notify("conversations", self._conversations)
        self._notify("archived_conversations", self._archived_conversations)
        return True

    @property
    def archived_conversations(self) -> list[dict]:
        return self._archived_conversations

    @archived_conversations.setter
    def archived_conversations(self, value: list[dict]) -> None:
        self._archived_conversations = value
        self._notify("archived_conversations", value)

    def get_archived_conversation(self, conv_id: str) -> dict | None:
        for c in self._archived_conversations:
            if c["id"] == conv_id:
                return c
        return None

    def update_conversation_preview(self, conv_id: str, message: str) -> None:
        for c in self._conversations:
            if c["id"] == conv_id:
                c["last_message"] = message[:60]
                import time
                c["timestamp"] = int(time.time())
                break
        self._notify("conversations", self._conversations)

    def get_conversation(self, conv_id: str) -> dict | None:
        for c in self._conversations:
            if c["id"] == conv_id:
                return c
        return None
