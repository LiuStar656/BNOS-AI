# 02 — Memory System Refactor: New Diary Table & Multi-Table Semantic Retrieval

> Date: 2026-08-07 | Files: 10 | Type: Architecture Refactor
>
> Commit: `f116292` refactor: 重构记忆系统，新增日记表与多表语义检索

---

## 1. Problem Description

The AAA cognition node's memory system had the following issues:

1. **Diary data mixed storage**: Diaries were written to `event_summary` distinguished by a `[diary date]` prefix marker, mixing event summaries with diary data, making independent query/statistics/retrieval impossible
2. **Single-table retrieval**: MemOS semantic retrieval only indexed the `long_term_memory` table; conversation originals (`user_messages`) and diaries could not participate in recall, resulting in incomplete memory retrieval
3. **Certainty-count noise**: The prompt exposed "self/other cognition" confirmation counts (`certainty_*`), which provided no real value to LLM decisions and added redundant fields
4. **Knowledge graph index could not incrementally update**: The graph was fully rebuilt every time (expensive with large data); node coordinates were missing so the GUI had to lay out nodes itself, and edge counts were not configurable

## 2. Root Cause Analysis

1. The diary feature was initially implemented as "event summaries with markers" — a temporary approach without an independent data model for diaries
2. The MemOS index only maintained `(entry_ids, identity_keys)` arrays, lacking a "source table" dimension, so entries could not be distinguished by table
3. The `certainty` field was designed early on to evaluate cognition reliability but never participated in any decision logic
4. Graph export only output `entries + edges`, without vector-reduction coordinates and full similarity pairs, so the GUI could not reproduce the layout

## 3. Changes

### 3.1 New `diaries` table (db.py)

`ensure()` now creates the `diaries` table, fully separated from `event_summary`:

```sql
CREATE TABLE IF NOT EXISTS diaries(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL DEFAULT 'default',
    date TEXT NOT NULL,
    content TEXT NOT NULL,
    mood TEXT,
    created_at TEXT NOT NULL DEFAULT(datetime('now','localtime')),
    identity_key TEXT NOT NULL DEFAULT 'gui:default');
```

### 3.2 Diary detection & write refactor (diary.py / main.py)

- `diary._diary_exists`: changed from "LIKE `%[diary date]%` in `event_summary`" to a direct `diaries WHERE date=?` query
- `main._on_diary_response`: changed from "write `event_summary` (with marker, truncated to 500 chars)" to "INSERT `diaries` (content limit raised to 2000, includes mood)"

### 3.3 Remove certainty-count logic (db.py / main.py / prompt.py)

- `self_cognition` / `other_cognition` no longer dedupe-merge; direct INSERT (consistent with adaptive-agent-architecture), `_increment_certainty` retained
- `_gather_context` removed `self_certainty` / `other_certainty` queries
- `prompt.py` removed `[确认次数: {self_certainty}]` / `[确认次数: {other_certainty}]` placeholders

### 3.4 MemOS multi-table semantic retrieval (memos.py)

The index gained a "source table" dimension:

```python
_entry_tables = []   # list[str]: source table of each entry
```

- `rebuild_index` collects entries from **long_term_memory / user_messages / diaries** (dedup by `(table, id)`)
  - `user_messages` indexed as `[role] content`
  - `diaries` indexed as `[diary] content (心情: mood)`
- `retrieve` / `retrieve_raw` return the source `table`, and look up the original text per table:
  - `user_messages` → appended "当时心情" (mood at that time) via `_fetch_feeling`
  - `diaries` → appended date and mood
  - `long_term_memory` → appended creation date
- Unified result format `[date | similarity] content` for prompt injection
- `main.py` / `listener.py` dynamically build table names from `r.get("table")` (`SELECT content FROM [{tbl}] WHERE id=?`)

### 3.5 MemOS index robustness (memos.py)

- `_get_model(timeout)` supports timeout control: `timeout=0` non-blocking fast check (returns None if model not ready), avoiding blocking the inference pipeline
- Index files gained an `entry_tables` field; loading is backward-compatible with old indexes (defaults all entries to `long_term_memory`)
- `_encode` / `retrieve` return None / empty when the model is not ready instead of raising

### 3.6 Knowledge graph PCA visualization & configurable edge rules (memos.py)

- Graph index format versioned (`GRAPH_INDEX_VERSION = 2`); version mismatch triggers full rebuild
- `rebuild_knowledge_index` supports **incremental updates**: loads `_load_knowledge_index` cache first, encodes only new entries; added `force_full` param
- New `_compute_2d_coordinates`: SVD/PCA reduces high-dim vectors to 2D, normalized to a 1500×1200 canvas, exported as `x/y` on each entry
- Configurable edge rules: `max_edges_per_node` (1–20, default 5), `threshold` (default 0.6)
- Extended export: `all_pairs` (all similarity pairs for GUI force layout), `sim_matrix`, `meta` (node/edge stats, layout, timestamp)
- New `recompute_graph_edges`: recomputes edges & coordinates only (no re-encoding), for quick refresh when the GUI adjusts parameters

### 3.7 Other optimizations

- `history_summary` event summaries now include a creation-date prefix `[YYYY-MM-DD]` (main.py)
- `db_command clear` excludes `sqlite_%` system tables, clearing only user tables (main.py)
- Updated 4 sample output files: `output_default.json` / `output_logseq.json` / `output_prompt.json` / `output_reply.json`

## 4. Impact

| File | Change |
|------|--------|
| `db.py` | Added diaries table; cognition writes no longer dedupe-merge |
| `memos.py` | Index gained source-table dimension; 3-table retrieval; model timeout; graph incremental + PCA + configurable edges; recompute_graph_edges (core, +490 lines) |
| `main.py` | Diary writes to diaries table; removed certainty counts; summary with dates; clear excludes system tables |
| `diary.py` | `_diary_exists` queries diaries table |
| `prompt.py` | Removed certainty-count placeholders |
| `listener.py` | Logseq backfill queries dynamic table names |
| `output_*.json` × 4 | Sample data synced |

## 5. Verification

1. First conversation triggers diary write; confirm records appear in `diaries` and `event_summary` is no longer mixed with diaries
2. Next-day first message triggers `_diary_exists`; confirm the same day's diary is not duplicated
3. Include historical keywords in conversation; confirm `retrieve` recalls from `user_messages` / `diaries` with "当时心情" attached
4. Run `rebuild_knowledge_index`; confirm `knowledge_graph.json` contains `x/y`, `all_pairs`, `meta`; rerun hits cache (skips when no new entries)
5. Call `recompute_graph_edges` with a new `max_edges_per_node`; confirm the graph updates without re-encoding
6. Check prompt output for the absence of "确认次数"; `db_command clear` keeps system tables (e.g. sqlite_sequence)
