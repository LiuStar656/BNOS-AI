# [PLAN] DSH Web 承载 AAA 主流程与 BNOS 资产迁移方案（待决策）

> 日期：2026-08-16 ｜ 修订：2026-08-25 ｜ 版本：v1.2 ｜ 状态：[PLAN]（待评审）
> 关联：[OK]-AAA直连DSH节点与模式切换方案 ｜ [PLAN]-DeepSeekHarness接入方案 ｜ [PLAN]-GUI可插拔化与AI操控UI完整方案 ｜ [PLAN]-DSH工具分配与模式复用闭环方案
> v1.1：聊天方向修正——**DSH 原生聊天 + smart 模式（AAA 为主要 agent）**，不做独立 BNOS 聊天页签/不接管 ui-conversation；bridge 仅作资产数据通道候选
> v1.2：Live2D/TTS 改为**自研并与 TTS 绑定为"面孔+声音"模块**——删除本计划中所有"可用现成插件替代 / 免自研"的 Live2D/TTS/ASR 描述，统一改为自研，避免插件调试链路繁琐、效果难统一。

---

## 目录

1. [背景与现状评估](#一背景与现状评估)
2. [目标](#二目标)
3. [方案设计](#三方案设计)
4. [分阶段实施计划](#四分阶段实施计划)
5. [风险评估](#五风险评估)
6. [测试计划](#六测试计划)
7. [影响范围](#七影响范围)
8. [待决策项](#八待决策项)

---

## 一、背景与现状评估

### 1.1 决策背景

用户决定从自研 PySide6 GUI 转向 **DSH web UI 作为统一界面**（载体），理由：

1. **省自研成本**：DSH web 的聊天/设置/工具/会话/工作区/主题均为工业级实现，
   自研 GUI 的 90% 功能（ThemeEngine/IconRegistry/UiRegistry/SkinRegistry/ProposalStore/ToolRegistry）
   在 DSH 均有原生覆盖且更强，继续自研 = 重复造轮子
2. **标准化定制能力强**：DSH 是"万物皆插件"（ui-slots 类型链式注册 + 冲突即失败），
   优于自研的手搓注册表 + QSS token
3. **许可合规**：DSH 为 MIT 协议（`harness/LICENSE`），允许自由使用/修改/再授权/商用，
   仅需保留版权声明——迁移与二次开发完全在授权范围内

### 1.2 关键方向确认（2026-08-16，2026-08-24 修正）

- **DSH 为主壳**：聊天/设置/工具/会话等直接用 DSH web **原生界面**；BNOS 独有资产
  （记忆库/活动流/节点监控/提案治理/流程库/定位）写成 slot 插件挂载；
  **Live2D 组件自研并与 TTS 绑定为"面孔+声音"模块**（不用插件替代）
- **聊天 = DSH 原生 + smart 模式**：对话直接在 DSH 原生 `ui-conversation` 中进行，
  **不做独立 BNOS 聊天页签、不接管 ui-conversation**；通过第 5 个预设
  **smart（AAA 助理）** 让 DSH agent 以 **AAA 为主要 agent** 运转
  （AAA 人格/记忆/输出格式内嵌 + 按需工具分配），详见
  `[PLAN]-DSH工具分配与模式复用闭环方案`
- **AAA 保持大脑地位**：日常对话由 smart 模式内嵌的 AAA 逻辑驱动；需要实际执行时
  经 AAA 意图门判定、按需调用 DSH 工具，**结果回 AAA 写库存档**（记忆链不断）；
  外部 AAA 节点保留首尾承接兜底
- **节点层零改动**：aaa/llm_infer/tts/node_dsh 的文件协议保持不变

### 1.3 现状：AAA 已是主流程（2026-08-14 已落地）

[AAA 直连 DSH 节点与模式切换方案](OK)-AAA直连DSH节点与模式切换方案.md v1.1 已实施：

```
用户输入 → gui_input.json → AAA.process()
    ├─ daily：AAA 拼上下文 → llm_infer → AAA 解析 → reply
    ├─ work：AAA 拼完整上下文 → dsh_client.submit_task → node_dsh → 结果回 AAA → reply
    └─ reply 写 gui_reply.json → 客户端轮询显示
```

关键事实（代码实证）：

| 组件 | 协议 | 位置 |
|---|---|---|
| 用户输入 | `gui_input.json`（data_type=text, source=gui, request_id, conversation_id）| `gui/core/message_manager.py` L78-118 |
| 回复 | `gui_reply.json`（data_type=reply, content, request_id；`<pending/>`/`<silent/>` 标签）| `gui/core/message_manager.py` L168-218 |
| DB 命令 | `gui_cmd.json` / `gui_cmd_result.json` | `gui/core/message_manager.py` L120-133 |
| 模式状态 | `nodes/shared/mode.json`（daily/work）| AAA `mode_manager.py` |
| DSH 直连 | `dsh_task_in.json` / `node_dsh/output.json`（task_id 精确匹配）| AAA `dsh_client.py` |

**结论：DSH web 化不需要改造 AAA——聊天直接在 DSH 原生 ui-conversation 进行，
通过 smart 模式（AAA 为主要 agent）承载 AAA 逻辑。**

> ⚠ **方向修正（2026-08-24）**：DSH web 化后聊天**不再"桥接/嵌入"**（无独立 BNOS
> 聊天页签、不接管 ui-conversation），对话由 **smart 模式**（`[PLAN]-DSH工具分配与
> 模式复用闭环方案`）驱动：DSH agent 以 AAA 为主要 agent 运转，经 aaa-engine MCP
> 直读写 AAA 记忆库。上表 `gui_input.json`/`gui_reply.json` 文件协议是 PySide6 GUI
> 时代的接口，双轨兼容期保留；smart 模式不经文件协议。

### 1.4 DSH web 能力盘点（迁移复用表）

| DSH web 组件 | BNOS 对应 | 处置 |
|---|---|---|
| ui-conversation | chat_page（聊天） | **复用**（原生，smart 模式下为 AAA 身份） |
| ui-settings-*（models/plugins/general/presets） | settings_panel + dsh_manage 9 分区 | **复用**（原生） |
| ui-goal / ui-plan / ui-jobs / ui-skill | workflow/activity 页 | **复用**（原生） |
| ui-tool / ui-subagent / ui-workspace | tools 页 | **复用**（原生） |
| ui-theme（token 主题） | theme_engine | 复用（DSH 生态更广） |
| ui-sidebar / ui-layout | sidebar / 布局 | **复用** |
| （无）Live2D 面孔 | Live2D 自研组件 | **自研（与 TTS 绑定为"面孔+声音"）** |
| （无）TTS 声音 | TTS 自研节点 | **自研（与 Live2D 绑定为"面孔+声音"）** |
| （无）节点状态监控 | nodes 页（引擎/pipeline 状态） | **独有 → slot 插件** |
| （无）提案治理 | ProposalStore（AI 变更审批回退） | **独有 → slot 插件** |

### 1.5 页面级迁移对照（逐页盘点 PySide6 全部页面）

> 补充：原 1.4 按"能力"盘点，此处按"页面"逐一对照 `gui/core/ui_registry.py`
> 注册的全部 10 个侧边栏页面（page.* 插槽）以及 3 个非注册挂载组件，
> 确保迁移清单无遗漏。★ 标记原方案缺失的独有资产。

| # | 页面/组件 | 注册 | 文件 | 核心功能 | 迁移处置 | 备注 |
|---|---|---|---|---|---|---|
| 1 | 聊天页 | page.chat | chat_page.py | 消息列表 + ChatInput + 会话 + 日常/工作切换 + pending/取消 + DSH 提问交互 | **DSH 原生 ui-conversation + smart 模式**（§3.2-3.3） | 已覆盖 |
| 2 | AI 活动页 | page.activity | activity_page.py | AI 事件流（工具/提案/主题/AAA 内心活动轮询 feelings 表） | **独有 → bnos-activity 插件** ★ | 原方案未写；DSH 无"AAA 内心活动"概念 |
| 3 | Live2D 页 | page.live2d | live2d_page.py | 面孔展示（与 TTS 绑定） | 自研（§3.10 方案 A，非插件） | 自研 |
| 4 | 地图页 | page.location | location_page.py | 实时地图 + 位置状态 + 刷新/自动更新/清除历史 | **独有 → bnos-location 插件** ★ | 原方案完全未写 |
| 5 | MCP 管理页 | page.mcp | mcp_page.py | MCP 管理（占位，待开发） | **复用 DSH 原生 MCP** | DSH 本身是 MCP client，待确认 web 端管理 UI |
| 6 | 记忆库 | page.knowledge | widgets/knowledge_panel.py | **数据浏览 + 记忆图谱双视图 + 时间区间筛选**（chatbot.db 多表：diaries/entity_attrs/event_summary/feelings/interest_judgment/location_history + knowledge_graph.json + MoodChart 情绪图） | **独有 → bnos-memory 插件** ★★ | **原方案完全未写；AAA 认知层最核心可视化，DSH 无任何对应** |
| 7 | 提案页 | page.proposals | proposals_page.py | ChangeProposal 审批/回退 | **bnos-governance 插件**（§3.5） | 已覆盖 |
| 8 | AI 工具页 | page.tools | tools_page.py | ToolRegistry 工具卡片（名称/描述/Schema/文件桥状态） | **评估 → ui-tool 或 bnos-tools 插件** | 语义不同：这是"GUI 暴露给 AI 的工具"，DSH ui-tool 是 DSH 自身工具 |
| 9 | 流程页 | page.workflows | workflow_page.py | AAA workflow 双引擎分数（多巴胺×用进废退）+ 👍/👎 反馈 | **独有 → bnos-workflow 插件** ★ | 原方案误判"复用 ui-plan/ui-jobs"——实际是 AAA 认知层流程库，非 DSH plan/jobs |
| 10 | DSH 管理页 | page.dsh_manage | dsh_manage_page.py | 9 分区（模型/会话/任务/工具开关/插件/工作区/运行参数/安全/Agent 预设+人格） | **逐区验证 ui-settings 覆盖度** ⚠ | 原方案假设"复用原生"未验证；extra.patch 编辑/persona 注入/工作区管理等 BNOS 特有配置方式可能需插件化（§5 新增风险） |
| 11 | 节点管理 | （非注册，main_window 挂载） | node_page.py | 引擎启停（进程控制）+ 节点状态（bnos_status）+ 重启（bnos_cmd） | **bnos-status 插件**（§3.4） | 非侧边栏页面；引擎进程控制逻辑需评估 web 化（web 无法直接管本机进程，走 bnos_cmd.json） |
| 12 | 设置面板 | （非注册，main_window 挂载） | settings_panel.py | AppConfig + API key（local_config 三层读取链） | **复用 ui-settings + bnos-settings 插件** | 非侧边栏页面；API key 存储链为 BNOS 特有（local_config.json + 环境变量兜底），需插件保留 |
| 13 | 启动闪屏 | （非注册） | startup_splash.py | 加载界面 | **弃用** | 非功能页，DSH web 自带加载态 |

**新增独有资产清单（原方案缺失）**：
- `bnos-memory`：**记忆库（记忆图谱 + 多表浏览）**——最高优先级独有资产，数据源 chatbot.db + knowledge_graph.json + MoodChart 逻辑
- `bnos-activity`：AI 活动事件流（复用 activity_page 数据源：AI_EVENT + chatbot.db feelings 轮询）
- `bnos-workflow`：AAA 流程库（复用 workflow_store，👍/👎 反馈写回）
- `bnos-location`：AI 定位地图（复用 location_page 数据源：位置 API + 地图渲染）

---

## 二、目标

1. **DSH web 成为 BNOS 统一界面**：聊天/设置/工具/会话/工作区直接使用 DSH web
2. **AAA 保持主流程大脑地位**：对话链路（AAA → llm/DSH → reply）不改变，
   DSH agent loop 不参与对话决策
3. **节点层零改动**：文件协议原样复用，aaa/llm_infer/tts/node_dsh 代码不动
4. **BNOS 独有资产以 slot 插件挂载**：节点监控/提案治理/记忆库/活动流/流程库/定位不丢失；
   **Live2D 组件自研并与 TTS 绑定为"面孔+声音"模块**（不用插件替代，便于统一调试）
5. **双轨兼容**：迁移期间 PySide6 GUI 与 DSH web 可并存，逐步切换

---

## 三、方案设计

### 3.1 总体架构

```
┌─────────────────────────────────────────────┐
│  DSH web（React 客户端，统一界面）            │
│  ├─ ui-conversation（原生聊天）── 选 smart 模式  │
│  │     = 以 AAA 为主要 agent 对话（AAA 人格/记忆）│
│  ├─ ui-settings（Agent 预设中切换 smart）      │
│  ├─ ui-goal / ui-tool / ui-plan（原生）       │
│  └─ slot 插件（BNOS 独有资产）：               │
│       bnos-memory / bnos-status /             │
│       bnos-governance / bnos-activity /       │
│       bnos-workflow / bnos-location           │
│  ·─ 自研（非插件）：Live2D 组件 + TTS         │
│      （绑定为"面孔+声音"模块）                 │
└──────────────┬──────────────────────────────┘
               │ 浏览器 ↔ DSH webserver（Node，本机）
┌──────────────▼──────────────────────────────┐
│  smart 预设（AAA 为主要 agent，第 5 个模式）   │
│  外壳：官方 preset（AAA 人格骨架/记忆注入/工具纪律）│
│  内层：aaa-engine MCP（memory_retrieve /      │
│        context_build / parse_respond /       │
│        cognition_commit）+ 按需工具分配       │
└──────────────┬──────────────────────────────┘
               │ aaa-engine MCP 直读写 AAA 记忆库（nodes/shared/）
┌──────────────▼──────────────────────────────┐
│  BNOS 节点层（零改动）                        │
│  AAA 节点（兜底承接：结果写库存档保记忆链）     │
└─────────────────────────────────────────────┘
```

**职责划分**：
- DSH web：显示与输入（脸）；聊天用原生 ui-conversation
- smart 模式：以 AAA 为主要 agent 的对话/执行（AAA 逻辑内嵌 DSH agent loop）
- AAA 节点：认知/记忆/情感/决策底座 + 首尾承接兜底（大脑）
- node_dsh：执行器官（手）
- slot 插件：BNOS 独有资产（记忆库/活动/节点/提案/流程/定位）
- 自研（非插件，绑定为"面孔+声音"模块）：Live2D 组件 + TTS（统一调试）

### 3.2 聊天方案（核心）：DSH 原生 + smart 模式

**聊天不再插件化、不接管原生**：直接用 DSH 原生 `ui-conversation`，通过第 5 个
预设 **smart（AAA 助理）** 让 DSH agent 以 **AAA 为主要 agent** 运转。
详细设计见 `[PLAN]-DSH工具分配与模式复用闭环方案`，此处只陈述与迁移的关系。

```
用户（DSH 原生聊天）→ DSH agent loop（smart 预设）
  ├─ 意图门（LLM，AAA 现有【工作模式】判定）
  │     不需要 → 直接回复（AAA 人格，0 工具调用）
  │     需要   → 按需调用执行工具（裁剪集，无子代理/编排）
  ├─ 记忆/上下文 → aaa-engine MCP：memory_retrieve / context_build
  └─ 输出 → parse_respond / cognition_commit 沉淀回 AAA 记忆库
外部 AAA 节点：首尾承接兜底（结果过 AAA 解析写库存档，保记忆链）
```

**smart 模式组成（三段式）**：
- 外壳：官方 preset 格式（`DSH_HOME/.agent-presets/smart/`），复制 `standard` 后
  裁剪子代理/编排类 8 个高风险工具，保留 19 个常用执行工具
- 内层：`nodes/shared/mcp_servers/aaa_engine/`（Python MCP server），复用 AAA 现有
  模块，暴露 AAA 认知工具（memory_retrieve / context_build / parse_respond /
  cognition_commit）+ tool_route（按需分配，v1 仅记录）
- 提示词三段式：AAA 人格骨架（与 AAA prompt.py 同源）／记忆注入位（动态填充）／
  工具使用纪律（按需调用、最少够用、不编排、结果按 AAA 格式返回）

**与文件协议的关系**：smart 模式经 aaa-engine MCP 直读写 AAA 记忆库，
**不经 `gui_input.json`/`gui_reply.json`**；原文件协议保留给 PySide6 GUI
（双轨兼容期）与工作模式兜底链路。

### 3.3 模式体系（两套概念的协同）

DSH web 化后存在两套"模式"，需理清而非混淆：

1. **DSH 预设（agent presets）**：standard / code / minimal / cordis / **smart（AAA 助理）**。
   在 DSH 原生 `ui-settings → Agent 预设` 中切换。**smart 即"与 AAA 对话"的模式**
   （BNOS 聊天在 DSH web 的形态），切换入口就是原生预设切换，无需自研按钮。
2. **AAA 意图门（daily/work）**：smart 模式内部，AAA 每次对话先做意图判定
   （LLM 的【工作模式】节，复用 AAA 现有逻辑）——不需要执行 → 直接回复（daily）；
   需要执行 → 按需调用 DSH 工具（work）。

关系：
- **预设切换 = 模式切换**（用户级，DSH 原生设置完成）；
- **daily/work = smart 内部的任务分流**（任务级，AAA 意图门自动判定，无需手动切换）；
- `nodes/shared/mode.json`（daily/work 持久化）作为 AAA 意图门状态存储，
  双轨兼容期与 PySide6 GUI 共用；smart 模式内由 aaa-engine 读写同一文件保持一致。

### 3.4 节点状态监控插件（bnos-status）

- 新增 slot 插件：读 `pipeline.json` + 各节点 `output_*.json` + `bnos_status.json` 渲染
- 功能：节点列表、运行状态、最近输出预览、文件协议可视化
- 与 PySide6 版 nodes 页同数据源（复用读取逻辑，只换渲染层）

### 3.5 提案治理插件（bnos-governance）

- 新增 slot 插件：读写提案存储（ProposalStore 同协议）
- 功能：AI 变更提案展示、审批（通过/拒绝）、回退、历史记录
- 归属 GUI 管理能力（与 DSH permission presets 并存，不做替代）

### 3.6 AI 活动流插件（bnos-activity）

- 新增 slot 插件：实时事件流（工具执行/提案审批/主题变更/**AAA 内心活动**）
- 数据源与 activity_page 一致：AI_EVENT（event_bus）+ `chatbot.db` feelings 表轮询
- 功能：事件列表（type 过滤）、AAA 内心想法上屏、时间线视图

### 3.7 AAA 流程库插件（bnos-workflow）

- 新增 slot 插件：workflow 卡片（双引擎分数：多巴胺 × 用进废退）
- 数据源：workflow_store（`nodes/shared/` 下 workflow 持久化）
- 功能：流程卡片、多巴胺 Q 值/用进废退权重展示、👍/👎 外部评价写回（RPE 校准）
- ⚠ 区别于 DSH 原生 ui-plan/ui-jobs（那是 DSH 的规划/任务列表），本插件是 AAA 认知层流程库

### 3.8 AI 定位插件（bnos-location）

- 新增 slot 插件：实时地图 + 位置状态
- 数据源与 location_page 一致（位置 API + 地图渲染，复用 `location_map_widget` 逻辑）
- 功能：大尺寸地图、城市/精度/来源信息栏、刷新位置/自动更新/启用位置/清除历史
- > **市场现成替代（2026-08）**：无地图可视化插件。最接近为 `dsh-environment-context`
  （把实时时间/天气/**地点**/电量/设备信息注入模型上下文，双语设置页）。若 BNOS 定位的诉求是
  "AI 感知自己在哪（城市/天气）"而非给用户看地图，可直接用该插件、免自研；若确需地图面板，
  则需自研 web 地图组件（Leaflet / 高德 / 百度地图 web）对接 BNOS 位置 API。

### 3.9 记忆库插件（bnos-memory）★ 最高优先级

- 新增 slot 插件：**AAA 认知层最核心的可视化**（DSH 无任何对应）
- 数据源与 KnowledgePanel 一致：
  - `chatbot.db` 多表浏览（diaries/entity_attrs/event_summary/feelings/interest_judgment/location_history，排除 fixed_cognition）
  - `knowledge_graph.json`（AAA 预计算图谱）+ 余弦相似度分段力导向布局（>=0.7 强吸引 / 0.4-0.7 弱斥 / <0.4 强斥）
  - MoodChart 情绪图（复用 mood_chart 逻辑）
- 功能：双视图（数据浏览 + 记忆图谱）、时间区间筛选、节点双击跳转详情
- ⚠ 力导向图谱 Qt GraphicsView → web 需重写（d3-force 或 canvas 方案），是独有插件中工作量最大的

### 3.10 Live2D / TTS（自研，绑定为"面孔+声音"模块）

> **方向（2026-08-24 修订）**：Live2D 相关组件**自研**，并与 TTS **绑定**为统一的
> "面孔+声音"模块，**不采用任何可替代的现成插件**（插件调试链路繁琐、效果难统一）。
> 本计划中所有"可用插件替代 / 免自研"的 Live2D/TTS 描述一律改为自研。

- **方案 A（自研，推荐，低成本）**：保留自研 PySide6 轻量窗口做"面孔+声音"
  ——DSH web 主界面 + 旁边一个只含自研 Live2D + TTS 的 Python 小窗
- **方案 B（自研 web）**：自研 web 版 Live2D 运行时（pixi-live2d-display / three.js）
  + 服务端 TTS（自研 tts 节点）推送音频流；**不接入任何市场 Live2D/TTS 插件**
- 影响面：方案 A 不动现有自研 Live2D/TTS 代码；方案 B 需评估 web 集成工作量
- **与 TTS 绑定**：面孔（Live2D）与声音（TTS）的进程生命周期、口型同步、热开关统一管理

### 3.11 双轨兼容（迁移期）

- PySide6 GUI 与 DSH web **并存**：两者都只读写同一批 shared/*.json，天然无冲突
  （文件协议是单点；谁在线谁消费，按 mtime/hash 判新，互不干扰）
- 迁移完成标志：DSH web 功能覆盖 PySide6 全部页面后，PySide6 GUI 停用

---

## 四、分阶段实施计划

### Phase 0：bridge 最小原型（验证可行性）

> ✅ **已完成（2026-08-24）**：验证了 DSH web 的**插件扩展链路**（宿主插件 +
> webServer 路由 + 客户端 slot 插件 + boot graph + bundle 服务），并临时以
> BNOS 聊天页签跑通"浏览器 → AAA 日常模式 → 回复"端到端链路。
> ⚠ **方向修正**：经确认，聊天**不做独立页签、不接管原生**，改为
> **DSH 原生聊天 + smart 模式**（见 §3.2）。bridge 聊天链路作为技术验证保留，
> 代码暂不重构；正式聊天方案见 `[PLAN]-DSH工具分配与模式复用闭环方案`。

- [x] 确认 DSH web 本地启动链路（node_dsh webserver + 浏览器访问）
- [x] 验证 DSH web 插件扩展链路（slot/loader/client-modules/bundle 服务）
- [x] 端到端验证：浏览器 → AAA 日常模式回复完整显示（临时 BNOS 页签）
- [ ] **（方向调整）** 聊天改为 DSH 原生 + smart 模式，移除独立 BNOS 页签形态

### Phase 1：smart 模式聊天落地（替代原"bridge 聊天功能完整化"）

> 聊天主体随 smart 预设落地，详见 `[PLAN]-DSH工具分配与模式复用闭环方案`。

- [ ] smart 预设落地：官方 preset 格式（AAA 人格骨架 + 记忆注入位 + 工具纪律）
- [ ] aaa-engine MCP server：memory_retrieve / context_build / parse_respond / cognition_commit
- [ ] 意图门（daily/work）在 smart 内嵌生效（复用 AAA 现有【工作模式】判定）
- [ ] 按需工具分配：工具裁剪（去子代理/编排 8 个）+ 纪律提示词 + 工具日志（`dsh_tool_usage_log.jsonl`）
- [ ] 外部 AAA 节点兜底承接（结果回写库存档，保记忆链）
- [ ] DSH 原生会话切换 / 附件 / 错误处理（随原生能力验证，无需自研）

### Phase 2：独有资产插件化

> **市场现成插件评估（2026-08，来源：插件市场目录 awesome-dsh-plugin.com/plugins.json，
> 该目录聚合 GitHub `dsh-plugin` 主题仓库 + npm 发布包，含 30 天下载量/GitHub 星标排序）**。
> 对照 §1.5 的 8 个独有资产，结论如下（"免自研"= 直接用现成插件；"自研"= 数据源/概念独有）：

| BNOS 资产 | 市场现成插件 | 处置 |
|---|---|---|
| Live2D（面孔） | 无（自研，不用市场插件） | **自研（与 TTS 绑定）** |
| TTS（声音） | 无（自研，不用市场插件） | **自研（与 Live2D 绑定）** |
| ASR 语音输入 | 无（自研，不用市场插件） | **自研** |
| AI 感知位置/天气（若定位仅需"AI 感知"） | `dsh-environment-context` | **免自研** |
| bnos-activity 活动流 | 原生 ui-trajectory + `dsh-codex-timeline`（轮次导航）+ `dsh-strata`（会话缩略图） | 部分替代；**AAA 内心活动上屏自研** |
| bnos-workflow 流程库 | `dsh-task-board` / `dsh-project-kanban`（看板）+ 原生 ui-plan/ui-goal | 执行可替代；**AAA 双引擎评分自研** |
| bnos-status 节点状态 | `dsh-context` / `dsh-cost-meter` / `dsh-spend` / control-center（DSH 会话/用量/费用仪表盘） | DSH 侧可替代；**BNOS 引擎节点（AAA/llm/tts/node_dsh）状态自研** |
| bnos-governance 提案治理 | `dsh-config-manager`（整套配置备份/导出/回滚）+ DSH 原生 approval + `dsh-approval-*` | 备份回滚/审批可借鉴；**AI 变更提案卡自研** |
| bnos-memory 记忆库 | 无（hindsight/mneme/layered 等是记忆**引擎**，非 AAA 记忆库可视化） | **自研（优先）** |
| bnos-location（地图面板） | 无地图可视化 | **自研**（若能退化为"AI 感知"则免） |
| 工具图谱（工具调用可视化） | 无（dsh-tool-lens 是代码 AST 图谱；tool-call-stats 是数字统计） | **自研**（`dsh_tool_usage_log.jsonl` 数据源已有） |

- [ ] **bnos-memory 记忆库插件**（**自研·优先**：AAA 认知层核心可视化，含图谱 web 化——d3-force/canvas 重写力导向布局）
- [ ] bnos-status 节点监控插件（**自研**：BNOS 引擎节点状态；DSH 会话/用量侧可先用 `dsh-context`/`dsh-spend`）
- [ ] bnos-governance 提案治理插件（**自研**：AI 变更提案卡；备份回滚借用 `dsh-config-manager`）
- [ ] bnos-activity AI 活动流插件（**部分自研**：AAA 内心活动上屏；轨迹/时间线用原生 ui-trajectory + `dsh-codex-timeline`/`dsh-strata`）
- [ ] bnos-workflow AAA 流程库插件（**部分自研**：双引擎评分；任务看板用 `dsh-task-board`/`dsh-project-kanban`）
- [ ] bnos-location AI 定位插件（**按需**：仅需"AI 感知位置/天气"→ 用 `dsh-environment-context` 免自研；需地图面板→ 自研）
- [ ] **Live2D/TTS**（**自研**，绑定为"面孔+声音"模块；ASR 语音输入亦自研，不用市场插件）
- [ ] DSH 管理页 9 分区逐区验证（ui-settings 覆盖度报告）
- [ ] 文件浏览/IDE 工作台（**界面补充**）：better-sidebar 在桌面壳下客户端 UI 未渲染、powerdesk
  需新版运行时——改用 `dsh-plugin-workbench`（VS Code 风格文件树 + 可编辑预览）或
  `dsh-workspace-explorer`（工作区文件树面板）作为"看文件/目录"入口

### Phase 3：设置/工具/会话全量迁移

- [ ] 校验 DSH 原生设置页覆盖 settings_panel + dsh_manage 9 分区
- [ ] 校验 ui-goal/ui-plan/ui-jobs/ui-tool/ui-workspace 覆盖 workflow/activity/tools
- [ ] 皮肤/主题迁移（DSH ui-theme 替代 ThemeEngine）
- [ ] 双轨并行回归，确认功能对等

### Phase 4：PySide6 GUI 退役

- [ ] 全功能对等清单核验
- [ ] PySide6 GUI 停用（保留源码与文档，不删除）

---

## 五、风险评估

| 风险 | 缓解 |
|---|---|
| bridge 写 gui_input 与 PySide6 并发 | 文件协议单点 + mtime/hash 判新，天然互斥；双轨期同一时刻仅一个客户端在线 |
| DSH web 需要本机 webserver | node_dsh 已在本机运行（headless fork + webserver），前提已具备 |
| smart 预设（AAA 为主要 agent）落地难度 | 官方 preset + MCP 通道，非侵入 harness；先做最小 preset 验证意图门/记忆注入再全量 |
| Live2D/TTS 自研集成成本高 | 默认走方案 A（保留自研 PySide6 小窗，"面孔+声音"绑定），成本最低，不影响主迁移 |
| request_id 协议细节不一致（仅双轨期文件协议链路） | 现有实现严格复用 MessageManager 逻辑（mtime+hash+id 过滤+标签剥离）；smart 模式不经文件协议，不受影响 |
| DSH 升级后插件兼容 | 插件按官方 slot 规范编写；升级前做快照测试 |
| dsh_manage 9 分区未被 ui-settings 完全覆盖 | Phase 2 先做"9 分区覆盖度报告"（逐区对照），不足部分插件化（extra.patch/persona/工作区等） |
| AAA 主流程被 DSH agent 抢话 | smart 模式下 DSH agent 以 AAA 为主要 agent 运转（人格/记忆/输出格式内嵌），对话决策由内嵌 AAA 逻辑驱动；外部 AAA 节点首尾承接兜底，结果回写库存档保记忆链 |
| tools_page 与 ui-tool 语义错位（GUI 工具 vs DSH 工具） | 先评估 ui-tool 能否展示 ToolRegistry 工具；不能则 bnos-tools 插件独立呈现 |
| 记忆图谱 Qt GraphicsView → web 重写工作量 | bnos-memory 列为最高优先级单独排期；web 图谱用 d3-force/canvas 重写力导向布局，行为对标（阈值/分段斥力） |
| 引擎进程控制 web 化（node_page 直接管进程） | web 不直接管本机进程，统一走 bnos_cmd.json（start/stop/restart 命令由节点侧执行），node_page 进程逻辑不迁移 |

---

## 六、测试计划

- **单元**：bridge 输入格式与 MessageManager 对照（字段逐一相等）；request_id 过滤；
  pending/silent 标签剥离；发送状态锁
- **集成（offscreen/CLI）**：bridge 写 gui_input → AAA 处理 → gui_reply 渲染；
  工作模式直通回执；模式切换（按钮写 mode.json + AAA 关键词切换后状态同步）
- **端到端**：DSH web 浏览器 → 日常聊天 → 回复显示；工作模式 → DSH 执行 → 结果回流；
  双轨（PySide6 与 web 同开）无冲突
- **回归**：AAA/llm_infer/tts/node_dsh 零改动下全链路正常

---

## 七、影响范围

| 文件 | 改动 |
|---|---|
| `DSH_HOME/.agent-presets/smart/` | 新增：smart 预设（AAA 人格骨架/记忆注入/工具纪律，复制 standard 裁剪） |
| `nodes/shared/mcp_servers/aaa_engine/` | 新增：aaa-engine MCP server（AAA 认知工具 + 按需分配，Phase 1） |
| `nodes/shared/dsh_tool_usage_log.jsonl` | 新增：工具使用日志（smart 观察数据，Phase 1） |
| `nodes/node_dsh/harness/packages/client/bnos-status/` | 新增：节点监控插件（Phase 2） |
| `nodes/node_dsh/harness/packages/client/bnos-governance/` | 新增：提案治理插件（Phase 2） |
| `nodes/node_dsh/harness/packages/client/bnos-memory/` | 新增：记忆库插件（多表浏览 + 记忆图谱 + 情绪图，Phase 2 优先） |
| `nodes/node_dsh/harness/packages/client/bnos-activity/` | 新增：AI 活动流插件（Phase 2） |
| `nodes/node_dsh/harness/packages/client/bnos-workflow/` | 新增：AAA 流程库插件（Phase 2） |
| `nodes/node_dsh/harness/packages/client/bnos-location/` | 新增：AI 定位插件（Phase 2） |
| `nodes/node_dsh/harness/packages/client/bnos-settings/` | 新增（按需）：API key/local_config 设置插件（Phase 2-3） |
| AAA / llm_infer / tts / node_dsh 节点 | **零改动**（文件协议原样复用） |
| `gui/`（PySide6） | **不改**（双轨并存，Phase 4 后停用） |
| `docs/changelogs/` | 每 Phase 落地记 changelog |

---

## 八、待决策项

1. **聊天实现方式（已定，2026-08-24）**：DSH 原生聊天 + smart 模式（AAA 为主要
   agent），**不做独立 bnos-chat 页签、不接管 ui-conversation**。细节见
   `[PLAN]-DSH工具分配与模式复用闭环方案`。
2. **资产数据通道（原 bridge 角色）**：bnos-memory 等 slot 插件读节点数据
   （chatbot.db / pipeline.json / 节点状态）的通道方式：
   - A. 宿主插件暴露 webServer 路由（骨架已验证，bridge 代码可复用）
   - B. 独立 `dsh-bridge` Node 服务（不动 DSH 官方包结构）
   - 倾向：A（复用已验证的 bridge 宿主骨架，符合"以 DSH 为载体"）

3. **Live2D / TTS 集成方式（自研，不用插件）**：
   - A. 保留自研 PySide6 轻量窗口（只含面孔+声音），DSH web 为主界面（推荐，成本最低）
   - B. 自研 web 版 Live2D 运行时 + 服务端 TTS 推送（全浏览器化，成本高）

4. **DSH agent loop 定位**：smart 模式下 DSH agent loop **以 AAA 身份参与对话**
   （人格/认知来自 AAA，结果回 AAA 写库存档），DSH agent 不"独立"决策。
   工作模式（需要外部执行的复杂任务）经 AAA 意图门判定后调用 DSH 工具——
   是否需要将这一约定正式写入 DSH 使用约定文档。

5. **PySide6 GUI 退役时机**：Phase 4 全功能对等后停用，或保留为可切换的备选界面

6. **node_dsh 退役路径（2026-08-24 补充）**：smart 模式落地 + DSH Desktop 承接 GUI 后，
   node_dsh 的三个职能（承载 DSH 实例 / AAA↔DSH 任务桥 `dsh_task_in.json` / 环境注入）
   分别被取代：DSH Desktop（统一实例；其内嵌 harness v0.1.1-rc.2 比 node_dsh 的
   0.1.0-rc.5 更新，双实例已造成插件双装与版本漂移）承载界面与执行；smart 模式意图门 +
   工具直连取代文件协议桥；环境注入降级为引擎启动脚本职责。退役条件（按序满足）：
   smart v1 落地并通过 8 条验收 → 执行链路切到 smart 直连 → 随 PySide6 GUI 退役
   （Phase 4）一并退役，代码保留不删。前置待决：AAA 后台"心跳"逻辑（意识流/记忆巩固/
   情绪维护）归属——aaa-engine MCP 内置后台线程 vs 保留轻量 AAA 认知维护进程，
   此决策同时决定 AAA 节点进程的去留。

---

## 附：与现有方案的关系

- [OK]-AAA直连DSH节点与模式切换方案：**本方案的节点侧底座**（AAA 主流程已成立），
  本方案只替换"客户端"（PySide6 → DSH web），节点侧零改动
- [PLAN]-GUI可插拔化与AI操控UI完整方案：自研 GUI 的插槽/主题/提案体系，
  本方案以 DSH ui-slots/ui-theme 替代，**BNOS 独有部分（提案/节点）转 slot 插件保留**
- [PLAN]-DeepSeekHarness接入方案：node_dsh 节点接入的基础，DSH web 运行前提
