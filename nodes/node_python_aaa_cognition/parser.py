"""
节标记解析模块 - 解析 LLM 回执 + 情绪标签注入
"""
import re

_MOOD_MAP = {"开心": "开心", "高兴": "开心", "愉快": "开心", "兴奋": "开心",
              "难过": "难过", "伤心": "难过", "沮丧": "难过", "低落": "难过",
              "生气": "生气", "愤怒": "生气", "烦躁": "生气",
              "惊讶": "惊讶", "震惊": "惊讶", "好奇": "惊讶",
              "害羞": "害羞", "俏皮": "俏皮", "调皮": "俏皮"}

_SECTION_LINE = re.compile(r"^【(.+?)】\s*$")
# v6.5 截断防御：未闭合的节标记行（如"【情绪调整"被 max_tokens 截断、
# 缺右括号）不是正文，不应并入上一节——否则会污染该节内容
_SECTION_FRAGMENT = re.compile(r"^【[^】]{1,16}$")


def is_truncated(raw: str) -> bool:
    """截断启发式检测（v6.6 P1-4 输出完整性校验）。

    两个信号：
    1) 输出以未闭合节标记结尾（如 `【情绪调整` 被截断，无右括号）——
       说明输出在节标记处中断，其后的小节（想法/回应对象等）全部丢失；
    2) 解析后【自然回复】有文本但【情绪调整】缺失——prompt 硬性要求
       reply/silent 都必须输出情绪调整数字，缺失说明输出被截断。

    Returns:
        True=判定为截断（调用方应重试一次）；False=输出看起来完整。
    """
    if not raw or not raw.strip():
        return False  # 空输出视为静默/无内容，不属于"截断"
    tail = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    if tail and _SECTION_FRAGMENT.match(tail[-1]):
        return True
    try:
        parsed = parse_llm_output(raw)
        if parsed.get("自然回复") and not parsed.get("情绪调整"):
            return True
    except Exception:
        pass
    return False


def parse_llm_output(text):
    """解析节标记文本为结构化 dict。

    基于行的节切分：节标记独占一行时开新节，空节直接跳过，
    修复原正则实现的「空节吞并」问题（空节把后续节并入自身）。

    扩展：从节内容中提取 [importance=N] 属性。
    """
    r = {}
    current = None
    buf = []
    for line in text.split("\n"):
        m = _SECTION_LINE.match(line.strip())
        if m:
            if current is not None:
                _store_section(r, current, "\n".join(buf))
            current = m.group(1).strip()
            buf = []
        elif current is not None:
            # v6.5 截断防御：残缺节标记行跳过，不并入上一节
            if _SECTION_FRAGMENT.match(line.strip()):
                continue
            buf.append(line)
    if current is not None:
        _store_section(r, current, "\n".join(buf))
    return r


def _parse_call_lines(v):
    """解析「工具名 | 参数名=值, 参数名=值」行列表（工具调用/流程选择共用）。

    值可能为 JSON 对象（含逗号），按闭合大括号合并解析为 dict。
    """
    import json as _json

    items = []
    for line in v.split("\n"):
        line = line.strip()
        if "|" not in line:
            continue
        name, _, rest = line.partition("|")
        args = {}
        parts = rest.split(",")
        i = 0
        while i < len(parts):
            kv = parts[i].strip()
            if "=" not in kv:
                i += 1
                continue
            kk, vv = kv.split("=", 1)
            kk, vv = kk.strip(), vv.strip()
            # 值以 { 开头 → JSON 对象，合并含逗号的后续片段直到闭合
            if vv.startswith("{"):
                j = i
                merged = vv
                while not merged.endswith("}") and j + 1 < len(parts):
                    j += 1
                    merged += "," + parts[j].strip()
                i = j
                try:
                    vv = _json.loads(merged)
                except _json.JSONDecodeError:
                    vv = merged
            args[kk] = vv
            i += 1
        items.append((name.strip(), args))
    return items


def _store_section(r, k, v):
    """存入一个节的解析结果；空节/无内容节直接跳过"""
    v = v.strip()
    if not v:
        return
    if k == "工具调用":
        r[k] = [{"tool_name": name, "args": args}
                for name, args in _parse_call_lines(v)]
    elif k == "流程选择":
        r[k] = [{"flow_id": name, "args": args}
                for name, args in _parse_call_lines(v)]
    else:
        # 提取 [importance=N] 属性
        importance = None
        imp_m = re.search(r"\[importance=(\d+)\]", v)
        if imp_m:
            importance = int(imp_m.group(1))
            v = v.replace(imp_m.group(0), "").strip()
        r[k] = v
        if importance is not None:
            r[f"{k}_importance"] = importance


def inject_mood_tag(reply, mood=""):
    """在回复前插入情绪标签，供 Live2D 使用"""
    tag = ""
    for k, v in _MOOD_MAP.items():
        if k in mood:
            tag = v
            break
    return f"<{tag}>{reply}" if tag else reply
