"""浮动面板基类 — 统一所有悬浮窗的样式、拖动和生命周期管理

参考 BNOS 主仓库的实现方式：
  QDialog + Tool | FramelessWindowHint + WA_TranslucentBackground + 半透明容器
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.core.config import AppConfig


class FloatingPanel(QDialog):
    """浮动面板基类 — 独立悬浮窗口，不嵌入 GUI 内部。

    子类通过 self.content_layout 或 set_content_widget 添加内容。
    自带：无边框、半透明背景、标题栏（可拖动）、关闭按钮。
    """

    closed = Signal()  # 面板被关闭时发出

    def __init__(self, parent_window=None, title="悬浮面板"):
        """浮动面板基类。
        
        parent_window: 用于定位的面板（居中显示），不作为 Qt 父窗口，
                       避免与主窗口的 WA_TranslucentBackground 冲突。
        """
        super().__init__()
        self.parent_window = parent_window
        self.drag_position = None
        self._config = AppConfig()
        self._colors = self._config.get_all_colors()

        # 窗口标志：Tool = 不占任务栏、跟随父窗口；Frameless = 无系统标题栏
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._setup_frame(title)

    # ─── 颜色工具 ─────────────────────────────

    def _rgba(self, color_key: str, alpha: int) -> str:
        """将配置中的 hex 色值转为 rgba 字符串，用于半透明主题色"""
        c = QColor(self._colors.get(color_key, "#000000"))
        return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"

    def _setup_frame(self, title):
        """搭建外层框架：半透明容器 + 标题栏 + 内容区"""
        # 主布局（无边距，配合半透明背景）
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 半透明容器（颜色跟随主题）
        self._container = QWidget(self)
        self._container.setObjectName("fp_container")
        self._container.setStyleSheet(f"""
            QWidget#fp_container {{
                background: {self._rgba('bg_secondary', 220)};
                border-radius: 8px;
                border: 1px solid {self._rgba('border_color', 180)};
            }}
        """)
        main_layout.addWidget(self._container)

        # 框架内布局
        self._frame_layout = QVBoxLayout(self._container)
        self._frame_layout.setContentsMargins(10, 8, 10, 8)
        self._frame_layout.setSpacing(6)

        # 标题栏
        self._frame_layout.addLayout(self._create_title_bar(title))

        # 内容区分隔线
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {self._rgba('border_color', 180)};")
        self._frame_layout.addWidget(sep)

        # 内容滚动区（子类通过 set_content_widget 填充）
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("""
            QScrollArea {
                background: transparent; border: none;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
        """)
        self._frame_layout.addWidget(self._scroll, 1)

        # 公用 content_layout（兼容直接添加方式）
        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(6)

    def _create_title_bar(self, title):
        """创建标题栏：标题 + ← 返回 + 关闭"""
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(4, 0, 4, 0)

        self._title_label = QLabel(title)
        self._title_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self._title_label.setStyleSheet(f"color: {self._rgba('text_primary', 230)};")
        title_layout.addWidget(self._title_label)
        title_layout.addStretch()

        # 关闭按钮
        close_btn = QLabel("✕")
        close_btn.setStyleSheet(f"""
            QLabel {{
                color: {self._rgba('text_secondary', 180)};
                font-size: 14px;
                padding: 2px 6px;
                border-radius: 4px;
            }}
            QLabel:hover {{
                color: white;
                background-color: rgba(200, 60, 60, 150);
            }}
        """)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.mousePressEvent = lambda e: self._on_close()
        title_layout.addWidget(close_btn)

        return title_layout

    # ─── 公共 API ───────────────────────────────

    def set_title(self, title: str):
        self._title_label.setText(title)

    def set_content_widget(self, widget: QWidget):
        """设置主内容（放入滚动区），并自动调整面板尺寸"""
        # 先取出旧 widget 防止被 setWidget 删除（MainWindow 持有引用，需要复用）
        old = self._scroll.takeWidget()
        if old is not None and old is not widget:
            old.setParent(None)
            old.hide()
        # 旧 widget 已安全取出，setWidget 不会再删除它
        self._scroll.setWidget(widget)
        # 延迟到布局完成后调整尺寸
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._auto_resize)

    def _auto_resize(self):
        """根据内容自适应面板尺寸"""
        content = self._scroll.widget()
        if not content:
            return
        # 获取内容期望尺寸
        content_size = content.sizeHint()
        # 计算容器额外空间（标题栏 + 分隔线 + 内边距 + 边框）
        extra = 48 + 1 + 16 + 2  # header + separator + padding + border
        scroll_margin = self._scroll.contentsMargins()
        extra += scroll_margin.top() + scroll_margin.bottom()

        desired_w = max(content_size.width() + 40, 480)  # 最小 480px 宽
        desired_h = min(content_size.height() + extra, 700)  # 最大 700px 高
        # 不超过父窗口的 80%
        if self.parent_window and self.parent_window.isVisible():
            max_h = int(self.parent_window.height() * 0.80)
            max_w = int(self.parent_window.width() * 0.60)
            desired_w = min(desired_w, max_w)
            desired_h = min(desired_h, max_h)
        desired_h = max(desired_h, 300)  # 最小 300px 高

        self._container.setFixedSize(desired_w, desired_h)
        QDialog.setFixedSize(self, desired_w, desired_h)

    # 移除 setFixedSize 覆盖，使用 QDialog 原生方法

    # ─── 窗口管理 ──────────────────────────────

    def show(self):
        """显示并居中于父窗口"""
        if self.parent_window and self.parent_window.isVisible():
            mw_geo = self.parent_window.geometry()
            x = mw_geo.x() + (mw_geo.width() - self.width()) // 2
            y = mw_geo.y() + (mw_geo.height() - self.height()) // 2
            self.move(x, y)
        super().show()

    def showEvent(self, event):
        """显示时自动激活窗口获取焦点"""
        super().showEvent(event)
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)

    # ─── 鼠标拖动 ──────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = None
            event.accept()

    # ─── ESC 关闭 ─────────────────────────────

    def event(self, event):
        """ESC 关闭窗口"""
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self._on_close()
            return True
        return super().event(event)

    def _on_close(self):
        self.close()

    def refresh_theme(self):
        """主题变更刷新样式 — 使用主题色 + 半透明"""
        self._colors = self._config.get_all_colors()
        self._container.setStyleSheet(f"""
            QWidget#fp_container {{
                background: {self._rgba('bg_secondary', 220)};
                border-radius: 8px;
                border: 1px solid {self._rgba('border_color', 180)};
            }}
        """)
        self._title_label.setStyleSheet(f"color: {self._rgba('text_primary', 230)};")
