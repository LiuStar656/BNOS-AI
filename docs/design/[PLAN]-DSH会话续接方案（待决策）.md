# [PLAN]-DSH 会话续接方案

> 状态：✅ 已实施（2026-08-14，路线 A：headless + session_id 续接）
> 关联：[DeepSeekHarness接入方案]([PLAN]-DeepSeekHarness接入方案.md)「后续扩展」第 1 项
> 目标：AAA/流程可对 DSH 发起**多轮对话续接**（同会话跨任务保留上下文），替代当前"每次任务新会话"

---

## 1. 问题现状

当前 node_dsh 每次任务都走 `dsh --profile headless <task>`，fork 的 runner 每次执行：

```ts
sessionId: SessionId(`session-${randomUUID()}`),   // 随机新会话
```

- 每轮任务都是全新会话，模型**不记得上一轮**说过什么
- 对话历史其实已持久化在 `dsh_home/sessions/`（JSONL，headless 每轮结束 flush），但从未被复用

## 2. 关键事实（已调研确认）

| 事实 | 说明 |
|---|---|
| 官方 `agents.resume` API | AgentRegistry 内置 `resume(ownerCtx, { resumeSessionId })`——加载持久化 session 并恢复 agent（[core/agent/src/index.ts](file:///e:/杂项/BNOS_AI_project/nodes/node_dsh/harness/packages/core/agent/src/index.ts#L204-L213)） |
| 持久化已挂载 | headless profile 含 `session-persistence-jsonl`（root=`dshHomePath('sessions')`），每轮 headless 结束已 flush |
| 当前 fork 点 | `bundle/headless/src/index.ts` 的 `agents.create`（已有 DSH_WORKDIR fork 先例） |
| 沙箱/模型/provider | 与会话无关，A/B 路线共用现有配置（bnos-deepseek + DSH_WORKDIR） |

## 3. 路线 A：headless + session_id 续接（推荐）

### 3.1 架构

```
任务(带 session_id?) → dsh_task_in.json
        │
   node_dsh/listener.py（不变，文件轮询）
        │
   node_dsh/main.py（小改：session_id 透传）
        │  env: DSH_SESSION_ID=<id>（有则续接，无则新会话）
        ▼
   DSH headless（fork：create ↔ resume 二选一）
        │  会话 JSONL 已持久化于 dsh_home/sessions/
        ▼
   output.json（新增字段 session_id）
```

- **保持单次任务进程模式**：仍是 `subprocess.run` 一次任务一进程，无常驻、无 HTTP 端口
- BNOS 文件协议不变，端口映射/过滤器不变
- 会话续接 = 复用持久化 session_id

### 3.2 改动点

| 文件 | 改动 |
|---|---|
| `harness/packages/bundle/headless/src/index.ts`（fork 定制） | 读 `process.env.DSH_SESSION_ID`：有值 → `agents.resume({ resumeSessionId, agentOptions })`；无值 → 现有 `agents.create`。inject 补 `sessionPersistence`（resume 前置依赖） |
| `nodes/node_dsh/main.py` | 输入增加可选 `session_id`：有 → 注入 `DSH_SESSION_ID` 环境变量；无 → 新会话并把生成 id 写回结果 |
| `gui/core/tool_registry.py` | `dsh.run_task` 增加可选 `session_id` 参数（透传）；`check_task` 解包 `session_id` |
| `docs/design/[PLAN]-DeepSeekHarness接入方案.md` | 验收表/后续扩展更新 |
| `dsh_home/profiles/headless/package.json` | 无需改动（resume 属 core 能力） |

### 3.3 数据流示例

```jsonc
// 第一轮（无 session_id）
{ "data_type": "dsh_task", "task": "我们定个暗号：蓝鲸" }
→ output.json: { "ok": true, "session_id": "session-abc123", "final": "好的，暗号是蓝鲸" }

// 第二轮（带 session_id 续接）
{ "data_type": "dsh_task", "task": "暗号是什么？", "session_id": "session-abc123" }
→ output.json: { "ok": true, "session_id": "session-abc123", "final": "暗号是蓝鲸" }
```

### 3.4 风险与边界

- **会话膨胀**：session 只增不减，本期不做清理（文档注明，后续可按天/按量清理 `dsh_home/sessions/`）
- **resume 失败场景**：session_id 不存在/已损坏 → 捕获异常回退为新会话并在结果中提示（main.py 兜底）
- **并发**：listener 线程池 1 worker 串行，无同会话并发冲突
- **上下文长度**：多轮对话超模型上下文 → DSH 自带 compaction（compaction-basic 已挂载），自动压缩

### 3.5 验收标准

1. 第一轮任务（无 session_id）→ 返回 `session_id`
2. 第二轮（带同一 session_id）→ 模型记得第一轮上下文（如暗号问答）
3. 不存在/错误的 session_id → 自动新会话且不报错
4. run.bat 4 节点启动无报错；`dsh.run_task`/`dsh.check_task` GUI 调用正常

## 4. 路线 B：web-app 常驻 HTTP 服务

### 4.1 架构

```
   node_dsh/listener.py（常驻）
        │
   main.py 启动常驻 DSH web 进程（dsh --profile web --port <固定端口>）
        │              DSH 侧：WebServer + api-gateway（HTTP/WebSocket）
        ├── HTTP 提交任务/轮询结果（api-gateway 接口）
        └── 会话管理在 DSH 侧（session_id 天然支持）
```

- 启用官方 `web-app` bundle（base + web-app）：Host/WebServer/前端静态资源/浏览器 UI/完整会话管理
- node_dsh 常驻管理 DSH 子进程生命周期

### 4.2 改动点

| 文件 | 改动 |
|---|---|
| 新 profile | `dsh_home/profiles/web/`（bundle 组合 web-app + base，provider 配置同 headless） |
| `main.py` | 大改：启动/守护常驻 DSH web 进程；HTTP 客户端（提交/轮询/会话）；端口与进程管理 |
| `listener.py` | 适配常驻模式（任务转 HTTP，进程重启自愈） |
| 前端构建 | `host-frontend-static` 静态资源构建（浏览器 UI 面） |
| 安全 | 端口暴露 + `--trusted-host` 信任边界配置 |
| `tool_registry.py` | `dsh.run_task`/`check_task` 改走 HTTP |

### 4.3 风险

- **工程量大**：main.py/listener.py 重构、新 profile、前端构建、端口/信任管理
- **安全面**：HTTP 端口暴露本机，需 trusted-host 白名单；TRAE 沙箱可能拦截常驻服务监听
- **资源占用**：web 模式挂载浏览器前端 + 常驻进程
- **与本项目耦合**：DSH 官方 web 面是完整浏览器 IDE（其价值主要在人工浏览器使用），BNOS 节点协议只需任务/会话 API

## 5. 对比与建议

| 维度 | A：headless + session_id | B：web-app 常驻 HTTP |
|---|---|---|
| 实现工作量 | 小（1 fork 文件 + 参数透传） | 大（进程管理/HTTP/新 profile/前端） |
| 会话续接 | ✅ 官方 resume API + 既有 JSONL 持久化 | ✅ 完整会话管理 |
| 协议一致性 | ✅ 保持 BNOS 文件协议 | HTTP + 端口 + 信任边界 |
| 并发/常驻 | 无（一次任务一进程） | 有（常驻服务） |
| 演进空间 | B 可作后续演进（浏览器入口与 BNOS GUI 并行） | 一次性到位 |
| 风险 | 低 | 中高（安全面/沙箱/资源） |

**建议：路线 A**。理由：
1. DSH 官方已提供 `agents.resume`，路线 A 是"用官方能力的最小改动"，不重复造轮子
2. 保持 BNOS 文件协议，不动 listener/端口/过滤器，风险可控
3. B 的价值（浏览器 UI + HTTP API）超出 BNOS 当前需求；若未来要给用户浏览器入口，可在 A 之上叠加官方 web profile

## 6. 实施步骤（若选 A）

1. fork `bundle/headless/src/index.ts`：`DSH_SESSION_ID` 分支（create ↔ resume）+ inject `sessionPersistence`
2. `pnpm run build:lib:host` 重新构建 bundle 产物（或依赖 tsx 直载源码，无需构建——当前运行方式）
3. `main.py`：session_id 参数透传 + 结果回带 + resume 失败兜底
4. `tool_registry.py`：`dsh.run_task` 支持 session_id
5. 端到端验证（暗号问答两轮）+ run.bat 启动检测
6. 更新 [PLAN]-DeepSeekHarness接入方案.md

> 附注：当前运行方式为 `node --import tsx/esm apps/cli/src/bin.ts`（tsx 直载 TS 源码），fork 改 `src/index.ts` 即改即用，无需重新构建 lib 产物。

## 7. 实施记录（路线 A）

### 改动文件

| 文件 | 改动 |
|---|---|
| `harness/packages/bundle/headless/src/index.ts`（fork） | inject 补 `sessionPersistence`；`DSH_SESSION_ID` 有值 → `agents.resume` 续接、无值 → `agents.create` 新建；resume 失败 try/catch 回退新会话（stderr 打 `[bnos] resume session ... failed`）；stdout 首行输出 `__BNOS_SESSION__=<id>` 供 main.py 解析 |
| `nodes/node_dsh/main.py` | `process()` 透传可选 `session_id`；`_run_dsh()` 注入 `DSH_SESSION_ID` 环境变量；解析 `__BNOS_SESSION__` 行回带真实会话 id（优先 DSH 输出、异常才用输入 id）；检测 stderr 的 `[bnos] resume session` 标记并在 message 提示"会话续接失败，已新建会话" |
| `gui/core/tool_registry.py` | `dsh.run_task` 参数新增可选 `session_id`（透传到 task 输入文件）；`dsh.check_task` 透出 `session_id`（output.json 直接含该字段） |

### 验收结果

| 项 | 结果 |
|---|---|
| 第一轮（无 session_id）→ 返回 session_id | ✅ `session-268dfb4b-...` |
| 第二轮（带同一 session_id）→ 上下文续接 | ✅ 首轮约定暗号"蓝鲸"，次轮询问答"蓝鲸" |
| 无效 session_id → 自动新会话 + 提示 | ✅ message 提示"会话续接失败，已新建会话"，回带新真实 id |
| 完整链路（dsh_task_in.json → listener → main.py → DSH → output.json） | ✅ 续接问答正确，`session_id` 一致 |
| run.bat 4 节点启动 | ✅ 无 Python 报错 |
| 代码诊断 | ✅ main.py / tool_registry.py 无语法/类型错误 |

### 使用方式

```jsonc
// 新建会话
{ "data_type": "dsh_task", "task": "..." }
→ output.json: { "ok": true, "session_id": "session-xxx", "final": "..." }

// 续接会话（GUI 侧 dsh.run_task 传 session_id 参数）
{ "data_type": "dsh_task", "task": "...", "session_id": "session-xxx" }
→ output.json: { "ok": true, "session_id": "session-xxx", "final": "..." }
```

### 后续注意

- 会话只增不减：多轮使用后可清理 `dsh_home/sessions/`（或按天归档），本期未做自动清理
- 多轮上下文超模型窗口时 DSH 自带 compaction 自动压缩
