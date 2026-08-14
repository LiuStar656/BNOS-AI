"""
GUI 工具消费模块（P0-1）— AAA 侧调用 GUI 工具的文件桥客户端。

与 GUI 的 ToolBridge（gui/core/tool_bridge.py）对接：
- load_schemas()：读取 GUI 暴露的工具清单（gui_tool_schemas.json），供 prompt 注入
- call_tool()：写请求文件 → 轮询响应 → 返回结果

调用链路：AAA 输出【工具调用】→ main.py 解析 → call_tool → GUI ToolBridge 轮询执行
→ 回写响应 → AAA 收到结果并转述给用户。破坏性变更走提案审批，不会直接生效。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

# 共享目录（与 GUI 工具桥同层）
_SHARED_DIR = Path(__file__).resolve().parent.parent.parent / "nodes" / "shared"
_REQUESTS_DIR = _SHARED_DIR / "gui_tool_requests"
_RESPONSES_DIR = _SHARED_DIR / "gui_tool_responses"
_SCHEMAS_FILE = _SHARED_DIR / "gui_tool_schemas.json"

# 单次工具调用超时（GUI 轮询间隔 600ms，正常 1-2s 内可完成）
_CALL_TIMEOUT = 8.0
_POLL_STEP = 0.3

# 流程库文件（与 GUI workflow_store 共享）
_WORKFLOWS_FILE = _SHARED_DIR / "workflows.json"


def load_schemas() -> list[dict]:
    """读取 GUI 工具清单（AI 能力接缝）。GUI 未启动或文件缺失时返回空列表。"""
    if not _SCHEMAS_FILE.is_file():
        return []
    try:
        data = json.loads(_SCHEMAS_FILE.read_text(encoding="utf-8"))
        tools = data.get("tools", [])
        return tools if isinstance(tools, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def tool_list_text() -> str:
    """生成工具清单的 prompt 注入文本（供 LLM 决策是否调用）"""
    schemas = load_schemas()
    if not schemas:
        return ""
    lines = ["（你可以输出【工具调用】节来操控 GUI，当前可用工具："]
    for t in schemas:
        req = f"｜必填: {', '.join(t['required'])}" if t.get("required") else ""
        lines.append(f"  · {t['name']}：{t.get('description', '')}{req}")
    lines.append(
        "调用格式：【工具调用】\\n工具名 | 参数名=值, 参数名=值\\n"
        "调用后 GUI 会执行并把结果告诉我。按需使用：用户请求 UI/主题/皮肤相关变更、"
        "DSH 任务或 Agent 预设管理、页面导航等均可调用。）"
    )
    return "\n".join(lines)


def workflows_text() -> str:
    """生成流程库 prompt 注入文本（含实时双引擎分数，驱动 LLM 流程决策）。

    分数越高表示流程越受信任（多巴胺=用户评价，用进废退=调用频次），
    LLM 决策时应倾向高分流程——双引擎反馈进入决策闭环。
    """
    flows = load_workflows()
    if not flows:
        return ""
    lines = [
        "（流程库：当用户请求匹配以下流程时，输出【流程选择】节，"
        "由流程执行而非逐个调用工具。分数=多巴胺×用进废退，越高越受信任："
    ]
    for w in flows:
        lines.append(
            f"  · {w.get('id', '')}（最终分 {w.get('final_score', 0)}｜"
            f"多巴胺 {w.get('dopamine', 0)}｜用进废退 {w.get('use_score', 0)}｜"
            f"已调用 {w.get('calls', 0)} 次）：{w.get('description', '')}"
        )
    lines.append(
        "输出格式：【流程选择】\\n流程id | 参数名=值, 参数名=值"
        "（如 skin_change | name=紫色皮肤, tokens={\"accent_color\":\"#7c3aed\"}）"
        "；不匹配任何流程时不要输出此节。"
    )
    return "\n".join(lines)


def load_workflows() -> list[dict]:
    """读取流程库（含双引擎分数）。GUI 未创建流程库时返回空列表。"""
    if not _WORKFLOWS_FILE.is_file():
        return []
    try:
        data = json.loads(_WORKFLOWS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def call_tool(tool_name: str, args: dict | None = None, timeout: float = _CALL_TIMEOUT) -> dict:
    """调用一个 GUI 工具，返回 {"ok", "message", "data"}。

    - 写请求文件 → GUI ToolBridge 轮询执行 → 回写响应 → 读取并删除响应文件
    - 超时兜底返回失败（不阻塞后续处理）
    """
    if not tool_name:
        return {"ok": False, "message": "缺少工具名", "data": None}
    _REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    _RESPONSES_DIR.mkdir(parents=True, exist_ok=True)

    request_id = uuid.uuid4().hex[:8]
    request_path = _REQUESTS_DIR / f"{request_id}.json"
    response_path = _RESPONSES_DIR / f"{request_id}.json"

    try:
        request_path.write_text(
            json.dumps(
                {"request_id": request_id, "tool": tool_name, "args": args or {}},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        return {"ok": False, "message": f"写请求文件失败: {exc}", "data": None}

    deadline = time.time() + timeout
    while time.time() < deadline:
        if response_path.is_file():
            try:
                result = json.loads(response_path.read_text(encoding="utf-8"))
                response_path.unlink(missing_ok=True)
                return result
            except (json.JSONDecodeError, OSError):
                time.sleep(_POLL_STEP)
                continue
        time.sleep(_POLL_STEP)

    return {"ok": False, "message": f"GUI 未响应（{tool_name} 调用超时）", "data": None}
