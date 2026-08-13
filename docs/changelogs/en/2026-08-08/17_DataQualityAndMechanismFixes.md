# 17 Experiment Data Quality & Mechanism Fixes: Failure/Silent Split, user_id Attribution, Last-Message Bias, Personality Evolution Break, Reply-Chain Injection

## Problem

The 5-Agent 40-round real experiment (20260808_103432, exp_5a40r_v2) was interrupted by account balance exhaustion (HTTP 402). The post-run analysis report exposed 6 issues; combined with the previous run (101510) analysis, two categories of root problems were confirmed:

- **P0 data pollution**: all 189 API-failure records fell into `action="silent"` (reported silence rate 84% was fake; real 17.8%); `user_id` of silent/reply decisions always equaled the *last* batch message sender (reproduced across 3 runs), corrupting cognition attribution;
- **P1 mechanism breaks**: reply-target selection had a strong last-message bias (nearly always replies to the batch's last message → agent:0/1 became cognition black holes, never perceived); personality evolution pipeline broken (zero drift across 3 runs while mood changed — break point located in `_adjust_vector`).
- **Missing reply chain (new user request)**: the "replied to whom" annotation was post-hoc rendering for humans — **the LLM never saw "who is responding to whom"** during decision (flat batch list).

## Root Cause

| Issue | Root cause |
|---|---|
| P0-1 failures fell into silent | `agent_bridge.py` subprocess failure branch built `action="silent"`; inline exceptions and `platform_runner` parallel-branch `except` also built silent |
| P0-2 user_id = last message | `_on_pool_batch` passed `last_user_id` (batch tail) as user_id all the way through; `setdefault` does not overwrite existing empty string |
| P1-3 last-message bias | merged context sorted by time asc; LLM tends to reply to the last message; agents whose speech sits at the batch front are never selected |
| P1-4 zero personality drift | `_on_parsed` always calls `_process_mood_and_evolution` with `reaction="neutral"`, but `_adjust_vector` only counts positive/negative → pos/neg empty → every dimension `continue` → `vector_changed` always False → never persisted (mood writes via `db.save_mood_value` independently, so it moves) |
| Missing reply chain | agent speech re-fed into the pool without reply target; batch injection had no reference structure |

## Changes

### P0-1: separate failures from silent

1. `agent_bridge.py`: subprocess `code != 0` → `action="error"`; inline branch wraps LLM calls in `try/except` → error;
2. `platform_runner.py`: single/parallel branch `except` → `action="error"`;
3. `collector.py`: new `error_count` (persisted to evolution.json);
4. `topic_report.py`: `_speech_stats` counts error and excludes it from the silence rate.

### P0-2: user_id = reply target

`main.py` `_on_parsed` recomputes user_id in batch_mode: reply → LLM-explicit 【回应对象】; silent/group/no target → no attribution (""). Retrieval injection (`last_user_id`) is kept — context retrieval still targets the last speaker; only **attribution** follows the reply target. Fallbacks in `aaa_serve.py` / `agent_bridge.py` no longer use the batch tail.

### P1-3: last-message bias

1. `platform_runner.py` `_batch_for(aid, batch)`: moves messages that `@` the agent to the batch end — the last-message bias then serves "@ priority" instead (the agent's last speaker becomes the mentioner);
2. `prompt.py`: reply-target section guides "pick from the whole batch (not necessarily the last) + prefer the mentioner".

### P1-4: personality evolution break

`personality.py` `_adjust_vector`: neutral feedback now participates — when pos/neg are empty but neutral observations exist, converge toward the observed style (step still clamped ±0.02; self-consistent observations yield delta≈0, no drift).

### Reply-chain injection (v6.4): LLM sees "who replies to whom"

1. `message_pool.py`: Message gains `reply_to`; `enqueue_input` passes it through; `to_dict` outputs it;
2. `arbiter.py`: `request_speech` / `_grant` / queue items carry `reply_to` (queued broadcasts keep the chain);
3. `platform_runner.py`: speech re-fed with `reply_to=decision's 【回应对象】` (both main `step` path and `drain_queue`);
4. `agent_bridge.py`: dispatched msgs carry `reply_to`;
5. `main.py`: `_fmt_pool_msg` renders `[author] content（回应 X）` into `pool_batch_section` (group → "（回应群聊）").

## Impact

- AAA node: `main.py`, `prompt.py`, `personality.py`;
- Experiment infra: `agent_bridge.py`, `platform_runner.py`, `aaa_serve.py`, `collector.py`, `topic_report.py`, `message_pool.py`, `arbiter.py`;
- GUI single-user path unaffected (`batch_mode=False` skips batch attribution; neutral-driven evolution is a general fix and equally applies to single-user dialogue).

## Verification

`infra_acceptance_test.py` adds U9 (P0/P1, 12 items) + U10 (reply chain, 6 items) → **96/96** pass (was 78 + 18 new):

- P0-1: inline/subprocess failures → `action="error"` with no user_id attribution; collector error counted separately;
- P0-2: reply user_id = LLM reply target (not batch tail); silent user_id empty;
- P1-3: `@` messages moved to batch end; no-`@` order preserved; prompt guidance present;
- P1-4: neutral feedback triggers evolution (warmth 0.6→0.9); self-consistent feedback does not drift;
- Reply chain: four layers (Message / arbiter / re-feed / batch annotation) transmit and render correctly.

## Conclusion

After fixing the two P0 data-pollution issues, silence rate and cognition attribution regain their true semantics (failures independently marked; attribution follows the reply target). P1 fixes the personality evolution pipeline (neutral feedback evolves) and mitigates last-message bias (@ priority + prompt guidance). Reply-chain injection makes LLM decisions consistent with what humans see in the chat log. **Pending: rerun the 5-Agent 40-round experiment after recharging** — llm_stats should decompose into ≈ decision calls (40×~4 with yield skipping one) + background review + platform direct, with error records accounted separately.
