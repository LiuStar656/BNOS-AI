"""GUI 工具桥 — 文件通道，让 AI（AAA 节点等）通过写 JSON 文件操控 GUI。

阶段7：完全实现的 AI 操控通道。与 MessageManager 同构（文件消息队列）：
- 请求目录：nodes/shared/gui_tool_requests/<request_id>.json
    {"request_id": "...", "tool": "ui.navigate_page", "args": {...}}
- 响应目录：nodes/shared/gui_tool_responses/<request_id>.json
    {"request_id": "...", "ok": true/false, "message": "...", "data": ...}
- 能力清单：nodes/shared/gui_tool_schemas.json（启动时写入，AI 侧加载）

任何本地进程写一个请求文件即可操控 GUI（导航/刷新/建提案等）。
破坏性操作走提案审批（create_skin_proposal 不直接生效）。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from gui.core.event_bus import event_bus
from gui.core.messages import AI_EVENT
from gui.core.tool_registry import tool_registry

# 共享目录（与引擎节点同层，约定前缀避免与节点文件冲突）
_SHARED_DIR = Path(__file__).resolve().parent.parent.parent / "nodes" / "shared"
_REQUESTS_DIR = _SHARED_DIR / "gui_tool_requests"
_RESPONSES_DIR = _SHARED_DIR / "gui_tool_responses"
_SCHEMAS_FILE = _SHARED_DIR / "gui_tool_schemas.json"

_POLL_INTERVAL_MS = 600

# 耗时工具集合：在独立线程执行，避免阻塞 GUI 主线程（QTimer 轮询 / 界面渲染）
_HEAVY_TOOLS = {"dsh.run_task_sync"}


class ToolBridge(QObject):
    """文件通道轮询器 — 处理 AI 发来的工具调用请求"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer: QTimer | None = None
        self._running = False
        self._last_log = 0.0

    # ─── 生命周期 ─────────────────────────────────

    def start(self):
        """启动轮询 + 写能力清单"""
        _REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
        _RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
        self.write_schemas()
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._poll)
        self._timer.start(_POLL_INTERVAL_MS)
        self._running = True

    def stop(self):
        if self._timer is not None:
            self._timer.stop()
        self._running = False

    def write_schemas(self):
        """能力清单落盘（AI 能力接缝）"""
        tool_registry.to_file(_SCHEMAS_FILE)

    # ─── 轮询处理 ─────────────────────────────────

    def _poll(self):
        if not _REQUESTS_DIR.is_dir():
            return
        try:
            request_files = sorted(_REQUESTS_DIR.glob("*.json"))
        except OSError:
            return
        for path in request_files:
            self._handle_request(path)

    def _handle_request(self, path: Path):
        """处理单个工具请求：受理后立即删除请求文件；耗时工具转独立线程执行"""
        try:
            request = json.loads(path.read_text(encoding="utf-8"))
            request_id = str(request.get("request_id") or uuid.uuid4().hex[:8])
            tool_name = request.get("tool", "")
            args = request.get("args") or {}
        except json.JSONDecodeError:
            self._log(f"跳过非法请求文件: {path.name}")
            return
        except Exception as exc:  # 读取异常不影响后续请求
            self._log(f"读取请求 {path.name} 失败: {exc}")
            return
        finally:
            try:
                path.unlink()
            except OSError:
                pass

        if not tool_name:
            self._exec_and_respond(request_id, tool_name, {"ok": False, "message": "缺少 tool 字段"})
            return

        if tool_name in _HEAVY_TOOLS:
            # 耗时工具（如 dsh.run_task_sync 等待分钟级任务）：独立线程执行，
            # 避免冻结 GUI 主线程；event_bus 基于 Qt Signal，跨线程 emit 自动回主线程
            threading.Thread(
                target=self._exec_and_respond,
                args=(request_id, tool_name, args),
                daemon=True,
            ).start()
        else:
            self._exec_and_respond(request_id, tool_name, args)

    def _exec_and_respond(self, request_id: str, tool_name: str, args: dict):
        """执行工具并回写响应（可在任意线程运行）"""
        outcome = tool_registry.execute(tool_name, args)
        result = {
            "request_id": request_id,
            "ok": outcome.get("ok", False),
            "message": outcome.get("message", ""),
            "data": outcome.get("data"),
        }
        # P0-2：实时事件推送（AI 操作可见）
        event_bus.publish(AI_EVENT, {
            "type": "tool",
            "text": f"工具 {tool_name}：{result['message']}",
        })
        # 回写响应（同一 request_id）
        try:
            (_RESPONSES_DIR / f"{request_id}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            self._log(f"回写响应失败: {exc}")

    def _log(self, message: str):
        now = time.time()
        if now - self._last_log > 1.0:  # 限频
            self._last_log = now
            print(f"[ToolBridge] {message}")


# 模块级单例
tool_bridge = ToolBridge()
