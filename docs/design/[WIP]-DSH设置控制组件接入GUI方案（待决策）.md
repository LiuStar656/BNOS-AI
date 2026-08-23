# DSH 设置/修改/控制组件搬到 BNOS GUI 方案（待决策）

> 需求澄清（用户 2026-08-14）：**不是内嵌 DSH web 面板**，而是把 DSH 中需要
> **设置、修改、控制**的组件做成 BNOS GUI 里的原生表单/列表/按钮，
> 不进入 DSH（CLI / web）就能操作。
> 已撤销：web 前端构建面板页（dsh_panel_page.py 已删，注册已移除）。

---

## 1. DSH 可控面调研结论

| DSH 组件 | 现有机制 / 数据 | 搬到 GUI 的落地方式 | 状态 |
|---|---|---|---|
| 模型配置 | `dsh_home/profiles/{headless,web}/cordis.patch.yml`（provider bnos-deepseek、默认模型） | 「DSH 配置」页表单（baseURL/默认模型/模型列表，双 profile 同步写回） | ✅ 已实现 |
| 会话管理 | `dsh_home/sessions/<workspace-hash>/<session-id>/session.jsonl.zstd`（已有约 20 个会话）；继续会话用 `agents.resume`（`DSH_SESSION_ID`，已实现） | 会话列表：展示 id / 最后活动时间 / 大小；操作：继续（resume 回聊天）、删除、清理归档 | 待做 |
| 任务控制 | `dsh_task_in.json`（提交）/ `output.json`（最近结果）；运行中任务 = node_dsh 的 DSH 子进程 | 任务控制：提交任务（task + session_id + 超时）、取消运行中任务（kill 子进程）、查看最近结果/最终回答 | 待做 |
| 运行时参数 | `cordis.patch.yml` 可扩展键：llm 温度、maxTokens、系统提示、cwd、agent 参数 | 常用参数表单（patch 写回，YAML 校验） | 待做 |
| Goal / Plan 管理 | goal/plan store（dsh_home 下 `.jsonl` 文件） | Goal/Plan 列表：增删改 | 待做（存储格式实施时定位） |
| 插件 / 工具开关 | `dsh plugin --profile add/remove`（转发 pnpm）；patch 的 `tool-*` 行启用/禁用 | 插件页：增删插件；工具开关表单 | 待做 |

## 2. 落地方式（全部原生 GUI，无 web 内嵌）

- 复用插槽注册（`ui_registry`）+ 现有「DSH 配置」页
- 数据读写沿用既有链路：文件协议（dsh_task_in.json / output.json / patch 文件 / sessions 目录）+ node_dsh 进程控制
- 所有操作同步返回结果；取消类操作 = 终止 node_dsh 当前 DSH 子进程
- 与「DSH 配置」页合并为一个「DSH 管理」大页（分区卡片）或独立成页，取决于范围

## 3. 待决策项

- [x] 首批落地组件：**全选**（会话管理、任务控制、运行时参数、Goal/Plan 管理、插件/工具开关）
- [x] 组织方式：**合并大页**（「DSH 管理」页，QTabWidget 分区）

---

## 4. 实施记录（2026-08-14 已实施）

### 4.1 落地形态

「DSH 管理」页（`gui/pages/dsh_manage_page.py`，`page.dsh_manage`，侧边栏「DSH 管理」），
替换原「DSH 配置」页（已删除）。**9 个分区**（QTabWidget）：

| 分区 | 内容 | 实现 |
|---|---|---|
| 模型配置 | provider baseURL / 默认模型 / 模型列表 / 最大 Token（provider `defaultMaxTokens`） | headless + web 双 patch 同步写回（YAML 原子替换）；API Key 复用 llm_infer 节点配置，不落盘 |
| 会话 | dsh_home/sessions 会话列表（id/时间/大小） | 继续（填入任务页会话框）、复制 id、导出（zip 打包会话目录）、删除（确认）、清理全部（确认） |
| 任务 | 提交任务（同步等待最终回答）、取消任务、最近结果 | 复用 dsh_task_in.json / output.json 链路（task_id 精确匹配）；取消 = taskkill `--profile headless` 的 node 进程 |
| 工具开关 | base/headless bundle + profile patch 合并视图的 `tool-*` 清单（18 个） | 每行「启用/禁用」写 extra.patch.yml 的 `disabled` 覆盖行；`!!js` 平台表达式归一（tool-bash Windows 禁用 / tool-pwsh 启用） |
| 插件 | `dsh plugin --profile headless add/remove <pkg>` 封装 | 子线程执行防冻结，输出回显；另附已装插件组合清单（82 行合并视图，只读） |
| 工作区 | `nodes/shared/dsh_workspace` 文件浏览 | QTreeWidget 树形浏览 + 文本预览（200KB / 二进制限制）；新建文件/目录、重命名、删除（路径安全校验防穿越） |
| 运行参数 | 附加 patch（extra.patch.yml）编辑 | YAML 校验 + 原子写回；模板快捷插入；由 node_dsh 以 `--patch` 加载（main.py 已改） |
| 通用/安全 | 沙箱权限模式 + 会话遥测 + 默认温度 | sandbox-policy.mode（read-only/workspace-write/danger-full-access）+ session-telemetry-otel.mode（DISABLED/FEEDBACK_ONLY/FULL，非 DISABLED 带完整 exporter/processor config）+ runtime.json 温度（经 DSH_TEMPERATURE 注入 headless） |
| Agent 预设 | 默认预设选择 + 自定义 Agent（复制创建/编辑/删除）+ **人格（dsh-persona 行）** | 预设清单（内置只读 + 自定义，卡片含人格摘要）；默认预设存 runtime.json `preset` → node_dsh 注入 DSH_PRESET → headless roster 挂载；复制创建写 `dsh_home/.agent-presets/<id>/`；编辑 agent.cordis.yml/preset.yml（组合校验）+ 人格编辑区（upsert `id: persona` 行，空文本=移除，继承部署默认）；删除仅限自定义、同步清空已删默认 |

### 4.2 本轮修复（用户反馈 2026-08-14）

1. **启动闪屏缺 node_dsh**：`gui/pages/startup_splash.py` 的 `NODE_LABELS` 增加
   `"node_dsh": "DSH 执行"`（与侧边栏「DSH 管理」呼应）。引擎 `engine.py::main()` 启动前
   `_kill_orphan_node_processes()` 清理残留，node_dsh 正常拉起后 `bnos_status.json` 标记 running，
   闪屏显示「DSH 执行 已就绪」。
2. **DSH 可控未涵盖全部控件**：由 6 分区扩充为 10 分区（见 4.1 表），覆盖人格注入、工具开关、
   工作区管理、会话导出、插件组合清单、沙箱权限、遥测、默认温度；并对不可控边界诚实说明
   （steering/goal/plan 为会话运行时状态、retry/transport 等运维参数不暴露），不做假控件。
3. **温度注入链路**（默认温度控件）：DSH 无持久温度配置（请求级参数）→ BNOS fork 在 headless
   bundle 的 `agent/request` waterfall 合并 `DSH_TEMPERATURE` env；node_dsh/main.py 每次任务读
   `dsh_home/runtime.json` 注入 env。已由会话日志 `request/header` 实测确认 `temperature: 0.3`
   进入请求配置。
4. **Agent 预设 / 自定义 Agent（第 10 分区，用户 2026-08-14 追加需求）**：
   - DSH 原生机制：预设 = `agent.cordis.yml`（必填，插件行列表）+ `preset.yml`（可选元数据）；
     shipped 根 `harness/apps/cli/config/agent-presets/`（system trust，只读），user 根
     `$DSH_HOME/.agent-presets/`（user trust，`copy()` 是唯一创建路径）。
   - **headless 启用 roster**：bundle headless `cordis.patch.yml` 增加 `agent-presets` 行
     （`default: standard`）——profile-boot 仅在组合树含该行时注入 shipped 根；
     headless runner `setup()` 钩子内 `agentPresets.mount()`（agent 发布前，失败整体回滚）。
   - **默认预设选择**：GUI 写 `runtime.json` `preset` 字段 → main.py 注入 `DSH_PRESET` env →
     headless 解析并 `mount`。创建会话前解析 id 写入 session header `agentPreset`
     （创建事实，冷读/续接按 header 重建组合）；续接会话按 header 记录的预设组合，
     默认预设变化不改变旧会话的组合。
   - **GUI 第 10 分区**：预设清单（名称/描述/内置或自定义/损坏标记）；「设为默认」+「跟随内置默认」；
     复制创建自定义 Agent（源预设 + 新 id + 显示名，目录整体复制 + preset.yml 重写为 name+源描述）；
     文件编辑器（agent.cordis.yml / preset.yml，agent.cordis.yml 保存前做插件行列表校验，
     支持 `!!js` 标签）；删除仅限自定义（内置只读），删除默认预设时同步清空默认。
   - 边界诚实说明：内置预设只读不可编辑（属安装代码，改动会被更新覆盖）；预设 id 须匹配
     `^[a-z0-9][a-z0-9-]*$`（目录名约束）；会话中途不可换预设（headless 无 blank 窗口）。
5. **人格归属修正（「目标/人格」Tab 删除）**：原独立 Tab 写全局 `system-prompt.persona`，
   与 DSH 官方语义（人格属于预设——`dsh-persona` 行，scope-only）及 AAA 负责人格重叠。
   已删除该 Tab，人格编辑并入「Agent 预设」分区编辑对话框；`_migrate_drop_global_persona()`
   在首次打开本页时幂等清理 extra.patch.yml 残留的 `system-prompt` 行（避免静默覆盖所有任务人格）。
   人格读写走 agent.cordis.yml 的 `id: persona` 行（`read_preset_persona` / `write_preset_persona`），
   空文本=移除该行（该 Agent 继承部署默认人格）；`!!js` 平台表达式经 `_JsExpr` roundtrip 原样保留。
6. **按钮字体自适应**：全局 QSS 按钮 `padding: 8px 16px` 固定 + 各页 `setFixedWidth(56/64/72…)`
   固定宽度 → 字体放大后文字溢出按钮。新增 `gui/core/utils/widget_utils.py::fit_button_width()`
   （fontMetrics 计算文本宽 + padding，只设 minimumWidth 保留 sizeHint 自适应），
   替换 6 个页面全部固定宽度文本按钮（会话/任务/工具开关/插件/工作区/预设/通用、活动页、
   流程页、工具页、节点页、提案页）。约定：文本按钮一律不用 setFixedWidth。
7. **AI 协作创建预设**：DSH 官方允许 user 预设 "authored by a person **or by an agent**"。
   工具桥新增 7 个 `dsh.preset_*` 工具（list/copy/read/write/persona/remove/set_default），
   AAA 侧 `gui_tools.py` 已接入（prompt 注入清单 + 【工具调用】解析），可直接与 AI 对话
   「帮我创建/修改一个 Agent 预设」。破坏性操作（复制创建/写入/删除/改默认）经工具直执行，
   结果即时生效。
8. **换肤 AI 闭环（t4）**：`gui_tools.py::tool_list_text()` 调用时机说明由「仅 UI/主题相关」
   放宽为「UI/主题/皮肤、DSH 任务、Agent 预设管理、页面导航均可调用」，使 preset 工具被 AI 主动使用。

### 4.3 改动文件

| 文件 | 改动 |
|---|---|
| `gui/pages/dsh_manage_page.py` | 大页（9 分区；共享 extra.patch 读写、工具/组合行扫描、平台表达式归一、沙箱/遥测/runtime.json 读写、Agent 预设清单/复制创建/编辑/删除/人格读写（dsh-persona 行）+ 全局人格迁移清理；耗时操作全在子线程 + Qt Signal 回主线程） |
| `gui/core/utils/widget_utils.py` | 新增 `fit_button_width()`：按钮最小宽度按文本 + padding 自适应（fontMetrics），约定替代 setFixedWidth |
| `gui/pages/activity_page.py` / `workflow_page.py` / `tools_page.py` / `node_page.py` / `proposals_page.py` | 固定宽度文本按钮（64/72/90 等）替换为 `fit_button_width()` |
| `gui/core/tool_registry.py` | 新增 7 个 `dsh.preset_*` 工具（list/copy/read/write/persona/remove/set_default），延迟导入 pages 层避免循环依赖 |
| `nodes/node_python_aaa_cognition/gui_tools.py` | `tool_list_text()` 调用时机说明放宽（UI/主题、DSH 任务、Agent 预设、页面导航均可调用） |
| `gui/pages/startup_splash.py` | `NODE_LABELS` 增加 `node_dsh`（「DSH 执行」） |
| `nodes/node_dsh/harness/packages/bundle/headless/cordis.patch.yml` | 组合树新增 `id: agent-presets` 行（`default: standard`），启用预设 roster（profile-boot 据此注入 shipped 根 + 自动追加 `$DSH_HOME/.agent-presets`） |
| `nodes/node_dsh/harness/packages/bundle/headless/src/index.ts` | BNOS fork：`setup` 改为 async；按 `DSH_PRESET` env / 会话 header 记录的预设 `agentPresets.mount()`（resolve 失败回退部署默认，不中断任务）；`agent/request` waterfall 合并 `DSH_TEMPERATURE` |
| `nodes/node_dsh/main.py` | 读 `dsh_home/runtime.json` 注入 `DSH_TEMPERATURE` / `DSH_PRESET` env；`_run_dsh` 支持 `--patch extra.patch.yml`（`_patch_has_entries()` 跳过仅注释/空白的 patch 文件，避免 DSH `loadOverlayPatches` 拒绝非数组顶层） |
| `gui/core/ui_registry.py` | `page.dsh_config` → `page.dsh_manage`（标题「DSH 管理」） |
| `gui/pages/dsh_config_page.py` | 删除（并入大页） |

### 4.4 验证结果

| 项 | 结果 |
|---|---|
| 导入/诊断 | ✅ 无语法错误；`page.dsh_manage` 注册成功 |
| 10 分区实例化 | ✅ 全部 Tab（含 Agent 预设）+ `DshManagePage` 实例化通过（offscreen 验证脚本） |
| 工具行 | ✅ 18 个（tool-bash Windows 禁用、tool-pwsh 启用、tool-jobs 启用，`enabled` 归一正确） |
| 插件组合行 | ✅ 82 个（启用 78 / 已禁用 4） |
| 人格 roundtrip | ✅ 写入/读取 extra.patch 一致，验证后还原 |
| 沙箱/遥测/温度 roundtrip | ✅ 读写一致；extra.patch 其他行（persona 等）共存保留 |
| dump-config 合成 | ✅ `sandbox-policy.mode=read-only`、`session-telemetry-otel.mode=DISABLED`、`system-prompt.persona` 均被 extra.patch 覆盖生效 |
| 真实任务端到端 | ✅ headless 任务完成；会话日志 `request/header` 实测 `temperature: 0.3` 注入、persona 进入 system、`sandbox/mode`+`approval/policy` 事件存在 |
| 引擎真实启动 | ✅ `python -m bnos_runtime.engine pipeline.json`：4 节点全 running（含 node_dsh），`engine_status=online`；停止后 process_killer 确认 4 节点全部清理 |
| 预设 roster | ✅ 4 个 shipped 预设（standard/minimal/code/cordis）；headless 组合树含 `agent-presets` 行，shipped 根注入 |
| 预设端到端 | ✅ runtime.json 写 `preset` → 新任务 header 记录 `agentPreset`（standard/minimal/my-test-agent 三种均正确，zstd 多帧解码确认）；续接会话按 header 重建组合 |
| 预设数据层 | ✅ 复制创建（目录复制 + preset.yml 重写）、保存默认、删除自定义并同步清空默认、组合结构校验全部通过；测试残留已清理 |
| 人格 roundtrip（本轮） | ✅ 复制 standard → 读人格（默认英文文本）→ 写入中文人格 → 组合首行 `id: persona` → 清空移除 → 恢复；`!!js` 表达式写入/读回原样保留 |
| AI preset 工具（本轮） | ✅ `dsh.preset_list` / `preset_persona` 写+读 / `preset_read` / `preset_set_default`（含恢复内置）/ `preset_remove` 全部 ok，数据一致 |
| 9 分区实例化（本轮） | ✅ DshManagePage offscreen 实例化：9 个 Tab，无「目标/人格」；PresetsTab 含人格编辑区；迁移函数幂等 |
| 按钮自适应（本轮） | ✅ 8 个文件 AST 语法通过；`fit_button_width` 导入无循环依赖（widget_utils 仅依赖 QtWidgets） |

### 4.5 使用方式

- 侧边栏「DSH 管理」→ 分区操作；不进入 DSH（CLI/web）即可完成设置/修改/控制
- 会话管理点「继续」自动把会话 id 填入任务页，实现多轮续接；「导出」打包会话目录为 zip
- 工具开关 / 沙箱 / 遥测共用 extra.patch.yml，保存后下一次 headless 任务自动生效（main.py `--patch` 加载）
- 默认温度写 dsh_home/runtime.json，node_dsh 经 DSH_TEMPERATURE 注入（headless fork 的 agent/request 合并）
- 「Agent 预设」分区：下拉选默认预设（存 runtime.json `preset` → DSH_PRESET），「复制创建」从任意内置/自定义预设派生新 Agent（自定义写 `dsh_home/.agent-presets/<id>/`），「编辑」改 agent.cordis.yml / preset.yml + 人格（内置只读；人格留空 = 该 Agent 继承部署默认人格），「删除」仅限自定义
- 人格：与 AAA 负责人格互不重叠——DSH 的人格属于预设（dsh-persona 行），AAA 侧人格属于认知系统自身设定；原全局人格注入入口已移除
- AI 协作创建预设：直接对 AI 说「创建一个名为 xx 的 Agent，人格是…，禁用 bash 工具」即可（AAA → dsh.preset_* 工具链自动完成，结果即时生效，下一次任务可用）
- 工作区新建文件后可在任务描述中引用（任务可读写的唯一目录）
- 插件增删走 pnpm（真实环境有效；TRAE 沙箱内命令执行受限属已知限制）

### 4.6 说明

- DSH 的 Goal/Plan 无独立全局 store（session 运行时状态），故不设「目标/Plan」分区；
  目标通过任务描述 + 会话续接表达；人格归预设（见 4.2-5）
- 温度原为请求级参数、无 profile 持久配置入口；已通过 BNOS fork（headless bundle 读
  `DSH_TEMPERATURE` 在 agent/request 合并）补上持久注入，GUI 侧为全局默认值
- 「全部权限」沙箱会把审批策略联动为「从不询问」（base bundle approval 行的表达式语义），
  GUI 已加警示文案；DANGER 模式下 Agent 可执行任意命令，仅限可信环境
- 遥测 FULL/FEEDBACK_ONLY 会把数据上传到 DeepSeek 遥测端点（base 默认 OTLP URL），
  GUI 已加警示；默认保持 DISABLED（仅本地）
- web profile / web 前端构建产物（前置工作中产出）保留备用，GUI 不再内嵌 web 面板
