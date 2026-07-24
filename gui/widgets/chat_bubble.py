"""消息气泡组件 — 左右对齐，QQ/微信风格"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget


_USER_QSS = """
    background-color: #95ec69;
    color: #333333;
    padding: 10px 14px;
    border-radius: 12px;
    font-size: 14px;
"""

_AI_QSS = """
    background-color: #ffffff;
    color: #333333;
    padding: 10px 14px;
    border-radius: 12px;
    font-size: 14px;
"""


class ChatBubble(QWidget):
    """消息气泡组件。

    Args:
        text: 消息文本（支持 HTML）。
        role: "user" 或 "ai"。
        parent: 父组件。
    """

    def __init__(self, text: str, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        self._text = text

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)

        self._label = QLabel(text)
        self._label.setWordWrap(True)
        self._label.setMinimumWidth(60)
        self._label.setMaximumWidth(520)

        if role == "user":
            self._label.setStyleSheet(_USER_QSS)
            self._label.setAlignment(Qt.AlignmentFlag.AlignLeft)
            layout.addStretch(1)
            layout.addWidget(self._label)
        else:
            self._label.setStyleSheet(_AI_QSS)
            self._label.setAlignment(Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(self._label)
            layout.addStretch(1)

    def set_text(self, text: str):
        self._text = text
        self._label.setText(text)

    def append_text(self, text: str):
        self._text += text
        self._label.setText(self._text)
