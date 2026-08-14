"""工具清单页 — 展示 GUI 已暴露给 AI 的可操控工具（工具卡片）。

阶段7：能力可视化。把 ToolRegistry 中的工具以卡片形式展示：
名称 / 描述 / 参数 Schema / 必填项，以及文件桥状态（AI 调用通道）。
"""

from __future__ import annotations

import json

from gui.core.utils.widget_utils import fit_button_width

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.core.event_bus import event_bus
from gui.core.messages import PAGE_ACTIVATED
from gui.core.theme_engine import theme_engine
from gui.core.tool_bridge import _SCHEMAS_FILE, _REQUESTS_DIR, _RESPONSES_DIR
from gui.core.tool_registry import tool_registry


class ToolsPage(QWidget):
    """AI 工具清单页"""

    def __init__(self):
        super().__init__()
        self._build_ui()
        self._refresh()

        # 阶段4：自查订阅页面激活消息
        self._subscribe_messages()

    # ─── 消息订阅（阶段4） ──────────────────────

    def _subscribe_messages(self):
        if getattr(self, "_events_subscribed", False):
            return
        self._events_subscribed = True
        event_bus.subscribe(PAGE_ACTIVATED, self._on_page_activated_msg)

    def _on_page_activated_msg(self, page_id=None):
        if page_id == "tools":
            self._refresh()

    # ─── UI ─────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        header = QLabel("AI 工具清单")
        header.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {theme_engine.get('text_primary')};"
        )
        layout.addWidget(header)

        hint = QLabel(
            "以下工具已通过文件通道暴露给 AI：AI 写请求文件到 "
            f"{_REQUESTS_DIR.name}/，GUI 执行后回写结果到 {_RESPONSES_DIR.name}/。"
            "破坏性变更（皮肤包）走提案审批，不会直接生效。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"font-size: 12px; color: {theme_engine.get('text_secondary')};"
        )
        layout.addWidget(hint)

        # 桥状态
        bridge = QLabel(
            f"能力清单：{_SCHEMAS_FILE.name}（共 {len(tool_registry.list())} 个工具）"
        )
        bridge.setStyleSheet(
            f"font-size: 12px; color: {theme_engine.get('icon_color')};"
            f"border: 1px dashed {theme_engine.get('border_color')};"
            f"border-radius: 4px; padding: 6px 8px;"
        )
        layout.addWidget(bridge)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("刷新")
        fit_button_width(refresh_btn)
        refresh_btn.clicked.connect(self._refresh)
        btn_row.addStretch()
        btn_row.addWidget(refresh_btn)
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
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._container)

    def _refresh(self):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for spec in tool_registry.list():
            card = self._make_card(spec)
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)

    def _make_card(self, spec) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background: {theme_engine.get('bg_primary')}; border-radius: 6px;"
            f"border: 1px solid {theme_engine.get('border_color')};"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(6)

        # 名称 + 必填徽标
        top = QHBoxLayout()
        name = QLabel(spec.name)
        name.setStyleSheet(
            f"font-family: Consolas, 'Courier New', monospace; font-size: 13px;"
            f"font-weight: bold; color: {theme_engine.get('accent_color')};"
        )
        top.addWidget(name)
        if spec.required:
            req = QLabel("必填: " + ", ".join(spec.required))
            req.setStyleSheet(
                f"font-size: 11px; color: {theme_engine.get('danger_color')};"
            )
            top.addWidget(req)
        top.addStretch()
        card_layout.addLayout(top)

        desc = QLabel(spec.description)
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 12px; color: {theme_engine.get('text_secondary')};"
        )
        card_layout.addWidget(desc)

        if spec.parameters:
            params_text = json.dumps(spec.parameters, ensure_ascii=False, indent=2)
            params = QLabel(params_text)
            params.setTextInteractionFlags(Qt.TextSelectableByMouse)
            params.setStyleSheet(
                f"font-family: Consolas, 'Courier New', monospace; font-size: 11px;"
                f"color: {theme_engine.get('text_primary')};"
                f"background: {theme_engine.get('bg_chat')}; border-radius: 4px; padding: 6px;"
            )
            card_layout.addWidget(params)

        return card
