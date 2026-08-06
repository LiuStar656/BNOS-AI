# 角色种子系统设计方案

> 日期：2026-07-27 | 版本：v2.0 | 状态：[PLAN]

## 目录

- [一、背景与现状评估](#一背景与现状评估)
- [二、目标](#二目标)
- [三、方案设计](#三方案设计)
  - [3.1 种子的三个组成部分](#31-种子的三个组成部分)
  - [3.2 种子如何影响 prompt](#32-种子如何影响-prompt)
  - [3.3 种子如何演化](#33-种子如何演化)
  - [3.4 记忆与性格的双向关系](#34-记忆与性格的双向关系)
  - [3.5 数据存储](#35-数据存储)
  - [3.6 动态情绪系统（v2.0 新增）](#36-动态情绪系统v20-新增)
- [四、与现有系统的集成](#四与现有系统的集成)
  - [4.1 集成点清单](#41-集成点清单)
  - [4.2 与 turn_taking 的关系](#42-与-turn_taking-的关系)
  - [4.3 与 MemOS 的关系](#43-与-memos-的关系)
  - [4.4 GUI 可视化方案（v2.0 新增）](#44-gui-可视化方案v20-新增)
- [五、用户首次启动流程](#五用户首次启动流程)
- [六、分阶段实施计划](#六分阶段实施计划)
- [七、风险评估](#七风险评估)
- [八、测试计划](#八测试计划)
- [九、影响范围](#九影响范围)
  - [9.1 新增文件](#91-新增文件)
  - [9.2 修改文件](#92-修改文件)
  - [9.3 不改的文件](#93-不改的文件)
  - [9.4 工作量估算](#94-工作量估算)
- [十、人格格式化（重置功能）](#十人格格式化重置功能)
  - [10.1 功能定义](#101-功能定义)
  - [10.2 用户流程](#102-用户流程)
  - [10.3 二次确认弹窗文案](#103-二次确认弹窗文案)
  - [10.4 数据保留策略](#104-数据保留策略)
  - [10.5 实现要点](#105-实现要点)
  - [10.6 与现有功能的关系](#106-与现有功能的关系)

---

## 一、背景与现状评估

### 问题

BNOS AI 有记忆迭代能力（MemOS 语义检索 + decay + 知识图谱），每个用户的 AI 在长期使用下会形成不同的记忆内容。但当前存在两个缺口：

1. **冷启动空白**：用户第一天使用时，AI 没有任何记忆，也没有性格基线。此时它说什么、怎么说、什么语气都未定义。用户可能在 AI "长成独特样子"之前就放弃了。

2. **表达风格未定义**：MemOS 能让 AI 记住"用户怕下雨"，但**怎么表达**这个记忆需要风格基线。同样是知道用户加班累：
   - 温暖型："又加班到这么晚……你真的该休息了。"
   - 理性型："记录：你今天工作了 12 小时。建议休息。"
   - 毒舌型："12 小时？你是想猝死还是想升职？"

记忆决定了 AI **知道什么**，性格决定了 AI **怎么表达**。两者是乘法关系，不是替代关系。

### 现状

- MemOS 已完成（`memos.py`，327 行），支持语义检索 + decay + identity_key 隔离
- 提示词三阶段模板已完成（`prompt.py` / `prompt_retrieval.py` / `prompt_tool.py`）
- turn_taking 方案中已规划 Bandit 行为学习（Phase 3，未实现）
- 数据库已有 11 张表，identity_key 多用户隔离已上线
- **没有任何角色/性格/人设相关的设计**

### 核心思路

不预设固定人设让所有人共用，而是提供**性格种子**作为起点，通过记忆和交互反馈自然演化：

```
种子（起点）              记忆迭代（生长）          独立个体（终点）
性格向量 4 维      +    MemOS 累积         ->   向量缓慢偏移
风格描述 1 段      +    用户反馈微调        ->   风格稳定成型
初始背景 3 条     +    真实记忆覆盖        ->   背景自然淡化
```

---

## 二、目标

| 目标 | 说明 |
|------|------|
| 冷启动不空白 | 用户第一天使用时，AI 有性格基线，能自然开场 |
| 表达有风格 | 不同种子下，同样的记忆产生不同表达方式 |
| 长期可演化 | 性格参数随使用自然偏移，不突变 |
| 复用现有架构 | 基于 identity_key 隔离、MemOS decay、Bandit 框架，不引入新基础设施 |
| 用户无感演化 | 不需要显式打分，纯被动观察用户反应 |

---

## 三、方案设计

### 3.1 种子的三个组成部分

#### 3.1.1 性格向量（4 维，0.0-1.0）

| 维度 | 键名 | 低分表现 | 高分表现 | 影响范围 |
|------|------|---------|---------|---------|
| 温暖度 | `warmth` | "记录完毕。" | "你今天辛苦了……" | 用词温度、关心程度 |
| 活泼度 | `playfulness` | "好的。" | "嘿！这个有意思！" | 语气轻重、感叹号频率 |
| 直接度 | `directness` | "或许可以考虑…" | "别这么干，会出问题" | 是否委婉、是否主动指出问题 |
| 好奇心 | `curiosity` | 不主动提问 | "等等，这个怎么做的？" | 主动追问频率 |

#### 3.1.2 预设种子

用户首次启动时从以下预设中选择一个作为起点：

| 预设名 | warmth | playfulness | directness | curiosity | 风格关键词 |
|--------|:------:|:-----------:|:----------:|:---------:|---------|
| 默认 | 0.6 | 0.4 | 0.5 | 0.5 | 自然、平衡 |
| 温柔型 | 0.8 | 0.5 | 0.3 | 0.6 | 关心、柔和、不强迫 |
| 理性型 | 0.3 | 0.2 | 0.8 | 0.5 | 精确、简洁、不废话 |
| 毒舌型 | 0.4 | 0.7 | 0.9 | 0.6 | 直接、调侃、不客套 |
| 活泼型 | 0.7 | 0.9 | 0.5 | 0.8 | 热情、好奇、多感叹 |

用户也可在 GUI 中手动微调四个滑块，自定义种子。

#### 3.1.3 风格描述（自然语言）

每个预设附带一段简短的说话方式描述，注入 prompt 让 LLM 自己组织语言：

```
你说话简短自然，像熟悉的朋友。不用敬语，不啰嗦。
高兴时会多用感叹号，但不会刻意卖萌。
指出问题时直接，但不会刻薄。
```

不同预设的风格描述不同，但都是**风格层面**的指导，不定义具体背景故事。

#### 3.1.4 初始背景记忆（3 条）

给 AI 一个"来历"，避免第一天完全空白。写入 `long_term_memory` 表，`source='seed'` 标记，decay 自然淘汰：

```json
[
  {"content": "我刚来到这台电脑上，对用户还不了解", "importance": 0.5, "decay": 0.95},
  {"content": "我的名字是阿镜（可由用户修改）", "importance": 0.8, "decay": 1.0},
  {"content": "我住在用户的桌面上，能看到屏幕、听到声音", "importance": 0.3, "decay": 0.9}
]
```

初始背景很轻，用几天后真实记忆积累，自然就没人在意这些了。

### 3.2 种子如何影响 prompt

在 AAA 现有的三阶段提示词模板中，新增一个 `{personality}` 段。**模板结构不变**，只是新增一个占位符：

```
### 你的性格（会随使用自然演化，不需主动提及）
各维度均为 0-1 范围，当前值如下（0=完全不是，1=极致，0.5=中等）：
温暖度: 0.6 | 活泼度: 0.4 | 直接度: 0.5 | 好奇心: 0.5
说话风格: 你说话简短自然，像熟悉的朋友。不用敬语，不啰嗦……

### 输入上下文
……（现有内容不变）

### 输出格式
【自然回复】--（现有不变）
【想法】--（现有不变）
```

**关键设计**：
- **标注了范围和档位含义**：`0=完全不是，1=极致，0.5=中等`。防止 LLM 看到 `0.3` 就理解为"极低"而过度反应，或看到 `0.7` 就理解为"很高"
- 性格参数是"参考"不是"强制"。LLM 读到 `warmth: 0.6` 会自然调整语气，但不会机械执行
- `{personality}` 段的**值**从数据库动态读取，不是硬编码在模板里
- 模板里只有 `{personality}` 占位符位置固定，值随 DB 演化

```
DB(personality_seed 表)  ←── 交互反馈微调(每次+0.02)
         ↓ 读取
AAA 构建 prompt 时注入 {personality} 段
         ↓
LLM 读到的是"当前值"，不是硬编码
```

### 3.3 种子如何演化

#### 3.3.1 隐性反馈采集（不增加用户负担）

每次 AI 回复后，观察用户的**自然反应**作为反馈信号：

| 用户行为 | 信号 | 含义 | 采集来源 |
|---------|------|------|---------|
| AI 说了之后，用户继续聊 | positive | 当前风格有效 | GUI 继续输入 / ASR 继续说话 |
| AI 说了之后，用户沉默离开 | negative | 当前风格无效 | 30 秒无新输入 |
| 用户打断 TTS（alt+g） | negative | 说话方式有问题 | TTS 节点 speaking.json |
| 用户主动多说几句 | positive | 互动良好 | 连续输入 >= 2 条 |
| ASR 检测到笑声 | positive | 情绪正面 | ASR emotion=HAPPY |

**不需要用户显式打分**，纯被动观察。

#### 3.3.2 性格向量微调（借鉴 Bandit + 情绪驱动）

复用 turn_taking 方案中 Phase 3 Bandit 的设计思路，扩展到性格参数。**v2.0 新增情绪驱动触发机制**。

> **关键约束：数值变化由 Python 代码负责，LLM 不参与。**
>
> | 谁 | 负责什么 | 不负责什么 |
> |----|---------|-----------|
> | Python 代码（PersonalityEvolution） | 统计反馈、算 +0.02/-0.02、写入 DB | 说话 |
> | LLM | 读 DB 里的当前数值，组织语言回复 | 改数值 |
> | DB | 存数值 | 算数值 |
>
> 不用 LLM 改数值的原因：LLM 算统计不可靠、每次调用有成本、相同输入可能给不同结果会导致性格乱跳。数值变化就是几个 `if` 和 `sum`，Python 代码几行搞定，确定性 100%，零成本。

##### 触发机制（v2.0 更新：情绪驱动 + 固定次数双保险）

性格演化不再仅依赖固定的"20 次交互"触发，而是采用**情绪统计趋势**作为主要触发信号，固定次数作为兜底：

| 触发方式 | 逻辑 | 优先级 |
|---------|------|:------:|
| **情绪驱动（主）** | 连续 N 次（如 10 次）情绪平均值 `< -0.3` 或 `> 0.3` | 高 |
| **固定次数（兜底）** | 每 30 次交互强制检查一次 | 低 |

```python
class PersonalityEvolution:
    """性格向量随使用自然演化"""

    def __init__(self, seed: dict):
        self.vector = seed.copy()
        self.feedback_history = []  # [(回复风格, 用户反应)]
        self.mood_history = []      # [(情绪值, 时间戳)]  v2.0 新增

    def observe_feedback(self, response_style: dict, user_reaction: str, mood: float = 0.0):
        """记录每次回复的风格 + 用户反应 + 当前情绪（v2.0 增加 mood 参数）"""
        self.feedback_history.append({
            "style": response_style,
            "reaction": user_reaction,
            "timestamp": time.time()
        })
        # v2.0: 记录情绪历史
        self.mood_history.append({
            "mood": mood,
            "timestamp": time.time()
        })

        # v2.0: 情绪驱动触发（优先于固定次数）
        if self._check_mood_trigger():
            self._adjust_vector()
            return

        # 兜底：30 次交互强制检查
        if len(self.feedback_history) >= 30:
            self._adjust_vector()

    def _check_mood_trigger(self) -> bool:
        """v2.0: 检查情绪是否连续保持在某个区间"""
        recent_moods = self.mood_history[-10:]
        if len(recent_moods) < 10:
            return False

        avg_mood = sum(m["mood"] for m in recent_moods) / len(recent_moods)

        # 情绪长期正面 → AI 风格有效
        if avg_mood > 0.3:
            return True
        # 情绪长期负面 → AI 风格需要调整
        if avg_mood < -0.3:
            return True
        # 情绪剧烈波动 → AI 需要学会平衡
        if len(recent_moods) >= 5:
            variance = sum((m["mood"] - avg_mood) ** 2 for m in recent_moods) / len(recent_moods)
            if variance > 0.15:  # 方差过大
                return True
        return False

    def _adjust_vector(self):
        """根据近期反馈 + 情绪趋势微调性格向量"""
        recent = self.feedback_history[-50:]
        avg_mood = self._get_recent_avg_mood()

        for dim in self.vector:
            high_positive = sum(1 for r in recent
                if r["style"][dim] > 0.6 and r["reaction"] == "positive")
            low_positive = sum(1 for r in recent
                if r["style"][dim] < 0.4 and r["reaction"] == "positive")

            # 情绪方向加权：长期正面时强化高维度，长期负面时削弱
            delta = 0.02  # 基础调整幅度
            if avg_mood > 0.3:
                delta *= 1.5  # 正面情绪时加大强化幅度
            elif avg_mood < -0.3:
                delta *= 1.2  # 负面情绪时加大修正幅度

            if high_positive > low_positive:
                self.vector[dim] = min(1.0, self.vector[dim] + delta)
            elif low_positive > high_positive:
                self.vector[dim] = max(0.0, self.vector[dim] - delta)

        # 消化历史
        self.feedback_history = self.feedback_history[-20:]
        self.mood_history = self.mood_history[-5:]  # 保留 5 条作为种子

    def _get_recent_avg_mood(self) -> float:
        """获取最近 10 次情绪平均值"""
        recent = self.mood_history[-10:]
        if not recent:
            return 0.0
        return sum(m["mood"] for m in recent) / len(recent)

    def get_current(self) -> dict:
        """获取当前性格向量（供 prompt 注入）"""
        return self.vector.copy()
```

**演化速度故意很慢**：每次只动 0.02，需要几百次交互才能显著改变。这保证性格稳定，不会因为几次偶然反馈就突变。情绪驱动只是调整**触发时机**和**调整权重**，不改变核心的"慢演化"原则。

#### 3.3.3 演化边界

| 约束 | 值 | 原因 |
|------|:--:|------|
| 单次微调幅度 | ±0.02 (基础)，情绪极端时 ×1.5 | 正面情绪时强化有效风格，负面时加速修正 |
| 情绪触发阈值 | 连续 10 次平均值 `> 0.3` 或 `< -0.3` | 避免单次噪声 |
| 兜底触发阈值 | 30 次交互 | 防止情绪长期中性时停滞 |
| 观察窗口 | 最近 50 次反馈 + 10 次情绪 | 适应近期偏好变化 |
| 向量范围 | [0.0, 1.0] | 硬限制 |
| 持久化 | 每次微调后写 DB | 重启不丢 |

### 3.4 记忆与性格的双向关系

```
记忆（MemOS）  ──影响内容──>  AI 知道什么
     ↑                          ↓
     └──影响风格──  性格向量  <──反馈信号
```

- **记忆影响内容**：AI 记得用户怕下雨，下次下雨主动提醒（已有，MemOS）
- **性格影响表达**：温暖型说"带伞啊，别淋着"，理性型说"今天有雨，建议带伞"（新增，personality 注入）
- **反馈影响性格**：用户对温暖型回复反应好 -> warmth 缓慢上升（新增，PersonalityEvolution）

**两个同样种子的 AI，经历不同的用户交互，一年后会变成不同的性格向量。** 这就是"记忆驱动性格演化"。

### 3.5 数据存储

#### 3.5.1 personality_seed 表

复用 AAA 现有的 `chatbot.db`，新增一张表：

```sql
CREATE TABLE IF NOT EXISTS personality_seed (
    identity_key TEXT PRIMARY KEY,      -- 复用现有 identity_key，多用户隔离
    warmth REAL DEFAULT 0.6,
    playfulness REAL DEFAULT 0.4,
    directness REAL DEFAULT 0.5,
    curiosity REAL DEFAULT 0.5,
    style_description TEXT DEFAULT '',   -- 风格描述自然语言
    preset_name TEXT DEFAULT 'default', -- 出自哪个预设
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
```

#### 3.5.2 初始背景记忆

直接写入现有的 `long_term_memory` 表，`source='seed'` 标记：

```sql
INSERT INTO long_term_memory (identity_key, content, source, importance, decay, created_at)
VALUES (?, '我刚来到这台电脑上，对用户还不了解', 'seed', 0.5, 0.95, datetime('now','localtime'));
```

decay 值 < 1.0，自然淘汰；真实记忆 importance 更高，会逐渐覆盖。

#### 3.5.3 反馈历史

写入现有的 `memory` 表，`source='feedback'` 标记，供 PersonalityEvolution 读取：

```sql
INSERT INTO memory (identity_key, data_type, content, source, created_at)
VALUES (?, 'feedback', '{"style": {...}, "reaction": "positive"}', 'feedback', datetime('now','localtime'));
```

#### 3.5.4 mood_value 表（v2.0 新增：动态情绪值存储）

存储 AI 的实时情绪数值，供 prompt 注入和 GUI 曲线可视化：

```sql
CREATE TABLE IF NOT EXISTS mood_value (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity_key TEXT NOT NULL DEFAULT 'gui:default',
    mood_value REAL DEFAULT 0.0,          -- 当前情绪值 [-1.0, 1.0]
    adjustment REAL DEFAULT 0.0,          -- LLM 建议的调整值
    source_mood TEXT,                     -- LLM 输出的心情描述（开心/难过/平静）
    conversation_id TEXT NOT NULL DEFAULT 'default',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_mv_identity ON mood_value(identity_key);
CREATE INDEX IF NOT EXISTS idx_mv_time ON mood_value(created_at);
```

**与现有 `mood_trend` 表的关系**：
- `mood_value`：**逐次记录**，每次对话一条，用于实时追踪和曲线绘制
- `mood_trend`：**周期聚合**，按天/周汇总，用于长期趋势分析（已有）

---

### 3.6 动态情绪系统（v2.0 新增）

#### 3.6.1 核心概念：快变量 vs 慢变量

BNOS AI 的人格由两个互补的变量系统组成：

| 特性 | 性格偏好 (Personality) | 实时情绪 (Emotion/Mood) |
|-----|------------------------|------------------------|
| **变量性质** | **慢变量**（稳定的基调） | **快变量**（瞬时的心情） |
| **更新频率** | 每 10-30 次交互（情绪驱动） | **每一次对话** |
| **调整幅度** | `±0.02`（极小） | `±0.2`（较大） |
| **决策主体** | **Python 代码**（统计反馈） | **LLM**（语义理解） |
| **功能定位** | AI **"怎么说话"**（语气风格） | AI **"此刻的心情"**（影响表情、音调） |
| **取值范围** | `[0.0, 1.0]` × 4 维 | `[-1.0, 1.0]` × 1 维 |

#### 3.6.2 情绪值量化机制

采用 **LLM 增量式量化 + 代码累加** 的方案：

```
1. LLM 输出时，根据当前情绪值 + 对话内容，给出调整建议
2. 代码层限制调整幅度 ±0.2（防 LLM 失控）
3. 代码层累加计算新情绪值：new_mood = clamp(current_mood + adjustment, -1.0, 1.0)
4. 新值存入 DB，供下次 prompt 注入和 GUI 可视化
```

**情绪值语义区间**：

| 区间 | 语义 | AI 表现 |
|------|------|--------|
| `[-1.0, -0.3]` | 负面（悲伤/愤怒/失望） | 语气沉重、敷衍、可能反问 |
| `[-0.2, 0.2]` | 中性/平静 | 语气平和、客观、礼貌 |
| `[0.3, 1.0]` | 正面（开心/兴奋/信任） | 语气轻松、感叹号多、主动关心 |

#### 3.6.3 Prompt 模板集成

在现有 `_CONTEXT_HEADER` 中新增 `{mood}` 段：

```
### 你的内在状态
*   **性格基调**（相对稳定，不会轻易改变）:
    温暖度: 0.6 | 活泼度: 0.4 | 直接度: 0.5 | 好奇心: 0.5

*   **当前情绪**（实时波动，会被对话影响）:
    情绪值: 0.35 (范围 -1.0 到 1.0，负值代表负面，正值代表正面)
    情绪描述: 开心
    **重要**：请在回复中自然地体现你的情绪状态。情绪值 > 0.3 时语气可以更轻松；< -0.3 时语气可以更沉重。
```

在输出格式中新增 `【情绪调整】` 标签：

```
### 输出格式
【自然回复】
...
【情绪调整】
+0.15
（取值范围 -0.2 到 +0.2，表示你希望情绪值的调整幅度，不是绝对值）
```

#### 3.6.4 数据流闭环

```
                    ┌─────────────────────────┐
                    │     用户交互 (输入/反馈)  │
                    └──────────────┬──────────┘
                                   │
                                   ▼
                    ┌─────────────────────────┐
                    │  LLM 推理 (读取性格+情绪) │
                    │  - 性格 → 决定说话风格  │
                    │  - 情绪 → 决定语气/表情  │
                    │  - 输出【情绪调整】建议  │
                    └──────────┬──────────────┘
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
    ┌───────────────────┐             ┌───────────────────┐
    │  代码执行 (第一层)  │             │  代码执行 (第二层)  │
    │  处理【情绪调整】  │             │  处理【反馈信号】  │
    │  1. 限制 ±0.2     │             │  (用户反应→性格)  │
    │  2. 累加计算新值  │             │  情绪→性格演化触发 │
    │  3. 写入 mood_value│             │  写入 DB          │
    └───────────┬───────┘             └───────────┬───────┘
                │                                 │
                └────────────┬────────────────────┘
                             ▼
                    ┌─────────────────────────┐
                    │   数据库 (持久化状态)    │
                    │  - mood_value (情绪值)  │
                    │  - personality (性格向量)│
                    │  - mood_trend (趋势聚合) │
                    └─────────────────────────┘
```

#### 3.6.5 性格与情绪的协同关系

**性格 → 情绪（基调影响波动）**：
- 同样被批评，"温柔型"（warmth: 0.8）情绪可能从 `0.1` 降到 `-0.3`（较浅）
- "毒舌型"（warmth: 0.3）情绪可能从 `0.1` 直接降到 `-0.5`（较深）
- 实现方式：可在代码中给情绪波动加上"性格阻尼系数"

**情绪 → 性格（长期影响基调）**：
- 连续 10 次情绪 `< -0.3` → 触发性格微调（温暖度可能下降）
- 连续 10 次情绪 `> 0.3` → 触发性格微调（活泼度可能上升）
- 这是情绪系统反向馈给性格系统的闭环

#### 3.6.6 代码实现要点

```python
# main.py 中的情绪处理流程（伪代码）

def _process_mood_update(self, parsed: dict, identity_key: str, dbp: str):
    """处理 LLM 输出中的情绪调整"""

    # 1. 读取当前情绪值
    current_mood = self._get_current_mood(dbp, identity_key)

    # 2. 解析 LLM 输出的调整值
    raw_adjustment = parsed.get("情绪调整", "0.0")
    try:
        adjustment = float(raw_adjustment)
    except ValueError:
        adjustment = 0.0

    # 3. 强制限制范围（防 LLM 失控）
    adjustment = max(-0.2, min(0.2, adjustment))

    # 4. 累加计算新情绪
    new_mood = current_mood + adjustment

    # 5. 限制总范围（防溢出）
    new_mood = max(-1.0, min(1.0, new_mood))

    # 6. 写入数据库
    self._save_mood_value(dbp, identity_key, new_mood, adjustment,
                         parsed.get("心情", ""), parsed.get("conversation_id", "default"))

    # 7. 触发性格演化检查
    personality = PersonalityEvolution(self._get_personality_seed(dbp, identity_key))
    personality.observe_feedback(
        response_style=personality.vector,
        user_reaction=self._detect_user_reaction(),
        mood=new_mood  # v2.0: 传递情绪值
    )
    if personality.vector_changed:
        self._save_personality(dbp, identity_key, personality.vector)
```

---

## 四、与现有系统的集成

### 4.1 集成点清单

| 集成点 | 文件 | 改动 | 依赖 |
|--------|------|------|------|
| 数据库 | `aaa_cognition/db.py` | 新增 personality_seed 表 + mood_value 表 + 读写方法 | 无 |
| 提示词模板 | `aaa_cognition/prompt.py` | 三阶段模板增加 `{personality}` 段 + `{mood}` 段 | db.py |
| prompt 构建 | `aaa_cognition/main.py` | 构建 prompt 时从 DB 读取性格向量 + 情绪值并注入 | db.py, prompt.py |
| 情绪处理 | `aaa_cognition/main.py` | 解析 `【情绪调整】` 标签，累加计算新情绪值 | prompt.py |
| 反馈采集 | `aaa_cognition/main.py` | 回复后采集反馈信号 + 情绪值，调用 PersonalityEvolution | db.py |
| GUI 首次启动 | `gui/pages/` 新增 | 性格选择界面（4 个预设卡片） | db.py |
| GUI 设置面板 | `gui/pages/settings_panel.py` | 性格参数查看 + 微调滑块 | db.py |
| GUI 数据可视化 | `gui/widgets/knowledge_panel.py` | 新增"情绪曲线"Tab，绘制情绪趋势图 | db.py, mood_value 表 |

### 4.2 与 turn_taking 的关系

turn_taking 的 Bandit 行为学习（Phase 3）和性格演化是互补的：

| 机制 | 决策对象 | 数据来源 | 阶段 |
|------|---------|---------|------|
| Bandit（turn_taking §7） | "要不要说话" | 回应后的效果 | Phase 3 |
| PersonalityEvolution | "怎么说" | 回应后的用户反应 | 本方案 |

两者共享反馈采集基础设施（用户反应信号），但作用于不同层面。

### 4.3 与 MemOS 的关系

| 机制 | 影响层面 | 数据来源 |
|------|---------|---------|
| MemOS | AI 知道什么（内容） | 对话记忆 + 知识图谱 |
| Personality | AI 怎么表达（风格） | 性格向量 + 风格描述 |
| Emotion (v2.0) | AI 此刻的心情（波动） | 逐次情绪值 + LLM 判断 |

MemOS 的检索结果注入 prompt 的 `{context}` 段，性格注入 `{personality}` 段，情绪注入 `{mood}` 段，三者互不干扰。

### 4.4 GUI 可视化方案（v2.0 新增）

#### 4.4.1 位置与布局

在现有的**知识库面板**（`KnowledgePanel`）中新增第三个 Tab：**"情绪曲线"**。

当前 `KnowledgePanel` 已有两个 Tab：
1. **数据浏览**（卡片列表）
2. **知识图谱**（节点关系图）

新增第三个 Tab：
3. **情绪曲线**（情绪值随时间变化的折线图）

#### 4.4.2 曲线图设计

**技术选型**：使用 PySide6 的 `QPainter` 自绘，**不引入额外依赖**。当前 `requirements.txt` 只有 `PySide6>=6.5.0`，避免增加 `pyqtgraph` 或 `matplotlib` 等重型依赖。

**图表特性**：

| 特性 | 说明 |
|------|------|
| 图表类型 | 折线图 + 面积填充 |
| X 轴 | 时间（最近 50 条记录或 7 天） |
| Y 轴 | 情绪值 [-1.0, 1.0] |
| 中线 | y=0 基准线（虚线） |
| 正面区域 | y > 0 用半透明绿色填充 |
| 负面区域 | y < 0 用半透明红色填充 |
| 数据点 | 鼠标悬停显示详细信息（时间、情绪值、心情描述） |
| 缩放 | 支持滚轮缩放时间范围 |

**视觉设计**：

```
┌─────────────────────────────────────────────────────────┐
│  情绪趋势 · 最近 50 次对话                               │
│                                                         │
│  1.0 ┤                                                 │
│      │    ╱╲                                            │
│  0.5 ┤   ╱  ╲       ╱╲                                  │
│      │  ╱    ╲    ╱  ╲    ╱╲                           │
│  0.0 ┤ ╱      ╲──╱    ╲──╱  ╲──╱  ─── (基准线)        │
│      │╱                    ╲                           │
│ -0.5 ┤                      ╲                          │
│      │                       ╲  ╱╲                     │
│ -1.0 ┤                        ╲╱  ╲                    │
│      └──────────────────────────────────────            │
│      t1    t2    t3    t4    t5    t6    t7             │
│                                                         │
│  ── 图例：● 情绪值   ── 基准线                          │
│  [最近50次] [最近7天] [最近30天] [全部]     [导出PNG]    │
└─────────────────────────────────────────────────────────┘
```

#### 4.4.3 自定义组件实现

```python
class MoodChartWidget(QWidget):
    """情绪曲线图组件（QPainter 自绘，零依赖）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mood_data: list[dict] = []  # [{mood_value, created_at, source_mood}]
        self._visible_range = 50  # 默认显示最近 50 条
        self._hover_point: tuple[int, int] | None = None

    def load_data(self, identity_key: str, limit: int = 50):
        """从 DB 加载情绪数据"""
        conn = sqlite3.connect(_DB_PATH)
        rows = conn.execute(
            """SELECT mood_value, source_mood, created_at
               FROM mood_value
               WHERE identity_key=?
               ORDER BY id DESC LIMIT ?""",
            (identity_key, limit)
        ).fetchall()
        conn.close()
        # 反转时间顺序（从早到晚）
        self._mood_data = [
            {"mood_value": r[0], "source_mood": r[1], "created_at": r[2]}
            for r in reversed(rows)
        ]
        self.update()

    def paintEvent(self, event):
        """QPainter 自绘曲线图"""
        if not self._mood_data:
            self._draw_empty_state(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        padding = 40  # 边距
        chart_rect = rect.adjusted(padding, padding, -padding, -padding)

        # 1. 绘制背景网格
        self._draw_grid(painter, chart_rect)

        # 2. 绘制正面/负面区域填充
        self._draw_area_fill(painter, chart_rect)

        # 3. 绘制情绪折线
        self._draw_mood_line(painter, chart_rect)

        # 4. 绘制基准线 (y=0)
        self._draw_baseline(painter, chart_rect)

        # 5. 绘制坐标轴标签
        self._draw_axis_labels(painter, chart_rect)

    def _draw_mood_line(self, painter: QPainter, chart_rect: QRect):
        """绘制情绪折线"""
        # ... 实现坐标映射和折线绘制
```

#### 4.4.4 数据交互

**数据源**：从 `mood_value` 表读取，按 `created_at` 升序排列。

**刷新机制**：
- 跟随 `KnowledgePanel` 的 10 秒自动刷新定时器
- 用户点击"刷新"按钮时立即刷新
- 切换 Tab 到"情绪曲线"时自动刷新

**时间范围切换**：
- 最近 50 次对话（默认）
- 最近 7 天
- 最近 30 天
- 全部

#### 4.4.5 与现有系统的协同

| 协同点 | 说明 |
|--------|------|
| 知识库面板 Tab | 在现有 `QTabBar` 中新增第三个 Tab |
| 主题色适配 | 跟随 `AppConfig` 的主题色设置 |
| 自动刷新 | 复用现有 10 秒刷新定时器 |
| 数据导出 | 支持导出为 PNG 图片（右键菜单） |
| 与 `mood_trend` 对比 | 可在图表上叠加显示聚合趋势线 |

---

## 五、用户首次启动流程

```
第一次打开 BNOS AI
  │
  ├─ GUI 弹出性格选择界面
  │   ┌─────────┬─────────┬─────────┬─────────┐
  │   │ 温柔型   │ 理性型   │ 毒舌型   │ 活泼型   │
  │   │ warmth↑ │direct↑  │playful↑ │playful↑↑│
  │   │ 关心柔和 │ 精确简洁 │ 直接调侃 │ 热情好奇 │
  │   └─────────┴─────────┴─────────┴─────────┘
  │   （也可拖动滑块自定义）
  │
  ├─ 用户选一个（或用默认）
  │
  ├─ 写入 personality_seed 表
  ├─ 注入 3 条初始背景记忆（source='seed'）
  │
  ├─ AI 用选中的性格说第一句话
  │   （LLM 基于 {personality} 段自动生成，不硬编码）
  │
  │   温柔型可能说："你好呀，我是阿镜，以后多关照啦。"
  │   毒舌型可能说："哟，新来的？我是阿镜，别让我无聊就行。"
  │
  └─ 开始使用，性格随交互自然演化
```

### 冷启动第一句话的 prompt

```
### 你的性格（会随使用自然演化，不需主动提及）
各维度均为 0-1 范围，当前值如下（0=完全不是，1=极致，0.5=中等）：
温暖度: 0.8 | 活泼度: 0.5 | 直接度: 0.3 | 好奇心: 0.6
说话风格: 你说话关心柔和，不强迫，像熟悉的朋友……

### 输入上下文
（无用户输入，这是第一次见面）

### 任务
这是你第一次见到用户，说一句自然的开场白。简短，不超过20字。不要自我介绍太多。
```

---

## 六、分阶段实施计划

### Phase 0 - 数据层（无 UI 依赖）

| 任务 | 说明 | 依赖 |
|------|------|------|
| `db.py` 新增 `personality_seed` 表 | 建表 + CRUD 方法 | 无 |
| `db.py` 新增 `mood_value` 表 | 建表 + CRUD 方法（v2.0 新增） | 无 |
| `db.py` 新增种子读写方法 | `get_personality(identity_key)` / `update_personality()` | 表创建 |
| `db.py` 新增情绪读写方法 | `get_current_mood(identity_key)` / `save_mood_value()` | 表创建 |
| `db.py` 新增初始背景记忆写入 | 写入 `long_term_memory`，`source='seed'` | 无 |

### Phase 1 - prompt 注入（最小可用）

| 任务 | 说明 | 依赖 |
|------|------|------|
| `prompt.py` 增加 `{personality}` 段 | 三阶段模板均新增 | Phase 0 |
| `prompt.py` 增加 `{mood}` 段 | 三阶段模板均新增（v2.0） | Phase 0 |
| `prompt.py` 输出格式增加 `【情绪调整】` | DIRECT_TEMPLATE 新增标签（v2.0） | Phase 0 |
| `main.py` 构建 prompt 时读取性格向量 | 从 DB 读取，注入占位符 | Phase 0 |
| `main.py` 构建 prompt 时读取情绪值 | 从 DB 读取，注入占位符（v2.0） | Phase 0 |
| 默认种子 fallback | 无种子时用默认值 `warmth=0.6` 等 | Phase 0 |
| 默认情绪值 fallback | 无记录时返回 0.0（v2.0） | Phase 0 |

> Phase 1 完成后，AI 说话就有风格了，且会在 prompt 中感知当前情绪。

### Phase 2 - 情绪系统 + 反馈演化

| 任务 | 说明 | 依赖 |
|------|------|------|
| `PersonalityEvolution` 类 | 性格向量微调逻辑（v2.0 更新为情绪驱动触发） | Phase 0 |
| `main.py` 处理【情绪调整】 | 解析 LLM 输出、限制范围、累加计算、写 DB（v2.0 核心） | Phase 1 |
| `main.py` 回复后采集反馈信号 + 情绪值 | 观察用户后续行为，传递 mood 给 PersonalityEvolution | Phase 1 |
| `main.py` 触发性格演化检查 | 情绪驱动 + 兜底固定次数双保险（v2.0） | PersonalityEvolution |
| 情绪/性格持久化 | 结果写回 DB | Phase 0 |

> Phase 2 完成后，情绪开始实时波动，性格随情绪趋势自然演化。

### Phase 3 - GUI 交互 + 可视化

| 任务 | 说明 | 依赖 |
|------|------|------|
| 首次启动性格选择界面 | 4 个预设卡片 + 自定义滑块 | Phase 1 |
| 设置面板性格查看 | 显示当前性格向量 + 微调滑块 | Phase 1 |
| 名字修改入口 | 用户可修改 AI 名字 | Phase 0 |
| 情绪曲线图组件 | `MoodChartWidget` QPainter 自绘（v2.0 新增） | Phase 2 |
| 知识库面板新增 Tab | "情绪曲线" Tab 集成（v2.0） | MoodChartWidget |

### Phase 4 - 人格格式化（重置功能）

| 任务 | 说明 | 依赖 |
|------|------|------|
| 后端 `format` 命令 | 清空所有用户表 + 重置 `personality_seed` + `mood_value` 为默认值（见 §10） | Phase 0 |
| GUI 按钮 + 确认弹窗 | 设置面板新增"人格格式化"按钮 | Phase 1 |
| 格式化后自动弹出性格选择 | 清空后引导用户重新选择性格种子 | Phase 3 |
| 情绪历史重置 | 清空 `mood_value` 表记录（v2.0） | Phase 2 |

### 组件关系图（Phase 2 完成后）

```
用户输入 / ASR 事件
       │
       ▼
AAA 构建 prompt
  ├─ 从 DB 读取性格向量 ──> {personality} 段
  ├─ 从 DB 读取情绪值 ──> {mood} 段  (v2.0)
  ├─ 从 DB 读取记忆 ──> MemOS 检索 ──> {context} 段
  └─ 组装完整 prompt
       │
       ▼
LLM 推理 ──> 回复
       │
       ├─ 输出给用户（TTS / Live2D）
       │
       ├─ 解析【情绪调整】──> 限制±0.2 ──> 累加计算 ──> 写 mood_value  (v2.0)
       │
       └─ 采集反馈信号 + 情绪值
            ├─ 用户继续输入? -> positive
            ├─ 用户沉默? -> negative
            ├─ 打断 TTS? -> negative
            ├─ 情绪驱动触发? (v2.0)
            │   └─ 连续10次平均 > 0.3 / < -0.3
            └─ 每30次兜底检查
                 └─ PersonalityEvolution._adjust_vector()
                      └─ 微调 ±0.02×情绪权重 ──> 写回 DB
```

---

## 七、风险评估

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|:------:|:----:|---------|
| LLM 不遵循性格参数 | 中 | 风格不明显 | 风格描述用自然语言强化，不只是数值 |
| 演化方向不符合用户期望 | 低 | 性格变偏 | 每次只动 0.02，用户可在 GUI 手动修正 |
| 反馈信号误判 | 中 | 演化方向偏 | 情绪驱动需要连续 10 次才触发，兜底 30 次 |
| 初始背景记忆干扰真实记忆 | 低 | 混淆 | decay < 1.0 自然淘汰，importance 低 |
| 性格参数被 LLM 当指令执行 | 低 | 行为异常 | prompt 明确标注"参考，不需主动提及" |
| **LLM 情绪调整值超出范围** (v2.0) | 中 | 情绪剧烈波动 | 代码层强制限制 ±0.2，总范围 clamp 到 [-1.0, 1.0] |
| **情绪值解析失败** (v2.0) | 低 | 情绪不更新 | try/except 包裹，解析失败默认为 0.0 |
| **情绪数据量过大** (v2.0) | 低 | 查询变慢 | mood_value 表加索引，GUI 限制读取条数 |
| **情绪与性格演化冲突** (v2.0) | 低 | 性格乱跳 | 情绪驱动只影响触发时机和权重，核心逻辑不变 |

---

## 八、测试计划

### 8.1 单元测试

| 测试项 | 验证内容 |
|--------|---------|
| `personality_seed` 表 CRUD | 建表、插入、读取、更新正常 |
| `mood_value` 表 CRUD | 建表、插入、读取、更新正常（v2.0） |
| 默认种子 fallback | 无种子时返回默认值 |
| 默认情绪值 fallback | 无记录时返回 0.0（v2.0） |
| `PersonalityEvolution._check_mood_trigger()` | 连续 10 次正面情绪触发，9 次不触发（v2.0） |
| `PersonalityEvolution._adjust_vector()` | 正面情绪时 delta × 1.5，负面时 × 1.2（v2.0） |
| 情绪值范围限制 | +0.3 + 0.2 = 0.5（不超 1.0），-0.9 - 0.2 = -1.0（不低于 -1.0）（v2.0） |
| 情绪调整值解析 | `+0.15` → 0.15，`abc` → 0.0（v2.0） |
| 向量边界 | 达到 0.0 / 1.0 后不再超出 |
| 初始背景记忆 decay | 随时间衰减，真实记忆覆盖 |

### 8.2 集成测试

| 测试项 | 验证内容 |
|--------|---------|
| prompt 注入 | `{personality}` 段 + `{mood}` 段正确出现在最终 prompt 中 |
| `【情绪调整】` 解析 | LLM 输出 `【情绪调整】:+0.15` 被正确解析和累加 |
| 多用户隔离 | 不同 identity_key 的性格向量 + 情绪值互不干扰 |
| 情绪 → 性格触发 | 连续 10 次正面情绪后，性格演化被触发 |
| 反馈采集 | 用户继续输入被正确识别为 positive |
| 演化持久化 | 重启后性格向量 + 情绪值保持上次的值 |
| 情绪曲线渲染 | `MoodChartWidget` 正确从 DB 加载并绘制曲线（v2.0） |

### 8.3 体验测试

| 测试项 | 验证内容 |
|--------|---------|
| 冷启动第一句话 | 不同预设产生不同风格的开场白 |
| 风格一致性 | 温暖型 AI 在多轮对话中保持温暖语气 |
| 情绪实时响应 | 被夸奖后情绪值上升，被批评后情绪值下降（v2.0） |
| 情绪曲线可视化 | 曲线图正确展示情绪趋势，悬停显示详情（v2.0） |
| 演化感知 | 模拟 100 次正面反馈后，性格向量有可见偏移 |
| 情绪驱动演化 | 模拟持续负面情绪后，性格演化被加速触发（v2.0） |

---

## 九、影响范围

### 9.1 新增文件

| 文件 | 职责 |
|------|------|
| `aaa_cognition/personality.py` | PersonalityEvolution 类 + 种子管理 + 情绪处理逻辑（v2.0 扩展） |
| `gui/widgets/mood_chart.py` | 情绪曲线图组件（v2.0 新增，QPainter 自绘） |

### 9.2 修改文件

| 文件 | 改动 |
|------|------|
| `aaa_cognition/db.py` | 新增 personality_seed 表 + mood_value 表 + 读写方法 |
| `aaa_cognition/prompt.py` | 三阶段模板增加 `{personality}` 段 + `{mood}` 段 + `【情绪调整】` 输出标签 |
| `aaa_cognition/prompt_retrieval.py` | 检索模板增加 `{personality}` 段 + `{mood}` 段 |
| `aaa_cognition/prompt_tool.py` | 工具模板增加 `{personality}` 段 + `{mood}` 段 |
| `aaa_cognition/main.py` | prompt 构建时注入性格 + 情绪 + 处理【情绪调整】标签 + 情绪驱动性格演化 |
| `gui/pages/settings_panel.py` | 性格参数查看 + 微调滑块 |
| `gui/widgets/knowledge_panel.py` | 新增"情绪曲线"Tab + 集成 MoodChartWidget（v2.0） |

### 9.3 不改的文件

| 文件 | 理由 |
|------|------|
| `bnos_runtime/*` | 引擎不感知性格/情绪，读 DB 与现有逻辑相同 |
| `node_python_llm_infer/*` | LLM 节点不感知性格/情绪，只是收到的 prompt 多了几段 |
| `node_python_tts/*` | TTS 节点不感知性格/情绪 |
| `node_python_asr_input/*` | ASR 节点不感知性格/情绪 |
| `nodes/shared/*` | 共享数据层无变化 |

### 9.4 工作量估算

| Phase | 内容 | 工作量 |
|-------|------|--------|
| Phase 0 | 数据层（personality_seed + mood_value 表） | 0.5 天 |
| Phase 1 | prompt 注入（性格 + 情绪双段 + 输出标签） | 0.5 天 |
| Phase 2 | 情绪系统 + 情绪驱动性格演化 | 1.5 天 |
| Phase 3 | GUI 交互 + 情绪曲线图可视化 | 1.5 天 |
| Phase 4 | 人格格式化（含情绪历史重置） | 0.3 天 |
| **合计** | | **约 4.3 天** |

---

## 十、人格格式化（重置功能）

> 当用户对当前 AI 的性格或记忆不满意时，可通过"人格格式化"重置 AI，使其从头开始。

### 10.1 功能定义

人格格式化 = **清空记忆** + **重置性格**，相当于让 AI 回到首次启动状态。

| 操作 | 说明 |
|------|------|
| 清空记忆 | 删除所有用户数据表中的记录（复用现有 `clear` 命令逻辑，同 §6.2.2） |
| 重置性格 | 将 `personality_seed` 表恢复为默认种子值（`warmth=0.6, playfulness=0.4, directness=0.5, curiosity=0.5`） |
| 弹出选择 | 重置后自动弹出性格选择界面，让用户重新选择预设种子 |

### 10.2 用户流程

```
用户在设置面板点击「人格格式化」
        │
        ▼
弹出确认弹窗（含警告文字）← 二次确认
        │
   ┌────┴────┐
   │ 取消？  │ → 关闭弹窗，不做任何操作
   └────┬────┘
        ▼
   ┌────┴────┐
   │ 确认？  │
   └────┬────┘
        ▼
执行 format 命令：
  1. 清空所有用户表（DELETE FROM 所有非 sqlite_ 表）
  2. personality_seed 重置为默认值（warmth=0.6 等）
  3. 重建 MemOS 索引（索引为空）
        │
        ▼
弹出性格选择界面（同首次启动流程）
        │
        ▼
用户选择新种子 → 写 personality_seed → 开始新交互
```

### 10.3 二次确认弹窗文案

```
┌──────────────────────────────────┐
│  ⚠ 人格格式化                    │
│                                  │
│  这将清空 AI 的所有记忆和当前性格。│
│  她将忘记有关你的一切，从头开始。  │
│                                  │
│  此操作不可撤销。                 │
│                                  │
│        [取消]    [确认格式化]     │
└──────────────────────────────────┘
```

### 10.4 数据保留策略

| 数据 | 保留？ | 原因 |
|------|:------:|------|
| 用户表（对话、记忆、认知、事件摘要、日记等） | ✗ 清空 | 核心重置目标 |
| `personality_seed` 表 | 重置为默认值 | 性格一起重置 |
| `fixed_cognition` 表 | 保留 | 系统级固定认知，不依赖用户交互 |
| 系统表（`sqlite_*`） | 保留 | SQLite 内部表 |
| MemOS 向量索引 | 重建（空） | 记忆清空后索引自然为空 |
| `gui_config.json` | 保留 | GUI 偏好（主题色等）与 AI 人格无关 |

### 10.5 实现要点

- **复用现有 `clear` 命令**：`SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'` 遍历删除（已有实现）
- **`personality_seed` 特殊处理**：清空后 INSERT 默认值（`_IDENTITY_KEY_DEFAULT`, `warmth=0.6`, `playfulness=0.4`, `directness=0.5`, `curiosity=0.5`）
- **GUI 端**：`settings_panel.py` 新增按钮 + 确认弹窗 + 格式化完成后回调弹出种子选择界面
- **后端接口**：新增 `db_command` 类型 `cmd="format"`，区别于现有 `cmd="clear"`
- **对话历史**：`conversation_history.json` 也应清空，避免 UI 残留旧对话

### 10.6 与现有功能的关系

| 现有功能 | 关系 |
|---------|------|
| 清空数据库（`clear`） | 格式化的子集——`clear` 只清记忆，`format` = `clear` + 重置性格 + 弹出选择 |
| 首次启动性格选择 | 格式化后触发同一套流程，复用原有界面组件 |
| 性格微调滑块 | 格式化后重置为默认值，后续仍可通过滑块微调 |

---

*本方案基于 BNOS AI 现有架构（MemOS 语义检索 + identity_key 多用户隔离 + 三阶段提示词模板）设计，不引入新基础设施，复用现有 DB 和 prompt 体系。*

*v2.0 更新：新增动态情绪系统（LLM 增量式量化 + 代码累加）、情绪驱动的性格演化触发机制、GUI 情绪曲线可视化方案。*
