"""消息收发管理 — 轮询后端产出文件 + 发送状态锁"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from gui.core.state import AppState

# ─── 路径常量 ──────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
NODES_DIR = PROJECT_ROOT / "nodes"
SHARED_DIR = NODES_DIR / "shared"
SHARED_DIR.mkdir(parents=True, exist_ok=True)

GUI_INPUT_PATH = str(SHARED_DIR / "gui_input.json")
AAA_OUTPUT_PATH = str(NODES_DIR / "node_python_aaa_cognition" / "output.json")


class MessageManager(QObject):
    """消息管理器 — 负责发送用户输入 + 轮询 AI 回复。

    信号:
        reply_received(str): 收到 AI 回复文本。
        error_occurred(str): 发生错误。
    """

    reply_received = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = AppState()
        self._last_aaa_mtime: float = 0
        self._last_aaa_hash: str = ""
        self._send_timer: QTimer | None = None

    def send_text(self, text: str) -> bool:
        """发送文本消息到后端。

        如果当前状态为 sending 则忽略（发送状态锁）。
        返回 True 表示发送成功，False 表示被状态锁拦截。
        """
        if self._state.send_state == "sending":
            return False

        self._state.send_state = "sending"

        data = {
            "data_type": "text",
            "content": text,
            "source": "gui",
            "timestamp": datetime.now().isoformat(),
        }
        try:
            with open(GUI_INPUT_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.error_occurred.emit(f"写入输入文件失败: {e}")
            self._state.send_state = "idle"
            return False

        # 启动超时计时器（60s 自动恢复）
        self._start_timeout()
        return True

    def poll_reply(self) -> str | None:
        """轮询 aaa_cognition output.json，返回新回复文本或 None。"""
        if not os.path.exists(AAA_OUTPUT_PATH):
            return None

        try:
            current_mtime = os.path.getmtime(AAA_OUTPUT_PATH)
        except OSError:
            return None

        if current_mtime <= self._last_aaa_mtime:
            return None

        try:
            with open(AAA_OUTPUT_PATH, "r", encoding="utf-8") as f:
                content = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        content_str = json.dumps(content, ensure_ascii=False)
        content_hash = hashlib.md5(content_str.encode()).hexdigest()
        if content_hash == self._last_aaa_hash:
            self._last_aaa_mtime = current_mtime
            return None

        self._last_aaa_mtime = current_mtime
        self._last_aaa_hash = content_hash

        # 解析回复
        data = content.get("data", {})
        reply_text = ""

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("data_type") == "reply":
                    reply_text = item.get("content", "")
                    break
        elif isinstance(data, dict):
            dt = data.get("data_type", "")
            if dt == "reply":
                reply_text = data.get("content", "")
            elif dt == "parsed":
                reply_text = data.get("content", "")

        if reply_text:
            self._state.send_state = "idle"
            self._cancel_timeout()
            self.reply_received.emit(reply_text)
            return reply_text

        return None

    def _start_timeout(self):
        """启动 60s 超时计时器。"""
        self._cancel_timeout()
        self._send_timer = QTimer(self)
        self._send_timer.setSingleShot(True)
        self._send_timer.timeout.connect(self._on_timeout)
        self._send_timer.start(60000)

    def _cancel_timeout(self):
        if self._send_timer and self._send_timer.isActive():
            self._send_timer.stop()
        self._send_timer = None

    def _on_timeout(self):
        self._state.send_state = "idle"
        self.error_occurred.emit("发送超时，请重试")
