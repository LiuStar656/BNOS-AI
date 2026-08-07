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
            buf.append(line)
    if current is not None:
        _store_section(r, current, "\n".join(buf))
    return r


def _store_section(r, k, v):
    """存入一个节的解析结果；空节/无内容节直接跳过"""
    v = v.strip()
    if not v:
        return
    if k == "工具调用":
        ts = []
        for line in v.split("\n"):
            line = line.strip()
            if "|" not in line:
                continue
            name, _, rest = line.partition("|")
            args = {}
            for kv in rest.split(","):
                kv = kv.strip()
                if "=" in kv:
                    kk, vv = kv.split("=", 1)
                    args[kk.strip()] = vv.strip()
            ts.append({"tool_name": name.strip(), "args": args})
        r[k] = ts
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
