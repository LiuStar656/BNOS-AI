# DSH 配置与可视化面板接入 BNOS GUI 方案（待决策）

> ⚠️ **已废弃（2026-08-14）**：用户澄清需求——**不内嵌 DSH web 面板**，而是把 DSH 的
> 设置/修改/控制组件做成 BNOS GUI 原生控件。已按新方向实施，见
> [DSH设置控制组件接入GUI方案（待决策）]([PLAN]-DSH设置控制组件接入GUI方案（待决策）.md)。
> 本文件保留仅作调研存档（web 面板启动方式、前置构建结论仍有参考价值）。

> 需求：把 DSH（DeepSeek Harness）的**配置管理**和**可视化面板（web UI）**挪到 BNOS AI 的 GUI 上，统一在一个入口使用。

---

## 1. 现状调研结论

### 1.1 DSH 可视化面板 = `dsh --profile web`

| 项 | 现状 |
|---|---|
| 启动方式 | `dsh --profile web`（`web` 是 `--profile web` 的硬编码别名；`dsh web` 等价） |
| 服务默认 | `127.0.0.1:3080`（`--host` / `--port` 可改，`--port 0` 让 OS 选端口） |
| 安全边界 | 仅允许 `127.0.0.1` 默认信任（`--host 0.0.0.0` 被明确禁止）；`--trusted-host` 可加白 |
| 面板能力 | 会话管理、模型设置（settings-models）、插件清单、Workspace、Goal、Plan、Subagent、Trajectory、Workflow 运行等完整 Agent 可视化 |
| 前端构建 | **`apps/web/dist` 不存在、`dsh-client-web` 等依赖未安装 → 面板当前不可用，需先构建** |

### 1.2 DSH 配置 = profile patch 层

```
dsh_home/profiles/headless/
  ├── cordis.yml          # 空（[]，编辑入口在 patch 层）
  └── cordis.patch.yml    # BNOS 定制：provider bnos-deepseek（baseURL/models）+ agent-default-model
```

- 关键配置：provider（`apiKeyEnv=DEEPSEEK_API_KEY`、`baseURL=https://api.deepseek.com/v1`、`models`）、默认模型（`deepseek-v4-flash`）
- **web profile 目前不存在**，web 面板若启用，需要一份与 headless 相同的 provider patch（否则面板无模型可用）

### 1.3 BNOS GUI 侧现成能力（可直接复用）

- **页面插槽注册**：`ui_registry.register("page.<id>", 工厂, meta={icon,page_id,title})` → 侧边栏自动组装（[ui_registry.py](file:///e:/杂项/BNOS_AI_project/gui/core/ui_registry.py#L41-L61)）
- **内嵌网页**：Live2D 页已示范 `QWebEngineView` 内嵌本地 HTTP 服务（[live2d_page.py](file:///e:/杂项/BNOS_AI_project/gui/pages/live2d_page.py)）
- **本地服务生命周期**：`subprocess.Popen` + 端口清理 + 页面析构停止（Live2D `_start_server`/`_kill_port` 同款）

---

## 2. 关键矛盾 / 前置风险

| 项 | 说明 |
|---|---|
| web 前端未构建 | 需 `pnpm install`（workspace 全量，体积大）+ `pnpm --filter @deepseek-ai/dsh-web-frontend build`（vite build） |
| 构建环境 | TRAE 沙箱内安装/构建可能受限；真实环境（run.bat 外）不受影响 |
| 常驻进程 | web server 是常驻 HTTP 服务，需随 GUI 启停（复用 Live2D 的 Popen 管理模式） |
| 模型配置 | web profile 需补 provider patch（与 headless 共享，配置管理应统一维护） |
| 端口 | 固定 3080 可能冲突 → 用 `--port 0` 动态端口，从进程输出解析实际 URL |

---

## 3. 方案对比

### 方案 A：一次到位 — 配置页 + 内嵌 web 面板（推荐）

GUI 新增两个页面：

1. **「DSH 面板」页**：内嵌 `QWebEngineView` 加载 `dsh --profile web`（Popen 管理，动态端口，`DSH_HOME`/`DSH_WORKDIR`/`DEEPSEEK_API_KEY` 注入，随页面/应用启停）
2. **「DSH 配置」页**：表单化编辑 provider（baseURL / 模型 / apiKey 来源），统一写 headless + web 两份 patch，保存后下次任务生效

**前置工作**：构建 web 前端（pnpm install + vite build）+ 生成 web profile patch。
**优点**：完整交付"配置 + 可视化"；体验最好（Agent 过程可视化、多会话管理）。
**缺点**：前置构建有不确定性（体积/时长/TRAE 沙箱）；web server 与 GUI 生命周期耦合需仔细管理。

### 方案 B：仅配置管理（轻量，先不内嵌面板）

GUI 新增「DSH 配置」页：表单编辑 provider/模型，写 headless + web 两份 patch。
**优点**：零构建、改动小、风险低。
**缺点**：可视化面板仍只能浏览器手动访问（`dsh --profile web`），不满足"挪到 GUI"的完整意图。

### 方案 C：分两步走（折中，推荐节奏）

- **第一步（本次）**：DSH 配置页 + 构建 web 前端 + 准备 web profile，验证 `dsh --profile web` 可本地启动
- **第二步（下阶段）**：GUI 内嵌 web 面板页（复用 Live2D 模式）

**优点**：先落地低风险配置管理，验证 web 构建可行后再投入内嵌面板；风险可控、进度可见。
**缺点**：面板集成推后，本阶段交付不完整。

---

## 4. 方案 A 详细设计（若选 A 或 C 第二步）

### 4.1 web 前端构建（一次性前置）

```bash
cd nodes/node_dsh/harness
pnpm install --ignore-scripts        # 补齐 workspace 依赖（含 web-app bundle、client-web 等）
pnpm --filter @deepseek-ai/dsh-web-frontend build   # vite build → apps/web/dist
```

### 4.2 web profile 准备

新建 `dsh_home/profiles/web/cordis.patch.yml`：provider 定义与 headless 相同（bnos-deepseek + deepseek-v4-flash），供面板使用。

### 4.3 GUI「DSH 面板」页（`page.dsh_panel`）

- 页面激活时 `subprocess.Popen(["node", "--import", "tsx/esm", "apps/cli/src/bin.ts", "--profile", "web", "--port", "0"], env=注入 DSH_HOME/DSH_WORKDIR/DEEPSEEK_API_KEY)`
- 解析 stdout 中的 URL 行 → `QWebEngineView.load(url)`（Live2D 同款）
- 页面析构 / 应用退出时终止进程（`QProcess`/`Popen.terminate` + 端口兜底清理）
- 复用沙箱 `DSH_WORKDIR=nodes/shared/dsh_workspace`

### 4.4 GUI「DSH 配置」页（`page.dsh_config`）

- 读取 `dsh_home/profiles/{headless,web}/cordis.patch.yml` → 表单（baseURL / 默认模型 / 模型列表 / apiKey 来源说明）
- 保存 → 原子写回两份 patch（YAML 由 `pyyaml` 或最小手写序列化；需确认 gui venv 是否含 pyyaml）
- 说明文案：Key 由 llm_infer 注入不落盘；修改下次任务生效

### 4.5 复用与边界

- 插槽注册 + 侧边栏：`ui_registry.register("page.dsh_panel", ..., meta={"icon":"terminal",...})`
- 不侵入现有 chat/流程页；DSH 面板与会话续接（`dsh_home/sessions/`）天然互通

---

## 5. 验收方式

1. `dsh --profile web` 本地启动成功（浏览器可访问 127.0.0.1 面板，模型可选 bnos-deepseek）
2. GUI 内嵌面板：页内可直接发消息跑 Agent 任务，工具调用可视化
3. 配置页：修改模型/保存 → 两份 patch 同步更新 → headless 任务与面板均生效
4. run.bat 启动检测无报错；GUI 退出后 web server 进程被清理

## 6. 待决策项

- [ ] 方案选型：A（一次到位）/ B（仅配置）/ C（分两步）
- [ ] 若选 C：本阶段只做配置页 + 构建验证，面板下阶段再做
- [ ] 配置页 YAML 读写依赖：gui venv 是否允许新增 pyyaml（或手写极简 YAML 序列化，仅覆盖 provider 结构）
