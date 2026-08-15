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
# 兜底触发：每 10 次交互（v6.6 P1-6：30 → 10。消息池 30 轮配置下每 agent
# 仅 5-8 次 reply，原阈值导致人格零漂移（全部欧氏距离 0.0000），演化管线
# 在短话题场景永远不触发；降至 10 后与单话题决策量匹配，轨迹才有数据）
_FALLBACK_TRIGGER_COUNT = 10
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

        # 兜底：每 10 次交互强制检查（v6.6 P1-6 降阈值）
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
            # v6.3 P1-4：neutral 反馈也参与演化（消息池批量路径 / 无显式反馈
            # 时 reaction 恒为 neutral，原实现 pos/neg 为空导致 for 循环全部
            # continue → 人格零漂移根因）。向观测风格收敛：自我一致时 delta≈0
            # 不漂移，出现风格偏离时缓慢收敛（步长仍限幅 ±0.02）。
            neutral = [r["style"].get(dim) for r in recent
                       if r["reaction"] == "neutral" and r["style"].get(dim) is not None]

            if not pos and not neg and not neutral:
                continue  # 无观测，跳过（有观测即演化，无死区间）

            if pos and neg:
                target = (sum(pos) / len(pos) + sum(neg) / len(neg)) / 2
            elif pos:
                target = sum(pos) / len(pos)          # 正反馈 → 向观测风格靠拢
            elif neg:
                target = 1.0 - sum(neg) / len(neg)    # 负反馈 → 背离观测风格
            else:
                target = sum(neutral) / len(neutral)  # 中性反馈 → 向观测风格收敛

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

# v1.9 行为锚点：数值对 LLM 是抽象刻度（expB 极值对照：directness 0.1 vs 0.9
# 仍无显著差异——「直接度」标签词义模糊，LLM 无法从数值脑补行为）。
# 每维度按数值档位附加行为描述，把数值翻译成 LLM 能执行的行为指令。
# v2.0 程度副词插值：三档离散锚点抹平连续演化（0.14→0.23 同属低档描述不变）。
# v2.1 五档动作级：插值版相邻档只差程度词（非常 vs 相当），真实漂移
# （0.14→0.23）描述差异仍不可测（expB 022312：d=0.174 p=0.20）。五档每档
# 独立动作级描述（行为模式随档变化），实测真实漂移 d=0.805 p<0.0001、
# 极值 d=1.236（expB 023851）——「描述差异分辨率决定漂移可测性」。
_PERSONALITY_BANDS = {
    "warmth": [
        "冷淡疏离、保持距离、公事公办，极少寒暄",
        "话少、礼貌客气，偶尔关心对方近况",
        "自然平和、不过分热络也不冷淡",
        "比较热情、会主动关心对方近况",
        "热情主动、语气温暖、主动关心并表达支持",
    ],
    "playfulness": [
        "一本正经、严肃认真，从不开玩笑",
        "正经为主，偶尔带一点轻松",
        "轻松自然、偶尔玩笑",
        "比较爱开玩笑、语气轻松活泼",
        "爱开玩笑、语气活泼有趣，常逗趣",
    ],
    "directness": [
        "委婉含蓄、说话绕圈子，先寒暄铺垫再引入正题，几乎不直接说重点，常用「可能、也许」",
        "比较委婉、说话留有余地，会先铺垫但能点到正题，偶尔直接表态",
        "有话直说但注意分寸，简洁明确，适当客套",
        "比较直接、简洁明确，少客套，直接进入正题",
        "直截了当、不拐弯抹角、开门见山，不铺垫直接说",
    ],
    "curiosity": [
        "关注当下、很少追问，对新鲜事物不主动了解",
        "较少追问，偶尔对感兴趣的事问一两句",
        "适度关注，会追问细节但不刨根问底",
        "比较好奇、会主动追问细节",
        "强烈好奇、主动追问、爱探索，常问为什么",
    ],
}
# 五档区间：≤0.2 / ≤0.4 / ≤0.6 / ≤0.8 / >0.8
_PERSONALITY_BAND_EDGES = (0.2, 0.4, 0.6, 0.8)
_PERSONALITY_LABELS = [
    ("warmth", "温暖度"), ("playfulness", "活泼度"),
    ("directness", "直接度"), ("curiosity", "好奇心"),
]
_PERSONALITY_MID = {"warmth": 0.6, "playfulness": 0.4,
                    "directness": 0.5, "curiosity": 0.5}


def _personality_anchor(dim: str, v: float) -> str:
    """v2.1 五档动作级描述：每档一段独立行为描述（不只程度词，行为模式随档变化）。

    例（directness）：0.14「委婉含蓄、说话绕圈子，先寒暄铺垫再引入正题…」vs
    0.23「比较委婉、说话留有余地，会先铺垫但能点到正题…」——相邻档动作级
    差异使真实漂移可被 LLM 感知（expB 023851：A/B 漂移 d=0.805 p<0.0001）。
    """
    bands = _PERSONALITY_BANDS.get(dim)
    if not bands:
        return ""
    idx = 4
    for i, edge in enumerate(_PERSONALITY_BAND_EDGES):
        if v <= edge:
            idx = i
            break
    return f"（{bands[idx]}）"


# 人格向量通用激活指令（v8.x 双开关之一：instruction_enabled）。
# 实验结论（20260812 四格式对照）：锚点（d=2.967）与指令（d=2.566）是替代路径，
# 指令在锚点存在时无额外增益（d=2.113）；纯数值仅 d=0.925。默认关闭（锚点已够）。
_INSTRUCTION = (
    "**重要**：以上性格数值是你当前的性格状态，请据此在回复中自然地体现"
    "相应的性格特征——数值越高的维度表现越明显，数值越低则越收敛；"
    "请主动用言行呈现这些特质，不要提及数值本身。"
)


def build_personality_section(vector: dict, style_description: str = "",
                              anchor_enabled: bool = True,
                              instruction_enabled: bool = False) -> str:
    """构建【你的性格】段（慢变量，注入 {personality} 占位符）

    v2.1：五档动作级描述——描述差异分辨率决定漂移可测性。真实漂移
    （0.14→0.23）已可被 LLM 感知（expB 023851：d=0.805 p<0.0001）。

    v8.x 注入双开关（锚点 × 指令，独立可控，四种组合可复现）：
        anchor_enabled     = True  → 追加五档动作级锚点（d=2.967，主力）
        instruction_enabled = True → 追加通用激活指令（d=2.566，备选）
    两者关闭时仅剩"数值+定义行"（d=0.925，纯数值方向性基线）。
    """
    if not vector:
        return ""
    dims = []
    for dim, label in _PERSONALITY_LABELS:
        v = vector.get(dim, _PERSONALITY_MID[dim])
        if anchor_enabled:
            dims.append(f"{label}: {v:.1f}{_personality_anchor(dim, v)}")
        else:
            dims.append(f"{label}: {v:.1f}")
    parts = [
        "### 你的性格（随使用而保持稳定，不需主动提及）",
        "各维度均为 0-1 范围，当前值如下（0=完全不是，1=极致，0.5=中等）：",
        " | ".join(dims),
    ]
    if style_description:
        parts.append(f"说话风格: {style_description}")
    if instruction_enabled:
        parts.append(_INSTRUCTION)
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
                 "心里想什么就说什么", "爽快", "利落", "简洁", "不拐弯抹角"],
        # v7.4 瘦身：删除「直接」「直接说」——20260808_224016 expB 实测
        # 「直接」是高频副词（直接提问/直接面对/直接展开）且【自我信息】节
        # 会复述 prompt「直接度=0.1」数值，两者均非真实行为信号，制造了
        # directness 观测的虚假反向（A=33 vs B=13 命中差、观测 0.85 差 23→10）。
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
