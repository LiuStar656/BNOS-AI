# Workflow 流程步骤接入 DSH 执行器方案（待决策）

> 主方案：`[PLAN]-DeepSeekHarness接入方案.md` 待办扩展项之一
> 前置：DSH 会话续接已落地（`DSH_SESSION_ID` / `agents.resume` / `__BNOS_SESSION__` 回带）

---

## 1. 目标

让 GUI 流程库（`workflow_store`）中的流程步骤可以包含 DSH 任务步骤，**DSH 作为流程执行器**：
流程执行到 DSH 步骤时，真正等到 Agent 任务完成、拿到结果，再继续后续步骤（或结束流程）。

## 2. 现状与关键矛盾

### 现状链路

```
AAA 节点 / GUI 工具 → tool_bridge（QTimer 轮询, GUI 主线程）
  → tool_registry.execute() → workflow_store.run()   # 同步执行每个步骤
      → 步骤工具如 dsh.run_task（写 nodes/shared/dsh_task_in.json，提交即返回）
  → node_dsh 独立进程 listener 轮询 → main.py 跑完整 DSH Agent（分钟级）
      → 写 nodes/node_dsh/output.json
  → dsh.check_task 读取 output.json（异步查询语义）
```

### 关键矛盾

| 项 | 现状 |
|---|---|
| `workflow_store.run()` | **同步**执行步骤，一步失败即短路 |
| `dsh.run_task` | **异步**提交（写文件即返回），结果需 `dsh.check_task` 事后轮询 |
| 工具执行线程 | `tool_bridge._poll` 由 QTimer 驱动，**运行在 GUI 主线程** |

→ 若流程步骤直接调 `dsh.run_task`，流程会"秒完成"，DSH 任务仍在后台跑，违背"DSH 作为流程执行器"的语义。
→ 若在 GUI 主线程阻塞等待分钟级任务，界面冻结，不可接受。

## 3. 方案对比

### 方案 A：新增同步等待工具 `dsh.run_task_sync`（推荐）

**语义**：提交任务 → 轮询直到本次任务完成 → 返回最终结果（同步语义）。
流程里一个 DSH 步骤 = 一次同步调用，`workflow_store.run()` **零改动**。

**配套改动（3 处）**：
1. `nodes/node_dsh/main.py`：提交附带唯一 `task_id`，结果中原样回带（约 3 行）。
2. `gui/core/tool_registry.py`：注册 `dsh.run_task_sync`（参数 task / session_id / timeout）。
3. `gui/core/tool_bridge.py`：耗时工具改在**独立线程**执行（通用机制，未来可复用于其他长任务工具），避免 GUI 主线程冻结；event_bus 基于 Qt Signal，跨线程 emit 走 QueuedConnection 自动回主线程，安全。

**优点**：改动最小、语义最直观、机制通用；`workflow_store` 不耦合 DSH 细节。
**缺点**：需引入 tool_bridge 子线程执行机制；`run_task_sync` 调用方（流程执行线程）会被阻塞到任务完成（预期内）。

### 方案 B：扩展 `workflow_store.run()` 支持步骤级异步等待

流程步骤 schema 增加等待标记（如 `{"tool": "dsh.run_task", "wait": true}`），`run()` 遇到后：提交 → 循环 `dsh.check_task` → 完成才继续下一步。

**优点**：不新增工具。
**缺点**：`workflow_store` 反向耦合 DSH 任务细节；等待循环同样运行在工具执行线程（主线程），仍需子线程机制兜底；其他异步工具无法复用；通用性差。

### 方案 C：流程执行整体异步化（大改）

`run()` 改异步：提交步骤后立即返回流程状态，由轮询器持续推进状态机。

**优点**：彻底贴合 BNOS 异步文件协议。
**缺点**：涉及流程状态机、持久化、GUI 展示、AAA 侧调用方式全链路改造，远超本扩展项范围，风险高。

---

## 4. 方案 A 详细设计

### 4.1 任务标识（task_id 回带）

`dsh.run_task_sync` 提交时生成 `uuid` 作为 `task_id`，写入 `dsh_task_in.json`（与 `session_id` 同法透传）；`main.py` 的 `process()` 读取 `task_id` 并并入返回结果：

```python
# nodes/node_dsh/main.py — process() 内
task_id = str(data.get("task_id", "")).strip()
result = _run_dsh(task, session_id)
if task_id:
    result["task_id"] = task_id
return result
```

→ GUI 侧轮询 `output.json`，以 `data.task_id == 本次提交的 task_id` 精确判定"本次任务已完成"（并发/重复提交亦可靠）。

### 4.2 同步等待工具 `dsh.run_task_sync`

```python
# tool_registry.py
ToolSpec(
    name="dsh.run_task_sync",
    description="把任务交给 DSH 执行并同步等待完成（适合流程步骤；结果即最终回答）",
    parameters={
        "task": {...},
        "session_id": {...可选，多轮续接...},
        "timeout": {"type": "number", "description": "等待上限（秒），默认 600"},
    },
    required=["task"],
    handler=_run_dsh_task_sync,
)
```

handler 流程：
1. 生成 `task_id` → 写 `dsh_task_in.json`（含 task/task_id/session_id/_ts）
2. 以 `poll_interval=1s` 轮询 `output.json`，直到 `data.task_id == task_id`（命中）或超过 timeout
3. 命中 → 返回 `{"ok": ..., "message": ..., "data": ...}`；超时 → 返回失败（任务仍在后台继续，可用 `dsh.check_task` 补查）

### 4.3 tool_bridge 耗时工具子线程执行

```python
# tool_bridge.py — 通用机制
_HEAVY_TOOLS = {"dsh.run_task_sync"}   # 耗时工具集合

def _handle_request(self, path):
    ...
    if tool_name in _HEAVY_TOOLS:
        threading.Thread(target=self._exec_heavy, args=(request, result_writer), daemon=True).start()
    else:
        ... 现有同步路径 ...
```

子线程中：`tool_registry.execute()` → 写响应文件 → `event_bus.publish(AI_EVENT)`（Qt 跨线程信号安全）。

## 5. 验收方式

1. **同步等待**：GUI/工具调用 `dsh.run_task_sync` 执行一个短任务（如"读 dsh_workspace 里 test.md 首行"），工具返回前阻塞、返回后结果含最终回答；耗时期间 GUI 界面不冻结。
2. **流程集成**：在 `nodes/shared/workflows.json` 新增示例流程（含一个 `dsh.run_task_sync` 步骤），执行流程后确认步骤结果 = DSH 最终回答。
3. **超时兜底**：传极小 timeout（如 1s）确认返回"超时"且任务仍在后台，`dsh.check_task` 可补查到结果。
4. **会话续接**：`session_id` 透传沿用既有续接能力。
5. `run.bat` 启动检测无报错。

## 6. 待决策项

- [x] 方案选型：**方案 A**（用户 2026-08-14 确认）
- [x] 示例流程：新增 `dsh_task` 流程（overrides 字段：`task`，可选 `session_id`）
- [x] `run_task_sync` 默认超时：600s（与 node_dsh 一致）

---

## 7. 实施记录（2026-08-14 已实施）

### 7.1 改动文件

| 文件 | 改动 |
|---|---|
| `nodes/node_dsh/main.py` | `process()` 读取 `task_id` 并原样回带到结果（约 4 行） |
| `gui/core/tool_registry.py` | 新增工具 `dsh.run_task_sync` + handler `_run_dsh_task_sync`（提交→1s 轮询 output.json→`data.task_id` 匹配判定完成→返回；`timeout` 默认 600；session_id 空值用 `or ""` 防 `str(None)`） |
| `gui/core/tool_bridge.py` | 新增 `_HEAVY_TOOLS` 集合 + `_exec_and_respond`；耗时工具转独立线程执行（daemon），避免 GUI 主线程冻结；请求文件受理即删 |
| `nodes/shared/workflows.json` | 新增示例流程 `dsh_task`（单步骤 `dsh.run_task_sync`，占位符 `{{task}}`） |

### 7.2 验收结果

| 项 | 结果 |
|---|---|
| 工具注册 | ✅ `dsh.run_task_sync` 出现在 schemas |
| 同步等待 | ✅ `dsh.run_task_sync` 真实等待 22s 后返回 DSH 最终回答（含 task_id 回带） |
| workflow 集成 | ✅ `ui.run_workflow` flow_id=`dsh_task` 耗时 23s，步骤结果 = DSH 最终回答 |
| 超时兜底 | ✅ timeout=2 返回"等待超时"；后台任务完成后 `dsh.check_task` 补查到结果 |
| GUI 工具桥子线程 | ✅ 真实 GUI 进程经 gui_tool_requests 调用 `dsh.run_task_sync`，响应含 DSH 最终回答；期间 GUI 无冻结 |
| run.bat 启动检测 | ✅ 引擎 4 节点全启动（含 node_dsh），无 Python 报错 |

### 7.3 使用方式

- 流程步骤：`{"tool": "dsh.run_task_sync", "args": {"task": "{{task}}"}}`（可选 `session_id` 续接）
- 工具直接调用：`dsh.run_task_sync` 参数 `task`（必填）/ `session_id` / `timeout`（秒，默认 600）
- 超时后任务仍在后台执行，用 `dsh.check_task` 补查最终结果

### 7.4 注意事项

- `dsh.run_task_sync` 会阻塞其调用线程直到任务完成（预期语义）；GUI 工具桥已将耗时工具放入子线程，**不要**在 GUI 主线程直接调用（会冻结界面）
- 依赖 node_dsh 的 `main.py` 回带 task_id；若直接手写 `dsh_task_in.json` 调用节点（绕过 GUI 工具），不带 `task_id` 时输出不含该字段（行为兼容，仅无法精确匹配"本次任务"）
