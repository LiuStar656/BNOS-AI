"""GUI 操控工具注册中心 — 把前 6 阶段能力封装为 AI 可调用的工具。

阶段7：完全实现。AI（AAA 节点等）通过工具操控 GUI：
- 工具定义：name / description / parameters(JSON Schema) / handler
- 执行引擎：execute(name, args) 统一入出，结果 {"ok", "message", "data"}
- 能力清单：schemas() 输出 JSON 序列化清单，供 AI 侧加载（工具卡片）

安全设计：破坏性变更走阶段6 提案机制（create_skin_proposal 生成 pending 提案，
审批后才生效）；导航/刷新/查询类工具直接执行但只发消息不改内部状态。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from gui.core.event_bus import event_bus
from gui.core.icon_registry import icons
from gui.core.messages import DATA_REFRESH_REQUESTED, NAVIGATE_REQUEST, THEME_CHANGED
from gui.core.proposal_store import proposal_store
from gui.core.workflow_store import workflow_store

# 工具结果
OK = "ok"
ERROR = "error"


@dataclass
class ToolSpec:
    """一个 GUI 操控工具"""

    name: str
    description: str
    parameters: dict = field(default_factory=dict)   # JSON Schema（properties）
    handler: Callable[[dict], dict] | None = None
    # required 参数名列表
    required: list[str] = field(default_factory=list)


class ToolRegistry:
    """GUI 工具注册中心（单例）。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._tools: dict[str, ToolSpec] = {}
        self._initialized = True
        self._register_builtin()

    # ─── 注册 ─────────────────────────────────────

    def register(self, spec: ToolSpec, *, replace: bool = False) -> None:
        """注册工具（冲突即设计：同名工具需 replace=True 覆盖）"""
        if spec.name in self._tools and not replace:
            raise ValueError(f"工具 '{spec.name}' 已注册，需 replace=True 覆盖")
        self._tools[spec.name] = spec

    # ─── 查询 ─────────────────────────────────────

    def list(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict]:
        """工具清单（JSON 序列化，供 AI 侧加载）"""
        out = []
        for spec in self.list():
            out.append({
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
                "required": spec.required,
            })
        return out

    def to_file(self, path) -> None:
        """能力清单落盘（AI 能力接缝：AAA 等节点读取了解 GUI 可操控项）"""
        payload = {"source": "bnos-ai-gui", "version": 1, "tools": self.schemas()}
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ─── 执行 ─────────────────────────────────────

    def execute(self, name: str, args: dict | None = None) -> dict:
        """执行工具，统一结果格式 {"ok", "message", "data"}"""
        spec = self.get(name)
        if spec is None:
            return {"ok": False, "message": f"未知工具: {name}", "data": None}
        if spec.handler is None:
            return {"ok": False, "message": f"工具 {name} 未实现", "data": None}
        try:
            result = spec.handler(args or {})
            if not isinstance(result, dict):
                result = {"ok": True, "message": "ok", "data": result}
            result.setdefault("ok", True)
            result.setdefault("message", "ok")
            return result
        except Exception as exc:  # 工具执行异常兜底
            return {"ok": False, "message": f"{name} 执行失败: {exc}", "data": None}

    # ─── 内置工具（阶段3/4/5/6 能力封装） ────────

    def _register_builtin(self):
        # ── 导航 / 刷新（发消息，不改内部状态） ──
        self.register(ToolSpec(
            name="ui.navigate_page",
            description="切换 GUI 页面到指定 id（可用 ui.list_pages 查询）",
            parameters={"page_id": {"type": "string", "description": "页面 id，如 chat/live2d/location/mcp/knowledge/proposals/tools"}},
            required=["page_id"],
            handler=lambda a: (event_bus.publish(NAVIGATE_REQUEST, a["page_id"]), {"ok": True, "message": f"已请求切换到 {a['page_id']}"})[1],
        ))
        self.register(ToolSpec(
            name="ui.list_pages",
            description="列出当前 GUI 全部页面（id 与标题）",
            handler=lambda a: {"ok": True, "message": "ok",
                               "data": [{"page_id": pid, "title": t[2]} for pid, t in zip(_page_ids(), _tabs())]},
        ))
        self.register(ToolSpec(
            name="ui.refresh_data",
            description="请求页面刷新数据（page_id 为空则刷新当前页）",
            parameters={"page_id": {"type": "string", "description": "页面 id"}},
            handler=lambda a: (event_bus.publish(DATA_REFRESH_REQUESTED, a.get("page_id")), {"ok": True, "message": "已请求刷新"})[1],
        ))

        # ── 主题 ──
        self.register(ToolSpec(
            name="ui.apply_preset",
            description="应用内置主题预设",
            parameters={"preset_id": {"type": "string", "description": "预设 id，如 default_light/dark/ubuntu"}},
            required=["preset_id"],
            handler=_apply_preset,
        ))

        # ── 皮肤包提案（阶段6 治理：生成提案，审批后生效） ──
        self.register(ToolSpec(
            name="ui.create_skin_proposal",
            description="创建皮肤包变更提案（待用户审批，不会直接生效）。tokens 为 token→颜色值 增量覆盖",
            parameters={
                "name": {"type": "string", "description": "皮肤包显示名"},
                "tokens": {"type": "object", "description": "如 {\"accent_color\": \"#7c3aed\", \"bg_primary\": \"#faf5ff\"}"},
                "mode": {"type": "string", "description": "可选 light/dark"},
                "description": {"type": "string", "description": "变更说明"},
            },
            required=["name", "tokens"],
            handler=_create_skin_proposal,
        ))
        self.register(ToolSpec(
            name="ui.approve_proposal",
            description="批准一条待审批的 UI 变更提案（皮肤包安装并应用）",
            parameters={"proposal_id": {"type": "string"}},
            required=["proposal_id"],
            handler=lambda a: _proposal_action("approve", a["proposal_id"]),
        ))
        self.register(ToolSpec(
            name="ui.reject_proposal",
            description="拒绝一条待审批的 UI 变更提案",
            parameters={"proposal_id": {"type": "string"}},
            required=["proposal_id"],
            handler=lambda a: _proposal_action("reject", a["proposal_id"]),
        ))
        self.register(ToolSpec(
            name="ui.revert_proposal",
            description="回退一条已生效的 UI 变更提案（恢复生效前状态）",
            parameters={"proposal_id": {"type": "string"}},
            required=["proposal_id"],
            handler=lambda a: _proposal_action("revert", a["proposal_id"]),
        ))

        # ── 图标覆盖（运行时生效，reset 可清） ──
        self.register(ToolSpec(
            name="ui.install_icon",
            description="运行时覆盖一个语义图标（如 title_close/node_start）",
            parameters={"name": {"type": "string"}, "char": {"type": "string", "description": "替换字符"}},
            required=["name", "char"],
            handler=lambda a: (icons.register(a["name"], a["char"]), {"ok": True, "message": f"图标 {a['name']} 已覆盖"})[1],
        ))

        # ── 流程库（P1-1：workflow + 双引擎） ──
        self.register(ToolSpec(
            name="ui.choose_workflow",
            description="按多巴胺 UCB 从流程库中选择最合适的流程（query 可选：限定匹配描述的流程）",
            parameters={"query": {"type": "string", "description": "可选，用户请求描述关键词"}},
            handler=lambda a: _choose_workflow(a),
        ))
        self.register(ToolSpec(
            name="ui.list_workflows",
            description="列出全部流程及其双引擎分数（多巴胺/用进废退/调用次数）",
            handler=lambda a: {"ok": True, "message": "ok", "data": workflow_store.summary()},
        ))
        self.register(ToolSpec(
            name="ui.run_workflow",
            description="执行一个流程（按流程步骤依次调用工具）。overrides 填充步骤中的 {{占位符}}",
            parameters={
                "flow_id": {"type": "string", "description": "流程 id（ui.list_workflows 查询）"},
                "overrides": {"type": "object", "description": "如 {\"name\": \"紫色皮肤\", \"tokens\": {...}, \"page_id\": \"tools\"}"},
            },
            required=["flow_id"],
            handler=lambda a: workflow_store.run(a["flow_id"], a.get("overrides")),
        ))
        self.register(ToolSpec(
            name="ui.rate_workflow",
            description="对某个流程给出外部评价（多巴胺显性反馈，更新 Q 值）",
            parameters={
                "flow_id": {"type": "string"},
                "positive": {"type": "boolean", "description": "true=正面 false=负面"},
            },
            required=["flow_id", "positive"],
            handler=lambda a: (
                {"ok": True, "message": "已记录评价"} if workflow_store.rate(a["flow_id"], bool(a["positive"]))
                else {"ok": False, "message": f"流程不存在: {a['flow_id']}"}
            ),
        ))

        # ── 查询 ──
        self.register(ToolSpec(
            name="ui.list_proposals",
            description="列出全部 UI 变更提案及其状态",
            handler=lambda a: {"ok": True, "message": "ok",
                               "data": [{"id": p.id, "title": p.title, "kind": p.kind, "status": p.status, "created_at": p.created_at}
                                        for p in proposal_store.list()]},
        ))
        self.register(ToolSpec(
            name="ui.get_theme_state",
            description="查询当前主题状态（预设/皮肤包/颜色）",
            handler=_get_theme_state,
        ))

        # ── DSH 执行器官（node_dsh 节点桥接） ──
        self.register(ToolSpec(
            name="dsh.run_task",
            description="把任务交给 DeepSeek Harness（node_dsh 节点）执行，返回提交状态；结果需用 dsh.check_task 查询（DSH Agent 任务通常需要数十秒到数分钟）。传 session_id 可续接同一会话的多轮对话（上下文延续）",
            parameters={
                "task": {"type": "string", "description": "自然语言任务描述，如「把 dsh_workspace 里 test.md 的 TODO 列出来」"},
                "session_id": {"type": "string", "description": "（可选）会话续接标识：dsh.check_task 返回的 session_id；不传则新建会话"},
            },
            required=["task"],
            handler=_run_dsh_task,
        ))
        self.register(ToolSpec(
            name="dsh.run_task_sync",
            description="把任务交给 DeepSeek Harness（node_dsh 节点）执行并同步等待完成，返回最终回答（适合流程步骤，流程会等到 DSH 任务真正结束）。传 session_id 可续接同一会话的多轮对话；等待超时后任务仍在后台继续，可用 dsh.check_task 补查",
            parameters={
                "task": {"type": "string", "description": "自然语言任务描述"},
                "session_id": {"type": "string", "description": "（可选）会话续接标识：dsh.check_task 返回的 session_id；不传则新建会话"},
                "timeout": {"type": "number", "description": "（可选）等待上限（秒），默认 600，与 node_dsh 超时一致"},
            },
            required=["task"],
            handler=_run_dsh_task_sync,
        ))
        self.register(ToolSpec(
            name="dsh.check_task",
            description="查询 node_dsh 最近一次 DSH 任务的执行结果",
            handler=_check_dsh_task,
        ))

        # ── DSH Agent 预设（AI 协作创建：DSH 官方允许 agent author user 预设）──
        self.register(ToolSpec(
            name="dsh.preset_list",
            description="列出全部 DSH Agent 预设（内置只读 + 自定义）及当前默认预设；每项含人格文本",
            handler=_list_presets_tool,
        ))
        self.register(ToolSpec(
            name="dsh.preset_copy",
            description="复制创建自定义 Agent 预设（DSH 唯一创建路径 = 整体复制现有预设；新 id 需匹配 ^[a-z0-9][a-z0-9-]*$）。创建后可用 dsh.preset_write / dsh.preset_persona 定制",
            parameters={
                "source_id": {"type": "string", "description": "源预设 id（dsh.preset_list 查询）"},
                "new_id": {"type": "string", "description": "新预设 id（目录名，小写字母/数字/中划线）"},
                "name": {"type": "string", "description": "（可选）显示名"},
            },
            required=["source_id", "new_id"],
            handler=_preset_copy_tool,
        ))
        self.register(ToolSpec(
            name="dsh.preset_read",
            description="读取预设详情：file 传 agent.cordis.yml / preset.yml 返回文件内容；不传 file 返回元信息与人格",
            parameters={
                "preset_id": {"type": "string"},
                "file": {"type": "string", "description": "（可选）agent.cordis.yml / preset.yml"},
            },
            required=["preset_id"],
            handler=_preset_read_tool,
        ))
        self.register(ToolSpec(
            name="dsh.preset_write",
            description="写入自定义预设文件：agent.cordis.yml（插件行列表，保存前组合校验）或 preset.yml（YAML 映射）",
            parameters={
                "preset_id": {"type": "string"},
                "file": {"type": "string", "description": "agent.cordis.yml / preset.yml"},
                "content": {"type": "string", "description": "完整文件内容"},
            },
            required=["preset_id", "file", "content"],
            handler=_preset_write_tool,
        ))
        self.register(ToolSpec(
            name="dsh.preset_persona",
            description="读写预设人格：传 text = 写入（空串 = 移除该预设人格，继承部署默认）；不传 text = 读取当前人格",
            parameters={
                "preset_id": {"type": "string"},
                "text": {"type": "string", "description": "（可选）人格文本；不传则读取"},
            },
            required=["preset_id"],
            handler=_preset_persona_tool,
        ))
        self.register(ToolSpec(
            name="dsh.preset_remove",
            description="删除自定义 Agent 预设（内置预设拒绝；删除当前默认预设时自动清空默认）",
            parameters={"preset_id": {"type": "string"}},
            required=["preset_id"],
            handler=_preset_remove_tool,
        ))
        self.register(ToolSpec(
            name="dsh.preset_set_default",
            description="设置默认预设（作用于所有后续 headless 任务）；preset_id 为空 = 跟随内置默认",
            parameters={"preset_id": {"type": "string", "description": "预设 id；空串表示跟随内置默认"}},
            handler=_preset_set_default_tool,
        ))


# ─── 内置 handler ──────────────────────────────────

def _page_ids():
    from gui.core.ui_registry import ui_registry

    return ui_registry.page_ids()


def _tabs():
    from gui.core.ui_registry import ui_registry

    return ui_registry.tabs()


def _apply_preset(args: dict) -> dict:
    from gui.core.config import AppConfig

    preset_id = args.get("preset_id")
    cfg = AppConfig()
    cfg.apply_preset(preset_id)
    event_bus.publish(THEME_CHANGED)
    return {"ok": True, "message": f"已应用预设 {preset_id}"}


def _create_skin_proposal(args: dict) -> dict:
    payload = {
        "skin_id": _slugify(args["name"]),
        "name": args["name"],
        "tokens": args.get("tokens", {}),
        "mode": args.get("mode"),
        "description": args.get("description", ""),
    }
    proposal = proposal_store.create("skin", f"皮肤包：{args['name']}", args.get("description", ""), payload)
    return {"ok": True, "message": f"已生成提案 {proposal.id}，等待审批", "data": {"proposal_id": proposal.id}}


def _proposal_action(action: str, proposal_id: str) -> dict:
    fn = {"approve": proposal_store.approve, "reject": proposal_store.reject, "revert": proposal_store.revert}[action]
    proposal = fn(proposal_id)
    if proposal is None:
        return {"ok": False, "message": f"提案 {proposal_id} 不存在或状态不可{action}"}
    return {"ok": True, "message": f"提案 {proposal_id} 已{action}（状态 {proposal.status}）"}


def _choose_workflow(args: dict) -> dict:
    """按多巴胺 UCB 选择流程（P1-2）"""
    w = workflow_store.choose(args.get("query"))
    if w is None:
        return {"ok": False, "message": "无匹配流程", "data": None}
    data = next((s for s in workflow_store.summary() if s["id"] == w.id), None)
    return {"ok": True, "message": f"推荐流程: {w.name}", "data": data}


# ─── DSH 执行器官（node_dsh） ──────────────────────────────

def _dsh_paths():
    """定位 node_dsh 的输入/输出文件（文件协议通道）。"""
    from pathlib import Path

    project_root = Path(__file__).resolve().parent.parent.parent
    shared_dir = project_root / "nodes" / "shared"
    node_dir = project_root / "nodes" / "node_dsh"
    return {
        "req": shared_dir / "dsh_task_in.json",
        "out": node_dir / "output.json",
        "node": node_dir,
    }


def _run_dsh_task(args: dict) -> dict:
    """提交 DSH 任务（写 task 输入文件，node_dsh 节点异步执行）。"""
    import time as _time

    task = str(args.get("task", "")).strip()
    if not task:
        return {"ok": False, "message": "缺少 task 字段"}
    session_id = str(args.get("session_id", "")).strip()
    paths = _dsh_paths()
    if not (paths["node"] / "node_config.json").is_file():
        return {"ok": False, "message": "node_dsh 节点不存在"}
    try:
        paths["req"].parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "data_type": "dsh_task",
            "task": task,
            "_ts": _time.time(),
        }
        if session_id:
            payload["session_id"] = session_id
        paths["req"].write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        return {"ok": False, "message": f"提交失败: {exc}"}
    return {
        "ok": True,
        "message": "DSH 任务已提交（由 node_dsh 节点异步执行）",
        "data": {"submitted": True, "task": task[:100], **({"session_id": session_id} if session_id else {})},
    }


def _run_dsh_task_sync(args: dict) -> dict:
    """提交 DSH 任务并同步等待完成（轮询 output.json，以 task_id 精确匹配本次任务）。"""
    import time as _time
    import uuid

    task = str(args.get("task", "")).strip()
    if not task:
        return {"ok": False, "message": "缺少 task 字段"}
    session_id = str(args.get("session_id") or "").strip()
    try:
        timeout = float(args.get("timeout", 600))
    except (TypeError, ValueError):
        timeout = 600.0
    timeout = max(1.0, timeout)

    paths = _dsh_paths()
    if not (paths["node"] / "node_config.json").is_file():
        return {"ok": False, "message": "node_dsh 节点不存在"}

    # 唯一任务标识：main.py 原样回带，轮询据此判定完成（并发/重复提交亦可靠）
    task_id = uuid.uuid4().hex[:12]
    try:
        paths["req"].parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "data_type": "dsh_task",
            "task": task,
            "task_id": task_id,
            "_ts": _time.time(),
        }
        if session_id:
            payload["session_id"] = session_id
        paths["req"].write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        return {"ok": False, "message": f"提交失败: {exc}"}

    # 轮询等待：node_dsh 独立进程执行完毕后写入 output.json
    out_path = paths["out"]
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        _time.sleep(1.0)
        if not out_path.is_file():
            continue
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            inner = data.get("data", data) if isinstance(data, dict) else data
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(inner, dict) or inner.get("task_id") != task_id:
            continue
        return {
            "ok": True,
            "message": "DSH 任务完成" if inner.get("ok") else "DSH 任务失败",
            "data": inner,
        }
    return {
        "ok": False,
        "message": f"DSH 任务等待超时（>{timeout:.0f}s，任务仍在后台执行，可用 dsh.check_task 补查）",
        "data": {"task_id": task_id, "submitted": True},
    }


def _check_dsh_task(args: dict) -> dict:
    """查询 node_dsh 最近一次执行结果。"""
    paths = _dsh_paths()
    out_path = paths["out"]
    if not out_path.is_file():
        return {"ok": False, "message": "node_dsh 尚无执行结果（任务可能还在进行或从未提交）", "data": None}
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
        inner = data.get("data", data) if isinstance(data, dict) else data
    except (json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "message": f"读取结果失败: {exc}", "data": None}
    ok = bool(inner.get("ok")) if isinstance(inner, dict) else False
    return {
        "ok": True,
        "message": ("DSH 任务已完成" if ok else "DSH 任务未完成/失败"),
        "data": inner,
    }


def _get_theme_state(args: dict) -> dict:
    from gui.core.config import AppConfig

    cfg = AppConfig()
    return {
        "ok": True,
        "message": "ok",
        "data": {
            "selected_preset": cfg.get_selected_preset(),
            "selected_skin": cfg.get_selected_skin(),
            "accent_color": cfg.get_theme("accent_color"),
            "mode": cfg.get_theme("mode"),
        },
    }


def _slugify(text: str) -> str:
    """生成安全的皮肤包 id（字母数字/_-）"""
    out = "".join(c if c.isalnum() or c in "_-" else "_" for c in text.lower())
    out = out.strip("_") or "skin"
    return out[:32]


# ─── DSH Agent 预设（AI 协作创建） ──────────────────────────────
# DSH 官方语义：user 预设可 "authored by a person or by an agent"。这里把
# dsh_manage_page 的预设读写封装为 AI 工具（延迟导入避免与 pages 层循环依赖）。

def _preset_api():
    """延迟导入 dsh_manage_page 的预设读写函数（避免循环依赖）。"""
    from gui.pages.dsh_manage_page import (
        create_custom_preset,
        delete_custom_preset,
        list_presets,
        read_preset_default,
        read_preset_file,
        read_preset_persona,
        save_preset_default,
        save_preset_file,
        write_preset_persona,
    )

    return {
        "create": create_custom_preset,
        "delete": delete_custom_preset,
        "list": list_presets,
        "read_default": read_preset_default,
        "read_file": read_preset_file,
        "read_persona": read_preset_persona,
        "save_default": save_preset_default,
        "save_file": save_preset_file,
        "write_persona": write_preset_persona,
    }


def _preset_summary(p) -> dict:
    return {
        "id": p["id"],
        "name": p["name"],
        "trust": p["trust"],
        "description": p["description"],
        "broken": p["broken"],
    }


def _list_presets_tool(args: dict) -> dict:
    api = _preset_api()
    presets = [_preset_summary(p) for p in api["list"]()]
    for item in presets:
        if not item["broken"]:
            item["persona"] = api["read_persona"](item["id"])
    return {"ok": True, "message": "ok", "data": {"presets": presets, "default": api["read_default"]()}}


def _preset_copy_tool(args: dict) -> dict:
    api = _preset_api()
    api["create"](str(args["source_id"]), str(args["new_id"]), str(args.get("name") or ""))
    return {"ok": True, "message": f"已创建自定义 Agent：{args['new_id']}", "data": {"preset_id": args["new_id"]}}


def _preset_read_tool(args: dict) -> dict:
    api = _preset_api()
    preset_id = str(args["preset_id"])
    filename = str(args.get("file") or "")
    if filename:
        content = api["read_file"](preset_id, filename)
        return {"ok": True, "message": "ok", "data": {"preset_id": preset_id, "file": filename, "content": content}}
    persona = api["read_persona"](preset_id)
    return {"ok": True, "message": "ok", "data": {"preset_id": preset_id, "persona": persona}}


def _preset_write_tool(args: dict) -> dict:
    api = _preset_api()
    api["save_file"](str(args["preset_id"]), str(args["file"]), str(args["content"]))
    return {"ok": True, "message": f"已写入 {args['file']}（下一次 headless 任务生效）"}


def _preset_persona_tool(args: dict) -> dict:
    api = _preset_api()
    preset_id = str(args["preset_id"])
    if "text" in args:
        api["write_persona"](preset_id, str(args["text"]))
        return {"ok": True, "message": "人格已写入（下一次 headless 任务生效）" if str(args["text"]).strip()
                else "人格已移除（继承部署默认）"}
    return {"ok": True, "message": "ok", "data": {"preset_id": preset_id, "persona": api["read_persona"](preset_id)}}


def _preset_remove_tool(args: dict) -> dict:
    api = _preset_api()
    api["delete"](str(args["preset_id"]))
    return {"ok": True, "message": f"已删除自定义 Agent：{args['preset_id']}"}


def _preset_set_default_tool(args: dict) -> dict:
    api = _preset_api()
    preset_id = str(args.get("preset_id") or "").strip()
    api["save_default"](preset_id or None)
    return {"ok": True, "message": f"默认预设已设为 {preset_id}" if preset_id else "已恢复跟随内置默认"}


# 模块级单例（置于文件末尾，确保 handler 函数已定义）
tool_registry = ToolRegistry()
