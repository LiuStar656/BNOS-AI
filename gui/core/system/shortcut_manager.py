"""
全局快捷键管理器 — 集中定义、持久化、统一应用
适配自 BNOS 参考项目
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence

# 默认快捷键定义: id → (default_keystr, display_name)
DEFAULTS = {
    "send_message": ("Ctrl+Enter", "发送消息"),
    "new_chat": ("Ctrl+N", "新建对话"),
    "clear_chat": ("Ctrl+L", "清空对话"),
    "settings": ("Ctrl+,", "设置"),
    "exit_app": ("Ctrl+Q", "退出"),
    "refresh_nodes": ("F5", "刷新节点"),
}

EMPTY_AS_DISABLED = True


class ShortcutManager:
    """快捷键注册表"""

    def __init__(self, app_config=None):
        self._cfg = app_config
        self._overrides = self._cfg.get("shortcuts", {}) if self._cfg else {}

    def get(self, sid: str) -> str:
        return self._overrides.get(sid) or DEFAULTS[sid][0]

    def get_qkey(self, sid: str) -> QKeySequence:
        return QKeySequence(self.get(sid))

    def set(self, sid: str, keystr: str) -> bool:
        if sid not in DEFAULTS:
            raise KeyError(sid)
        if keystr and keystr.strip():
            existing = self._find_conflict(keystr, sid)
            if existing:
                return False
        self._overrides[sid] = keystr
        return True

    def _find_conflict(self, keystr: str, exclude_sid: str = "") -> str:
        for sid, (default, _) in DEFAULTS.items():
            if sid == exclude_sid:
                continue
            current = self._overrides.get(sid, default)
            if current and current.strip() == keystr:
                return sid
        return ""

    def reset(self, sid: str = None):
        if sid:
            self._overrides.pop(sid, None)
        else:
            self._overrides.clear()

    def save(self):
        if self._cfg:
            self._cfg["shortcuts"] = self._overrides

    def all_items(self):
        for sid, (default, display_name) in DEFAULTS.items():
            yield (sid, display_name, self.get(sid), default)
