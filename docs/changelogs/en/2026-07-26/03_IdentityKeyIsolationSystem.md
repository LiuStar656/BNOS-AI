# 03 — Identity Key Multi-User Isolation System

> Date: 2026-07-26 | Files touched: 6 | Type: Architecture Upgrade

---

## 1. Problem

All AAA system data (self-cognition, other-cognition, feelings, event summaries, long-term memory, user profiles) was stored by `conversation_id` with no cross-user isolation. In a multi-user scenario, different users' cognitive data and memories would mix together.

## 2. Root Cause

1. Database tables had no user identity field; all data defaulted to `conversation_id = "default"`
2. MemOS semantic retrieval index did not distinguish users
3. LLM prompts did not identify the current user
4. GUI input layer carried no user identifier

## 3. Solution

### 3.1 Database Layer (db.py)

Added `identity_key` column to all 11 data tables with idempotent migration:

```python
# Migration: add identity_key column if missing
for table in tables:
    conn.execute(f"ALTER TABLE {table} ADD COLUMN identity_key TEXT")
    conn.execute(
        f"UPDATE {table} SET identity_key = 'gui:default' WHERE identity_key IS NULL"
    )
```

### 3.2 MemOS Retrieval Layer (memos.py)

Added `_entry_identity_keys` array to the vector index:

```python
# During rebuild, read identity_key
rows = conn.execute(
    "SELECT id, content, identity_key FROM long_term_memory WHERE ..."
).fetchall()

# During retrieval, filter by user
def retrieve(query, identity_key="gui:default"):
    for idx in top_idx:
        if _entry_identity_keys[idx] != identity_key:
            continue  # skip other users' memories
```

### 3.3 GUI Input Layer (message_manager.py)

```python
data = {
    "data_type": "text",
    "content": text,
    "source": "gui",
    "identity_key": "gui:default",
    ...
}
```

### 3.4 LLM Prompt Layer (prompt.py)

Added identity key to the context header:

```
### Input Context
Current user: {identity_key}
Your self-cognition: ...
```

### 3.5 Data Flow

```
GUI send_text(identity_key="gui:default")
  → AAA extracts identity_key
    → db writes with identity_key → user isolation
    → LLM prompt informs current user identity
    → MemOS retrieval filters by identity_key
```

## 4. Impact

- `db.py`: 11 tables +identity_key, migration, query updates
- `main.py`: Full pipeline identity_key propagation
- `memos.py`: Index stores identity_key, filtered retrieval
- `prompt.py`: Prompt injects identity_key
- `message_manager.py`: Input carries identity_key
