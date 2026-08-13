"""
第二轮 Prompt — 工具调用模板（当前预留，功能尚未开放）
"""
from prompt import _CONTEXT_HEADER, _prepare_ctx

# 工具执行模板（待工具功能上线后再完善）
# TOOL_EXEC_TEMPLATE = _CONTEXT_HEADER + """..."""


def build_tool_response(ctx):
    """工具调用结果回复（当前返回未开放的提示）"""
    _prepare_ctx(ctx)
    return {
        "_port": "reply", "data_type": "reply",
        "content": "抱歉，工具调用功能目前尚未开放。",
    }
