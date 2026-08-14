"""LayoutSpec — 主窗口布局的 Schema 化描述与校验。

数据驱动 UI 布局动态调整方案（Phase 0-3）：
- 布局（导航位置/方向/宽度/页面显隐与顺序/窗口默认尺寸）描述为 JSON，可落盘/切换/回退
- 与换肤正交：颜色/大小走 ThemeEngine token，布局结构走 LayoutSpec

布局包目录约定（gui/resources/layouts/<layout_id>/layout.json）：
{
  "id", "name", "description", "version",
  "layout": {
    "nav_position": "left"|"top",
    "nav_width": 56, "nav_height": 48,
    "nav_mode": "icon"|"text"|"icon_text",
    "nav_visible": true,
    "pages": [{"id": "chat", "visible": true}, ...],   // 缺省=注册顺序全显示
    "window_default": {"width": 1200, "height": 800}
  }
}
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 合法枚举
NAV_POSITIONS = ("left", "top")
NAV_MODES = ("icon", "text", "icon_text")

# 数值边界（过度设计防护：非法值拒绝而非静默钳制）
NAV_WIDTH_MIN, NAV_WIDTH_MAX = 40, 120
NAV_HEIGHT_MIN, NAV_HEIGHT_MAX = 32, 96
WINDOW_WIDTH_MIN, WINDOW_HEIGHT_MIN = 800, 560


def safe_id(s: str) -> bool:
    """布局 id 安全字符校验（同 skin 目录名约定）"""
    return bool(s) and all(c.isalnum() or c in "_-" for c in s)


@dataclass
class LayoutSpec:
    """一份布局描述 — 对 main_window 导航容器的完整约束。"""

    id: str
    name: str
    description: str = ""
    version: str = "1.0"
    nav_position: str = "left"          # "left" | "top"
    nav_width: int = 56                 # 左栏宽度（nav_position=left 生效）
    nav_height: int = 48                # 顶栏高度（nav_position=top 生效）
    nav_mode: str = "icon"              # "icon" | "text" | "icon_text"
    nav_visible: bool = True            # 导航栏整体显隐
    pages: list[dict] = field(default_factory=list)      # [{"id", "visible"}, ...]，缺省=全显示
    window_default: dict = field(default_factory=lambda: {"width": 1200, "height": 800})

    # ─── 构造 ──────────────────────────────────────

    @classmethod
    def default(cls) -> "LayoutSpec":
        """内置默认布局 — 等价当前硬编码（左侧竖排图标导航）"""
        return cls(id="default", name="默认侧边栏", description="左侧竖排图标导航（默认）")

    @classmethod
    def from_dict(cls, data: dict) -> "LayoutSpec":
        """从布局包 JSON dict 解析（宽容读缺省值，未知键忽略）"""
        layout = data.get("layout", {})
        pages = layout.get("pages")
        spec = cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            version=str(data.get("version", "1.0")),
            nav_position=str(layout.get("nav_position", "left")),
            nav_width=int(layout.get("nav_width", 56)),
            nav_height=int(layout.get("nav_height", 48)),
            nav_mode=str(layout.get("nav_mode", "icon")),
            nav_visible=bool(layout.get("nav_visible", True)),
            pages=[{"id": str(p["id"]), "visible": bool(p.get("visible", True))} for p in pages] if pages else [],
            window_default=dict(layout.get("window_default", {"width": 1200, "height": 800})),
        )
        return spec

    def to_dict(self) -> dict:
        """序列化为布局包 JSON（含 layout 外层）"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "layout": {
                "nav_position": self.nav_position,
                "nav_width": self.nav_width,
                "nav_height": self.nav_height,
                "nav_mode": self.nav_mode,
                "nav_visible": self.nav_visible,
                "pages": [dict(p) for p in self.pages],
                "window_default": dict(self.window_default),
            },
        }

    # ─── 校验 ──────────────────────────────────────

    def errors(self) -> list[str]:
        """校验错误清单（空列表 = 合法）。页面引用以注册中心为权威源。"""
        errs = []
        if not safe_id(self.id):
            errs.append(f"非法 id: {self.id!r}")
        if not self.name:
            errs.append("缺少显示名 name")
        if self.nav_position not in NAV_POSITIONS:
            errs.append(f"nav_position 必须为 {'/'.join(NAV_POSITIONS)}，当前 {self.nav_position!r}")
        if not (NAV_WIDTH_MIN <= self.nav_width <= NAV_WIDTH_MAX):
            errs.append(f"nav_width 超出边界 [{NAV_WIDTH_MIN}, {NAV_WIDTH_MAX}]：{self.nav_width}")
        if not (NAV_HEIGHT_MIN <= self.nav_height <= NAV_HEIGHT_MAX):
            errs.append(f"nav_height 超出边界 [{NAV_HEIGHT_MIN}, {NAV_HEIGHT_MAX}]：{self.nav_height}")
        if self.nav_mode not in NAV_MODES:
            errs.append(f"nav_mode 必须为 {'/'.join(NAV_MODES)}，当前 {self.nav_mode!r}")
        if self.pages:
            from gui.core.ui_registry import ui_registry  # 延迟导入避免初始化时序耦合

            known = set(ui_registry.page_ids())
            seen = set()
            for p in self.pages:
                if p["id"] not in known:
                    errs.append(f"pages 引用未知页面 id: {p['id']!r}")
                if p["id"] in seen:
                    errs.append(f"pages 重复引用页面 id: {p['id']!r}")
                seen.add(p["id"])
        wd = self.window_default
        w = wd.get("width")
        h = wd.get("height")
        if not isinstance(w, int) or w < WINDOW_WIDTH_MIN:
            errs.append(f"window_default.width 非法: {w!r}")
        if not isinstance(h, int) or h < WINDOW_HEIGHT_MIN:
            errs.append(f"window_default.height 非法: {h!r}")
        return errs

    def is_valid(self) -> bool:
        return not self.errors()

    # ─── 页面视图 ──────────────────────────────────

    def page_filter(self) -> list[str] | None:
        """过滤/排序后的页面 id 列表；None = 注册顺序全显示。

        注册中心（ui_registry）仍是全量权威源，本视图仅做显隐与排序。
        """
        if not self.pages:
            return None
        return [p["id"] for p in self.pages if p.get("visible", True)]
