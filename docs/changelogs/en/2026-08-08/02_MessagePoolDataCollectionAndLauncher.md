# Message Pool Data Collection & Multi-Agent Launch Script

## Problem

The multi-user message pool experiment needs three kinds of data: raw database dumps of
all agents (bnosai) organized by table, the platform's message-pool chat history, and a
script that launches multiple agents (default 5) into the platform. The original platform
only produced events/decisions/evolution files — no chat history, no integrated per-table
DB export, and no launch script.

## Root Cause

- The per-table DB export logic only existed as the private `export_db` function inside
  `tests/evolution_enhance_acceptance_test.py`, not integrated into the pool platform.
- `collector.py` only captured platform events and agent decisions, with no chat history
  of "who said what in the message pool".
- Launching multiple agents required manually constructing each `AgentBridge` and wiring
  the platform; adjusting the agent count was not convenient.

## Solution

### 1. Data export `tests/message_pool/data_export.py` (new)

- `export_agent_db(db_path, out_dir, agent_id)`: exports a single agent's raw SQLite DB
  by table into `runs/.../db/{agent_id}_final/` (one JSON per table + `data.sqlite` copy +
  `_manifest.json`), aligned with the cognitive-evolution experiment's `export_db` format.
- `export_all_agent_dbs(agents, run_dir)`: exports every agent.
- `render_chat_history_md(run_dir)`: renders `chat_history.jsonl` into a human-readable
  Markdown (user danmaku and agent broadcasts interleaved by time).

### 2. Chat history `collector.py` / `platform_runner.py`

- `collector.py` adds a `chat_history.jsonl` output and a `chat()` method.
- `platform_runner.py` records successfully enqueued user danmaku (role=user) in `inject()`
  and actually broadcast agent replies (role=agent) in `step()` / `drain_queue()`, so the
  chat history matches what the platform actually received and actually sent (deduped/dropped
  or silent messages are not recorded).

### 3. Launch script `tests/message_pool/run_pool_experiment.py` (new)

- `--agents N` (default 5): adjust the agent count in one place; each agent gets its own DB
  and identity key `agent:{i}` plus a default persona seed.
- `--rounds N` / `--per-batch N` / `--gid NAME` / `--fake-llm` (fake LLM smoke validation,
  no API) / `--out DIR`.
- Built-in simulated users (userA~userF) and a danmaku pool; DeepSeek direct call `llm_infer`
  (same pattern as self_evolution_test).
- Main loop: inject danmaku → `step()` batched dispatch → `drain_queue()` broadcasts queued replies.
- Finish: wait for background review threads to settle → `write_evolution()` → export all agent
  raw DBs → render chat history md; every run gets its own timestamped archive directory.

## Impact

| File | Change |
|------|--------|
| `tests/message_pool/data_export.py` | New: per-table export + chat history md render |
| `tests/message_pool/run_pool_experiment.py` | New: multi-agent launch script (--agents default 5) |
| `tests/message_pool/collector.py` | New chat_history.jsonl and `chat()` |
| `tests/message_pool/platform_runner.py` | inject/step/drain_queue record chat history |
| `tests/message_pool/infra_acceptance_test.py` | U5 adds chat_history assertion (32→33) |
| `tests/message_pool/README.md` | File list + data artifacts + launch commands |

## Verification

- `infra_acceptance_test.py`: 33/33 passed (new chat_history persistence assertion).
- `run_pool_experiment.py --agents 3 --rounds 2 --fake-llm` smoke run (no real API):
  each agent exported 14 tables (user_messages has correct user_id attribution),
  chat_history.jsonl/md, events/decisions/evolution.json, and _run_meta.json all persisted.
