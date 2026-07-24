"""主窗口 — 左侧 Sidebar + 右侧 QStackedWidget + 底部状态栏"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from gui.core.event_bus import event_bus
from gui.core.message_manager import MessageManager
from gui.core.config import AppConfig
from gui.core.state import AppState
from gui.pages.chat_page import ChatPage
from gui.pages.live2d_page import Live2DPage
from gui.pages.mcp_page import MCPPage
from gui.pages.node_page import NodePage
from gui.pages.settings_page import SettingsPage
from gui.resources.theme import get_light_qss
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
        self.setMaximumSize(1400, 1000)
        self.setStyleSheet(get_light_qss())

        self._config = AppConfig()
        self._state = AppState()
        self._message_manager: MessageManager | None = None
        self._pages: dict[str, QWidget] = {}

        self._init_central()
        self._init_pages()
        self._connect_signals()

        # 恢复窗口位置和尺寸
        self._restore_window_geometry()

        # 默认显示聊天页
        self._sidebar.set_active("chat")
        self._stack.setCurrentWidget(self._pages["chat"])

        # 启动后发送 init_check
        from PySide6.QtCore import QTimer
        QTimer.singleShot(500, self._on_initialized)

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

        # 创建 MessageManager 并连接信号
        self._message_manager = MessageManager(self)
        self._message_manager.error_occurred.connect(self._on_error_occurred)

        # 将 MessageManager 传给 ChatPage
        if "chat" in self._pages and hasattr(self._pages["chat"], "set_message_manager"):
            self._pages["chat"].set_message_manager(self._message_manager)

        # 监听状态变化
        self._state.on_change("engine_status", self._on_engine_status_changed)
        self._state.on_change("current_model", self._on_current_model_changed)
        self._state.on_change("nodes", self._on_nodes_changed)

        # 监听主题变更
        event_bus.subscribe("theme_changed", self._on_theme_changed)

    # ─── 主题刷新 ──────────────────────────────

    def _on_theme_changed(self, _data=None):
        """主题颜色在设置页被修改时触发刷新"""
        # 1. 刷新全局 QSS
        self.setStyleSheet(get_light_qss())
        # 2. 刷新侧边栏样式
        self._sidebar.refresh_theme()
        # 3. 刷新状态栏样式
        self._status_bar.refresh_theme()
        # 4. 刷新气泡颜色
        chat_page = self._pages.get("chat")
        if chat_page and hasattr(chat_page, "refresh_bubble_themes"):
            chat_page.refresh_bubble_themes()
        # 5. 刷新输入栏样式
        if chat_page and hasattr(chat_page, "refresh_input_bar"):
            chat_page.refresh_input_bar()

    # ─── 初始化 ──────────────────────────────

    def _on_initialized(self):
        """GUI 初始化完成后调用"""
        pass

    def _on_error_occurred(self, error: str):
        """发生错误"""
        pass

    def _on_engine_status_changed(self, status: str):
        """引擎状态变化"""
        self._status_bar.update_engine(status)

    def _on_current_model_changed(self, model: str):
        """当前模型变化"""
        self._status_bar.update_model(model)

    def _on_nodes_changed(self, nodes: dict):
        """节点状态变化"""
        online = sum(1 for node in nodes.values() if node.get("online"))
        total = len(nodes)
        self._status_bar.update_nodes(online, total)

    def _switch_page(self, page_id: str):
        page = self._pages.get(page_id)
        if page:
            self._stack.setCurrentWidget(page)

    def _restore_window_geometry(self):
        """从配置恢复窗口位置和尺寸"""
        geometry = self._config.get("window", {}).get("geometry", {})
        x = geometry.get("x", 100)
        y = geometry.get("y", 100)
        w = geometry.get("width", 900)
        h = geometry.get("height", 680)

        # 确保窗口尺寸在合理范围内
        w = max(900, min(1400, w))
        h = max(600, min(1000, h))

        self.setGeometry(x, y, w, h)

    def _save_window_geometry(self):
        """保存窗口位置和尺寸到配置"""
        geometry = self.geometry()
        self._config.set("window", {
            "geometry": {
                "x": geometry.x(),
                "y": geometry.y(),
                "width": geometry.width(),
                "height": geometry.height()
            }
        })
        self._config.save()

    def closeEvent(self, event):
        """窗口关闭时保存配置"""
        self._save_window_geometry()
        super().closeEvent(event)
