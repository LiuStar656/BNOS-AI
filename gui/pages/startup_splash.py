"""启动闪屏 — 引擎启动动画 + 节点状态轮询"""

from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QVBoxLayout,
    QWidget,
)


def _read_node_status(project_root: str) -> dict | None:
    """读取 bnos_status.json，返回节点状态字典。"""
    path = Path(project_root) / "bnos_status.json"
    if not path.exists():
        return None
    try:
        raw = path.read_text("utf-8").strip()
        if not raw:
            return None
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return None


def _all_nodes_running(status: dict | None) -> bool:
    """检查是否所有节点都处于 running 状态。"""
    if status is None:
        return False
    nodes = status.get("nodes", {})
    if not nodes:
        return False
    return all(
        n.get("status") == "running" for n in nodes.values()
    )


class SpinnerWidget(QWidget):
    """旋转加载指示器 — 用 QPainter 绘制。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)
        self._timer.start(50)

    def _rotate(self):
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        r = min(cx, cy) - 6
        painter.translate(cx, cy)
        painter.rotate(self._angle)
        for i in range(12):
            alpha = 255 - int(200 * i / 12)
            color = QColor(26, 115, 232, alpha)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(0, r - 4, 6, 6)
            painter.rotate(30)


class StartupSplash(QWidget):
    """启动闪屏窗口 — 引擎启动期间展示。

    启动流程：
        1. 引擎启动
        2. 轮询 bnos_status.json
        3. 节点全部就绪 → 关闭闪屏，发射 nodes_ready 信号
    """

    nodes_ready = Signal()  # 所有节点就绪时发射

    NODE_LABELS: dict[str, str] = {
        "node_python_aaa_cognition": "AAA 认知",
        "node_python_llm_infer":     "LLM 推理",
        "node_python_tts":           "TTS 语音",
    }

    POLL_INTERVAL_MS = 500
    MAX_WAIT_SEC = 60

    def __init__(self, project_root: str):
        super().__init__()
        self._project_root = project_root
        self._start_time = time.time()
        self._last_nodes: dict[str, str] = {}  # node_id → last_status

        # 窗口属性
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(420, 300)

        # 居中
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            self.move(
                sg.center().x() - self.width() // 2,
                sg.center().y() - self.height() // 2,
            )

        self._build_ui()

        # 轮询定时器
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_status)

    def _build_ui(self):
        """构建 UI 组件。"""
        # 背景容器
        container = QWidget(self)
        container.setObjectName("splashContainer")
        container.setStyleSheet("""
            QWidget#splashContainer {
                background-color: #ffffff;
                border-radius: 12px;
                border: 1px solid #e0e0e0;
            }
        """)
        container.setGeometry(0, 0, 420, 300)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(6)

        # 标题
        title = QLabel("BNOS AI 伴侣")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #1a1a1a;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 副标题
        subtitle = QLabel("正在启动引擎...")
        subtitle.setObjectName("splashSubtitle")
        subtitle.setStyleSheet("font-size: 13px; color: #888;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(12)

        # 旋转动画
        spinner = SpinnerWidget()
        spinner.setFixedSize(48, 48)
        spinner_layout = QVBoxLayout()
        spinner_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spinner_layout.addWidget(spinner)
        layout.addLayout(spinner_layout)

        layout.addSpacing(8)

        # 节点状态列表
        self._status_labels: dict[str, QLabel] = {}
        for node_id, label in self.NODE_LABELS.items():
            lbl = QLabel(f"  ○  {label}  等待中...")
            lbl.setStyleSheet("font-size: 12px; color: #aaa;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)
            self._status_labels[node_id] = lbl

        layout.addStretch()

        # 底部提示
        hint = QLabel("首次启动可能需要下载模型")
        hint.setObjectName("splashHint")
        hint.setStyleSheet("font-size: 11px; color: #bbb;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

    # ─── 公开接口 ─────────────────────────────

    def start_waiting(self):
        """开始轮询节点状态。"""
        self._last_nodes = {}
        self._start_time = time.time()
        self._poll_timer.start(self.POLL_INTERVAL_MS)
        self.show()

    # ─── 内部方法 ─────────────────────────────

    def _poll_status(self):
        """轮询 bnos_status.json，更新节点状态。"""
        status = _read_node_status(self._project_root)
        elapsed = time.time() - self._start_time

        # 更新每个节点的状态显示
        nodes = (status or {}).get("nodes", {})
        for node_id, label_obj in self._status_labels.items():
            node_info = nodes.get(node_id)
            last = self._last_nodes.get(node_id)
            if node_info is None:
                if last != "waiting":
                    label_obj.setText(f"  ○  {self.NODE_LABELS[node_id]}  等待中...")
                    label_obj.setStyleSheet("font-size: 12px; color: #aaa;")
                    self._last_nodes[node_id] = "waiting"
            elif node_info.get("status") == "running":
                if last != "running":
                    label_obj.setText(f"  ●  {self.NODE_LABELS[node_id]}  已就绪")
                    label_obj.setStyleSheet("font-size: 12px; color: #1a73e8; font-weight: bold;")
                    self._last_nodes[node_id] = "running"
            else:
                if last != "starting":
                    label_obj.setText(f"  ◌  {self.NODE_LABELS[node_id]}  启动中...")
                    label_obj.setStyleSheet("font-size: 12px; color: #e8a01a;")
                    self._last_nodes[node_id] = "starting"

        # 更新副标题
        subtitle = self.findChild(QLabel, "splashSubtitle")
        if subtitle:
            subtitle.setText(f"正在启动引擎... ({int(elapsed)}s)")

        # 检查是否全部就绪
        if _all_nodes_running(status):
            self._poll_timer.stop()
            subtitle = self.findChild(QLabel, "splashSubtitle")
            if subtitle:
                subtitle.setText("引擎已就绪")
            hint = self.findChild(QLabel, "splashHint")
            if hint:
                hint.setText("正在进入主界面...")
            QApplication.processEvents()
            # 延迟一小段让用户看到"已就绪"状态
            QTimer.singleShot(300, self.nodes_ready.emit)
            return

        # 超时处理
        if elapsed > self.MAX_WAIT_SEC:
            self._poll_timer.stop()
            subtitle = self.findChild(QLabel, "splashSubtitle")
            if subtitle:
                subtitle.setText("启动超时，请检查节点状态")
            hint = self.findChild(QLabel, "splashHint")
            if hint:
                hint.setText("可继续进入主界面手动排查")
            QTimer.singleShot(1500, self.nodes_ready.emit)
