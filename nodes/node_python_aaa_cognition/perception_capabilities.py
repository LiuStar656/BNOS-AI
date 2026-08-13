"""
感知能力声明系统 (v4.0)

在 Prompt 中明确告知 LLM 当前可用的感知通道，防止幻觉，支持渐进增强。
当 ASR/Vision 节点上线时，只需调用 enable() 即可自动更新 Prompt。
"""

import json
import os


class PerceptionCapabilities:
    """AI 感知能力状态管理"""

    DEFAULT_CAPABILITIES = {
        "text": {
            "enabled": True,
            "description": "用户的文字输入"
        },
        "auditory": {
            "enabled": False,
            "description": "环境语音（ASR 捕获）"
        },
        "visual": {
            "enabled": False,
            "description": "屏幕画面（Vision 捕获）"
        },
        "screen": {
            "enabled": False,
            "description": "屏幕截图"
        },
        "system": {
            "enabled": False,
            "description": "系统事件（时间、通知等）"
        }
    }

    _CHANNEL_CN = {
        "text": "文本输入",
        "auditory": "语音环境",
        "visual": "视觉环境",
        "screen": "屏幕截图",
        "system": "系统事件"
    }

    def __init__(self, config_path: str = None):
        self._config = {k: v.copy() for k, v in self.DEFAULT_CAPABILITIES.items()}
        if config_path and os.path.exists(config_path):
            self._load_from_file(config_path)

    def enable(self, channel: str):
        """启用指定感知通道"""
        if channel in self._config:
            self._config[channel]["enabled"] = True

    def disable(self, channel: str):
        """禁用指定感知通道"""
        if channel in self._config:
            self._config[channel]["enabled"] = False

    def is_available(self, channel: str) -> bool:
        """检查指定通道是否可用"""
        return self._config.get(channel, {}).get("enabled", False)

    def get_perception_text(self) -> str:
        """生成 Prompt 中的感知能力描述"""
        lines = [
            "### 你的感知能力（重要）",
            "当前可用的感知通道："
        ]
        for channel, info in self._config.items():
            status = "✅ 可用" if info["enabled"] else "❌ 不可用"
            cn_name = self._channel_cn(channel)
            lines.append(f"- {cn_name} ({channel}): {status}（{info['description']}）")

        disabled = [
            self._channel_cn(k) for k, v in self._config.items()
            if not v["enabled"]
        ]
        if disabled:
            lines.append(
                f"\n**注意**：以下通道不可用，不要假装能感知到这些信息：{', '.join(disabled)}"
            )

        return "\n".join(lines)

    def _channel_cn(self, en: str) -> str:
        return self._CHANNEL_CN.get(en, en)

    def _load_from_file(self, config_path: str):
        """从配置文件加载"""
        with open(config_path, 'r', encoding='utf-8') as f:
            custom = json.load(f)
        for key, value in custom.items():
            if key in self._config and isinstance(value, dict):
                self._config[key].update(value)
