"""设置页 — 模型选择、API Key 配置等"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class SettingsPage(QWidget):
    """设置页 — 模型选择、API Key 配置等（待完善）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        label = QLabel("设置（待开发）")
        label.setStyleSheet("color: #999999; font-size: 16px;")
        layout.addWidget(label)
