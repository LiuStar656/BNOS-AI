# 13 Agent Subprocess Architecture: Platform Maintains Multiple Independent AAA Processes (F9)

## Problem Description

The message-pool experiment platform originally used a "single process, multiple AAA instances" architecture: the main process `import main` then created N `MyNode()` instances sharing the in-process memos semantic index. The user wanted **Agents to become subprocesses of the platform** — each Agent handled by its own independent AAA cognition process, with the platform (parent process) only orchestrating.

Three critical flaws of the single-process architecture:

1. **Shared memos race**: Multiple instances share the same memos global index; concurrent background rebuild threads write the same numpy state, risking native crashes (already proven in earlier long-run evolution tests).
2. **Crash cascade**: An LLM exception or background-thread crash in any instance drags down the entire experiment process.
3. **No true parallelism**: Under GIL constraints, multi-Agent decisions in one process can only run serially (threads only help for I/O).

## Root Cause Analysis

- The experiment needs two orthogonal dimensions — "platform orchestration" and "independent Agent cognition" — which the original implementation fused into one process.
- `MyNode.__init__` instantiates at module level and calls `memos.preload()`; multiple instances in one process inherently share the index and cannot be isolated.
- LLM calls are HTTP direct connections (`urllib`), natively concurrent — the bottleneck is only the in-process sharing of AAA cognition state and the index.

## Solution

### Architectural Decision

An IPC protocol of **one JSON object per line over stdin/stdout** (same process-isolation philosophy as the BNOS node file protocol, but tuned for high-frequency experiment communication):

```
Platform (parent process)            AAA subprocesses × N (one per Agent)
─────────────────────             ─────────────────────────────────────
MessagePoolPlatform          ┌──► aaa_serve.py resident loop
  step() parallel decision ──┼──► aaa_serve.py
  @ priority arbitration     └──► aaa_serve.py
  AgentBridge._send(ping/pool_batch/flush_review/shutdown)
```

- Each AAA subprocess loads its own memos semantic model and index (~80MB; within the Agent ≤ 5 memory budget).
- Background review threads call the LLM inside the subprocess, matching the real architecture; `flush_review` waits for persistence before process exit.
- Automatic crash restart: `_send` catches EOF/parse failure → kill old process → respawn → retry once.

### 1. New `tests/message_pool/aaa_serve.py` (AAA resident subprocess service)

- Protocol: `ping` / `pool_batch` / `flush_review` / `shutdown`, responses `{"code": 0|-1, "type", "data"/"error"}`; stdout carries only protocol JSON, logs go to stderr.
- LLM injected via environment variables (`AAA_LLM_MODE=real|fake`, `AAA_API_URL/KEY/MODEL`) — no node code hardcoding.
- `AAA_SKIP_HEAVY=1` (acceptance/fake mode): patch `memos.preload` / `rebuild_index` / `rebuild_knowledge_index` / `db._aggregate_mood` **before** `import main` — the module level instantiates `MyNode()`, whose `__init__` calls `memos.preload()`.
- `_handle_pool_batch` mirrors AgentBridge inline logic line by line (`_on_pool_batch` → LLM → `_on_parsed(batch_mode=True)` until an action converges), guaranteeing behavioral equivalence between the two modes.
- Note: the plan document specified "main.py with a --serve loop"; the actual implementation uses a **standalone aaa_serve.py service** instead — keeping the AAA node black-box untouched and decoupling experiment infrastructure from node code.

### 2. `tests/message_pool/agent_bridge.py` — subprocess bridging

- `__init__` gains `mode="inline"|"subprocess"`, `aaa_env`, `serve_script`, `log_dir`.
- `_ensure_proc`: `subprocess.Popen([sys.executable, aaa_serve.py, --identity, --db], ...)`; stderr redirected to a log file (when `log_dir` is provided).
- `_send`: write one JSON line + blocking read one line; on EOF/parse failure → kill, respawn, retry once; otherwise raise `ConnectionError`.
- `ping` / `flush_review` / `close` (shutdown → wait to reclaim, preventing orphan processes).
- Inline mode logic fully preserved (control/regression).

### 3. `tests/message_pool/platform_runner.py` — parallel decisions + priority arbitration

- `step()`: for multiple target Agents, spawn threads to run `process_batch` in parallel and collect all decisions.
- Arbitration sorts **by @ mention priority after decisions complete** (mentioned Agents first), no longer first-come-first-served — a mentioned Agent's speech wins even if its decision finishes later.
- Single target Agent stays serial (no concurrency overhead).

### 4. `tests/message_pool/run_pool_experiment.py` — parameter passthrough and cleanup

- New `--inline` (single-process control mode, the pre-F9 architecture retained for regression); default: each Agent gets its own AAA subprocess.
- LLM configuration injected into subprocesses via `aaa_env`; `--fake-llm` also sets `AAA_SKIP_HEAVY=1` (smoke testing without resource cost).
- Cleanup: `flush_review` waits for persistence → `close` shuts down all subprocesses and prints reclamation summary.

## Impact Scope

- New: `tests/message_pool/aaa_serve.py`.
- Modified: `tests/message_pool/agent_bridge.py` (subprocess bridging, inline retained), `platform_runner.py` (parallel decisions + priority arbitration), `run_pool_experiment.py` (--inline + aaa_env + cleanup), `infra_acceptance_test.py` (U7 acceptance section).
- No AAA node code changes (`nodes/node_python_aaa_cognition/`) and no platform infrastructure changes (message pool/router/arbiter/collector) — the process protocol lives entirely in the bridge layer.
- Memory budget: ~80MB per subprocess (model + index), Agent ≤ 5.

## Verification

1. U7 acceptance (appended to `infra_acceptance_test.py`):
   - Process isolation: 3 independent AAA subprocesses with distinct PIDs;
   - Resident communication: ping round-trip < 1s after warm-up; all 50 `pool_batch` requests return valid decisions;
   - @ mention priority: mentioned `agent:s2` wins the floor under parallel decisions;
   - Crash recovery: killing a subprocess triggers auto-restart and returns a decision;
   - Resource reclamation: after close, all subprocesses exit, no orphans.
2. Regression: U1–U6 + I1–I4 (57 items) all pass; `infra_acceptance_test.py` **64/64**.
3. Smoke full chain: `run_pool_experiment.py --fake-llm --agents 3 --rounds 3 --gid smoke` → 3 subprocess-mode Agents complete self-intro → topic announcement → 10 rounds of Agent speech (platform declares topic end at the cap) → each Agent's 14 tables exported + chat history + topic report → `[回收] 已关闭 3 个 AAA 子进程`.
