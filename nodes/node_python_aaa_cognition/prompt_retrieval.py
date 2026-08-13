"""
第二轮 Prompt — 检索记忆后带结果的直接回复模板
"""
from prompt import _CONTEXT_HEADER, _prepare_ctx

SECOND_TEMPLATE = _CONTEXT_HEADER + """
### 记忆检索结果
{retrieval_results}

### 输出格式
请根据上述检索结果，生成最终回复。
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


def build_second(ctx):
    """用上下文填充第二轮模板（带检索结果，仅直接回复格式）"""
    _prepare_ctx(ctx)
    ctx["retrieval_results"] = ctx.pop("memos_top5", "")
    return SECOND_TEMPLATE.format(**ctx)
