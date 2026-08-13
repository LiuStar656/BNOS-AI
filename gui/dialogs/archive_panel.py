"""归档对话管理面板 — 查看/恢复已删除的对话（嵌入 FloatingPanel 使用）"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.core.config import AppConfig
from gui.core.state import AppState


class ArchivePanel(QWidget):
    """归档对话管理面板。传入 _conversation_messages 以显示消息内容。"""

    restored = Signal(str)  # 发出被恢复的对话 id

    def __init__(self, conversation_messages: dict, parent=None):
        super().__init__(parent)
        self._state = AppState()
        self._config = AppConfig()
        self._conversation_messages = conversation_messages

        self._init_ui()
        self._populate_list()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)

        # ─── 左侧：归档列表 ──────────────────
        left = QVBoxLayout()
        left.setSpacing(6)

        title = QLabel("已归档对话")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        left.addWidget(title)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.currentRowChanged.connect(self._on_selection)
        left.addWidget(self._list, 1)

        # 底部按钮
        btn_layout = QHBoxLayout()
        self._restore_btn = QPushButton("恢复选中对话")
        self._restore_btn.clicked.connect(self._on_restore)
        self._restore_btn.setEnabled(False)
        self._restore_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 16px; border-radius: 4px;
                background: #07C160; color: white; font-size: 13px; border: none;
            }
            QPushButton:hover { background: #06AD56; }
            QPushButton:disabled { background: #ccc; }
        """)
        btn_layout.addWidget(self._restore_btn)
        left.addLayout(btn_layout)

        # ─── 右侧：消息预览 ──────────────────
        right = QVBoxLayout()
        right.setSpacing(6)

        preview_label = QLabel("消息预览")
        preview_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        right.addWidget(preview_label)

        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setStyleSheet("""
            QTextEdit {
                border: 1px solid #ddd; border-radius: 6px;
                padding: 8px; font-size: 13px;
                background: #fafafa;
            }
        """)
        right.addWidget(self._preview, 1)

        layout.addLayout(left, 2)
        layout.addLayout(right, 3)

    def _populate_list(self):
        for conv in self._state.archived_conversations:
            cid = conv["id"]
            name = conv.get("name", "新对话")
            last_msg = conv.get("last_message", "")
            preview = last_msg[:40] + "…" if len(last_msg) > 40 else last_msg
            display = f"{name}\n[{cid}] {preview}" if last_msg else f"{name}\n[{cid}] 无消息"

            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, cid)
            self._list.addItem(item)

        if self._list.count() == 0:
            empty = QListWidgetItem("暂无归档对话")
            empty.setFlags(empty.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._list.addItem(empty)

    def refresh_list(self):
        """外部数据变更后刷新列表"""
        self._list.clear()
        self._populate_list()

    def _on_selection(self, row: int):
        if row < 0 or row >= self._list.count():
            self._preview.clear()
            self._restore_btn.setEnabled(False)
            return

        item = self._list.item(row)
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            self._preview.clear()
            self._restore_btn.setEnabled(False)
            return

        conv_id = item.data(Qt.ItemDataRole.UserRole)
        self._restore_btn.setEnabled(True)

        messages = self._conversation_messages.get(conv_id, [])
        if not messages:
            self._preview.setPlainText("（该对话无保存的消息内容）")
            return

        lines = []
        for role, text in messages:
            label = "你" if role == "user" else "AI"
            display_text = text[:200] + "…" if len(text) > 200 else text
            lines.append(f"【{label}】{display_text}")
        self._preview.setPlainText("\n\n".join(lines))

    def _on_restore(self):
        row = self._list.currentRow()
        if row < 0:
            return
        item = self._list.item(row)
        if not item:
            return
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        if not conv_id:
            return

        if self._state.restore_conversation(conv_id):
            self.restored.emit(conv_id)
