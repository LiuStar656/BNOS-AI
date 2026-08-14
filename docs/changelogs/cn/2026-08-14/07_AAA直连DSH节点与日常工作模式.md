# 07 AAA 直连 DSH 节点与日常/工作模式

## 问题描述

1. **AAA 转发 DSH 绕道 GUI**：node_dsh 本是标准 BNOS 节点（listener 轮询
   `nodes/shared/dsh_task_in.json` → 执行 → 写 `output.json`），但原链路是
   AAA → gui_tools.call_tool → GUI ToolBridge（文件通道，**GUI 必须在线**）→
   ToolRegistry `dsh.run_task` → 写同一文件。多余一跳 + 引入 GUI 依赖。
2. **DSH 结果不回流**：`dsh.run_task` 异步提交，AAA 拿到「已提交」即回复用户，
   不等完成、结果不转述。
3. **全部请求走 LLM 判断**：无日常/工作模式区分，每轮都拼完整上下文发 LLM 判断
   「直接回复还是工具调用」，工作类请求（本就要 DSH）白白花判断成本。

## 修改方案

### Phase 0：节点通道客户端（dsh_client.py，GUI 无关）

- 新增 `nodes/node_python_aaa_cognition/dsh_client.py`：
  - `submit_task()` 写 `dsh_task_in.json`（原子替换，带唯一 `task_id`、可选
    `session_id` 续接、`context` 上下文）
  - `read_result()` 按 `task_id` 精确读 `node_dsh/output.json`（不匹配视为未完成）
  - `wait_result()` 同步等待（后台线程用）；`push_reply()` 直写 `gui_reply.json`
  - `node_ready()` 检查 node_dsh 节点配置是否存在

### Phase 1：AAA 工具分发改造 + 异步回执

- `main.py` ③ 工具调用分支：`tname` 以 `dsh.` 开头 → `dsh_client.submit_task`
  直连节点（不经 GUI）→ 立即回复「已提交」→ 后台 daemon 线程轮询
  `wait_result(task_id)`，完成后 `push_reply` 主动推送最终回答（沿用原
  `request_id`，GUI 过期回复过滤逻辑同 id 放行）
- DSH 结果回带的 `session_id` 由 AAA 记录（`_dsh_session_id`），多轮续接
- `node_dsh/main.py`：新增 `context` 字段支持（背景上下文拼入 task 前缀）

### Phase 2：日常/工作模式（手动 + 自动切换）

- 新增 `mode_manager.py`：`nodes/shared/mode.json` 模式状态（原子读写）；
  `try_switch()` 关键词子串检测（多词按词长优先，如「退出工作模式」优先于「工作模式」）
- 切换关键词配置在 AAA `node_config.json` 的 `mode_keywords` 段（默认：
  work=进入工作模式/开始工作模式/…，daily=进入日常模式/退出工作模式/…）
- GUI 聊天页顶部「日常/工作」切换按钮（chat_page.py）：点击原子写 mode.json，
  按钮状态每秒同步（AAA 关键词自动切换后 GUI 保持一致）
- GUI 设置面板「模式切换关键词」分组（settings_panel.py）：读写同一 node_config.json
- AAA `_on_text`：
  - 入口先做 NLP 关键词检测，命中 → 切模式 + 立即回执（不写库、不走 LLM）
  - 当前为工作模式 → `_direct_dsh_to_node()`：带 AAA 完整上下文（`_gather_context`
    产出的自我认知/固定认知/最近感受/历史摘要/用户信息，列表字段 join 为字符串）
    直发 DSH，立即回复「已提交」，后台轮询完成后推送结果
  - 日常模式 → 原有链路（LLM 判断）不变

### Phase 3：GUI 工具桥移除 dsh.* + workflow 适配

- `tool_registry.py`：移除 `dsh.run_task` / `dsh.run_task_sync` / `dsh.check_task`
  （AI 工具清单 25 → 22；`dsh.preset_*` 属 GUI 管理能力，保留）
- `workflow_store.py`：`run()` 对 `dsh.*` 执行类前缀走新增 `_run_dsh_direct()`
  （直连节点通道，写 dsh_task_in.json + task_id 轮询，同步等待语义保留）
- `tool_bridge.py`：`_HEAVY_TOOLS` 清空（dsh 执行已迁移节点通道，保留机制）
- `nodes/shared/gui_tool_schemas.json`：能力清单刷新为 22 工具

## 关键链路

```
工作模式直通（跳过 LLM 判断）：
用户输入 → AAA._on_text
  ├─ NLP 检测切换关键词？→ 切换 + 回复（不执行任务）
  ├─ mode==work →
  │    组装完整上下文 ctx → submit_task(task=输入, context=ctx)
  │    → 立即回复「已提交」→ 后台轮询 output.json（task_id 匹配）
  │    → 完成 → push_reply 推送最终回答（GUI 显示）
  └─ mode==daily → 现有链路（LLM 判断）

DSH 工具调用（LLM 已判定）：
LLM 输出 dsh.* 工具 → submit_task（直连节点）→ 异步回执（同上）
```

## 验证方法

- AAA/GUI 全量 py_compile 通过
- mode_manager 冒烟：切 work / 切 daily / 普通输入不误触
- GUI offscreen：chat_page 模式按钮、settings_panel 关键词分组实例化无异常
- tool_registry：22 工具（执行器官移除、preset 保留）
- workflow_store `_run_dsh_direct`：缺 task 字段正确返回错误，不抛异常
