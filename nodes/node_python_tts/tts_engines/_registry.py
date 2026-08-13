"""
TTS 引擎注册表 — 支持运行时动态发现和切换引擎
"""

from __future__ import annotations

from typing import Type

from .base import BaseTTSEngine

_registry: dict[str, Type[BaseTTSEngine]] = {}


def register_engine(engine_cls: Type[BaseTTSEngine]) -> None:
    """注册一个 TTS 引擎类"""
    _registry[engine_cls.meta.name] = engine_cls


def get_engine(name: str) -> Type[BaseTTSEngine] | None:
    """按名称获取引擎类"""
    return _registry.get(name)


def list_engines() -> dict[str, str]:
    """列出所有已注册引擎

    Returns:
        {name: display_name, ...}
    """
    return {cls.meta.name: cls.meta.display_name for cls in _registry.values()}


def discover_all() -> None:
    """导入所有引擎模块，触发自动注册"""
    from . import edge_tts  # noqa: F401
    try:
        from . import voxcpm2  # noqa: F401
    except ImportError:
        pass
    try:
        from . import qwen3_tts  # noqa: F401
    except ImportError:
        pass
