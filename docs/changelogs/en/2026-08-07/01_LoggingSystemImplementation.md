# 01 — Logging System Implementation

> Date: 2026-08-07 | Files involved: 7 | Change type: Infrastructure addition

---

## 1. Problem Description

The BNOS AI project lacked a unified logging system with the following pain points:

1. **No persistent GUI logging**: Only `print()` output to console, lost after window close
2. **Engine logs unreadable**: `engine.py`'s `_p()` method only prints, no history after crash
3. **Node logs completely discarded**: Node child process `stdout` and `stderr` set to `DEVNULL` in `standalone_runner.py`, making node-internal errors (Python traceback, JS exceptions) invisible
4. **No batch isolation**: Multiple launch sessions mixed together, hard to debug

## 2. Root Cause Analysis

1. **GUI layer**: No Python `logging` module file handler configured
2. **Engine layer**: `_p()` method only wraps `print()`, no file writing channel
3. **Node layer**: `stdout=DEVNULL, stderr=DEVNULL` — deliberate choice to avoid console spam, sacrificing observability
4. **Architecture gap**: No "launch batch" concept — each GUI launch should create an independent log directory tied to its lifecycle

## 3. Solution Design

### 3.1 Overall Architecture

```
┌──────────────────────────────────────────────┐
│  GUI Process                                │
│  ┌────────────────────────────────────────┐ │
│  │ gui/core/logger.py (new)               │ │
│  │  ├─ Creates batch directory on startup  │ │
│  │  ├─ app.log (INFO+)                    │ │
│  │  ├─ error.log (ERROR+)                │ │
│  │  └─ sys.excepthook → error.log         │ │
│  └────────────────────────────────────────┘ │
│         │                                    │
│         │ subprocess.Popen + --log-dir      │
│         ▼                                    │
│  ┌────────────────────────────────────────┐ │
│  │ bnos_runtime (modified)                │ │
│  │  ├─ engine.log  ← _p() writes          │ │
│  │  ├─ nodes/{node_id}.log ← node proc    │ │
│  │  └─ engine_pipe.log ← pipe output      │ │
│  └────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
```

### 3.2 Directory Structure

```
logs/
  └── 20250807_143052/              ← Launch batch
      ├── app.log                   ← GUI runtime logs
      ├── error.log                 ← GUI error logs
      └── engine/
          ├── engine.log            ← Engine logs (_p writes)
          ├── engine_pipe.log       ← Engine stdout pipe
          └── nodes/
              ├── node_chat.log     ← Node child process logs
              └── ...
```

### 3.3 GUI Logging System (gui/core/logger.py)

New `gui/core/logger.py` with responsibilities:
- `setup_gui_logger()`: Creates batch directory, configures dual file handler (app.log + error.log) + console handler
- `get_logger(name)`: Gets module-level logger
- `get_batch_dir()`: Gets current batch directory
- `sys.excepthook`: Uncaught exceptions written to error.log

```python
# Usage example
from gui.core.logger import get_logger
_log = get_logger("knowledge_graph")
_log.info("Graph loaded, %d nodes total", n)
_log.error("Node rendering failed: %s", e)
```

### 3.4 Engine Logging (bnos_runtime/engine.py)

`PipelineRunner` gains optional `log_dir` parameter:

```python
# Before
def __init__(self, pipeline_path: Path):
    ...
def _p(self, *args, **kwargs):
    print(*args, **kwargs, flush=True)

# After
def __init__(self, pipeline_path: Path, log_dir: Path | None = None):
    ...
    self._log_fh = open(log_dir / "engine.log", "a") if log_dir else None
def _p(self, *args, **kwargs):
    print(*args, **kwargs, flush=True)
    if self._log_fh:
        print(*args, **kwargs, flush=True, file=self._log_fh)
```

Also supports CLI parameter `--log-dir`:
```bash
python -m bnos_runtime.engine pipeline.json --serve --log-dir ./logs/20250807/engine
```

### 3.5 Node Logging (bnos_runtime/standalone_runner.py)

`start()` method gains optional `log_dir` parameter, node child process `stdout`/`stderr` changed from `DEVNULL` to log file:

```python
# Before
def start(self) -> tuple[str, subprocess.Popen]:
    proc = subprocess.Popen(
        [str(python_exe), entry],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ...
    )

# After
def start(self, log_dir: Path | None = None) -> tuple[str, subprocess.Popen]:
    log_fh = None
    if log_dir:
        node_log = Path(log_dir) / "nodes" / f"{self.node_id}.log"
        log_fh = open(node_log, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [str(python_exe), entry],
        stdout=log_fh if log_fh else subprocess.DEVNULL,
        stderr=log_fh if log_fh else subprocess.DEVNULL,
        ...
    )
```

**Backward compatible**: When `log_dir=None`, behavior unchanged (DEVNULL or inherited from parent)

### 3.6 Integration Point (gui/main.py)

```python
def main():
    # Initialize logging
    from gui.core.logger import setup_gui_logger, get_logger
    _batch_dir = setup_gui_logger()
    _log = get_logger("main")
    _log.info("BNOS AI launched — batch dir: %s", _batch_dir)

    # Pass batch log directory when starting engine
    _engine_log_dir = _batch_dir / "engine"
    _start_engine(log_dir=_engine_log_dir)
```

## 4. Implementation Phases

| Phase | Content | Status |
|-------|---------|--------|
| Phase 1 | Modify source bnos_runtime (standalone_runner.py + engine.py) | ✅ Done |
| Phase 2 | Sync to AI project bnos_runtime | ✅ Done |
| Phase 3 | Create gui/core/logger.py | ✅ Done |
| Phase 4 | Integrate gui/main.py and node_page.py | ✅ Done |

## 5. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Log file disk usage | Low | Medium | Periodic cleanup of old batches |
| Node log file handle leak | Low | Medium | `log_fh` auto-released on child process exit |
| Engine log file write blocking | Very low | Low | Uses `flush=True` + Python file buffering |
| BNOS editor sync issue | Low | Low | `log_dir` is optional param, behavior unchanged when not passed |

## 6. Impact Scope

| Module | Impact |
|--------|--------|
| gui/core/logger.py | New file, no impact on existing code |
| gui/main.py | Startup flow adds logging initialization |
| gui/pages/node_page.py | Engine output pipe adds file writing |
| bnos_runtime/standalone_runner.py | `start()` method signature change (optional param, backward compatible) |
| bnos_runtime/engine.py | `PipelineRunner` constructor change (optional param, backward compatible); new `--log-dir` CLI param |
| BNOS editor | Pass `log_dir=None` when syncing, behavior completely unchanged |

## 7. Verification

1. Launch GUI → Check if batch directory created under `logs/`
2. Check if `app.log` contains startup logs
3. Check if `error.log` is empty (normal case)
4. Check if `engine/engine.log` contains engine startup info
5. Check if `engine/nodes/` contains log files for each node
6. Trigger exception → Check if `error.log` captured the stack trace
7. Restart GUI → Check if new batch directory created, old directory preserved

---

**Last updated**: 2026-08-07
