# 03 — Identity Key 多用户隔离系统

> 日期：2026-07-26 | 涉及文件：6 | 变更类型：架构升级

---

## 一、问题描述

AAA 系统的所有数据（自我认知、他人认知、情感、事件摘要、长期记忆、用户画像等）都按 `conversation_id` 分组存储，没有跨用户隔离机制。多用户场景下，不同用户的认知数据和记忆会混淆。

## 二、根因分析

1. 数据库表没有记录用户身份的字段，所有数据默认归入 `conversation_id = "default"`
2. MemOS 语义检索索引不区分用户，检索时可能返回其他用户的数据
3. LLM 提示词未告知当前对话用户身份，无法区分不同用户
4. GUI 输入层未携带用户标识

## 三、修改方案

### 3.1 数据库层 (db.py)

向 11 张数据表添加 `identity_key` 列，实现幂等迁移：

```python
_TABLES_NEED_CONV_ID = [
    ("user_messages", True, True),
    ("self_cognition", True, True),     # +identity_key
    ("other_cognition", True, True),
    ("feelings", True, True),
    ("event_summary", True, True),
    ("user_facts", True, True),
    ("self_info", True, True),
    ("long_term_memory", True, True),
    ("mood_trend", True, True),
    ("user_messages", True, True),
]
```

迁移逻辑在 `v3_ensure_identity_key.py` 中：
- 检查表是否有 `identity_key` 列，没有则 `ALTER TABLE ADD COLUMN`
- 已有数据的 `identity_key` 为空时，回填 `"gui:default"`
- 所有查询操作按 `identity_key` 过滤

### 3.2 MemOS 检索层 (memos.py)

在向量索引中添加 `_entry_identity_keys` 数组，每个条目记录所属用户：

```python
# 索引重建时读取 identity_key
rows = conn.execute(
    "SELECT id, content, identity_key FROM long_term_memory WHERE ..."
).fetchall()

# 检索时按用户过滤
def retrieve(query, identity_key="gui:default"):
    for idx in top_idx:
        if _entry_identity_keys[idx] != identity_key:
            continue  # 跳过其他用户的记忆
```

### 3.3 GUI 输入层 (message_manager.py)

```python
data = {
    "data_type": "text",
    "content": text,
    "source": "gui",
    "source_id": "gui_default",        # ← 新增 identity_key
    "identity_key": "gui:default",
    "conversation_id": self._state.current_conversation_id,
    "request_id": self._current_request_id,
}
```

### 3.4 LLM 提示词层 (prompt.py)

在 `_CONTEXT_HEADER` 第一行加入当前用户身份：

```
### 输入上下文
当前对话用户：{identity_key}
你的自我认知：{self_cognition} [确认次数: {self_certainty}]
...
```

### 3.5 数据流

```
GUI send_text(identity_key="gui:default")
  → AAA _on_text() 提取 identity_key
    → db.write_async(identity_key=...) → 所有表按用户隔离
    → LLM prompt 告知当前用户身份
    → LLM 回复 → AAA write_parsed_async(identity_key=...)
    → MemOS rebuild_index(identity_key=...) → 检索只返回该用户记忆
```

## 四、影响范围

- `db.py`：11 张表加 identity_key 列、迁移逻辑、全量查询更新
- `main.py`：全链路传递 identity_key
- `memos.py`：索引存储 identity_key、按用户过滤
- `prompt.py`：提示词注入 identity_key
- `message_manager.py`：输入携带 identity_key

## 五、验证方法

1. 启动系统并发送消息，确认数据库表中 `identity_key` 列正确填充
2. 切换不同 identity_key 发送消息，确认认知/画像/情感数据互不混淆
3. 长期记忆检索只返回当前用户的记忆
4. LLM 提示词上下文显示正确的当前用户身份
5. 旧数据兼容：未设置 identity_key 的数据自动归为 "gui:default"
