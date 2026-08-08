# 16 Reply-Context Annotation: Chat History & Decision Context Show "Who Is Responding to Whom"

## Problem

The user noticed it was **hard to tell from multi-Agent chat logs which agent was responding to whom**. In the 5-Agent 40-round dialogues many messages seemed to continue each other, but lacked explicit "this message replies to X" info; `decisions.jsonl` also had no reply-target field, making it impossible to reconstruct the conversational reference structure afterwards.

## Root Cause

The message pool is a **broadcast/flat structure**: the platform fans one batch (multiple messages) out to each AAA subprocess; AAA merges context, the LLM decides and emits reply text, but:

1. The LLM decision prompt had no requirement to state *whom* it answers;
2. The collector did not record the reply target;
3. The renderer did not annotate `chat_history.md` with reply links.

## Changes

### 1. `prompt.py`: conditional 【回应对象】 output section

Only rendered in multi-message batch scenarios (message pool); skipped for 1-to-1 single messages (the target is always the user, output is redundant and disturbs parsing).

### 2. `main.py`: batch_mode decision returns 【回应对象】

`_on_parsed` batch_mode return adds `"回应对象": parsed.get("回应对象", "").strip()`.

### 3. `agent_bridge.py`: batch_context recording

Each decision records `batch_context` (batch message authors + 60-char content excerpts) so the renderer can annotate "replied to whom".

### 4. `data_export.py`: renderer annotation + legacy-data rebuild fallback

- `_reply_context_annotation(decision, batch)`: **priority = LLM-explicit 【回应对象】 > batch author list** (group → "（回应群聊）", single → "（回应上下文：X）", multiple → "（回应上下文：A, B, C（N 条））");
- `_reconstruct_round_batches(run_dir, decisions)`: rebuilds each round's batch for legacy runs without `batch_context` (priority desc / time asc, shared batch_size per round, batch boundary = earliest decision ts);
- Rebuild runs only when legacy decisions without `batch_context` exist.

## Impact

- AAA node: `prompt.py`, `main.py`;
- Experiment infra: `agent_bridge.py`, `data_export.py`;
- 1-to-1 GUI dialogue unaffected (`batch_mode=False` skips the section).

## Verification

1. `infra_acceptance_test.py`: U8 adds 10 items + I1/I2 adds 3 → **78/78** pass.
2. Real 5-Agent 40-round run (20260808_101510): rerender shows round 1 "（回应上下文：platform）", round 2 "（回应上下文：agent:1, agent:2, agent:3, agent:4（4 条））".
3. Real run (20260808_103432): LLM-explicit 【回应对象】 persisted (agent:4 / agent:2 / 群聊 ...); rendering switches to LLM-explicit priority.

## Conclusion

Every chat-history line now annotates whom it replies to (LLM-explicit first, batch authors fallback); requiring explicit reply targets also made the "last-message bias" observable, laying the data foundation for the fixes in #17.
