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
你的他人认知{other_cognition_label}：{other_cognition}

本轮输入：
{user_text_section}
{attachment_context}

{perception}

{location_section}

{personality}

{mood}

当前日期时间：{current_date} {current_time}
历史摘要：{history_summary}
用户信息：{user_info}
你的自我信息：{self_info}

{reflection_section}
"""

# ─── 模板一：直接回复 ──────────────────────────────────────────
DIRECT_TEMPLATE = _CONTEXT_HEADER + """
### 输出格式
**硬性要求：每个【节标记】必须独占一行，后面换行写内容；所有内容（包括对用户的回复正文）都必须放在对应节内，严禁写在节标记之外或输出任何前言。**

【自然回复】
你给用户看的回复文本（禁止使用emoji和颜文字）
【心情】
1-4个字，如：开心、难过、好奇、平静
【想法】
1-2句话描述你此刻的内心想法
【情绪调整】
1个数字（范围 -0.2 到 +0.2，表示你希望情绪值的调整幅度，不是绝对值；情绪平稳时输出 0.0）
【事件摘要】
本轮对话的核心摘要，1-2句话 [重要性:1-5]
【自我认知】
你对自己的新认识
【他人认知】
你对当前对话对象 {current_user_label} 的新认识（必须点名对象、具体描述其言行特点，禁止用笼统的"用户"二字）
【用户信息】
key=值, key=值（针对当前对话对象 {current_user_label}）
【自我信息】
key=值, key=值
【用户记忆】
关于当前对话对象 {current_user_label} 的信息（喜好、习惯、身份），具体详细描述，没有可留空
【环境记忆】
关于环境/物品/空间的信息（最多3条），没有可留空
【实体名】
如果有环境记忆，标注对应的实体名称（逗号分隔），没有可留空
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
    for key in ("reflection_section", "mood_trend", "perception", "location_section",
                "personality", "mood", "other_cognition_label", "user_text_section",
                "pool_batch_section", "current_user_label"):
        if key not in ctx:
            ctx[key] = ""
    # v6.0 多用户：他人认知注入标签（对指定用户 / 对用户）
    if not ctx.get("other_cognition_label"):
        ctx["other_cognition_label"] = f"（对 {ctx.get('user_id')}）" if ctx.get("user_id") else "（对用户）"
    # v6.1 多用户：认知描述点名对象（他人认知/用户信息/用户记忆必须指名，避免歧义）
    if not ctx.get("current_user_label"):
        ctx["current_user_label"] = ctx.get("user_id") or "用户"
    # v6.0 批量输入：消息池合并段优先；否则回退单条用户文本
    if ctx.get("pool_batch_section"):
        ctx["user_text_section"] = ctx["pool_batch_section"]
    else:
        ctx["user_text_section"] = f"  用户文本：{ctx.get('user_text', '')}"
    if ctx.get("reflection_prompt"):
        ctx["reflection_section"] = (
            f"{ctx['reflection_prompt']}\n"
            "请回顾上述历史自我认识，输出当前更深层的【自我认知】和【自我信息】。"
        )
    elif "reflection_section" not in ctx or not ctx["reflection_section"]:
        ctx["reflection_section"] = ""

    # v1.3: 注入位置信息段（如未提供则按 db_path + identity_key 查询）
    if not ctx.get("location_section"):
        db_path = ctx.get("db_path", "")
        identity_key = ctx.get("identity_key", "")
        if db_path and identity_key:
            try:
                import location as _loc
                ctx["location_section"] = _loc.build_location_section(
                    db_path, identity_key)
            except Exception:
                ctx["location_section"] = ""
