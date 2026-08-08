# 19 Unified Batch-Order Source of Truth & Seven-Item Data Collection (v6.6)

## Problem

The `exp_5a30r_v2` (20260808_111908) experiment analysis report left 6 issues — 4 data/accounting defects and 2 mechanism gaps — while `[PLAN]-数据采集价值清单与方案.md` requires 7 data-collection items; both were addressed here:

- **P0-1 decisions/events batch-order mismatch**: decisions.batch_context `[agent:1,2,3,4,0]` vs events.batch_dispatched `[agent:0,1,2,3,4]` recorded the same batch in different orders — last-message-bias analysis depends on "who is at the batch end," so two order sources undermine every bias conclusion;
- **P0-2 empty user_id polluting other_cognition**: round_2_agent_0 had `user_id=""` targeting itself; the empty key entered the cognition matrix;
- **P1-3 ghost speeches not eliminated**: 35 replies vs 30 enqueued events; 5 replies were generated after topic_ended but never enqueued;
- **P1-4 round_9_agent_1 truncated output**: content stopped mid-sentence; thought / user_id / reply-target fields all empty;
- **P1-5 last-message bias still present**: the agent:0 black-hole disappearance was merely a side effect of batch-position rotation;
- **P1-6 zero personality drift**: the evolution fallback threshold of 30 is never reached in a 30-round config.

## Root Cause

| Issue | Root cause |
|---|---|
| P0-1 order mismatch | batch_context and batch_dispatched were recorded from two sources ("customized order" vs "dispatch order") with no global sequence number tying them together |
| P0-2 empty-attribution pollution | `_write_parsed` batch path did not filter `user_id=""`, writing empty keys into other_cognition |
| P1-3 ghost speeches | `step()` / `drain_queue()` kept processing residual batches after topic_ended, producing new decisions/broadcasts |
| P1-4 truncation | larger max_tokens still allows truncation; there was no truncation detection or retry |
| P1-5 last-message bias | the reply target is still freely inferred by the LLM from the batch with no explicit determination and no quantifiable metric |
| P1-6 zero drift | `_FALLBACK_TRIGGER_COUNT=30` far exceeds per-agent interaction counts (5-8) in a 30-round experiment |

## Changes

### P0-1 single source of truth for batch order (message_pool.py + platform_runner.py)
1. `Message.to_dict()` now carries `seq` (pool-wide monotonically increasing number); `enqueue_input` increments `_seq`;
2. `platform_runner.step()` computes each agent's customized order exactly once via `ordered = {a: self._batch_for(a, batch)}`; batch_context and batch_dispatched share this single source;
3. decisions.batch_context and events.batch_dispatched are cross-validated through seq.

### P0-2 empty user_id filtering (db.py + main.py + topic_report.py)
1. `db._write_parsed(..., skip_empty_other=True)`: batch mode skips other_cognition writes with empty attribution (the GUI 1-on-1 path keeps empty user_id as a "global cognition fallback");
2. `topic_report._read_other_cognition` defensively filters empty keys on the read side.

### P1-3 ghost-speech source fuse (platform_runner.py)
`step()` and `drain_queue()` return early when `not topic_active`; no new decisions/broadcasts after topic_ended.

### P1-4 truncation detection + retry (parser.py + main.py + aaa_serve.py)
`parser.is_truncated(raw)` uses two signals: unclosed section marker (`^【[^】]{1,16}$`) / has 【自然回复】 but missing 【情绪调整】; on hit, one retry appends an extra prompt instruction; wired into both inline and subprocess (aaa_serve) paths.

### P1-5 last-message-bias quantification (agent_bridge.py + topic_report.py)
Decisions now include `reply_target_pos` (reply target's position in the batch the LLM actually saw), `batch_last_author`, `mention_targets` / `mention_responded` (replied to the mentioner) / `attribution_ok` (user_id == reply target) — turning last-message bias from a perception into a measurable metric.

### P1-6 evolution fallback threshold (personality.py)
`_FALLBACK_TRIGGER_COUNT` 30 → 10; neutral feedback converges warmth.

### Data collection persistence (aligned with `[PLAN]-数据采集价值清单与方案.md`)
| Item | Persisted to |
|---|---|
| P0-1 memory retrieval hits | `memory_usage` table (`_write_memory_usage`) + decisions.memory_hits (memos.py `_retrieve_hits` thread-local pass-through) |
| P0-2 silent-period cognition updates | `silent_cognition` table (`_write_silent_cognition`) + decisions.silent_cognition_written |
| P0-3 personality drift trajectory | decisions.personality → evolution.json trajectory (`platform_runner._trajectory`) |
| P1-4 cognition network evolution timeline | topic_report chapter 11 (edge/bidirectional growth per round) |
| P1-5 @-mention response rate + attribution accuracy | topic_report chapter 6 |
| P2-6 batch-position vs reply-target cross-table | topic_report chapter 5 (last-position reply rate) |
| P2-7 mood-behavior correlation | topic_report chapter 7 (reply/silent average mood) |

## Scope

- AAA node: `db.py` (empty-attribution filter + two collection tables), `main.py` (decision field returns), `parser.py` (truncation detection), `memos.py` (hit pass-through), `personality.py` (threshold);
- Experiment infrastructure: `message_pool.py` / `platform_runner.py` / `agent_bridge.py` / `aaa_serve.py` / `topic_report.py`;
- GUI single-user path unaffected (skip_empty_other only active in batch mode; GUI fallback cognition preserved).

## Verification

`infra_acceptance_test.py` gains the U12 section (P0-1~P1-6 + collection persistence + report-section rendering) → **142/142** (111 + 31 new).

**Rerun evidence (20260808_115334, exp_5a30r_v3, 30 rounds, real LLM)**:

| Issue | v2 (before) | v3 (after) |
|---|---|---|
| P0-1 batch order | two order sources | ✅ batch_dispatched carries seq (seq 2-6...) in sync with decisions.batch_context |
| P0-2 empty user_id | agent:0 `""` key polluted the matrix | ✅ mutual-cognition matrix has no `""` key |
| P1-3 ghost speeches | 35 vs 30 (5 never enqueued) | ✅ 31 vs 30; the last queued speech (agent:4 r9) was dropped by the topic_ended fuse (normal behavior), no ghost rounds |
| P1-4 truncation | round_9_agent_1 mid-sentence | ✅ no truncated records |
| P1-5 last-message bias | not quantified | ⚠️ quantified: 25/31 = 80.6% (report 83.3%, 25 of 30 localizable replies hit the last position) — mechanism unfixed but collection achieved |
| P1-6 personality drift | threshold 30 never hit | ⚠️ threshold 10 still not hit (agent replies 7/5/9/5/5 < 10) — further decision needed |

**Seven collection items**:

| Item | v3 data |
|---|---|
| memory_hits | 0 (LLM never triggered 【语意检索】; the pipeline itself is verified via U12 standalone-DB direct tests + thread-local pass-through) |
| silent_cognition | 6 records (agent:0×2, agent:1×4), all with thoughts but no cognition sections written |
| trajectory | 9/9/9/5/5 sample points complete (unchanged throughout, consistent with P1-6) |
| cognition network timeline | bidirectional groups 0→6, edges 3→16 (first bidirectional at r5) |
| @-mention response | @=0 (no sim messages injected this round); attribution accuracy 93% (28/30) |
| batch-position cross-table | last-position reply rate 83.3% (trustworthy under the seq source of truth) |
| mood-behavior | reply/silent average mood split (agent:1 silent mood constant 0 flagged) |

## Pending Decisions

- **P1-5 last-message bias**: quantified at 80.6%; the mechanistic fix (explicit reply-target determination) is not implemented — to be pursued per the plan's next steps;
- **P1-6 zero personality drift**: threshold 10 still unmet in a 30-round config — recommend lowering to ≤5 or wiring `_adjust_vector` into the multi-user batch path; otherwise the E7 hypothesis (directness-center convergence) cannot be verified in the message-pool scenario.
