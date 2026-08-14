"""布局包注册中心 — 布局包落盘为目录，与内置 default 平级可切换。

数据驱动 UI 布局动态调整方案（Phase 1）：
- 内置 default 代码内注册（不落盘，保证任何环境可用）
- 用户/AI 产出布局落盘为 gui/resources/layouts/<layout_id>/layout.json
- install() 是 AI 产出落盘入口：Schema 校验 → 落盘 → reload → 立即可用
- 同名内置优先（与皮肤包/主题预设语义一致）

目录约定：
gui/resources/layouts/<layout_id>/layout.json   # LayoutSpec 完整 JSON（含 id/name/layout）
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from gui.core.layout_spec import LayoutSpec, safe_id

# 布局包根目录（gui/resources/layouts/）
_LAYOUTS_DIR = Path(__file__).resolve().parent.parent / "resources" / "layouts"


@dataclass
class LayoutPack:
    """一个已加载的布局包"""

    id: str
    name: str
    description: str = ""
    version: str = "1.0"
    spec: LayoutSpec | None = None
    path: Path | None = None
    builtin: bool = False   # True = 代码内注册（不落盘，禁止移除/覆盖）


class LayoutRegistry:
    """布局包注册中心（单例）— 扫描 / 加载 / 安装 / 移除布局包。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._layouts: dict[str, LayoutPack] = {}
        self._initialized = True
        self.reload()

    # ─── 扫描 / 加载 ──────────────────────────────

    @property
    def layouts_dir(self) -> Path:
        return _LAYOUTS_DIR

    def reload(self) -> None:
        """重载布局清单：内置 default + 扫描落盘目录"""
        self._layouts.clear()
        # 内置 default（代码内注册，不落盘）
        default_spec = LayoutSpec.default()
        self._layouts["default"] = LayoutPack(
            id=default_spec.id,
            name=default_spec.name,
            description=default_spec.description,
            version=default_spec.version,
            spec=default_spec,
            builtin=True,
        )
        # 扫描落盘布局
        if not _LAYOUTS_DIR.is_dir():
            return
        for d in sorted(_LAYOUTS_DIR.iterdir()):
            if not d.is_dir():
                continue
            pack = self._load_layout(d)
            if pack is not None:
                self._layouts[pack.id] = pack  # 同名内置优先（已注册的内置不会被覆盖）

    def _load_layout(self, d: Path) -> LayoutPack | None:
        """加载一个布局目录（容错：缺文件 / 坏 JSON / 非法 spec 跳过）"""
        try:
            data = json.loads((d / "layout.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        try:
            spec = LayoutSpec.from_dict(data)
        except Exception:
            return None
        if not spec.is_valid():
            return None
        return LayoutPack(
            id=spec.id,
            name=spec.name,
            description=spec.description,
            version=spec.version,
            spec=spec,
            path=d,
        )

    # ─── 查询 ─────────────────────────────────────

    def list_layouts(self) -> list[LayoutPack]:
        return list(self._layouts.values())

    def get(self, layout_id: str) -> LayoutPack | None:
        return self._layouts.get(layout_id)

    def has(self, layout_id: str) -> bool:
        return layout_id in self._layouts

    def get_spec(self, layout_id: str) -> LayoutSpec | None:
        pack = self._layouts.get(layout_id)
        return pack.spec if pack else None

    # ─── 安装 / 移除（AI 产出入口） ───────────────

    def install(
        self,
        layout_id: str,
        name: str,
        spec_dict: dict,
        *,
        description: str = "",
        version: str = "1.0",
    ) -> LayoutSpec:
        """安装布局包：Schema 校验 → 落盘 → reload。

        安全设计（同 SkinRegistry）：非法 id / 校验失败抛 ValueError，不落盘。
        """
        if not safe_id(layout_id):
            raise ValueError(f"布局 id 含非法字符: {layout_id!r}")
        if layout_id == "default":
            raise ValueError("default 为内置布局，禁止覆盖")
        spec_dict = dict(spec_dict or {})
        spec_dict["id"] = layout_id
        spec_dict["name"] = name
        spec_dict.setdefault("description", description)
        spec_dict.setdefault("version", version)
        spec = LayoutSpec.from_dict(spec_dict)
        errs = spec.errors()
        if errs:
            raise ValueError("布局校验失败: " + "; ".join(errs))
        d = _LAYOUTS_DIR / layout_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "layout.json").write_text(
            json.dumps(spec_dict, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.reload()
        return spec

    def remove(self, layout_id: str) -> bool:
        """移除布局包（内置 default 禁止移除）"""
        pack = self._layouts.get(layout_id)
        if pack is None or pack.builtin:
            return False
        if pack.path and pack.path.is_dir():
            shutil.rmtree(pack.path)
        self.reload()
        return True


# 模块级单例
layout_registry = LayoutRegistry()
