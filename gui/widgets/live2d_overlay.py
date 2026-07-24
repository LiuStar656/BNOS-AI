"""Live2D 桌面悬浮窗 — 无边框透明窗口，桌面最底层显示"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, QPoint, QRect
from PySide6.QtGui import QAction, QCloseEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings

from gui.core.config import AppConfig


class Live2DOverlay(QWidget):
    """Live2D 桌面悬浮窗。无边框、透明、桌面最底层，不阻挡其他窗口。"""

    CONFIG_KEY = "live2d_overlay"
    SCALE_KEY = "live2d_model_scale"

    SERVER_PORT = 3000
    RESIZE_MARGIN = 12  # 缩放拖拽区域宽度（像素）

    DEFAULT_SCALE = 0.35
    SCALE_MIN = 0.05
    SCALE_MAX = 2.0
    SCALE_STEP = 0.05  # 每格滚轮的缩放增量

    def __init__(self, model_rel_path: str = ""):
        super().__init__()
        self._drag_pos: QPoint | None = None
        self._is_dragging = False
        self._is_dragging_model = False
        self._is_resizing = False
        self._model_rel_path = model_rel_path
        self._init_done = False

        # 加载保存的模型缩放值
        self._model_scale = AppConfig().get(self.SCALE_KEY, self.DEFAULT_SCALE)

        self._setup_window()
        self._setup_webview()
        self._restore_geometry()
        self._init_done = True

    # ─── 窗口属性 ───────────────────────────────────

    def _setup_window(self):
        self.setWindowTitle("Live2D 桌面")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnBottomHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(200, 300)
        self.resize(400, 600)

    # ─── WebView ────────────────────────────────────

    def _setup_webview(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._web = QWebEngineView()
        settings = self._web.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        self._web.setStyleSheet("background: transparent;");
        self._web.page().setBackgroundColor(Qt.GlobalColor.transparent)
        self._web.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # 页面加载完成后恢复保存的模型缩放值
        self._web.loadFinished.connect(self._on_page_loaded)

        self._load_model(self._model_rel_path)

        layout.addWidget(self._web, 1)

    def _on_page_loaded(self, ok: bool):
        """页面加载完成后，应用保存的模型缩放值"""
        if ok and self._model_scale != self.DEFAULT_SCALE:
            self._web.page().runJavaScript(
                f"setModelScaleAbsolute({self._model_scale})"
            )

    def _load_model(self, model_rel_path: str = ""):
        url = f"http://localhost:{self.SERVER_PORT}/"
        self._web.setUrl(QUrl(url))

    def setModel(self, model_rel_path: str):
        self._model_rel_path = model_rel_path
        self._load_model(model_rel_path)

    # ─── 判断鼠标是否在缩放区域 ─────────────────────

    def _in_resize_area(self, pos: QPoint) -> bool:
        """检查鼠标位置是否在窗口右下角的缩放区域内"""
        return (
            pos.x() >= self.width() - self.RESIZE_MARGIN
            and pos.y() >= self.height() - self.RESIZE_MARGIN
        )

    # ─── 鼠标事件（拖动 + 缩放）────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            local_pos = event.position().toPoint()
            if self._in_resize_area(local_pos):
                self._is_resizing = True
                self._drag_pos = event.globalPosition().toPoint()
                self._drag_rect = QRect(self.geometry())
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                event.accept()
                return

            self._drag_pos = event.globalPosition().toPoint()
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._is_dragging_model = True
                self.setCursor(Qt.CursorShape.DragMoveCursor)
            else:
                self._is_dragging = True
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not (event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos):
            # 不按下左键时，悬停到缩放区域切换光标
            if self._in_resize_area(event.position().toPoint()):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        delta = event.globalPosition().toPoint() - self._drag_pos

        if self._is_resizing:
            # 自定义缩放
            new_w = max(self.minimumWidth(), self._drag_rect.width() + delta.x())
            new_h = max(self.minimumHeight(), self._drag_rect.height() + delta.y())
            self.setGeometry(
                self._drag_rect.x(),
                self._drag_rect.y(),
                new_w,
                new_h,
            )
        elif self._is_dragging_model:
            js = f"moveModelPosition({delta.x()}, {delta.y()})"
            self._web.page().runJavaScript(js)
        elif self._is_dragging:
            self.move(self.pos() + delta)

        self._drag_pos = event.globalPosition().toPoint()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._is_dragging_model = False
            self._is_resizing = False
            self._drag_pos = None
            self._drag_rect = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._save_geometry()
            event.accept()

    # ─── Ctrl + 滚轮缩放模型 ──────────────────────

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            # 在 Python 侧计算新缩放值，发送绝对值给 JS，并保存
            step = self.SCALE_STEP if delta > 0 else -self.SCALE_STEP
            self._model_scale = max(self.SCALE_MIN, min(self.SCALE_MAX, self._model_scale + step))
            self._web.page().runJavaScript(
                f"setModelScaleAbsolute({self._model_scale})"
            )
            self._save_model_scale()
            event.accept()
        else:
            super().wheelEvent(event)

    # ─── 关闭事件 ───────────────────────────────────

    def closeEvent(self, event: QCloseEvent):
        self._save_geometry()
        super().closeEvent(event)

    # ─── 右键菜单 ───────────────────────────────────

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: white; border: 1px solid #ddd; border-radius: 6px; padding: 4px; }
            QMenu::item { padding: 6px 20px; border-radius: 4px; }
            QMenu::item:selected { background: #e8f0fe; }
        """)
        close_action = QAction("关闭", self)
        close_action.triggered.connect(self.close)
        menu.addAction(close_action)
        menu.exec(event.globalPos())

    # ─── 尺寸/位置持久化 ─────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 初始化完成之后才保存（防止 init 时误存默认尺寸）
        if self._init_done:
            self._save_geometry()

    def moveEvent(self, event):
        super().moveEvent(event)
        if self._init_done:
            self._save_geometry()

    def _save_geometry(self):
        rect = self.geometry()
        data = {"x": rect.x(), "y": rect.y(), "w": rect.width(), "h": rect.height()}
        cfg = AppConfig()
        cfg.set(self.CONFIG_KEY, data)
        cfg.set(self.SCALE_KEY, self._model_scale)
        cfg.save()

    def _save_model_scale(self):
        """仅保存缩放值（wheelEvent 中调用）"""
        cfg = AppConfig()
        cfg.set(self.SCALE_KEY, self._model_scale)
        cfg.save()

    def _restore_geometry(self):
        cfg = AppConfig()
        data = cfg.get(self.CONFIG_KEY, {})
        if data:
            self.setGeometry(data["x"], data["y"], data["w"], data["h"])
