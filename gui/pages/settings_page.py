"""设置页 — 主题颜色自定义"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.core.config import AppConfig
from gui.core.event_bus import event_bus
from gui.widgets.color_picker import ColorPickerPopup


class SettingsPage(QWidget):
    """设置页 — 主题颜色自定义"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = AppConfig()

        self._init_ui()

        # 监听主题变更，刷新自身背景
        event_bus.subscribe("theme_changed", self._on_theme_changed)

    def _on_theme_changed(self, _data=None):
        colors = self._config.get_all_colors()
        p = self.palette()
        p.setColor(QPalette.Window, QColor(colors['bg_secondary']))
        self.setPalette(p)
        self.setAutoFillBackground(True)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        colors = AppConfig().get_all_colors()
        p = self.palette()
        p.setColor(QPalette.Window, QColor(colors['bg_secondary']))
        self.setPalette(p)
        self.setAutoFillBackground(True)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background-color: {colors['bg_secondary']}; border: none; }}
        """)

        content = QWidget()
        content.setObjectName("settings_content")
        content.setStyleSheet(f"""
            #settings_content {{ background-color: {colors['bg_secondary']}; }}
        """)
        self._form_layout = QVBoxLayout(content)
        self._form_layout.setSpacing(12)
        self._form_layout.setContentsMargins(24, 16, 24, 16)

        # ─── 强调色 ───
        accent_group = QGroupBox("强调色")
        accent_layout = QFormLayout(accent_group)
        self._accent_btn = self._color_button(self._config.get_theme("accent_color"), "accent_color")
        self._accent_btn.clicked.connect(lambda: self._pick_color("accent_color", self._accent_btn))
        accent_layout.addRow("主色调", self._accent_btn)

        accent_hover_btn = self._color_button(self._config.get_theme("accent_hover"), "accent_hover")
        accent_hover_btn.clicked.connect(lambda: self._pick_color("accent_hover", accent_hover_btn))
        accent_layout.addRow("悬停色", accent_hover_btn)
        self._form_layout.addWidget(accent_group)

        # ─── 聊天区域 ───
        chat_group = QGroupBox("聊天区域")
        chat_layout = QFormLayout(chat_group)
        self._chat_bg_btn = self._color_button(self._config.get_theme("bg_chat"), "bg_chat")
        self._chat_bg_btn.clicked.connect(lambda: self._pick_color("bg_chat", self._chat_bg_btn))
        chat_layout.addRow("聊天背景", self._chat_bg_btn)
        self._form_layout.addWidget(chat_group)

        # ─── 气泡颜色 ───
        bubble_group = QGroupBox("消息气泡")
        bubble_layout = QFormLayout(bubble_group)

        self._bubble_user_btn = self._color_button(self._config.get_theme("bubble_user_bg"), "bubble_user_bg")
        self._bubble_user_btn.clicked.connect(lambda: self._pick_color("bubble_user_bg", self._bubble_user_btn))
        bubble_layout.addRow("用户气泡", self._bubble_user_btn)

        bubble_user_text_btn = self._color_button(self._config.get_theme("bubble_user_text"), "bubble_user_text")
        bubble_user_text_btn.clicked.connect(lambda: self._pick_color("bubble_user_text", bubble_user_text_btn))
        bubble_layout.addRow("用户文字色", bubble_user_text_btn)

        self._bubble_ai_btn = self._color_button(self._config.get_theme("bubble_ai_bg"), "bubble_ai_bg")
        self._bubble_ai_btn.clicked.connect(lambda: self._pick_color("bubble_ai_bg", self._bubble_ai_btn))
        bubble_layout.addRow("AI 气泡", self._bubble_ai_btn)

        bubble_ai_text_btn = self._color_button(self._config.get_theme("bubble_ai_text"), "bubble_ai_text")
        bubble_ai_text_btn.clicked.connect(lambda: self._pick_color("bubble_ai_text", bubble_ai_text_btn))
        bubble_layout.addRow("AI 文字色", bubble_ai_text_btn)
        self._form_layout.addWidget(bubble_group)

        # ─── 侧边栏 ───
        sidebar_group = QGroupBox("侧边栏")
        sidebar_layout = QFormLayout(sidebar_group)

        self._sidebar_bg_btn = self._color_button(self._config.get_theme("sidebar_bg"), "sidebar_bg")
        self._sidebar_bg_btn.clicked.connect(lambda: self._pick_color("sidebar_bg", self._sidebar_bg_btn))
        sidebar_layout.addRow("背景色", self._sidebar_bg_btn)

        sidebar_active_btn = self._color_button(self._config.get_theme("sidebar_active"), "sidebar_active")
        sidebar_active_btn.clicked.connect(lambda: self._pick_color("sidebar_active", sidebar_active_btn))
        sidebar_layout.addRow("选中高亮", sidebar_active_btn)

        sidebar_active_text_btn = self._color_button(self._config.get_theme("sidebar_active_text"), "sidebar_active_text")
        sidebar_active_text_btn.clicked.connect(
            lambda: self._pick_color("sidebar_active_text", sidebar_active_text_btn)
        )
        sidebar_layout.addRow("选中文字色", sidebar_active_text_btn)
        self._form_layout.addWidget(sidebar_group)

        # ─── 操作按钮 ───
        btn_layout = QHBoxLayout()
        reset_btn = QPushButton("恢复默认")
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5; color: #333;
                border: 1px solid #d0d0d0; border-radius: 4px;
                padding: 8px 20px; font-size: 14px;
            }
            QPushButton:hover { background-color: #e8e8e8; }
        """)
        reset_btn.clicked.connect(self._reset_defaults)
        btn_layout.addStretch()
        btn_layout.addWidget(reset_btn)
        self._form_layout.addLayout(btn_layout)

        self._form_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll)

    # ─── 工具方法 ──────────────────────────────────

    def _color_button(self, hex_color: str, config_key: str = "") -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(32, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn._config_key = config_key
        btn.setStyleSheet(self._btn_style(hex_color))
        btn.setToolTip(hex_color)
        return btn

    def _pick_color(self, config_key: str, btn: QPushButton):
        current = QColor(self._config.get_theme(config_key, "#ffffff"))
        color = ColorPickerPopup.get_color(current, self)
        if color:
            hex_color = color.name()
            self._config.set_theme(config_key, hex_color)
            self._config.save()
            btn.setStyleSheet(self._btn_style(hex_color))
            btn.setToolTip(hex_color)
            # 广播主题变更事件，让主窗口立即刷新
            event_bus.publish("theme_changed")

    def _reset_defaults(self):
        defaults = AppConfig().config["theme"]
        self._config.apply_theme(defaults)
        for child in self.findChildren(QPushButton):
            key = getattr(child, "_config_key", "")
            if key and key in defaults:
                child.setStyleSheet(self._btn_style(defaults[key]))
                child.setToolTip(defaults[key])
        event_bus.publish("theme_changed")

    @staticmethod
    def _btn_style(hex_color: str) -> str:
        return f"""
            QPushButton {{
                background-color: {hex_color};
                border: 2px solid #d0d0d0;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                border-color: #1a73e8;
            }}
        """
