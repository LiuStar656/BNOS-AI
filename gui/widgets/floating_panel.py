"""
浮动面板基类 — 统一所有悬浮窗的样式、拖动和生命周期管理

子类通过 self.content_layout 和 self.hint_bar 添加内容。
自带：无边框、半透明白色背景、标题栏（可拖动）、最小化/关闭按钮。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class FloatingPanel(QDialog):
    """浮动面板基类"""

    closed = Signal()  # 关闭信号

    def __init__(self, parent=None, title="面板"):
        super().__init__(parent)
        self.parent_window = parent
        self.drag_position = None

        # 统一窗口标志
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._setup_frame(title)

    # ==================== 框架搭建 ====================

    def _setup_frame(self, title):
        """搭建外层框架：半透明容器 + 标题栏 + 内容区"""
        # 主布局（无边距，配合半透明背景）
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 半透明白色容器
        self._container = QWidget(self)
        self._container.setObjectName("fp_container")
        self._container.setStyleSheet(self._container_style())
        main_layout.addWidget(self._container)

        # 框架内布局
        self._frame_layout = QVBoxLayout(self._container)
        self._frame_layout.setContentsMargins(10, 8, 10, 8)
        self._frame_layout.setSpacing(6)

        # 标题栏
        self._title_label = QLabel(title)
        self._frame_layout.addLayout(self._create_title_bar())

        # 内容区（子类使用 self.content_layout 添加自己的内容）
        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(6)
        self._frame_layout.addLayout(self.content_layout, 1)

        # 底部提示栏（子类可选使用 self.hint(text) 设置）
        self._hint_label = QLabel("")
        self._hint_label.setStyleSheet("color: rgba(0, 0, 0, 40%); font-size: 9px; padding: 2px;")
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._frame_layout.addWidget(self._hint_label)

    def _container_style(self):
        """容器样式（子类可覆盖自定义颜色）"""
        return """
            QWidget#fp_container {
                background-color: rgba(255, 255, 255, 240);
                border-radius: 8px;
                border: 1px solid rgba(0, 0, 0, 15);
            }
        """

    def _create_title_bar(self):
        """创建标题栏：标题 + 最小化 + 关闭"""
        title_layout = QHBoxLayout()

        self._title_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self._title_label.setStyleSheet("color: #333;")
        title_layout.addWidget(self._title_label)
        title_layout.addStretch()

        # 最小化按钮
        minimize_btn = QLabel("-")
        minimize_btn.setStyleSheet("""
            QLabel {
                color: rgba(0, 0, 0, 50%);
                font-size: 16px;
                padding: 0px 5px;
            }
            QLabel:hover {
                color: #333;
                background-color: rgba(0, 0, 0, 8%);
                border-radius: 3px;
            }
        """)
        minimize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        minimize_btn.mousePressEvent = lambda e: self.showMinimized()
        title_layout.addWidget(minimize_btn)

        # 关闭按钮
        close_btn = QLabel("x")
        close_btn.setStyleSheet("""
            QLabel {
                color: rgba(0, 0, 0, 50%);
                font-size: 16px;
                padding: 0px 5px;
            }
            QLabel:hover {
                color: #d32f2f;
                background-color: rgba(232, 17, 35, 0.12);
                border-radius: 3px;
            }
        """)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.mousePressEvent = lambda e: self._on_close()
        title_layout.addWidget(close_btn)

        return title_layout

    # ==================== 公共工具 ====================

    def set_title(self, title: str):
        """动态设置标题文字"""
        self._title_label.setText(title)

    def hint(self, text: str):
        """设置底部提示文字"""
        self._hint_label.setText(text)

    # ==================== 鼠标拖动 ====================

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            self._on_drag_start()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.drag_position = None
            event.accept()
            self._on_drag_end()

    def _on_drag_start(self):
        """拖动开始回调（子类可覆盖）"""
        pass

    def _on_drag_end(self):
        """拖动结束回调（子类可覆盖）"""
        pass

    # ==================== 生命周期 ====================

    def _on_close(self):
        """关闭按钮回调 — 子类可覆盖添加清理逻辑"""
        self.close()

    def cleanup_polling_signals(self):
        """虚钩子: 子类可覆盖以清理 polling_manager 信号连接"""
        pass

    def closeEvent(self, event):
        self._on_close()
        self.closed.emit()
        self.cleanup_polling_signals()
        super().closeEvent(event)

    def event(self, event):
        """ESC 关闭窗口"""
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self._on_close()
            return True
        return super().event(event)

    def showEvent(self, event):
        """显示时自动激活窗口获取焦点"""
        super().showEvent(event)
        self.activateWindow()
        self.raise_()
