"""
GUI 配置管理 — 从 BNOS AppConfig 适配，专注于主题/颜色配置持久化

使用单例模式确保全局只有一个配置实例。
"""

from __future__ import annotations

import json
from pathlib import Path


class AppConfig:
    """应用配置管理 — 单例模式"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # 配置文件存放在项目根目录
        self.config_file = Path(__file__).resolve().parent.parent.parent / "gui_config.json"

        self.config: dict = {
            "theme": {
                "mode": "light",
                "accent_color": "#1a73e8",
                "accent_hover": "#1557b0",
                "bg_primary": "#f5f5f5",
                "bg_secondary": "#ffffff",
                "bg_chat": "#f0f2f5",
                "text_primary": "#333333",
                "text_secondary": "#666666",
                "border_color": "#d0d0d0",
                "bubble_user_bg": "#95ec69",
                "bubble_user_text": "#333333",
                "bubble_ai_bg": "#ffffff",
                "bubble_ai_text": "#333333",
                "sidebar_bg": "#ffffff",
                "sidebar_active": "#e8f0fe",
                "sidebar_text": "#555555",
                "sidebar_active_text": "#1a73e8",
                "toast_info": "#ffffff",
                "toast_success": "#e8f5e9",
                "toast_warning": "#fff3e0",
                "toast_error": "#ffebee",
                "toast_text": "#333333",
            },
            "window": {
                "geometry": {"x": 100, "y": 100, "width": 900, "height": 680},
            },
        }

        self.load()
        self._initialized = True

    # ─── 持久化 ────────────────────────────────────

    def load(self):
        config_file = Path(self.config_file)
        try:
            if config_file.exists():
                with config_file.open(encoding="utf-8") as f:
                    loaded = json.load(f)
                for key in loaded:
                    if key in self.config and isinstance(self.config[key], dict) and isinstance(loaded[key], dict):
                        self.config[key].update(loaded[key])
                    elif key in self.config:
                        default_type = type(self.config[key])
                        if isinstance(loaded[key], default_type):
                            self.config[key] = loaded[key]
        except (OSError, json.JSONDecodeError):
            pass

    def save(self):
        config_file = Path(self.config_file)
        tmp_path = config_file.with_suffix(config_file.suffix + ".tmp")
        try:
            d = config_file.parent
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            if config_file.exists():
                config_file.unlink(missing_ok=True)
            tmp_path.rename(config_file)
        except OSError:
            pass

    # ─── 通用读写 ──────────────────────────────────

    def get(self, key: str, default=None):
        return self.config.get(key, default)

    def set(self, key: str, value):
        self.config[key] = value

    # ─── 主题读写 ──────────────────────────────────

    def get_theme(self, key: str | None = None, default=None):
        if key is None:
            return self.config.get("theme", {})
        return self.config.get("theme", {}).get(key, default)

    def set_theme(self, key: str, value):
        self.config["theme"][key] = value

    def get_all_colors(self) -> dict:
        """获取所有颜色项，方便外部引用"""
        return dict(self.config.get("theme", {}))

    def apply_theme(self, colors: dict):
        """批量应用主题颜色并持久化"""
        self.config["theme"].update(colors)
        self.save()
