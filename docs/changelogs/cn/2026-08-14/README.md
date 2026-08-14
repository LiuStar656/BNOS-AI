# 2026-08-14 更新总览

[返回总索引](../README.md)

---

## 更新目录

- [01 GUI 可插拔化与 AI 操控 UI（7 阶段）](#01-gui-可插拔化与-ai-操控-ui7-阶段)
- [02 DSH 设置/控制组件接入 GUI（DSH 管理页）](#02-dsh-设置控制组件接入-guidsh-管理页)
- [03 Workflow 流程接入 DSH 执行器](#03-workflow-流程接入-dsh-执行器)
- [04 人格归并入 Agent 预设（目标/人格 Tab 删除）](#04-人格归并入-agent-预设目标人格-tab-删除)
- [05 AI 协作创建预设与换肤闭环（工具扩充）](#05-ai-协作创建预设与换肤闭环工具扩充)
- [06 全局按钮字体自适应](#06-全局按钮字体自适应)
- [07 AAA 直连 DSH 节点与日常/工作模式](#07-aaa-直连-dsh-节点与日常工作模式)

---

## 摘要

| # | 核心改动 | 根因 | 影响 |
|---|---------|------|------|
| 01 | 分 7 阶段实现 GUI 可插拔化与 AI 操控 UI：ThemeEngine（token→全局 QSS）、IconRegistry（语义图标运行时覆盖）、UiRegistry（页面插槽化）、消息事件化、皮肤包机制（AI 产出落盘）、提案卡片（审批/回退治理）、工具闭环（ToolRegistry+ToolBridge，AI 写请求文件→GUI 执行→回结果） | 对标 DeepSeek Harness WebUI 的"UI 可插拔 + AI 实时操控 UI"能力：让 agent 产出（皮肤/图标/页面/流程）可直接应用到 UI，变更可见、可审批、可回退 | GUI 全组件取色走 token（theme_engine 唯一生成器）；AI 可通过 25 个工具操控 GUI；破坏性变更走提案审批不会直接生效 |
| 02 | 把 DSH 中需设置/修改/控制的组件做成 BNOS GUI 原生表单：「DSH 管理」页 9 分区（模型配置/会话/任务/工具开关/插件/工作区/运行参数/通用安全/Agent 预设），不进入 DSH 即可操作 | 用户要求不在 DSH web 面板内操作，所有 DSH 设置控制组件挪到 BNOS GUI | headless/web 双 patch 同步写回、extra.patch 运行时生效、runtime.json 经 DSH_TEMPERATURE/DSH_PRESET 注入；会话管理/任务控制/工作区浏览/插件管理全在 GUI 完成 |
| 03 | DSH 作为流程执行器：workflow_store 流程步骤接入 `dsh.run_task`（DSH 执行器官），流程可提交 DSH 任务并等待最终回答 | 流程步骤需要真实执行能力，DSH（DeepSeek Harness）是已接入的执行器 | 流程执行不再空转，DSH 任务结果回流；同步等待超时后仍可 `dsh.check_task` 补查 |
| 04 | 删除独立「目标/人格」Tab，人格并入「Agent 预设」分区（agent.cordis.yml 的 `id: persona` 行）；新增 `_migrate_drop_global_persona()` 幂等清理 extra.patch.yml 残留的全局 `system-prompt` 行 | 原 Tab 写全局 `system-prompt.persona` 与 DSH 官方"人格属预设"语义冲突，且与 AAA 负责人格重叠 | 人格编辑入口在预设编辑对话框；无该行则继承部署默认人格；`!!js` 平台表达式 roundtrip 保留 |
| 05 | ToolRegistry 扩充至 25 工具：新增 7 个 `dsh.preset_*`（list/copy/read/write/persona/remove/set_default）实现 AI 协作创建预设；`gui_tools.py` 工具注入说明放宽（UI/主题、DSH 任务、Agent 预设、页面导航均可调用） | DSH 官方允许 user 预设 "authored by a person or by an agent"；用户要求像 DSH 一样通过对话创建预设 | 对 AI 说「创建一个叫 xx 的 Agent，人格是…」即可创建/定制预设，下一次 headless 任务生效 |
| 06 | 新增 `gui/core/utils/widget_utils.py::fit_button_width()`：fontMetrics 计算文本宽+padding，只设 minimumWidth 保留 sizeHint 自适应；替换 6 个页面全部 `setFixedWidth` 文本按钮 | 全局 QSS 按钮 padding 固定 + 各页固定宽度 → 字体放大后文字溢出按钮 | 系统字体/主题字号放大后按钮不再溢出；约定文本按钮一律不用 setFixedWidth |
| 07 | AAA 直连 DSH 节点通道（dsh_client.py，不经 GUI 工具桥）+ 异步回执（后台轮询完成后主动推送 gui_reply.json）+ 日常/工作双模式（GUI 按钮手动 + 可配置关键词自动切换，工作模式跳过 LLM 判断带完整上下文直通 DSH）；GUI 工具桥移除 dsh 执行器官（25→22 工具），workflow 步骤直连节点 | node_dsh 本就是标准 BNOS 节点，转发应走节点通道而非 GUI 工具桥（GUI 必须在线）；DSH 结果不回流；每轮都走 LLM 判断浪费成本 | 转发不依赖 GUI；DSH 完成结果自动推送；工作模式输入直通 DSH 不再走 LLM 判断；关键词可设置面板修改；workflow dsh 步骤同步等待语义保留 |

---

### 01 GUI 可插拔化与 AI 操控 UI（7 阶段）

详见 [01_GUI可插拔化与AI操控UI.md](./01_GUI可插拔化与AI操控UI.md)。

### 02 DSH 设置/控制组件接入 GUI（DSH 管理页）

详见 [02_DSH设置控制组件接入GUI.md](./02_DSH设置控制组件接入GUI.md)。

### 03 Workflow 流程接入 DSH 执行器

详见 [03_Workflow流程接入DSH执行器.md](./03_Workflow流程接入DSH执行器.md)。

### 04 人格归并入 Agent 预设（目标/人格 Tab 删除）

详见 [04_人格归并入Agent预设.md](./04_人格归并入Agent预设.md)。

### 05 AI 协作创建预设与换肤闭环（工具扩充）

详见 [05_AI协作创建预设与换肤闭环.md](./05_AI协作创建预设与换肤闭环.md)。

### 06 全局按钮字体自适应

详见 [06_全局按钮字体自适应.md](./06_全局按钮字体自适应.md)。

### 07 AAA 直连 DSH 节点与日常/工作模式

详见 [07_AAA直连DSH节点与日常工作模式.md](./07_AAA直连DSH节点与日常工作模式.md)。

---

## 修改文件清单

### 新增文件

| 文件 | 所属 |
|------|------|
| `gui/core/theme_engine.py` | #01 |
| `gui/core/icon_registry.py` | #01 |
| `gui/core/ui_registry.py` | #01 |
| `gui/core/messages.py` | #01 |
| `gui/core/skin_registry.py` | #01 |
| `gui/core/proposal_store.py` | #01 |
| `gui/core/tool_registry.py` | #01、#05、#07 |
| `gui/core/tool_bridge.py` | #01、#07 |
| `gui/core/workflow_store.py` | #01、#03、#07 |
| `gui/core/utils/widget_utils.py` | #06 |
| `gui/pages/activity_page.py` | #01 |
| `gui/pages/tools_page.py` | #01 |
| `gui/pages/proposals_page.py` | #01 |
| `gui/pages/workflow_page.py` | #01、#03 |
| `gui/pages/dsh_manage_page.py` | #02、#04、#05 |
| `nodes/node_python_aaa_cognition/dsh_client.py` | #07 |
| `nodes/node_python_aaa_cognition/mode_manager.py` | #07 |
| `docs/design/[PLAN]-GUI可插拔化与AI操控UI完整方案.md` | #01 |
| `docs/design/[PLAN]-DSH设置控制组件接入GUI方案（待决策）.md` | #02、#04、#05 |
| `docs/design/[PLAN]-workflow接入DSH执行器方案（待决策）.md` | #03 |
| `docs/design/[PLAN]-DeepSeekHarness接入方案.md` | #02、#03 |
| `docs/design/[PLAN]-DSH会话续接方案（待决策）.md` | #02 |
| `docs/design/[OK]-AAA直连DSH节点与模式切换方案.md` | #07 |

### 重大修改文件

| 文件 | 改动 | 所属 |
|------|------|------|
| `gui/core/config.py` / `gui/resources/theme.py` | 预设/token 化取色接入 ThemeEngine；皮肤包 apply_skin | #01 |
| `gui/main_window.py` | 页面改由 ui_registry 插槽加载；订阅 THEME_CHANGED 即时重绘 | #01 |
| `gui/widgets/{sidebar,title_bar,toast,chat_input,color_picker,floating_panel,knowledge_panel,live2d_overlay,location_map_widget}.py`、`gui/pages/{chat_page,live2d_page,location_page,mcp_page,node_page,settings_panel}.py`、`gui/dialogs/{archive_panel,personality_dialog}.py`、`gui/core/utils/dialog_utils.py` | 硬编码颜色 token 化，统一走 theme_engine 取色 | #01 |
| `gui/pages/startup_splash.py` | `NODE_LABELS` 增加 `node_dsh`（「DSH 执行」） | #02 |
| `gui/core/ui_registry.py` | `page.dsh_config` → `page.dsh_manage`（标题「DSH 管理」） | #02 |
| `nodes/node_dsh/harness/packages/bundle/headless/cordis.patch.yml` | 组合树新增 `agent-presets` 行（启用预设 roster） | #02、#04 |
| `nodes/node_dsh/harness/packages/bundle/headless/src/index.ts` | `setup` 改 async；按 `DSH_PRESET` 挂载预设；`agent/request` 合并 `DSH_TEMPERATURE` | #02 |
| `nodes/node_python_aaa_cognition/gui_tools.py` | 工具桥客户端（load_schemas/call_tool/tool_list_text/workflows_text）；调用时机说明放宽 | #01、#05 |
| `nodes/node_python_aaa_cognition/main.py` | 解析【工具调用】【流程选择】节 → call_tool / 流程分支；dsh.* 直连 node_dsh + 异步回执；`_on_text` 模式 NLP + 工作模式直通；`_dsh_session_id` 会话续接 | #01、#03、#07 |
| `nodes/node_python_aaa_cognition/node_config.json` | 新增 `mode_keywords` 段（模式切换默认关键词） | #07 |
| `nodes/node_dsh/main.py` | 注入 `DSH_TEMPERATURE`/`DSH_PRESET` env；`--patch extra.patch.yml` 加载（跳过空 patch）；`context` 字段拼入 task 前缀 | #02、#03、#07 |
| `nodes/node_python_aaa_cognition/prompt.py` | `_gui_tools_section()` 注入工具清单 + 流程库 | #01、#03 |
| `nodes/node_python_aaa_cognition/parser.py` | 新增工具调用/流程选择节解析 | #01、#03 |
| `gui/core/tool_registry.py` | 移除 dsh.run_task / run_task_sync / check_task（25→22 工具） | #07 |
| `gui/core/workflow_store.py` | `run()` 对 dsh.* 执行类步骤走 `_run_dsh_direct` 节点直连（同步等待语义保留） | #07 |
| `gui/core/tool_bridge.py` | `_HEAVY_TOOLS` 清空（dsh 执行已迁移节点通道） | #07 |
| `gui/pages/chat_page.py` | 顶部「日常/工作」切换按钮 + 每秒状态同步 | #07 |
| `gui/pages/settings_panel.py` | 「模式切换关键词」配置分组（读写 AAA node_config.json） | #07 |
| `gui/pages/dsh_manage_page.py` | 注释同步（任务链路描述改为 node_dsh 节点通道） | #07 |
| `nodes/shared/gui_tool_schemas.json` | 能力清单刷新为 22 工具 | #07 |
| `pipeline.json` | 引擎管线增加 `node_dsh` 节点 | #02 |

---

**最后更新**：2026-08-14
