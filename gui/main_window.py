"""主窗口 — 自定义标题栏 + 左侧 Sidebar + 右侧 QStackedWidget + 底部状态栏"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
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
from gui.widgets.title_bar import TitleBar

_RESIZE_MARGIN = 6  # 窗口边缘 resize 区域宽度


class MainWindow(QMainWindow):
    """主窗口 — 自定义标题栏 + 左侧 Sidebar + 右侧 QStackedWidget + 底部状态栏。"""

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
        self.setMaximumSize(1500, 1000)

        # 启用无边框窗口 + 保留系统菜单（支持 Alt+F4、右键菜单等）
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowSystemMenuHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(get_light_qss())

        self._config = AppConfig()
        self._state = AppState()
        self._message_manager: MessageManager | None = None
        self._pages: dict[str, QWidget] = {}
        self._resize_edge = 0  # 当前鼠标所在边缘

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
        # 外层容器（白色圆角背景，模拟窗口内容区）
        central = QWidget()
        central.setObjectName("centralWidget")
        central.setStyleSheet("""
            QWidget#centralWidget {
                background-color: white;
                border-radius: 8px;
            }
        """)
        self.setCentralWidget(central)

        # 整体布局：竖排 标题栏 + 内容区
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 顶部自定义标题栏
        self._title_bar = TitleBar(self, "BNOS AI 伴侣")
        main_layout.addWidget(self._title_bar)

        # 内容区（Sidebar + 页面栈 + 状态栏）
        content = QWidget()
        content.setObjectName("mainContent")
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # 左侧标签栏
        self._sidebar = Sidebar()
        content_layout.addWidget(self._sidebar)

        # 右侧内容区（页面栈 + 状态栏）
        right_side = QWidget()
        right_layout = QVBoxLayout(right_side)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._stack = QStackedWidget()
        right_layout.addWidget(self._stack, 1)

        self._status_bar = StatusBar()
        right_layout.addWidget(self._status_bar)

        content_layout.addWidget(right_side, 1)
        main_layout.addWidget(content, 1)

    def _init_pages(self):
        for page_id, page_cls in self.PAGE_CLASSES.items():
            page = page_cls()
            self._pages[page_id] = page
            self._stack.addWidget(page)

    def _connect_signals(self):
        self._sidebar.page_changed.connect(self._switch_page)

        # 标题栏信号
        self._title_bar.minimize_clicked.connect(self.showMinimized)
        self._title_bar.maximize_clicked.connect(self._toggle_maximized)
        self._title_bar.close_clicked.connect(self.close)

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

    # ─── 启动后初始化 ──────────────────────────

    def _on_initialized(self):
        """GUI 初始化完成后调用"""
        pass

    # ─── 窗口管理 ──────────────────────────────

    def _toggle_maximized(self):
        """切换最大化/还原状态"""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._title_bar.set_maximized_state(self.isMaximized())

    def changeEvent(self, event):
        """窗口状态变化时同步标题栏（如 Alt+F4 或系统菜单）"""
        if event.type() == event.Type.WindowStateChange:
            self._title_bar.set_maximized_state(self.isMaximized())
        super().changeEvent(event)

    def resizeEvent(self, event):
        """窗口尺寸变化后更新标题栏最大化状态（拖拽还原时）"""
        super().resizeEvent(event)
        self._title_bar.set_maximized_state(self.isMaximized())

    def mousePressEvent(self, event):
        """边缘 resize：检测点击位置是否在边缘区域内"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._resize_edge = self._get_resize_edge(event)
            if self._resize_edge:
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """边缘 resize：拖拽时调整窗口大小"""
        if event.buttons() & Qt.MouseButton.LeftButton and self._resize_edge:
            self._do_resize(event)
            event.accept()
            return
        # 无按键按下时更新光标形状
        edge = self._get_resize_edge(event)
        if edge:
            cursor_map = {
                Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
                Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
                Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
                Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
                Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
                Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
                Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
                Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
            }
            self.setCursor(cursor_map.get(edge, Qt.CursorShape.ArrowCursor))
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """释放鼠标时清除 resize 状态"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._resize_edge = 0
        super().mouseReleaseEvent(event)

    def _get_resize_edge(self, event):
        """判断鼠标位置在哪个窗口边缘"""
        if self.isMaximized() or self.isFullScreen():
            return 0
        x = event.position().x()
        y = event.position().y()
        w = self.width()
        h = self.height()
        edge = 0
        if x <= _RESIZE_MARGIN:
            edge |= Qt.Edge.LeftEdge
        if x >= w - _RESIZE_MARGIN:
            edge |= Qt.Edge.RightEdge
        if y <= _RESIZE_MARGIN:
            edge |= Qt.Edge.TopEdge
        if y >= h - _RESIZE_MARGIN:
            edge |= Qt.Edge.BottomEdge
        return edge

    def _do_resize(self, event):
        """根据鼠标位置调整窗口大小"""
        gx, gy = event.globalPosition().x(), event.globalPosition().y()
        rect = self.geometry()
        min_w, min_h = self.minimumWidth(), self.minimumHeight()
        max_w, max_h = self.maximumWidth(), self.maximumHeight()

        new_left, new_top, new_right, new_bottom = rect.getRect()
        new_left, new_top = rect.x(), rect.y()
        new_w, new_h = rect.width(), rect.height()

        if self._resize_edge & Qt.Edge.LeftEdge:
            new_left = gx
            new_w = rect.right() - gx
        elif self._resize_edge & Qt.Edge.RightEdge:
            new_w = gx - rect.x()

        if self._resize_edge & Qt.Edge.TopEdge:
            new_top = gy
            new_h = rect.bottom() - gy
        elif self._resize_edge & Qt.Edge.BottomEdge:
            new_h = gy - rect.y()

        # 强制最小/最大尺寸
        new_w = max(min_w, min(max_w, new_w))
        new_h = max(min_h, min(max_h, new_h))
        self.setGeometry(new_left, new_top, new_w, new_h)

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
        w = geometry.get("width", 1200)
        h = geometry.get("height", 800)

        # 升级旧配置（旧默认 900×680）到新 3:2 默认
        if w == 900 and h == 680:
            w, h = 1200, 800

        # 确保窗口尺寸在合理范围内
        w = max(900, min(1500, w))
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
        """窗口关闭时保存配置并清理子进程"""
        self._save_window_geometry()
        # 清理 Live2D 服务
        live2d_page = self._pages.get("live2d")
        if live2d_page and hasattr(live2d_page, '_stop_server'):
            live2d_page._stop_server()
        super().closeEvent(event)
