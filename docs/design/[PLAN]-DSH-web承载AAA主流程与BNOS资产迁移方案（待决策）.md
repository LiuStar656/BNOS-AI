# [PLAN] DSH Web 承载 AAA 主流程与 BNOS 资产迁移方案（待决策）

> 日期：2026-08-16 ｜ 版本：v1.0 ｜ 状态：[PLAN]（待决策）
> 关联：[OK]-AAA直连DSH节点与模式切换方案 ｜ [PLAN]-DeepSeekHarness接入方案 ｜ [PLAN]-GUI可插拔化与AI操控UI完整方案

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

### 1.2 关键方向确认（2026-08-16）

- **DSH 为主壳**：聊天/设置/工具/会话等直接用 DSH web；BNOS 独有资产
  （Live2D/TTS/节点监控/提案治理）写成 slot 插件挂载
- **AAA 主流程**：对话主链路仍是 AAA（想）→ DSH（做），AAA 保持大脑地位；
  DSH web 只当"脸"，**DSH agent loop 不参与对话决策**
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

**结论：DSH web 化不需要改造 AAA——只需要把"GUI 轮询文件"换成"web 轮询文件"。**

### 1.4 DSH web 能力盘点（迁移复用表）

| DSH web 组件 | BNOS 对应 | 处置 |
|---|---|---|
| ui-conversation | chat_page（聊天） | **复用**，bridge 接管输入输出 |
| ui-settings-*（models/plugins/general/presets） | settings_panel + dsh_manage 9 分区 | **复用**（原生） |
| ui-goal / ui-plan / ui-jobs / ui-skill | workflow/activity 页 | **复用**（原生） |
| ui-tool / ui-subagent / ui-workspace | tools 页 | **复用**（原生） |
| ui-theme（token 主题） | theme_engine | 复用（DSH 生态更广） |
| ui-sidebar / ui-layout | sidebar / 布局 | **复用** |
| （无）Live2D 面孔 | Live2D 架构 | **独有 → slot 插件** |
| （无）TTS 声音 | TTS 节点 | **独有 → 服务端 + web 播放** |
| （无）节点状态监控 | nodes 页（引擎/pipeline 状态） | **独有 → slot 插件** |
| （无）提案治理 | ProposalStore（AI 变更审批回退） | **独有 → slot 插件** |

### 1.5 页面级迁移对照（逐页盘点 PySide6 全部页面）

> 补充：原 1.4 按"能力"盘点，此处按"页面"逐一对照 `gui/core/ui_registry.py`
> 注册的全部 10 个侧边栏页面（page.* 插槽）以及 3 个非注册挂载组件，
> 确保迁移清单无遗漏。★ 标记原方案缺失的独有资产。

| # | 页面/组件 | 注册 | 文件 | 核心功能 | 迁移处置 | 备注 |
|---|---|---|---|---|---|---|
| 1 | 聊天页 | page.chat | chat_page.py | 消息列表 + ChatInput + 会话 + 日常/工作切换 + pending/取消 + DSH 提问交互 | **bridge 接管 ui-conversation**（§3.2-3.3） | 已覆盖 |
| 2 | AI 活动页 | page.activity | activity_page.py | AI 事件流（工具/提案/主题/AAA 内心活动轮询 feelings 表） | **独有 → bnos-activity 插件** ★ | 原方案未写；DSH 无"AAA 内心活动"概念 |
| 3 | Live2D 页 | page.live2d | live2d_page.py | 面孔展示 | 方案 A/B（§3.11） | 已覆盖 |
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
4. **BNOS 独有资产以 slot 插件挂载**：Live2D/TTS/节点监控/提案治理不丢失
5. **双轨兼容**：迁移期间 PySide6 GUI 与 DSH web 可并存，逐步切换

---

## 三、方案设计

### 3.1 总体架构

```
┌─────────────────────────────────────────────┐
│  DSH web（React 客户端，统一界面）            │
│  ├─ ui-conversation（聊天）← bridge 接管      │
│  ├─ ui-settings / ui-goal / ui-tool ...      │
│  └─ slot 插件：bnos-chat / bnos-status /      │
│       bnos-governance / bnos-live2d /        │
│       bnos-tts（独有资产）                    │
└──────────────┬──────────────────────────────┘
               │ 浏览器 ↔ DSH webserver（Node，本机）
┌──────────────▼──────────────────────────────┐
│  Bridge 服务（新增，Node，dsh 客户端插件）    │
│  复用 BNOS 文件协议，作为 web 与节点的翻译层   │
└──────────────┬──────────────────────────────┘
               │ 读写 nodes/shared/*.json（协议不变）
┌──────────────▼──────────────────────────────┐
│  BNOS 节点层（零改动）                        │
│  AAA（想）→ llm_infer / node_dsh（做）→ AAA → reply │
└─────────────────────────────────────────────┘
```

**职责划分**：
- DSH web：显示与输入（脸）
- AAA：认知/记忆/情感/决策（大脑）
- node_dsh：执行器官（手）
- Bridge：文件协议 ↔ DSH 内部 RPC 的翻译层（新增，唯一的"桥"）

### 3.2 Bridge 插件设计（核心）

新增 DSH 客户端插件包（React/TS），命名 `dsh-client-bnos-chat`（先做聊天，
其余独有资产按 3.3-3.10 分插件扩展）：

**职责**：接管 `ui-conversation` 的输入输出，转发到 BNOS 文件协议。

```
用户输入（web）→ 写 gui_input.json（与 MessageManager 完全同格式）
   {data_type: text, content, source: gui, identity_key: gui:web,
    conversation_id, request_id(uuid8), timestamp}
    ↓
AAA 处理（daily: llm / work: dsh 直通）→ reply 写 gui_reply.json
    ↓
bridge 轮询 gui_reply.json（mtime + md5 判新，同 MessageManager L172-194）
    ↓
解析 reply（content / request_id 匹配 / <pending/> <silent/> 标签剥离）
    ↓
渲染进 ui-conversation
```

**协议对齐点（务必与 MessageManager 一致）**：
- request_id：发送时生成 uuid4 hex8，只接受匹配 reply（过期回复丢弃）
- `<pending/>`：工作模式 DSH 执行中回执，UI 保持等待指示
- `<silent/>`：仅抑制 TTS 播报，显示正常
- 发送状态锁：sending 状态下忽略新输入

**实现位置**：`nodes/node_dsh/harness/packages/client/bnos-chat/`
（注册方式按 client 规范：tsconfig/tsdown/cordis.patch/package.json 四处）
也可挂载到独立 `dsh-bridge` 服务进程，避免侵入 DSH 官方包结构（见待决策项 8.1）。

### 3.3 模式切换（日常/工作）

- Bridge 渲染顶部「日常/工作」切换按钮（复用 chat_page 现有逻辑）
- 切换写 `nodes/shared/mode.json`（原子写，与 GUI/AAA 共用同一文件）
- 按钮状态每秒同步；AAA 关键词自动切换后 Bridge 保持一致

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

### 3.9 记忆库插件（bnos-memory）★ 最高优先级

- 新增 slot 插件：**AAA 认知层最核心的可视化**（DSH 无任何对应）
- 数据源与 KnowledgePanel 一致：
  - `chatbot.db` 多表浏览（diaries/entity_attrs/event_summary/feelings/interest_judgment/location_history，排除 fixed_cognition）
  - `knowledge_graph.json`（AAA 预计算图谱）+ 余弦相似度分段力导向布局（>=0.7 强吸引 / 0.4-0.7 弱斥 / <0.4 强斥）
  - MoodChart 情绪图（复用 mood_chart 逻辑）
- 功能：双视图（数据浏览 + 记忆图谱）、时间区间筛选、节点双击跳转详情
- ⚠ 力导向图谱 Qt GraphicsView → web 需重写（d3-force 或 canvas 方案），是独有插件中工作量最大的

### 3.10 Live2D / TTS（待决策，见 §八）

- **方案 A（推荐，低成本）**：保留 PySide6 轻量窗口做"面孔+声音"
  ——DSH web 主界面 + 旁边一个只含 Live2D/TTS 的 Python 小窗
- **方案 B**：web 版 Live2D 运行时（pixi-live2d-display）+ 服务端 TTS（tts 节点）推送音频流
- 影响面：方案 A 不动现有 Live2D/TTS 代码；方案 B 需评估 web 集成工作量

### 3.11 双轨兼容（迁移期）

- PySide6 GUI 与 DSH web **并存**：两者都只读写同一批 shared/*.json，天然无冲突
  （文件协议是单点；谁在线谁消费，按 mtime/hash 判新，互不干扰）
- 迁移完成标志：DSH web 功能覆盖 PySide6 全部页面后，PySide6 GUI 停用

---

## 四、分阶段实施计划

### Phase 0：bridge 最小原型（验证可行性）

- [ ] 确认 DSH web 本地启动链路（node_dsh webserver + 浏览器访问）
- [ ] 新建 `dsh-client-bnos-chat` 最小插件：拦截输入写 gui_input.json
- [ ] 轮询 gui_reply.json 渲染回复（含 request_id 过滤、pending 处理）
- [ ] 验收：web 聊天 → AAA 日常模式回复完整显示

### Phase 1：聊天功能完整化

- [ ] 模式切换按钮（读/写 mode.json + 状态同步）
- [ ] 工作模式直通显示（pending 回执 + 最终结果）
- [ ] 会话切换（conversation_id 传递）
- [ ] 附件发送（缓存附件 + attachments 字段）
- [ ] 错误处理（60s 超时、发送状态锁、过期回复丢弃）

### Phase 2：独有资产插件化

- [ ] **bnos-memory 记忆库插件**（优先：AAA 认知层核心可视化，含图谱 web 化）
- [ ] bnos-status 节点监控插件
- [ ] bnos-governance 提案治理插件
- [ ] bnos-activity AI 活动流插件
- [ ] bnos-workflow AAA 流程库插件
- [ ] bnos-location AI 定位插件
- [ ] DSH 管理页 9 分区逐区验证（ui-settings 覆盖度报告）
- [ ] Live2D/TTS 集成（方案 A 或 B，待决策后实施）

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
| ui-conversation 接管难度 | 官方设计允许替换/新增 UI 插件（client 规范明示）；先做最小原型验证再全量 |
| Live2D/TTS web 集成成本高 | 默认走方案 A（保留 PySide6 小窗），成本最低，不影响主迁移 |
| request_id 协议细节不一致 | Bridge 严格复用 MessageManager 逻辑（mtime+hash+id 过滤+标签剥离），做对照测试 |
| DSH 升级后插件兼容 | 插件按官方 slot 规范编写；升级前做快照测试 |
| dsh_manage 9 分区未被 ui-settings 完全覆盖 | Phase 2 先做"9 分区覆盖度报告"（逐区对照），不足部分插件化（extra.patch/persona/工作区等） |
| AAA 主流程被 DSH agent 抢话 | Bridge 只接管 ui-conversation 的收发，DSH agent loop 不注入对话；work 模式仍走 AAA→node_dsh |
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
| `nodes/node_dsh/harness/packages/client/bnos-chat/` | 新增：bridge 聊天插件（输入/轮询/渲染/模式/会话/附件） |
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

1. **Bridge 实现位置**：
   - A. 挂载为 DSH 客户端 slot 插件（`dsh-client-bnos-chat`，按官方规范）
   - B. 独立 `dsh-bridge` Node 服务（不动 DSH 官方包结构，web 通过现有 RPC 连它）
   - 倾向：A（复用官方 slot 体系，符合"以 DSH 为载体"）；若侵入成本高则退 B

2. **Live2D / TTS 集成方式**：
   - A. 保留 PySide6 轻量窗口（只含面孔+声音），DSH web 为主界面（推荐，成本最低）
   - B. web 版 Live2D 运行时 + 服务端 TTS 推送（全浏览器化，成本高）

3. **DSH agent loop 定位**：确认 DSH 在 BNOS 中**永远只当执行器官**（AAA 工作模式调用），
   不参与日常对话决策——是否需要正式写入 DSH 使用约定文档

4. **PySide6 GUI 退役时机**：Phase 4 全功能对等后停用，或保留为可切换的备选界面

---

## 附：与现有方案的关系

- [OK]-AAA直连DSH节点与模式切换方案：**本方案的节点侧底座**（AAA 主流程已成立），
  本方案只替换"客户端"（PySide6 → DSH web），节点侧零改动
- [PLAN]-GUI可插拔化与AI操控UI完整方案：自研 GUI 的插槽/主题/提案体系，
  本方案以 DSH ui-slots/ui-theme 替代，**BNOS 独有部分（提案/节点）转 slot 插件保留**
- [PLAN]-DeepSeekHarness接入方案：node_dsh 节点接入的基础，DSH web 运行前提
