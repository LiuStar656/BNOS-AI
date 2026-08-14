# AGENTS.md — BNOS AI 项目（常驻指令）

> DSH 等 agent 每次会话自动加载（项目根 `.git` 定位 + `AGENTS.md` 候选）。
> 此处只留入口，细节在链接文档（一条事实一个家）。

- **改 GUI 代码前必读**：[GUI 开发规范](docs/design/[OK]-GUI开发规范.md)（工程/样式/配置/AI 操控规则/审查清单）
- **布局调整**：见规范 2.6 与[数据驱动UI布局动态调整方案](docs/design/[OK]-数据驱动UI布局动态调整方案.md)
- 设计/规范文档统一在 `docs/design/`（`[OK]`/`[PLAN]`/`[WIP]` 状态前缀），动手前先读对应文档
- 节点开发遵循各节点 `节点开发规范.md` 与根目录 `node_config_json_开发规范.md`
- GUI 代码在 `gui/`；节点在 `nodes/`（gitignore 不入库）；共享协议在 `nodes/shared/`：原子写、id 精确匹配、不手改运行时文件
