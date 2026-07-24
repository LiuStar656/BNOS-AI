"""聊天页 — 消息列表 + 输入框 + 发送按钮 + 状态锁"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.core.config import AppConfig
from gui.core.message_manager import MessageManager
from gui.core.state import AppState
from gui.widgets.chat_bubble import ChatBubble


class ChatPage(QWidget):
    """聊天页 — 消息列表 + 输入框 + 发送按钮。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = AppState()
        self._config = AppConfig()
        self._msg_mgr: MessageManager | None = None

        self._init_ui()
        self._connect_signals()

    def set_message_manager(self, msg_mgr: MessageManager):
        """设置 MessageManager 实例（由 MainWindow 传入）"""
        self._msg_mgr = msg_mgr
        if self._msg_mgr:
            self._msg_mgr.reply_received.connect(self._on_reply)
            self._msg_mgr.error_occurred.connect(self._on_error)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        colors = self._config.get_all_colors()

        # 页面背景色（QPalette 方式，比 QSS 类选择器更可靠）
        p = self.palette()
        p.setColor(QPalette.Window, QColor(colors['bg_chat']))
        self.setPalette(p)
        self.setAutoFillBackground(True)

        # ─── 消息列表滚动区域 ──────────────────────────
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setObjectName("chat_scroll")
        self._scroll_area.setStyleSheet(f"""
            QScrollArea#chat_scroll {{ background-color: {colors['bg_chat']}; border: none; }}
        """)

        # 消息列表容器（气泡从下往上堆叠，类似微信）
        self._msg_container = QWidget()
        self._msg_container.setObjectName("msg_container")
        # 容器背景：与滚动区域一致
        self._msg_container.setStyleSheet(f"""
            #msg_container {{ background-color: {colors['bg_chat']}; }}
        """)
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(0, 8, 0, 8)
        self._msg_layout.setSpacing(8)
        # 弹簧在最底部：气泡总是插入到弹簧之前，实现从下往上堆叠
        self._msg_layout.addStretch(1)

        self._scroll_area.setWidget(self._msg_container)
        layout.addWidget(self._scroll_area, 1)

        # ─── 输入区域 ──────────────────────────────────
        input_bar = QWidget()
        input_bar.setObjectName("input_bar")
        input_bar.setStyleSheet(f"""
            #input_bar {{
                background-color: {colors['bg_secondary']};
                border-top: 1px solid {colors['border_color']};
                padding: 12px 16px;
            }}
        """)
        input_layout = QHBoxLayout(input_bar)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(12)

        self._input_box = QLineEdit()
        self._input_box.setPlaceholderText("输入消息...")
        self._input_box.returnPressed.connect(self._send_message)
        input_layout.addWidget(self._input_box, 1)

        self._send_btn = QPushButton("发送")
        self._send_btn.setFixedWidth(80)
        self._send_btn.clicked.connect(self._send_message)
        input_layout.addWidget(self._send_btn)

        layout.addWidget(input_bar)

    def _connect_signals(self):
        self._state.on_change("send_state", self._on_send_state_changed)

    # ─── 发送 ──────────────────────────────────

    def _send_message(self):
        if not self._msg_mgr:
            return

        text = self._input_box.text().strip()
        if not text:
            return

        self._input_box.clear()
        self._append_bubble(text, "user")
        ok = self._msg_mgr.send_text(text)
        if not ok:
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

    # ─── 接收回复 ──────────────────────────────

    def append_reply(self, text: str):
        """MainWindow 调用此方法添加 AI 回复"""
        self._append_bubble(text, "ai")

    def _on_reply(self, text: str):
        self._append_bubble(text, "ai")

    def _on_error(self, msg: str):
        self._append_bubble(f"[错误] {msg}", "ai")

    # ─── 气泡管理 ──────────────────────────────

    def _append_bubble(self, text: str, role: str):
        bubble = ChatBubble(text, role)
        # 插入到 stretch 之前（最新消息在最下面）
        count = self._msg_layout.count()
        self._msg_layout.insertWidget(count - 1, bubble)

        # 强制刷新布局
        self._msg_container.updateGeometry()
        self._scroll_area.updateGeometry()
        self.updateGeometry()

        # 立即滚动到底部
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        """事件队列处理完成后滚动到底部（确保布局已生效）"""
        QTimer.singleShot(0, lambda: self._scroll_area.verticalScrollBar().setValue(
            self._scroll_area.verticalScrollBar().maximum()
        ))

    def refresh_bubble_themes(self):
        """主题变更后刷新所有已有气泡的颜色"""
        for i in range(self._msg_layout.count()):
            item = self._msg_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), ChatBubble):
                item.widget()._apply_theme()

    def refresh_input_bar(self):
        """主题变更后刷新输入栏样式"""
        colors = self._config.get_all_colors()
        # 刷新页面背景（QPalette）
        p = self.palette()
        p.setColor(QPalette.Window, QColor(colors['bg_chat']))
        self.setPalette(p)
        self.setAutoFillBackground(True)
        # 刷新消息容器背景
        msg_container = self.findChild(QWidget, "msg_container")
        if msg_container:
            msg_container.setStyleSheet(f"""
                #msg_container {{ background-color: {colors['bg_chat']}; }}
            """)
        input_bar = self.findChild(QWidget, "input_bar")
        if input_bar:
            input_bar.setStyleSheet(f"""
                #input_bar {{
                    background-color: {colors['bg_secondary']};
                    border-top: 1px solid {colors['border_color']};
                    padding: 12px 16px;
                }}
            """)
        # 刷新滚动区域背景
        self._scroll_area.setStyleSheet(f"""
            QScrollArea#chat_scroll {{ background-color: {colors['bg_chat']}; border: none; }}
        """)

    def clear_messages(self):
        """清除所有消息气泡"""
        while self._msg_layout.count() > 1:
            item = self._msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def resizeEvent(self, event):
        """窗口尺寸变化时确保滚动到最新消息"""
        super().resizeEvent(event)
        self._scroll_to_bottom()
