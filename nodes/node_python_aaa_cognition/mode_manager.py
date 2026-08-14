"""
模式管理模块 — 日常/工作双模式状态 + NLP 关键词切换检测。

mode.json（nodes/shared/mode.json）是模式状态的唯一事实来源：
- GUI 聊天页顶部按钮写该文件（手动切换）
- AAA 侧 NLP 关键词命中写该文件（自动切换，如用户输入「进入工作模式」）
- AAA 每次处理文本时读取，决定走 LLM 判断（日常）还是直通 DSH（工作）

关键词可配置：node_config.json → mode_keywords 段，可在 GUI 设置面板修改。
"""

from __future__ import annotations

import json
from pathlib import Path

_NODES_DIR = Path(__file__).resolve().parent.parent.parent / "nodes"
_MODE_FILE = _NODES_DIR / "shared" / "mode.json"

MODE_DAILY = "daily"
MODE_WORK = "work"
DEFAULT_MODE = MODE_DAILY

_MODE_LABELS = {
    MODE_DAILY: "日常模式",
    MODE_WORK: "工作模式",
}


def get_mode() -> str:
    """读取当前模式，默认 daily；文件缺失/损坏不抛异常。"""
    try:
        if _MODE_FILE.is_file():
            data = json.loads(_MODE_FILE.read_text(encoding="utf-8"))
            mode = str(data.get("mode", "")).strip()
            if mode in (MODE_DAILY, MODE_WORK):
                return mode
    except (OSError, json.JSONDecodeError):
        pass
    return DEFAULT_MODE


def set_mode(mode: str) -> bool:
    """原子写模式状态（临时文件 + replace），非法值忽略。"""
    if mode not in (MODE_DAILY, MODE_WORK):
        return False
    try:
        _MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _MODE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"mode": mode}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_MODE_FILE)
        return True
    except OSError:
        return False


def _load_keywords() -> dict:
    """读取 node_config.json 的 mode_keywords 段（AAA 侧配置）。"""
    cfg_path = Path(__file__).resolve().parent / "node_config.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    kw = cfg.get("mode_keywords") or {}
    return kw if isinstance(kw, dict) else {}


def try_switch(query: str) -> str:
    """关键词 NLP 检测：命中切换词 → 执行切换并返回提示语；未命中返回 ""。

    子串匹配（用户输入中带关键词字段即触发）。同一输入命中多个词时，
    优先匹配更长的词（更具体，如「退出工作模式」优先于「工作模式」）。
    """
    query = (query or "").strip()
    if not query:
        return ""
    kw = _load_keywords()
    candidates = []
    for word in kw.get("work", []) or []:
        if word:
            candidates.append((word, MODE_WORK))
    for word in kw.get("daily", []) or []:
        if word:
            candidates.append((word, MODE_DAILY))
    candidates.sort(key=lambda item: len(item[0]), reverse=True)
    for word, mode in candidates:
        if word in query:
            set_mode(mode)
            label = _MODE_LABELS[mode]
            if mode == MODE_WORK:
                return f"已切换到{label}，后续输入将直接交给 DSH 执行，不再走对话判断。"
            return f"已切换到{label}，回归对话。"
    return ""
