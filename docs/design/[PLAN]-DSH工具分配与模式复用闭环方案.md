# DSH 工具分配与模式复用闭环方案

> 状态：`[PLAN]`（待评审）
> 主方案：`[PLAN]-DeepSeekHarness接入方案.md` 的延伸扩展
> 前置：DSH 已接入（node_dsh + headless profile）、AAA 直连 DSH 已落地、`DSH_PRESET` 环境变量按任务注入可用
> 实施策略：**零重构——新增第 5 个自创模式"smart"（AAA 为主要 agent + 按需工具分配；外壳官方 preset 挂载 + 内层自研 MCP 引擎），不做 AAA 主流程改造；先观察记录，验证后决定是否上学习系统**

---

## 1. 目标与实施策略

在不引入多 agent 编排、**不做大量重构**的前提下，用"按任务自律分配工具"替代"每次固定全量工具集"，作为官方 4 个预设之外的**第 5 个自创模式**（smart）供选择使用；该模式的 **agent 以 AAA 为主要 agent 运转**——人格/认知来自 AAA，工具执行按需分配。

**目标**：
1. **AAA 为主要 agent**：smart 模式运行时 agent 以 AAA 身份工作（人格内嵌、记忆随行、输出按 AAA 格式），不依赖外部节点接力；外部 AAA 仅作首尾承接兜底。
2. **减少调用**：工具只用于"需要外部信息/操作"的任务环节，纯文本可答的环节不调用工具。
3. **减少 token/轮次**：裁剪高风险高成本工具（子代理/编排类），执行期工具池更小、更聚焦。
4. **积累观察**：通过模式使用过程中的工具调用痕迹（工具日志 / 工具图谱），验证"工具自律分配"是否有效，作为是否升级学习系统的依据。

**实施策略（零重构，先观察不学习）**：
- **v1（本次实施）**：新增自创模式 smart = **外壳（官方 preset 格式）+ 内层（自研 MCP server）**：
  - 外壳：官方用户预设目录（`DSH_HOME/.agent-presets/`，非侵入 harness 源码），挂载自研 MCP server + 裁剪后的常用执行工具 + 三段式提示词（AAA 人格骨架 / 记忆注入位 / 工具纪律）。
  - 内层：自研 MCP server（`nodes/shared/mcp_servers/aaa_engine/`，Python，复用 AAA 现有模块加 MCP 外壳），暴露 AAA 认知工具（记忆检索 / 上下文构建 / 解析 / 沉淀）与按需分配工具（v1 仅记录）。
  - **不改 AAA `main.py` / `dsh_client` / node_dsh 内核**。
- **v2（验证后决定）**：若观察数据证明"任务→工具映射需要学习才能得到"，再启用模式库 + 匹配 + 奖惩 + 交集收敛的学习系统（见 4.3）。**学习系统不做则不加。**

> 设计取舍：不做 AAA 静态映射路由（不重构主流程），改为"模式级自律"——外壳走官方 preset（DSH 原生识别、可切换、可逆），内层走官方 MCP 通道（零源码改动、零官方更新冲突）。学习系统复杂度高且冷启动期净亏，只有观察数据证明必要才投入。

## 2. 现状与关键事实

### 2.1 DSH 一次任务的本质

```
一次 DSH 任务（headless）= 1 个 agent（1 个 LLM 循环会话，挂 1 个 preset）
  └─ agent loop：LLM 想 → 调工具 → 看结果 → 再想 → … → 完成
```

- **一个 preset 内部不是多个 agent**，而是一个 agent + 一组工具；工具调用顺序由模型在会话内自由编排（工具调用流程）。
- **工具全量注入**：模型每次 LLM 请求都携带 preset 工具集的完整 schema（工具目录），"看到"的是全部、"调"的才是需要的。
- **工具池大小 = preset 决定**，与任务内容无关。当前所有任务固定挂 `standard`（默认），模型每次都拿到 ~25 个工具的全量 schema。

### 2.2 官方预设与自创机制

| preset | 工具数 | 构成 | 适用 |
|---|---|---|---|
| `standard` | ~25 | 全套 | 通用执行（默认） |
| `code` | ~25（以 `run_code` 呈现） | 全套 + Code Mode（一次程序多步，省轮次） | 批量/多步操作 |
| `minimal` | **2** | `bash` + `str_replace_editor` | 轻量快速 |
| `cordis` | ~32 | standard + 7 个自改工具 | 自我修改 |

- 自创 preset 通过官方 copy 机制（`agent-presets`）裁剪任意工具组合；**用户预设目录 `DSH_HOME/.agent-presets/`**（`USER_PRESET_DIR = '.agent-presets'`，`dshHomePath` 解析，`includeUserRoot` 时扫描），**不侵入 harness 源码**。
- `DSH_PRESET` 环境变量支持按任务注入（headless-runner 读取）；GUI「DSH 管理-预设管理」维护全局 preset（runtime.json）。
- 工具全量注入成本：全池 ~25 工具 schema ≈ 数千 token/轮，工具越多每轮越贵、选择越易偏（末位偏置经验）。

## 3. 总体流程

> **首尾 AAA 承接（硬约束）**：主流程输入先进 AAA、输出由 AAA 给出（`[OK]-AAA直连DSH节点与模式切换方案` 的 AAA → DSH → AAA 链路）。凡调用工具（DSH）的情况，**DSH 结果必须回 AAA 过一遍**：按 AAA 输出格式解析节（情绪/自我认知/他人认知/事件摘要/记忆）→ 写库存档 → 再推送 GUI。**严禁 DSH 结果直通 GUI**，否则 AAA 记忆断链。本方案为"预设级"，不改动既有输出/存档链路。

### v1 流程（本次实施）

```
用户在 GUI「DSH 管理-预设管理」切换到"smart / AAA 助理"模式（第 5 个模式）
  │
  ▼
用户输入（GUI → AAA）
  │
  ▼
意图门（LLM，现有【工作模式】判定）────── 不需要 → 直接回复（0 调用，现状已有）
  │ 需要
  ▼
DSH 任务：1 个 agent + "smart" 模式（AAA 为主要 agent）
  │      ├─ 外壳：preset 挂载 aaa-engine MCP server + 裁剪后的常用执行工具（~19 个）
  │      ├─ 内层：aaa-engine（Python）——AAA 认知工具（记忆检索/上下文构建/解析/沉淀）+ 按需分配（v1 仅记录）
  │      ├─ 提示词三段式：AAA 人格骨架 / 记忆注入位（含 AAA 完整上下文）/ 工具使用纪律
  │      └─ 任务仍按 AAA 输出格式返回（含节标记）
  │
  ▼
回 AAA 承接（复用 _dsh_wait_and_push 认知链，兜底）：
  │      ├─ 解析节 → 写库存档（情绪/认知/事件摘要/记忆，role=assistant）
  │      ├─ 顺带记录工具日志（见 4.2）
  │      └─ 推送 GUI（注入心情标签的最终回复）
```

**可逆性**：效果不佳 → GUI 切回 `standard` 即还原，无残留改动。

### v2 升级路径（验证后决定）

若观察数据证明需要，v2 再引入"任务 → 工具集"的**确定性路由**（AAA 侧静态映射表 或 模式库学习），此时才动 AAA 主流程（见 4.3）。v1 的预设与观察数据是 v2 的决策依据与基础。

## 4. 详细设计

### 4.1 smart 模式：AAA 为主要 agent（v1，核心）

**命名**：`smart`（示例名，待决策，候选 `frugal` / `focused` / `selective`）。中文显示名"AAA 助理"。

**定位**：不是官方 preset"标准工具 + 通用提示词"的形态，而是**把 AAA 作为主要 agent、按需工具分配机制内嵌**的完整模式。DSH 提供 agent 循环外壳，模式内部由自研引擎驱动——**外壳官方 + 内层自研**，两层均走官方扩展机制，与官方更新零冲突。

**架构**：

```
DSH 模式列表（DSH_PRESET=smart 可切换，与官方 4 模式并列）
└── smart（第 5 个模式）
    ├── 【外壳】官方 preset 格式（DSH 原生挂载，零源码改动）
    │   ├── 位置：DSH_HOME/.agent-presets/smart/
    │   ├── agent.cordis.yml：挂载 aaa-engine MCP server + 裁剪后的常用执行工具
    │   ├── preset.yml：名称/描述/order: 5
    │   └── 提示词三段式（见 b）
    └── 【内层】自研 MCP server（nodes/shared/mcp_servers/aaa_engine/，Python）
        ├── AAA 认知工具（复用 AAA 现有模块，包 MCP 外壳）：
        │   memory_retrieve（记忆检索）/ context_build（上下文构建）
        │   parse_respond（解析输出节）/ cognition_commit（认知沉淀）
        ├── 按需分配工具：tool_route（任务特征 → 建议工具；v1 仅记录，v2 学习）
        └── 数据：读写 AAA 记忆库（存库分离，原子写协议）
```

**运行效果**：agent 开口即 AAA（人格骨架）、带 AAA 记忆干活（memory_retrieve / context_build）、按需使用执行工具（裁剪集 + 纪律）、任务结果经 parse_respond / cognition_commit 沉淀回库。外部 AAA 节点保留首尾承接作为**兜底**（LLM 可能不调 AAA 工具，确定性链路不可依赖工具调用）。

**a. `agent.cordis.yml`（外壳，copy `standard` 后裁剪）**：

移除工具（高风险/高成本，共 8 个）：

| 工具 | 类别 | 移除理由 |
|---|---|---|
| `subagent` `subagent_fork` `send_message` `interrupt_agent` `list_agents` `report` | 子代理 | 扇出子 agent 成本高、不可控，与"减少调用"目标相悖 |
| `workflow` `ralph` | 编排 | 模型编排脚本成本高、不可观察 |

保留工具（共 19 个）：`pwsh` `read` `write` `edit` `read_image` `grep` `glob` `str_replace_editor` `job_list` `job_output` `job_kill` `skill` `get_goal` `create_goal` `update_goal` `todo_write` `web_search` `ask_user_question` `exit_plan_mode`，**外加 aaa-engine MCP server 暴露的 AAA 认知工具与 tool_route**。

**b. 提示词三段式**（smart 的系统提示词由三部分拼接，**人格骨架与 AAA prompt.py 同源，单一事实源**）：

```
【AAA 人格骨架】（静态，与 AAA prompt.py 人格节同源，升级时同步）
- 身份：你是谁、性格、自我认知、说话方式
- 认知框架：如何看待世界/用户/自己

【记忆注入位】（动态，由外部 AAA 或 context_build 工具填充）
- 本任务相关记忆摘要 / 当前认知 / 情绪 / 上下文

【工具使用纪律】
- 按需调用：仅当任务需要外部信息或实际执行时才调用工具；基于已有上下文/记忆可直接回答的，直接输出，不调用工具。
- 最少够用：优先用最直接的单一工具完成，能用一步完成的不拆多步。
- 工具是手段不是流程：不使用工具做"编排"（本预设已移除子代理/编排类工具）。
- AAA 工具优先：需要记忆/认知时先调 aaa-engine 工具（memory_retrieve / context_build），不要绕过 AAA 直接输出。
- 严格按 AAA 输出格式返回（含节标记），工具结果只是中间产物。
```

**c. `preset.yml`**：名称"smart / AAA 助理"、描述、`order: 5`。

**按需分配的现实边界**：DSH 一次任务的工具集是**会话级固定**（preset 挂载），无法在任务中途动态更换工具集。因此"按需分配"在 v1 落地为三层：**静态裁剪**（预设级，去高风险工具）+ **纪律自律**（提示词约束 LLM 少调）+ **日志记录**（数据积累）；v2 学习系统负责"任务 → 选哪个模式 / 是否用工具"的**确定性路由**（AAA 侧），不改变 DSH 机制。

### 4.2 观察与记录（v1）

- **即时观察**：GUI 活动气泡已实时显示工具调用（`tool/call` 事件），切到新预设后直接可见工具调用是否收敛、是否减少。
- **工具日志（必需——工具图谱的数据源）**：node_dsh 任务完成返回中携带工具调用摘要 → 追加一行 `nodes/shared/dsh_tool_usage_log.jsonl`（原子追加）：
  `{ts, task_id, preset, tools[], success, duration_ms}`
  v1 仅记录不决策，作为 v2 是否上学习系统的数据依据。**同时作为"工具图谱"的数据源（见下），故为必需项而非可选。**
- **工具图谱（复用记忆图谱组件）**：在 GUI 知识图谱区域增加"工具图谱"视图，复用 `KnowledgeGraph` 力导向组件（节点尺寸 ∝ 调用次数、边粗细 ∝ 联动频次、高频联动工具自动聚合）：
  - 节点 = 工具（content 含工具名+类别，按类别着色）
  - 节点尺寸 = 调用次数（log 缩放，防糊屏）
  - 边 = 同任务共现对（v1 定义"联动"= 同一任务内一起调用；v2 可选升级为"调用顺序相邻"）
  - 力矩阵 = 联动频次归一化（高频联动工具聚在一起）
  - 数据流：日志 → 聚合器（统计调用次数 + 共现对）→ `KnowledgeGraph.load_data(entries, edges, sim_matrix)` → 任务完成后自动刷新
  - 价值：AI 工具使用习惯白盒化；standard vs smart 图谱对比可直接验证"自律分配"是否生效

**工具扩展路径（MCP，未来加工具的唯一标准通道）**：
- DSH 工具来源：MCP server（`tools/list` + `tools/call`，mcp-client 自动 `ctx.tools.register()`）→ 官方工具包（改 harness，不推荐）→ `tool-cordis`（运行时实验）。
- 添加流程：写 MCP server（声明 name/description/inputSchema）→ 配置连接 → 自动注册 → preset 决定是否可见（standard 默认全见，smart 裁剪可选收录）→ tool-catalog 重新生成。
- **设计红利**：日志/图谱数据驱动（读会话记录），新工具加进来自动收录，**不改任何代码**。
- BNOS 规范（建议）：MCP server 统一放 `nodes/shared/mcp_servers/`；工具命名/描述按注册表规范；tool-catalog 重新生成后人工核对。

### 4.3 v2 学习系统（验证后启用，设计保留）

> 触发条件：观察/日志数据显示"任务→工具"映射需要学习才能得到（工具使用分散/预设级自律不足/任务类型差异大）。**未验证前不实现。**

- **模式库匹配**（AAA 侧确定性路由）：标准化任务特征（类型标签 + 关键实体）embedding → 与模式库余弦相似度 → ≥阈值（0.80，实测校准）取 top-1 复用；<阈值 pass 走静态映射/工具池匹配。冷启动放宽阈值。
- **固化 + 交集收敛**：每次执行更新 `tool_usage_freq`，高频工具（≥ 执行次数×0.8）强化保留、低频（< ×0.3）衰减剔除，`tools` 收敛为"最少够用集"（够用最少，非字面最少）。
- **奖惩**：命中成功 strength+；失败 strength-；久不使用衰减；长期失败淘汰。相似模式合并（embedding ≥0.95 并入不新增）。
- 模式库 `nodes/shared/tool_mode_store.json`（独立存储，符合"存库分离"约束）。
- **工具池膨胀演进**（远期，非本次）：工具 >100 时匹配方式升级为分类两阶段（类名一级 + 类内二级，附录 A 已有类别列）；>500 时向量召回 top-k + LLM 精排（匹配成本与总数解耦，复用 MemOS 设施）。

### 4.4 Token 账（为什么值得做）

设全池 schema ≈ 8000 token/轮，裁剪后池 ≈ 5000 token/轮（19 个）：

```
standard：意图门 + 执行 n 轮 × 8000          = 8000n
smart：   意图门 + 执行 n 轮 × 5000          = 5000n   （工具池更小 + 提示词纪律减少工具调用轮次）
v2：      意图门 + 执行 n 轮 × 精简池        = 更低    （命中模式才带精简池，0 匹配成本）
```

- smart 的收益不只是 schema 变小，更是**纪律提示词减少无谓工具调用**（本会调子代理/绕路的环节直接输出）。
- v1 无需为"选择"付任何 LLM 成本（预设是静态的，切换靠 GUI）。

## 5. 落地改动清单

### v1（本次实施，零重构）

| 模块 | 改动 |
|---|---|
| `DSH_HOME/.agent-presets/smart/agent.cordis.yml`（新） | 外壳：copy `standard`，裁剪子代理/编排类 8 工具，挂载 aaa-engine MCP server，追加三段式提示词 |
| `DSH_HOME/.agent-presets/smart/preset.yml`（新） | 名称/描述/order |
| `nodes/shared/mcp_servers/aaa_engine/`（新） | 内层：自研 MCP server（Python），暴露 AAA 认知工具（memory_retrieve / context_build / parse_respond / cognition_commit）+ tool_route（v1 仅记录）；复用 AAA 现有模块 |
| `nodes/shared/dsh_tool_usage_log.jsonl`（新） | 工具使用日志（逐行追加，只记录不学习；node_dsh 返回工具摘要） |
| GUI `tool_usage_panel.py`（新） | 工具图谱视图：复用 `KnowledgeGraph`，节点=工具/尺寸=调用次数、边=联动/粗细=频次，任务完成后刷新 |
| GUI `knowledge_panel.py`（改） | 增加"工具图谱"标签页入口 |
| node_dsh | 任务完成返回携带工具调用摘要（`tool/call` 事件汇总，只读不改内核） |
| GUI「DSH 管理-预设管理」 | 切换/查看第 5 个模式（现有功能，无需改） |

**明确不改**：AAA `main.py` / `dsh_client.py` 主流程 / harness 源码 / DSH 内核（node_dsh 仅加"读取会话记录汇总工具摘要返回"的轻量代码，不动执行逻辑）。

### v2（验证后决定，未验证不实现）

| 模块 | 改动 |
|---|---|
| AAA 侧 `tool_route.py`（新） | 静态映射表（关键词 → 预设）或模式库匹配（embedding + 阈值 + top-1）+ 固化 + 奖惩/衰减/合并 |
| `nodes/shared/tool_mode_store.json`（新） | 模式库存储（见 4.3） |
| AAA 任务特征 embedding | 复用 MemOS 向量化能力 |
| GUI（可选） | 模式库查看/管理页 |

## 6. 验收方式

### v1

1. **预设可切换**：GUI 切换到 `smart`，`DSH_PRESET=smart` 生效，任务正常执行。
2. **工具集已裁剪**：smart 任务中无子代理/编排类工具被调用（观察活动气泡/日志）。
3. **纪律生效**：纯文本可答的任务不调用工具（对比 standard 会调工具的环节）。
4. **回 AAA 不破坏**：工具任务结果仍按 AAA 输出格式解析存档推送，记忆不断链（回归）。
5. **日志落盘**：任务完成后 `dsh_tool_usage_log.jsonl` 追加一行，含实际工具列表。
6. **工具图谱**：GUI 工具图谱页显示节点（工具）/尺寸（调用次数）/边（联动），任务完成后自动刷新；standard 与 smart 可对比。
7. **可逆**：切回 `standard` 行为与现状一致，无残留改动。
8. `run.bat` 启动检测无报错。

### v2（仅验证通过后）

7. **模式库复用**：同类任务第二次命中模式（相似度 ≥ 阈值），携带精简工具集。
8. **交集收敛**：同一模式执行 5 次，`tools` 收敛到核心集、低频工具剔除。
9. **奖惩/淘汰/相似合并**：按 4.3 规则生效。

## 7. 待决策项

- [ ] 第 5 个模式命名：`smart` / `frugal` / `focused` / `selective`（或其他）
- [ ] aaa-engine 认知工具集范围：先做全部 4 个（memory_retrieve / context_build / parse_respond / cognition_commit）还是先做 context_build 一个（v1 最小集）
- [ ] 人格骨架单一事实源：smart 提示词与 AAA `prompt.py` 人格节**同源生成**（脚本抽取）还是手动同步维护
- [ ] 工具裁剪范围：是否也裁掉 `skill`/`goal_*`/`todo_write`（保留更保守 vs 更精简）
- [ ] 工具图谱"联动"定义：同任务共现（v1 默认）vs 调用顺序相邻（v2 可选）
- [ ] 工具图谱时间维度：累积全历史（v1 默认）vs 可切时间窗
- [ ] 工具扩展路径（MCP 通道确认）：BNOS 专属工具是否全部走 `nodes/shared/mcp_servers/` 统一托管；新工具默认进 standard，是否进 smart 由裁剪决策
- [ ] 观察周期与指标：跑多少天 / 看什么数据分布，决定是否启用 v2
- [ ] v2（若启用）：静态映射 vs 模式库学习、阈值 0.80 校准、两档（0.90/0.80）、冷启动放宽等参数

---

## 8. 关联与边界

- 本方案**不引入多 agent 编排**（workflow/subagent 管道不在范围内）；若未来任务需要多 agent，另行设计。
- 与 `[PLAN]-workflow接入DSH执行器方案` 不冲突：workflow_store 管"外部确定性步骤流程"，本方案管"单任务内工具自律"，可叠加。
- 与 AAA 记忆体系同构：模式库 = "工作流层记忆"（v2），机制（强化/衰减/冷板凳）复用消息池与记忆系统的既有经验。
- **与官方 DSH 更新的关系（零冲突）**：smart 模式两层均走官方扩展机制——外壳是官方 preset 格式（`DSH_HOME/.agent-presets/`），内层是官方 MCP 通道（mcp-client 自动 `ctx.tools.register()`）。官方更新只影响"外壳格式跟随升级"，自研引擎（aaa-engine Python MCP server）与 node_dsh 包装层不受源码级冲突影响；对比"改 headless 源码"路线（如 DSH_* 环境变量注入处 +219 行），本方案刻意避开源码改动面。
- **架构演进兼容（AAA 嵌入 DSH、存库分离）**：DSH web 承载 BNOS AI 后，AAA 将**直接嵌入 DSH**（大脑逻辑跑在 DSH 内部），仅存库（记忆/认知/对话/模式库/日志）单独分离于独立存储层。本方案天然兼容：
  - 意图门 / 回 AAA 解析 = "AAA 逻辑"，不依赖 AAA 运行形态——独立节点或嵌入 DSH 内部，逻辑不变。
  - smart 模式即 DSH 原生 preset + MCP 引擎，嵌入后直接可用。
  - 日志/模式库独立存储，符合"存库分离"约束；存储接口按 BNOS 共享协议（原子写）实现，与运行形态解耦。

---

## 附录 A：DSH 工具池完整清单（standard 场景，Windows）

| # | 工具名 | 类别 | 来源包 | 一句话用途 | 备注 |
|---|---|---|---|---|---|
| 1 | `pwsh` | Shell | tool-pwsh | 执行 PowerShell 命令（Win） | Win 启用；Linux 为 `bash` |
| 2 | `read` | 文件 | tool-fs | 读文件（支持行区间/图片） | |
| 3 | `write` | 文件 | tool-fs | 写文件（原子替换） | |
| 4 | `edit` | 文件 | tool-fs | 精确字符串替换编辑 | |
| 5 | `read_image` | 文件 | tool-fs | 读取图片内容（多模态） | |
| 6 | `grep` | 检索 | tool-fs-search | 内容正则搜索 | |
| 7 | `glob` | 检索 | tool-fs-search | 文件名模式匹配 | |
| 8 | `str_replace_editor` | 编辑器 | tool-str-replace-editor | 大文件受控编辑 | |
| 9 | `job_list` | 后台任务 | tool-jobs | 列出后台任务 | |
| 10 | `job_output` | 后台任务 | tool-jobs | 取后台任务输出 | |
| 11 | `job_kill` | 后台任务 | tool-jobs | 终止后台任务 | |
| 12 | `skill` | Skill | tool-skill | 技能列表/加载/卸载 | |
| 13 | `get_goal` | 目标 | tool-goal | 读当前目标 | |
| 14 | `create_goal` | 目标 | tool-goal | 创建目标 | |
| 15 | `update_goal` | 目标 | tool-goal | 更新目标 | |
| 16 | `todo_write` | 待办 | tool-todo | 写待办清单 | |
| 17 | `web_search` | 联网 | tool-web | 网页搜索 | `web_fetch` 已禁用 |
| 18 | `subagent` | 子代理 | tool-subagent | 派生子 agent | smart 移除 |
| 19 | `subagent_fork` | 子代理 | tool-subagent-fork | 复制会话派生子 agent | smart 移除 |
| 20 | `send_message` | 子代理 | tool-subagent-control | 给子 agent 发消息 | smart 移除 |
| 21 | `interrupt_agent` | 子代理 | tool-subagent-control | 中断子 agent | smart 移除 |
| 22 | `list_agents` | 子代理 | tool-subagent-control/list-agents | 枚举子 agent | smart 移除 |
| 23 | `report` | 子代理 | tool-subagent-report | 子 agent 主动汇报 | 仅 continuable 子 agent 内；smart 移除 |
| 24 | `workflow` | 编排 | tool-workflow | 运行模型写的编排脚本 | smart 移除 |
| 25 | `ralph` | 编排 | tool-ralph | Ralph 编排 agent | smart 移除 |
| 26 | `ask_user_question` | 交互 | tool-ask-user | 向用户提问 | |
| 27 | `exit_plan_mode` | 计划 | plan-mode | 退出计划模式 | 会话模式工具 |

**未挂载（官方有，当前组合不启用）**：`tool-bash-persistent`（仅 minimal）、`tool-cordis` 7 个（仅 cordis）、`tool-lsp`（base 未挂）、`tool-session-query` 5 个（base 只挂服务）、`tool-terminal` 6 个（base 未挂）、`web_fetch`（已禁用）。

**smart 预设保留 19 个**（#1~17 常用执行 + #26~27 交互/计划）；移除 8 个（#18~25 子代理/编排类）。
