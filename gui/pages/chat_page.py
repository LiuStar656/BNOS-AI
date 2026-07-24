"""聊天页 — 消息列表 + 输入框 + 发送按钮 + 状态锁"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.core.message_manager import MessageManager
from gui.core.state import AppState
from gui.widgets.chat_bubble import ChatBubble


class ChatPage(QWidget):
    """聊天页 — 消息列表 + 输入框 + 发送按钮。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = AppState()
        self._msg_mgr = MessageManager(self)

        self._init_ui()
        self._init_timers()
        self._connect_signals()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ─── 消息列表 ───
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setObjectName("chat_scroll")
        self._scroll_area.setStyleSheet("""
            #chat_scroll { background-color: #f0f2f5; border: none; }
        """)

        self._msg_container = QWidget()
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(0, 8, 0, 8)
        self._msg_layout.setSpacing(4)
        self._msg_layout.addStretch(1)

        self._scroll_area.setWidget(self._msg_container)
        layout.addWidget(self._scroll_area, 1)

        # ─── 输入区域 ───
        input_bar = QWidget()
        input_bar.setObjectName("input_bar")
        input_bar.setStyleSheet("""
            #input_bar {
                background-color: #ffffff;
                border-top: 1px solid #e0e0e0;
                padding: 8px 12px;
            }
        """)
        input_layout = QHBoxLayout(input_bar)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)

        self._input_box = QLineEdit()
        self._input_box.setPlaceholderText("输入消息...")
        self._input_box.returnPressed.connect(self._send_message)
        input_layout.addWidget(self._input_box, 1)

        self._send_btn = QPushButton("发送")
        self._send_btn.setFixedWidth(64)
        self._send_btn.clicked.connect(self._send_message)
        input_layout.addWidget(self._send_btn)

        layout.addWidget(input_bar)

    def _init_timers(self):
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_reply)
        self._poll_timer.start(500)

    def _connect_signals(self):
        self._msg_mgr.reply_received.connect(self._on_reply)
        self._msg_mgr.error_occurred.connect(self._on_error)
        self._state.on_change("send_state", self._on_send_state_changed)

    # ─── 发送 ──────────────────────────────────

    def _send_message(self):
        text = self._input_box.text().strip()
        if not text:
            return

        self._input_box.clear()
        self._append_bubble(text, "user")
        ok = self._msg_mgr.send_text(text)
        if not ok:
            # 状态锁拦截时，显示提示
            pass

    def _on_send_state_changed(self, state: str):
        if state == "sending":
            self._input_box.setEnabled(False)
            self._send_btn.setEnabled(False)
            self._input_box.setPlaceholderText("发送中...")
        else:
            self._input_box.setEnabled(True)
            self._send_btn.setEnabled(True)
            self._input_box.setPlaceholderText("输入消息...")
            self._input_box.setFocus()

    # ─── 轮询回复 ──────────────────────────────

    def _poll_reply(self):
        self._msg_mgr.poll_reply()

    def _on_reply(self, text: str):
        self._append_bubble(text, "ai")

    def _on_error(self, msg: str):
        self._append_bubble(f"[错误] {msg}", "ai")

    # ─── 气泡管理 ──────────────────────────────

    def _append_bubble(self, text: str, role: str):
        bubble = ChatBubble(text, role)
        # 插入到 stretch 之前
        count = self._msg_layout.count()
        self._msg_layout.insertWidget(count - 1, bubble)

        # 滚动到底部
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        scrollbar = self._scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_messages(self):
        while self._msg_layout.count() > 1:
            item = self._msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
