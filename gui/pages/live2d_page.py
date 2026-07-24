"""Live2D 预览页 — 占位视图"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class Live2DPage(QWidget):
    """Live2D 模型预览区（占位）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        label = QLabel("Live2D 预览（待集成）")
        label.setStyleSheet("color: #999999; font-size: 16px;")
        layout.addWidget(label)
