"""左侧标签栏 — 竖排图标按钮，点击切换页面"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QPushButton, QVBoxLayout, QWidget

from gui.core.config import AppConfig
from gui.resources.icons.codicon import codicon


class Sidebar(QWidget):
    """左侧标签栏 — 竖排图标按钮组，点击切换 QStackedWidget 页面。"""

    page_changed = Signal(str)

    TABS = [
        ("chat",     "chat",     "聊天"),
        ("live2d",   "live2d",   "Live2D"),
        ("node",     "node",     "节点管理"),
        ("mcp",      "mcp",      "MCP 管理"),
        ("settings", "settings", "设置"),
    ]

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

        for icon_name, page_id, tooltip in self.TABS:
            btn = self._create_button(icon_name, tooltip, colors)
            self._buttons[page_id] = btn
            self._group.addButton(btn)
            layout.addWidget(btn)

        layout.addStretch(1)

        self._group.buttonClicked.connect(self._on_clicked)

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
