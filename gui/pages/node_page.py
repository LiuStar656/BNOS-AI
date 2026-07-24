"""节点管理页 — 节点状态仪表盘（从 gui_status.json 读取）"""

from __future__ import annotations

import json
import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.core.state import AppState

GUI_STATUS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "nodes", "shared", "gui_status.json",
)


class NodePage(QWidget):
    """节点管理仪表盘 — 显示各节点状态。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = AppState()
        self._last_mtime: float = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["节点", "状态", "详情"])
        self._tree.setAlternatingRowColors(True)
        self._tree.header().setStretchLastSection(True)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        layout.addWidget(self._tree)

        # 轮询状态
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_status)
        self._timer.start(2000)

    def _poll_status(self):
        if not os.path.exists(GUI_STATUS_PATH):
            return
        try:
            mtime = os.path.getmtime(GUI_STATUS_PATH)
        except OSError:
            return
        if mtime <= self._last_mtime:
            return
        self._last_mtime = mtime
        try:
            with open(GUI_STATUS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        self._update_tree(data)

    def _update_tree(self, data: dict):
        self._tree.clear()
        nodes = data.get("nodes", {})
        for node_name, node_status in nodes.items():
            init_status = node_status.get("init_status", "unknown")
            detail = node_status.get("detail", "")
            item = QTreeWidgetItem([node_name, init_status, detail])
            components = node_status.get("components", {})
            for comp_name, comp_status in components.items():
                child = QTreeWidgetItem([
                    f"  {comp_name}",
                    comp_status.get("status", ""),
                    comp_status.get("detail", ""),
                ])
                item.addChild(child)
            self._tree.addTopLevelItem(item)
        self._tree.expandAll()
