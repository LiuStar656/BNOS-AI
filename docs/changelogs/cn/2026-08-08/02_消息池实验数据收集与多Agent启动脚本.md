# 消息池实验数据收集设施与多 Agent 启动脚本

## 问题描述

多用户消息池实验需要三类数据：所有 Agent（bnosai）的原始数据库数据（按表分类）、
平台消息池聊天历史、以及一键拉起多个 Agent（默认 5 个）进入平台的启动脚本。
原平台仅有 events/decisions/evolution 三类产物，无聊天历史、无按表导出集成、无启动脚本。

## 根因分析

- 原始数据库按表导出逻辑只存在于 `tests/evolution_enhance_acceptance_test.py` 的私有
  函数 `export_db` 中，未集成到消息池平台，实验脚本无法复用。
- `collector.py` 只采集平台事件与 Agent 决策，没有"谁在消息池里说了什么"的聊天历史。
- 拉起多 Agent 需要手动逐个创建 `AgentBridge` 并拼装平台，数量调整不便捷。

## 修改方案

### 1. 数据导出 `tests/message_pool/data_export.py`（新增）

- `export_agent_db(db_path, out_dir, agent_id)`：单个 Agent 原始 SQLite 按表分类导出到
  `runs/.../db/{agent_id}_final/`（每表一个 JSON + `data.sqlite` 副本 + `_manifest.json`），
  格式与认知演化实验 `export_db` 对齐。
- `export_all_agent_dbs(agents, run_dir)`：遍历所有 Agent 导出。
- `render_chat_history_md(run_dir)`：把 `chat_history.jsonl` 渲染为人类可读 Markdown
  （用户弹幕与 Agent 广播按时间交错展示）。

### 2. 聊天历史 `collector.py` / `platform_runner.py`

- `collector.py` 新增 `chat_history.jsonl` 输出与 `chat()` 方法。
- `platform_runner.py` 在 `inject()` 记录入池成功的用户弹幕（role=user）、
  `step()` / `drain_queue()` 记录实际广播的 Agent 发言（role=agent），
  保证聊天历史与"平台实际收到 + 实际发出"一致（去重丢弃/静默不记录）。

### 3. 启动脚本 `tests/message_pool/run_pool_experiment.py`（新增）

- `--agents N`（默认 5）：调整 Agent 数量只改这一处；每个 Agent 独立 DB + 独立身份键
  `agent:{i}` + 默认角色种子。
- `--rounds N` / `--per-batch N` / `--gid NAME` / `--fake-llm`（假 LLM 冒烟验证，不调 API）/ `--out DIR`。
- 内置模拟用户（userA~userF）与弹幕池，DeepSeek 直连 `llm_infer`（与 self_evolution_test 同模式）。
- 主循环：注入弹幕 → `step()` 批量派发 → `drain_queue()` 广播排队发言。
- 收尾：等待 review 后台线程落库 → `write_evolution()` → 导出全部 Agent 原始 DB →
  渲染聊天历史 md；每次运行独立时间戳留档目录，禁止覆盖历史实验数据。

## 影响范围

| 文件 | 改动 |
|------|------|
| `tests/message_pool/data_export.py` | 新增：按表分类导出 + 聊天历史 md 渲染 |
| `tests/message_pool/run_pool_experiment.py` | 新增：多 Agent 启动脚本（--agents 默认 5） |
| `tests/message_pool/collector.py` | 新增 chat_history.jsonl 与 `chat()` |
| `tests/message_pool/platform_runner.py` | inject/step/drain_queue 记录聊天历史 |
| `tests/message_pool/infra_acceptance_test.py` | U5 增加 chat_history 断言（32→33 项） |
| `tests/message_pool/README.md` | 文件列表 + 数据产物 + 启动命令 |

## 验证方法

- `infra_acceptance_test.py` 33 项全通过（新增 chat_history 落盘断言）。
- `run_pool_experiment.py --agents 3 --rounds 2 --fake-llm` 冒烟跑通（不调真实 API）：
  每个 Agent 导出 14 张表（user_messages 含正确 user_id 归属）、chat_history.jsonl/md、
  events/decisions/evolution.json、_run_meta.json 全部落盘。
