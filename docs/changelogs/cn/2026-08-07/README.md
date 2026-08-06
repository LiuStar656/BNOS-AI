# 2026-08-07 更新总览

[返回总索引](../README.md)

---

## 更新目录

- [01 日志系统实现](#01-日志系统实现)
- [02 记忆系统重构：新增日记表与多表语义检索](#02-记忆系统重构新增日记表与多表语义检索)

---

## 摘要

| # | 核心改动 | 根因 | 影响 |
|---|---------|------|------|
| 01 | 实现按启动批次隔离的日志系统：GUI 日志（双文件 handler + 异常钩子）、引擎日志（_p 方法同时写文件）、节点日志（子进程 stdout/stderr 从 DEVNULL 改为写入独立日志文件） | GUI 无持久化日志；引擎日志仅 print 无文件；节点子进程日志被 DEVNULL 丢弃导致崩溃无法排查 | 每次 GUI 启动创建独立批次目录；app.log 记录运行日志，error.log 记录错误日志；引擎和节点日志按批次归档；支持通过 --log-dir 参数控制日志目录 |
| 02 | 新增 diaries 日记表与 event_summary 解耦；MemOS 索引增加来源表维度，支持 long_term_memory / user_messages / diaries 三表语义检索；记忆图谱支持 PCA 降维坐标导出、增量更新与可配置边规则；移除认知确认次数逻辑 | 日记混存 event_summary 无法独立管理；检索仅覆盖单表导致记忆召回不完整；确认次数对决策无实际价值；图谱全量重建耗时且 GUI 无法复现布局 | 日记独立存储与查询；检索结果附日期/心情上下文，回忆更完整；knowledge_graph.json 新增 x/y 坐标、all_pairs、meta；图谱增量构建 + recompute_graph_edges 免重新编码 |

---

### 01 日志系统实现

详见 [01_日志系统实现.md](./01_日志系统实现.md)。

### 02 记忆系统重构：新增日记表与多表语义检索

详见 [02_记忆系统重构与多表语义检索.md](./02_记忆系统重构与多表语义检索.md)。

---

## 修改文件清单

### 新增文件

| 文件 | 所属 |
|------|------|
| `gui/core/logger.py` | #01 |
| `docs/design/[OK]-日志系统设计方案.md` | #01 |

### 重大修改文件

| 文件 | 改动 | 所属 |
|------|------|------|
| `bnos_runtime/standalone_runner.py` (源头) | `start()` 增加 `log_dir` 参数，节点 stdout/stderr 写入 `nodes/{node_id}.log` | #01 |
| `bnos_runtime/engine.py` (源头) | `PipelineRunner` 增加 `log_dir` 参数；`_p()` 同时写文件；`--log-dir` CLI 参数 | #01 |
| `bnos_runtime/standalone_runner.py` (AI 项目) | 同步源头修改，保留 JS 节点支持 | #01 |
| `bnos_runtime/engine.py` (AI 项目) | 同步源头修改 | #01 |
| `gui/main.py` | 启动时初始化日志系统，传递 `--log-dir` 给引擎 | #01 |
| `gui/pages/node_page.py` | `_pipe_engine_output` 增加文件写入；页面内启动引擎时获取批次目录 | #01 |
| `db.py` | 新增 diaries 表；自我/他人认知写库取消去重合并，直接 INSERT | #02 |
| `memos.py` | 索引增加来源表维度（_entry_tables）；三表检索；模型加载超时；图谱增量构建 + PCA 坐标 + 可配置边规则；新增 recompute_graph_edges | #02 |
| `main.py` | 日记改写 diaries 表；移除确认次数查询；事件摘要带日期前缀；clear 排除 sqlite_ 系统表 | #02 |
| `diary.py` | `_diary_exists` 改查 diaries 表 | #02 |
| `prompt.py` | 移除确认次数占位符 | #02 |
| `listener.py` | logseq 回填按条目来源表动态查询 | #02 |
| `output_default.json` / `output_logseq.json` / `output_prompt.json` / `output_reply.json` | 示例数据同步更新 | #02 |

---

## 文件变更统计

| 指标 | #01 | #02 |
|------|:---:|:---:|
| 涉及文件 | 7 | 10 |
| 新增行数 | ~180 | 465 |
| 删除行数 | ~30 | 101 |
| **净增行数** | **~150** | **~364** |

---

**最后更新**：2026-08-07
