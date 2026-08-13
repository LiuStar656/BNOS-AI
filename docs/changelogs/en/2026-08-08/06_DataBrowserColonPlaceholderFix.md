# Data Browser "Colon-Only" Placeholder Fix

## Problem

Many rows in the data browser appeared as a lone colon (e.g. `"content": ""`) with
nothing after it. Investigation found 8 `user_messages` rows stored as JSON-wrapped
**empty messages**: `{"data_type": "text", "content": "", "source": "text"}`.

## Root Cause

Two layers contributed:

1. **Write layer** `db.py` `_write`: `c = data.get("content", "") or json.dumps(data)`.
   When `content` was an empty string (falsy), the whole message dict was JSON-serialized
   into `user_messages`, producing `{"data_type":"text","content":"",...}` junk rows.
2. **Display layer** `knowledge_panel.py` `_read_db`: rendered the `content` column
   verbatim, so the empty JSON displayed as `"content": ""` — the "colon with nothing
   after it" placeholder.

Pre-fix verification showed the `_read_db()` extraction chain (mood/thought safe join)
already had zero colon leftovers, confirming the colon came from these JSON rows
themselves, not from the generic extraction logic.

## Solution

### 1. Plug the source (`db.py` v5.5): empty user messages are not persisted

```python
# Old: empty content got JSON-serialized into the table
c = data.get("content", "") or json.dumps(data, ensure_ascii=False)

# New: empty user messages are dropped
c = data.get("content", "")
if role == "user" and (c is None or str(c).strip() == ""):
    conn.close()
    return
if not c:
    c = json.dumps(data, ensure_ascii=False)
```

### 2. Tolerate existing junk (`knowledge_panel.py` v1.6): parse JSON-wrapped messages

```python
# New, right after the extraction chain: unwrap JSON; empty content is skipped below
if isinstance(content, str) and content.lstrip().startswith("{"):
    try:
        inner = json.loads(content)
        if isinstance(inner, dict) and "content" in inner:
            content = inner.get("content") or ""
    except Exception:
        pass
```

Empty parsed content then hits the existing `if not content ... continue`, so the
junk rows no longer show.

## Impact

| File | Change |
|------|--------|
| `nodes/node_python_aaa_cognition/db.py` | `_write` returns early for empty user messages (v5.5) |
| `gui/widgets/knowledge_panel.py` | `_read_db` unwraps JSON messages, skips empty content (v1.6) |

The 8 existing JSON junk rows are hidden (data kept, display filtered);
no new empty-message JSON rows will be created.

## Verification

- Write layer: `_write` with `{"data_type":"text","content":"","source":"text"}`
  (role="user") returns immediately; `user_messages` gains no row.
- Display layer: reproduced `_read_db()` output — of 296 displayed rows,
  0 JSON junk rows and 0 colon-only rows.
