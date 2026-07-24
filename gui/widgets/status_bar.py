"""底部状态栏 — 全局状态显示"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class StatusBar(QWidget):
    """底部状态栏 — 显示引擎状态、当前模型、节点数量。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("status_bar")
        self.setFixedHeight(28)
        self.setStyleSheet("""
            #status_bar {
                background-color: #fafafa;
                border-top: 1px solid #e0e0e0;
            }
            QLabel {
                color: #999999;
                font-size: 11px;
                padding: 0 12px;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._engine_label = QLabel("引擎: 离线")
        self._model_label = QLabel("模型: -")
        self._node_label = QLabel("节点: 0/0")

        layout.addWidget(self._engine_label)
        layout.addWidget(self._model_label, 1, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._node_label)

    def update_engine(self, status: str):
        self._engine_label.setText(f"引擎: {status}")

    def update_model(self, name: str):
        self._model_label.setText(f"模型: {name or '-'}")

    def update_nodes(self, online: int, total: int):
        self._node_label.setText(f"节点: {online}/{total}")
