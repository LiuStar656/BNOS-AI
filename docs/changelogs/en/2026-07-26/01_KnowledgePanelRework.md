# 01 — Knowledge Panel Rework & Auto-Refresh

> Date: 2026-07-26 | Files touched: 2 | Type: Enhancement

---

## 1. Problem

The knowledge panel used hardcoded JSON as its data source and could not read the latest records from the database in real time. When switching tabs to the knowledge page, data remained stale from the last load unless the user manually refreshed or waited for the 10-second timer.

## 2. Root Cause

1. `KnowledgePanel.__init__` only called `_load_data()` once during construction
2. AAA node continuously writes new records to the database, but the panel had no update notification mechanism
3. The 10-second timer provided periodic refresh, but page switching did not trigger an immediate refresh

## 3. Solution

### 3.1 Database-Driven Refactor (knowledge_panel.py)

Replaced JSON file reads with direct SQLite queries:

```python
# Before: reading JSON files
with open("data.json") as f:
    self._data = json.load(f)

# After: querying from database
conn = sqlite3.connect(dbp)
rows = conn.execute("SELECT id, content, created_at FROM long_term_memory ORDER BY id DESC LIMIT 50").fetchall()
```

### 3.2 Page-Switch Auto-Refresh (main_window.py)

Added a trigger in `_switch_page` method for the knowledge page:

```python
def _switch_page(self, page_id: str):
    ...
    self._slide_animation(target, direction)
    if page_id == "knowledge" and hasattr(target, "_load_data"):
        target._load_data()
```

Refresh logic is added in both code paths (animation in progress and normal animation).

## 4. Impact

- `gui/widgets/knowledge_panel.py`: Core refactor
- `gui/main_window.py`: Page-switch trigger added

## 5. Verification

1. Launch GUI, switch to knowledge page, confirm data loads from database
2. Send a chat message (triggers AAA DB write), switch away and back, confirm updated data
3. Verify the 10-second auto-refresh timer still works
