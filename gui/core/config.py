"""
GUI 配置管理 — 从 BNOS AppConfig 适配，专注于主题/颜色配置持久化

使用单例模式确保全局只有一个配置实例。
"""

from __future__ import annotations

import json
from pathlib import Path

from gui.core.skin_registry import skin_registry

# ─── 8 套主题预设 ──────────────────────────────────
THEME_PRESETS: dict[str, dict] = {
    "default_light": {
        "name": "默认亮色",
        "colors": {
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
            "select_bg": "#1557b0",
        },
    },
    "dark": {
        "name": "暗夜",
        "colors": {
            "mode": "dark",
            "accent_color": "#64b5f6",
            "accent_hover": "#42a5f5",
            "bg_primary": "#1e1e1e",
            "bg_secondary": "#252526",
            "bg_chat": "#2d2d30",
            "text_primary": "#cccccc",
            "text_secondary": "#999999",
            "border_color": "#3c3c3c",
            "bubble_user_bg": "#2b5278",
            "bubble_user_text": "#e0e0e0",
            "bubble_ai_bg": "#383838",
            "bubble_ai_text": "#e0e0e0",
            "sidebar_bg": "#252526",
            "sidebar_active": "#37373d",
            "sidebar_text": "#999999",
            "sidebar_active_text": "#64b5f6",
            "toast_info": "#333333",
            "toast_success": "#1b3a1b",
            "toast_warning": "#3a2a1b",
            "toast_error": "#3a1b1b",
            "toast_text": "#e0e0e0",
            "select_bg": "#264f78",
        },
    },
    "amoled": {
        "name": "纯黑 AMOLED",
        "colors": {
            "mode": "dark",
            "accent_color": "#64b5f6",
            "accent_hover": "#42a5f5",
            "bg_primary": "#000000",
            "bg_secondary": "#0a0a0a",
            "bg_chat": "#000000",
            "text_primary": "#e0e0e0",
            "text_secondary": "#888888",
            "border_color": "#1a1a1a",
            "bubble_user_bg": "#0d47a1",
            "bubble_user_text": "#ffffff",
            "bubble_ai_bg": "#1a1a1a",
            "bubble_ai_text": "#e0e0e0",
            "sidebar_bg": "#000000",
            "sidebar_active": "#1a1a1a",
            "sidebar_text": "#888888",
            "sidebar_active_text": "#64b5f6",
            "toast_info": "#1a1a1a",
            "toast_success": "#0a1a0a",
            "toast_warning": "#1a1a0a",
            "toast_error": "#1a0a0a",
            "toast_text": "#e0e0e0",
            "select_bg": "#0d47a1",
        },
    },
    "macos": {
        "name": "macOS 风格",
        "colors": {
            "mode": "light",
            "accent_color": "#007aff",
            "accent_hover": "#0066d9",
            "bg_primary": "#f0f0f0",
            "bg_secondary": "#ffffff",
            "bg_chat": "#e8e8e8",
            "text_primary": "#1d1d1f",
            "text_secondary": "#86868b",
            "border_color": "#d2d2d7",
            "bubble_user_bg": "#007aff",
            "bubble_user_text": "#ffffff",
            "bubble_ai_bg": "#e9e9eb",
            "bubble_ai_text": "#1d1d1f",
            "sidebar_bg": "#ffffff",
            "sidebar_active": "#e8f0fe",
            "sidebar_text": "#86868b",
            "sidebar_active_text": "#007aff",
            "toast_info": "#ffffff",
            "toast_success": "#e8f5e9",
            "toast_warning": "#fff3e0",
            "toast_error": "#ffebee",
            "toast_text": "#1d1d1f",
            "select_bg": "#007aff",
        },
    },
    "koyu": {
        "name": "暗青 (Koyu)",
        "colors": {
            "mode": "dark",
            "accent_color": "#26a69a",
            "accent_hover": "#20a096",
            "bg_primary": "#1a1a2e",
            "bg_secondary": "#16213e",
            "bg_chat": "#0f3460",
            "text_primary": "#e0e0e0",
            "text_secondary": "#a0a0a0",
            "border_color": "#2a3a5c",
            "bubble_user_bg": "#26a69a",
            "bubble_user_text": "#ffffff",
            "bubble_ai_bg": "#1a2744",
            "bubble_ai_text": "#e0e0e0",
            "sidebar_bg": "#16213e",
            "sidebar_active": "#1a3a5c",
            "sidebar_text": "#a0a0a0",
            "sidebar_active_text": "#26a69a",
            "toast_info": "#1a2744",
            "toast_success": "#1b3a2b",
            "toast_warning": "#3a3a1b",
            "toast_error": "#3a1b1b",
            "toast_text": "#e0e0e0",
            "select_bg": "#26a69a",
        },
    },
    "ubuntu": {
        "name": "Ubuntu 风格",
        "colors": {
            "mode": "light",
            "accent_color": "#e95420",
            "accent_hover": "#d4461a",
            "bg_primary": "#f2f2f2",
            "bg_secondary": "#ffffff",
            "bg_chat": "#ebeaef",
            "text_primary": "#333333",
            "text_secondary": "#777777",
            "border_color": "#cdcdcd",
            "bubble_user_bg": "#e95420",
            "bubble_user_text": "#ffffff",
            "bubble_ai_bg": "#ffffff",
            "bubble_ai_text": "#333333",
            "sidebar_bg": "#ffffff",
            "sidebar_active": "#fde8e0",
            "sidebar_text": "#777777",
            "sidebar_active_text": "#e95420",
            "toast_info": "#ffffff",
            "toast_success": "#e8f5e9",
            "toast_warning": "#fff3e0",
            "toast_error": "#ffebee",
            "toast_text": "#333333",
            "select_bg": "#e95420",
        },
    },
    "neon": {
        "name": "霓虹",
        "colors": {
            "mode": "dark",
            "accent_color": "#ff4081",
            "accent_hover": "#f50057",
            "bg_primary": "#1a1a2e",
            "bg_secondary": "#222240",
            "bg_chat": "#2a2a4e",
            "text_primary": "#e0e0e0",
            "text_secondary": "#a0a0b0",
            "border_color": "#3a3a5e",
            "bubble_user_bg": "#ff4081",
            "bubble_user_text": "#ffffff",
            "bubble_ai_bg": "#2a2a4e",
            "bubble_ai_text": "#e0e0e0",
            "sidebar_bg": "#222240",
            "sidebar_active": "#3a2a4e",
            "sidebar_text": "#a0a0b0",
            "sidebar_active_text": "#ff4081",
            "toast_info": "#2a2a4e",
            "toast_success": "#1a3a2a",
            "toast_warning": "#3a2a1a",
            "toast_error": "#3a1a2a",
            "toast_text": "#e0e0e0",
            "select_bg": "#ff4081",
        },
    },
    "gri": {
        "name": "冷灰",
        "colors": {
            "mode": "light",
            "accent_color": "#546e7a",
            "accent_hover": "#455a64",
            "bg_primary": "#eceff1",
            "bg_secondary": "#ffffff",
            "bg_chat": "#e0e0e0",
            "text_primary": "#37474f",
            "text_secondary": "#78909c",
            "border_color": "#b0bec5",
            "bubble_user_bg": "#546e7a",
            "bubble_user_text": "#ffffff",
            "bubble_ai_bg": "#ffffff",
            "bubble_ai_text": "#37474f",
            "sidebar_bg": "#ffffff",
            "sidebar_active": "#e0e0e0",
            "sidebar_text": "#78909c",
            "sidebar_active_text": "#546e7a",
            "toast_info": "#ffffff",
            "toast_success": "#e8f5e9",
            "toast_warning": "#fff3e0",
            "toast_error": "#ffebee",
            "toast_text": "#37474f",
            "select_bg": "#546e7a",
        },
    },
}


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
            "selected_preset": "default_light",
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
                "select_bg": "#1557b0",
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
                    else:
                        # 保留未知键（live2d_overlay, live2d_current_model 等第三方写入的键）
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

    # ─── 主题预设 / 皮肤包管理 ─────────────────────

    @staticmethod
    def get_preset_list() -> list[tuple[str, str]]:
        """返回 [(preset_id, display_name), ...]（仅内置预设，兼容旧接口）"""
        return [(pid, p["name"]) for pid, p in THEME_PRESETS.items()]

    def get_theme_list(self) -> list[tuple[str, str, str]]:
        """返回 [(theme_id, display_name, source), ...]（内置预设 + 皮肤包平级）"""
        themes = [(pid, p["name"], "preset") for pid, p in THEME_PRESETS.items()]
        themes += [(s.id, s.name, "skin") for s in skin_registry.list_skins()]
        return themes

    def get_selected_preset(self) -> str:
        return self.config.get("selected_preset", "default_light")

    def get_selected_skin(self) -> str | None:
        """当前选中的皮肤包 id（未启用皮肤包时为 None）"""
        return self.config.get("selected_skin")

    def apply_preset(self, preset_id: str):
        """应用主题预设：覆盖所有颜色并持久化"""
        preset = THEME_PRESETS.get(preset_id)
        if not preset:
            return
        self.config["selected_preset"] = preset_id
        self.config.pop("selected_skin", None)
        self.config["theme"].update(preset["colors"])
        self.save()

    def apply_skin(self, skin_id: str):
        """应用皮肤包：增量覆盖 token 并持久化（与内置预设平级）"""
        skin = skin_registry.get(skin_id)
        if not skin:
            return
        if skin.mode:
            self.config["theme"]["mode"] = skin.mode
        self.config["theme"].update(skin.tokens)
        self.config["selected_skin"] = skin_id
        self.config.pop("selected_preset", None)
        self.save()
