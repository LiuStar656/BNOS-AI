"""
TTS 引擎抽象基类 — 所有 TTS 后端必须实现此接口
"""

from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class TTSEngineMeta:
    """引擎元信息，用于注册和展示"""
    name: str                    # 引擎标识，如 "edge_tts"
    display_name: str            # 显示名称，如 "Microsoft Edge TTS"
    description: str = ""        # 简介
    category: str = "cloud"      # cloud / local / hybrid
    supported_params: list[str] = field(default_factory=list)  # 额外可调参数


class BaseTTSEngine(ABC):
    """TTS 引擎抽象基类

    所有 TTS 后端必须：
    1. 继承此类，设置 `meta` 类变量
    2. 实现所有抽象方法
    3. 在模块底部调用 register_engine() 注册
    """

    meta: ClassVar[TTSEngineMeta]

    # ─── 不可变属性 ─────────────────────────

    @property
    def extension(self) -> str:
        """输出音频文件扩展名（默认 mp3）"""
        return "mp3"

    @property
    def content_type(self) -> str:
        """HTTP Content-Type（默认 audio/mpeg）"""
        return "audio/mpeg"

    # ─── 抽象方法 ───────────────────────────

    @abstractmethod
    def synthesize(self, text: str, **kwargs: Any) -> bytes:
        """合成语音，返回音频二进制数据

        Args:
            text: 待合成的文本
            **kwargs: 引擎特定参数（如 voice, rate, pitch 等）

        Returns:
            音频二进制数据（空字节表示合成失败）
        """
        ...

    # ─── 可选重写方法 ──────────────────────

    def check_available(self) -> bool:
        """检查引擎在当前环境是否可用（网络、依赖等）"""
        return True

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """为 argparse 添加引擎专有 CLI 参数"""
        pass
