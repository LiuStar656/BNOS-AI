"""
TTS 引擎包 — 多引擎统一接口

使用方法:
    from tts_engines import create_engine, list_engines

    engine = create_engine("edge_tts", voice="xiaoxiao")
    audio = engine.synthesize("你好世界")
"""

from ._registry import discover_all, get_engine, list_engines, register_engine
from .base import BaseTTSEngine

discover_all()

__all__ = [
    "BaseTTSEngine",
    "create_engine",
    "list_engines",
    "register_engine",
    "get_engine",
]


def create_engine(name: str, **kwargs) -> BaseTTSEngine | None:
    """工厂方法：按名称创建引擎实例"""
    cls = get_engine(name)
    if cls is None:
        return None
    return cls(**kwargs)
