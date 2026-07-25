"""
明亮版自定义标题栏（VSCode 风格，配色改为白底深色文字）

标题 + 窗口按钮 同行，支持拖动、最小化、最大化/还原、关闭
顶部 6px 保留给窗口 resize，不响应拖动
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

_RESIZE_MARGIN = 6  # 顶部边缘保留给窗口 resize，不响应拖动


class TitleBar(QWidget):
    """明亮版自定义标题栏"""

    minimize_clicked = Signal()
    maximize_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, parent=None, title="BNOS AI 伴侣", menubar=None):
        super().__init__(parent)
        self._parent_window = parent
        self._is_maximized = False
        self._drag_pos = None

        self.setFixedHeight(40)
        self.setObjectName("titleBar")
        self.setMouseTracking(True)  # 边缘 hover 时改变光标为 resize 样式

        self._init_ui(title, menubar)
        self._apply_styles()

    def _init_ui(self, title, menubar):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # 标题
        self.title_label = QLabel(title)
        self.title_label.setObjectName("titleBarTitle")
        self.title_label.setFixedHeight(40)
        layout.addWidget(self.title_label)

        # 菜单栏（可选）
        if menubar:
            menubar.setObjectName("titleBarMenu")
            menubar.setNativeMenuBar(False)
            menubar.setFixedHeight(40)
            layout.addWidget(menubar)

        layout.addStretch(1)

        # 最小化
        self.min_btn = QPushButton("─")
        self.min_btn.setObjectName("titleBarMinBtn")
        self.min_btn.setFixedSize(50, 40)
        self.min_btn.clicked.connect(self.minimize_clicked.emit)
        layout.addWidget(self.min_btn)

        # 最大化/还原
        self.max_btn = QPushButton("□")
        self.max_btn.setObjectName("titleBarMaxBtn")
        self.max_btn.setFixedSize(50, 40)
        self.max_btn.clicked.connect(self._on_max_clicked)
        layout.addWidget(self.max_btn)

        # 关闭
        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("titleBarCloseBtn")
        self.close_btn.setFixedSize(50, 40)
        self.close_btn.clicked.connect(self.close_clicked.emit)
        layout.addWidget(self.close_btn)

    def _apply_styles(self):
        self.setStyleSheet("""
            #titleBar {
                background-color: rgba(255, 255, 255, 245);
                border-bottom: 1px solid rgba(0, 0, 0, 12);
            }
            #titleBarTitle {
                color: #333;
                font-size: 16px;
                font-weight: bold;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                padding: 0px 12px 3px 12px;
            }
            #titleBar QPushButton {
                background-color: transparent;
                border: none;
                color: #555;
                font-size: 16px;
                font-family: 'Segoe UI', sans-serif;
            }
            #titleBar QPushButton:hover {
                background-color: rgba(0, 0, 0, 6%);
            }
            QPushButton#titleBarMaxBtn {
                font-size: 25px;
                padding: 0px 0px 6px 0px;
            }
            #titleBarCloseBtn:hover {
                background-color: rgba(232, 17, 35, 0.12) !important;
                color: #d32f2f;
            }
            #titleBarMenu {
                background-color: transparent;
                color: #333;
                font-size: 13px;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                padding: 0px;
                margin: 0px;
            }
            #titleBarMenu::item {
                padding: 10px 12px;
                background-color: transparent;
                border-radius: 4px;
            }
            #titleBarMenu::item:selected {
                background-color: #1a73e8;
                color: white;
            }
            QMenu {
                background-color: white;
                color: #333;
                border: 1px solid rgba(0, 0, 0, 15);
                padding: 4px 0px;
                font-size: 13px;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
            }
            QMenu::item {
                padding: 8px 32px 8px 16px;
            }
            QMenu::item:selected {
                background-color: #1a73e8;
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background-color: rgba(0, 0, 0, 12);
                margin: 4px 8px;
            }
        """)

    def _on_max_clicked(self):
        if self._is_maximized:
            self.max_btn.setText("□")
            self._is_maximized = False
        else:
            self.max_btn.setText("❐")
            self._is_maximized = True
        self.maximize_clicked.emit()

    def set_maximized_state(self, is_maximized):
        self._is_maximized = is_maximized
        self.max_btn.setText("❐" if is_maximized else "□")

    def set_title(self, title):
        self.title_label.setText(title)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # 顶部 6px 不响应拖动，留给主窗口 resize
            if event.position().y() < _RESIZE_MARGIN:
                event.ignore()
                return
            self._drag_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event):
        # 顶部边缘区域内不拖动，避免与 resize 冲突
        if event.position().y() < _RESIZE_MARGIN:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
            event.ignore()
            return
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            if self._parent_window:
                delta = event.globalPosition().toPoint() - self._drag_pos
                self._parent_window.move(self._parent_window.pos() + delta)
                self._drag_pos = event.globalPosition().toPoint()
            event.accept()
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_max_clicked()
            event.accept()
