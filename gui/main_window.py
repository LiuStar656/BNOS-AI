"""主窗口 — 自定义标题栏 + 数据驱动导航容器 + 右侧 QStackedWidget + 底部状态栏"""

from __future__ import annotations

import ctypes

from PySide6.QtCore import Qt, QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, QTimer
from PySide6.QtGui import QMouseEvent, QCursor
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from gui.core.event_bus import event_bus
from gui.core.message_manager import MessageManager
from gui.core.config import AppConfig
from gui.core.state import AppState
from gui.core.theme_engine import theme_engine
from gui.core.ui_registry import ui_registry
from gui.core.messages import (
    PAGE_ACTIVATED,
    THEME_CHANGED,
    DATA_REFRESH_REQUESTED,
    NAVIGATE_REQUEST,
    LAYOUT_REQUEST,
)
from gui.core.layout_engine import layout_engine
from gui.core.layout_registry import layout_registry
from gui.core.layout_spec import LayoutSpec
from gui.core.tool_bridge import tool_bridge
from gui.dialogs.archive_panel import ArchivePanel
from gui.pages.settings_panel import SettingsPanel
from gui.pages.node_page import NodePage
from gui.widgets.floating_panel import FloatingPanel
from gui.widgets.logseq_writer import LogseqWriter
from gui.widgets.status_bar import StatusBar
from gui.widgets.title_bar import TitleBar

_RESIZE_MARGIN = 6  # 窗口边缘 resize 区域宽度


class MainWindow(QMainWindow):
    """主窗口 — 自定义标题栏 + 数据驱动导航容器 + 右侧 QStackedWidget + 底部状态栏。

    页面装配由 UiRegistry 插槽注册中心驱动（阶段3）；导航容器由 LayoutEngine 依
    LayoutSpec 数据驱动（Phase 0-1，可切换/回退），不再硬编码在内容区布局。
    """

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
        self.setAutoFillBackground(False)
        # 全局样式由 ThemeEngine 统一生成（换肤即时生效）
        theme_engine.apply_global(self)

        self._config = AppConfig()
        self._state = AppState()
        self._message_manager: MessageManager | None = None
        self._floating_panel: FloatingPanel | None = None
        self._settings_content: SettingsPanel | None = None
        self._node_content: NodePage | None = None
        self._archive_content: ArchivePanel | None = None
        self._right_side: QWidget | None = None
        self._pages: dict[str, QWidget] = {}
        self._anim_group: QParallelAnimationGroup | None = None  # 页面滑动动画组
        self._resize_edge = 0  # 当前鼠标所在边缘
        self._nav_view = None  # 当前导航容器（NavView 接口：SidebarNav/TopNav）
        self._layout_spec: LayoutSpec = LayoutSpec.default()  # 当前生效布局 spec

        self._init_central()
        self._init_pages()
        self._connect_signals()

        # 恢复窗口位置和尺寸
        self._restore_window_geometry()

        # 默认显示聊天页（DeepSeek 风格：打开即输入框，不进入独立首页）
        self._nav_view.set_active("chat")
        self._stack.setCurrentWidget(self._pages["chat"])

        # 启动后发送 init_check
        from PySide6.QtCore import QTimer
        QTimer.singleShot(500, self._on_initialized)

        # 延迟初始化浮动面板
        self._init_floating_panel()

    def _init_central(self):
        # 外层容器（圆角背景，颜色由全局 QSS #centralWidget 接管）
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        # 整体布局：竖排 标题栏 + 内容区
        self._main_layout = QVBoxLayout(central)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        # 顶部自定义标题栏
        self._title_bar = TitleBar(self, "BNOS AI 伴侣")
        self._main_layout.addWidget(self._title_bar)

        # 内容区（导航容器 + 页面栈 + 状态栏）
        self._content = QWidget()
        self._content.setObjectName("mainContent")
        self._content_layout = QHBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)

        # 右侧内容区（页面栈 + 状态栏）
        self._right_side = QWidget()
        right_layout = QVBoxLayout(self._right_side)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._stack = QStackedWidget()
        right_layout.addWidget(self._stack, 1)

        # 暂时隐藏状态栏，专注聊天体验
        # self._status_bar = StatusBar()
        # right_layout.addWidget(self._status_bar)

        self._content_layout.addWidget(self._right_side, 1)
        self._main_layout.addWidget(self._content, 1)

        # 数据驱动布局（Phase 0-1）：导航容器由 LayoutEngine 依 LayoutSpec 创建。
        # 启动时恢复配置中的布局（缺省 default 左栏），行为与旧硬编码一致。
        layout_engine.bind(self)
        self._layout_spec = (
            layout_registry.get_spec(self._config.get("layout_id", "default"))
            or LayoutSpec.default()
        )
        layout_engine.apply(self._layout_spec, self)

    def _init_floating_panel(self):
        """初始化浮动面板（延迟创建，避免 init 时 right_side 尺寸为 0）"""
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._do_init_floating_panel)

    def _do_init_floating_panel(self):
        if self._floating_panel is not None:
            return
        try:
            self._floating_panel = FloatingPanel(self)  # 传入 MainWindow 仅用于定位
            # 创建内容面板实例
            self._settings_content = SettingsPanel()
            self._node_content = NodePage()
            self._archive_content = ArchivePanel(
                self._get_conversation_messages()
            )
            self._archive_content.restored.connect(self._on_archive_restored)
            # 关闭浮动面板时暂停节点定时器
            self._floating_panel.closed.connect(self._on_panel_closed)
            # 默认显示设置面板
            self._floating_panel.set_content_widget(self._settings_content)
        except Exception as e:
            import traceback
            print(f"[MainWindow] 初始化浮动面板失败: {e}")
            traceback.print_exc()

    def _get_conversation_messages(self) -> dict:
        chat = self._pages.get("chat")
        if chat and hasattr(chat, "_conversation_messages"):
            return chat._conversation_messages
        return {}

    def _on_panel_closed(self):
        """浮动面板关闭时暂停节点定时器"""
        self._stop_node_timer()

    def _stop_node_timer(self):
        """停止节点管理页面的定时器"""
        if self._node_content and hasattr(self._node_content, "_stale_timer"):
            self._node_content._stale_timer.stop()

    def _init_pages(self):
        for slot in ui_registry.page_slots():
            page_id = ui_registry.meta(slot).get("page_id", slot.removeprefix("page."))
            page = ui_registry.resolve(slot)
            self._pages[page_id] = page
            self._stack.addWidget(page)

    def _connect_signals(self):
        self._nav_view.page_changed.connect(self._switch_page)
        self._nav_view.settings_clicked.connect(self._on_open_settings)
        self._nav_view.node_clicked.connect(self._on_open_node)
        # 归档信号在 ConversationList 上（位于 ChatPage 内部）
        chat_page = self._pages.get("chat")
        if chat_page and hasattr(chat_page, "_conv_list"):
            chat_page._conv_list.show_archive_requested.connect(self._on_open_archive)

        # 标题栏信号
        self._title_bar.minimize_clicked.connect(self.showMinimized)
        self._title_bar.maximize_clicked.connect(self._toggle_maximized)
        self._title_bar.close_clicked.connect(self.close)

        # 创建 MessageManager 并连接信号
        self._message_manager = MessageManager(self)
        self._message_manager.error_occurred.connect(self._on_error_occurred)

        # 初始化 LogseqWriter（自动轮询并写入 Logseq 知识条目）
        self._logseq_writer = LogseqWriter(self)

        # 将 MessageManager 传给 ChatPage
        if "chat" in self._pages and hasattr(self._pages["chat"], "set_message_manager"):
            self._pages["chat"].set_message_manager(self._message_manager)

        # 监听状态变化
        self._state.on_change("engine_status", self._on_engine_status_changed)
        self._state.on_change("current_model", self._on_current_model_changed)
        self._state.on_change("nodes", self._on_nodes_changed)

        # 监听主题变更
        event_bus.subscribe(THEME_CHANGED, self._on_theme_changed)

        # 阶段7：AI 工具消息（导航 / 数据刷新请求）
        event_bus.subscribe(NAVIGATE_REQUEST, self._on_navigate_request)
        event_bus.subscribe(DATA_REFRESH_REQUESTED, self._on_refresh_requested)

        # 数据驱动布局（Phase 1）：布局应用请求入口（设置面板 / AI 工具）
        event_bus.subscribe(LAYOUT_REQUEST, self._on_layout_request)

        # 阶段7：启动文件工具桥（AI 写请求文件 → GUI 执行 → 回结果）
        tool_bridge.start()

    # ─── 布局请求（数据驱动 UI 布局动态调整） ────

    def _on_layout_request(self, layout_id=None):
        """布局应用请求：查注册中心 spec → 应用（不重启，页面实例复用，可回退）"""
        if not layout_id:
            return
        spec = layout_registry.get_spec(layout_id)
        if spec is None:
            return
        layout_engine.apply(spec, self)

    # ─── AI 工具消息（阶段7） ──────────────────

    def _on_navigate_request(self, page_id=None):
        """AI 导航请求：切换到指定页面"""
        if page_id:
            self._switch_page(page_id)

    def _on_refresh_requested(self, page_id=None):
        """AI 数据刷新请求：广播页面激活消息，页面自查刷新"""
        if page_id:
            self._after_page_switch(page_id, self._pages.get(page_id))
            return
        current = self._stack.currentWidget()
        for pid, wid in self._pages.items():
            if wid is current:
                self._after_page_switch(pid, current)
                break

    # ─── 主题刷新 ──────────────────────────────

    def _on_theme_changed(self, _data=None):
        """主题颜色在设置页被修改时触发刷新

        各组件已自查订阅 THEME_CHANGED 刷新自身样式（阶段4），
        MainWindow 只负责刷新全局 QSS + 应用级调色板。
        """
        theme_engine.apply_global(self)
        from PySide6.QtWidgets import QApplication
        theme_engine.apply_palette(QApplication.instance())

    # ─── 启动后初始化 ──────────────────────────

    def _on_initialized(self):
        """GUI 初始化完成后调用"""
        self._check_first_start_personality()

    def _check_first_start_personality(self):
        """首次启动（无性格种子）时弹出性格选择界面"""
        try:
            from gui.dialogs.personality_dialog import (
                PersonalityDialog,
                has_personality,
            )
            if has_personality():
                return
            dlg = PersonalityDialog(self)
            dlg.center_on_parent()
            dlg.exec()
        except Exception:
            import traceback
            print("[MainWindow] 性格选择界面弹出失败:", traceback.format_exc())

    def show_personality_dialog(self):
        """重新弹出性格选择界面（人格格式化后调用）"""
        try:
            from gui.dialogs.personality_dialog import PersonalityDialog
            dlg = PersonalityDialog(self)
            dlg.center_on_parent()
            dlg.exec()
        except Exception:
            import traceback
            print("[MainWindow] 性格选择界面弹出失败:", traceback.format_exc())

    def reset_chat_after_format(self):
        """人格格式化后清空聊天 UI（气泡 + 对话列表 + 历史文件）"""
        chat = self._pages.get("chat")
        if chat is None:
            return
        try:
            # 1. 清除消息气泡
            if hasattr(chat, "clear_messages"):
                chat.clear_messages()
            # 2. 清空内存中的对话消息缓存
            if hasattr(chat, "_conversation_messages"):
                chat._conversation_messages.clear()
            # 3. 重置对话列表为默认对话
            st = self._state
            st.conversations = []
            st.current_conversation_id = "default"
            if hasattr(chat, "_conv_list"):
                chat._conv_list._rebuild_list()
            # 4. 清空当前输入框（若有）
            if hasattr(chat, "_chat_input"):
                chat._chat_input.clear()
            # 5. 持久化空历史（conversation_history.json 已由节点删除，重写一份空的）
            if hasattr(chat, "_save_history"):
                chat._save_history()
        except Exception:
            import traceback
            print("[MainWindow] 格式化后重置聊天 UI 失败:", traceback.format_exc())

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

    # ─── Windows 原生 resize（FramelessWindowHint 时必需） ──

    def nativeEvent(self, eventType, message):
        """Windows WM_NCHITTEST 响应 — 让系统正确处理无边框窗口的边缘缩放"""
        if self.isMaximized() or self.isFullScreen():
            return False, 0
        if eventType != b"windows_generic_MSG":
            return False, 0

        try:
            # 仅处理 WM_NCHITTEST (0x0084)
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message != 0x0084:
                return False, 0

            cursor_pos = QCursor.pos()
            x, y = cursor_pos.x(), cursor_pos.y()
            geo = self.geometry()
            border = _RESIZE_MARGIN

            left   = x < geo.x() + border
            right  = x >= geo.x() + geo.width() - border
            top    = y < geo.y() + border
            bottom = y >= geo.y() + geo.height() - border

            # 返回 Windows HT* 常量
            if top and left:       ht = 13  # HTTOPLEFT
            elif top and right:    ht = 14  # HTTOPRIGHT
            elif bottom and left:  ht = 16  # HTBOTTOMLEFT
            elif bottom and right: ht = 17  # HTBOTTOMRIGHT
            elif top:              ht = 12  # HTTOP
            elif bottom:           ht = 15  # HTBOTTOM
            elif left:             ht = 10  # HTLEFT
            elif right:            ht = 11  # HTRIGHT
            else:
                return False, 0

            return True, ctypes.c_longlong(ht).value
        except Exception:
            return False, 0

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
        """引擎状态变化（状态栏已隐藏，暂不处理）"""
        pass

    def _on_current_model_changed(self, model: str):
        """当前模型变化（状态栏已隐藏，暂不处理）"""
        pass

    def _on_nodes_changed(self, nodes: dict):
        """节点状态变化（状态栏已隐藏，暂不处理）"""
        pass

    def _on_open_settings(self):
        """打开设置浮动面板"""
        self._stop_node_timer()
        self._ensure_floating_panel()
        self._floating_panel.set_title("设置")
        self._floating_panel.set_content_widget(self._settings_content)
        self._floating_panel.show()

    def _on_open_node(self):
        """打开节点管理浮动面板"""
        self._ensure_floating_panel()
        self._floating_panel.set_title("节点管理")
        self._floating_panel.set_content_widget(self._node_content)
        # 启动节点定时器
        if hasattr(self._node_content, "_stale_timer"):
            self._node_content._stale_timer.start(2000)
        # 同步一次 UI
        if hasattr(self._node_content, "_sync_ui"):
            self._node_content._sync_ui()
        self._floating_panel.show()

    def _on_open_archive(self):
        """打开归档浮动面板"""
        self._stop_node_timer()
        self._ensure_floating_panel()
        self._floating_panel.set_title("归档管理")
        # 清理旧面板实例，防止内存泄漏
        if self._archive_content is not None:
            try:
                self._archive_content.deleteLater()
            except RuntimeError:
                pass
        # 刷新归档面板数据
        self._archive_content = ArchivePanel(
            self._get_conversation_messages()
        )
        self._archive_content.restored.connect(self._on_archive_restored)
        self._floating_panel.set_content_widget(self._archive_content)
        self._floating_panel.show()

    def _on_archive_restored(self, conv_id: str):
        """归档对话被恢复 → 切换对话并保存"""
        self._floating_panel.hide()
        self._state.current_conversation_id = conv_id
        self._nav_view.set_active("chat")
        self._stack.setCurrentWidget(self._pages["chat"])
        chat = self._pages.get("chat")
        if chat and hasattr(chat, "_on_conversation_changed"):
            chat._on_conversation_changed(conv_id)

    def _ensure_floating_panel(self):
        """确保浮动面板已初始化"""
        if self._floating_panel is not None:
            return
        self._do_init_floating_panel()

    def _switch_page(self, page_id: str):
        """切换页面 — 带滑动动画"""
        target = self._pages.get(page_id)
        if not target or target == self._stack.currentWidget():
            return

        # 正在动画中 → 先取消旧动画，再直接跳转
        if self._anim_group is not None:
            self._cancel_animation()
            self._stack.setCurrentWidget(target)
            self._after_page_switch(page_id, target)
            return

        # 计算滑动方向（1=左滑，-1=右滑）— 按当前布局的页面视图顺序（LayoutSpec 视图优先）
        page_ids = self._layout_spec.page_filter() or ui_registry.page_ids()
        direction = 1
        current_widget = self._stack.currentWidget()
        for pid, wid in self._pages.items():
            if wid is current_widget:
                current_idx = page_ids.index(pid)
                target_idx = page_ids.index(page_id)
                direction = 1 if target_idx > current_idx else -1
                break

        self._slide_animation(target, direction)

        self._after_page_switch(page_id, target)

    def _after_page_switch(self, page_id: str, target):
        """页面切换完成后的统一处理

        各页面已自查订阅 PAGE_ACTIVATED 刷新自身数据（阶段4），
        MainWindow 只负责广播页面激活消息。
        """
        event_bus.publish(PAGE_ACTIVATED, page_id)

    def _cancel_animation(self):
        """取消正在播放的动画，清理覆盖层"""
        if self._anim_group is None:
            return
        try:
            self._anim_group.stop()
            # 断开所有 finished 连接
            try:
                self._anim_group.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
        except RuntimeError:
            pass
        # 找到并删除 overlay（通过遍历子控件查找覆盖层 QWidget）
        for child in self._stack.findChildren(QWidget, "", Qt.FindChildOption.FindDirectChildrenOnly):
            if child.metaObject().className() == "QWidget" and child is not self._stack.currentWidget():
                try:
                    child.deleteLater()
                except RuntimeError:
                    pass
        self._anim_group = None

    def _slide_animation(self, target_page: QWidget, direction: int):
        """执行页面滑动动画（截图覆盖层方式）"""
        current_widget = self._stack.currentWidget()
        stack_size = self._stack.size()
        w = max(stack_size.width(), 1)
        h = max(stack_size.height(), 1)

        # 1) 截图当前页面 + 目标页面（关闭栈更新避免闪烁）
        self._stack.setUpdatesEnabled(False)
        current_pixmap = current_widget.grab()
        self._stack.setCurrentWidget(target_page)
        # 强制渲染确保截图完整
        QApplication.processEvents()
        target_pixmap = target_page.grab()
        self._stack.setCurrentWidget(current_widget)
        self._stack.setUpdatesEnabled(True)

        # 2) 创建动画覆盖层（作为 QStackedWidget 的子控件，自动覆盖）
        overlay = QWidget(self._stack)
        overlay.setGeometry(0, 0, w, h)
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        overlay.show()
        overlay.raise_()

        # 旧页标签（当前位置）
        old_label = QLabel(overlay)
        old_label.setPixmap(current_pixmap)
        old_label.setGeometry(0, 0, w, h)

        # 新页标签（从 off-screen 滑入）
        new_label = QLabel(overlay)
        new_label.setPixmap(target_pixmap)
        new_label.setGeometry(direction * w, 0, w, h)

        # 3) 并行动画组
        self._anim_group = QParallelAnimationGroup(self)

        # 旧页滑出
        a1 = QPropertyAnimation(old_label, b"pos")
        a1.setDuration(280)
        a1.setStartValue(QPoint(0, 0))
        a1.setEndValue(QPoint(-direction * w, 0))
        a1.setEasingCurve(QEasingCurve.OutCubic)

        # 新页滑入
        a2 = QPropertyAnimation(new_label, b"pos")
        a2.setDuration(280)
        a2.setStartValue(QPoint(direction * w, 0))
        a2.setEndValue(QPoint(0, 0))
        a2.setEasingCurve(QEasingCurve.OutCubic)

        self._anim_group.addAnimation(a1)
        self._anim_group.addAnimation(a2)
        self._anim_group.finished.connect(lambda: self._finish_slide(target_page, overlay))
        self._anim_group.start()

    def _finish_slide(self, target_page: QWidget, overlay: QWidget):
        """滑动动画完成 — 切换到实际页面 + 清理覆盖层"""
        self._stack.setCurrentWidget(target_page)
        overlay.deleteLater()
        self._anim_group = None

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
        # 停止引擎和所有节点进程
        try:
            from gui.main import _stop_engine
            _stop_engine()
        except Exception:
            pass
        super().closeEvent(event)
