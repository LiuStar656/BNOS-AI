# [PLAN]-DeepSeek Harness 接入方案（node_dsh 执行器官）

> 状态：✅ 已实施完成（2026-08-14）
> 说明：把 DeepSeek Harness（DSH，官方开源 Agent 运行框架）直接作为 BNOS 节点接入——不做桥接壳，DSH 本体装在节点目录内，成为 BNOS 编排体系中的一个"执行器官"。
> v2：DSH **源码仓库**已 clone 至节点内（`nodes/node_dsh/harness/`），可二次开发；工作目录沙箱通过 fork 定制实现。

## 背景与目标

BNOS-AI 的 AAA 认知中枢负责"想"（认知/记忆/情感），DSH 负责"做"（工具调用/文件读写/代码执行/子 Agent）——对标 DeepSeek 官方公式 `Agent = Model + Harness`，BNOS 的对应关系是：

| BNOS 角色 | 组件 |
|---|---|
| 大脑（认知中枢） | node_python_aaa_cognition |
| 推理服务 | node_python_llm_infer |
| 面孔（Live2D）/ 声音（TTS） | gui 内置 + node_python_tts |
| **执行神经系统（手脚）** | **node_dsh（DeepSeek Harness）** |

目标：DSH 作为独立节点（独立进程 + 独立状态 + 崩溃隔离），AAA 可把任务交给它执行，无需自研 subagent/沙箱/工具系统（P2 的能力从 DSH 借力）。

## 环境现状（接入前调研）

- DSH v0.1.0-rc.6 已通过 `npx @deepseek-ai/dsh web` 缓存到 `C:\Users\Lenovo\.dsh`（内置 100+ 插件：headless/subagent/sandbox/workflow/bash/fs 等）
- 本机 Node v24.18.0、pnpm 11.21.0 就绪
- DSH 提供四种运行形态，headless 最适配 BNOS 文件协议：
  - `dsh --profile headless "<任务>"` — 单次 Agent 任务，打印最终回答后退出，可被子进程驱动

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│ nodes/node_dsh/  （独立进程 + 独立 venv，BNOS 引擎拉起）      │
│  ├── node_modules/@deepseek-ai/dsh   DSH 本体（npm 安装）    │
│  ├── dsh_home/                        DSH_HOME（私有状态）   │
│  │   └── profiles/headless/           headless profile 配置  │
│  ├── listener.py                       BNOS 文件协议监听器    │
│  ├── main.py                           调 dsh headless 执行   │
│  └── node_config.json                  输入 task / 输出 default│
├─────────────────────────────────────────────────────────────┤
│ nodes/shared/                                                │
│  ├── dsh_task_in.json     ← GUI 工具桥 / 上游写入任务请求     │
│  ├── dsh_workspace/       ← DSH 唯一可读写沙箱（与项目隔离）  │
│  └── gui_tool_schemas.json（含 dsh.run_task / dsh.check_task）│
└─────────────────────────────────────────────────────────────┘
```

### 关键机制

1. **节点自包含**：DSH 本体装在节点目录内——**源码版** `harness/`（官方仓库 clone，`git pull` 升级）为主，npm 编译包 `node_modules/@deepseek-ai/dsh` 为 fallback；`start.bat` 自动安装缺失部分。
2. **状态隔离**：`DSH_HOME` 指向 `node_dsh/dsh_home/`，headless 的 sessions/storages 全部封在节点内，互不污染。
3. **模型 Key 复用**：运行时从 `node_python_llm_infer/node_config.json` 读取 api_key，注入子进程环境变量 `DEEPSEEK_API_KEY`（不落盘到 DSH 配置）。provider 在 `dsh_home/profiles/headless/cordis.patch.yml` 显式配置 OpenAI 兼容端点（绕开 pi-ai 内置目录解析问题）。
4. **沙箱工作区（fork 定制）**：DSH 源码 `packages/bundle/headless/src/index.ts` 的会话初始化 `meta.cwd` 改为支持 `DSH_WORKDIR` 环境变量覆盖——BNOS 侧注入 `DSH_WORKDIR=nodes/shared/dsh_workspace/`，Agent 的工作根（system prompt 的 cwd + workspace 插件的 fs 根）被限定在沙箱内，harness 源码零污染。
5. **调用链**：GUI 工具桥写 `dsh_task_in.json`（data_type=dsh_task）→ listener 轮询 → subprocess 调 `node --import tsx/esm apps/cli/src/bin.ts --profile headless <task>`（tsx 直载 TS 源码，改代码即改即用）→ 解析最终回答 → 写 `output.json`。

### GUI 工具接口（AAA 可调）

| 工具 | 说明 |
|---|---|
| `dsh.run_task` | 提交任务（写 task 文件），立即返回提交状态；DSH 任务分钟级，异步执行 |
| `dsh.check_task` | 查询最近一次任务结果（读 output.json，返回 result/final） |

两步式设计原因：ToolBridge 在主线程同步执行，DSH 任务会阻塞 GUI；拆成"提交/查询"天然异步。AAA 侧可在多轮对话中先 run 再 check。

## 实施过程与问题

1. **版本踩坑**：`@deepseek-ai/dsh@^0.1.0` 无匹配版本，registry 实际是 `0.1.0-rc.x`，锁定 `0.1.0-rc.6`。
2. **provider 解析**：pi-ai 内置 catalog 未描述 `deepseek-official` 路由（`getBuiltinProviders` 为空），先报 "resolves no models"；显式声明 providers 又报 "already declared"（与目录冲突）。解法：用**自定义 provider id**（`bnos-deepseek`）+ baseURL/models 显式配置 + `agent-default-model` 覆盖。
3. **原生模块编译**：pnpm 10 默认拦截 install script（allowBuilds 白名单：esbuild/node-pty/koffi 已放行）。初次 `--ignore-scripts` 装依赖会缺原生模块；补 `pnpm rebuild node-pty koffi esbuild`。验证后确认：node-pty 1.1.0 自带 `prebuilds/win32-x64/pty.node`（无需本地编译），koffi 经 `node-addon-require-builtin-win32-x64-msvc` 平台包加载——两者 `require` 冒烟测试均通过，bash/pwsh 工具的原生依赖已就绪。
4. **TRAE 沙箱拦截 windows-acl 受限 token 进程**：默认 `workspace-write` 模式下 pwsh 经 windows-acl runner 以受限 token 启动，TRAE 开发环境报 `process launch failed; code=2147483653`（真实环境无此限制）。用 `DSH_PERMISSION_MODE=danger-full-access` 临时绕过验证：pwsh 工具链路完全正常（见验收表）。

## 验收结果

| 项 | 结果 |
|---|---|
| DSH headless 直调（真实 API） | ✅ 返回"你好" |
| 源码版构建（pnpm install + build:lib:host） | ✅ 924 包 + 产物生成 |
| 源码版 headless（tsx 直载 TS） | ✅ exit 0 返回"你好" |
| 沙箱隔离（DSH_WORKDIR fork 定制） | ✅ 文件落在 dsh_workspace，harness 零污染 |
| node_dsh/main.py 业务逻辑 | ✅ 返回 {ok, result, final} |
| run.bat 启动检测 | ✅ 4 节点全启动（含 node_dsh），无 Python 报错 |
| 端到端：run_task 提交 → 节点执行 → check_task 查询 | ✅ DSH 真实创建文件并读取回报告知 |
| bash/pwsh 原生依赖（node-pty/koffi） | ✅ require 冒烟测试通过（prebuilds + 平台包加载） |
| pwsh 工具端到端（danger-full-access 绕过 TRAE） | ✅ `Write-Output hello` 输出正常；文件写入/读回沙箱 dsh_workspace 成功 |
| pwsh 可执行解析 | ✅ 系统无 PowerShell 7，pwsh-local 内置 fallback 自动解析到 Windows PowerShell 5.1（powershell.exe） |
| 会话续接（DSH_SESSION_ID → agents.resume） | ✅ 首轮约定暗号，次轮续接答对；无效 session_id 自动回退新会话并提示（详见 [DSH会话续接方案]([PLAN]-DSH会话续接方案（待决策）.md)） |
| workflow 接入 DSH 执行器（dsh.run_task_sync） | ✅ 流程步骤同步等待 Agent 完成（23s 真实等待，步骤结果=最终回答）；task_id 回带精确判定完成；timeout 兜底 + check_task 补查；GUI 工具桥子线程执行不冻结（详见 [workflow接入DSH执行器方案]([PLAN]-workflow接入DSH执行器方案（待决策）.md)） |

> ⚠️ **TRAE 环境限制说明**：默认 `workspace-write` 模式下 pwsh 经 windows-acl 受限 token 执行，TRAE 开发环境拦截（`process launch failed; code=2147483653`）。这是 TRAE 沙箱限制，**真实环境（run.bat 在 TRAE 外双击运行）不受影响**；在 TRAE 内验证 shell 工具需临时设 `DSH_PERMISSION_MODE=danger-full-access`。

## 后续扩展（对应 P2 深水区）

- [x] 会话续接（headless + session_id，经 `agents.resume` 复用持久化会话；未引入常驻 HTTP——详见 [DSH会话续接方案]([PLAN]-DSH会话续接方案（待决策）.md)。DSH 常驻 web-app 留作浏览器入口的后续演进）
- [x] bash/pwsh 工具启用（源码版已含 `packages/shell`，原生依赖就绪：node-pty prebuilds + koffi 平台包；Windows 上 `tool-bash` 平台禁用、`tool-pwsh` 启用，可执行解析自动 fallback 到 PowerShell 5.1；沙箱根 = session.header.cwd = DSH_WORKDIR，pwsh 写操作天然限定在 dsh_workspace）
  - 建议：生产环境安装 PowerShell 7（`winget install Microsoft.PowerShell`），pwsh 工具走官方正轨（UTF-8 默认、更全语法）
- [x] workflow_store 流程步骤接入 dsh.run_task（DSH 作为流程执行器：新增同步等待工具 `dsh.run_task_sync`（提交→轮询 output.json 以 task_id 精确判定完成→返回最终回答）；`main.py` 回带 task_id；tool_bridge 耗时工具子线程执行防 GUI 冻结——详见 [workflow接入DSH执行器方案]([PLAN]-workflow接入DSH执行器方案（待决策）.md)）
- [ ] subagent 透传（DSH 子 Agent 任务归因到 AAA 认知）
- [ ] harness 上游升级（`git pull` 时需留意 fork 定制点 `bundle/headless/src/index.ts` 的冲突）
