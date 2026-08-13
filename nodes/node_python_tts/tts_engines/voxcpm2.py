"""
VoxCPM2 适配器 — 本地高保真语音合成（预留接口）

性能要求: >= 8 GB VRAM, CUDA >= 12.0
模型大小: 1.7 GB (4-bit 量化) / 4.2 GB (bf16)
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .base import BaseTTSEngine, TTSEngineMeta
from ._registry import register_engine


class VoxCPM2Engine(BaseTTSEngine):
    """VoxCPM2 本地 TTS（2B 参数，48kHz，零样本语音克隆）"""

    meta = TTSEngineMeta(
        name="voxcpm2",
        display_name="VoxCPM2 (本地)",
        description="2B 参数本地 TTS，48kHz 影棚级音质，支持语音克隆",
        category="local",
        supported_params=["voice", "mode", "prompt_audio", "max_new_tokens"],
    )

    def __init__(self, **kwargs: Any):
        pass

    @property
    def extension(self) -> str:
        return "wav"

    @property
    def content_type(self) -> str:
        return "audio/wav"

    def synthesize(self, text: str, **kwargs: Any) -> bytes:
        raise NotImplementedError(
            "VoxCPM2 引擎尚未实现。\n"
            "需要: Python 3.12 + CUDA PyTorch\n"
            "安装: 参考 https://github.com/bilibili/VoxCPM2"
        )

    def check_available(self) -> bool:
        try:
            import torch
            if not torch.cuda.is_available():
                print("[VoxCPM2] CUDA 不可用", file=sys.stderr)
                return False
            props = torch.cuda.get_device_properties(0)
            if props.total_memory < 7 * 1024 ** 3:
                print(f"[VoxCPM2] 显存不足: {props.total_memory / 1e9:.1f} GB", file=sys.stderr)
                return False
            return True
        except ImportError:
            print("[VoxCPM2] PyTorch 未安装", file=sys.stderr)
            return False

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        g = parser.add_argument_group("VoxCPM2 参数（预留）")
        g.add_argument("--voxcpm2-mode", default="voice_clone",
                       choices=["voice_clone", "tts", "voice_design"])
        g.add_argument("--voxcpm2-prompt-audio", default=None,
                       help="参考音频路径")
        g.add_argument("--voxcpm2-max-tokens", type=int, default=2048)


register_engine(VoxCPM2Engine)
