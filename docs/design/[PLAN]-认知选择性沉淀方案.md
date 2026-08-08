# [PLAN] 认知选择性沉淀方案（other_cognition 阈值机制）

> 目标目录：`E:\杂项\BNOS_AI_project\docs\design\`
> 提出日期：2026-08-08
> 代码基线：`node_python_aaa_cognition`（v6.6）
> 关联方案：消息池与弹幕式消息处理方案、数据采集价值清单与方案（P0-2 静默认知更新）

---

## 一、问题定义

当前 other_cognition 的写入是"LLM 输出即 INSERT"（db.py:588-597），无去重、无重要性过滤、无频次阈值。认知对象的选择完全由 LLM 决定，而 prompt 只要求写"对当前对话对象"的认知（prompt.py:55），该对象又锚定在回应对象上（main.py:254-262 归因逻辑）。结果是：

1. 认知覆盖高度选择性，但选择因子是**批次位置**（末位偏置），不是认知价值。
2. "0 认知"无法区分两种含义：**没被评估**（结构性缺口）与**评估后不够格**（真正的稀疏性）。
3. 感知层（user_messages / event_summary）全量记录了所有消息，认知层只沉淀了回应对象的——中间缺一个显式的评估环节。

本方案的目标：把"认知由 LLM 自由选"改为"平台驱动全量评估 + 阈值沉淀"，让 0 认知变成可解释的过滤结果。

## 二、设计原则

1. **反锚定**：评估对象由平台注入（批次发言者全名单），不由 LLM 自选——评估环节必须脱离回应对象与批次位置。
2. **显式候选区**：未达沉淀阈值的信息先进入候选区，带显著性分数与出现频次，随轮次强化或衰减。候选区是"评估过但未沉淀"的唯一事实记录。
3. **复用现有机制**：long_term_memory 的 importance + decay_date（`_calc_decay_date`）、event_summary 的 `_dedup_and_merge` 都已存在，认知巩固与衰减直接复用同一套模式。
4. **兼容 1 对 1**：GUI 单用户路径不改变行为（user_id 恒为用户、直接沉淀），本方案只作用于消息池批量路径。

## 三、管线设计

### 阶段 A：全量评估（感知 → 评估）

**平台侧**：批量派发时，在 ctx 注入 `batch_speaker_list`（本轮批次内所有发言者去重名单，如 `agent:1, agent:2, agent:3`）。

**Prompt 侧**：新增【认知评估】节，替代/扩展现有【他人认知】的评估职责：

```
【认知评估】
对上方消息中出现的每位发言者（包括你不打算回应的），逐行输出：
发言者名 | 显著性分(0-1) | 一句话要点（具体言行，禁止"用户"二字）
判断标准：信息量是否新增、是否与你的已有认知相关、情绪或话题强度。
若你认为某位发言者本轮没有值得记住的内容，也必须输出该行（显著性 0.1-0.3）。
即使你选择静默（自然回复留空），此节也必须输出——你不说话时也在评估在场的人。
```

要点：**全员必评**（包括不回应的人、包括静默时），显著性分数强制给出，让"没评估"在结构上不可能发生。

**写入侧**：解析【认知评估】节后，逐行 upsert 到候选区（见阶段 B）。【他人认知】节保留，但语义收窄为"仅对沉淀对象的一句话总结"，不再承担评估职责。

### 阶段 B：候选区与沉淀判定（评估 → 沉淀）

新表 `candidate_cognition`：

```sql
CREATE TABLE IF NOT EXISTS candidate_cognition(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT, identity_key TEXT,
    target_user_id TEXT,            -- 被评估的发言者
    salience REAL,                  -- 最近一次显著性分
    peak_salience REAL,             -- 历史最高显著性分
    hit_count INTEGER DEFAULT 1,    -- 被评估（出现）次数
    content TEXT,                   -- 最近一次要点
    last_seen_at TEXT, created_at TEXT, updated_at TEXT
);
```

判定规则（写入路径从"LLM 输出即 INSERT"改为"候选区判定后 INSERT"）：

| 条件 | 动作 |
|---|---|
| 单次 `salience ≥ 0.75` | 直接沉淀 → other_cognition，importance 取 salience×5 四舍五入 |
| `hit_count ≥ 3` 且平均 salience ≥ 0.4 | 沉淀（重复出现强化，即使单次不突出） |
| 上述都不满足 | 留在候选区：`hit_count+1`、`peak_salience` 取历史最大、更新 `content` |
| 候选条目 10 轮未见（last_seen_at 超期） | 标记 `expired`（不删除，供事后分析"被过滤掉的"） |

沉淀写入 other_cognition 时，内容带上前缀如 `[显著性0.8] agent:1 每次都用植物比喻...`，保留评估痕迹。沉淀后 `_increment_certainty("other_cognition", conn)` 照常调用（语义从"写入次数"变为"沉淀次数"，计数器继续向上兼容）。

### 阶段 C：巩固与衰减（沉淀 → 记忆）

1. other_cognition 加两列：`importance REAL DEFAULT 3`、`decay_date TEXT`（复用 `_calc_decay_date(importance)`）。
2. 沉淀时写入 importance 与 decay_date；同一对象的认知再次沉淀时，走 `_dedup_and_merge` 的合并强化路径（importance 提升、decay 延长），避免重复条目堆叠。
3. 检索注入（main.py:555 `g_where_identity_user`）按 importance 降序 + 未过期过滤，让"重要且新鲜的认知"优先进入上下文。
4. 过期认知不删除，检索时排除——与分析导出时单独标记，可观察认知的寿命分布。

## 四、改动清单（按文件）

| 文件 | 改动 |
|---|---|
| `db.py` | 新增 `candidate_cognition` 建表；`other_cognition` 加 importance/decay_date/salience 列；`write_parsed_async` 增加候选区写入分支（`skip_empty_other=True` 路径）；新增 `_consolidate_cognition()` 判定函数 |
| `prompt.py` | 新增【认知评估】节模板（批量模式渲染，1 对 1 不渲染）；`batch_speaker_list` 占位符 |
| `main.py` | 批量模式解析【认知评估】节 → 写入候选区；调用 `_consolidate_cognition()` 判定沉淀；`_gather_context` 注入 `batch_speaker_list`；静默路径（自然回复为空）也执行评估写入 |
| `parser.py` | 解析【认知评估】节（多行 `name|score|text` 格式） |
| `message_pool_test` 平台 | 批派发时把 sender 去重名单传入 ctx（与 batch_items 同源） |

## 五、实现顺序（每步可独立验证）

1. **Step 1（评估闭环）**：schema + 候选表 + 【认知评估】节 + 平台注入名单。跑一轮消息池实验，检查候选区质量：显著性分布是否拉开、是否覆盖批次全员、静默时是否也在评估。此步不改变 other_cognition 行为。
2. **Step 2（判定生效）**：沉淀判定接入写入路径。跑一轮，核对沉淀对象的分布是否脱离位置锚定（对照 5a30r：agent:0 的沉淀率应从 0 回升到与其消息显著性匹配的水平）。
3. **Step 3（巩固衰减）**：importance/decay 生效 + 检索排序。长跑观察认知条目寿命与强化路径。
4. **Step 4（导出与指标）**：topic_report 增加候选 vs 沉淀统计、评估-沉淀转换率、0 认知分解（没评估 / 评估未达标 / 已过期）。

## 六、验证指标

| 指标 | 目标 | 对应问题 |
|---|---|---|
| 评估覆盖率（批次全员中被评估比例） | 100% | 结构性缺口是否消除 |
| 位置独立性（同一发言者在首位/末位的沉淀率差） | 显著缩小 | 末位偏置是否退出认知环节 |
| 沉淀率-显著性相关性 | salience 高分组沉淀率 > 低分组 | 选择性是否真实成立 |
| 0 认知可解释率（候选区能追溯的比例） | 接近 100% | "0 认知"是否有据可查 |
| 静默轮次候选写入率 | > 0 | 静默期间后台评估是否发生（P0-2 采集项落地） |

## 七、边界与风险

1. **Token 成本**：每轮新增评估节约 60-120 tokens（6 条消息 × 每行约 15-20 tokens），30 轮约增加 2-4 千 tokens，可忽略。
2. **评估质量依赖 LLM**：显著性分数是模型主观输出，存在噪声。缓解：`peak_salience` 与 `hit_count` 双通道（单次高分或多次出现都触发），不依赖单次分数；后续可用"该对象是否被其他 agent 引用"作为外部校验。
3. **候选表膨胀**：`expired` 标记而不是删除，长时间运行会积累。缓解：分析导出时按 conversation_id + identity_key 过滤，过期条目可归档清理（保留计数即可）。
4. **与实验 B 的关系**：本方案改的是认知沉淀路径，不碰人格向量注入路径，实验 B（漂移→输出验证）不受影响，可并行推进。

## 八、与既有计划的衔接

- 数据采集清单 P0-2（静默期间认知更新）：【认知评估】节静默必输出，让"后台 listen 是否发生"首次有结构化记录。
- 消息池方案（弹幕式消息处理）：评估环节可视为弹幕的"后台处理"动作，与"接收消息后处理不一定要发言"的机制同源。
- 修复验证轮（5a30r 基线）：Step 1 可与基础设施修复（批次顺序、空 user_id）同批上线，一次实验同时验证两件事。
