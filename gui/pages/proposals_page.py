"""提案页面 — AI 产出的 UI 变更以卡片展示，用户审批后生效，可回退。

阶段6：变更治理层。AI 产出的变更（当前支持皮肤包）先落盘为 pending 提案，
用户在卡片上批准/拒绝；已生效提案可回退到生效前状态。
"""

from __future__ import annotations

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
from gui.core.proposal_store import (
    APPLIED,
    ChangeProposal,
    PENDING,
    REJECTED,
    REVERTED,
    proposal_store,
)
from gui.core.theme_engine import theme_engine


# 状态 → (显示名, token)
_STATUS_META = {
    PENDING: ("待审批", "status_warn"),
    APPLIED: ("已生效", "status_ok"),
    REJECTED: ("已拒绝", "icon_muted"),
    REVERTED: ("已回退", "icon_muted"),
}

# 类型 → 徽标文字
_KIND_LABELS = {
    "skin": "皮肤包",
    "layout": "布局",
}


class ProposalsPage(QWidget):
    """UI 变更提案卡片页"""

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
        if page_id == "proposals":
            self._refresh()

    # ─── UI ─────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        header = QLabel("UI 变更提案")
        header.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {theme_engine.get('text_primary')};"
        )
        layout.addWidget(header)

        hint = QLabel("AI 产出的 UI 变更在此等待审批：批准后生效，已生效项可一键回退。")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"font-size: 12px; color: {theme_engine.get('text_secondary')};"
        )
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("刷新列表")
        fit_button_width(refresh_btn)
        refresh_btn.clicked.connect(self._refresh)
        btn_row.addStretch()
        btn_row.addWidget(refresh_btn)
        layout.addLayout(btn_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setStyleSheet(
            f"background: transparent; border: none;"
        )
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
        """重建提案卡片列表"""
        # 清空旧卡片（保留 stretch）
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        proposals = proposal_store.list()
        if not proposals:
            empty = QLabel("暂无提案。AI 产出的 UI 变更会以提案形式出现在这里。")
            empty.setStyleSheet(
                f"color: {theme_engine.get('icon_muted')}; font-size: 12px; padding: 24px;"
            )
            empty.setAlignment(Qt.AlignCenter)
            self._list_layout.insertWidget(0, empty)
            return

        for proposal in proposals:
            card = self._make_card(proposal)
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)

    def _make_card(self, proposal: ChangeProposal) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background: {theme_engine.get('bg_primary')}; border-radius: 6px;"
            f"border: 1px solid {theme_engine.get('border_color')};"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(6)

        # 首行：标题 + 类型徽标 + 状态
        top = QHBoxLayout()
        title = QLabel(proposal.title)
        title.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {theme_engine.get('text_primary')};"
        )
        top.addWidget(title)
        top.addStretch()

        kind_label = QLabel(_KIND_LABELS.get(proposal.kind, proposal.kind))
        kind_label.setStyleSheet(
            f"font-size: 11px; color: {theme_engine.get('accent_color')};"
            f"border: 1px solid {theme_engine.get('accent_color')};"
            f"border-radius: 3px; padding: 1px 6px;"
        )
        top.addWidget(kind_label)

        status_name, status_token = _STATUS_META.get(
            proposal.status, (proposal.status, "icon_muted")
        )
        status_label = QLabel(status_name)
        status_label.setStyleSheet(
            f"font-size: 11px; color: {theme_engine.get(status_token)};"
        )
        top.addWidget(status_label)
        card_layout.addLayout(top)

        # 描述 + 时间
        desc = QLabel(proposal.description or "(无描述)")
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 12px; color: {theme_engine.get('text_secondary')};"
        )
        card_layout.addWidget(desc)

        meta = QLabel(f"创建于 {proposal.created_at}　ID: {proposal.id}")
        meta.setStyleSheet(f"font-size: 11px; color: {theme_engine.get('icon_muted')};")
        card_layout.addWidget(meta)

        # 操作按钮
        actions = QHBoxLayout()
        actions.addStretch()

        if proposal.is_actionable:
            approve_btn = QPushButton("批准")
            fit_button_width(approve_btn, padding=28)
            approve_btn.setStyleSheet(
                f"QPushButton {{ background: {theme_engine.get('accent_color')}; color: white;"
                f"border: none; border-radius: 4px; padding: 4px 0; }}"
                f"QPushButton:hover {{ background: {theme_engine.get('accent_hover')}; }}"
            )
            approve_btn.clicked.connect(lambda _=False, pid=proposal.id: self._approve(pid))
            actions.addWidget(approve_btn)

            reject_btn = QPushButton("拒绝")
            fit_button_width(reject_btn, padding=28)
            reject_btn.setStyleSheet(
                f"QPushButton {{ background: {theme_engine.get('bg_chat')}; color: {theme_engine.get('text_primary')};"
                f"border: 1px solid {theme_engine.get('border_color')}; border-radius: 4px; padding: 4px 0; }}"
                f"QPushButton:hover {{ background: {theme_engine.get('danger_color')}; color: white; }}"
            )
            reject_btn.clicked.connect(lambda _=False, pid=proposal.id: self._reject(pid))
            actions.addWidget(reject_btn)
        elif proposal.is_revertable:
            revert_btn = QPushButton("回退")
            fit_button_width(revert_btn, padding=28)
            revert_btn.setStyleSheet(
                f"QPushButton {{ background: {theme_engine.get('bg_chat')}; color: {theme_engine.get('text_primary')};"
                f"border: 1px solid {theme_engine.get('border_color')}; border-radius: 4px; padding: 4px 0; }}"
                f"QPushButton:hover {{ background: {theme_engine.get('status_warn')}; color: white; }}"
            )
            revert_btn.clicked.connect(lambda _=False, pid=proposal.id: self._revert(pid))
            actions.addWidget(revert_btn)
        elif proposal.is_cleanable:
            clean_btn = QPushButton("删除记录")
            fit_button_width(clean_btn, padding=28)
            clean_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {theme_engine.get('icon_muted')};"
                f"border: none; border-radius: 4px; padding: 4px 0; }}"
                f"QPushButton:hover {{ color: {theme_engine.get('danger_color')}; }}"
            )
            clean_btn.clicked.connect(lambda _=False, pid=proposal.id: self._clean(pid))
            actions.addWidget(clean_btn)

        card_layout.addLayout(actions)
        return card

    # ─── 操作 ───────────────────────────────────

    def _approve(self, proposal_id: str):
        proposal_store.approve(proposal_id)
        self._refresh()

    def _reject(self, proposal_id: str):
        proposal_store.reject(proposal_id)
        self._refresh()

    def _revert(self, proposal_id: str):
        proposal_store.revert(proposal_id)
        self._refresh()

    def _clean(self, proposal_id: str):
        proposal_store.delete(proposal_id)
        self._refresh()
