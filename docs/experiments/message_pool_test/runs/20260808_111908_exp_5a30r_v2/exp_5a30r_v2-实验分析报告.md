# exp_5a30r_v2 实验分析报告

> 实验目录：`E:\杂项\BNOS_AI_project\docs\experiments\message_pool_test\runs\20260808_111908_exp_5a30r_v2`
> 分析日期：2026-08-08
> 前置实验：n3_25r（3 智能体 25 轮）、5a40r_api（5 智能体 40 轮）、5a40r_v2（5 智能体 40 轮 v2）、5a30r（5 智能体 30 轮）

---

## 一、实验概况

| 项目 | 值 |
|---|---|
| 运行时间戳 | 2026-08-08 11:19:08 |
| 智能体数量 | 5（agent:0 ~ agent:4） |
| rounds 配置 | 60（topic_rounds=30，per_batch=6） |
| 模型 | deepseek-v4-flash |
| evolution.rounds | **10**（`rounds_metric: "processed_batches"`，新口径字段） |
| 数据文件 | evolution.json、topic_report.md、llm_stats.json、decisions.jsonl（41 条）、events.jsonl（173 条）、_run_meta.json |

**核心结论（一句话）**：本轮是五轮实验中基础设施最干净的一轮——8 组双向认知、agent:0 黑洞消失、轮次口径修复、静默归因空值化、llm_stats 稳定；但遗留 6 个问题，其中 2 个 P0 级（批次顺序不一致、空 user_id 污染认知矩阵），且黑洞消失是批次位置轮转的偶然结果，并非末位偏置已修复。

---

## 二、本轮改进验证（相对前四轮）

### 1. agent:0 认知黑洞消失 ✅

topic_report.md 核对结果为 **8 组双向认知**：

```
agent:0 ↔ agent:1 / agent:2 / agent:3 / agent:4
agent:1 ↔ agent:4
agent:2 ↔ agent:3 / agent:4
agent:3 ↔ agent:4
```

对比上一轮 5a30r 只有 6 组（agent:0 黑洞，仅 2 条单向认知）。agent:4 不再是认知黑洞，且在 round 4 后才首次 reply（`reply_count: {0:8, 1:8, 2:8, 3:6, 4:5}`）。

**注意**：黑洞消失是**偶然**——由批次位置轮转使 agent:0 落在末位而被看见，末位偏置机制本身未修复（证据见问题 P1-5）。

### 2. rounds_metric 新字段，轮次口径修复 ✅

evolution.json 新增 `rounds_metric: "processed_batches"`，本轮 `rounds=10`。此前 5a40r_api（60/16/40 互相冲突）、5a40r_v2（60/49）、5a30r（60/30/11/30）的轮次计数混乱问题得到统一口径。

### 3. topic_ended 显式标记 ✅

- `topic_ended=true`，`agent_speech_count=30` 与批次统计一致。
- events.jsonl 中 `topic_end` 消息以 `priority=10` 抢占批次末位，`topic_ended` 事件在 11:24:22.862 触发。
- 对比 5a30r 在 topic_ended 后 round_11 出现 5 条幽灵发言——本轮无整轮幽灵轮次，但仍有 5 条 reply 未入队（见问题 P1-3）。

### 4. 静默归因空值化，兜底污染消除 ✅

静默记录的 `user_id=""` 不再兜底取批次末项。n3_25r（全指 agent:2）、5a40r（批次末尾）、5a40r_v2（round_13 全指 userB）的静默归因污染在数据源头被切断。

### 5. llm_stats 统计链路稳定 ✅

`total=62`（子进程 57 + 平台直连 5），`per_agent: {0:14, 1:14, 2:14, 3:8, 4:7}`。对比 5a40r_api 的 total=5 严重损坏，统计链路已修复并稳定两轮。

### 6. error_count 干净 ✅

`error_count={}`，无 402 欠费错误、无 API 静默吞错。对比 5a40r_v2 静默占比被污染至 84%（实际 17.8%）。

---

## 三、数据核对明细

### 3.1 发言与静默统计（evolution.json）

| 维度 | 值 |
|---|---|
| reply_count | {0:8, 1:8, 2:8, 3:6, 4:5} = **35 条** |
| silent_count | {0:2, 1:2, 2:2} = 6 条（3 个智能体各 2 次，agent:3/4 无静默） |
| error_count | {} |
| agent_speech_count | 30 |

### 3.2 decisions 与 events 一致性

- decisions.jsonl 共 41 条（round 1-10），包含 35 reply + 6 silent。
- events.jsonl 共 173 条：每轮先 5 个并发 `speech_requested`，再 `speech_output_started` 串行输出。
- **不一致点**：reply 35 条 vs events 入队 30 条（见问题 P1-3）。

### 3.3 认知内容特征

- agent:0 的 other_cognition 出现 `""` 空键污染（见问题 P0-2）。
- agent:1 mood 0.05 → 0.0452（缓慢衰减，情绪通道在动）。
- 互认认知内容形成意象链（水 / 桥 / 笔记本），说明主题内认知在积累。

---

## 四、遗留问题明细

### P0-1 decisions/events 批次顺序不一致

- **证据**：decisions 的 `batch_context` 顺序为 `[agent:1,2,3,4,0]`，events 的 `batch_dispatched` 顺序为 `[agent:0,1,2,3,4]`，两处记录同批次成员但顺序不同。
- **影响**：末位偏置分析依赖"谁在批次末尾"，顺序来源不一致会动摇所有末位偏置结论的基础。
- **下一步**：核对 batch_context 顺序的写入来源，统一从平台调度器取唯一事实源。

### P0-2 空 user_id 认知对象污染 other_cognition

- **证据**：round_2_agent_0 的 reply 记录 `user_id=""` 且回应对象为 agent:0 自己，导致 agent:0 的 other_cognition 出现 `""` 键。
- **影响**：空键会进入认知矩阵统计，污染双向认知组数、网络演化分析。
- **下一步**：reply 侧同样加 user_id 空值兜底/过滤；平台在派发时显式注入发送者 id，禁止模型自行决定。

### P1-3 reply 35 条 vs events 入队 30 条不一致

- **证据**：round_9 / round_10 共 5 条 reply 在 topic_ended 触发后生成但**未入队**（decisions 有记录，events 无对应派发）。
- **影响**：topic_ended 后的"幽灵生成"未彻底根除——上轮是整轮幽灵发言，本轮收敛为 5 条未入队记录；统计口径（35 vs 30）仍互相打架。
- **下一步**：topic_ended 后立即熔断新 reply 生成，或入队时统一以 events 为准并在 decisions 打标。

### P1-4 round_9_agent_1 输出截断

- **证据**：round_9_agent_1 的 reply 内容止于 `agent:2 这句"谁先慢下来` 半句，想法 / user_id / 回应对象字段全空。
- **影响**：截断记录既丢内容又丢归因，且可能连带触发 P0-2 形态的空字段。
- **下一步**：对截断输出做长度校验 + 重试/重采样，或在 decisions 写入前校验完整性。

### P1-5 末位偏置仍在，黑洞消失是偶然

五轮实验连续复现的末位偏置，本轮批次级证据：

| 轮次 | 批次成员 | 全员回应对象 |
|---|---|---|
| round_4 | [agent:0, 1, 4, 2] | agent:2（末位） |
| round_5 | [agent:0, 3] | agent:3（末位） |
| round_6 | [agent:0, 1, 2, 4] | agent:4（末位） |
| round_7 | [agent:1, 2, 3, 0] | agent:0（末位） |
| round_10 | [platform, agent:0] | agent:0（末位） |

**解读**：模型几乎总是回复批次最后一条消息的发送者。本轮 agent:0 黑洞消失，只是因为它在 round_7 恰好排到末位被看见，机制本身未动。**修复方向是回应对象显式判定**（平台解析 @提及 / 明确回复目标，而不是让模型从批次末尾推断）。

### P1-6 人格零漂移（演化阈值未触发）

- **证据**：全部人格向量欧氏距离 0.0000，无任何漂移。
- **原因**：人格演化触发条件为 mood 方差 > 0.15 **或** 30 次交互兜底；而本轮每 agent 仅 5-8 次 reply，兜底阈值远未达到。mood 在动（0.05 → 0.0452）但人格不动，演化管线断裂点坐实（_adjust_vector 未接入多用户批量路径）。

---

## 五、跨实验基础设施演进

| 维度 | n3_25r | 5a40r_api | 5a40r_v2 | 5a30r | 5a30r_v2 |
|---|---|---|---|---|---|
| 智能体/轮数 | 3/25 | 5/40 | 5/40 | 5/30 | 5/30 |
| 双向认知组数 | 1 单向黑洞 | — | 双黑洞(0+1) | 6 | **8** |
| llm_stats | 正常 | total=5 损坏 | total=291 修复 | 62 稳定 | **62 稳定** |
| 静默归因 | 全指 agent:2 | 批次末尾 | round_13 全指 userB | user_id="" | **user_id=""（reply 侧仍漏）** |
| 轮次口径 | — | 60/16/40 冲突 | 60/49 冲突 | 60/30/11/30 | **rounds=10 修复** |
| 错误记录 | — | 未分离 | 402 污染 84% | 干净 | **error_count={} 干净** |
| 幽灵发言 | — | — | — | 5 条(round_11) | 5 条未入队(round_9/10) |

---

## 六、优先级修复建议

### P0（阻塞后续分析）

1. **核对 decisions.batch_context 顺序来源**——统一批次顺序的唯一事实源，末位偏置分析才站得住。
2. **过滤 / 修复 reply 侧空 user_id**——平台在派发时显式注入发送者 id，禁止模型自行决定回应对象，杜绝 `""` 键污染认知矩阵。

### P1（本轮实验质量）

3. **回应对象显式判定**——平台解析 @提及与明确回复目标，从根上消除末位偏置（修复后黑洞自然消失，无需依赖批次位置轮转）。
4. **topic_ended 熔断**——结束后立即停止新 reply 生成，消除 35 vs 30 的口径分歧。
5. **输出完整性校验**——截断检测 + 重试，避免 round_9_agent_1 类半句记录。

### P2（演化能力验证）

6. **降人格演化触发阈值**（30 → 10-12 次交互）或接入 `_adjust_vector` 多用户批量路径——否则 30 轮配置下人格演化永远不会触发，E7 假设（directness 中心收敛）在消息池场景无法验证。

---

## 七、结论

本轮是消息池实验基础设施的分水岭：轮次口径、llm_stats、静默归因、错误分离四项修复全部生效，8 组双向认知首次接近全连通，说明多智能体多用户认知场景已经具备可信的数据底座。但三个结构性短板仍然存在：批次顺序事实源不统一（P0-1）、回应对象仍由模型自由推断（P0-2 / P1-3 同源）、人格演化管线未接入（P1-6）。**下一轮实验前先修 P0 两项 + 回应对象显式判定，否则末位偏置与认知污染会持续稀释数据价值。**
