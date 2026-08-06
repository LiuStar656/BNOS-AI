# 2026-08-07 更新总览

[返回总索引](../README.md)

---

## 更新目录

- [01 日志系统实现](#01-日志系统实现)

---

## 摘要

| # | 核心改动 | 根因 | 影响 |
|---|---------|------|------|
| 01 | 实现按启动批次隔离的日志系统：GUI 日志（双文件 handler + 异常钩子）、引擎日志（_p 方法同时写文件）、节点日志（子进程 stdout/stderr 从 DEVNULL 改为写入独立日志文件） | GUI 无持久化日志；引擎日志仅 print 无文件；节点子进程日志被 DEVNULL 丢弃导致崩溃无法排查 | 每次 GUI 启动创建独立批次目录；app.log 记录运行日志，error.log 记录错误日志；引擎和节点日志按批次归档；支持通过 --log-dir 参数控制日志目录 |

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

---

## 文件变更统计

| 指标 | #01 |
|------|:---:|
| 涉及文件 | 7 |
| 新增行数 | ~180 |
| 删除行数 | ~30 |
| **净增行数** | **~150** |

---

**最后更新**：2026-08-07
