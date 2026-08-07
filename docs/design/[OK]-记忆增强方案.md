# AAA 记忆增强方案

> 日期：2026-07-26 | 版本：v2.0 | 状态：[PLAN] | 基于 AAA v2.0 现有架构

---

## 目录

1. [动机](#一动机)
2. [方案概览](#二方案概览)
3. [记忆分层](#三记忆分层)
4. [冲突检测与去重](#四冲突检测与去重)
5. [按需检索](#五按需检索)
6. [Prompt 模板变更](#六prompt-模板变更)
7. [DB 迁移](#七db-迁移)
8. [改动清单](#八改动清单)
9. [影响范围](#九影响范围)
10. [自我反思机制](#十自我反思机制)
11. [Diary 日记联动 MemOS](#十一diary-日记联动-memos)

---

## 一、动机

### 1.1 当前问题

| # | 问题 | 现象 | 根因 |
|:--:|------|------|------|
| 1 | 记忆无权重 | 闲聊摘要和重大事件在 prompt 中地位相同 | 无重要性标记 |
| 2 | LLM 重复写库 | 同一事实反复输出，DB 堆叠重复行 | 无去重机制 |
| 3 | 无谓检索 | 每次对话都跑 FAISS，多数场景不需要 | 无按需触发 |
| 4 | 无情感趋势 | 每轮情感是孤立的，无基线概念 | 无聚合统计 |
| 5 | 无时效感知 | 3 个月前的认知依然原样注入 prompt | 无 decay 机制 |

### 1.2 设计原则

- **不改现有表结构**（加列/加表，不删不改）
- **不增加 LLM 调用次数**（常规对话仍为单轮，检索场景最多两轮；仅 Diary 每日额外 +1 次）
- **不改变 LLM 输出格式**（只扩展节标记，不新增标记）
- **prompt 模板只做加法**（最多加 2 行）

### 1.3 架构决策（v1.1 新增）

```
记忆检索层: FAISS（hash 伪向量）→ MemOS（语义向量）
  形态: AAA 内部模块（memos.py），替换现有 memory.py
     → 不是独立节点，不走进程间通信
     → 不增加 LLM 调用（SentenceTransformer 算向量，CPU 毫秒级）
     → prompt 模板占位符 {faiss_top5} 改名 {memos_top5}

知识持久化: logseq_writer 独立节点 → 废弃
  理由: logseq_writer 本质是 open().write()，不值得开进程
  替代: AAA DB（user_facts）已是唯一持久化来源
  可视化: 由 GUI 知识库面板直接读 DB 展示，不做节点
  port_mappings: 删除 knowledge → logseq_writer 映射
```

---

## 二、方案概览

```
用户输入
  │
  ▼
_on_text（改动点 A）
  ├→ 薄 prompt（skip_faiss=True）→ LLM
  │     ↓
  │   检查 【语意检索】节
  │     ├─ 空 → 正常写库、分发（单轮，不检索）
  │     └─ 非空 → 跑 MemOS 语义检索 → 重建 prompt → 再次 LLM（两轮）

  ├→ write_async 写库（改动点 B）
  │     └→ _dedup_and_merge（冲突检测 + 去重）
  └→ write_parsed_async 写解析结果（改动点 C）
        └→ 解析 importance/decay 属性
             + 异步写入 MemOS 向量索引
```

---

## 三、记忆分层

### 3.1 新增列

`long_term_memory` 表加 3 列（迁移 SQL）：

```sql
ALTER TABLE long_term_memory ADD COLUMN importance INTEGER DEFAULT 3;
ALTER TABLE long_term_memory ADD COLUMN decay_date TEXT DEFAULT NULL;
ALTER TABLE long_term_memory ADD COLUMN source_confidence INTEGER DEFAULT 3;
```

| 列 | 值域 | 含义 |
|:----:|:----:|------|
| `importance` | 1-5 | 1=闲聊, 2=日常, 3=事实(默认), 4=重要, 5=重大事件 |
| `decay_date` | ISO 8601 | 过期时间，NULL=永不过期 |
| `source_confidence` | 1-5 | 1=系统推断, 2=LLM生成, 3=用户提及, 4=用户直接说, 5=用户主动确认 |

### 3.2 重要性来源

| 来源 | 赋值规则 | 默认值 |
|------|---------|:------:|
| LLM 输出节标记 | `【事件摘要】... [importance=5]` 提取属性 | 3 |
| 用户主动提及 | 正则匹配"记住"、"重要"等关键词 → +1 | 3→4 |
| 重复确认 | 同一事实出现 ≥3 次 → 自动升级 | 随次数递增 |
| 用户直接说 | source="asr", 喊名字/打招呼 → +1 | 3→4 |

### 3.3 decay_date 计算

```python
_IMPORTANCE_DAYS = {1: 1, 2: 7, 3: 30, 4: 90, 5: 365}

def _calc_decay_date(importance: int) -> str:
    """根据重要性计算过期日期"""
    days = _IMPORTANCE_DAYS.get(importance, 30)
    return (datetime.now() + timedelta(days=days)).isoformat()
```

### 3.4 写入时的使用

```python
# db.py _write / _write_parsed 中
importance = data.get("importance", parsed.get("importance", 3))
data["importance"] = importance
data["decay_date"] = _calc_decay_date(importance)

INSERT INTO long_term_memory(..., importance, decay_date, ...) VALUES(..., ?, ?, ...)
```

---

## 四、冲突检测与去重

### 4.1 新增 `_dedup_and_merge`

```python
# db.py 新增

_SIMILARITY_THRESHOLD = 0.80  # 余弦相似度阈值


def _dedup_and_merge(
    table: str,
    conv_id: str,
    new_content: str,
    conn: sqlite3.Connection,
    importance: int = 3,
) -> str | None:
    """去重合并。返回 None=不写, str=写入的实际内容"""
    # 取同类最近一条
    old = conn.execute(
        f"SELECT content FROM [{table}] WHERE conversation_id=? ORDER BY id DESC LIMIT 1",
        (conv_id,),
    ).fetchone()
    if not old:
        return new_content                        # 无旧记录 → 直接写

    old_content = old[0]
    if not old_content:
        return new_content

    # 简单相似度（字符级 Jaccard，无需额外依赖）
    sim = _text_similarity(new_content, old_content)
    if sim > _SIMILARITY_THRESHOLD:
        return None                               # 高度相似 → 跳过

    if importance >= 4 and sim > 0.5:
        # 重要性高 + 有一定差异 → 合并（保留旧信息基础上追加）
        return f"{old_content}；补充：{new_content}"

    return new_content                            # 低重要性或差异大 → 覆盖


def _text_similarity(a: str, b: str) -> float:
    """字符级 Jaccard 相似度，轻量无依赖"""
    if not a or not b:
        return 0.0
    set_a, set_b = set(a), set(b)
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0
```

### 4.2 调用点

```python
# _write_parsed 中，每种写入前调用
deduped = _dedup_and_merge("other_cognition", conversation_id, val, conn, importance)
if deduped is None:
    continue  # 跳过写入

# _write 中同理（针对 long_term_memory 的 user 角色）
if role == "user":
    deduped = _dedup_and_merge("long_term_memory", conv_id, c, conn)
    if deduped is None:
        return
    c = deduped
```

### 4.3 确认计数

同一事实被确认多次时，额外记录一个外部计数器（不修改 DB schema，用 `fixed_cognition` 表）：

```python
def _increment_certainty(key: str, conn: sqlite3.Connection):
    """增加确认次数；返回当前次数"""
    conn.execute(
        """INSERT INTO fixed_cognition(key, value) VALUES(?, '1')
           ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
           updated_at = datetime('now','localtime')""",
        (f"certainty_{key}",),
    )
    row = conn.execute(
        "SELECT value FROM fixed_cognition WHERE key = ?",
        (f"certainty_{key}",),
    ).fetchone()
    return int(row[0]) if row else 0
```

确认次数 ≥3 后，该事实重要性自动 +1（在 `_gather_context` 中体现）。

---

## 五、按需检索（语义向量检索 — MemOS 替换 FAISS）

### 5.0 记忆检索层替换：memory.py → memos.py

当前 `memory.py` 使用 MD5 hash 伪向量做 FAISS 检索，语义匹配效果差。替换为 MemOS（SentenceTransformer 真向量）：

```python
# memory.py（旧，将被删除）
def _text_to_vector(text, dim):
    # MD5 hash 伪向量，无语义
    v = [0.0] * dim
    for w in re.findall(r"\w+", text.lower()):
        h = hashlib.md5(w.encode()).hexdigest()
        ...

# memos.py（新）
import numpy as np
from sentence_transformers import SentenceTransformer

_model = None

def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")  # ~80MB, CPU
    return _model

def _text_to_vector(text: str) -> np.ndarray:
    """真语义嵌入"""
    return _get_model().encode(text, normalize_embeddings=True)

def retrieve(query: str, top_k: int = 5) -> str:
    """语义检索相关记忆 — 替换 memory.faiss_retrieve()"""
    ...

def add_entry(entry_id: int, text: str):
    """写入新记忆的向量索引"""
    ...
```

| 对比 | 旧 memory.py（FAISS hash） | memos.py（语义向量） |
|------|:--------------------------:|:--------------------:|
| 检索质量 | 关键词硬匹配 | 语义理解 |
| 写入成本 | MD5，零成本 | SentenceTransformer，CPU 毫秒级 |
| 每条长度 | 原始对话 200 字（~300 token） | LLM 加工后 15-80 字（~60 token） |
| 额外依赖 | faiss-cpu | sentence-transformers |
| LLM 调用 | 不增加 | 不增加 |

> **并存还是替换？** 替换。两者在 prompt 中占同一个位置，并存导致 prompt 变长、内容重复。hash 向量的检索结果干扰大于帮助，不保留降级。

### 5.1 当前行为（改前）

```python
# _gather_context 每次都运行
faiss_top5 = memory.faiss_retrieve(user_text, ...)
```

### 5.2 改为两轮交互

#### 第一轮：薄 prompt

```python
# _on_text
ctx = self._gather_context(
    user_text, dbp, conv_id,
    skip_retrieval=True,         # ← 不跑 MemOS 检索
    skip_history=False,          # 历史摘要、认知等照常加载
)
thin_prompt = pt.build(ctx)
# 写入 output_prompt.json → LLM 推理节点
```

#### LLM 决定是否需检索

prompt 中保留 `【语意检索】` 节，LLM 自行判断：

```
不需要回忆：
  【语意检索】（空，可省略）
  【自然回复】今天天气确实不错

需要回忆：
  【语意检索】用户喜欢的电影
  【自然回复】让我回想一下...
```

#### 第二轮：带检索结果

```python
def _on_text(self, data, dbp):
    conv_id = data.get("conversation_id") or "default"
    attachments = data.get("attachments", [])

    # ── 第一轮：薄 prompt ─────────────────
    ctx = self._gather_context(data.get("content", ""), dbp, attachments, conv_id, skip_faiss=True)
    prompt = pt.build(ctx)

    # 发送到 LLM（写 output_prompt.json，由框架转发）
    # ... 接收 LLM 返回 ...

    # ── 检查检索需求 ─────────────────
    parsed = psr.parse_llm_output(llm_response)
    keywords = (parsed.get("语意检索") or "").strip()

    if keywords:
        # ── 第二轮：带 MemOS 检索结果 ────
        memos_results = memos.retrieve(keywords, ...)
        ctx2 = self._gather_context(data.get("content", ""), dbp, attachments, conv_id,
                                     retrieval_override=memos_results)
        prompt2 = pt.build(ctx2)
        # 再次发送到 LLM
        # ... 接收 LLM 返回 ...
        parsed = psr.parse_llm_output(llm_response2)

    # ── 正常后续处理（写库＋分发）──
    db.write_parsed_async(parsed, dbp, conversation_id=conv_id)
    ...
```

### 5.3 `_gather_context` 新增参数

```python
def _gather_context(self, user_text, dbp, attachments=None, conv_id="default",
                     skip_retrieval=False, retrieval_override=None):
    # ... 现有代码 ...

    # 改前
    faiss_top5 = memory.faiss_retrieve(...)

    # 改后
    if retrieval_override is not None:
        memos_top5 = retrieval_override          # 第二轮：使用精确检索结果
    elif skip_retrieval:
        memos_top5 = ""                          # 第一轮：不检索
    else:
        memos_top5 = memos.retrieve(...)         # 兼容其他调用方（如 _on_tool_result）
```

`remove_old_faiss` 函数和 `memory.py` 最后删除。FAISS 相关的依赖也从 `requirements.txt` 移除，改为 `sentence-transformers`。

### 5.4 两轮调用的时序问题

AAA 当前是**同步处理**模式（`process()` 函数调用内完成所有逻辑）。由于 LLM 推理是异步的（通过 `output_prompt.json` 写入 + 等待 `llm_response` 端口），实际两轮交互需要依靠 AAA 节点的**两次连续调用**完成：

```
第一次调用（source="gui"）：
  _on_text → 薄 prompt → output_prompt.json
     ↓ 等待 LLM 推理完成
第二次调用（source="llm", data_type="text"）：
  _on_parsed → 检查 【语意检索】
    ├─ 无检索 → 正常分发、写库
    └─ 有检索 → 跑 MemOS 语义检索 → output_prompt.json（第二轮）
         ↓ 等待 LLM 再次推理完成
第三次调用（source="llm", data_type="text"）：
  _on_parsed → 正常分发、写库
```

AAA 需在 `_on_parsed` 中判断"这是第一轮 LLM 返回还是第二轮"。通过 `data.get("request_id")` 关联。

---

## 六、Prompt 模板变更

### 6.1 改前（prompt.py）

```
### 输入上下文
你的自我认知：{self_cognition}
你的最近感受：{recent_feelings}
你的他人认知（对用户）：{other_cognition}

本轮输入：
  用户文本：{user_text}
...
记忆检索结果：{faiss_top5}
...
```

### 6.2 改后

```
### 输入上下文
你的自我认知：{self_cognition} [确认次数: {self_certainty}]    ← 仅加确认次数
你的最近感受：{recent_feelings}
本周情感基调：{mood_trend}                                     ← 新增 1 行
你的他人认知（对用户）：{other_cognition} [确认次数: {other_certainty}]

本轮输入：
  用户文本：{user_text}
...

{memos_section}                                                ← 条件注入，原名 {faiss_section}

### 输出格式（用节标记包裹，不需要的节省略）
...
【语意检索】                                                    ← 已有，语义变为"按需触发"
需要回忆的关键词，如：用户喜欢的电影
...
【事件摘要】
本轮对话的核心摘要，1-2句话 [重要性:1-5]                        ← 加重要性标记
```

`{memos_section}` 条件注入：

```python
# prompt.py build() 中
memos_section = ""
if ctx.get("memos_top5"):
    memos_section = f"记忆检索结果（按需）：\n{ctx['memos_top5']}"
```

确认次数从 `fixed_cognition` 表读取：

```python
# _gather_context 中
self_certainty = conn.execute(
    "SELECT value FROM fixed_cognition WHERE key='certainty_self_cognition'"
).fetchone()
other_certainty = conn.execute(
    "SELECT value FROM fixed_cognition WHERE key='certainty_other_cognition'"
).fetchone()
```

---

## 七、DB 迁移

### 7.1 新增表

```sql
-- 情感趋势聚合
CREATE TABLE IF NOT EXISTS mood_trend (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL DEFAULT 'default',
    period TEXT NOT NULL,           -- 'hourly' | 'daily' | 'weekly'
    period_start TEXT NOT NULL,
    avg_mood_value REAL DEFAULT 3.0,-- 1=负面, 3=中性, 5=正面
    dominant_mood TEXT,             -- 出现最多的心情词
    sample_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 按需检索请求日志（调试用，可清理）
CREATE TABLE IF NOT EXISTS retrieval_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL DEFAULT 'default',
    keywords TEXT NOT NULL,
    result_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
```

### 7.2 新增列（迁移）

```sql
-- 现有表加列（幂等，重复列会抛异常但被 except pass 吃掉）
ALTER TABLE long_term_memory ADD COLUMN importance INTEGER DEFAULT 3;
ALTER TABLE long_term_memory ADD COLUMN decay_date TEXT DEFAULT NULL;
ALTER TABLE long_term_memory ADD COLUMN source_confidence INTEGER DEFAULT 3;
```

### 7.3 情感聚合逻辑

```python
# db.py 新增

_MOOD_VALUES = {
    "开心": 5, "兴奋": 5, "喜悦": 5,
    "好奇": 4, "期待": 4, "平静": 3,
    "疲惫": 2, "无聊": 2, "难过": 1,
    "悲伤": 1, "愤怒": 1, "焦虑": 1,
    "恐惧": 1,
}


def _aggregate_mood(db_path: str, conv_id: str, period: str = "daily"):
    """聚合指定周期的情感数据"""
    conn = sqlite3.connect(db_path)
    try:
        # 取周期内的所有心情记录
        rows = conn.execute(
            """SELECT mood, COUNT(*) as cnt FROM feelings
               WHERE conversation_id=? AND mood IS NOT NULL AND mood != ''
               AND date(created_at) = date('now')
               GROUP BY mood ORDER BY cnt DESC""",
            (conv_id,),
        ).fetchall()
        if not rows:
            return

        total = sum(r[1] for r in rows)
        dominant = rows[0][0]
        avg_value = sum(_MOOD_VALUES.get(r[0], 3) * r[1] for r in rows) / total

        conn.execute(
            """INSERT INTO mood_trend(conversation_id, period, period_start,
               avg_mood_value, dominant_mood, sample_count)
               VALUES(?, ?, date('now'), ?, ?, ?)""",
            (conv_id, period, avg_value, dominant, total),
        )
        conn.commit()
    finally:
        conn.close()
```

---

## 八、改动清单

### 8.1 文件变动

| 文件 | 改动 | 行数 |
|------|------|:----:|
| `memory.py` | **删除**，功能由 `memos.py` 取代 | 删除 ~100 行 |
| `memos.py` | **新建**，语义向量检索模块（SentenceTransformer + FAISS 真向量） | **~120 行** |
| `db.py` | 新增 `_dedup_and_merge`, `_text_similarity`, `_increment_certainty`, `_aggregate_mood`, `_calc_decay_date`；`_write`/`_write_parsed` 增加重要性/decay 写库 + 异步写入 MemOS 向量 | **~160 行** |
| `main.py` | `_on_text` 改为按需检索两轮流程；`_gather_context` 新增 `skip_retrieval`/`retrieval_override` 参数；`_on_parsed` 异步写 MemOS 向量；新增 `_gather_historical_self_cognition()` 和 `_check_reflection_trigger()` | **~80 行** |
| `prompt.py` | 模板加 `mood_trend`, `self_certainty`, `other_certainty`, `[重要性:1-5]`；`build()` 条件注入 `memos_section`、`reflection_prompt`；`{faiss_top5}` → `{memos_top5}` | **~15 行** |
| `parser.py` | 解析 `[importance=N]` 属性；解析 `[decay=Nd]` 属性 | **~15 行** |
| `ensure()` | 新增 `mood_trend`, `retrieval_log` 表建表；幂等加列迁移 | **~20 行** |
| `requirements.txt` | 移除 `faiss-cpu`，添加 `sentence-transformers` | **~2 行** |
| `node_config.json` | 删除 `faiss_index_path` 参数；删除 `knowledge → logseq_writer` 的 port_mappings | **~5 行** |
| `diary.py` | **新建**，AI 日记模块：空闲触发、LLM 摘要生成、MemOS 向量写入、self_cognition 更新 | **~100 行** |

**总计**：**~475 行新增代码，~105 行删除代码，净增 ~370 行**（含注释和空行约 ~450 行）。

### 8.2 删除的文件

| 文件 | 说明 |
|------|------|
| `memory.py` | 被 `memos.py` 替换 |
| `nodes/node_python_logseq_writer/` | 整个节点目录标记废弃，不再维护 |

### 8.3 不变的文件

| 文件 | 说明 |
|------|------|
| `config.py` | 配置加载不变（新参数从 `node_config.json` 读取） |
| `packet.py` | 不变 |
| `listener.py` | 不变 |
| `output_*.json` | 输出协议不变 |

---

## 九、影响范围

### 9.1 兼容性

| 维度 | 是否兼容 | 说明 |
|:----:|:--------:|------|
| 现有 DB | ✅ | 加列/加表，不删不修改现有数据 |
| LLM 输出格式 | ✅ | 节标记不变，`[importance=N]` 为可选属性 |
| GUI 客户端 | ✅ | 不变（知识可视化后续以 GUI 组件形式添加，不影响现有功能） |
| Live2D 节点 | ✅ | 不变 |
| turn_taking | ✅ | 不变（turn_taking 为独立事件路由节点，不依赖记忆检索方式） |
| ASR 输入 | ✅ | `source="asr"` 直接走 `_on_text`，兼容 |

### 9.2 回退策略

如新增功能出现问题，可回退的方案：

1. **按需检索**：将 `skip_retrieval` 默认改为 `False`，恢复每次检索
2. **去重合并**：注释 `_dedup_and_merge` 调用，恢复原有写入
3. **记忆分层**：新列有 `DEFAULT` 值，不做条件查询时不感知
4. **MemOS 回退**：保留 `memory.py` 副本，替换 `memos.py` 导入即可恢复旧 FAISS hash 检索

---

## 十、自我反思机制

> v2.0 新增 | 触发方式：self_cognition 条数阈值 | 额外 LLM 调用：0

### 10.1 动机

当前 AAA 的 `self_cognition` 表只是"记录自我认知"，但不会去回顾、比较、迭代这些认知。AI 对自己的理解在同一个层次上原地打转，缺乏反思带来的认知深度提升。

### 10.2 设计

```
正常对话流程中：
  _on_parsed → 写库前检查 self_cognition 条数
    ├─ 未达阈值 → 正常写库（无反思）
    └─ 达阈值（每 10 条）→ 取最近 5 条自我认知 + 事件摘要
         ↓
        条件性注入 reflection_prompt 到 LLM 提示词
         ↓
        LLM 在同一轮输出中生成更深层的【自我认知】和【自我信息】
```

### 10.3 实现

#### 触发判断

```python
# main.py _on_parsed 中
def _check_reflection_trigger(conn, conv_id) -> bool:
    """检查是否触发自我反思。每 10 条 self_cognition 触发一次。"""
    count = conn.execute(
        "SELECT COUNT(*) FROM self_cognition WHERE conversation_id=?",
        (conv_id,),
    ).fetchone()[0]
    return count > 0 and count % 10 == 0
```

#### 历史认知收集

```python
# main.py _gather_historical_self_cognition
def _gather_historical_self_cognition(conn, conv_id, limit=5) -> str:
    """取最近 N 条历史自我认知和事件摘要"""
    sc_rows = conn.execute(
        "SELECT content FROM self_cognition WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
        (conv_id, limit),
    ).fetchall()

    events = conn.execute(
        "SELECT summary FROM event_summary WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
        (conv_id, limit),
    ).fetchall()

    parts = []
    if sc_rows:
        parts.append("你之前的自我认识：\n" + "\n".join(
            f"{i+1}. {r[0]}" for i, r in enumerate(reversed(sc_rows))))
    if events:
        parts.append("最近的事件：\n" + "\n".join(
            f"- {r[0]}" for r in reversed(events)))
    return "\n\n".join(parts)
```

#### Prompt 条件注入

```python
# prompt.py build() 中
reflection_section = ""
if ctx.get("reflection_prompt"):
    reflection_section = ctx["reflection_prompt"]
    # 追加到 prompt 末尾：
    # "请回顾上述历史自我认识，输出当前更深层的【自我认知】和【自我信息】。"
```

修改后的 prompt 模板：

```
### 输入上下文
你的自我认知：{self_cognition} [确认次数: {self_certainty}]
你的最近感受：{recent_feelings}
本周情感基调：{mood_trend}
你的他人认知（对用户）：{other_cognition} [确认次数: {other_certainty}]

本轮输入：
  用户文本：{user_text}
...

{memos_section}

{reflection_section}     ← 条件注入，仅在触发反思时非空

### 输出格式（用节标记包裹，不需要的节省略）
...
【自我认知】              ← LLM 输出新的自我认知
【自我信息】              ← LLM 输出新的自我信息
【语意检索】
【事件摘要】[重要性:1-5]
【自然回复】
```

### 10.4 与 10 轮阈值的关系

| 触发器 | 时机 | 作用 | LLM 调用 |
|--------|------|------|:--------:|
| self_cognition 条数达 10 倍数 | 对话中（写库前） | 回顾历史认知，迭代自我理解 | 0（同一轮注入） |
| Diary 次日触发（见第十一节） | 次日首条对话 | 每日沉淀总结，补偿深化 | 每天 +1 |

两者互补：**对话中密集反思** + **每日异步总结**。

---

## 十一、Diary 日记联动 MemOS

> v2.0 新增 | 触发方式：次日首条对话 | 额外 LLM 调用：每天 +1

### 11.1 动机

my-neuro 的 Diary 功能写的是纯文本文件（`AI记录室/AI日记.txt`），写进去就再也没被用过。我们将其改造为：

1. diary 内容 + 当天事件摘要 → 向量化写入 MemOS（可检索）
2. diary → 触发 `self_cognition` 更新（异步补充 10 轮阈值反思）

### 11.2 触发设计

**次日首条对话触发**（相对于空闲 20s），理由：

| 问题 | 空闲 20s 触发 | 次日首对话触发 |
|------|:------------:|:-------------:|
| 白天内容截断 | 早上写了，中午晚上的对话丢了 | 第二天一整天内容完整 |
| 早上没内容 | 会产生空日记 | 前一天内容已积累完毕 |
| 一天多次触发 | 需防重，需检查内容量 | 仅触发一次，直接检查前一天 |

流程：

```
Day N: 用户全天断断续续聊天
Day N+1: 用户发第一条消息
  └─ 检测到日期变更（today != last_diary_date）
       ├─ 检查 Day N 的日记是否已存在
       │    ├─ 已存在 → 跳过，正常处理消息
       │    └─ 不存在 → 触发写日记
       │              ↓
       │              ├─ LLM 生成日记（1次调用）
       │              ├─ 写入 MemOS 向量索引
       │              └─ 异步更新 self_cognition
       │
       └─ 然后正常处理 Day N+1 的第一条消息
```

### 11.3 时间范围约束

AI 撰写日记时的输入严格限定在**前一天**：

```python
def _write_diary(yesterday: str):
    """生成前一天日记，时间范围严格限定"""
    # 只取前一天的事件（created_at LIKE '2026-07-25%'）
    events = _get_day_events(yesterday)

    # 只取前一天的对话（long_term_memory）
    conversations = _get_day_conversations(yesterday)

    # 只取前一天的心情（feelings）
    mood = _get_day_mood(yesterday)

    diary_prompt = (
        f"日期：{yesterday}\n\n"
        f"今天的事件：\n{events}\n\n"
        f"今天的对话记录：\n{conversations}\n\n"
        f"今天的心情：{mood}\n\n"
        f"请根据以上信息，以第一人称写一段日记总结今天的经历和感受。"
    )
```

### 11.4 实现

```python
# diary.py — 新建模块

from datetime import datetime

_last_diary_date = None  # 最后写日记的日期，用于次日检测


def check_and_write_diary(today: str) -> bool:
    """次日首条对话时调用。
    检查是否需要写前一天的日记，如果写返回 True，否则返回 False。
    调用方在 _on_text 中处理完用户消息后调用此函数。
    """
    global _last_diary_date

    # 首次启动，无 last_diary_date，跳过
    if _last_diary_date is None:
        _last_diary_date = today
        return False

    yesterday = _calc_yesterday(today)

    # 昨天已经写过日记了
    if _diary_exists(yesterday):
        _last_diary_date = today
        return False

    # 写日记（不论内容多少，没有内容就写"空白的一天"）
    _write_diary(yesterday)
    _last_diary_date = today
    return True


def _write_diary(yesterday: str):
    """生成前一天日记并联动 MemOS 和 self_cognition"""
    # 1. 收集前一天的内容（时间范围严格限定）
    events = _get_day_events(yesterday)
    conversations = _get_day_conversations(yesterday)
    mood = _get_day_mood(yesterday)

    # 2. LLM 生成日记（1次调用）
    diary_prompt = (
        f"日期：{yesterday}\n\n"
        f"今天的事件：\n{events}\n\n"
        f"今天的对话记录：\n{conversations}\n\n"
        f"今天的心情：{mood}\n\n"
        f"请根据以上信息，以第一人称写一段日记总结今天的经历和感受。"
    )
    diary_text = _call_llm(diary_prompt)

    # 3. 写入 MemOS 向量索引
    memos.add_entry(
        text=diary_text,
        metadata={"type": "diary", "date": yesterday, "importance": 3},
    )

    # 4. 异步更新 self_cognition
    update_prompt = f"基于{yesterday}的日记内容，提炼一条对你的自我认知的更新：\n{diary_text}"
    self_cog_text = _call_llm(update_prompt)
    _queue_self_cognition_update(self_cog_text)


def _calc_yesterday(today: str) -> str:
    """计算昨天日期"""
    dt = datetime.strptime(today, "%Y-%m-%d")
    return datetime(dt.year, dt.month, dt.day - 1).strftime("%Y-%m-%d")


def _diary_exists(date_str: str) -> bool:
    """检查指定日期是否已有日记（查 MemOS metadata 或表）"""
    ...

def _get_day_events(date_str: str) -> str:
    """从 event_summary 表取指定日期的事件"""
    ...

def _get_day_conversations(date_str: str) -> str:
    """从 long_term_memory 取指定日期的对话"""
    ...

def _get_day_mood(date_str: str) -> str:
    """从 feelings 表聚合指定日期的心情"""
    ...

def _call_llm(prompt: str) -> str:
    """写 output_prompt.json，等待 LLM 返回"""
    ...

def _queue_self_cognition_update(text: str):
    """缓存到队列，由 _on_parsed 处理写入"""
    ...
```

### 11.5 与 10 轮阈值反思的互补

| | 10 轮阈值反思 | Diary 反思 |
|---|:-----------:|:--------:|
| 触发 | self_cognition 每 10 条 | 次日首条对话 |
| 内容 | 历史自我认知 + 近期事件 | 当天完整对话总结 |
| LLM 调用 | 0（同一轮不额外调） | 每天 +1 |
| 写入 | self_cognition 表 | MemOS + self_cognition |
| 定位 | 对话中短期密集迭代 | 每日收尾沉淀补充 |

---

**最后更新**：2026-07-26
