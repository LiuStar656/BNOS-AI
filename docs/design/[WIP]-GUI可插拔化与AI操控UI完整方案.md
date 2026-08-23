# [PLAN]-GUI可插拔化与AI操控UI完整方案

> 状态：阶段 1-7 已实施完成；P0-2/P0-1/P1-1（workflow+双引擎）/P1-2（AAA 自动选流程）已实施；P2 待推进
> 日期：2026-08-14

## 背景与目标

BNOS-AI 的 GUI 要实现对标 DeepSeek Harness WebUI 的"UI 可插拔 + AI 实时操控 UI"能力：
用户告诉 agent 要什么效果后，agent 产出（皮肤、图标、页面、流程）可以直接应用到 UI 上，
且**变更可见、可审批、可回退**。

核心架构决策：借鉴 DeepSeek Harness 的"万物皆插件"范式，但保留 Qt 命令式渲染的既有现实，
分 7 个渐进阶段落地，每阶段有独立验收标准。

## 阶段方案与实施记录

| 阶段 | 能力 | 核心产出 | 状态 |
|---|---|---|---|
| 1 ThemeEngine | token→全局 QSS 唯一生成器，统一取色入口 | `gui/core/theme_engine.py`，15 组件硬编码色 token 化 | ✅ 完成 |
| 2 IconRegistry | 语义图标注册中心，运行时覆盖 | `gui/core/icon_registry.py`，7 组件裸符号收口 | ✅ 完成 |
| 3 UiRegistry | 页面插槽化，注册即出现，冲突即设计 | `gui/core/ui_registry.py`，6 页面（含提案/AI 工具） | ✅ 完成 |
| 4 消息事件化 | 组件自查订阅，跨组件协作走消息 | `gui/core/messages.py`，sidebar/chat/面板订阅 THEME_CHANGED、PAGE_ACTIVATED | ✅ 完成 |
| 5 皮肤包机制 | AI 产出落盘为皮肤包目录，与预设平级 | `gui/core/skin_registry.py`（install/scan/list/remove） | ✅ 完成 |
| 6 提案卡片 | 变更治理：pending→审批→可回退 | `gui/core/proposal_store.py` + `gui/pages/proposals_page.py` | ✅ 完成 |
| 7 工具闭环 | AI 写请求文件→GUI 执行→回结果 | `gui/core/tool_registry.py`（25 工具：15 ui.*（导航/皮肤/提案/图标/主题/workflow）+ 3 dsh.run_* + 7 dsh.preset_*）+ `gui/core/tool_bridge.py` + `gui/pages/tools_page.py` | ✅ 完成 |

### 阶段 7 工具清单（GUI 暴露给 AI 的能力，2026-08-14 扩充为 25 个）

- `ui.navigate_page` / `ui.list_pages` / `ui.refresh_data`
- `ui.apply_preset`
- `ui.create_skin_proposal` / `ui.approve_proposal` / `ui.reject_proposal` / `ui.revert_proposal`（治理链路）
- `ui.install_icon`
- `ui.list_proposals` / `ui.get_theme_state`
- `ui.choose_workflow` / `ui.list_workflows` / `ui.run_workflow` / `ui.rate_workflow`（流程编排 P1-1）
- `dsh.run_task` / `dsh.run_task_sync` / `dsh.check_task`（DSH 执行器官，node_dsh 桥接）
- `dsh.preset_list` / `dsh.preset_copy` / `dsh.preset_read` / `dsh.preset_write` /
  `dsh.preset_persona` / `dsh.preset_remove` / `dsh.preset_set_default`
  （Agent 预设管理——DSH 官方允许 user 预设 "authored by a person **or by an agent**"，
  AI 与用户对话即可创建/定制预设）

文件通道：`nodes/shared/gui_tool_requests/`（AI 发请求）→ `gui_tool_responses/`（GUI 回结果）；
能力清单落盘 `nodes/shared/gui_tool_schemas.json`（AI 能力接缝）。

## 对标 DeepSeek Harness 差距分析

Harness 子系统：session/context/compaction/workflow/skills/subagent/approval/feedback/sandbox/api-gateway/sdk。
7 阶段补齐的是 GUI 侧"操控端"，Harness 完整闭环是"agent 发现 + 执行 + 过程可视化 + 治理 + 编排"——目前只通了一端。

### P0（核心差距，不通则桥白搭）

1. **AI 消费端**：工具桥只有 GUI 发布端；AAA 尚未加载 `gui_tool_schemas.json`、不会写请求文件
2. **实时双向通道**：文件轮询 600ms 单向；agent 思考中/工具调用/步骤进度不可见（打"AI 操作可见"诉求）

### P1（治理与演化层）

3. **workflow 编排器**：AAA 有流程库概念（多巴胺/用进废退）但无执行追踪、无 schema 化描述——双引擎无处挂接
4. **feedback 回流**：提案审批已有（≈approval），但用户对流程的评价未数据化回流（多巴胺 RPE 校准未落地）
5. **上下文管理**：chatbot.db 只存消息，agent 侧无上下文压缩与 token 计量

### P2（能力面）

6. 统一能力接缝（现 4 个分散注册表：Ui/Icon/Tool/Skin，无统一"能力注册表"）
7. skills 技能包（prompt+工具组合、可安装）
8. subagent 子代理（任务分解/并行/归并）
9. sandbox 隔离（AI 写文件跑代码的安全底线）
10. api-gateway + SDK（对外协议层）

## 后续推进计划

| 优先级 | 项 | 说明 | 是否动 AAA | 状态 |
|---|---|---|---|---|
| P0-2 | 实时事件推送 | GUI 侧：工具执行/提案审批/主题变更事件 + AAA 想法轮询实时上屏（`gui/pages/activity_page.py`，AI_EVENT 消息） | 否（纯 GUI） | ✅ 完成 |
| P0-1 | AAA 消费端 | AAA 读 schemas + 发请求 + 收响应（`nodes/node_python_aaa_cognition/gui_tools.py`；prompt 注入工具清单；【工具调用】节开放执行） | 是 | ✅ 完成 |
| P0-1b | AI 协作创建 Agent 预设 | `dsh.preset_*` 7 工具（list/copy/read/write/persona/remove/set_default）；`tool_list_text()` 调用时机说明放宽（UI/主题/皮肤、DSH 任务、Agent 预设、页面导航均可调用） | 是（提示词微调） | ✅ 完成 |
| P0-1c | 换肤 AI 闭环验收 | 用户对 AI 说需求（如「换个紫色主题」）→ 【工具调用】ui.create_skin_proposal → 提案卡 → 审批 → skin_registry.install + apply_skin + THEME_CHANGED → theme_engine 即时重绘；**可回退**（提案 revert 恢复旧皮肤）。颜色/背景/大小等 token 均可动态改；布局结构调整（如侧栏↔顶栏）不在换肤范围，属数据驱动 UI 改造（更大工程） | 是（已具备） | ✅ 完成 |
| P1-1 | workflow + 双引擎 | 流程 schema 化 + 多巴胺（外部评价 RPE 校准/UCB 选择）+ 用进废退（分位数降权）评价回流（`gui/core/workflow_store.py` + `gui/pages/workflow_page.py` + ui.list_workflows/run_workflow/rate_workflow） | 部分（AAA 经工具桥消费） | ✅ 完成 |
| P1-2 | AAA 自动选流程 | prompt 注入流程清单（含双引擎实时分数），LLM 输出【流程选择】→ AAA 决策循环接入 ui.run_workflow（parser 新增节解析、gui_tools.load_workflows/workflows_text、main.py 流程分支） | 是 | ✅ 完成 |
| P2 | 技能包/subagent/沙箱/统一注册表 | 工程完备性 | 是 | 待推进 |

## 附加工程（2026-08-14）

- **按钮字体自适应**（全局 UI 健壮性）：`gui/core/utils/widget_utils.py::fit_button_width()`
  用 fontMetrics 计算文本宽 + padding，只设 minimumWidth 保留 sizeHint 自适应；替换 6 个页面
  全部 `setFixedWidth` 文本按钮（activity/workflow/tools/node/proposals/dsh_manage），
  解决系统字体放大后文字溢出按钮的问题。约定：文本按钮一律不用 setFixedWidth。

## 验收方法

每阶段验收 = 编译 + 冒烟（注册/链路/回退断言）+ `run.bat` 启动检测（无 Python 报错、引擎 3 节点就绪、清理无残留）+ 8 套预设视觉回归。
