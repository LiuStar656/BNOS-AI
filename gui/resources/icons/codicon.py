"""Codicon 图标字体管理器 — 从 BNOS 参考源码复用"""

from __future__ import annotations

import os

CODEPOINTS = {
    "chat": 0xEC4F, "comment": 0xEA6B, "comment-discussion": 0xEAC7,
    "send": 0xEC0F, "mention": 0xEB1F, "reply": 0xEA7D,
    "person": 0xEA67, "person-add": 0xEBCD, "smiley": 0xEB54,
    "heart": 0xEB05, "star": 0xEA6A, "star-full": 0xEB59,
    "settings": 0xEB52, "settings-gear": 0xEB51, "gear": 0xEAF8,
    "search": 0xEA6D, "close": 0xEA76, "check": 0xEAB2,
    "info": 0xEA74, "warning": 0xEA6C, "error": 0xEA87,
    "question": 0xEB32, "feedback": 0xEB96, "megaphone": 0xEB1E,
    "bell": 0xEAA2, "bell-dot": 0xEB9A, "history": 0xEA82,
    "clock": 0xEA82, "trash": 0xEA81, "trashcan": 0xEA81,
    "edit": 0xEA73, "pencil": 0xEA73, "copy": 0xEBCC,
    "export": 0xEBAC, "import": 0xEBAC, "save": 0xEB4B,
    "folder": 0xEA83, "file": 0xEA7B, "files": 0xEAF0,
    "new-file": 0xEA7F, "new-folder": 0xEA80,
    "home": 0xEB06, "organization": 0xEA7E, "project": 0xEB30,
    "code": 0xEAC4, "terminal": 0xEA85, "console": 0xEA85,
    "output": 0xEB9D, "debug": 0xEAD8, "bug": 0xEAAF,
    "play": 0xEB2C, "run": 0xEB2C, "stop": 0xEA87,
    "record": 0xEBA7, "refresh": 0xEB37, "sync": 0xEA77,
    "download": 0xEC74, "upload": 0xEC74, "link": 0xEB15,
    "globe": 0xEB01, "lock": 0xEA75, "unlock": 0xEB74,
    "key": 0xEB11, "shield": 0xEB53, "verified": 0xEB77,
    "pulse": 0xEB31, "graph": 0xEB03, "graph-left": 0xEBAD,
    "dashboard": 0xEACD, "database": 0xEACE, "server": 0xEB50,
    "plug": 0xEB2D, "broadcast": 0xEAAD, "hubot": 0xEB08,
    "robot": 0xEC20, "chip": 0xEC19, "tools": 0xEB6D,
    "wrench": 0xEB65, "extensions": 0xEAE6, "library": 0xEB9C,
    "book": 0xEAA4, "bookmark": 0xEAA5, "note": 0xEB26,
    "list-tree": 0xEB86, "list-flat": 0xEB84, "list-filter": 0xEB83,
    "checklist": 0xEAB3, "tasklist": 0xEB67, "filter": 0xEAF1,
    "color-mode": 0xEAC6, "lightbulb": 0xEA61, "beaker": 0xEA79,
    "paintcan": 0xEB2A, "eye": 0xEA70, "eye-closed": 0xEAE7,
    "live-share": 0xEB18, "share": 0xEC25, "report": 0xEB42,
    "flag": 0xEC3F, "pin": 0xEB2B, "pinned": 0xEBA0,
    "coffee": 0xEC15, "game": 0xEC17, "music": 0xEC1B,
    "mic": 0xEC12, "mic-filled": 0xEC1C, "mute": 0xEB24,
    "vm": 0xEA7A, "device-desktop": 0xEA7A, "device-mobile": 0xEADB,
    "browser": 0xEAAE, "window": 0xEB7F, "screen-full": 0xEB4C,
    "layout": 0xEBEB, "layout-sidebar-left": 0xEBF3, "layout-panel": 0xEBF2,
    "layout-statusbar": 0xEBF5, "layout-centered": 0xEBF7,
    "chevron-down": 0xEAB4, "chevron-left": 0xEAB5, "chevron-right": 0xEAB6, "chevron-up": 0xEAB7,
    "arrow-down": 0xEA9A, "arrow-left": 0xEA9B, "arrow-right": 0xEA9C, "arrow-up": 0xEAA1,
    "ellipsis": 0xEA7C, "more": 0xEA7C, "kebab-vertical": 0xEB10,
    "add": 0xEA60, "plus": 0xEA60, "remove": 0xEB3B, "dash": 0xEACC,
    "circle-filled": 0xEA71, "circle": 0xEABC, "pass": 0xEBA4,
    "loading": 0xEB19, "sparkle": 0xEC10, "wand": 0xEBCF,
    "menu": 0xEB94, "indent": 0xEBF9, "bold": 0xEAA3, "italic": 0xEB0D,
    "quote": 0xEB33, "quotes": 0xEC60, "link-external": 0xEB14,
    "go-to-file": 0xEA94, "search-stop": 0xEB4E, "clear-all": 0xEABF,
    "collapse-all": 0xEAC5, "expand-all": 0xEB95, "fold": 0xEAF5,
    "unfold": 0xEB73, "split-horizontal": 0xEB56, "split-vertical": 0xEB57,
    "whole-word": 0xEB7E, "preserve-case": 0xEB2E, "regex": 0xEB38,
    "newline": 0xEBEA, "case-sensitive": 0xEAB1, "select-all": 0xEB85,
    "map": 0xEC05, "globe": 0xEB01, "rocket": 0xEB44,
    "target": 0xEBF8, "magnet": 0xEBAE, "gift": 0xEAF9,
    "calendar": 0xEAB0, "clockface": 0xEC75, "credit-card": 0xEAC9,
    "percent": 0xEC33, "percentage": 0xEC33, "symbol-method": 0xEB8C,
    "symbol-constant": 0xEB5D, "symbol-class": 0xEB5B, "symbol-interface": 0xEB61,
    "symbol-enum": 0xEB95, "symbol-field": 0xEB5F, "symbol-variable": 0xEA88,
    "symbol-color": 0xEB5C, "symbol-keyword": 0xEB62, "symbol-snippet": 0xEB66,
    "symbol-string": 0xEB8D, "symbol-boolean": 0xEB8F, "symbol-numeric": 0xEB90,
    "symbol-structure": 0xEB91, "symbol-file": 0xEB60, "symbol-misc": 0xEB63,
    "symbol-operator": 0xEB64, "symbol-property": 0xEB65, "symbol-unit": 0xEB96,
    "symbol-ruler": 0xEB96, "symbol-text": 0xEB93, "symbol-reference": 0xEA94,
    "rss": 0xEB47, "twitter": 0xEB72, "github": 0xEA84,
    "python": 0xEC39, "markdown": 0xEB1D, "json": 0xEB0F,
    "git-branch": 0xEC6F, "git-commit": 0xEAFC, "git-merge": 0xEAFE,
    "git-pull-request": 0xEA64, "git-compare": 0xEAFD, "github-alt": 0xEB00,
    "live2d": 0xEC17, "mcp": 0xEC47, "agent": 0xEC67,
    "node": 0xEAF8, "database": 0xEACE, "notebook": 0xEBAF,
    "output": 0xEB9D, "server-environment": 0xEBA3, "server-process": 0xEBA2,
    "type-hierarchy": 0xEBB9, "type-hierarchy-sub": 0xEBBA, "type-hierarchy-super": 0xEBBB,
    "workspace-trusted": 0xEBC1, "workspace-untrusted": 0xEBC2, "workspace-unknown": 0xEBC3,
    "debug-all": 0xEBDC, "debug-alt": 0xEB91, "debug-step-into": 0xEAD4,
    "debug-step-out": 0xEAD5, "debug-step-over": 0xEAD6, "debug-continue": 0xEACF,
    "debug-restart": 0xEAD2, "debug-start": 0xEAD3, "debug-pause": 0xEAD1,
    "debug-stop": 0xEAD7, "debug-disconnect": 0xEAD0, "debug-rerun": 0xEBC0,
    "preview": 0xEB2F, "open-preview": 0xEB28, "open-in-product": 0xEC65,
    "rename": 0xEC61, "eraser": 0xEC5D, "cursor": 0xEC5C,
    "combine": 0xEBB6, "gather": 0xEBB6, "collection": 0xEC57,
    "file-text": 0xEC5E, "file-binary": 0xEAE8, "file-code": 0xEAE9,
    "file-media": 0xEAEA, "file-pdf": 0xEAEB, "file-zip": 0xEAEF,
    "file-symlink-file": 0xEAEE, "file-symlink-directory": 0xEAED,
    "archive": 0xEA98, "unarchive": 0xEC76, "package": 0xEB29,
    "table": 0xEBB7, "pie-chart": 0xEBE4, "graph-line": 0xEBE2,
    "graph-scatter": 0xEBE3, "circle-large-filled": 0xEBB4,
    "circle-large": 0xEBB5, "circle-large-outline": 0xEBB5,
    "circle-small": 0xEC07, "circle-small-filled": 0xEB8A,
    "square": 0xEA72, "dash": 0xEACC,
    "triangle-left": 0xEB6F, "triangle-right": 0xEB70,
    "triangle-up": 0xEB71, "triangle-down": 0xEB6E,
    "thumbsup": 0xEB6C, "thumbsdown": 0xEB6B,
    "thumbsup-filled": 0xEC14, "thumbsdown-filled": 0xEC13,
    "clippy": 0xEAC0, "paste": 0xEAC0, "discard": 0xEAE2,
    "redo": 0xEBB0, "undo": 0xEBB0,
    "reply": 0xEA7D, "forward": 0xEC73, "mail": 0xEB1C,
    "mail-read": 0xEB1B, "inbox": 0xEB09, "calendar": 0xEAB0,
    "pinned-dirty": 0xEBB2, "pinned": 0xEBA0, "pass-filled": 0xEBB3,
    "verify-filled": 0xEBE9, "unverified": 0xEB76,
    "error-small": 0xEBFB, "warning": 0xEA6C, "info": 0xEA74,
    "blank": 0xEC03, "ellipsis": 0xEA7C,
    "ask": 0xEC80, "openai": 0xEC81, "claude": 0xEC82,
    "copilot": 0xEC1E, "copilot-error": 0xEC4D, "copilot-warning": 0xEC38,
    "copilot-success": 0xEC4E, "copilot-in-progress": 0xEC4C,
    "code-review": 0xEC37, "edit-code": 0xEC68, "edit-sparkle": 0xEC51,
    "chat-sparkle": 0xEC4F, "chat-sparkle-warning": 0xEC55, "chat-sparkle-error": 0xEC56,
    "search-sparkle": 0xEC50, "sparkle-filled": 0xEC21,
    "comment-draft": 0xEC0E, "comment-unresolved": 0xEC0A,
    "thinking": 0xEC59, "send-to-remote-agent": 0xEC53,
    "build": 0xEC5A, "run-with-deps": 0xEC62,
    "blank": 0xEC03, "insert": 0xEC11,
    "screen-cut": 0xEC7F, "new-session": 0xEC84,
    "chat-export": 0xEC86, "chat-import": 0xEC87,
    "share-window": 0xEC88,
    "connector": 0xEB88,
    "variable-group": 0xEBB8,
    "strikethrough": 0xEC64,
    "highlight": 0xEBEE,
}


class CodiconManager:
    """图标管理器 — 负责加载 codicon 字体并提供图标字符查询。"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._instance.font_family = "Segoe MDL2 Assets"
        return cls._instance

    def init(self):
        if self._initialized:
            return
        self.font_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Codicon.ttf")
        loaded_family = self._load_font()
        if loaded_family:
            self.font_family = loaded_family
        self._initialized = True

    def _load_font(self):
        try:
            from PySide6.QtGui import QFontDatabase
            font_id = QFontDatabase.addApplicationFont(self.font_path)
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    return families[0]
        except ImportError:
            pass
        return None

    def get_char(self, icon_name: str) -> str:
        code = CODEPOINTS.get(icon_name)
        if code:
            return chr(code)
        return "?"

    def get_font(self, size: int = 14):
        try:
            from PySide6.QtGui import QFont
            return QFont(self.font_family, size)
        except ImportError:
            return None


codicon = CodiconManager()
