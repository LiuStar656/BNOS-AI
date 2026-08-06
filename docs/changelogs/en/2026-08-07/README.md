# 2026-08-07 Changelog

[Back to Index](../README.md)

---

## Entries

- [01 Logging System Implementation](./01_LoggingSystemImplementation.md)

---

## Summary

| # | Core Change | Root Cause | Impact |
|---|------------|-----------|--------|
| 01 | Implemented batch-isolated logging system: GUI logs (dual-file handler + exception hook), engine logs (_p writes to file), node logs (child process stdout/stderr from DEVNULL to independent log files) | No persistent GUI logging; engine logs only print; node child process logs discarded by DEVNULL making crash diagnosis impossible | Each GUI launch creates an independent batch directory; app.log records runtime logs, error.log records errors; engine and node logs archived by batch; --log-dir parameter supported |

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

---

## File Change Stats

| Metric | #01 |
|--------|:---:|
| Files involved | 7 |
| Lines added | ~180 |
| Lines removed | ~30 |
| **Net change** | **~150** |

---

**Last updated**: 2026-08-07
