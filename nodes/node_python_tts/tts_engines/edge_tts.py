"""
Edge-TTS 适配器 — Microsoft Edge 浏览器 TTS（云端免费，高质量）
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from .base import BaseTTSEngine, TTSEngineMeta
from ._registry import register_engine

# 中文音色映射
EDGE_VOICE_MAP: dict[str, str] = {
    "xiaoxiao":   "zh-CN-XiaoxiaoNeural",
    "xiaoyi":     "zh-CN-XiaoyiNeural",
    "xiaochen":   "zh-CN-XiaochenNeural",
    "xiaohan":    "zh-CN-XiaohanNeural",
    "xiaomo":     "zh-CN-XiaomoNeural",
    "xiaorui":    "zh-CN-XiaoruiNeural",
    "xiaoshuang": "zh-CN-XiaoshuangNeural",
    "xiaoxuan":   "zh-CN-XiaoxuanNeural",
    "xiaoyan":    "zh-CN-XiaoyanNeural",
    "xiaoyou":    "zh-CN-XiaoyouNeural",
    "yunxi":      "zh-CN-YunxiNeural",
    "yunjian":    "zh-CN-YunjianNeural",
    "yunyang":    "zh-CN-YunyangNeural",
    "yunfeng":    "zh-CN-YunfengNeural",
    "yunhao":     "zh-CN-YunhaoNeural",
    "yunze":      "zh-CN-YunzeNeural",
    "xiaobei":    "zh-CN-liaoning-XiaobeiNeural",
    "hsiaochen":  "zh-TW-HsiaoChenNeural",
    "hiugaai":    "zh-HK-HiuGaaiNeural",
}


class EdgeTTSEngine(BaseTTSEngine):
    """Microsoft Edge TTS（在线，高质量，免费）"""

    meta = TTSEngineMeta(
        name="edge_tts",
        display_name="Microsoft Edge TTS",
        description="微软 Edge 浏览器语音合成（云端免费，19种中文音色）",
        category="cloud",
        supported_params=["voice", "rate", "pitch"],
    )

    def __init__(self, **kwargs: Any):
        self._voice = kwargs.get("voice", "xiaoxiao")
        self._rate = kwargs.get("rate", "+0%")
        self._pitch = kwargs.get("pitch", "+0Hz")

    @property
    def voice_name(self) -> str:
        return self._voice

    @property
    def voice_id(self) -> str:
        return EDGE_VOICE_MAP.get(self._voice.lower(), EDGE_VOICE_MAP["xiaoxiao"])

    def synthesize(self, text: str, **kwargs: Any) -> bytes:
        if not text.strip():
            return b""

        voice = kwargs.get("voice", self._voice)
        rate = kwargs.get("rate", self._rate)
        pitch = kwargs.get("pitch", self._pitch)
        voice_id = EDGE_VOICE_MAP.get(voice.lower(), EDGE_VOICE_MAP["xiaoxiao"])

        print(f"[TTS] Edge [{voice}]: {text[:60]}...")
        sys.stdout.flush()

        from edge_tts import Communicate

        async def _run() -> bytes:
            communicate = Communicate(text=text, voice=voice_id, rate=rate, pitch=pitch)
            chunks: list[bytes] = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            return b"".join(chunks)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                new_loop = asyncio.new_event_loop()
                try:
                    return new_loop.run_until_complete(_run())
                finally:
                    new_loop.close()
            else:
                return loop.run_until_complete(_run())
        except RuntimeError:
            return asyncio.run(_run())

    def check_available(self) -> bool:
        try:
            from edge_tts import Communicate  # noqa: F401
            return True
        except ImportError:
            return False

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        g = parser.add_argument_group("Edge-TTS 参数")
        g.add_argument("--voice", default="xiaoxiao",
                       help=f"音色: {', '.join(EDGE_VOICE_MAP.keys())}")
        g.add_argument("--rate", default="+0%", help="语速: -50%% ~ +100%%")
        g.add_argument("--pitch", default="+0Hz", help="音调: -20Hz ~ +20Hz")


register_engine(EdgeTTSEngine)
