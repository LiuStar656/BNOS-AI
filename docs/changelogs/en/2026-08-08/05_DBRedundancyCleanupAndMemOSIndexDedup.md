# Database Redundancy Cleanup & MemOS Index Deduplication

## Problem

A per-table audit confirmed redundancy: `retrieval_log` was never written to (a dead table); the MemOS semantic index indexed both `user_messages` and `long_term_memory`, so dialogue content was indexed twice and retrieval returned duplicates; the data browser had untranslated tables (mood_value, personality_seed) plus stale translations for the removed table.

## Root Cause

- `retrieval_log` was a leftover from an early design with no write path — a meaningless table.
- Dialogue is already stored as merged QA in `long_term_memory` (source='exchange'); indexing `user_messages` (raw conversation) as well produced two vectors for the same content.
- `TABLE_LABELS` in the data browser was not synced with new/removed tables.

## Solution

1. **`nodes/node_python_aaa_cognition/db.py`**: v5.4 idempotent migration `DROP TABLE IF EXISTS retrieval_log`, and the table-creation statement was removed.
2. **`nodes/node_python_aaa_cognition/memos.py`**: `rebuild_index` / `retrieve` drop the `user_messages` source, indexing only `long_term_memory` + `diaries`; deleted the dead `_fetch_feeling` code.
3. **`gui/widgets/knowledge_panel.py`**: `TABLE_LABELS` adds mood_value / personality_seed translations and removes the `retrieval_log` entry.

## Impact

| File | Change |
|------|--------|
| `nodes/node_python_aaa_cognition/db.py` | v5.4 migration drops retrieval_log (creation statement also removed) |
| `nodes/node_python_aaa_cognition/memos.py` | Index source drops user_messages (only long_term_memory + diaries); `_fetch_feeling` dead code removed |
| `gui/widgets/knowledge_panel.py` | Translations added for mood_value/personality_seed, retrieval_log entry removed |

## Verification

- DB confirms `retrieval_log` no longer exists (fresh DBs never create it; old DBs migrate it away).
- After index rebuild, the same dialogue content has one index entry; retrieval returns no duplicates.
- Every table shown in the data browser has a Chinese label.
