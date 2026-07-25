"""对话列表 — 微信风格，位于侧边栏与聊天页之间"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from gui.core.config import AppConfig
from gui.core.state import AppState
from gui.resources.icons.codicon import codicon


class ConversationItem(QWidget):
    """对话列表单项 — 名称 + 最新消息预览"""

    def __init__(self, conv: dict, colors: dict, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        # 名称行
        name_layout = QHBoxLayout()
        name_layout.setSpacing(8)

        self._name_label = QLabel(conv.get("name", "新对话"))
        self._name_label.setStyleSheet(f"""
            font-size: 14px; font-weight: 600; color: {colors['text_primary']};
        """)
        name_layout.addWidget(self._name_label)
        name_layout.addStretch()

        # 时间戳
        ts = conv.get("timestamp", 0)
        time_text = self._format_timestamp(ts)
        self._time_label = QLabel(time_text)
        self._time_label.setStyleSheet(f"""
            font-size: 11px; color: {colors['text_secondary']};
        """)
        name_layout.addWidget(self._time_label)

        layout.addLayout(name_layout)

        # 最新消息预览
        last_msg = conv.get("last_message", "")
        self._preview_label = QLabel(last_msg if last_msg else "暂无消息")
        self._preview_label.setStyleSheet(f"""
            font-size: 12px; color: {colors['text_secondary']};
        """)
        self._preview_label.setMaximumHeight(18)
        layout.addWidget(self._preview_label)

    @staticmethod
    def _format_timestamp(ts: int) -> str:
        if ts == 0:
            return ""
        import datetime
        now = datetime.datetime.now()
        dt = datetime.datetime.fromtimestamp(ts)
        if dt.date() == now.date():
            return dt.strftime("%H:%M")
        elif (now - dt).days < 7:
            weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            return weekdays[dt.weekday()]
        else:
            return dt.strftime("%m/%d")

    def update_data(self, conv: dict, colors: dict):
        self._name_label.setText(conv.get("name", "新对话"))
        last_msg = conv.get("last_message", "")
        self._preview_label.setText(last_msg if last_msg else "暂无消息")
        self._time_label.setText(self._format_timestamp(conv.get("timestamp", 0)))
        self._name_label.setStyleSheet(f"""
            font-size: 14px; font-weight: 600; color: {colors['text_primary']};
        """)
        self._preview_label.setStyleSheet(f"""
            font-size: 12px; color: {colors['text_secondary']};
        """)
        self._time_label.setStyleSheet(f"""
            font-size: 11px; color: {colors['text_secondary']};
        """)


class ConversationList(QWidget):
    """对话列表面板 — 固定在聊天页左侧"""

    conversation_selected = Signal(str)  # 发出 conv_id
    conversation_deleted = Signal(str)  # 发出被删除的 conv_id
    show_archive_requested = Signal()  # 打开归档管理窗口

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = AppConfig()
        self._state = AppState()
        self.setFixedWidth(240)
        self.setObjectName("conversationList")

        self._apply_outer_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ─── 头部：标题 + 新建按钮 ────────
        header = QWidget()
        header.setObjectName("convListHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 12, 8, 8)

        title = QLabel("对话")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self._add_btn = QPushButton(codicon.get_char("add"))
        self._add_btn.setToolTip("新建对话")
        self._add_btn.setFixedSize(28, 28)
        colors = self._config.get_all_colors()
        self._add_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; font-size: 18px;
                border-radius: 6px; color: {colors['text_primary']};
            }}
            QPushButton:hover {{ background: rgba(0,0,0,0.06); }}
        """)
        self._add_btn.clicked.connect(self._add_new_conversation)
        header_layout.addWidget(self._add_btn)

        # 归档管理按钮
        self._archive_btn = QPushButton(codicon.get_char("archive"))
        self._archive_btn.setToolTip("归档管理")
        self._archive_btn.setFixedSize(28, 28)
        self._archive_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; font-size: 16px;
                border-radius: 6px; color: {colors['text_primary']};
            }}
            QPushButton:hover {{ background: rgba(0,0,0,0.06); }}
        """)
        self._archive_btn.clicked.connect(self.show_archive_requested.emit)
        header_layout.addWidget(self._archive_btn)

        codicon.init()
        self._add_btn.setFont(codicon.get_font(18))
        self._archive_btn.setFont(codicon.get_font(16))

        layout.addWidget(header)

        # ─── 搜索框（预留） ────────────────
        # 第一版简化，不实现搜索

        # ─── 列表 ──────────────────────────
        self._list = QListWidget()
        self._list.setObjectName("convListWidget")
        self._list.setFrameShape(QListWidget.Shape.NoFrame)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list.setSpacing(1)
        self._list.currentRowChanged.connect(self._on_selection_changed)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._list, 1)

        # ─── 底部新建对话按钮（文字版，更醒目） ──
        self._bottom_new_btn = QPushButton("  ＋  新建对话")
        self._bottom_new_btn.setObjectName("newConvBtn")
        self._bottom_new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bottom_new_btn.clicked.connect(self._add_new_conversation)
        layout.addWidget(self._bottom_new_btn)

        self._apply_bottom_btn_style()

        self._apply_list_style()
        self._rebuild_list()

        # 监听对话列表变化
        self._state.on_change("conversations", lambda _: self._rebuild_list())
        # 监听当前对话切换（选中同步）
        self._state.on_change("current_conversation_id", lambda _: self._sync_selection())

    def _apply_outer_style(self):
        colors = self._config.get_all_colors()
        self.setStyleSheet(f"""
            #conversationList {{
                background-color: {colors['bg_secondary']};
                border-right: 1px solid {colors['border_color']};
            }}
            #convListHeader {{
                background-color: {colors['bg_secondary']};
                border-bottom: 1px solid {colors['border_color']};
            }}
            #convListWidget {{
                background-color: {colors['bg_secondary']};
                border: none;
                outline: none;
            }}
        """)

    def _apply_list_style(self):
        colors = self._config.get_all_colors()
        self._list.setStyleSheet(f"""
            QListWidget {{
                background-color: {colors['bg_secondary']};
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                background-color: {colors['bg_secondary']};
                border: none;
            }}
            QListWidget::item:selected {{
                background-color: {colors['sidebar_active']};
            }}
            QListWidget::item:hover {{
                background-color: {colors['bg_chat']};
            }}
        """)

    def _apply_bottom_btn_style(self):
        colors = self._config.get_all_colors()
        self._bottom_new_btn.setStyleSheet(f"""
            QPushButton#newConvBtn {{
                background-color: {colors['bg_secondary']};
                border: none; border-top: 1px solid {colors['border_color']};
                padding: 10px 0; font-size: 13px;
                color: {colors['text_primary']};
                text-align: left; padding-left: 16px;
            }}
            QPushButton#newConvBtn:hover {{
                background-color: {colors['bg_chat']};
            }}
        """)

    def _rebuild_list(self):
        """根据 AppState 重新构建列表项"""
        self._list.blockSignals(True)
        self._list.clear()
        colors = self._config.get_all_colors()
        current_id = self._state.current_conversation_id

        for conv in self._state.conversations:
            item = QListWidgetItem()
            widget = ConversationItem(conv, colors)
            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, conv["id"])
            self._list.addItem(item)
            self._list.setItemWidget(item, widget)

            # 恢复选中状态
            if conv["id"] == current_id:
                self._list.setCurrentItem(item)

        self._list.blockSignals(False)

        # 如果没有选中项但列表有内容，选中第一个
        if self._list.currentRow() < 0 and self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _on_selection_changed(self, row: int):
        if row < 0:
            return
        item = self._list.item(row)
        if not item:
            return
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        self._state.current_conversation_id = conv_id
        self.conversation_selected.emit(conv_id)

    def _on_context_menu(self, pos):
        """右键菜单 — 重命名 / 新建 / 删除"""
        item = self._list.itemAt(pos)
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { padding: 4px; border-radius: 6px; }
            QMenu::item { padding: 6px 24px; border-radius: 4px; }
            QMenu::item:hover { background: rgba(0,0,0,0.06); }
        """)

        # 新建对话（始终可用）
        new_action = menu.addAction("新建对话")
        menu.addSeparator()

        rename_action = None
        delete_action = None
        if item:
            rename_action = menu.addAction("重命名")
            delete_action = menu.addAction("删除对话")

        action = menu.exec(self._list.mapToGlobal(pos))
        if action == new_action:
            self._add_new_conversation()
        elif rename_action and action == rename_action:
            conv_id = item.data(Qt.ItemDataRole.UserRole)
            self._rename_conversation(conv_id)
        elif delete_action and action == delete_action:
            conv_id = item.data(Qt.ItemDataRole.UserRole)
            self.conversation_deleted.emit(conv_id)
            self._state.archive_conversation(conv_id)
            if conv_id == self._state.current_conversation_id:
                remaining = [c for c in self._state.conversations if c["id"] != conv_id]
                if remaining:
                    self._state.current_conversation_id = remaining[0]["id"]
                    self.conversation_selected.emit(remaining[0]["id"])
                else:
                    new_id = self._state.add_conversation()
                    self._state.current_conversation_id = new_id
                    self.conversation_selected.emit(new_id)

    def _rename_conversation(self, conv_id: str):
        """弹出输入框重命名对话"""
        conv = self._state.get_conversation(conv_id)
        if not conv:
            return
        current_name = conv.get("name", "新对话")
        new_name, ok = QInputDialog.getText(
            self, "重命名对话", "对话名称：",
            QLineEdit.EchoMode.Normal, current_name
        )
        if ok and new_name and new_name.strip():
            conv["name"] = new_name.strip()
            # 触发 setter → 通知 → _rebuild_list 刷新显示
            self._state.conversations = self._state.conversations

    def _add_new_conversation(self):
        conv_id = self._state.add_conversation()
        self._state.current_conversation_id = conv_id
        self.conversation_selected.emit(conv_id)

    def _sync_selection(self):
        """同步当前选中项与 AppState.current_conversation_id"""
        target_id = self._state.current_conversation_id
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == target_id:
                self._list.blockSignals(True)
                self._list.setCurrentItem(item)
                self._list.blockSignals(False)
                break

    def refresh_theme(self):
        """主题变更时刷新样式"""
        self._apply_outer_style()
        self._apply_list_style()
        self._apply_bottom_btn_style()
        # 刷新每个 item
        colors = self._config.get_all_colors()
        for i in range(self._list.count()):
            item = self._list.item(i)
            if not item:
                continue
            w = self._list.itemWidget(item)
            if isinstance(w, ConversationItem):
                conv_id = item.data(Qt.ItemDataRole.UserRole)
                conv = self._state.get_conversation(conv_id)
                if conv:
                    w.update_data(conv, colors)
