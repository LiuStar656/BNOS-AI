"""聊天页 — 消息列表 + ChatInput（WeChat 风格发送框）"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from gui.core.config import AppConfig
from gui.core.message_manager import MessageManager
from gui.core.state import AppState
from gui.widgets.chat_bubble import ChatBubble
from gui.widgets.chat_input import ChatInput


class ChatPage(QWidget):
    """聊天页 — 消息列表 + ChatInput 输入栏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = AppState()
        self._config = AppConfig()
        self._msg_mgr: MessageManager | None = None
        self._current_ai_bubble: ChatBubble | None = None  # 当前正在 append 的 AI 气泡

        self._init_ui()
        self._connect_signals()

    def set_message_manager(self, msg_mgr: MessageManager):
        """设置 MessageManager 实例（由 MainWindow 传入）"""
        self._msg_mgr = msg_mgr
        if self._msg_mgr:
            self._msg_mgr.reply_received.connect(self._on_reply)
            self._msg_mgr.error_occurred.connect(self._on_error)

    def _init_ui(self):
        # 外层水平布局：左右各 5% 空白，中间 90% 内容区
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        left_spacer = QWidget()
        left_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.addWidget(left_spacer)

        # 中间内容容器
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)

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
        self._msg_container.setStyleSheet(f"""
            #msg_container {{ background-color: {colors['bg_chat']}; }}
        """)
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(0, 8, 0, 8)
        self._msg_layout.setSpacing(8)
        self._msg_layout.addStretch(1)  # 弹簧在最底部

        self._scroll_area.setWidget(self._msg_container)
        inner_layout.addWidget(self._scroll_area, 1)

        # ─── ChatInput（WeChat 风格发送框）───────────
        self._chat_input = ChatInput()
        self._chat_input.send_requested.connect(self._send_message)
        inner_layout.addWidget(self._chat_input)

        outer.addWidget(inner)

        right_spacer = QWidget()
        right_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.addWidget(right_spacer)

        # 比例：左 5 : 内容 90 : 右 5
        outer.setStretch(0, 5)
        outer.setStretch(1, 90)
        outer.setStretch(2, 5)

    def _connect_signals(self):
        self._state.on_change("send_state", self._on_send_state_changed)

    # ─── 发送 ──────────────────────────────────

    def _send_message(self, text: str, attachments: list):
        if not self._msg_mgr:
            return

        self._current_ai_bubble = None  # 发送新消息时重置当前 AI 气泡
        self._append_bubble(text, "user")

        # 如果有附件，在气泡下方显示附件信息
        for att in attachments:
            att_text = f"[{'图片' if att['type'] == 'image' else '文件'}] {att['name']}"
            self._append_bubble(att_text, "user")

        ok = self._msg_mgr.send_text(text, attachments)
        if not ok:
            pass

    def _on_send_state_changed(self, state: str):
        if state == "sending":
            self._chat_input.set_enabled(False)
        else:
            self._chat_input.set_enabled(True)
            self._chat_input.set_focus()

    # ─── 接收回复 ──────────────────────────────

    def append_reply(self, text: str):
        """MainWindow 调用此方法添加 AI 回复"""
        text = self._strip_mood_tag(text)
        self._append_bubble(text, "ai")

    def _on_reply(self, text: str):
        # 过滤情绪标签 <xxx>（如 <开心>），仅保留纯文本
        text = self._strip_mood_tag(text)
        if self._current_ai_bubble:
            # 流式追加：直接追加到当前气泡
            self._current_ai_bubble.append_text(text)
            self._scroll_to_bottom()
        else:
            # 新建气泡
            self._current_ai_bubble = self._append_bubble(text, "ai")

    def _on_error(self, msg: str):
        self._append_bubble(f"[错误] {msg}", "ai")

    @staticmethod
    def _strip_mood_tag(text: str) -> str:
        """去除 AAA 注入的情绪标签 <xxx>，保留后续文本"""
        import re
        return re.sub(r'^<\w+>', '', text).strip()

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
        return bubble

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
        # 刷新 ChatInput 样式
        if self._chat_input:
            self._chat_input._apply_styles()
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
