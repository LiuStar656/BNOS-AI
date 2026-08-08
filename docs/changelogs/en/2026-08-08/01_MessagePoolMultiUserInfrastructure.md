# Message Pool & Danmaku Processing Infrastructure

## Problem

Per `[PLAN] 消息池与弹幕式消息处理方案（多用户交互实验）.md`, build the infrastructure
for the multi-user interaction experiment (experiments themselves are out of scope).
Eight capabilities are required (F1–F8): message pool subscription, user_id dimension,
per-user cognition storage/retrieval, silent processing channel, batched context merging,
speech arbitration & routing, background observation-driven cognition updates, and
experiment data collection.

## Root Cause

- AAA `_on_text` only handles a single text and triggers one LLM call per message;
  100 danmaku = 100 LLM calls (missing F1/F5).
- All memory tables only have `identity_key` (the AI's own identity), with no field for
  "who is speaking" (missing F2/F3).
- Output side can conditionally skip speech, but there is no explicit silent signal for
  the platform (missing F4).
- No arbiter on the platform; multiple agents may reply to the same message (missing F6).
- Cognition updates are tied to dialogue-round counters; silently observed messages never
  enter the evolution pipeline (missing F7).
- No structured experiment data output (missing F8).

## Solution

### AAA node side (node_python_aaa_cognition)

1. **F2 `db.py`**: add `_TABLES_NEED_USER_ID` (user_messages / event_summary /
   other_cognition / user_facts); idempotent v6.0 migration
   `user_id TEXT NOT NULL DEFAULT ''` (empty string = AI self / anonymous / global fallback).
   `_dedup_and_merge` / `_write` / `write_parsed_async` / `_write_parsed` now carry `user_id`;
   dedup is scoped per user so similar messages from different users are not merged.
2. **F3 retrieval**: new `g_where_identity_user(...)`: prefers the specified user's
   cognition, falls back to `user_id=''` global cognition. `_gather_context` filters
   `other_cognition` / `user_facts` by user_id.
3. **F5 `prompt.py`**: `_CONTEXT_HEADER` replaces "他人认知（对用户）" with a
   `{other_cognition_label}` placeholder (renders 「对 用户A」 by user_id) and "用户文本"
   with `{user_text_section}` (injects the batch section in pool mode).
4. **F1/F4/F7 `main.py`**: new `_on_pool_batch` entry (batched write with user_id →
   F5 merged context → pending cache → `_observe_counter`, background review every 5 batches);
   `_on_parsed` gains `batch_mode=True` returning an explicit
   `{action: reply|silent, content, user_id, ...}`; fixed lost pending context on the
   reflection round (identity_key/user_id were dropped, which breaks multi-agent flows).

### Platform side (new package tests/message_pool/)

5. **F1 `message_pool.py`**: `enqueue_input` (non-blocking enqueue + same-user same-text
   window dedup) / `pop_all_inputs` (priority desc → ts asc → per-user quota truncation).
6. **F6 `router.py`** (@ mention `pick_speaker`) and `arbiter.py`
   (`SpeechOutputArbiter`: QUEUE / DROP / INTERRUPT, single speech floor, events on EventBus).
7. **F8 `collector.py`**: events.jsonl / decisions.jsonl / evolution.json under runs/.
8. **`agent_bridge.py` + `platform_runner.py`**: bridge AAA batch entry with multi-round
   echo handling until an explicit action is returned; step orchestration
   (batch → route → agent decisions → arbiter broadcast), releasing the floor at step end.

## Impact

| File | Change |
|------|--------|
| `nodes/node_python_aaa_cognition/db.py` | v6.0 user_id migration; user_id dimension across write/dedup/retrieval; new `g_where_identity_user` |
| `nodes/node_python_aaa_cognition/main.py` | new `_on_pool_batch`; `_on_parsed` batch_mode explicit decisions; `_gather_context` user_id/batch_items/pool_batch_section; `_observe_counter` |
| `nodes/node_python_aaa_cognition/prompt.py` | cognition-label and user-text placeholders (per-user rendering, batch section) |
| `tests/message_pool/` (new) | event_bus / message_pool / router / arbiter / collector / agent_bridge / platform_runner / infra_acceptance_test / README |

GUI direct path (`_on_text`) and existing tests (`self_evolution_test.run_round`) are
unaffected: all new parameters have defaults, and empty-batch behavior is unchanged.

## Verification

- `tests/message_pool/infra_acceptance_test.py` (no real LLM): 21 unit checks
  (bus / pool dedup-quota-ordering / mention routing / arbiter policies / collector)
  + 11 integration checks (Fake LLM covering the batch pipeline: user_id attribution,
  reply/silent explicit decisions, silent-round event summary writes, DROP single-floor,
  decisions.jsonl persistence).
- AAA-side smoke validation (temp script, removed after verification): user_id migration,
  `g_where_identity_user` fallback, `pool_batch_section` rendering, `_on_pool_batch` full
  chain — 24/24 passed.
- The experiment itself (real LLM multi-user cognition evolution) is executed separately
  per plan §六/§七 and is out of scope here.
