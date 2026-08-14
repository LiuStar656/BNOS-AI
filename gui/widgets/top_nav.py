"""顶栏横排导航 — 页面标签水平排列（顶部布局实现）。

数据驱动 UI 布局动态调整方案（Phase 1）：
- nav_position=top 时的导航容器，与 SidebarNav 共享 NavView 协议
- 高度 / 外观 / 页面显隐顺序由 LayoutSpec 驱动
- 右侧固定「更多」入口（设置 / 节点管理），与左栏语义对齐
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton

from gui.core.layout_spec import LayoutSpec
from gui.resources.icons.codicon import codicon
from gui.widgets.sidebar import NavView


class TopNav(NavView):
    """顶栏横排导航 — 页面标签水平排列 + 右侧更多菜单入口。"""

    def __init__(self, spec: LayoutSpec | None = None, parent=None):
        super().__init__(spec, parent)
        height = spec.nav_height if spec else 48
        self.setFixedHeight(height)
        self.setObjectName("topNav")

        self._nav_mode = spec.nav_mode if spec else "icon"

        colors = self._config.get_all_colors()
        self.setStyleSheet(f"""
            #topNav {{
                background-color: {colors['sidebar_bg']};
                border-bottom: 1px solid {colors['border_color']};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        codicon.init()
        self._icon_font = codicon.get_font(18)

        for icon_name, page_id, title in self._page_items():
            btn = self._create_button(icon_name, title, colors)
            self._buttons[page_id] = btn
            self._group.addButton(btn)
            layout.addWidget(btn)

        layout.addStretch(1)

        # ─── 右侧更多按钮（弹出菜单：设置 / 节点管理）──
        self._more_btn = QPushButton()
        self._more_btn.setToolTip("更多")
        self._more_btn.setFixedSize(36, height - 8)
        self._more_btn.setCheckable(False)
        self._more_btn.setFont(self._icon_font)
        self._more_btn.setText(codicon.get_char("settings"))
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {colors['sidebar_text']};
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {colors['bg_chat']};
                color: {colors['text_secondary']};
            }}
        """)
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

        self._subscribe_messages()

    # ─── 按钮构建 ─────────────────────────────────

    def _create_button(self, icon_name: str, title: str, colors: dict) -> QPushButton:
        btn = QPushButton()
        btn.setToolTip(title)
        if self._nav_mode == "icon":
            btn.setFixedSize(36, self.height() - 8)
            btn.setFont(self._icon_font)
            btn.setText(codicon.get_char(icon_name))
        elif self._nav_mode == "icon_text":
            btn.setText(f"{codicon.get_char(icon_name)}  {title}")
            btn.setFont(self._icon_font)
            btn.setFixedHeight(self.height() - 8)
        else:  # text
            btn.setText(title)
            btn.setFixedHeight(self.height() - 8)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {colors['sidebar_text']};
                border: none;
                border-radius: 6px;
                padding: 0 12px;
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

    def _show_more_menu(self):
        btn_rect = self._more_btn.rect()
        global_pos = self._more_btn.mapToGlobal(btn_rect.bottomLeft())
        self._more_menu.exec(global_pos)

    def refresh_theme(self):
        """主题颜色变更后刷新顶栏样式"""
        colors = self._config.get_all_colors()
        self.setStyleSheet(f"""
            #topNav {{
                background-color: {colors['sidebar_bg']};
                border-bottom: 1px solid {colors['border_color']};
            }}
        """)
        for page_id, btn in self._buttons.items():
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {colors['sidebar_text']};
                    border: none;
                    border-radius: 6px;
                    padding: 0 12px;
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
        if self._more_btn:
            self._more_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {colors['sidebar_text']};
                    border: none;
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background-color: {colors['bg_chat']};
                    color: {colors['text_secondary']};
                }}
            """)
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
