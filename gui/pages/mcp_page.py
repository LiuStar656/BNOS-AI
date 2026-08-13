"""MCP 管理页 — 占位视图"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class MCPPage(QWidget):
    """MCP 工具管理（待开发）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        label = QLabel("MCP 管理（待开发）")
        label.setStyleSheet("color: #999999; font-size: 16px;")
        layout.addWidget(label)
