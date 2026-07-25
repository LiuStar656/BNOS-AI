"""聊天页 — 消息列表 + ChatInput（WeChat 风格发送框）"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from gui.core.config import AppConfig
from gui.core.message_manager import MessageManager
from gui.core.state import AppState
from gui.widgets.chat_bubble import ChatBubble
from gui.widgets.chat_input import ChatInput
from gui.widgets.conversation_list import ConversationList

_TYPING_INTERVAL_MS = 50  # 逐字输出间隔（毫秒）

# 对话历史持久化文件
_HISTORY_FILE = Path(__file__).resolve().parent / "conversation_history.json"


class ChatPage(QWidget):
    """聊天页 — 消息列表 + ChatInput 输入栏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = AppState()
        self._config = AppConfig()
        self._msg_mgr: MessageManager | None = None
        self._current_ai_bubble: ChatBubble | None = None  # 当前正在 append 的 AI 气泡
        self._conversation_messages: dict[str, list[tuple[str, str]]] = {}  # conv_id -> [(role, text)]
        self._prev_conv_id: str = ""  # 切换前记录旧对话 id

        # 打字机效果状态
        self._typing_timer: QTimer | None = None
        self._typing_text: str = ""
        self._typing_index: int = 0

        # 从历史文件恢复对话状态
        self._load_history()

        self._init_ui()
        # 记录初始对话 id，供切换时保存使用
        self._prev_conv_id = self._state.current_conversation_id
        self._connect_signals()
        # 加载当前对话的气泡
        self._load_conversation_messages(self._state.current_conversation_id)

    def set_message_manager(self, msg_mgr: MessageManager):
        """设置 MessageManager 实例（由 MainWindow 传入）"""
        self._msg_mgr = msg_mgr
        if self._msg_mgr:
            self._msg_mgr.reply_received.connect(self._on_reply)
            self._msg_mgr.error_occurred.connect(self._on_error)

    def _init_ui(self):
        # 外层水平布局：对话列表 + 聊天区（带右侧留白）
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ─── 对话列表（左侧 240px）─────────
        self._conv_list = ConversationList()
        self._conv_list.conversation_selected.connect(self._on_conversation_changed)
        outer.addWidget(self._conv_list)

        # 中间内容容器（聊天面板）
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
        self._msg_layout.setContentsMargins(0, 10, 0, 10)
        self._msg_layout.setSpacing(12)
        self._msg_layout.addStretch(1)  # 弹簧在最底部

        self._scroll_area.setWidget(self._msg_container)
        inner_layout.addWidget(self._scroll_area, 1)

        # ─── ChatInput（WeChat 风格发送框）───────────
        self._chat_input = ChatInput()
        self._chat_input.send_requested.connect(self._send_message)
        inner_layout.addWidget(self._chat_input)

        outer.addWidget(inner)

        # 右侧留白（5%）
        right_spacer = QWidget()
        right_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.addWidget(right_spacer)

        # 比例：对话列表固定 240px, 聊天区按比例
        outer.setStretch(0, 0)   # ConversationList 固定宽度
        outer.setStretch(1, 90)  # 聊天区
        outer.setStretch(2, 5)   # 右侧留白

    def _connect_signals(self):
        self._state.on_change("send_state", self._on_send_state_changed)
        self._conv_list.conversation_deleted.connect(self._on_conversation_deleted)

    # ─── 对话切换 ────────────────────────────────

    def _on_conversation_changed(self, conv_id: str):
        """切换对话 — 保存当前消息（用旧 id），加载目标对话消息"""
        self._cancel_typing()  # 取消打字动画
        # 用 _prev_conv_id 保存当前消息（state.current 已被覆盖）
        if self._prev_conv_id:
            self._save_current_messages(self._prev_conv_id)
        # 通知后端切换对话
        if self._msg_mgr:
            self._msg_mgr.send_switch_conversation(conv_id)
        # 清除显示
        self.clear_messages()
        # 记录新 id 供下次切换使用
        self._prev_conv_id = conv_id
        # 加载目标对话的消息
        self._load_conversation_messages(conv_id)
        self._current_ai_bubble = None

    def _on_conversation_deleted(self, conv_id: str):
        """对话被删除 → 清理消息缓存"""
        self._conversation_messages.pop(conv_id, None)
        self._save_history()

    def _save_current_messages(self, conv_id: str):
        """将当前气泡保存到内存字典 + 持久化文件"""
        if not conv_id:
            return
        messages = []
        for i in range(self._msg_layout.count()):
            item = self._msg_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), ChatBubble):
                messages.append((item.widget().role, item.widget()._text))
        if messages:
            self._conversation_messages[conv_id] = messages
        self._save_history()

    def _load_conversation_messages(self, conv_id: str):
        """从内存字典加载指定对话的消息"""
        messages = self._conversation_messages.get(conv_id, [])
        for role, text in messages:
            self._append_bubble(text, role)
        self._scroll_to_bottom()

    # ─── 持久化 ────────────────────────────────

    def _save_history(self):
        """将对话消息 + 对话列表元数据写入 JSON 文件"""
        try:
            data: dict = {
                "current_conv_id": self._state.current_conversation_id,
                "convs": {},
                "archived_convs": {},
            }
            # 活跃对话
            for conv in self._state.conversations:
                cid = conv["id"]
                data["convs"][cid] = {
                    "name": conv.get("name", "新对话"),
                    "last_message": conv.get("last_message", ""),
                    "timestamp": conv.get("timestamp", 0),
                    "messages": self._conversation_messages.get(cid, []),
                }
            # 归档对话
            for conv in self._state.archived_conversations:
                cid = conv["id"]
                data["archived_convs"][cid] = {
                    "name": conv.get("name", "新对话"),
                    "last_message": conv.get("last_message", ""),
                    "timestamp": conv.get("timestamp", 0),
                    "messages": self._conversation_messages.get(cid, []),
                }
            with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ChatPage] 保存对话历史失败: {e}")

    def _load_history(self):
        """从 JSON 文件恢复对话消息 + 对话列表 + 归档"""
        if not _HISTORY_FILE.exists():
            return
        try:
            with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[ChatPage] 加载对话历史失败: {e}")
            return

        # 恢复活跃对话
        raw_convs = data.get("convs", {})
        restored = []
        for cid, info in raw_convs.items():
            restored.append({
                "id": cid,
                "name": info.get("name", "新对话"),
                "last_message": info.get("last_message", ""),
                "timestamp": info.get("timestamp", 0),
            })
            msgs = info.get("messages", [])
            if msgs:
                self._conversation_messages[cid] = [(r, t) for r, t in msgs]

        if restored:
            self._state.conversations = restored

        # 恢复归档对话
        raw_archived = data.get("archived_convs", {})
        archived_restored = []
        for cid, info in raw_archived.items():
            archived_restored.append({
                "id": cid,
                "name": info.get("name", "新对话"),
                "last_message": info.get("last_message", ""),
                "timestamp": info.get("timestamp", 0),
            })
            msgs = info.get("messages", [])
            if msgs:
                self._conversation_messages[cid] = [(r, t) for r, t in msgs]

        if archived_restored:
            self._state.archived_conversations = archived_restored

        # 恢复当前对话 ID
        cur = data.get("current_conv_id", "")
        all_convs = restored + archived_restored
        if cur and any(c["id"] == cur for c in all_convs):
            self._state.current_conversation_id = cur
        elif restored:
            self._state.current_conversation_id = restored[0]["id"]

    # ─── 发送 ──────────────────────────────────

    def _send_message(self, text: str, attachments: list):
        if not self._msg_mgr:
            return

        self._cancel_typing()  # 取消正在进行的打字动画
        self._current_ai_bubble = None  # 发送新消息时重置当前 AI 气泡
        self._append_bubble(text, "user")

        # 自动生成标题：首条消息时取前 20 字作为对话名
        conv_id = self._state.current_conversation_id
        conv = self._state.get_conversation(conv_id)
        if conv and conv.get("name", "") in ("新对话", ""):
            title = text[:20].strip()
            if len(text) > 20:
                title += "…"
            if title:
                conv["name"] = title

        # 保存用户消息到内存字典
        self._save_current_messages(conv_id)

        # 如果有附件，在气泡下方显示附件信息
        for att in attachments:
            att_text = f"[{'图片' if att['type'] == 'image' else '文件'}] {att['name']}"
            self._append_bubble(att_text, "user")

        # 更新对话预览
        self._state.update_conversation_preview(
            self._state.current_conversation_id, text
        )

        ok = self._msg_mgr.send_text(text, attachments)
        if not ok:
            pass

    def _on_send_state_changed(self, state: str):
        if state == "sending":
            self._chat_input.set_enabled(False)
        else:
            self._chat_input.set_enabled(True)
            self._chat_input.set_focus()

    # ─── 接收回复（逐字打字机效果） ─────────────

    def append_reply(self, text: str):
        """MainWindow 调用此方法添加 AI 回复"""
        text = self._strip_mood_tag(text)
        self._start_typing(text)

    def _on_reply(self, text: str):
        """收到 AI 回复 → 去掉情绪标签 → 逐字显示"""
        text = self._strip_mood_tag(text)
        if not text:
            return
        self._start_typing(text)

    def _start_typing(self, text: str):
        """开始逐字输出"""
        self._cancel_typing()
        # 创建空气泡
        self._current_ai_bubble = self._append_bubble("", "ai")
        # 准备打字
        self._typing_text = text
        self._typing_index = 0
        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(_TYPING_INTERVAL_MS)
        self._typing_timer.timeout.connect(self._type_next_char)
        self._typing_timer.start()

    def _type_next_char(self):
        """打字机定时器回调：输出下一个字符"""
        if self._typing_index >= len(self._typing_text) or not self._current_ai_bubble:
            # 打字完成 → 保存 AI 回复到内存字典
            if self._state.current_conversation_id:
                self._save_current_messages(self._state.current_conversation_id)
            self._cancel_typing()
            return

        char = self._typing_text[self._typing_index]
        self._typing_index += 1
        self._current_ai_bubble.append_text(char)
        self._scroll_to_bottom()

    def _cancel_typing(self):
        """取消打字动画"""
        if self._typing_timer:
            self._typing_timer.stop()
            self._typing_timer = None
        self._typing_text = ""
        self._typing_index = 0

    def _on_error(self, msg: str):
        self._append_bubble(f"[错误] {msg}", "ai")

    @staticmethod
    def _strip_mood_tag(text: str) -> str:
        """去除 AAA 注入的情绪标签 <xxx>（支持中英文），保留后续文本"""
        import re
        # \w 不匹配中文，改用 [^>]+ 匹配尖括号内任意非 > 字符
        return re.sub(r'^<[^>]+>', '', text).strip()

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
        """主题变更后刷新输入栏样式及对话列表"""
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
        # 刷新对话列表主题
        if self._conv_list:
            self._conv_list.refresh_theme()

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
