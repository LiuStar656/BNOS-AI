# 03 配套插件同步进 DSH Web（GUI 层直接用插件）

> 时间：2026-08-24 ｜ 关联：[01 DSH web 桥接 BNOS（Phase 0）](./01_DSH-web桥接BNOS_Phase0.md) ｜ [02 方案方向修正](./02_方案方向修正_聊天为DSH原生加smart模式.md)

## 目标

用户决策：**原本 GUI 层面的功能，能用 dsh_desktop 配套插件的就直接装插件**（"大概看了一下都可以全部装上"）。本次把 dsh_desktop 仓库 `assets/plugins` 的全套 34 个配套插件同步进 BNOS 的 DSH web profile（`nodes/node_dsh/dsh_home/profiles/web`），使 DSH web 原生界面具备 BNOS 所需的 GUI 能力。

## 方案与执行

### 关键发现

- dsh_desktop 的插件与桌面壳的 `scripts/plugin-core`（manifest/inventory/patch-surgery/companion-profile 等）深度耦合，但官方提供了**独立于 Electron 壳**的同步入口：
  `node scripts/sync-companion-plugins.js [DSH_HOME] [--dsh-package <目录>]`
  它把 `assets/plugins` 的配套插件复制进 `<DSH_HOME>/profiles/web/node_modules/**`，并写入 `cordis.patch.yml`、对账 `dsh.profile.bundles`、同步内置 Agent 预设。
- **版本差**：node_dsh 用 `@deepseek-ai/dsh 0.1.0-rc.6`，插件面向 `0.1.1-rc.2`；peer 大多 `^0.1.0-rc.6` 或 `*`，可解析。
- **dsh_desktop/node_modules 未安装** → 插件的 vendor 依赖（schemastery 等）未随同步进来，导致首次启动 `ERR_MODULE_NOT_FOUND: schemastery`。

### 执行步骤

1. **备份**：`profiles/web` → `profiles/web.bak-before-plugins`（可回滚）。
2. 安装 pnpm（npm 全局 `pnpm@9`）。
3. dry-run 预览后执行真实同步（**不带 `--with-patches`**，避免面向 0.1.1-rc.2 的运行时补丁污染 0.1.0-rc.6 运行时）：
   ```
   node scripts/sync-companion-plugins.js "D:\BNOS-AI\nodes\node_dsh\dsh_home" \
     --dsh-package "D:\BNOS-AI\nodes\node_dsh\node_modules\@deepseek-ai\dsh"
   ```
   结果：34 个配套件装入 profile；15 个 bundle 插件并入 `dsh.profile.bundles`；19 个非 bundle 插件注册进 `cordis.patch.yml`；写入 `compaction-basic`/`harness-pet` 默认禁用条目；同步 8 个内置 Agent 预设 → dsh 包 `config/agent-presets`。
4. **补装缺失运行时依赖**（dsh_desktop 未装 node_modules，vENDOR 同步落空）：在临时目录 `npm install --no-save` 后复制到 profile 根 `node_modules`，避免 pnpm/npm prune 误删已同步插件。
   - 纯 JS：`schemastery`、`acp-kernel`、`@sinclair/typebox`、`ws`、`cosmokit`、`@standard-schema`
   - 原生：`node-pty`（dsh-better-sidebar）、`@photostructure/sqlite`（graph-memory）——均已成功构建/加载。

### 宿主入口实际 import 分析（决定补哪些依赖，避免过度安装）

对各 bundle 插件 `main` 入口做了静态扫描，仅宿主启动时 import 的外部依赖会崩启动。结论：
- community-market 宿主入口**不 import `sharp`**（sharp 仅媒体图标处理，链路在 install-root node_modules 解析），可启动。
- 需补依赖的宿主入口：dsh-better-sidebar（ws/schemastery/node-pty）、dsh-side-session（schemastery）、billion-context-dsh（acp-kernel）、graph-memory（@sinclair/typebox + @photostructure/sqlite）。

## 结果 / 验证

- DSH web 在 `http://127.0.0.1:52861` 启动成功，启动日志无任何 error/fail/warn。
- 已挂载插件：`openclaw-bridge`、`dsh-mini v1.4.2`、`dsh-vision`（wrapped llm.resolveModelInfo 3 个适配器）等。
- 健康检查：`GET /` → 200；`GET /bnos/api/poll` → 200（`@bnos/bridge` 桥接路由在同步后**仍存活**，cordis.patch.yml 保留 `insert: bnos-bridge`）。

## 生效 / 注记

- 插件与预设仅在 **DSH web 启动时**挂载，故需重启 web_server；重启会中断当前会话（数据在磁盘，重启后可继续）。
- `harness-pet`（桌面宠物，rAF 常驻绘画）与 `compaction-basic`（被 billion-context-dsh 接管压缩）**默认禁用**，可在 设置 → 插件 → 管理 一键开启。
- 卸载：从 `profiles/web/cordis.patch.yml` 删对应 insert 条目 + 删 `profiles/web/node_modules/@deepseek-ai/dsh-*`（及顶层对应包目录）。
- 后续桌面壳集成时，同一套插件由 dsh_desktop 壳的 plugin-core 自动管理（manifest/inventory/启停/更新），无需手动同步。

## 修改文件清单

### 新增 / 变更

| 文件 | 说明 |
|------|------|
| `nodes/node_dsh/dsh_home/profiles/web/cordis.patch.yml` | 新增 19 个非 bundle 插件 insert 条目 + `compaction-basic`/`harness-pet` 禁用条目；保留 `llm-pi-ai`/`agent-default-model`/`bnos-bridge` |
| `nodes/node_dsh/dsh_home/profiles/web/package.json` | `dsh.profile.bundles` 并入 15 个配套 bundle 插件 |
| `nodes/node_dsh/dsh_home/profiles/web/node_modules/**` | 34 个配套插件 + 补装依赖（schemastery/acp-kernel/@sinclair/typebox/ws/cosmokit/@standard-schema/node-pty/@photostructure） |
| `nodes/node_dsh/node_modules/@deepseek-ai/dsh/config/agent-presets/*` | 同步 8 个内置 Agent 预设（anchored-standard/minimal-win/router-standard/v4-flash-godmode-opencode-go/warmupbetter/warmupbetter-replay/whoami-standard/zero-anchored-standard） |
| `nodes/node_dsh/dsh_home/hotplug-hub/packs/dsh-desktop/hotpack.json` | hub 指针包（6 个内置件识别） |
