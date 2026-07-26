# 04 — Database Write Fix & Long-Term Memory Format Correction

> Date: 2026-07-26 | Files touched: 4 | Type: Bug Fix

---

## 1. Problem

Multiple database tables (`feelings`, `self_cognition`, `other_cognition`, `user_facts`) had silent write failures — the GUI data browser showed stale data. TTS read emotion tags (e.g., `<惊讶>`) aloud. Long-term memory only stored user input without AI response context.

## 2. Root Cause

1. **`_dedup_and_merge` hardcoded column name**: Used `SELECT content FROM [{table}]`, but `event_summary` uses `summary` column, causing `sqlite3.OperationalError: no such column: content` silently caught
2. **TTS emotion tag regex mismatch**: LLM output uses angle brackets (`<惊讶>`), but TTS regex matched square brackets (`[惊讶]`)
3. **Long-term memory only stored user input**: `_write` only wrote user content to `long_term_memory`, not AI responses

## 3. Solution

### 3.1 _dedup_and_merge Column Fix (db.py)

Added `column` parameter:

```python
def _dedup_and_merge(table, conv_id, new_content, conn, importance=3, column="content"):
    old = conn.execute(
        f"SELECT [{column}] FROM [{table}] WHERE ...",
        (conv_id,),
    ).fetchone()
```

Call with `column="summary"` for event_summary.

### 3.2 TTS Regex Fix (main.py)

```python
# Before
m = re.match(r"^\[([\u4e00-\u9fff]{2,4})]", text)

# After
m = re.match(r"^<([\u4e00-\u9fff]{2,4})>", text)
```

### 3.3 Long-Term Memory Format (db.py)

```python
if user_input:
    combined = f"user: {user_input}\nassistant: {val}"
    conn.execute(
        "INSERT INTO long_term_memory(...) VALUES(..., combined, ...)")
```

## 4. Impact

- `db.py`: `_dedup_and_merge` parameter, long-term memory write logic
- `node_python_tts/main.py`: Emotion tag regex fix
- `scripts/check_db_tables.py`: New debug script

## 5. Verification

1. Send message with emotion tag, TTS should not read the tag
2. Check all cognition tables for correct writes
3. Check `long_term_memory` for `user: {input}\nassistant: {response}` format
