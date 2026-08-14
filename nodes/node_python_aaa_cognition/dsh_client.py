"""
DSH 节点通道客户端（AAA 侧）— 直连 node_dsh，不经 GUI 工具桥。

node_dsh 是标准 BNOS 节点：listener 轮询 nodes/shared/dsh_task_in.json
（filter data_type=dsh_task）→ 执行 DSH → 结果写 nodes/node_dsh/output.json。

本模块提供：
- submit_task()：写任务文件（原子替换，带唯一 task_id）
- read_result()：按 task_id 精确读取结果（不匹配视为未完成/旧结果）
- wait_result()：同步等待（后台线程用，超时返回 None）

不依赖 GUI 进程；BNOS 引擎启动 node_dsh listener 即可工作。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_NODES_DIR = _PROJECT_ROOT / "nodes"
_REQ_FILE = _NODES_DIR / "shared" / "dsh_task_in.json"
_OUT_FILE = _NODES_DIR / "node_dsh" / "output.json"
_NODE_CONFIG = _NODES_DIR / "node_dsh" / "node_config.json"
_GUI_REPLY_FILE = _NODES_DIR / "shared" / "gui_reply.json"

# 与 node_dsh listener / GUI run_task_sync 对齐的轮询与超时
POLL_STEP = 1.0
DEFAULT_TIMEOUT = 600  # 与 node_dsh DSH_TIMEOUT / GUI 默认一致


def push_reply(content: str, request_id: str = "") -> bool:
    """直写 gui_reply.json（异步回执推送通道，格式与 listener 的 reply 写出一致）。

    AAA listener 在 reply 端口输出时也会写该文件；后台线程完成 DSH 后
    主动推送结果复用同一通道，GUI MessageManager 按 data_type=reply 显示。
    沿用原请求 request_id（poll_reply 同 id 放行；用户已发新消息则旧结果被丢弃）。
    """
    try:
        payload = {"data_type": "reply", "content": str(content)}
        if request_id:
            payload["request_id"] = request_id
        _GUI_REPLY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _GUI_REPLY_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


def node_ready() -> bool:
    """node_dsh 节点是否存在（listener 是否可消费由 BNOS 引擎保证）。"""
    return _NODE_CONFIG.is_file()


def submit_task(task: str, session_id: str = "", context: dict | None = None) -> dict:
    """提交 DSH 任务到 node_dsh（写 dsh_task_in.json）。

    Args:
        task: 任务描述（工作模式直通时为用户输入）
        session_id: 非空则续接 DSH 已有会话（多轮对话）
        context: 工作模式直通时携带的 AAA 完整上下文（node_dsh 拼入 task 前缀）

    Returns:
        {"ok": True, "data": {"task_id", "submitted": True}} 或失败 dict。
    """
    task = str(task).strip()
    if not task:
        return {"ok": False, "message": "缺少 task 字段"}
    if not node_ready():
        return {"ok": False, "message": "node_dsh 节点不存在（未启动或未安装）"}
    task_id = uuid.uuid4().hex[:12]
    payload = {
        "data_type": "dsh_task",
        "task": task,
        "task_id": task_id,
        "_ts": time.time(),
    }
    if session_id:
        payload["session_id"] = session_id
    if context:
        payload["context"] = context
    try:
        _REQ_FILE.parent.mkdir(parents=True, exist_ok=True)
        _REQ_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "message": f"提交失败: {exc}"}
    return {
        "ok": True,
        "message": "DSH 任务已提交（node_dsh 异步执行）",
        "data": {"task_id": task_id, "submitted": True},
    }


def read_result(task_id: str) -> dict | None:
    """按 task_id 精确读取 node_dsh 执行结果。

    Returns:
        node_dsh 返回的内层 dict（含 ok/message/result/final/session_id），
        未完成 / task_id 不匹配 / 读取失败返回 None。
    """
    if not task_id or not _OUT_FILE.is_file():
        return None
    try:
        data = json.loads(_OUT_FILE.read_text(encoding="utf-8"))
        inner = data.get("data", data) if isinstance(data, dict) else data
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(inner, dict) or inner.get("task_id") != task_id:
        return None
    return inner


def wait_result(task_id: str, timeout: float = DEFAULT_TIMEOUT) -> dict | None:
    """同步等待任务完成（后台线程用）。

    Returns:
        完成时返回内层 dict；超时返回 None（任务仍在后台执行）。
    """
    deadline = time.time() + max(1.0, timeout)
    while time.time() < deadline:
        result = read_result(task_id)
        if result is not None:
            return result
        time.sleep(POLL_STEP)
    return None
