"""首页 — 欢迎 + 系统状态 + 快捷入口（BNOS 启动默认页）"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.core.config import AppConfig
from gui.core.event_bus import event_bus
from gui.core.messages import NAVIGATE_REQUEST
from gui.core.state import AppState

_STATUS_REFRESH_MS = 3000  # 引擎/节点状态轮询间隔


class HomePage(QWidget):
    """BNOS 首页：启动默认页。

    - 欢迎区：按时间段问候
    - 状态区：引擎状态 + 节点在线数（轮询 AppState）
    - 快捷入口：跳转聊天/记忆库/AI 活动/Live2D/DSH 管理/流程
    """

    # 快捷入口：(page_id, 标题, 描述)
    _SHORTCUTS = [
        ("chat", "聊天", "与 AI 日常对话"),
        ("knowledge", "记忆库", "浏览记忆与认知数据"),
        ("activity", "AI 活动", "查看 AI 行为轨迹"),
        ("live2d", "Live2D", "虚拟形象互动"),
        ("dsh_manage", "DSH 管理", "管理 DSH 助手"),
        ("workflows", "流程", "查看与执行流程"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = AppState()
        self._config = AppConfig()
        self._engine_label: QLabel | None = None
        self._node_label: QLabel | None = None
        self._build_ui()
        self._refresh_status()
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(_STATUS_REFRESH_MS)

    # ─── UI ──────────────────────────────────

    def _build_ui(self):
        colors = self._config.get_all_colors()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 30, 36, 20)
        outer.setSpacing(14)

        # 欢迎区
        title = QLabel(self._greeting())
        title.setStyleSheet(
            f"font-size: 26px; font-weight: bold; color: {colors['text_primary']};")
        outer.addWidget(title)

        sub = QLabel("欢迎回来，想聊点什么，还是看看我的记忆？")
        sub.setStyleSheet(
            f"font-size: 13px; color: {colors['text_secondary']};")
        outer.addWidget(sub)
        outer.addSpacing(6)

        # 状态区
        status_row = QHBoxLayout()
        status_row.setSpacing(12)
        self._engine_label = self._make_status_card("引擎状态", "检测中…")
        self._node_label = self._make_status_card("节点状态", "检测中…")
        status_row.addWidget(self._engine_label)
        status_row.addWidget(self._node_label)
        outer.addLayout(status_row)
        outer.addSpacing(10)

        # 快捷入口
        sec_title = QLabel("快捷入口")
        sec_title.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {colors['text_primary']};")
        outer.addWidget(sec_title)

        grid = QGridLayout()
        grid.setSpacing(12)
        for i, (pid, title, desc) in enumerate(self._SHORTCUTS):
            grid.addWidget(self._make_shortcut_card(pid, title, desc), i // 2, i % 2)
        outer.addLayout(grid)
        outer.addStretch(1)

    def _make_status_card(self, name: str, value: str) -> QLabel:
        colors = self._config.get_all_colors()
        card = QLabel()
        card.setObjectName("homeStatusCard")
        card.setStyleSheet(f"""
            #homeStatusCard {{
                background-color: {colors['bubble_ai_bg']};
                border: 1px solid {colors['border_color']};
                border-radius: 10px;
                padding: 12px 16px;
            }}
        """)
        card.setTextFormat(Qt.TextFormat.RichText)
        card.setText(f"<b>{name}</b>　{value}")
        return card

    def _make_shortcut_card(self, page_id: str, title: str, desc: str) -> QPushButton:
        colors = self._config.get_all_colors()
        btn = QPushButton()
        btn.setObjectName("homeShortcut")
        btn.setStyleSheet(f"""
            #homeShortcut {{
                background-color: {colors['bubble_ai_bg']};
                border: 1px solid {colors['border_color']};
                border-radius: 10px;
                padding: 14px 16px;
                text-align: left;
            }}
            #homeShortcut:hover {{
                background-color: {colors['accent_hover']};
            }}
        """)
        btn.setText(f"<b>{title}</b><br><span style='font-size:12px;"
                    f"color:{colors['text_secondary']}'>{desc}</span>")
        btn.clicked.connect(lambda _=False, p=page_id: self._go_to(p))
        return btn

    # ─── 状态刷新 ────────────────────────────

    def _greeting(self) -> str:
        hour = datetime.now().hour
        if hour < 6:
            return "夜深了，还没休息？"
        if hour < 12:
            return "早上好"
        if hour < 18:
            return "下午好"
        return "晚上好"

    def _refresh_status(self):
        colors = self._config.get_all_colors()
        ok_color = "#3fb950"
        bad_color = "#f85149"
        # 引擎状态
        eng = self._state.engine_status
        if eng == "online":
            eng_html = f"<span style='color:{ok_color}'><b>在线</b></span>"
        elif eng == "starting":
            eng_html = "<span style='color:#d29922'><b>启动中</b></span>"
        else:
            eng_html = f"<span style='color:{bad_color}'><b>离线</b></span>"
        if self._engine_label is not None:
            self._engine_label.setText(f"<b>引擎状态</b>　{eng_html}")
        # 节点在线数
        nodes = getattr(self._state, "nodes", {}) or {}
        online = sum(1 for n in nodes.values() if n.get("online"))
        total = len(nodes)
        if self._node_label is not None:
            self._node_label.setText(
                f"<b>节点状态</b>　<span style='color:{ok_color}'><b>{online}</b></span>"
                f" / {total} 在线")

    def _go_to(self, page_id: str):
        event_bus.publish(NAVIGATE_REQUEST, page_id)
