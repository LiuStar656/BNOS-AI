"""Live2D 预览页 — 使用 QWebEngineView 嵌入 Live2D 渲染"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView


class Live2DPage(QWidget):
    """Live2D 模型预览区，通过 QWebEngineView 嵌入 Live2D 渲染页面。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Live2D 渲染页面路径（位于 node_js_live2d_face 节点目录内）
        live2d_dir = Path(__file__).resolve().parent.parent.parent / "nodes" / "node_js_live2d_face" / "live2d"
        index_path = live2d_dir / "index.html"

        self._web_view = QWebEngineView()
        self._web_view.setUrl(index_path.resolve().as_uri())

        layout.addWidget(self._web_view)

    def refresh(self):
        """重新加载 Live2D 页面（用于切换模型等场景）。"""
        self._web_view.reload()
