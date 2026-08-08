"""
retrieval_gate.py — 检索门控（输入侧，向量锚点）

判断「这轮对话需不需要预取记忆」。与兴趣门控（interest gate，判断 agent 对
话题感不感兴趣）同构：都用向量判定，但判断对象是「这轮是否在回忆/询问旧经历」。

判定模式（config.retrieval_gate.mode，默认 off = 现状每轮强制预取）：
  - off      关闭门控，每轮强制预取（v4.0 现状）
  - symbol   符号规则兜底（embedding 服务不可用时）
  - single   向量锚点单阈值：score >= t1 → 预取，否则跳过
  - dual     双阈值 + LLM 模糊区精判：score < t1 跳过，> t2 预取，
             [t1, t2] 模糊区调一次 LLM 精判（无 judge 回调时保守预取）

设计输入（E1 实测 20260808_211410，all-MiniLM-L6-v2 + 6 条回忆询问原型）：
  - 正例最小 0.759（「我上次说的考试还记得吗」带问号，无问号 0.793）
  - 负例最高 0.904（「你觉得我应该怎么规划找工作」——英文模型中文语义坍塌）
  - 单阈值不可行（0.759 与 0.904 区间重叠）→ 必须双阈值分层
  - 默认 t1=0.75 / t2=0.95：t2 高于所有负例保证直接放行的都是强正例，
    模糊区 [0.75, 0.95] 交 LLM 精判区分「考试回忆」与「找工作规划」

阈值按具体 embedding 模型标定（同模型同温度），换模型须重标。
"""
import re

import numpy as np


# ── 意图原型（v1.4 规划：按记忆类型分组，捕捉「回忆/询问旧经历」语义）──
# 分组仅用于区分「触发哪类记忆表检索」，门控分数取所有原型的最大相似度。
INTENT_PROTOTYPES: dict[str, list[str]] = {
    "回忆询问": [
        "你还记得我之前说过的事情吗",
        "我之前说的考试你还记得吗",
        "我们之前聊过什么",
        "上回那件事后来怎么样了",
    ],
    "用户事实询问": [
        "你记得我喜欢什么吗",
        "我的猫叫什么名字",
        "你还记得我的事吗",
        "我说过的爱好是什么",
    ],
    "关系询问": [
        "其他朋友之前说过什么",
        "别人提过的事情你还记得吗",
    ],
}

# 符号规则兜底（仅 embedding 不可用时，规则判定低相关 → 跳过预取）
_KNOWN_TERMS = ["电影", "猫", "考试", "名字", "喜欢", "还记得", "记得", "上次", "上回",
                "之前", "专升本", "星际穿越", "二饼", "说过", "聊过", "后来"]


def _symbol_gate(text: str) -> bool:
    """符号规则：疑问句（回忆语义常见形态）或含已知记忆词 → 预取"""
    t = text.strip()
    if t.endswith("？") or t.endswith("?") or t.endswith("吗"):
        return True
    return any(k in text for k in _KNOWN_TERMS)


# ── 配置 ──────────────────────────────────────────────────────
# 惰性从 node_config.json 读取（E6 实验可覆盖 config._config 切换模式）
_DEFAULTS = {"mode": "off", "t1": 0.75, "t2": 0.95}


def _cfg() -> dict:
    try:
        from config import load_config
        g = (load_config() or {}).get("retrieval_gate") or {}
    except Exception:
        g = {}
    merged = dict(_DEFAULTS)
    merged.update(g or {})
    return merged


def get_mode() -> str:
    return str(_cfg().get("mode", "off")).lower()


# ── 向量锚点 ──────────────────────────────────────────────────
_proto_vecs: np.ndarray | None = None


def _ensure_proto_vecs() -> np.ndarray | None:
    """预计算意图原型向量；embedding 模型未就绪时返回 None（走符号兜底）"""
    global _proto_vecs
    if _proto_vecs is not None:
        return _proto_vecs
    import memos
    model = memos._get_model(timeout=0)
    if model is None:
        return None
    vecs = []
    for group_texts in INTENT_PROTOTYPES.values():
        for p in group_texts:
            v = memos._encode(p)
            if v is not None:
                vecs.append(v)
    if not vecs:
        return None
    _proto_vecs = np.array(vecs)
    return _proto_vecs


def reset_proto_vecs():
    """清空原型向量缓存（换模型/换库后调用）"""
    global _proto_vecs
    _proto_vecs = None


def gate_score(text: str) -> float | None:
    """输入与意图原型的最大余弦相似度；模型未就绪返回 None"""
    vecs = _ensure_proto_vecs()
    if vecs is None:
        return None
    import memos
    qv = memos._encode(text)
    if qv is None:
        return None
    return float((vecs @ qv).max())


# ── LLM 模糊区精判 ───────────────────────────────────────────
_llm_judge = None


def set_llm_judge(fn):
    """注入模糊区精判回调（E6 实验传真 LLM；生产默认 None = 模糊区保守预取）。
    fn(text: str) -> bool：True=需要记忆 / False=不需要"""
    global _llm_judge
    _llm_judge = fn


# ── 主接口 ────────────────────────────────────────────────────
def should_prefetch(text: str) -> tuple[bool, dict]:
    """判定这轮对话是否需要预取记忆。

    Returns:
        (是否预取, 判定详情)。详情含 mode / decision / score / group，
        供 E6 统计与调试（无需预取时上层跳过 prefetch 调用）。
    """
    cfg = _cfg()
    mode = str(cfg.get("mode", "off")).lower()
    info = {"mode": mode, "decision": "", "score": None, "group": ""}

    if mode == "off":
        info["decision"] = "prefetch"
        return True, info

    if mode == "symbol":
        decision = _symbol_gate(text)
        info["decision"] = "prefetch" if decision else "skip"
        return decision, info

    # 向量锚点（single / dual）
    score = gate_score(text)
    if score is None:
        # embedding 未就绪 → 符号规则兜底
        decision = _symbol_gate(text)
        info["decision"] = "prefetch" if decision else "skip"
        info["note"] = "embedding_unavailable"
        return decision, info

    info["score"] = round(score, 3)
    t1 = float(cfg.get("t1", _DEFAULTS["t1"]))
    t2 = float(cfg.get("t2", _DEFAULTS["t2"]))

    if mode == "single":
        decision = score >= t1
        info["decision"] = "prefetch" if decision else "skip"
        return decision, info

    # dual：双阈值分层
    if score < t1:
        info["decision"] = "skip"
        info["layer"] = "t1"
        return False, info
    if score > t2:
        info["decision"] = "prefetch"
        info["layer"] = "t2"
        return True, info

    # 模糊区 [t1, t2] → LLM 精判（无回调时保守预取）
    info["layer"] = "gray"
    if _llm_judge is None:
        info["decision"] = "prefetch"
        info["judge"] = "na"
        return True, info
    try:
        decision = bool(_llm_judge(text))
    except Exception:
        decision = True  # 精判异常保守预取
    info["decision"] = "prefetch" if decision else "skip"
    info["judge"] = "llm"
    return decision, info
