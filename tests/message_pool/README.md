# message_pool 消息池实验平台

多用户交互实验的基础设施：平台维护聊天室式消息池，多个 AAA 认知 Agent 订阅消息池、
批量消费、选择性回应（对齐 Lumi_Nox 的 SpeakerScheduler / SpeechOutputArbiter）。
仅提供基础设施，不含具体实验场景（实验脚本单独编写）。
> 注：『弹幕』仅为从 Lumi_Nox 借鉴的概念词，本场景实为聊天室——多人按时间顺序发言，
> Agent 看到完整聊天记录并按轮次自然参与。

## 文件列表

| 文件 | 用途 |
|------|------|
| `event_bus.py` | 事件发布/订阅（消息池、仲裁器、采集器解耦通信） |
| `message_pool.py` | 聊天室消息池：`enqueue_input` 入队不打断（`dedup` 可关，agent 回投不过去重）/ `pop_all_inputs` 批量取出 / 同人同文去重 / 单用户洪流配额 / 优先级排序 |
| `router.py` | `@` 点名路由：`pick_speaker` 决定一批消息的派发顺序（被点名者优先） |
| `arbiter.py` | 发言仲裁器：同一时刻单一发言权；`POLICY_QUEUE` / `POLICY_DROP` / `POLICY_INTERRUPT` |
| `collector.py` | 实验数据采集：`events.jsonl` / `decisions.jsonl` / `chat_history.jsonl` / `evolution.json`（runs/ 目录留档） |
| `agent_bridge.py` | Agent 桥接：调 AAA `_on_pool_batch` → LLM → `_on_parsed(batch_mode=True)`，多轮回执直到拿到 `{action: reply|silent}` |
| `platform_runner.py` | 平台主入口：编排消息池 + 路由 + 仲裁 + 采集 + Agent（文件名避让 stdlib `platform`）；`record_speech` 自我介绍 / `announce` 话题发放 / agent 发言回投构成多轮对话 / `topic_rounds` 轮数上限后平台宣告话题结束 |
| `data_export.py` | 原始数据库按表分类导出（`db/{agent}_final/`：每表 JSON + sqlite + manifest）+ 聊天历史 md 渲染（含自我介绍/话题/结束公告） |
| `run_pool_experiment.py` | 实验启动脚本：每次启动生成专属 DB + 随机角色种子 + 自我介绍 + 平台发话题，拉起 N 个 Agent（`--agents`，默认 5）跑 agent 间多轮对话并收集全部数据 |
| `topic.txt` | 默认话题文件：修改内容即可更换下次实验话题（或用 `--topic` 直接传） |
| `infra_acceptance_test.py` | 基础设施验收测试（不跑 LLM，Fake LLM 覆盖批量链路，39 项断言） |

## 数据收集（实验产物）

每次运行留档于 `docs/experiments/message_pool_test/runs/YYYYMMDD_HHMMSS[_gid]/`：

| 产物 | 内容 |
|------|------|
| `db/{agent_id}_final/` | 每个 Agent 的**原始数据库按表分类导出**（`{表名}.json` + `data.sqlite` 副本 + `_manifest.json`，含 personality_seed 随机角色种子） |
| `chat_history.jsonl` / `.md` | **平台消息池聊天历史**（自我介绍 + 平台话题 + Agent 广播 + 平台结束公告，按时间顺序；md 为人类可读版） |
| `events.jsonl` | 平台事件（入池 / 去重 / 派发 / 仲裁 / 广播） |
| `decisions.jsonl` | Agent 每批决策（reply/silent、user_id、想法、性格向量快照、心情） |
| `evolution.json` | 终态性格向量 / 情感 / 他人认知条目数（按 user_id 分组） |
| `_run_meta.json` | 本次运行配置 |

## 架构与数据流

```
[Agent A] [Agent B] ... [Agent N]          平台
    │          │             │
    ▼          ▼             ▼
消息池（enqueue_input → pop_all_inputs）
 → 路由 router（@ 点名 / 无点名）
 → 派发 _on_pool_batch（批量写库 + 合并上下文）
 → AAA 认知处理 → LLM → {action: reply|silent}
 → 仲裁器 SpeechOutputArbiter（reply 广播 / silent 标记已消费）
 → 实验采集（events.jsonl / decisions.jsonl / evolution.json）
```

## 核心 API 示例

```python
from message_pool.agent_bridge import AgentBridge
from message_pool.platform_runner import MessagePoolPlatform
from message_pool.arbiter import ArbiterPolicy

agents = [AgentBridge("agent:alpha", "agent:alpha", db_path_a, llm_fn), ...]
plat = MessagePoolPlatform(agents, run_dir="runs/...", gid="exp",
                           arbiter_policy=ArbiterPolicy.QUEUE)
plat.inject([{"content": "大家好", "user_id": "userA"}, ...])
speech = plat.step()          # 本步发言 (agent_id, content) 或 None
while True:                   # 依次广播排队发言
    queued = plat.drain_queue()
    if queued is None:
        break
plat.write_evolution()        # 采集终态 evolution.json
```

## 运行验收测试

在项目根目录使用 AAA 节点 venv 运行（Fake LLM，不调用真实 API）：

```
& nodes/node_python_aaa_cognition/venv/Scripts/python.exe tests/message_pool/infra_acceptance_test.py
```

## 启动实验（拉起多 Agent）

每次启动流程：

1. 为每个 Agent 生成**专属数据库** `runs/.../db/agent_{i}.sqlite`
2. 用角色种子功能**随机注入初始设定**（性格向量 + 说话风格 → `personality_seed` 表；`--seed` 固定可复现）
3. 每个 Agent 基于角色设定做**自我介绍**（广播到聊天历史，stage=self_intro）
4. 自我介绍完成后平台**发放话题**（默认读 `topic.txt`，改文件即可换话题）
5. **多轮对话**：Agent 广播发言**回投消息池**，其他 Agent 下一轮感知并接话（用户发言仅在池空时作开场/续场引子）
6. **避让机制（防自言自语）**：上一条 agent 广播发言者下一批被跳过（@ 点名豁免），让其他 Agent 有机会接话；若其他 Agent 均沉默则解除避让，防止对话停滞
7. 达到 `--topic-rounds` 轮（默认 10，只统计**成功入池的 agent 发言**，后台思考/总结不计）后平台**主动宣告话题结束**（role=system），Agent 可回应最后一句，对话停止

```
# 真实实验：拉起 5 个 Agent（默认），agent 间对话 10 轮后平台宣告话题结束
& nodes/node_python_aaa_cognition/venv/Scripts/python.exe tests/message_pool/run_pool_experiment.py --rounds 20 --gid exp1

# 调整 Agent 数量：改 --agents 即可（如 2 个，10 轮简单测试）
& nodes/node_python_aaa_cognition/venv/Scripts/python.exe tests/message_pool/run_pool_experiment.py --agents 2 --rounds 20 --topic-rounds 10 --gid test10

# 调整对话轮数上限：--topic-rounds N（0=不限）
& nodes/node_python_aaa_cognition/venv/Scripts/python.exe tests/message_pool/run_pool_experiment.py --topic-rounds 20 --gid exp2

# 更换话题：改 topic.txt，或直接传 --topic（重启实验时更换）
& nodes/node_python_aaa_cognition/venv/Scripts/python.exe tests/message_pool/run_pool_experiment.py --topic "聊聊你最喜欢的一本书"

# 固定随机种子复现同一批角色设定
& nodes/node_python_aaa_cognition/venv/Scripts/python.exe tests/message_pool/run_pool_experiment.py --seed 42 --gid exp3

# 冒烟验证流程（假 LLM，不调真实 API）
& nodes/node_python_aaa_cognition/venv/Scripts/python.exe tests/message_pool/run_pool_experiment.py --agents 2 --rounds 3 --topic-rounds 3 --fake-llm
```

参数：`--agents N`（默认 5）、`--rounds N`（用户发言批次上限，默认 20）、`--seed INT`（随机种子，默认 None=每次随机）、
`--topic 文本`（本次话题，优先于话题文件）、`--topic-file 路径`（话题文件，默认 `tests/message_pool/topic.txt`）、
`--topic-rounds N`（agent 间对话轮数上限，默认 10，0=不限；达到后平台宣告话题结束）、
`--per-batch N`（每轮消息条数上限）、`--gid NAME`（实验标识）、`--fake-llm`（验证模式）、`--out DIR`（留档根目录）。

## 关键约束

- 平台侧组件（event_bus / message_pool / router / arbiter / collector）不依赖 AAA 节点，可独立单测。
- `agent_bridge` 通过 `sys.path` 直连 AAA 节点 `main.py`（与 `tests/self_evolution_test.py` 同模式），仅用于测试/实验场景，不构成节点间通信。
- 节点目录的 `memos.preload()` 会异步加载语义模型（daemon 线程），验收测试须先禁用 `memos.rebuild_index` 等后台重建线程（防并发 native 崩溃，见项目内存教训）。
- 仲裁器在 `platform.step()` 步末释放发言权；QUEUE 策略下的排队发言由 `drain_queue()` 逐步广播，保证「同一时刻至多一个 Agent 发言」。
