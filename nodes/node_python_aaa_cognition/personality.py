"""
角色种子系统 - 性格演化 + 动态情绪处理 + Prompt 段构建

职责：
- PersonalityEvolution: 性格向量随用户反馈自然演化（慢变量，±0.02）
- 情绪处理：解析 LLM 输出的【情绪调整】，限制 ±0.2，累加 clamp 到 [-1.0, 1.0]
- build_personality_section / build_mood_section: 构建注入 prompt 的段落

与 db.py 的关系：本模块只做计算，持久化通过 db.py 的读写方法完成。
"""

from __future__ import annotations

import re
import time
import json

# 情绪调整值的硬限制（防 LLM 失控）
_MOOD_ADJUST_LIMIT = 0.2
# 情绪总值范围
_MOOD_RANGE = (-1.0, 1.0)
# v2.1 情绪阻尼：单次净调整上限（防持续同向调整 5 轮贴死边界）
_MOOD_MAX_STEP = 0.05
# v2.1 情绪阻尼：每轮向 0 回归系数（情绪自然平复，不锁死 ±1.0）
_MOOD_REGRESSION = 0.98
# 情绪驱动触发：连续最近 N 次
_MOOD_TRIGGER_WINDOW = 10
# 情绪驱动阈值
_MOOD_TRIGGER_THRESHOLD = 0.3
# 兜底触发：每 30 次交互
_FALLBACK_TRIGGER_COUNT = 30
# 观察窗口
_FEEDBACK_WINDOW = 50
# 单次微调幅度上限（慢演化）
_DELTA = 0.02
# v2.0 差距驱动演化：收敛系数（观测 vs 当前的差距 × 该系数）
_ADJUST_LEARN_RATE = 0.06
# v2.0 差距驱动演化：单次最大微调幅度（与 _DELTA 一致）
_ADJUST_MAX_STEP = 0.02


class PersonalityEvolution:
    """性格向量随使用自然演化（慢演化，确定性计算，LLM 不参与）"""

    def __init__(self, seed: dict):
        self.vector = {
            "warmth": float(seed.get("warmth", 0.6)),
            "playfulness": float(seed.get("playfulness", 0.4)),
            "directness": float(seed.get("directness", 0.5)),
            "curiosity": float(seed.get("curiosity", 0.5)),
        }
        self.feedback_history: list[dict] = []
        self.mood_history: list[dict] = []
        self.vector_changed = False  # 调用 observe_feedback 后是否发生了微调

    def observe_feedback(self, response_style: dict, user_reaction: str,
                         mood: float = 0.0) -> bool:
        """记录一次反馈 + 情绪值；触发演化时返回 True，并置 vector_changed"""
        self.vector_changed = False
        self.feedback_history.append({
            "style": dict(response_style),
            "reaction": user_reaction,
            "timestamp": time.time(),
        })
        self.mood_history.append({
            "mood": float(mood),
            "timestamp": time.time(),
        })

        # 情绪驱动触发（优先）
        if self._check_mood_trigger():
            self._adjust_vector()
            return self.vector_changed

        # 兜底：每 30 次交互强制检查
        if len(self.feedback_history) >= _FALLBACK_TRIGGER_COUNT:
            self._adjust_vector()
        return self.vector_changed

    def _check_mood_trigger(self) -> bool:
        """检查情绪是否连续保持在某个区间（主触发机制）"""
        recent = self.mood_history[-_MOOD_TRIGGER_WINDOW:]
        if len(recent) < _MOOD_TRIGGER_WINDOW:
            return False
        avg = sum(m["mood"] for m in recent) / len(recent)
        if avg > _MOOD_TRIGGER_THRESHOLD or avg < -_MOOD_TRIGGER_THRESHOLD:
            return True
        # 剧烈波动 → 需要学会平衡
        variance = sum((m["mood"] - avg) ** 2 for m in recent) / len(recent)
        return variance > 0.15

    def _adjust_vector(self):
        """差距驱动演化：以"观测风格 vs 当前向量"的差距驱动微调（v2.0）。

        修复 v1.0 死区间缺陷：原实现要求观测 style>0.6/<0.4 才调整，
        默认种子 [0.6,0.4,0.5,0.5] 恰好全落 (0.4,0.6] 内，永不触发。
        v2.0 只要存在观测（positive/negative），就向目标收敛，步长限幅 ±0.02。
        """
        recent = self.feedback_history[-_FEEDBACK_WINDOW:]
        avg_mood = self._get_recent_avg_mood()
        changed = False

        for dim in ("warmth", "playfulness", "directness", "curiosity"):
            pos = [r["style"].get(dim) for r in recent
                   if r["reaction"] == "positive" and r["style"].get(dim) is not None]
            neg = [r["style"].get(dim) for r in recent
                   if r["reaction"] == "negative" and r["style"].get(dim) is not None]

            if not pos and not neg:
                continue  # 无观测，跳过（有观测即演化，无死区间）

            if pos and neg:
                target = (sum(pos) / len(pos) + sum(neg) / len(neg)) / 2
            elif pos:
                target = sum(pos) / len(pos)          # 正反馈 → 向观测风格靠拢
            else:
                target = 1.0 - sum(neg) / len(neg)    # 负反馈 → 背离观测风格

            delta = (target - self.vector[dim]) * _ADJUST_LEARN_RATE
            # 情绪趋势调速（保留 v1.0 行为）
            if avg_mood > _MOOD_TRIGGER_THRESHOLD:
                delta *= 1.5
            elif avg_mood < -_MOOD_TRIGGER_THRESHOLD:
                delta *= 1.2
            delta = max(-_ADJUST_MAX_STEP, min(_ADJUST_MAX_STEP, delta))

            new_value = min(1.0, max(0.0, self.vector[dim] + delta))
            if abs(new_value - self.vector[dim]) > 1e-9:
                changed = True
            self.vector[dim] = new_value

        # 消化历史（保留少量作为种子）
        self.feedback_history = self.feedback_history[-20:]
        self.mood_history = self.mood_history[-5:]
        self.vector_changed = changed

    def _get_recent_avg_mood(self) -> float:
        recent = self.mood_history[-10:]
        if not recent:
            return 0.0
        return sum(m["mood"] for m in recent) / len(recent)

    def get_current(self) -> dict:
        return self.vector.copy()


# ══════════════════════════════════════════════════════════════════
# 情绪调整值处理（快变量：LLM 给建议，代码限制并累加）
# ══════════════════════════════════════════════════════════════════

def parse_mood_adjustment(raw: str) -> float:
    """解析 LLM 输出的【情绪调整】值；解析失败返回 0.0，超限被 clamp"""
    if raw is None:
        return 0.0
    text = str(raw).strip().replace("+", "")
    try:
        val = float(text)
    except ValueError:
        return 0.0
    return max(-_MOOD_ADJUST_LIMIT, min(_MOOD_ADJUST_LIMIT, val))


def compute_new_mood(current: float, adjustment: float) -> float:
    """累加计算新情绪值并 clamp 到 [-1.0, 1.0]

    v2.1 情绪阻尼：
    1) 中性回归：情绪随时间自然回落（× _MOOD_REGRESSION），不锁死边界
    2) 步长限制：单次净调整不超过 ±_MOOD_MAX_STEP（原为 ±0.2 全量累加）
    持续同向刺激时 mood 渐进攀升而非 5 轮贴顶；刺激消失后逐轮回落。
    """
    regressed = current * _MOOD_REGRESSION
    step = max(-_MOOD_MAX_STEP, min(_MOOD_MAX_STEP, adjustment))
    return max(_MOOD_RANGE[0], min(_MOOD_RANGE[1], regressed + step))


def mood_level_text(value: float) -> str:
    """情绪值 → 语义区间描述"""
    if value <= -0.3:
        return "负面"
    if value >= 0.3:
        return "正面"
    return "中性"


# ══════════════════════════════════════════════════════════════════
# Prompt 段构建
# ══════════════════════════════════════════════════════════════════

def build_personality_section(vector: dict, style_description: str = "") -> str:
    """构建【你的性格】段（慢变量，注入 {personality} 占位符）"""
    if not vector:
        return ""
    parts = [
        "### 你的性格（会随使用自然演化，不需主动提及）",
        "各维度均为 0-1 范围，当前值如下（0=完全不是，1=极致，0.5=中等）：",
        (f"温暖度: {vector.get('warmth', 0.6):.1f} | "
         f"活泼度: {vector.get('playfulness', 0.4):.1f} | "
         f"直接度: {vector.get('directness', 0.5):.1f} | "
         f"好奇心: {vector.get('curiosity', 0.5):.1f}"),
    ]
    if style_description:
        parts.append(f"说话风格: {style_description}")
    return "\n".join(parts)


def build_mood_section(mood_value: float, source_mood: str = "") -> str:
    """构建【当前情绪】段（快变量，注入 {mood} 占位符）"""
    desc = source_mood or mood_level_text(mood_value)
    return (
        "### 你的当前情绪（实时波动，会被对话影响）\n"
        f"情绪值: {mood_value:.2f} (范围 -1.0 到 1.0，负值代表负面，正值代表正面)\n"
        f"情绪描述: {desc}\n"
        "**重要**：请在回复中自然地体现你的情绪状态。"
        "情绪值 > 0.3 时语气可以更轻松；< -0.3 时语气可以更沉重。"
    )


# ══════════════════════════════════════════════════════════════════
# 反馈信号采集（被动观察，不增加用户负担）
# ══════════════════════════════════════════════════════════════════

# v2.0 风格观测词典：从 LLM 本次回执文本判定四维倾向（确定性、可单测）
_STYLE_KEYWORDS = {
    "warmth": {
        "high": ["温暖", "温柔", "关心", "耐心", "体贴", "亲切", "柔和", "暖心", "爱护", "照顾"],
        "low": ["冷漠", "冷淡", "无情", "冷冰冰", "疏远", "冷酷", "敷衍"],
    },
    "playfulness": {
        "high": ["活泼", "幽默", "俏皮", "调皮", "玩笑", "有趣", "逗趣", "轻松", "欢快", "可爱"],
        "low": ["严肃", "古板", "呆板", "死板", "正经", "一本正经"],
    },
    "directness": {
        "high": ["说话直", "直来直去", "想到什么说什么", "不藏着掖着",
                 "心里想什么就说什么", "爽快", "利落", "简洁", "不拐弯抹角",
                 "直接说", "直接"],
        "low": ["委婉", "含蓄", "吞吞吐吐", "拐弯抹角", "磨叽", "绕来绕去",
                "欲言又止", "绕弯"],
    },
    "curiosity": {
        "high": ["好奇", "追问", "探索", "感兴趣", "求知", "想知道", "渴望了解",
                 "爱问", "刨根问底", "想弄明白", "研究", "琢磨"],
        "low": ["敷衍", "无所谓", "不感兴趣", "厌倦", "懒得", "提不起兴趣"],
    },
}
# 否定句检测（v2.0）：用户显式纠正/否定 → negative 反馈
_NEGATIVE_PATTERNS = [
    r"不对", r"不是", r"不喜欢", r"你错了", r"别这样", r"你搞错了",
    r"重新说", r"算了", r"闭嘴", r"别说了", r"你根本不懂", r"胡说",
    r"瞎说", r"说错了", r"不要这样", r"不想听", r"stop", r"打住",
]


def get_default_style() -> dict:
    """默认观测风格（未观测到时使用，与默认角色种子一致，不会引发演化）"""
    return {"warmth": 0.6, "playfulness": 0.4, "directness": 0.5, "curiosity": 0.5}


def estimate_style_from_reply(parsed: dict) -> dict:
    """从 LLM 本次回执中提取四维风格观测值（v2.0 演化输入源）。

    不再"自己看自己"（v1.0 传当前向量），而是观测本次回复实际表现的风格：
    按【自我认知】【自我信息】【心情】【想法】【自然回复】文本中的关键词打分。

    Args:
        parsed: parser.parse_llm_output 的节字典（空 dict 也安全）

    Returns:
        {"warmth": 0-1, "playfulness": 0-1, "directness": 0-1, "curiosity": 0-1}
        未命中任何关键词的维度回退 0.5（中性）。
    """
    if not parsed:
        return get_default_style()
    parts = [str(parsed.get(k, "") or "") for k in
             ("自我认知", "自我信息", "心情", "想法", "自然回复")]
    text = " ".join(parts)
    style = {}
    for dim, kv in _STYLE_KEYWORDS.items():
        high = sum(1 for kw in kv["high"] if kw in text)
        low = sum(1 for kw in kv["low"] if kw in text)
        if high or low:
            # 命中倾向 → 在 [0.15, 0.85] 区间给出得分，避免直接贴 0/1 导致演化过冲
            score = 0.5 + 0.35 * (high - low) / max(high + low, 1)
        else:
            score = 0.5
        style[dim] = max(0.0, min(1.0, score))
    return style


def detect_negative_reaction(user_text: str) -> bool:
    """检测用户输入是否为显式否定/纠正（v2.0 真实 negative 信号源）。

    与 v1.0 的 `detect_user_reaction`（依赖 GUI 行为，未被调用）不同，
    此函数在 AAA 节点内可直接判定，零外部依赖。
    """
    if not user_text:
        return False
    return any(re.search(p, user_text) for p in _NEGATIVE_PATTERNS)


def detect_user_reaction(continued: bool, interrupted: bool = False) -> str:
    """根据用户自然行为判定反馈信号

    Args:
        continued: AI 回复后用户是否继续输入（GUI 检测）
        interrupted: 用户是否打断 TTS（alt+g）
    Returns:
        "positive" / "negative"
    """
    if interrupted:
        return "negative"
    if continued:
        return "positive"
    # 无新输入也暂记中性（沉默离开在定时器超时后置 negative，由调用方决定）
    return "neutral"
