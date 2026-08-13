# Agent 间多轮对话与话题轮数控制（平台宣告话题结束）

## 问题描述

平台消息流是单向的「用户弹幕 → Agent 回复」，Agent 的广播发言不回到消息池，
Agent 之间无法针对话题进行连续对话；同时实验无法控制话题会话的轮数长度，
也无法在适当时候主动结束当前话题。

## 根因分析

- 平台 `step()`/`drain_queue()` 广播发言后只记录聊天历史，不把发言注入消息池，
  其他 Agent 下一轮看不到彼此的发言，对话无连续性。
- 平台没有任何「轮数上限 / 话题结束」机制，实验主循环只能由用户弹幕批次驱动。

## 修改方案

### 1. 平台多轮对话与话题结束 `platform_runner.py`

- 新增 `topic_rounds`（默认 10，0=不限）、`topic_active`、`topic_ended`、
  `agent_speech_count` 状态。
- `_feed_agent_speech(agent_id, content)`：把广播发言**回投消息池**
  （source=agent、user_id=agent_id、`dedup=False`）→ 其他 Agent 下一轮感知并接话，
  构成 agent 间多轮对话；每成功入池一条计 1 轮，达到 `topic_rounds` 后触发 `_end_topic`。
- `_end_topic()`：平台**主动宣告当前话题结束**——注入一条 role=system 公告到
  消息池 + 聊天历史（含累计轮数），发布 `topic_ended` 事件；此后发言不再回投/计数，
  Agent 可对结束公告回应最后一句，对话自然停止。
- `step()` 与 `drain_queue()` 在广播发言后调用 `_feed_agent_speech`。

**轮数语义**：只统计「成功入池的 agent 发言」；被去重丢弃、静默决策以及
Agent 后台的思考/总结（不经消息池）都不计入。

### 2. 消息池支持关闭去重 `message_pool.py`

- `enqueue_input(..., dedup=True)`：Agent 发言回投传 `dedup=False`——
  Agent 每次发言都是对话的实际一轮，不被同人同文去重（60s 窗口）误伤
  （去重机制本是为用户弹幕防刷屏设计的）。

### 3. 聊天历史渲染 `data_export.py`

- `render_chat_history_md` 支持 `role=system`（平台结束公告，`⏹ 平台：...`）。

### 4. 启动脚本 `run_pool_experiment.py`

- 新增 `--topic-rounds N`（默认 10，0=不限）。
- 主循环改造为**话题会话驱动**：Agent 发言回投维持对话，用户弹幕仅在池空时
  作开场/续场引子；达到 `--topic-rounds` 轮后平台宣告话题结束并停止注入。
- `_run_meta.json` 记录 `topic_rounds`；结束时打印累计轮数与结束状态。

### 5. 验收测试 `infra_acceptance_test.py`

- 新增 I3「话题轮数」3 项断言：Agent 发言回投消息池（source=agent）、
  达到 N 轮后 `topic_ended`、结束公告写入聊天历史（role=system）（36 → 39 项）。

## 影响范围

| 文件 | 改动 |
|------|------|
| `tests/message_pool/platform_runner.py` | `topic_rounds` 轮数控制、发言回投（`_feed_agent_speech`）、平台宣告话题结束（`_end_topic`） |
| `tests/message_pool/message_pool.py` | `enqueue_input` 增加 `dedup` 参数 |
| `tests/message_pool/data_export.py` | 聊天历史 md 渲染 role=system |
| `tests/message_pool/run_pool_experiment.py` | `--topic-rounds` 参数、会话驱动主循环 |
| `tests/message_pool/infra_acceptance_test.py` | 新增 I3 三项断言（36→39） |
| `tests/message_pool/README.md` | 多轮对话流程、--topic-rounds 参数 |

## 验证方法

- `infra_acceptance_test.py` 39 项全通过。
- 冒烟 `--agents 2 --rounds 3 --topic-rounds 3 --fake-llm`：3 轮后平台宣告
  「当前话题已结束（共 3 轮 agent 发言）」。
- **真实测试 `--agents 2 --rounds 20 --topic-rounds 10 --gid test10`**：
  2 个 Agent 围绕话题「聊聊最近的生活」自然对话 10 轮（拼图/留白/地图等隐喻
  连续延伸，Agent 能接住彼此发言——回投机制生效），第 10 轮后平台宣告话题结束
  （`chat_history.md` 中 role=system 公告），Agent 回应最后一句后对话停止；
  14 张表/聊天历史/events/decisions/evolution 全部落盘。
