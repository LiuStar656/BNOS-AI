"""图标注册中心 — 语义图标名 → 渲染字符 的统一收口。

阶段2目标：把散落在各组件里的裸 unicode 符号（✕ □ ▶ ⚠ 等）收口到注册中心。
组件只按语义名取图标（icons.get('close')），不写裸字符。

设计要点：
- _ICON_DEFAULTS：语义名 → 字符（默认值 = 原硬编码字符，视觉不变）
- 与 codicon 字体图标体系打通：get() 先查注册表，再回退 codicon CODEPOINTS
- register()/unregister()/set_many()：运行时注册/覆盖，为 AI 产出替换图标铺路
- get_font(name)：统一字体出口（codicon 图标返回 codicon 字体，普通符号返回默认字体）
"""

from __future__ import annotations

from gui.resources.icons.codicon import CODEPOINTS, codicon

# 语义图标默认值（= 原硬编码字符，视觉不变）
_ICON_DEFAULTS: dict[str, str] = {
    # 标题栏窗口控制
    "title_min": "─",        # 最小化
    "title_max": "□",        # 最大化
    "title_restore": "❐",    # 还原
    "title_close": "✕",      # 关闭
    # 面板通用
    "panel_close": "✕",
    "panel_back": "←",
    # 节点页
    "node_start": "▶",       # 启动引擎
    "node_stop": "■",        # 停止引擎
    # 引擎/节点状态
    "state_online": "●",
    "state_starting": "●",
    "state_error": "●",
    "state_offline": "○",
    # 启动闪屏节点状态
    "state_wait": "○",       # 等待中
    "state_ready": "●",      # 已就绪
    "state_booting": "◌",    # 启动中
    # 状态/提示
    "warn": "⚠",             # 警告
    "dropdown": "▾",         # 下拉箭头
    "arrow": "→",            # 右箭头（预览）
}


class IconRegistry:
    """图标注册中心（单例）。

    - get(name, default): 统一取图入口（自定义覆盖 → 默认表 → codicon → 调用方默认）
    - register/unregister/set_many: 运行时注册与覆盖（AI 产出替换图标的入口）
    - get_font(name, size): 图标字体出口（codicon 名返回 codicon 字体，否则默认字体）
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._overrides: dict[str, str] = {}
        self._initialized = True

    # ─── 图标访问 ──────────────────────────────

    @property
    def all(self) -> dict[str, str]:
        """合并后的完整图标字典（覆盖优先）"""
        merged = dict(_ICON_DEFAULTS)
        merged.update(self._overrides)
        return merged

    def get(self, name: str, default: str | None = None) -> str:
        """统一取图入口：自定义覆盖 → 默认表 → codicon 码表 → 调用方默认值"""
        value = self._overrides.get(name)
        if not value:
            value = _ICON_DEFAULTS.get(name)
        if value:
            return value
        if name in CODEPOINTS:
            return chr(CODEPOINTS[name])
        return default or "?"

    def get_font(self, name: str, size: int = 14):
        """图标字体出口：codicon 图标返回 codicon 字体，普通符号返回默认字体（None）"""
        if name in _ICON_DEFAULTS or name in self._overrides:
            return None
        if name in CODEPOINTS:
            return codicon.get_font(size)
        return None

    # ─── 运行时注册 / 覆盖（AI 产出替换入口） ──

    def register(self, name: str, char: str) -> None:
        """注册或覆盖一个图标"""
        self._overrides[name] = char

    def unregister(self, name: str) -> None:
        """移除自定义覆盖，回落到默认/码表"""
        self._overrides.pop(name, None)

    def set_many(self, mapping: dict[str, str]) -> None:
        """批量注册/覆盖"""
        self._overrides.update(mapping)

    def reset(self) -> None:
        """清空全部自定义覆盖"""
        self._overrides.clear()


# 模块级单例
icons = IconRegistry()
