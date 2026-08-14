"""UI 变更提案存储与审批 — AI 产出的 UI 变更先以提案落盘，用户审批后生效，可回退。

阶段6目标：在阶段5（皮肤包机制）之上加治理层：
- AI 产出变更 → 生成提案（pending），不直接生效
- 用户在提案页面审批：批准 → 生效并记录生效前快照；拒绝 → 丢弃
- 已生效提案可回退：恢复生效前主题状态（皮肤包保留安装，可再次选用）

提案目录约定（gui/resources/proposals/<id>.json）：
{
  "id", "kind"("skin"), "title", "description", "payload", "status",
  "created_at", "applied_at", "prior": {生效前 theme/selected_skin/selected_preset 快照}
}
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from gui.core.event_bus import event_bus
from gui.core.messages import AI_EVENT, THEME_CHANGED
from gui.core.skin_registry import skin_registry

# 提案状态
PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
APPLIED = "applied"
REVERTED = "reverted"

# 提案目录（gui/resources/proposals/）
_PROPOSALS_DIR = Path(__file__).resolve().parent.parent / "resources" / "proposals"


@dataclass
class ChangeProposal:
    """一条 UI 变更提案"""

    id: str
    kind: str                        # 当前支持 "skin"
    title: str
    description: str = ""
    payload: dict = field(default_factory=dict)
    status: str = PENDING            # pending/approved/rejected/applied/reverted
    created_at: str = ""
    applied_at: str | None = None
    prior: dict | None = None        # 生效前状态快照（回退用）

    @property
    def is_actionable(self) -> bool:
        """是否可审批（批准/拒绝）"""
        return self.status == PENDING

    @property
    def is_revertable(self) -> bool:
        """是否可回退"""
        return self.status == APPLIED

    @property
    def is_cleanable(self) -> bool:
        """是否可清理（rejected/reverted 记录）"""
        return self.status in (REJECTED, REVERTED)


class ProposalStore:
    """提案存储与审批（单例）。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        _PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)

    # ─── 创建 / 查询 ──────────────────────────────

    def create(
        self,
        kind: str,
        title: str,
        description: str = "",
        payload: dict | None = None,
    ) -> ChangeProposal:
        """创建一条待审批提案（AI 产出入口）"""
        proposal = ChangeProposal(
            id=uuid.uuid4().hex[:8],
            kind=kind,
            title=title,
            description=description,
            payload=payload or {},
            status=PENDING,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._save(proposal)
        return proposal

    def list(self, status: str | None = None) -> list[ChangeProposal]:
        """列出提案（按创建时间倒序，最新在前）"""
        items = [self._load(p) for p in sorted(_PROPOSALS_DIR.glob("*.json"), reverse=True)]
        if status:
            items = [i for i in items if i.status == status]
        return items

    def get(self, proposal_id: str) -> ChangeProposal | None:
        path = _PROPOSALS_DIR / f"{proposal_id}.json"
        if not path.is_file():
            return None
        return self._load(path)

    def delete(self, proposal_id: str) -> bool:
        """删除一条提案记录（仅允许清理态，或强制）"""
        path = _PROPOSALS_DIR / f"{proposal_id}.json"
        if path.is_file():
            path.unlink()
            return True
        return False

    # ─── 审批 / 回退 ──────────────────────────────

    def approve(self, proposal_id: str) -> ChangeProposal | None:
        """批准提案：生效变更并记录生效前快照"""
        proposal = self.get(proposal_id)
        if proposal is None or not proposal.is_actionable:
            return None
        if proposal.kind == "skin":
            from gui.core.config import AppConfig

            cfg = AppConfig()
            # 记录生效前状态快照（回退用）
            proposal.prior = {
                "theme": cfg.get_all_colors(),
                "selected_skin": cfg.get_selected_skin(),
                "selected_preset": cfg.get_selected_preset(),
            }
            payload = proposal.payload
            skin_registry.install(
                payload["skin_id"],
                payload["name"],
                payload.get("tokens", {}),
                description=payload.get("description", ""),
                mode=payload.get("mode"),
            )
            cfg.apply_skin(payload["skin_id"])
            proposal.status = APPLIED
            proposal.applied_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._save(proposal)
            event_bus.publish(THEME_CHANGED)
            # P0-2：实时事件推送（AI 操作可见）
            event_bus.publish(AI_EVENT, {
                "type": "proposal",
                "text": f"提案「{proposal.title}」已批准生效",
            })
        return proposal

    def reject(self, proposal_id: str) -> ChangeProposal | None:
        """拒绝提案：丢弃变更"""
        proposal = self.get(proposal_id)
        if proposal is None or not proposal.is_actionable:
            return None
        proposal.status = REJECTED
        self._save(proposal)
        # P0-2：实时事件推送
        event_bus.publish(AI_EVENT, {
            "type": "proposal",
            "text": f"提案「{proposal.title}」已拒绝",
        })
        return proposal

    def revert(self, proposal_id: str) -> ChangeProposal | None:
        """回退已生效提案：恢复生效前主题状态（皮肤包保留安装）"""
        proposal = self.get(proposal_id)
        if proposal is None or not proposal.is_revertable:
            return None
        if proposal.prior:
            from gui.core.config import AppConfig

            cfg = AppConfig()
            cfg.config["theme"] = dict(proposal.prior.get("theme", cfg.get_theme()))
            cfg.config["selected_skin"] = proposal.prior.get("selected_skin")
            cfg.config["selected_preset"] = proposal.prior.get("selected_preset")
            cfg.save()
            event_bus.publish(THEME_CHANGED)
        proposal.status = REVERTED
        proposal.applied_at = None
        self._save(proposal)
        # P0-2：实时事件推送
        event_bus.publish(AI_EVENT, {
            "type": "proposal",
            "text": f"提案「{proposal.title}」已回退",
        })
        return proposal

    # ─── 持久化 ───────────────────────────────────

    def _path(self, proposal: ChangeProposal) -> Path:
        return _PROPOSALS_DIR / f"{proposal.id}.json"

    def _save(self, proposal: ChangeProposal) -> None:
        self._path(proposal).write_text(
            json.dumps(asdict(proposal), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _load(self, path: Path) -> ChangeProposal:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ChangeProposal(**{k: data.get(k) for k in ChangeProposal.__dataclass_fields__})


# 模块级单例
proposal_store = ProposalStore()
