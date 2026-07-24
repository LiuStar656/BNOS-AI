"""主窗口 — 左侧 Sidebar + 右侧 QStackedWidget + 底部状态栏"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from gui.pages.chat_page import ChatPage
from gui.pages.live2d_page import Live2DPage
from gui.pages.mcp_page import MCPPage
from gui.pages.node_page import NodePage
from gui.pages.settings_page import SettingsPage
from gui.resources.theme import LIGHT_QSS
from gui.widgets.sidebar import Sidebar
from gui.widgets.status_bar import StatusBar


class MainWindow(QMainWindow):
    """主窗口 — 左侧 Sidebar + 右侧 QStackedWidget + 底部状态栏。"""

    PAGE_CLASSES = {
        "chat":     ChatPage,
        "live2d":   Live2DPage,
        "node":     NodePage,
        "mcp":      MCPPage,
        "settings": SettingsPage,
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("BNOS AI 伴侣")
        self.setMinimumSize(900, 600)
        self.setStyleSheet(LIGHT_QSS)

        self._pages: dict[str, QWidget] = {}

        self._init_central()
        self._init_pages()
        self._connect_signals()

        # 默认显示聊天页
        self._sidebar.set_active("chat")
        self._stack.setCurrentWidget(self._pages["chat"])

    def _init_central(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        # 整体布局：水平分 Sidebar + 内容区
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 左侧标签栏
        self._sidebar = Sidebar()
        main_layout.addWidget(self._sidebar)

        # 右侧内容区（页面栈 + 状态栏）
        right_side = QWidget()
        right_layout = QVBoxLayout(right_side)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._stack = QStackedWidget()
        right_layout.addWidget(self._stack, 1)

        self._status_bar = StatusBar()
        right_layout.addWidget(self._status_bar)

        main_layout.addWidget(right_side, 1)

    def _init_pages(self):
        for page_id, page_cls in self.PAGE_CLASSES.items():
            page = page_cls()
            self._pages[page_id] = page
            self._stack.addWidget(page)

    def _connect_signals(self):
        self._sidebar.page_changed.connect(self._switch_page)

    def _switch_page(self, page_id: str):
        page = self._pages.get(page_id)
        if page:
            self._stack.setCurrentWidget(page)
