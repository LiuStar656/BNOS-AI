"""
BNOS AI Toast 通知系统 - 右上角自动消失的通知弹窗
适配自 BNOS 参考项目，改为明亮主题风格

采用"外层透明窗口 + 内层QFrame承载样式"的双层架构。
使用 setWindowOpacity 做淡入淡出动画。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

# ---------------- 全局配置 ----------------

_toast_config = {
    "info_color": "rgba(255, 255, 255, 235)",
    "success_color": "rgba(232, 245, 233, 235)",
    "warning_color": "rgba(255, 243, 224, 235)",
    "error_color": "rgba(255, 235, 238, 235)",
    "text_color": "#333333",
    "border_color": "#d0d0d0",
    "shadow_color": "rgba(0, 0, 0, 40)",
}


def set_toast_config(config):
    """设置Toast全局配置"""
    global _toast_config
    for key, value in config.items():
        if key.endswith("_color") and value.startswith("#"):
            qcolor = QColor(value)
            alpha = int(config.get("opacity", 0.92) * 255)
            _toast_config[key] = f"rgba({qcolor.red()}, {qcolor.green()}, {qcolor.blue()}, {alpha})"
        elif key == "opacity":
            pass
        else:
            _toast_config[key] = value


def get_toast_config():
    return _toast_config.copy()


# ---------------- Toast 组件 ----------------


class ToastNotification(QWidget):
    """右上角自动消失的通知弹窗（Toast）- 明亮主题版"""

    closed = Signal()

    _DISPLAY_AREA_MARGIN_RIGHT = 15
    _DISPLAY_AREA_MARGIN_TOP = 40
    _TOAST_SPACING = 55

    def __init__(
        self, message, parent=None, duration=3000, toast_type="info", stack_index=0, node_name=None, operation_type=None
    ):
        super().__init__(parent)

        self.stack_index = stack_index
        self.parent_window = parent
        self.node_name = node_name
        self.operation_type = operation_type

        if self.parent_window:
            self.parent_window.installEventFilter(self)
            self._last_parent_geometry = self.parent_window.geometry()

        config = _toast_config
        color_map = {
            "info": config["info_color"],
            "success": config["success_color"],
            "warning": config["warning_color"],
            "error": config["error_color"],
        }
        bg_color = color_map.get(toast_type, config["info_color"])
        text_color = config["text_color"]
        border_color = config["border_color"]

        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._label = QLabel(message)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            "background-color: " + bg_color + ";"
            "color: " + text_color + ";"
            "border: 1px solid " + border_color + ";"
            "padding: 10px 18px;"
            "border-radius: 8px;"
            "font-size: 13px;"
        )
        outer.addWidget(self._label)

        self.adjustSize()

        self.duration = duration
        self._fade_duration = 300
        self._opacity = 0.0
        self._is_fading_in = False
        self._is_fading_out = False
        self._pending_show = False

        self._anim_timer = QTimer(self)
        self._anim_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._anim_timer.timeout.connect(self._tick_animation)

        self._stay_timer = QTimer(self)
        self._stay_timer.setSingleShot(True)
        self._stay_timer.timeout.connect(self.start_fade_out)

        self.setWindowOpacity(0.0)

    def show_toast(self):
        """显示通知并启动淡入动画"""
        self.adjustSize()
        self._position_correctly()

        self.setWindowOpacity(0.0)
        self._opacity = 0.0

        if self.parent_window and not self.parent_window.isActiveWindow():
            self._pending_show = True
            self._is_fading_in = True
            self._is_fading_out = False
            self._anim_timer.start(16)
            return

        self._pending_show = False
        self.show()
        QTimer.singleShot(150, self._delayed_positioning)
        self.raise_()

        self._is_fading_in = True
        self._is_fading_out = False
        self._anim_timer.start(16)

    def _delayed_positioning(self):
        self._position_correctly()

    def _tick_animation(self):
        if self._is_fading_in:
            self._opacity += 16.0 / self._fade_duration
            if self._opacity >= 1.0:
                self._opacity = 1.0
                self._is_fading_in = False
                self.setWindowOpacity(1.0)
                self._anim_timer.stop()
                if not self._stay_timer.isActive():
                    self._stay_timer.start(self.duration)
            else:
                self.setWindowOpacity(self._opacity)
        elif self._is_fading_out:
            self._opacity -= 16.0 / self._fade_duration
            if self._opacity <= 0.0:
                self._opacity = 0.0
                self._is_fading_out = False
                self.setWindowOpacity(0.0)
                self._anim_timer.stop()
                if self._stay_timer.isActive():
                    self._stay_timer.stop()
                self.close()
            else:
                self.setWindowOpacity(self._opacity)

    def start_fade_out(self):
        if self._is_fading_out or self._is_fading_in:
            return
        self._is_fading_out = True
        self._anim_timer.start(16)

    def eventFilter(self, obj, event):
        if obj is self.parent_window:
            if event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
                current_geometry = self.parent_window.geometry()
                if current_geometry != self._last_parent_geometry:
                    self._last_parent_geometry = current_geometry
                    self._position_correctly()
            elif event.type() == QEvent.Type.WindowDeactivate:
                if self.isVisible():
                    self.hide()
            elif event.type() == QEvent.Type.WindowActivate:
                if self._pending_show:
                    self._pending_show = False
                    self.show()
                    self.raise_()
                    self._position_correctly()
                    QTimer.singleShot(150, self._delayed_positioning)
                elif not self.isVisible():
                    self.show()
                    self.raise_()
                    self._position_correctly()
        return super().eventFilter(obj, event)

    def _position_correctly(self):
        if self.parent_window:
            self._position_relative_to_parent()
        else:
            self._position_relative_to_screen()

    def _position_relative_to_parent(self):
        pw = self.parent_window
        parent_top_left = pw.mapToGlobal(pw.rect().topLeft())
        parent_bottom_right = pw.mapToGlobal(pw.rect().bottomRight())

        toast_x = parent_bottom_right.x() - self.width() - self._DISPLAY_AREA_MARGIN_RIGHT
        base_toast_y = parent_top_left.y() + self._DISPLAY_AREA_MARGIN_TOP

        max_safe_x = parent_bottom_right.x() - self.width() - 5
        max_safe_y = parent_bottom_right.y() - self.height() - 5
        min_safe_x = parent_top_left.x() + 5
        min_safe_y = parent_top_left.y() + 50

        x = max(min(toast_x, max_safe_x), min_safe_x)
        y = max(min(base_toast_y + (self.stack_index * self._TOAST_SPACING), max_safe_y), min_safe_y)

        self.move(x, y)

    def _position_relative_to_screen(self):
        from PySide6.QtWidgets import QApplication

        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.right() - self.width() - self._DISPLAY_AREA_MARGIN_RIGHT
            y = geo.top() + self._DISPLAY_AREA_MARGIN_TOP + (self.stack_index * self._TOAST_SPACING)
            self.move(x, y)

    def update_position(self):
        self._position_correctly()
