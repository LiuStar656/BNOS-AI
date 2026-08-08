# Knowledge Graph Semantic Data Filtering & "Ideas" Category

## Problem

The knowledge graph ingested data from every database table, causing three issues:

1. **Noise nodes**: feelings records with only a mood and no thought (e.g. just "开心"); long_term_memory entries with `role='tool'` tool returns (e.g. "结果"), `source='diary'` full diary texts, and fragments ≤10 chars — none have semantic distinctiveness.
2. **Transient/metadata tables should not be in the graph**: location coordinates, mood statistics, config key-values are not semantic memories; the graph should only show the AI's long-term semantic memory of the user and itself.
3. **"Ideas" were invisible**: the thought field of the feelings table appeared under the "情感" (Emotion) label in the data browser, and graph hover showed mood words as categories — users could not see "想法" (Ideas).

## Root Cause

- `MEMORY_QUERIES` had no quality filter: feelings had no condition and long_term_memory only filtered by `status='active'`, so low-distinction records entered the graph.
- `diaries` was missing — full diary texts entered via `source='diary'` in long_term_memory instead of the diaries table, and the graph sources did not include diaries.
- feelings nodes used mood words as their category, inconsistent with table name and content, so the GUI could not identify them as "ideas".

## Solution

### Source filtering (`nodes/node_python_aaa_cognition/memos.py`)

1. **`MEMORY_QUERIES` v4 semantic filtering**:
   - feelings only keeps records where `thought IS NOT NULL AND thought != ''` (pure mood words removed);
   - long_term_memory drops `role='tool'` / `source='diary'` / requires `LENGTH(content) > 10` (keeps exchange merged QA and seed backgrounds);
   - **new diaries source** (`LENGTH(content) > 10`);
   - explicitly excluded: user_messages (raw dialogue noise), location_history, fixed_cognition, self_info, personality_seed, mood_trend, mood_value (transient/metadata).
2. **`GRAPH_INDEX_VERSION` 3→4**: triggers full rebuild to purge old-index entries that no longer match the filters.

### "Ideas" category (v5)

3. **`memos.py`**: feelings node category changed from `mood` to `'feelings'` (GUI shows "想法"); `GRAPH_INDEX_VERSION` 4→5 triggers another full rebuild.
4. **`gui/widgets/knowledge_panel.py`**: `TABLE_LABELS["feelings"]` changed from "情感" to "想法" (filter button and card label).
5. **`gui/widgets/knowledge_graph.py`**: new `CATEGORY_LABELS` mapping; hovering an ideas node shows `[想法]` plus the idea text.

## Impact

| File | Change |
|------|--------|
| `nodes/node_python_aaa_cognition/memos.py` | MEMORY_QUERIES v4 semantic filtering + diaries added; GRAPH_INDEX_VERSION 3→4; feelings category → 'feelings'; GRAPH_INDEX_VERSION 4→5 |
| `gui/widgets/knowledge_panel.py` | TABLE_LABELS feelings "情感"→"想法" |
| `gui/widgets/knowledge_graph.py` | CATEGORY_LABELS mapping + hover tooltip shows "想法" |

## Verification

- SQL filters checked one by one: feelings 21 records (all with thought), long_term_memory 17 records (no tool/diary/short fragments), diaries included (currently empty table).
- After full rebuild, knowledge_graph.json: 117 nodes; all 21 feelings nodes have category `'feelings'`; zero short-content leftovers.
- All three files compile cleanly.
- GUI: the data browser shows an "想法" filter; hovering an ideas node shows `[想法]`.
