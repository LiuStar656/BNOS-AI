"""左侧标签栏 — 竖排图标按钮，点击切换页面"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QMenu, QPushButton, QVBoxLayout, QWidget

from gui.core.config import AppConfig
from gui.core.event_bus import event_bus
from gui.core.messages import THEME_CHANGED
from gui.core.ui_registry import ui_registry
from gui.resources.icons.codicon import codicon


class Sidebar(QWidget):
    """左侧标签栏 — 竖排图标按钮组，点击切换 QStackedWidget 页面。

    标签列表由 UiRegistry 插槽注册中心驱动（阶段3），不再硬编码。
    """

    page_changed = Signal(str)
    settings_clicked = Signal()    # 设置面板
    node_clicked = Signal()        # 节点管理页

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(56)
        self.setObjectName("sidebar")

        self._config = AppConfig()
        colors = self._config.get_all_colors()

        self.setStyleSheet(f"""
            #sidebar {{
                background-color: {colors['sidebar_bg']};
                border-right: 1px solid {colors['border_color']};
            }}
        """)

        self._buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        codicon.init()
        self._icon_font = codicon.get_font(20)

        for icon_name, page_id, tooltip in ui_registry.tabs():
            btn = self._create_button(icon_name, tooltip, colors)
            self._buttons[page_id] = btn
            self._group.addButton(btn)
            layout.addWidget(btn)

        layout.addStretch(1)

        # ─── 底部更多按钮（弹出菜单：设置 / 节点管理）──
        self._more_btn = QPushButton()
        self._more_btn.setToolTip("更多")
        self._more_btn.setFixedSize(48, 48)
        self._more_btn.setCheckable(False)
        self._more_btn.setFont(self._icon_font)
        self._more_btn.setText(codicon.get_char("settings"))
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        colors = self._config.get_all_colors()
        self._more_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {colors['sidebar_text']};
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: {colors['bg_chat']};
                color: {colors['text_secondary']};
            }}
        """)
        # 弹出菜单
        self._more_menu = QMenu(self)
        self._more_menu.setStyleSheet(f"""
            QMenu {{
                padding: 4px; border-radius: 6px;
                background: {colors['bg_secondary']};
                border: 1px solid {colors['border_color']};
            }}
            QMenu::item {{
                padding: 6px 24px; border-radius: 4px;
                font-size: 13px; color: {colors['text_primary']};
            }}
            QMenu::item:hover {{
                background: rgba(0,0,0,0.06);
            }}
        """)
        self._settings_action = self._more_menu.addAction("设置")
        self._node_action = self._more_menu.addAction("节点管理")
        self._settings_action.triggered.connect(self.settings_clicked.emit)
        self._node_action.triggered.connect(self.node_clicked.emit)

        self._more_btn.clicked.connect(self._show_more_menu)
        layout.addWidget(self._more_btn)

        self._group.buttonClicked.connect(self._on_clicked)

        # 阶段4：自查订阅主题变更消息（替代 MainWindow 直接调用）
        self._subscribe_messages()

    # ─── 消息订阅（阶段4） ──────────────────────

    def _subscribe_messages(self):
        """订阅关心的 UI 消息（幂等，防重复实例化重复订阅）"""
        if getattr(self, "_events_subscribed", False):
            return
        self._events_subscribed = True
        event_bus.subscribe(THEME_CHANGED, self._on_theme_changed_msg)

    def _on_theme_changed_msg(self, _data=None):
        self.refresh_theme()

    def _create_button(self, icon_name: str, tooltip: str, colors: dict) -> QPushButton:
        btn = QPushButton()
        btn.setToolTip(tooltip)
        btn.setFixedSize(48, 48)
        btn.setCheckable(True)
        btn.setFont(self._icon_font)
        btn.setText(codicon.get_char(icon_name))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {colors['sidebar_text']};
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: {colors['bg_chat']};
                color: {colors['text_secondary']};
            }}
            QPushButton:checked {{
                background-color: {colors['sidebar_active']};
                color: {colors['sidebar_active_text']};
            }}
        """)
        return btn

    def _on_clicked(self, btn: QPushButton):
        for page_id, b in self._buttons.items():
            if b is btn:
                self.page_changed.emit(page_id)
                return

    def _show_more_menu(self):
        """在按钮上方弹出更多菜单"""
        btn_rect = self._more_btn.rect()
        global_pos = self._more_btn.mapToGlobal(btn_rect.topLeft())
        self._more_menu.exec(global_pos)

    def set_active(self, page_id: str):
        btn = self._buttons.get(page_id)
        if btn:
            btn.setChecked(True)

    def refresh_theme(self):
        """主题颜色变更后刷新侧边栏样式"""
        colors = self._config.get_all_colors()
        self.setStyleSheet(f"""
            #sidebar {{
                background-color: {colors['sidebar_bg']};
                border-right: 1px solid {colors['border_color']};
            }}
        """)
        for page_id, btn in self._buttons.items():
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {colors['sidebar_text']};
                    border: none;
                    border-radius: 8px;
                }}
                QPushButton:hover {{
                    background-color: {colors['bg_chat']};
                    color: {colors['text_secondary']};
                }}
                QPushButton:checked {{
                    background-color: {colors['sidebar_active']};
                    color: {colors['sidebar_active_text']};
                }}
            """)
        # 刷新底部更多按钮
        if self._more_btn:
            self._more_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {colors['sidebar_text']};
                    border: none;
                    border-radius: 8px;
                }}
                QPushButton:hover {{
                    background-color: {colors['bg_chat']};
                    color: {colors['text_secondary']};
                }}
            """)
        # 刷新菜单样式
        if self._more_menu:
            self._more_menu.setStyleSheet(f"""
                QMenu {{
                    padding: 4px; border-radius: 6px;
                    background: {colors['bg_secondary']};
                    border: 1px solid {colors['border_color']};
                }}
                QMenu::item {{
                    padding: 6px 24px; border-radius: 4px;
                    font-size: 13px; color: {colors['text_primary']};
                }}
                QMenu::item:hover {{
                    background: rgba(0,0,0,0.06);
                }}
            """)
