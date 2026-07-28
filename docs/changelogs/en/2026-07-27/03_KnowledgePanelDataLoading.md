# 03 — Knowledge Panel Data Loading & Display Optimization

> Date: 2026-07-27 | Files touched: 4 | Type: Enhancement

---

## 1. Problem

1. The knowledge panel filter buttons were hardcoded with a static list of table names. When new cognition tables were added to the database by the AAA node, the filter buttons did not automatically include them — they had to be manually added to `TABLE_LABELS` in the source code.
2. Data display only showed the `content` column. Records storing data in `period`, `keywords`, or `key=value` formats (e.g., mood trends, search logs) showed empty or uninformative content.
3. Label text on filter buttons did not always match the actual table content, causing user confusion.

## 2. Root Cause

1. `_build_list_view()` used a hardcoded `TABLE_LABELS` dict and a static list of categories; it never queried `sqlite_master` to discover available tables dynamically.
2. The `_read_db()` function had a single fallback chain that only checked `content` then `summary` — it did not handle period-based records (`mood_trend`), keyword-based records (`retrieval_log`), or key-value records (`self_info`).
3. The `TABLE_LABELS` mapping was manually maintained and could drift from actual database schema.

## 3. Solution

### 3.1 Dynamic DB Table Scanning (knowledge_panel.py)

Replaced the hardcoded filter button list with a dynamic query against `sqlite_master`:

```python
# Before: hardcoded categories
categories = ["all", "diaries", "event_summary", "feelings", ...]

# After: dynamic scan from actual database
conn = sqlite3.connect(_DB_PATH)
db_tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name"
).fetchall()]
conn.close()
categories = ["all"] + db_tables
```

Each discovered table name is looked up in `TABLE_LABELS` for a human-readable label (falling back to the raw table name if no label exists).

### 3.2 Content Display Format Expansion

Extended `_read_db()` to handle additional column formats:

```python
# New period format (e.g., mood_trend records)
if record.get("period"):
    content = f"[{record['period']}] {record.get('dominant_mood', '')} ({record.get('avg_mood_value', '')})"

# New keywords format (e.g., retrieval_log records)
if record.get("keywords"):
    content = f"{record['keywords']} → {record.get('result_count', 0)} 条结果"
```

The content extraction fallback chain was also expanded to include `mood + thought`, `key = value`, and `dominant_mood` before falling through to empty:

```python
content = (
    record.get("content")
    or record.get("summary")
    or record.get("mood", "") + ": " + record.get("thought", "")
    or str(record.get("key", "")) + " = " + str(record.get("value", ""))
    or record.get("dominant_mood", "")
    or record.get("keywords", "")
    or ""
)
```

### 3.3 Label Text Updates

The `TABLE_LABELS` dictionary was updated with clearer labels for existing and new tables.

### 3.4 New Design Documents

Three new design docs were created to complement the data/knowledge system:

- **Environment/Memory Perception System** (`[PLAN]-AI世界感知记忆系统设计方案.md`, 134 lines): Design for an AI world-awareness and environmental memory perception subsystem.
- **Soul-of-Waifu Component Analysis** (`[ANALYSIS]-Soul-of-Waifu组件复用分析.md`, 661 lines): Reusability analysis of the Soul-of-Waifu architecture.
- **Airi-SillyTavern Component Analysis** (`[ANALYSIS]-Airi-SillyTavern组件复用分析.md`, 928 lines): Reusability analysis of the Airi-SillyTavern project.

## 4. Impact

- `gui/widgets/knowledge_panel.py`: Dynamic DB-driven filter buttons; content display supports period, keyword, key-value, and mood formats; updated labels
- `docs/design/[PLAN]-AI世界感知记忆系统设计方案.md`: New (134 lines)
- `docs/design/[ANALYSIS]-Soul-of-Waifu组件复用分析.md`: New (661 lines)
- `docs/design/[ANALYSIS]-Airi-SillyTavern组件复用分析.md`: New (928 lines)

## 5. File Change List

| File | Lines Changed | Description |
|------|:------------:|-------------|
| `gui/widgets/knowledge_panel.py` | ~60 | Dynamic DB table scanning; content display formats (period, keywords, key=value, mood); updated labels |
| `docs/design/[PLAN]-AI世界感知记忆系统设计方案.md` | 134 | New — environment/memory perception design |
| `docs/design/[ANALYSIS]-Soul-of-Waifu组件复用分析.md` | 661 | New — component reuse analysis |
| `docs/design/[ANALYSIS]-Airi-SillyTavern组件复用分析.md` | 928 | New — component reuse analysis |
