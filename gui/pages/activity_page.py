"""AI 活动页 — 实时事件流：AI 操作全部可见（P0-2）。

数据源：
- 工具执行事件（ToolBridge 发布 AI_EVENT, type=tool）
- 提案审批事件（proposal_store 发布 AI_EVENT, type=proposal）
- 主题变更事件（THEME_CHANGED）
- AAA 内心活动（轮询 chatbot.db feelings 表最新想法，type=thought）

目标：兑现"AI 操作可见"——agent 正在做什么、刚做了什么，实时上屏。
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from gui.core.utils.widget_utils import fit_button_width

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.core.event_bus import event_bus
from gui.core.messages import AI_EVENT, PAGE_ACTIVATED, THEME_CHANGED
from gui.core.theme_engine import theme_engine

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_PATH = _PROJECT_ROOT / "nodes" / "shared" / "chatbot.db"

_MAX_EVENTS = 200
_THOUGHT_POLL_MS = 3000

# 事件类型 → (显示名, token)
_TYPE_META = {
    "tool": ("工具", "accent_color"),
    "proposal": ("提案", "status_warn"),
    "theme": ("主题", "status_ok"),
    "thought": ("AI 内心", "icon_color"),
}


class ActivityPage(QWidget):
    """AI 活动事件流页"""

    def __init__(self):
        super().__init__()
        self._events: list[dict] = []
        self._last_thought = ""

        self._build_ui()
        self._subscribe_messages()

        # AAA 想法轮询（低频 DB 查询，主线程安全）
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_thought)
        self._poll_timer.start(_THOUGHT_POLL_MS)

    # ─── 消息订阅（阶段4） ──────────────────────

    def _subscribe_messages(self):
        if getattr(self, "_events_subscribed", False):
            return
        self._events_subscribed = True
        event_bus.subscribe(AI_EVENT, self._on_ai_event)
        event_bus.subscribe(THEME_CHANGED, self._on_theme_changed_msg)
        event_bus.subscribe(PAGE_ACTIVATED, self._on_page_activated_msg)

    def _on_page_activated_msg(self, page_id=None):
        if page_id == "activity":
            self._refresh()

    # ─── 事件处理 ───────────────────────────────

    def _on_ai_event(self, data=None):
        data = data or {}
        self._append({
            "type": data.get("type", "tool"),
            "text": data.get("text", ""),
            "ts": data.get("ts", time.time()),
        })

    def _on_theme_changed_msg(self, *_):
        self._append({"type": "theme", "text": "主题已变更", "ts": time.time()})

    def _append(self, event: dict):
        self._events.append(event)
        if len(self._events) > _MAX_EVENTS:
            self._events = self._events[-_MAX_EVENTS:]
        self._render_event(event)

    def _poll_thought(self):
        """轮询 AAA 最新内心想法（feelings.thought），变化时推送"""
        if not _DB_PATH.is_file():
            return
        try:
            conn = sqlite3.connect(str(_DB_PATH), timeout=2.0)
            row = conn.execute(
                "SELECT thought FROM feelings "
                "WHERE thought IS NOT NULL AND thought != '' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            conn.close()
        except sqlite3.Error:
            return
        if not row:
            return
        thought = str(row[0]).strip()
        if thought and thought != self._last_thought:
            self._last_thought = thought
            self._append({"type": "thought", "text": thought, "ts": time.time()})

    # ─── UI ─────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        header = QLabel("AI 活动")
        header.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {theme_engine.get('text_primary')};"
        )
        layout.addWidget(header)

        hint = QLabel(
            "实时事件流：AI 的工具调用、提案审批、主题变更，以及 AAA 的内心想法（意识流）。"
            "这是「AI 在做什么」的可视化窗口。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"font-size: 12px; color: {theme_engine.get('text_secondary')};"
        )
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("清空")
        fit_button_width(clear_btn)
        clear_btn.clicked.connect(self._clear)
        btn_row.addStretch()
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        layout.addWidget(self._scroll, 1)

        self._container = QWidget()
        self._container.setStyleSheet(
            f"background: {theme_engine.get('bg_secondary')}; border-radius: 8px;"
            f"border: 1px solid {theme_engine.get('border_color')};"
        )
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(10, 10, 10, 10)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._container)

        empty = QLabel("暂无活动。AI 的工具调用、提案审批会实时出现在这里。")
        empty.setStyleSheet(
            f"color: {theme_engine.get('icon_muted')}; font-size: 12px; padding: 24px;"
        )
        empty.setAlignment(Qt.AlignCenter)
        self._list_layout.insertWidget(0, empty)

    def _render_event(self, event: dict):
        # 移除空态占位
        if self._list_layout.count() > 1 and isinstance(
            self._list_layout.itemAt(0).widget(), QLabel
        ):
            w = self._list_layout.itemAt(0).widget()
            if w.text().startswith("暂无活动"):
                self._list_layout.removeWidget(w)
                w.deleteLater()

        row = QHBoxLayout()
        type_name, type_token = _TYPE_META.get(event["type"], (event["type"], "icon_muted"))

        badge = QLabel(type_name)
        badge.setStyleSheet(
            f"font-size: 11px; color: {theme_engine.get(type_token)};"
            f"border: 1px solid {theme_engine.get(type_token)};"
            f"border-radius: 3px; padding: 1px 5px;"
        )
        row.addWidget(badge)

        text = QLabel(str(event.get("text", "")))
        text.setWordWrap(True)
        text.setStyleSheet(
            f"font-size: 12px; color: {theme_engine.get('text_primary')};"
        )
        row.addWidget(text, 1)

        ts = QLabel(time.strftime("%H:%M:%S", time.localtime(event.get("ts", time.time()))))
        ts.setStyleSheet(f"font-size: 11px; color: {theme_engine.get('icon_muted')};")
        row.addWidget(ts)

        self._list_layout.insertLayout(self._list_layout.count() - 1, row)

    def _refresh(self):
        """重建全部事件（历史 + 新）"""
        # 清空（保留 stretch）
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

        if not self._events:
            empty = QLabel("暂无活动。AI 的工具调用、提案审批会实时出现在这里。")
            empty.setStyleSheet(
                f"color: {theme_engine.get('icon_muted')}; font-size: 12px; padding: 24px;"
            )
            empty.setAlignment(Qt.AlignCenter)
            self._list_layout.insertWidget(0, empty)
            return

        for event in self._events:
            self._render_event(event)

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                ActivityPage._clear_layout(item.layout())

    def _clear(self):
        self._events.clear()
        self._refresh()
