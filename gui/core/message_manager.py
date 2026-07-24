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

# ==================== 路径常量 ====================
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
NODES_DIR = PROJECT_ROOT / "nodes"
SHARED_DIR = NODES_DIR / "shared"
SHARED_DIR.mkdir(parents=True, exist_ok=True)

GUI_INPUT_PATH = str(SHARED_DIR / "gui_input.json")
GUI_REPLY_PATH = str(SHARED_DIR / "gui_reply.json")
BNOS_STATUS_PATH = str(PROJECT_ROOT / "bnos_status.json")


class MessageManager(QObject):
    """消息管理器 — 负责发送用户输入 + 轮询 AI 回复和节点状态。

    信号:
        reply_received(str): 收到 AI 回复文本。
        error_occurred(str): 发生错误。
    """

    reply_received = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = AppState()
        self._last_gui_reply_mtime: float = 0
        self._last_gui_reply_hash: str = ""
        self._poll_timer: QTimer | None = None
        self._send_timer: QTimer | None = None

        # 启动轮询定时器（每 200ms 检查一次）
        self._start_polling()

    def _start_polling(self):
        """启动轮询定时器"""
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._on_poll_tick)
        self._poll_timer.start(200)

    def _on_poll_tick(self):
        """轮询触发回调"""
        self.poll_reply()
        self.poll_status()

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

        # 启动超时定时器（60 秒自动恢复）
        self._start_timeout()
        return True

    def poll_status(self):
        """轮询 bnos_status.json（引擎 NodeMonitor 输出），更新引擎和节点状态"""
        status_path = PROJECT_ROOT / "bnos_status.json"
        if not status_path.exists():
            self._state.engine_status = "offline"
            self._state.nodes = {}
            return

        try:
            with open(status_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        # 映射引擎状态
        raw_engine_status = data.get("engine_status", "offline")
        if raw_engine_status in ("online", "degraded"):
            self._state.engine_status = "online"
        else:
            self._state.engine_status = "offline"

        # 映射节点状态（简化字段）
        raw_nodes = data.get("nodes", {})
        nodes: dict[str, dict] = {}
        for node_name, node_info in raw_nodes.items():
            ns = node_info.get("status", "unknown")
            pid = node_info.get("pid", 0)
            exit_code = node_info.get("exit_code")
            if ns == "running":
                nodes[node_name] = {
                    "online": True,
                    "pid": pid,
                    "detail": f"PID {pid}",
                }
            elif ns == "crashed":
                nodes[node_name] = {
                    "online": False,
                    "pid": pid,
                    "detail": f"exit_code={exit_code}" if exit_code is not None else "",
                }
            elif ns == "stopped":
                nodes[node_name] = {
                    "online": False,
                    "pid": pid,
                    "detail": "正常退出",
                }
            else:
                nodes[node_name] = {
                    "online": False,
                    "pid": pid,
                    "detail": "",
                }

        self._state.nodes = nodes

    def poll_reply(self) -> str | None:
        """轮询 shared/gui_reply.json，返回新回复文本或 None"""
        if not os.path.exists(GUI_REPLY_PATH):
            return None

        try:
            current_mtime = os.path.getmtime(GUI_REPLY_PATH)
        except OSError:
            return None

        if current_mtime <= self._last_gui_reply_mtime:
            return None

        try:
            with open(GUI_REPLY_PATH, "r", encoding="utf-8") as f:
                content = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        content_str = json.dumps(content, ensure_ascii=False)
        content_hash = hashlib.md5(content_str.encode()).hexdigest()
        if content_hash == self._last_gui_reply_hash:
            self._last_gui_reply_mtime = current_mtime
            return None

        self._last_gui_reply_mtime = current_mtime
        self._last_gui_reply_hash = content_hash

        # 解析回复
        reply_text = ""
        if isinstance(content, dict) and content.get("data_type") == "reply":
            reply_text = content.get("content", "")

        if reply_text:
            self._state.send_state = "idle"
            self._cancel_timeout()
            self.reply_received.emit(reply_text)
            return reply_text

        return None

    def poll_status(self):
        """轮询 bnos_status.json（引擎 NodeMonitor 输出），更新引擎和节点状态"""
        status_path = PROJECT_ROOT / "bnos_status.json"
        if not status_path.exists():
            self._state.engine_status = "offline"
            self._state.nodes = {}
            return

        try:
            with open(status_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        # 映射引擎状态
        raw_engine_status = data.get("engine_status", "offline")
        if raw_engine_status in ("online", "degraded"):
            self._state.engine_status = "online"
        else:
            self._state.engine_status = "offline"

        # 映射节点状态
        raw_nodes = data.get("nodes", {})
        nodes: dict[str, dict] = {}
        for node_name, node_info in raw_nodes.items():
            ns = node_info.get("status", "unknown")
            pid = node_info.get("pid", 0)
            exit_code = node_info.get("exit_code")
            if ns == "running":
                nodes[node_name] = {
                    "online": True,
                    "init_status": "ok",
                    "pid": pid,
                    "detail": f"PID {pid}",
                }
            elif ns == "crashed":
                nodes[node_name] = {
                    "online": False,
                    "init_status": "error",
                    "pid": pid,
                    "detail": f"exit_code={exit_code}" if exit_code is not None else "",
                }
            elif ns == "stopped":
                nodes[node_name] = {
                    "online": False,
                    "init_status": "stopped",
                    "pid": pid,
                    "detail": "正常退出",
                }
            else:
                nodes[node_name] = {
                    "online": False,
                    "init_status": "unknown",
                    "pid": pid,
                    "detail": "",
                }

        self._state.nodes = nodes

    def _start_timeout(self):
        """启动 60s 超时定时器"""
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
