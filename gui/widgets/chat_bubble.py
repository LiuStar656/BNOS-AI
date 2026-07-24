"""消息气泡组件 — 左右对齐，QQ/微信风格，动态尺寸"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSpacerItem, QWidget, QSizePolicy

from gui.core.config import AppConfig


class ChatBubble(QWidget):
    """消息气泡组件。

    用户气泡右对齐（绿底），AI 气泡左对齐（白底）。
    气泡宽度随文本内容自适应，最大宽度不超过 600px。

    Args:
        text: 消息文本。
        role: "user" 或 "ai"。
        parent: 父组件。
    """

    def __init__(self, text: str, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        self._text = text
        self._config = AppConfig()

        # 气泡宽度填满父容器，高度跟随内容
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # 水平布局：spacer + label 实现左右对齐
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 8, 24, 8)
        layout.setSpacing(0)

        # 文本标签，宽度跟随内容
        self._label = QLabel(text)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(600)
        # Maximum 策略：label 宽度只取内容所需，不扩展
        self._label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self._label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._apply_theme()

        if role == "user":
            # 用户气泡 → 右侧
            layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))
            layout.addWidget(self._label)
        else:
            # AI 气泡 → 左侧
            layout.addWidget(self._label)
            layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))

    def _apply_theme(self):
        """应用主题颜色到气泡"""
        colors = self._config.get_all_colors()
        if self.role == "user":
            self._label.setStyleSheet(f"""
                background-color: {colors['bubble_user_bg']};
                color: {colors['bubble_user_text']};
                padding: 12px 16px;
                border-radius: 16px;
                border-bottom-right-radius: 4px;
                font-size: 14px;
                line-height: 1.5;
            """)
        else:
            self._label.setStyleSheet(f"""
                background-color: {colors['bubble_ai_bg']};
                color: {colors['bubble_ai_text']};
                padding: 12px 16px;
                border-radius: 16px;
                border-bottom-left-radius: 4px;
                font-size: 14px;
                line-height: 1.5;
            """)

    def minimumSizeHint(self):
        """最小尺寸：只返回 label 的内容尺寸 + 边距，不扩展"""
        hint = self._label.sizeHint()
        return QSize(hint.width() + 48, hint.height() + 16)

    def set_text(self, text: str):
        self._text = text
        self._label.setText(text)
        self.updateGeometry()

    def append_text(self, text: str):
        self._text += text
        self._label.setText(self._text)
        self.updateGeometry()
