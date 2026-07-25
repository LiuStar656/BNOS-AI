"""Live2D 预览页 — 内嵌 QWebEngineView 加载 Live2D HTTP 渲染服务"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QTimer, Signal, QEvent, QPoint
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QGroupBox,
    QApplication,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings


class _Live2DWebPage(QWebEnginePage):
    """自定义 WebPage，捕获 JS 控制台输出到 Python 终端"""
    page_console = Signal(object, str, int, str)  # level, msg, line, src

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        try:
            self.page_console.emit(level, message, lineNumber, sourceID)
        except Exception:
            pass
        super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)

from gui.core.config import AppConfig
from gui.widgets.live2d_overlay import Live2DOverlay


class Live2DPage(QWidget):
    """Live2D 预览页。左侧控制面板 + 右侧 QWebEngineView 渲染。"""

    CONFIG_KEY = "live2d_sidebar_width"
    CURRENT_MODEL_KEY = "live2d_current_model"
    TTS_ENABLED_KEY = "tts_enabled"
    TTS_PORT = 8084

    @classmethod
    def _server_script_path(cls) -> Path:
        return Path(__file__).resolve().parent.parent / "live2d" / "server.py"

    @classmethod
    def _tts_script_path(cls) -> Path:
        """TTS 服务脚本路径（位于 Live2D 节点目录）"""
        root = Path(__file__).resolve().parent.parent.parent
        return root / "nodes" / "node_js_live2d_face" / "tts_server.py"

    @classmethod
    def _models_dir_path(cls) -> Path:
        return Path(__file__).resolve().parent.parent / "live2d" / "2D"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server_proc: subprocess.Popen | None = None
        self._overlay: Live2DOverlay | None = None
        self._page_shown = False
        self._preview_loaded = False
        self._current_model_path: str | None = None

        # 模型缩放/拖拽状态（Ctrl+滚轮缩放、Ctrl+左键拖拽，与桌面悬浮窗一致）
        self._model_scale = AppConfig().get(Live2DOverlay.SCALE_KEY, Live2DOverlay.DEFAULT_SCALE)
        self._model_drag_pos: QPoint | None = None
        self._is_model_dragging = False

        # TTS 进程状态（GUI 直接持有，支持运行时热开关）
        self._tts_proc: subprocess.Popen | None = None
        self._tts_enabled = AppConfig().get(self.TTS_ENABLED_KEY, True)

        self._colors = AppConfig().get_all_colors()

        # 启动后台服务
        self._start_server()

        # ── QSplitter ──
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.setHandleWidth(4)
        self._splitter.setChildrenCollapsible(False)

        # ── 左侧面板 ──
        left_panel = QWidget()
        left_panel.setObjectName("live2dSidebar")
        left_panel.setStyleSheet(f"""
            QWidget#live2dSidebar {{
                background-color: {self._colors['bg_secondary']};
            }}
        """)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(8)

        title = QLabel("Live2D 渲染")
        title.setStyleSheet(f"""
            font-size: 14px; font-weight: bold;
            color: {self._colors['text_primary']};
            padding: 4px 0;
        """)
        left_layout.addWidget(title)

        # 模型选择组
        model_group = QGroupBox("模型选择")
        model_group.setStyleSheet(f"""
            QGroupBox {{
                color: {self._colors['text_primary']};
                border: 1px solid {self._colors['border_color']};
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 8px;
                font-weight: 500;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }}
        """)
        model_group_layout = QVBoxLayout(model_group)
        model_group_layout.setContentsMargins(6, 6, 6, 6)
        model_group_layout.setSpacing(6)

        self._model_list = QListWidget()
        self._model_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {self._colors['bg_primary']};
                border: none;
                border-radius: 4px;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 6px 8px;
                border-radius: 4px;
                margin: 2px;
            }}
            QListWidget::item:selected {{
                background-color: {self._colors['select_bg']};
                color: {self._colors['accent_color']};
            }}
        """)
        self._model_list.currentItemChanged.connect(self._on_model_changed)
        model_group_layout.addWidget(self._model_list)

        # 模型操作按钮
        model_btn_layout = QHBoxLayout()
        self._open_folder_btn = QPushButton("打开模型文件夹")
        self._open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_folder_btn.clicked.connect(self._open_models_folder)
        model_btn_layout.addWidget(self._open_folder_btn)
        model_group_layout.addLayout(model_btn_layout)

        left_layout.addWidget(model_group)

        left_layout.addStretch()

        # TTS 语音开关（运行时热开/热关）
        self._tts_btn = QPushButton()
        self._tts_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tts_btn.clicked.connect(self._toggle_tts)
        self._apply_tts_btn_style()
        left_layout.addWidget(self._tts_btn)

        self._desktop_btn = QPushButton("桌面显示")
        self._desktop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        accent = self._colors.get('accent_color', '#1a73e8')
        self._desktop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {accent};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {self._colors.get('select_bg', '#1557b0')};
            }}
        """)
        self._desktop_btn.clicked.connect(self._toggle_desktop)
        left_layout.addWidget(self._desktop_btn)

        self._splitter.addWidget(left_panel)

        # ── 右侧渲染区 ──
        self._web_view = QWebEngineView()
        self._web_page = _Live2DWebPage()
        self._web_view.setPage(self._web_page)
        self._web_page.page_console.connect(self._on_js_console)
        settings = self._web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, True)
        self._web_view.loadFinished.connect(self._on_preview_page_loaded)
        self._splitter.addWidget(self._web_view)

        # 恢复左侧栏宽度
        self._restore_sidebar_width()

        # 主布局
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self._splitter)

        # 扫描模型列表
        self._scan_models()

        # 后台预加载预览（服务启动后自动导航）
        QTimer.singleShot(1500, self._load_preview)

        # 应用级事件过滤器：拦截预览 webview 的 Ctrl+滚轮缩放 / Ctrl+左键拖拽
        QApplication.instance().installEventFilter(self)

    def showEvent(self, event):
        """页面变为可见时，若 canvas 是 0x0（后台加载导致），重新加载页面。"""
        super().showEvent(event)
        if self._preview_loaded and not self._page_shown:
            self._page_shown = True
            # 首次显示时重新加载页面（让 initRenderer 以正确尺寸运行）
            print("[Live2D] 页面首次可见，重新加载渲染器...")
            QTimer.singleShot(100, lambda: self._web_view.reload())

    # ─── JS 控制台日志 ──────────────────────────────

    def _on_js_console(self, level: int, msg: str, line: int, src: str):
        """捕获 JS 控制台输出"""
        levels = {0: "INFO", 1: "WARN", 2: "ERROR"}
        print(f"[JS-{levels.get(level, str(level))}] {msg} ({src}:{line})")

    # ─── 服务管理 ──────────────────────────────────

    @staticmethod
    def _is_port_open(port: int) -> bool:
        """检查本地端口是否已开放"""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            result = s.connect_ex(('127.0.0.1', port))
            s.close()
            return result == 0
        except Exception:
            return False

    def _load_preview(self):
        """加载 Live2D 预览页面（带服务器健康检查和自动重试）"""
        # 检查服务器进程是否还在运行
        if self._server_proc and self._server_proc.poll() is not None:
            ret = self._server_proc.returncode
            print(f"[Live2D] 服务器进程已退出（返回码={ret}），尝试重启...")
            self._start_server()

        # 检查端口是否已就绪
        if not self._is_port_open(3000):
            print("[Live2D] 端口 3000 未就绪，1 秒后重试...")
            QTimer.singleShot(1000, self._load_preview)
            return

        print("[Live2D] 预览服务器就绪，加载页面 http://127.0.0.1:3000")
        self._web_view.setUrl(QUrl("http://127.0.0.1:3000"))
        self._preview_loaded = True

    def _on_preview_page_loaded(self, ok: bool):
        """预览页加载完成后的处理"""
        print(f"[Live2D] 预览页面加载{'成功' if ok else '失败'}")
        if not ok:
            # 加载失败，尝试重载
            QTimer.singleShot(2000, lambda: self._web_view.reload())
            return
        # 应用保存的模型缩放值（与桌面悬浮窗保持一致）
        if self._model_scale != Live2DOverlay.DEFAULT_SCALE:
            self._web_view.page().runJavaScript(
                f"setModelScaleAbsolute({self._model_scale})"
            )
        # 同步 TTS 启用状态到前端（控制 renderer.js 是否播放）
        self._push_tts_flag()
        # 读取当前选中的模型，如果不是默认 feiniu，则加载它
        item = self._model_list.currentItem()
        if item:
            model_path = item.data(Qt.ItemDataRole.UserRole)
            if model_path and 'feiniu' not in model_path:
                js_path = self._build_model_js_path(model_path)
                QTimer.singleShot(200, lambda: self._web_view.page().runJavaScript(
                    f'loadModel("{js_path}")'
                ))

    # ─── 预览页模型缩放/拖拽（Ctrl+滚轮 / Ctrl+左键）──

    def _is_within_webview(self, watched) -> bool:
        """判断 watched 是否属于预览 webview 的子树"""
        web = getattr(self, "_web_view", None)
        if web is None:
            return False
        w = watched
        while w is not None:
            if w is web:
                return True
            w = w.parent()
        return False

    def _scale_preview_model(self, event: QWheelEvent):
        """Ctrl+滚轮缩放预览模型，并持久化（与桌面悬浮窗共享配置）"""
        delta = event.angleDelta().y()
        step = Live2DOverlay.SCALE_STEP if delta > 0 else -Live2DOverlay.SCALE_STEP
        self._model_scale = max(
            Live2DOverlay.SCALE_MIN,
            min(Live2DOverlay.SCALE_MAX, self._model_scale + step),
        )
        self._web_view.page().runJavaScript(
            f"setModelScaleAbsolute({self._model_scale})"
        )
        cfg = AppConfig()
        cfg.set(Live2DOverlay.SCALE_KEY, self._model_scale)
        cfg.save()

    def eventFilter(self, watched, event):
        etype = event.type()

        # 拖拽进行中：全局拦截鼠标移动与释放，保证拖出 webview 也能继续移动
        if self._is_model_dragging:
            if etype == QEvent.Type.MouseMove:
                if self._model_drag_pos is not None:
                    delta = event.globalPosition().toPoint() - self._model_drag_pos
                    self._web_view.page().runJavaScript(
                        f"moveModelPosition({delta.x()}, {delta.y()})"
                    )
                    self._model_drag_pos = event.globalPosition().toPoint()
                return True
            if etype == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self._is_model_dragging = False
                self._model_drag_pos = None
                self._web_view.setCursor(Qt.CursorShape.ArrowCursor)
                return True

        # 非拖拽事件需落在预览 webview 子树内才处理
        if not self._is_within_webview(watched):
            return super().eventFilter(watched, event)

        if etype == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._scale_preview_model(event)
                return True
        elif etype == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton and (
                event.modifiers() & Qt.KeyboardModifier.ControlModifier
            ):
                self._is_model_dragging = True
                self._model_drag_pos = event.globalPosition().toPoint()
                self._web_view.setCursor(Qt.CursorShape.DragMoveCursor)
                return True

        return super().eventFilter(watched, event)

    def _start_server(self):
        """启动 Live2D HTTP 渲染服务，并按配置决定是否启动 TTS。"""
        # 先尝试清理旧端口占用
        self._kill_port(3000)
        script = self._server_script_path()
        if not script.exists():
            print(f"[Live2D] 服务脚本不存在: {script}")
            return
        try:
            self._server_proc = subprocess.Popen(
                [sys.executable, str(script)],
                cwd=str(script.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                text=True,
            )
            print(f"[Live2D] 渲染服务已启动 PID={self._server_proc.pid}")
        except Exception as e:
            print(f"[Live2D] 启动失败: {e}")

        # 按配置启动 TTS（GUI 直接持有进程，支持热开关）
        if self._tts_enabled:
            self._start_tts()

    def _kill_port(self, port):
        """强制释放指定端口（杀掉占用进程）"""
        try:
            result = subprocess.run(
                f'netstat -ano | findstr ":{port}"',
                capture_output=True, text=True, shell=True, timeout=3
            )
            for line in result.stdout.splitlines():
                if "LISTENING" in line:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        try:
                            subprocess.run(["taskkill", "/F", "/PID", pid],
                                         capture_output=True, timeout=3)
                            print(f"[Live2D] 已杀掉端口 {port} 占用进程 PID={pid}")
                        except Exception:
                            pass
        except Exception:
            pass

    def _stop_server(self):
        # 先停 TTS（避免孤儿进程），再停渲染服务
        self._stop_tts()
        if self._server_proc and self._server_proc.poll() is None:
            self._server_proc.kill()
            self._server_proc.wait(timeout=3)
            self._server_proc = None
            print("[Live2D] 渲染服务已停止")

    # ─── TTS 热开关管理 ──────────────────────────────

    def _start_tts(self):
        """启动 TTS 服务进程（GUI 直接持有句柄，单一拥有者）。"""
        if self._tts_proc and self._tts_proc.poll() is None:
            return  # 已在运行
        script = self._tts_script_path()
        if not script.exists():
            print(f"[Live2D] TTS 脚本不存在: {script}")
            return
        # 清理 8084 残留占用（可能是上次未正常退出的孤儿进程）
        self._kill_port(self.TTS_PORT)
        try:
            self._tts_proc = subprocess.Popen(
                [sys.executable, str(script), "--port", str(self.TTS_PORT)],
                cwd=str(script.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                text=True,
            )
            print(f"[Live2D] TTS 服务已启动 PID={self._tts_proc.pid}")
        except Exception as e:
            print(f"[Live2D] TTS 启动失败: {e}")
            self._tts_proc = None

    def _stop_tts(self):
        """停止 TTS 服务进程（用真实 PID，无孤儿）。"""
        if self._tts_proc and self._tts_proc.poll() is None:
            try:
                self._tts_proc.kill()
                self._tts_proc.wait(timeout=3)
                print("[Live2D] TTS 服务已停止")
            except Exception as e:
                print(f"[Live2D] TTS 停止异常: {e}")
        self._tts_proc = None

    def _toggle_tts(self):
        """运行时热开关 TTS：翻转启用状态 -> 持久化 -> 启/停进程 -> 推送前端标志。"""
        self._tts_enabled = not self._tts_enabled
        cfg = AppConfig()
        cfg.set(self.TTS_ENABLED_KEY, self._tts_enabled)
        cfg.save()

        if self._tts_enabled:
            self._start_tts()
        else:
            self._stop_tts()
        self._push_tts_flag()
        self._apply_tts_btn_style()

    def _push_tts_flag(self):
        """把 TTS 启用状态推送到前端 webview，控制 renderer.js 是否播放。"""
        js = f"window.TTS_ENABLED = {'true' if self._tts_enabled else 'false'};"
        # 预览页
        if self._web_view is not None:
            self._web_view.page().runJavaScript(js)
        # 桌面悬浮窗
        if self._overlay is not None and hasattr(self._overlay, "_web"):
            self._overlay._web.page().runJavaScript(js)

    def _apply_tts_btn_style(self):
        """根据 _tts_enabled 更新按钮文本与样式。"""
        accent = self._colors.get('accent_color', '#1a73e8')
        on_bg = accent
        off_bg = self._colors.get('bg_primary', '#555555')
        if self._tts_enabled:
            self._tts_btn.setText("语音：开")
            bg, fg = on_bg, "white"
        else:
            self._tts_btn.setText("语音：关")
            bg, fg = off_bg, self._colors.get('text_primary', 'white')
        self._tts_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: none;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {self._colors.get('select_bg', '#1557b0')};
            }}
        """)

    # ─── 模型管理 ────────────────────────────────────

    def _scan_models(self):
        """扫描模型目录，更新模型列表。"""
        self._model_list.clear()
        models_dir = self._models_dir_path()
        if not models_dir.exists():
            return

        # 先看根目录有没有模型
        root_models = list(models_dir.glob("*.model3.json"))
        for model_file in root_models:
            item = QListWidgetItem(model_file.stem)
            item.setData(Qt.ItemDataRole.UserRole, str(model_file.name))
            self._model_list.addItem(item)

        # 再看子目录有没有
        for subdir in models_dir.iterdir():
            if subdir.is_dir():
                subdir_models = list(subdir.glob("*.model3.json"))
                if subdir_models:
                    item = QListWidgetItem(f"{subdir.name}/")
                    item.setData(Qt.ItemDataRole.UserRole, str(subdir.name))
                    self._model_list.addItem(item)

        # 尝试恢复上次的选择
        cfg = AppConfig()
        last_model = cfg.get(self.CURRENT_MODEL_KEY)
        if last_model:
            for i in range(self._model_list.count()):
                item = self._model_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == last_model:
                    self._model_list.setCurrentItem(item)
                    break

    def _build_model_js_path(self, model_path: str) -> str:
        """根据模型路径数据构建 JS 使用的 URL 路径"""
        if model_path.endswith('/'):
            dir_name = model_path[:-1]
            return f'/2D/{dir_name}/{dir_name}.model3.json'
        return f'/2D/{model_path}'

    def _on_model_changed(self, item: QListWidgetItem):
        if not item:
            return
        model_path = item.data(Qt.ItemDataRole.UserRole)
        if not model_path:
            return
        # 保存配置
        cfg = AppConfig()
        cfg.set(self.CURRENT_MODEL_KEY, model_path)
        cfg.save()
        
        # 构建模型路径
        js_path = self._build_model_js_path(model_path)
        
        # 调用 JS 加载新模型
        js_code = f'loadModel("{js_path}")'
        self._web_view.page().runJavaScript(js_code)
        
        # 同时更新 desktop overlay 的模型
        if self._overlay and hasattr(self._overlay, '_web'):
            self._overlay._web.page().runJavaScript(js_code)

    def _open_models_folder(self):
        models_dir = self._models_dir_path()
        if not models_dir.exists():
            models_dir.mkdir(parents=True, exist_ok=True)
        webbrowser.open(models_dir.absolute().as_uri())

    # ─── 桌面显示 ───────────────────────────────────

    def _toggle_desktop(self):
        if self._overlay is not None and self._overlay.isVisible():
            self._overlay.close()
            self._overlay.deleteLater()
            self._overlay = None
            self._desktop_btn.setText("桌面显示")
            return

        self._overlay = Live2DOverlay()
        self._overlay.destroyed.connect(self._on_overlay_closed)
        self._overlay.show()
        self._desktop_btn.setText("关闭桌面")
        # overlay 页面加载后同步 TTS 启用状态
        QTimer.singleShot(800, self._push_tts_flag)

    def _on_overlay_closed(self):
        self._overlay = None
        self._desktop_btn.setText("桌面显示")

    # ─── 左侧栏宽度持久化 ──────────────────────────

    def _save_sidebar_width(self):
        try:
            sizes = self._splitter.sizes()
            if not sizes or sizes[0] <= 0:
                return
            w = sizes[0]
        except Exception:
            return
        cfg_path = Path(__file__).resolve().parent.parent.parent / "gui_config.json"
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        cfg[self.CONFIG_KEY] = w
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _restore_sidebar_width(self):
        cfg_path = Path(__file__).resolve().parent.parent.parent / "gui_config.json"
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            w = cfg.get(self.CONFIG_KEY)
            if isinstance(w, (int, float)) and w >= 100:
                self._splitter.setSizes([w, max(self.width() - w, 400)])
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self._page_shown = True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._page_shown:
            self._save_sidebar_width()

    # ─── 生命周期 ───────────────────────────────────

    def refresh(self):
        self._scan_models()
