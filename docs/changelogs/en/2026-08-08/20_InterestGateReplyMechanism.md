# 20 Interest-Gate Reply Mechanism (v7.0)

## Problem

The rerun of `exp_5a30r_v3` (20260808_115334) confirmed that **last-message bias is a systemic mechanism flaw**: even after cold-bench rotation, the last-position reply rate stayed at 80.6% (25 of 31 locatable). The root cause is not the model but **who owns the decision**:

> Whom to answer is freely inferred by the LLM from a long context → the model uses "the last message" as a heuristic shortcut.

Cold-bench rotation (v6.5) only hands the last position to the ignored agent — it exploits the bias rather than removes it. The mechanistic fix is to move "reply-target determination" explicitly to the platform.

## Root Cause

| Problem | Root cause |
|---|---|
| Last-message bias cannot be eliminated | The reply target is freely inferred by the LLM (no explicit determination); any reordering just relocates the bias |
| Disinterested agents are forced to call the LLM | Every candidate agent decides every batch even when irrelevant (wasted calls, noise replies) |
| Interest is not quantifiable | No platform-side interest judgment exists, so interest distribution is unobservable and cannot be an experiment metric |

## Solution

### Mechanism design (per `[PLAN]-兴趣门控回复机制.md`)

1. **Interest anchor**: each agent's most recent broadcast (self-intro is the initial anchor), updated after speaking (interest drifts with participation);
2. **Interest value**: `cos(message_embedding, anchor_embedding)` cosine similarity (`paraphrase-multilingual-MiniLM-L12-v2`, 384-dim normalized vectors);
3. **Gate judgment**: max similarity over the batch ≥ threshold 0.60 → pass (`reason=interest`); `reply_to==agent` or `@`-mentioned → direct pass (`reason=direct`);
4. **Encode once, compare many**: each message in a batch is encoded once (cached) and dot-producted against all agent anchors; O(m) encode + O(n×m) dot products; measured 7.7s offline load + 0.03s per 10 encodes — the LLM call remains the real bottleneck;
5. **Call savings**: non-passing agents do not call the LLM (platform judges silence); judgments (detected text + interest value) are written to each agent's `interest_judgment` table (explicit user requirement);
6. **Fallbacks**: no model → `no_model`, no anchor → `no_anchor` (all pass, back to v6.6); if no agent passes → the highest-interest one passes via `interest_floor` (prevents dialogue stall);
7. **Context is not trimmed**: the gate decides *who* decides; passing agents still see the full batch — keeping the last-message-bias metric comparable with v6.6;
8. **Arbitration order**: `@ mention > interest value > cold bench (least-responded first) > original order` (with gate off, the interest dimension is constant 0, reverting to v6.6).

### Threshold calibration (calibrate_interest_threshold.py)

Calibrated on 31 real replies from 5a30r_v3 (25 computable pairs): real replies median 0.653 / p25 0.499; random baseline median 0.464 / p90 0.701. Picked the midpoint **0.600** (0.7 would drop 68% of real replies — the user's original threshold was too high).

### Persistence (interest_judgment table, per-agent sqlite)

| Column | Meaning |
|---|---|
| `detected_text` | Detected text: content of the evaluated message (highest interest / direct hit) |
| `interest_value` | Interest value: cosine similarity |
| `passed` / `reason` | Passed? / reason (direct/interest/none/interest_floor) |
| `round_no` / `message_seq` / `anchor_text` | Round / pool-global seq / interest anchor text |

Written directly by the platform process (judgment happens before LLM decisions, serialized); `db.ensure()` creates the table plus an idempotent `CREATE TABLE IF NOT EXISTS` on write; `data_export` covers it automatically.

## Impact

- New `tests/message_pool/interest_gate.py` (shared model + encode cache + gate judgment + persistence);
- Modified `platform_runner.py` (gate pre-filter in step(), anchor updates, arbitration sort key), `run_pool_experiment.py` (`--gate-threshold`/`--gate-model`/`--no-gate`), `nodes/node_python_aaa_cognition/db.py` (ensure table), `topic_report.py` (chapter 12 interest-gate collection);
- AAA subprocesses are unaware (gate is a pure platform pre-layer); GUI single-user path unaffected.

## Verification

**U13 unit acceptance** (infra_acceptance_test.py, deterministic fake encoder, no model load): encode-once / gate judgment / anchor update / persistence fields / platform integration (non-passing agent skips LLM) / arbitration → **158/158** (142 previous + 16 new).

**5-agent 20-round experiment (20260808_123326, exp_5a20r_v2, real LLM, threshold 0.60)**:

| Metric | Result |
|---|---|
| Last-position reply rate | 58.8% (10/17) vs 80.6% in v3 — down (batch structure differs; agent cross-references dominate) |
| Gate silence rate | 25 of 55 judgments rejected (45.5%), saving 25 LLM calls (33 total) |
| Reason distribution | direct×11, interest×19, none×25; interest min 0.152 / median 0.587 / p90 1.000 |
| Persistence | 55 rows (5 agents × 11) fully queryable (detected_text + interest_value) |
| Participation concentration | agent:1 (median 0.370)/agent:3 (median 0.310) low interest, 1 speech each in 20 rounds; agent:2/4 (median 0.735/0.744) dominate |
| Mutual cognition | bidirectional cognition formed; topic not fragmented |

## v7.1 Increment: Recent-Observation Injection (option a, 2026-08-08)

**Motivation**: 5a20r_v2 showed that non-passing agents keep only the interest_judgment row (detected text + interest value) for a message, but that table never enters the LLM context — "recorded" but "unrecallable". Per user decision (option a): a passing agent's context now includes the latest N non-passed (`passed=0`) detected texts as "recent observations", making "seen but unanswered" recallable at zero extra LLM calls.

**Implementation**: `db.py` adds `read_recent_observations()` (filtered by identity_key + passed=0, id-desc dedup, N=5 default, error-safe); `main.py` `_gather_context` injects it; `prompt.py` renders a 【近期观察记录】 section after "你的他人认知" (empty section omitted; 1-on-1 unaffected).

**Acceptance**: U13.7, five checks (passed=0 filter + desc dedup + limit + missing-table tolerance + prompt render/empty-omission) → 163/163.

**v3 run (20260808_130257, exp_5a20r_v3, gate + injection, new random seeds)**:

| Metric | v2 (gate) | v3 (gate + injection) |
|---|---|---|
| Last-position reply rate | 58.8% (10/17) | 66.7% (14/21) |
| Gate pass rate | 30/55 (54.5%), 25 saved | 33/45 (73.3%), 12 saved |
| Bidirectional cognition pairs | 3 (agent:1/3 erased) | **6** (all agents in the network, no black hole) |
| Low-curiosity agents | agent:1/3 spoke once each | agent:1 passed 7, agent:4 passed 5 |

> v3 uses the same config (gate on, threshold 0.6) but different seeds/topic (everyday topic: iced coffee) — low-curiosity agents were not silenced, confirming the "cognitive black hole" is a seed×topic combination effect, not a necessary gate outcome, supporting the "few rounds × personality amplification" diagnosis. The standalone contribution of observation injection needs 40+ rounds to quantify; within 20 rounds it is a soft effect.

## v7.2 Increment: Bystander Reply-Entry Judgment + Sliding Attention Window (2026-08-08)

**Motivation** (user-designed semantics): whole-batch judgment has two kinds of distortion — (1) judging "highest interest over the batch" lets an interesting message be diluted by disinterested ones; (2) deciding over the full batch cannot explicitly express "start replying after so-and-so has spoken". User scenario: 1 speaks → 2 passes the gate and answers 1 → 3 fails the gate and watches → 1 replies to 2 → **3, as a bystander**, judges each speech in chronological order (oldest to newest); the first passing speech = the reply-entry point, deciding whose turn 3 starts joining from.

**Implementation**:
1. `judge_sequence` (interest_gate.py): candidates are now **all messages judged one-by-one by seq from oldest to newest (no dedup per speaker)** — 1's first speech, 2's second-earliest speech, and 1's third reply are judged independently; the first passing one = the entry point (target + target_speaker persisted);
2. **Reply-entry window** (platform_runner.py): a passing agent's decision context = all history messages in `(own latest speech, entry message]` (excluding own speeches, no truncation), maintained via `_msg_history` + `_last_speech_seq`; agents that never spoke use the pool start as the lower bound (a bystander sees the whole conversational thread);
3. **Bookkeeping** (agent_bridge.py): `batch_context` = the window (what the decision actually saw, basis for metric statistics), new `batch_full` = the complete batch (for cross-checking against the v6.6 basis), `window_size`;
4. Sliding anchor: anchor = each agent's latest speech written to the pool (updated after broadcast), so the judgment basis drifts with participation (sliding attention window).

**Acceptance**: U13.8, six checks (oldest-to-newest one-by-one judgment, independent per-speaker judgment, direct priority, window range, never-spoken lower bound, platform integration batch_context/batch_full) → **169/169** green.

**Experiment (20260808_134554, exp_5a20r_v4, 20-round philosophical topic)**:
- API calls total=33 vs v3's 41 (**-19.5%**); per-decision LLM input chars (token proxy) 3176 vs v3's 4063 (**-22%** — the window narrows focus to the conversational range);
- agent:1/3 sat out the whole run: interest_judgment 33/33 rows with passed=0 (top interest 0.590/0.554 < 0.6 threshold) — evidence of genuine "not interested in these 20 rounds" (0 gate passes at the judgment level, not a lack of opportunity); agent:3's only call was the interest_floor fallback (joke batch), still silent against the full-history window;
- Window sliding evidence: agent:4's per-round window seq range slides with its own speech lower bound ([1] → [3..10] → [12] → [15]...);
- Cost: bystanders (lower bound = 0) get the full-history window (max=27 messages) — per-decision token inflation on a few decisions; participation skew grows with the topic.

**60-round new-topic experiment (20260808_140318, exp_5a60r_ai_self, topic "AI 该不该有自我意识")**:
- All 60/60 rounds ran; total=102 (AAA 97 + direct 5); per-agent **extremely even** (16-22 calls, range 6) — the topic determines participation distribution; "AI self-awareness" keeps everyone (incl. playful/gentle types) interested throughout;
- Per-round cost 1.70 calls/round vs v4's 1.65 — **cost follows participation, not round count**; lengthening rounds does not amplify cost;
- The 60 rounds produced real drift across the display threshold (agent:0 directness 0.14→0.23, curiosity 0.1→0.2; agent:3 play 0.87→0.73), which became group B's vector source for Experiment B.

**Experiment B linkage (20260808_142236, personality-drift output-impact verification)**: group C extreme contrast (warmth 0.1 vs 0.9) **d=+0.962 / p=0.0000, highly significant** — first empirical proof of the "state→output" loop: the model does read the personality-vector section and change its output; groups A/B with real drift (amplitude only 1/8 of the extreme) show no significant difference — a statistical-power shortfall, not an injection failure. Suggestion: rerun the loop after raising display precision .1f→.2f or enlarging the evolution step 0.02→0.05.

## Open Decisions

- **Topic-tunnel effect**: high-interest agents keep passing and repeating (the anchor locks to the topic as it updates); agent:1/3 sit out the whole run — anchor decay or interest-diversity penalties are candidates for future evaluation;
- **Bias-comparison basis**: v7 batches are dominated by agent cross-references (2-4 msgs), not directly comparable to v3's large user-danmaku batches — an isomorphic-batch comparison run is needed to confirm the drop magnitude.
