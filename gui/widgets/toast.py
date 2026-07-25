"""Toast 通知组件 — 从 DyberPet 移植

屏幕角落弹窗通知，带淡入淡出动画、自动关闭、悬停保持。
纯 PySide6 实现，无额外依赖。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QAbstractAnimation, QPoint, QRect, QSize
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget, QSpacerItem,
)

from gui.core.config import AppConfig


class Toast(QFrame):
    """屏幕角落 Toast 通知。

    用法::

        Toast.info("消息已发送", timeout=3000)
        Toast.warning("网络连接失败", timeout=5000)

    支持四个角落定位、淡入淡出动画、鼠标悬停保持。
    """

    _instances: dict[str, "Toast"] = {}

    @classmethod
    def info(cls, message: str, timeout: int = 3000):
        """显示信息 Toast"""
        inst = cls(message, corner=Qt.BottomRightCorner, timeout=timeout)
        inst.show_toast()

    @classmethod
    def warning(cls, message: str, timeout: int = 4000):
        """显示警告 Toast"""
        inst = cls(message, corner=Qt.BottomRightCorner, timeout=timeout)
        inst.show_toast()

    @classmethod
    def error(cls, message: str, timeout: int = 5000):
        """显示错误 Toast"""
        inst = cls(message, corner=Qt.BottomRightCorner, timeout=timeout)
        inst.show_toast()

    def __init__(
        self,
        message: str,
        corner: Qt.Corner = Qt.BottomRightCorner,
        closable: bool = True,
        timeout: int = 3000,
        parent: QWidget | None = None,
    ):
        super().__init__(parent=parent)
        self._config = AppConfig()
        self._message = message
        self._corner = corner
        self._is_closable = closable
        self._timeout = timeout
        self._margin = 16
        self._close_type = "faded"

        # 定时器
        self._timer = QTimer(singleShot=True, timeout=self._hide)
        self._opacity_ani = QPropertyAnimation(self, b"windowOpacity")
        self._opacity_ani.setStartValue(0.0)
        self._opacity_ani.setEndValue(1.0)
        self._opacity_ani.setDuration(120)
        self._opacity_ani.finished.connect(self._check_closed)

        self._build_ui()

    def _build_ui(self):
        colors = self._config.get_all_colors()
        bg = colors["bg_primary"]
        fg = colors["text_primary"]
        border = colors["border_color"]

        # 内容标签
        self._label = QLabel(self._message)
        self._label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._label.setWordWrap(True)
        self._label.setFixedWidth(180)
        self._label.setStyleSheet(f"""
            QLabel {{
                border: 0px;
                font: 14px 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', sans-serif;
                color: {fg};
                background-color: transparent;
            }}
        """)

        # 关闭按钮
        self._close_btn = QPushButton("×")
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setVisible(self._is_closable)
        self._close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {fg};
                font-size: 16px;
                font-weight: bold;
                padding: 0px;
            }}
            QPushButton:hover {{
                color: #d32f2f;
            }}
        """)
        self._close_btn.clicked.connect(lambda: self._close_now("button"))

        # 布局
        container = QFrame()
        container.setStyleSheet(f"""
            QFrame {{
                border: 1px solid {border};
                border-radius: 8px;
                background: {bg};
            }}
        """)

        hbox = QHBoxLayout(container)
        hbox.setContentsMargins(14, 10, 14, 10)
        hbox.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        hbox.addWidget(self._label, 0, Qt.AlignVCenter | Qt.AlignLeft)
        spacer = QSpacerItem(10, 20, QSizePolicy.Expanding, QSizePolicy.Fixed)
        hbox.addItem(spacer)
        hbox.addWidget(self._close_btn, 0, Qt.AlignVCenter | Qt.AlignRight)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)

        self.setMinimumWidth(250)
        self.adjustSize()

        # 窗口属性
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.BypassWindowManagerHint
            | Qt.SubWindow
            | Qt.NoDropShadowWindowHint
        )

    def show_toast(self):
        """计算位置并显示 Toast"""
        screen = QApplication.primaryScreen()
        if not screen:
            return
        rect = screen.availableGeometry()
        geo = self.geometry()
        m = self._margin

        if self._corner == Qt.TopLeftCorner:
            geo.moveTopLeft(rect.topLeft() + QPoint(m, m))
        elif self._corner == Qt.TopRightCorner:
            geo.moveTopRight(rect.topRight() + QPoint(-m, m))
        elif self._corner == Qt.BottomRightCorner:
            geo.moveBottomRight(rect.bottomRight() + QPoint(-m, -m))
        else:
            geo.moveBottomLeft(rect.bottomLeft() + QPoint(m, -m))

        self.setGeometry(geo)
        self._timer.setInterval(self._timeout)
        self._timer.start()
        self.show()
        self._opacity_ani.start()

    def _hide(self):
        """开始淡出"""
        self._opacity_ani.setDirection(QAbstractAnimation.Backward)
        self._opacity_ani.setDuration(400)
        self._opacity_ani.start()

    def _check_closed(self):
        if self._opacity_ani.direction() == QAbstractAnimation.Backward:
            self._close_now("faded")

    def _close_now(self, close_type: str = "button"):
        self._close_type = close_type
        self.close()

    def closeEvent(self, event):
        super().closeEvent(event)
        self.deleteLater()

    def enterEvent(self, event):
        self._timer.stop()
        self._opacity_ani.stop()
        self.setWindowOpacity(1.0)

    def leaveEvent(self, event):
        self._timer.start()
