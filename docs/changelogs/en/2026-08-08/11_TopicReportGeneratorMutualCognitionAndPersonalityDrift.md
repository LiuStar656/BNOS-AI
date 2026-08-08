# 11 Topic Report Generator: Mutual Cognition Memory & Personality Drift Analysis

## Problem

After a chatroom (message pool) experiment, the platform only produced `evolution.json`
(other-cognition counts) plus raw DB table exports. Two key scientific questions were
not directly answered:

1. **Mutual cognition memory**: did the agents form cognition memories about *each other*
   (rather than only about simulated users)? Is the cognition bidirectional?
2. **Personality drift tendency**: did each agent's initial persona seed (personality
   vector) drift by the end of the topic? How much, and along which dimensions?

Per user request, collection must follow the `[WIP]-实验设计方案.md` (cognition
evolution experiment design v2) method, and a report must be generated at the end of
**every topic round**.

## Root Cause

- The platform teardown only exported DBs and summarized evolution; `other_cognition`
  rows (user_id=agent:X) were never aggregated into a readable "cognition × target"
  conclusion.
- `personality_seed` holds only the final vector (`save_personality` is an idempotent
  INSERT OR REPLACE); the initial seed lived only in memory of the run script and was
  never persisted → no drift baseline could be computed.
- No unified report artifact (`report.md`), inconsistent with the experiment design's
  "per-group output `report.md`".

## Solution

### 1. New `tests/message_pool/topic_report.py` (report generator)

Pure stdlib (sqlite3/json/glob), does not load AAA models. Reads the archive directory
and writes `topic_report.md`:

- **Mutual cognition matrix**: `other_cognition` grouped by `identity_key` (source) ×
  `user_id` (target), including an "other" column for non-agent targets.
- **Bidirectional verdict**: for each agent pair (A, B), checks whether both A→B and
  B→A have cognition entries → mutual formed / one-way / not formed.
- **Cognition excerpts**: full text of agent→agent entries; counts only for other targets.
- **Personality drift table**: initial seed (`_run_meta.json` `seeds[identity].vector`,
  fallback to first `decisions.jsonl` personality snapshot) → final vector
  (`personality_seed`) Euclidean distance and per-dimension deltas; drift ≥ 0.05 marked
  as "drift tendency".
- **E3 metrics table** (aligned with [WIP] design doc): self_cognition / event_summary /
  self_info / feelings counts, mood trace (first→last + mean), top-3 self-cognition
  keywords, reply/silent counts.

### 2. `run_pool_experiment.py`: persist seeds + auto-generate report

- `_run_meta.json` gains `seeds`: each agent's initial vector + style (written after
  agents are created).
- Teardown now calls `generate_topic_report(run_dir)` → `topic_report.md` at the end of
  every topic round (currently one topic = one run; report is generated after review
  threads are joined, when data is complete).

### 3. `__init__.py` / `infra_acceptance_test.py`

- Module list updated with topic_report.py.
- New **U6** acceptance items (15): report file generation, matrix, bidirectional
  verdict, drift table, metrics table, seed loading, personality read, Euclidean
  distance, one-way cognition verdict, and **n-agent full coverage** (3-agent matrix
  rows/columns/verdicts/excerpts all verified).

## n-Agent Support

The generator auto-discovers all agents via `db/agent_*.sqlite` glob (`_agent_dbs`);
matrix/verdict/excerpt/drift/metrics all iterate over every identity with no
hard-coded agent count, so future N-agent experiments generate reports directly.
Verified with a 3-agent fixture DB plus a real 3-agent fake-LLM run.

## Impact

- New: `tests/message_pool/topic_report.py`.
- Modified: `tests/message_pool/run_pool_experiment.py` (seeds in _run_meta + report at
  teardown), `tests/message_pool/__init__.py` (module list),
  `tests/message_pool/infra_acceptance_test.py` (U6).
- AAA node source untouched; platform package still contains no business logic (report
  generation is experiment-scoped, invoked by the experiment script).

## Verification

1. Acceptance: `& nodes/node_python_aaa_cognition/venv/Scripts/python.exe
   tests/message_pool/infra_acceptance_test.py` → 57/57 pass (incl. new U6, 15 items,
   n-agent full coverage with 3 agents).
2. Backfill real run: `topic_report.py runs/20260808_090024_yield10` → report shows
   agent:0→agent:1 ×4, agent:1→agent:0 ×3 → **mutual cognition formed**; both agents
   drift 0.0000 (short topic did not trigger evolution threshold; needs cross-topic
   accumulation).
3. Real 3-agent fake run (`--agents 3 --gid n3_final`) → report matrix 3×3+other
   column, bidirectional verdict covers all 3 pairs, drift table has 3 rows, gid
   displayed correctly.
4. Old runs without `seeds` fall back to the first decisions.jsonl snapshot without
   error.
5. Fixed: `_agent_dbs` filter now checks basename only, so a run_dir whose name
   contains `_final` (e.g. gid ending in `_final`) no longer excludes all agent DBs.
