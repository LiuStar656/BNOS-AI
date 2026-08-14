"""皮肤包注册中心 — AI 产出落地为皮肤包目录，与内置预设平级。

阶段5目标：AI 产出（或用户制作）的皮肤落盘为皮肤包目录，注册中心扫描加载后
与内置主题预设平级出现在主题下拉框中。

皮肤包目录约定（gui/resources/themes/<skin_id>/）：
- metadata.json: {"name": 显示名, "description": 描述, "version": "1.0", "mode": "light"|"dark"}
- tokens.json:   {token名: 颜色值, ...}（覆盖/新增语义 token 的增量集合）

install() 是 AI 产出落盘的入口：AI 生成 tokens → 落盘 → reload 后立即生效。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# 皮肤包根目录（gui/resources/themes/）
_THEMES_DIR = Path(__file__).resolve().parent.parent / "resources" / "themes"


@dataclass
class SkinPack:
    """一个已加载的皮肤包"""

    id: str                      # 目录名（唯一标识）
    name: str                    # 显示名
    description: str = ""
    version: str = "1.0"
    mode: str | None = None      # light/dark，可选
    tokens: dict[str, str] = field(default_factory=dict)  # token 覆盖增量
    path: Path | None = None


class SkinRegistry:
    """皮肤包注册中心（单例）— 扫描/加载/安装皮肤包。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._skins: dict[str, SkinPack] = {}
        self._initialized = True
        self.reload()

    # ─── 扫描 / 加载 ──────────────────────────────

    @property
    def skins_dir(self) -> Path:
        return _THEMES_DIR

    def reload(self) -> None:
        """重新扫描皮肤包目录，加载全部皮肤包"""
        self._skins.clear()
        if not _THEMES_DIR.is_dir():
            return
        for child in sorted(_THEMES_DIR.iterdir()):
            if not child.is_dir():
                continue
            skin = self._load_skin(child)
            if skin is not None:
                self._skins[skin.id] = skin

    def _load_skin(self, directory: Path) -> SkinPack | None:
        """从目录加载一个皮肤包（容错：缺文件/坏 JSON 时跳过）"""
        meta_file = directory / "metadata.json"
        tokens_file = directory / "tokens.json"
        if not meta_file.is_file():
            return None
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            tokens = json.loads(tokens_file.read_text(encoding="utf-8")) if tokens_file.is_file() else {}
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(meta, dict) or not isinstance(tokens, dict):
            return None
        return SkinPack(
            id=directory.name,
            name=str(meta.get("name") or directory.name),
            description=str(meta.get("description") or ""),
            version=str(meta.get("version") or "1.0"),
            mode=str(meta["mode"]) if meta.get("mode") else None,
            tokens=tokens,
            path=directory,
        )

    # ─── 查询 ─────────────────────────────────────

    def list_skins(self) -> list[SkinPack]:
        """按目录名排序的全部皮肤包"""
        return [self._skins[k] for k in sorted(self._skins)]

    def get(self, skin_id: str) -> SkinPack | None:
        return self._skins.get(skin_id)

    def has(self, skin_id: str) -> bool:
        return skin_id in self._skins

    # ─── 安装 / 移除（AI 产出落盘入口） ─────────

    def install(
        self,
        skin_id: str,
        display_name: str,
        tokens: dict[str, str],
        *,
        description: str = "",
        mode: str | None = None,
        version: str = "1.0",
    ) -> SkinPack:
        """落盘安装一个皮肤包并立即注册（AI 产出入口）。

        - skin_id 仅允许安全字符（字母/数字/_/-）
        - 覆盖同名皮肤包（AI 迭代更新）
        """
        if not all(c.isalnum() or c in "_-" for c in skin_id):
            raise ValueError(f"非法皮肤包 id: {skin_id!r}")
        directory = _THEMES_DIR / skin_id
        directory.mkdir(parents=True, exist_ok=True)
        meta = {"name": display_name, "description": description, "version": version}
        if mode:
            meta["mode"] = mode
        (directory / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (directory / "tokens.json").write_text(
            json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.reload()
        skin = self.get(skin_id)
        assert skin is not None, "皮肤包安装后应可加载"
        return skin

    def remove(self, skin_id: str) -> bool:
        """移除一个皮肤包（删除目录）"""
        skin = self._skins.get(skin_id)
        if skin is None or skin.path is None:
            return False
        import shutil

        shutil.rmtree(skin.path, ignore_errors=True)
        self.reload()
        return True


# 模块级单例
skin_registry = SkinRegistry()
