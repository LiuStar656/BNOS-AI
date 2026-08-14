"""
颜色选择器弹出窗口 — 从 BNOS ColorPickerPopup 适配

替代系统 QColorDialog，继承 FloatingPanel 保持统一明亮主题。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.widgets.floating_panel import FloatingPanel
from gui.core.theme_engine import theme_engine
from gui.core.icon_registry import icons

# 预设色板（明亮主题适用）
_PRESET_COLORS = [
    "#ffffff", "#e0e0e0", "#bdbdbd", "#9e9e9e", "#757575", "#616161", "#424242", "#212121",
    "#ffebee", "#ffcdd2", "#ef9a9a", "#e57373", "#ef5350", "#f44336", "#e53935", "#d32f2f",
    "#fff3e0", "#ffe0b2", "#ffcc80", "#ffb74d", "#ffa726", "#ff9800", "#fb8c00", "#f57c00",
    "#fffde7", "#fff9c4", "#fff59d", "#fff176", "#ffee58", "#ffeb3b", "#fdd835", "#fbc02d",
    "#e8f5e9", "#c8e6c9", "#a5d6a7", "#81c784", "#66bb6a", "#4caf50", "#43a047", "#388e3c",
    "#e3f2fd", "#bbdefb", "#90caf9", "#64b5f6", "#42a5f5", "#2196f3", "#1e88e5", "#1976d2",
    "#f3e5f5", "#e1bee7", "#ce93d8", "#ba68c8", "#ab47bc", "#9c27b0", "#8e24aa", "#7b1fa2",
    "#eceff1", "#cfd8dc", "#b0bec5", "#90a4ae", "#78909c", "#607d8b", "#546e7a", "#455a64",
]


class ColorPickerPopup(FloatingPanel):
    """颜色选择器弹出窗口"""

    color_selected = Signal(QColor)

    def __init__(self, current_color: QColor, parent=None):
        super().__init__(parent, title="选择颜色")
        self._current = QColor(current_color)
        self._result: QColor | None = None

        # 由 _auto_resize 动态调整尺寸，不设固定尺寸
        self._setup_ui()

    def _setup_ui(self):
        """创建内容 widget 并通过 set_content_widget 注入到滚动区"""
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(8)
        layout.setContentsMargins(4, 4, 4, 4)

        # ─── 预览行 ───
        preview = QHBoxLayout()
        self._preview_old = QLabel()
        self._preview_old.setFixedSize(40, 22)
        self._preview_old.setStyleSheet(
            f"background-color: {self._current.name()}; border: 1px solid {theme_engine.get('border_color')}; border-radius: 3px;"
        )
        preview.addWidget(QLabel("当前:"))
        preview.addWidget(self._preview_old)
        preview.addWidget(QLabel(f" {icons.get('arrow')} "))
        self._preview_new = QLabel()
        self._preview_new.setFixedSize(40, 22)
        self._preview_new.setStyleSheet(
            f"background-color: {self._current.name()}; border: 1px solid {theme_engine.get('border_color')}; border-radius: 3px;"
        )
        preview.addWidget(self._preview_new)
        self._hex_input = QLineEdit(self._current.name())
        self._hex_input.setFixedWidth(80)
        self._hex_input.editingFinished.connect(self._on_hex_input)
        preview.addWidget(self._hex_input)
        preview.addStretch()
        layout.addLayout(preview)

        # ─── 色板网格 ───
        grid = QGridLayout()
        grid.setSpacing(3)
        for i, hex_color in enumerate(_PRESET_COLORS):
            swatch = self._make_swatch(hex_color)
            row, col = divmod(i, 8)
            grid.addWidget(swatch, row, col)
        layout.addLayout(grid)

        # ─── 按钮 ───
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(lambda: self.close())
        btn_row.addWidget(cancel_btn)
        ok_btn = QPushButton("确定")
        ok_btn.setObjectName("okBtn")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        self.set_content_widget(content)

    def _make_swatch(self, hex_color: str) -> QLabel:
        swatch = QLabel()
        swatch.setFixedSize(26, 26)
        swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        swatch.setToolTip(hex_color)
        swatch.setStyleSheet(f"""
            QLabel {{
                background-color: {hex_color};
                border: 1px solid {theme_engine.get('border_color')};
                border-radius: 2px;
            }}
            QLabel:hover {{
                border: 2px solid {theme_engine.get('accent_color')};
            }}
        """)
        swatch.mousePressEvent = lambda e, c=hex_color: self._select_color(c)
        return swatch

    def _select_color(self, hex_color: str):
        self._current = QColor(hex_color)
        self._update_preview()

    def _update_preview(self):
        color = self._current
        self._preview_new.setStyleSheet(
            f"background-color: {color.name()}; border: 1px solid {theme_engine.get('border_color')}; border-radius: 3px;"
        )
        self._hex_input.setText(color.name())

    def _on_hex_input(self):
        text = self._hex_input.text().strip()
        c = QColor(text)
        if c.isValid():
            self._current = c
            self._update_preview()

    def _on_ok(self):
        self._result = QColor(self._current)
        self.color_selected.emit(self._result)
        self.accept()

    @staticmethod
    def get_color(current: QColor, parent=None) -> QColor | None:
        """静态方法：弹出颜色选择器，返回选中的颜色或 None"""
        popup = ColorPickerPopup(current, parent=parent)
        if popup.exec():
            return popup._result
        return None
