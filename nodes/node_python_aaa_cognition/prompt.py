"""
Prompt 拼接模块 - 构建发给 LLM 的提示词

三套独立输出模板（直接回复／检索记忆／工具调用），外层根据 LLM 选择调用对应模板。
"""

_CONTEXT_HEADER = """
### 输入上下文
当前对话用户：{identity_key}
你的自我认知：{self_cognition}
你的固定认知（长期不变的核心设定）：{fixed_cognition}
你的最近感受：{recent_feelings}
本周情感基调：{mood_trend}
你的他人认知（对用户）：{other_cognition}

本轮输入：
  用户文本：{user_text}
{attachment_context}

当前日期时间：{current_date} {current_time}
历史摘要：{history_summary}
用户信息：{user_info}
你的自我信息：{self_info}

{reflection_section}
"""

# ─── 模板一：直接回复 ──────────────────────────────────────────
DIRECT_TEMPLATE = _CONTEXT_HEADER + """
### 输出格式
【自然回复】
你给用户看的回复文本（禁止使用emoji和颜文字）
【心情】
1-4个字，如：开心、难过、好奇、平静
【想法】
1-2句话描述你此刻的内心想法
【事件摘要】
本轮对话的核心摘要，1-2句话 [重要性:1-5]
【自我认知】
你对自己的新认识
【他人认知】
你对用户的新认识
【用户信息】
key=值, key=值
【自我信息】
key=值, key=值
【记忆归档】
值得归档的记忆内容
【归档标签】
逗号分隔的标签，如：见闻, 日常"""

# ─── 模板二：检索记忆 ──────────────────────────────────────────
RETRIEVAL_TEMPLATE = _CONTEXT_HEADER + """
### 输出格式
【语意检索】
需要回忆的关键词，如：用户喜欢的电影"""

# ─── 模板三：工具调用（当前功能尚未开放） ─────────────────────
TOOL_TEMPLATE = _CONTEXT_HEADER + """
### 输出格式
【工具调用】
工具名 | 参数名=值"""

def build(ctx):
    """用上下文填充第一轮模板（LLM 可自主选择其他操作）"""
    _prepare_ctx(ctx)
    return DIRECT_TEMPLATE.format(**ctx) + """

（注意：你也可以输出【语意检索】关键词 来检索记忆，或输出【工具调用】来调用工具。）"""


def build_direct(ctx):
    """构建直接回复模板（独立使用）"""
    _prepare_ctx(ctx)
    return DIRECT_TEMPLATE.format(**ctx)


def build_retrieval(ctx):
    """构建检索记忆模板（独立使用）"""
    _prepare_ctx(ctx)
    return RETRIEVAL_TEMPLATE.format(**ctx)


def build_tool(ctx):
    """构建工具调用模板（独立使用）"""
    _prepare_ctx(ctx)
    return TOOL_TEMPLATE.format(**ctx)


def _prepare_ctx(ctx):
    """填充条件字段"""
    for key in ("reflection_section", "mood_trend"):
        if key not in ctx:
            ctx[key] = ""
    if ctx.get("reflection_prompt"):
        ctx["reflection_section"] = (
            f"{ctx['reflection_prompt']}\n"
            "请回顾上述历史自我认识，输出当前更深层的【自我认知】和【自我信息】。"
        )
    elif "reflection_section" not in ctx or not ctx["reflection_section"]:
        ctx["reflection_section"] = ""
