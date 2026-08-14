"""UI 插槽注册中心 — 页面/面板按插槽名注册，主窗口从注册中心组装。

阶段3目标（借鉴 DeepSeek Harness 的 Slot 插槽系统）：
- 组件声明插槽（register），主窗口消费插槽（resolve），页面装配不再硬编码在 main_window
- 冲突即设计：同一插槽重复注册默认抛 SlotConflictError，显式 replace=True 才允许覆盖
- 工厂懒加载：注册的是工厂，resolve 时才实例化（为动态插拔/皮肤包铺路）

插槽命名：页面插槽 `page.<id>`；meta 携带页面元信息（icon/page_id/title），
Sidebar 与 MainWindow 均从注册中心读取，保持单一数据源。
"""

from __future__ import annotations

from typing import Callable


class SlotConflictError(Exception):
    """插槽冲突 — 同一插槽被重复注册（冲突即设计）"""


class UiRegistry:
    """UI 插槽注册中心（单例）。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._slots: dict[str, dict] = {}
        self._initialized = True
        self._register_builtin()

    # ─── 内置页面插槽注册（懒加载工厂） ─────────

    def _register_builtin(self):
        from gui.pages.chat_page import ChatPage
        from gui.pages.activity_page import ActivityPage
        from gui.pages.live2d_page import Live2DPage
        from gui.pages.location_page import LocationPage
        from gui.pages.mcp_page import MCPPage
        from gui.pages.proposals_page import ProposalsPage
        from gui.pages.tools_page import ToolsPage
        from gui.pages.workflow_page import WorkflowPage
        from gui.pages.dsh_manage_page import DshManagePage
        from gui.widgets.knowledge_panel import KnowledgePanel

        # 注意：注册顺序即侧边栏/页面切换顺序；chat 排最前 → 启动默认页
        self.register("page.chat", ChatPage, meta={"icon": "chat", "page_id": "chat", "title": "聊天"})
        self.register("page.activity", ActivityPage, meta={"icon": "pulse", "page_id": "activity", "title": "AI 活动"})
        self.register("page.live2d", Live2DPage, meta={"icon": "live2d", "page_id": "live2d", "title": "Live2D"})
        self.register("page.location", LocationPage, meta={"icon": "map", "page_id": "location", "title": "地图"})
        self.register("page.mcp", MCPPage, meta={"icon": "mcp", "page_id": "mcp", "title": "MCP 管理"})
        self.register("page.knowledge", KnowledgePanel, meta={"icon": "book", "page_id": "knowledge", "title": "记忆库"})
        self.register("page.proposals", ProposalsPage, meta={"icon": "git-pull-request", "page_id": "proposals", "title": "提案"})
        self.register("page.tools", ToolsPage, meta={"icon": "beaker", "page_id": "tools", "title": "AI 工具"})
        self.register("page.workflows", WorkflowPage, meta={"icon": "hubot", "page_id": "workflows", "title": "流程"})
        self.register("page.dsh_manage", DshManagePage, meta={"icon": "settings", "page_id": "dsh_manage", "title": "DSH 管理"})

    # ─── 注册 / 覆盖 ────────────────────────────

    def register(self, slot: str, factory: Callable, *, replace: bool = False, meta: dict | None = None) -> None:
        """注册插槽工厂。

        重复注册同一插槽默认抛 SlotConflictError（冲突即设计）；
        显式 replace=True 允许覆盖（AI 产出替换既有页面的入口）。
        """
        if slot in self._slots and not replace:
            prev = self._slots[slot]["meta"].get("title") or self._slots[slot]["meta"].get("page_id") or "?"
            raise SlotConflictError(
                f"UI 插槽 '{slot}' 已注册（{prev}），若要覆盖需显式 replace=True"
            )
        self._slots[slot] = {"factory": factory, "meta": meta or {}}

    def unregister(self, slot: str) -> None:
        """移除插槽"""
        self._slots.pop(slot, None)

    # ─── 查询 / 消费 ────────────────────────────

    def has(self, slot: str) -> bool:
        return slot in self._slots

    def resolve(self, slot: str):
        """实例化插槽页面（工厂懒加载，每次调用新建实例）"""
        entry = self._slots.get(slot)
        if entry is None:
            raise KeyError(f"UI 插槽 '{slot}' 未注册")
        return entry["factory"]()

    def meta(self, slot: str) -> dict:
        return self._slots.get(slot, {}).get("meta", {})

    def page_slots(self) -> list[str]:
        """按注册顺序返回全部页面插槽名"""
        return [s for s in self._slots if s.startswith("page.")]

    def page_ids(self) -> list[str]:
        """按注册顺序返回页面 id 列表"""
        return [self._slots[s]["meta"].get("page_id", s.removeprefix("page.")) for s in self.page_slots()]

    def tabs(self) -> list[tuple[str, str, str]]:
        """侧边栏标签 [(icon, page_id, title), ...]（按注册顺序）"""
        return [
            (self._slots[s]["meta"]["icon"], self._slots[s]["meta"]["page_id"], self._slots[s]["meta"]["title"])
            for s in self.page_slots()
        ]


# 模块级单例
ui_registry = UiRegistry()
