# 2026-08-07 Changelog

[Back to Index](../README.md)

---

## Entries

- [01 Logging System Implementation](./01_LoggingSystemImplementation.md)
- [02 Memory System Refactor: New Diary Table & Multi-Table Semantic Retrieval](./02_MemorySystemRefactorAndMultiTableRetrieval.md)

---

## Summary

| # | Core Change | Root Cause | Impact |
|---|------------|-----------|--------|
| 01 | Implemented batch-isolated logging system: GUI logs (dual-file handler + exception hook), engine logs (_p writes to file), node logs (child process stdout/stderr from DEVNULL to independent log files) | No persistent GUI logging; engine logs only print; node child process logs discarded by DEVNULL making crash diagnosis impossible | Each GUI launch creates an independent batch directory; app.log records runtime logs, error.log records errors; engine and node logs archived by batch; --log-dir parameter supported |
| 02 | Added `diaries` table decoupled from `event_summary`; MemOS index gained source-table dimension supporting retrieval across long_term_memory / user_messages / diaries; knowledge graph supports PCA coordinate export, incremental updates and configurable edge rules; removed cognition certainty-count logic | Diaries mixed into event_summary prevented independent management; single-table retrieval made recall incomplete; certainty counts had no real decision value; full graph rebuilds were slow and GUI could not reproduce layout | Diaries stored/queried independently; retrieval results carry date & mood context for fuller recall; knowledge_graph.json adds x/y, all_pairs, meta; incremental graph builds + recompute_graph_edges without re-encoding |

---

### 01 Logging System Implementation

See [01_LoggingSystemImplementation.md](./01_LoggingSystemImplementation.md).

### 02 Memory System Refactor: New Diary Table & Multi-Table Semantic Retrieval

See [02_MemorySystemRefactorAndMultiTableRetrieval.md](./02_MemorySystemRefactorAndMultiTableRetrieval.md).

---

## Modified Files

### New Files

| File | Ref |
|------|-----|
| `gui/core/logger.py` | #01 |
| `docs/design/[OK]-日志系统设计方案.md` | #01 |

### Modified Files

| File | Change | Ref |
|------|--------|-----|
| `bnos_runtime/standalone_runner.py` (source) | `start()` added `log_dir` param, node stdout/stderr written to `nodes/{node_id}.log` | #01 |
| `bnos_runtime/engine.py` (source) | `PipelineRunner` added `log_dir` param; `_p()` writes to file; `--log-dir` CLI param | #01 |
| `bnos_runtime/standalone_runner.py` (AI project) | Synced from source, retained JS node support | #01 |
| `bnos_runtime/engine.py` (AI project) | Synced from source | #01 |
| `gui/main.py` | Initialize logging on startup, pass `--log-dir` to engine | #01 |
| `gui/pages/node_page.py` | `_pipe_engine_output` added file writing; in-page engine startup gets batch directory | #01 |
| `db.py` | Added diaries table; self/other cognition writes no longer dedupe-merge (direct INSERT) | #02 |
| `memos.py` | Index gained source-table dimension (_entry_tables); 3-table retrieval; model load timeout; graph incremental build + PCA coordinates + configurable edge rules; new recompute_graph_edges | #02 |
| `main.py` | Diary writes to diaries table; removed certainty-count queries; event summary date prefix; clear excludes sqlite_ system tables | #02 |
| `diary.py` | `_diary_exists` queries diaries table | #02 |
| `prompt.py` | Removed certainty-count placeholders | #02 |
| `listener.py` | Logseq backfill queries dynamic table names | #02 |
| `output_default.json` / `output_logseq.json` / `output_prompt.json` / `output_reply.json` | Sample data synced | #02 |

---

## File Change Stats

| Metric | #01 | #02 |
|--------|:---:|:---:|
| Files involved | 7 | 10 |
| Lines added | ~180 | 465 |
| Lines removed | ~30 | 101 |
| **Net change** | **~150** | **~364** |

---

**Last updated**: 2026-08-07
