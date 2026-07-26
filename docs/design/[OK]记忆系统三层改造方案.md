# BNOS AI — 记忆系统三层改造方案

> 日期: 2026-07-25
> 涉及节点: `node_python_aaa_cognition`

---

## 一、现状与问题

### 当前架构（扁平）

```
所有消息 + 摘要 + 认知 → 8 张无隔离的表
                              ↓
_gather_context() 永远只读「最新 N 条」
                              ↓
                        无法区分不同对话
```

**关键缺陷**:
- 所有表缺少 `conversation_id` 列，数据混在一起
- `_gather_context()` 只能按 `ORDER BY id DESC LIMIT N` 取最近记录
- 设计文档(开发方案.md) Section 13 的会话方案从未实现
- FAISS 向量检索索引构建代码缺失（只读了 `.index` 没有写入）

### 根本矛盾

> 记忆系统加载的是「最近一次对话」的上下文，如果 GUI 做了多对话切换，后端不知道该切换。

---

## 二、目标架构：三层记忆

```
┌──────────────────────────────────────────────┐
│              固定认知层 (always loaded)        │
│  · 无 conversation_id                        │
│  · 用户画像、长期设定、性格偏好                │
│  · _gather_context() 始终加载                  │
├──────────────────────────────────────────────┤
│                                              │
│  对话 A         对话 B         对话 C         │
│  ┌────────┐    ┌────────┐    ┌────────┐      │
│  │消息列表│    │消息列表│    │消息列表│      │
│  │对话摘要│    │对话摘要│    │对话摘要│      │
│  │情感/认知│   │情感/认知│   │情感/认知│      │
│  └────────┘    └────────┘    └────────┘      │
│           对话层 (按 conversation_id 隔离)     │
├──────────────────────────────────────────────┤
│              共享记忆层 (cross-conversation)  │
│  · 无 conversation_id                        │
│  · 从所有对话提取的实体、事件、代码片段        │
│  · FAISS 向量检索跨对话命中                   │
└──────────────────────────────────────────────┘
```

### 数据流

```
用户发消息 (conversation_id=conv_A)
    ↓
1. 加载固定认知（用户画像 + 长期记忆）
2. 加载 conv_A 的上下文（摘要 + 情感 + 认知）
3. 检索共享记忆（FAISS 跨对话）
4. LLM 推理（三层信息拼入 prompt）
5. 写入 conv_A 的消息表 + 更新摘要
6. 提取实体/事件沉淀到共享记忆层
```

---

## 三、数据库改造（db.py）

### 3.1 现有表加 `conversation_id`

所有 8 张表增加一列：

```sql
ALTER TABLE user_messages  ADD COLUMN conversation_id TEXT DEFAULT 'default';
ALTER TABLE feelings       ADD COLUMN conversation_id TEXT DEFAULT 'default';
ALTER TABLE event_summary  ADD COLUMN conversation_id TEXT DEFAULT 'default';
ALTER TABLE self_cognition ADD COLUMN conversation_id TEXT DEFAULT 'default';
ALTER TABLE other_cognition ADD COLUMN conversation_id TEXT DEFAULT 'default';
ALTER TABLE user_facts     ADD COLUMN conversation_id TEXT DEFAULT 'default';
ALTER TABLE self_info      ADD COLUMN conversation_id TEXT DEFAULT 'default';
ALTER TABLE long_term_memory ADD COLUMN conversation_id TEXT DEFAULT 'default';
```

> 默认值 `'default'` 确保现有数据无须迁移。

### 3.2 新增 `fixed_cognition` 表（固定认知层）

```sql
CREATE TABLE IF NOT EXISTS fixed_cognition (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT UNIQUE NOT NULL,
    value       TEXT NOT NULL,
    updated_at  TEXT DEFAULT (datetime('now','localtime'))
);
```

- 无 `conversation_id`，跨对话共享
- 由 LLM 在 `【自我认知】` 节中输出带 `[固定]` 标记的内容时写入
- GUI 设置页也可写入固定认知条目（如用户设定的姓名、偏好）

### 3.3 写操作改造

所有 `INSERT` 语句增加 `conversation_id` 参数：

```python
# 改造前
conn.execute("INSERT INTO user_messages(role,content,created_at) VALUES(?,?,?)", ...)

# 改造后
conn.execute(
    "INSERT INTO user_messages(conversation_id,role,content,created_at) VALUES(?,?,?,?)",
    (conversation_id, role, content, now)
)
```

`conversation_id` 来源：
- 来自 GUI 输入 JSON 中的 `conversation_id` 字段
- 来自 LLM 输出解析后的 `data.get("_session_id", "default")`

### 3.4 读操作改造（_gather_context）

```python
# 改造前
def _gather_context(self, data: dict) -> str:
    ...
    rows = conn.execute(
        "SELECT summary FROM event_summary ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()

# 改造后
def _gather_context(self, data: dict) -> str:
    conv_id = data.get("conversation_id", "default")
    ...
    # 1. 固定认知层（始终加载）
    fixed = conn.execute(
        "SELECT key, value FROM fixed_cognition ORDER BY updated_at DESC"
    ).fetchall()

    # 2. 对话层（按 conv_id 过滤）
    summaries = conn.execute(
        "SELECT summary FROM event_summary WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
        (conv_id, limit)
    ).fetchall()

    # 3. 共享记忆层（FAISS 跨对话检索，不变）
    memories = faiss_retrieve(query, ...)
```

---

## 四、对话切换协议

### 4.1 新增 `switch_conversation` 消息类型

```
GUI → 发送:
{
    "data_type": "switch_conversation",
    "conversation_id": "conv_002",
    "source": "gui",
    "timestamp": "..."
}

aaa → 收到后:
1. 保存当前对话上下文快照（可选）
2. 清除工具调用轮数计数（_tool_rounds）
3. 设置 self._current_conversation_id = "conv_002"
4. 后续所有查询按新 conv_id 过滤
```

### 4.2 消息发送流程扩展

```python
# 当前 send_text()
data = {
    "data_type": "text",
    "content": text,
    "source": "gui",
    "request_id": self._current_request_id,
    "timestamp": datetime.now().isoformat(),
}

# 改造后
data = {
    "data_type": "text",
    "content": text,
    "source": "gui",
    "conversation_id": self._current_conversation_id,  # 新增
    "request_id": self._current_request_id,
    "timestamp": datetime.now().isoformat(),
}
```

### 4.3 main.py 中的分发逻辑

在 `MyNode.process()` 的 `data_type` 分发中新增分支：

```python
def process(self, data: dict) -> dict:
    data_type = data.get("data_type", "")

    if data_type == "switch_conversation":
        return self._on_switch_conversation(data)

    # 现有逻辑不变...
```

---

## 五、变动的文件清单

| 文件 | 改动内容 | 工作量 |
|------|---------|:----:|
| `nodes/node_python_aaa_cognition/db.py` | 8 张表加列 + 新增 `fixed_cognition` 表 + 读写带 `conversation_id` | 2h |
| `nodes/node_python_aaa_cognition/main.py` | `_gather_context` 隔离查询 + 新增 `_on_switch_conversation` + `conversation_id` 传递 | 2h |
| `nodes/node_python_aaa_cognition/prompt.py` | Prompt 模板增加固定认知层占位符（可选） | 0.5h |
| `gui/core/message_manager.py` | send_text 带 `conversation_id` + 新增 `switch_conversation` 方法 | 0.5h |
| `gui/chat_page.py`（可选） | 对话切换 UI（如果实现多对话） | 2h |

**总工作量**: 约 5-7h（不含 GUI 对话列表）

---

## 六、向后兼容策略

1. **现有数据**：`conversation_id` 默认值为 `'default'`，现有数据不需要迁移
2. **现有 GUI**：不发送 `conversation_id` 的旧版 GUI 仍然有效，后端默认使用 `'default'`
3. **FAISS 索引**：`long_term_memory` 表的共享记忆检索不加 `conversation_id` 过滤，跨对话命中不受影响
4. **现有对话摘要**：`default` 对话的摘要继续工作，切换新对话时新摘要写入对应 `conv_id`

---

## 七、FAISS 索引缺失修复（附带）

当前 `memory.py` 的 `faiss_retrieve()` 只读不写。需要补一个周期性/触发式的索引构建：

```python
def faiss_build_index(db_path: str, index_path: str):
    """从 long_term_memory 表重建 FAISS 索引"""
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT id, content FROM long_term_memory").fetchall()
    conn.close()
    if not rows:
        return
    ids = []
    vectors = []
    for row_id, content in rows:
        vec = _text_to_vector(content)
        vectors.append(vec)
        ids.append(row_id)
    import faiss
    dim = len(vectors[0])
    index = faiss.IndexFlatIP(dim)
    index.add(np.array(vectors, dtype=np.float32))
    faiss.write_index(index, index_path)
```

可在 `_on_parsed()` 写入完成后异步调用，或由定时器每 N 分钟重建一次。

---

## 八、实施步骤（推荐顺序）

```
Step 1: db.py — 加 conversation_id 列 + 建 fixed_cognition 表
Step 2: main.py — _gather_context 按 conv_id 过滤 + 加载固定认知
Step 3: main.py — 新增 switch_conversation 消息处理
Step 4: prompt.py — 可选：固定认知占位符
Step 5: memory.py — 补充索引构建函数
Step 6: message_manager.py — 传递 conversation_id
Step 7: GUI 对话列表界面（如需）
```
