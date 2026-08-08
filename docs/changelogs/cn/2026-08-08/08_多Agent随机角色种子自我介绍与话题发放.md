# 多 Agent 随机角色种子、自我介绍与话题发放

## 问题描述

多 Agent 实验启动时，所有 Agent 使用同一个固定角色种子
（`{"warmth":0.6, "playfulness":0.4, "directness":0.5, "curiosity":0.5}`），
初始设定无差异化；启动后直接进入弹幕循环，没有"Agent 自我介绍"阶段；
平台也缺少"发放话题"机制，实验话题无法便捷更换。

## 根因分析

- `init_character` 硬编码固定种子，`run_pool_experiment.py` 创建 Agent 时未随机化。
- 平台只有 `inject()`（用户弹幕入池）与 `step()`（批量派发），无"广播自我介绍"与
  "发放话题"两类初始化阶段接口。
- 话题无任何配置途径（命令行参数 / 配置文件均不存在）。
- 附带发现：`init_character` 在新建空库上直接调用 `save_personality`，而该函数只
  INSERT 不建表，导致新建库的 `personality_seed` 表实际为空（写入静默失败、返回 False 被忽略）。

## 修改方案

### 1. 平台初始化阶段接口 `platform_runner.py`

- `record_speech(agent_id, content, stage=...)`：记录一条 Agent 发言到聊天历史
  （**不入消息池**，用于自我介绍等初始化展示）。
- `announce(content, role="topic", user_id="platform", priority=5, enqueue=True)`：
  平台发放话题/公告——默认注入消息池（下一轮 `step()` 中所有 Agent 感知并围绕展开）
  并记录聊天历史（role=topic）；`enqueue=False` 时只记录不注入。

### 2. 聊天历史渲染支持新角色 `data_export.py`

- `render_chat_history_md` 支持 `role=topic`（"平台话题"行）与 `role=agent` 的
  `stage` 标注（如 `（self_intro）`）。

### 3. 启动脚本初始化流程 `run_pool_experiment.py`

- `random_seed(rng)`：随机生成四维性格向量（0.1~0.9）+ 从 6 种说话风格池随机抽取，
  注入 `personality_seed` 表（preset_name="随机种子"）。
- `--seed INT`：固定随机种子可复现同一批角色设定（默认 None=每次随机）。
- `build_intro_prompt` / `gen_self_intro`：基于角色种子构造自我介绍 prompt 并调 LLM 生成，
  通过 `plat.record_speech(..., stage="self_intro")` 广播到聊天历史。
- `resolve_topic(args)`：话题优先级 `--topic 文本` > `--topic-file`（默认
  `tests/message_pool/topic.txt`）> 内置默认；通过 `plat.announce(topic)` 发放。
- 修复 `init_character`：先 `db.ensure(db_path)` 建表（幂等）再 `save_personality`。
- `_run_meta.json` 记录 `seed` 与 `topic`；启动打印每个 Agent 的随机种子与风格。

### 4. 默认话题文件 `topic.txt`（新增）

- 修改文件内容即可更换下次实验话题（重启实验时生效）；或用 `--topic` 直接传。

### 5. 验收测试 `infra_acceptance_test.py`

- 集成部分新增 3 项：自我介绍记录（stage=self_intro）、话题记录（role=topic +
  platform）、话题注入消息池；user_messages 归属断言调整为含 platform 话题
  （33 → 36 项）。

## 影响范围

| 文件 | 改动 |
|------|------|
| `tests/message_pool/run_pool_experiment.py` | 随机角色种子（--seed）、自我介绍阶段、话题发放（--topic/--topic-file）、init_character 修复 ensure 建表 |
| `tests/message_pool/platform_runner.py` | 新增 `record_speech` / `announce` |
| `tests/message_pool/data_export.py` | 聊天历史 md 渲染支持 role=topic 与 stage 标注 |
| `tests/message_pool/topic.txt` | 新增：默认话题文件（改文件换话题） |
| `tests/message_pool/infra_acceptance_test.py` | 新增初始化阶段 3 项断言（33→36） |
| `tests/message_pool/README.md` | 启动流程（随机种子/自我介绍/话题）、新参数、topic.txt 说明 |

## 验证方法

- `infra_acceptance_test.py` 36 项全通过。
- `run_pool_experiment.py --agents 3 --rounds 2 --fake-llm --seed 42` 冒烟跑通：
  - 3 个 Agent 随机种子各不相同（如 warmth 0.61 / 0.18 / 0.12），且 `personality_seed`
    表正确落盘（修复前为空）。
  - `chat_history.jsonl` 按序含 3 条 self_intro + 1 条 topic（user_id=platform）+ 弹幕 + 广播。
  - `_run_meta.json` 记录 seed=42 与 topic；14 张表导出与 md 渲染正常。
