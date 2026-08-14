"""流程库页 — 展示 workflow 及其双引擎分数（P1-1）。

每张卡片：流程名/描述/步骤数、最终分 = 多巴胺 × 用进废退、
多巴胺 Q 值、用进废退权重、调用/正负反馈计数；用户可点 👍/👎 给出外部评价
（多巴胺显性反馈，RPE 校准更新 Q 值）。
"""

from __future__ import annotations

import json

from gui.core.utils.widget_utils import fit_button_width

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.core.event_bus import event_bus
from gui.core.messages import PAGE_ACTIVATED
from gui.core.theme_engine import theme_engine
from gui.core.workflow_store import workflow_store


class WorkflowPage(QWidget):
    """流程库页（双引擎可视化）"""

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
        if page_id == "workflows":
            self._refresh()

    # ─── UI ─────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        header = QLabel("流程库（双引擎）")
        header.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {theme_engine.get('text_primary')};"
        )
        layout.addWidget(header)

        hint = QLabel(
            "每个流程由有序工具步骤组成。最终分 = 多巴胺 × 用进废退："
            "多巴胺（显性反馈）由你的 👍/👎 评价校准，用进废退（隐性反馈）按调用频次修剪。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"font-size: 12px; color: {theme_engine.get('text_secondary')};"
        )
        layout.addWidget(hint)

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

        flows = workflow_store.list()
        if not flows:
            empty = QLabel("暂无流程。")
            empty.setStyleSheet(
                f"color: {theme_engine.get('icon_muted')}; font-size: 12px; padding: 24px;"
            )
            empty.setAlignment(Qt.AlignCenter)
            self._list_layout.insertWidget(0, empty)
            return

        for wf in flows:
            card = self._make_card(wf)
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)

    def _make_card(self, wf) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background: {theme_engine.get('bg_primary')}; border-radius: 6px;"
            f"border: 1px solid {theme_engine.get('border_color')};"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # 首行：名称 + 最终分 + 步骤数
        top = QHBoxLayout()
        name = QLabel(wf.name)
        name.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {theme_engine.get('text_primary')};"
        )
        top.addWidget(name)

        score = QLabel(f"最终分 {wf.final_score}")
        score.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {theme_engine.get('accent_color')};"
        )
        top.addWidget(score)

        steps = QLabel(f"{len(wf.steps)} 步")
        steps.setStyleSheet(
            f"font-size: 11px; color: {theme_engine.get('icon_muted')};"
            f"border: 1px solid {theme_engine.get('border_color')}; border-radius: 3px; padding: 1px 6px;"
        )
        top.addWidget(steps)
        top.addStretch()
        layout.addLayout(top)

        desc = QLabel(wf.description)
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 12px; color: {theme_engine.get('text_secondary')};"
        )
        layout.addWidget(desc)

        # 双引擎分数条
        layout.addWidget(self._score_bar(
            "多巴胺（显性反馈）", wf.dopamine, "accent_color"))
        layout.addWidget(self._score_bar(
            "用进废退（隐性反馈）", wf.use_score, "status_ok"))

        # 统计 + 评价按钮
        bottom = QHBoxLayout()
        stats = QLabel(
            f"调用 {wf.calls} 次　👍 {wf.positive}　👎 {wf.negative}"
        )
        stats.setStyleSheet(
            f"font-size: 11px; color: {theme_engine.get('icon_muted')};"
        )
        bottom.addWidget(stats)
        bottom.addStretch()

        rate_text = QLabel("我的评价：")
        rate_text.setStyleSheet(
            f"font-size: 11px; color: {theme_engine.get('icon_muted')};"
        )
        bottom.addWidget(rate_text)

        good_btn = QPushButton("👍")
        good_btn.setFixedSize(30, 24)
        good_btn.setStyleSheet(self._btn_style("status_ok"))
        good_btn.clicked.connect(lambda _=False, fid=wf.id: self._rate(fid, True))
        bottom.addWidget(good_btn)

        bad_btn = QPushButton("👎")
        bad_btn.setFixedSize(30, 24)
        bad_btn.setStyleSheet(self._btn_style("danger_color"))
        bad_btn.clicked.connect(lambda _=False, fid=wf.id: self._rate(fid, False))
        bottom.addWidget(bad_btn)

        layout.addLayout(bottom)
        return card

    def _score_bar(self, label: str, value: float, token: str) -> QWidget:
        row = QHBoxLayout()
        text = QLabel(label)
        text.setStyleSheet(
            f"font-size: 11px; color: {theme_engine.get('text_secondary')};"
        )
        text.setFixedWidth(150)
        row.addWidget(text)

        bar = QProgressBar()
        bar.setFixedHeight(8)
        bar.setRange(0, 100)
        bar.setValue(int(value * 100))
        bar.setTextVisible(False)
        bar.setStyleSheet(
            f"QProgressBar {{ background: {theme_engine.get('bg_chat')};"
            f"border: none; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {theme_engine.get(token)};"
            f"border-radius: 4px; }}"
        )
        row.addWidget(bar, 1)

        num = QLabel(f"{value:.2f}")
        num.setStyleSheet(
            f"font-size: 11px; color: {theme_engine.get('icon_muted')};"
        )
        num.setFixedWidth(38)
        row.addWidget(num)

        wrap = QWidget()
        wrap.setLayout(row)
        return wrap

    @staticmethod
    def _btn_style(token: str) -> str:
        return (
            f"QPushButton {{ background: {theme_engine.get('bg_chat')};"
            f"border: 1px solid {theme_engine.get('border_color')};"
            f"border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {theme_engine.get(token)}; }}"
        )

    # ─── 用户评价（多巴胺显性反馈） ─────────────

    def _rate(self, flow_id: str, positive: bool):
        workflow_store.rate(flow_id, positive)
        self._refresh()
