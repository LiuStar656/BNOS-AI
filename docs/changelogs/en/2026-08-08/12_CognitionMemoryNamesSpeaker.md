# 12 Cognition Memory Generation Names the Speaker: Multi-User Ambiguity Fix

## Problem

A user noticed that memory content in `user_facts.json` read like "用户正在慢慢找回自己的节奏，
不着急去远方，享受安静坐着的状态" ("the user is slowly finding their own pace...") — the LLM
generated other-cognition / user-info / user-memory entries using the generic word "用户" (the user)
without naming the actual speaker. In multi-person (multi-agent / multi-user) scenarios, such
ownerless memories are ambiguous at retrieval time and can contaminate cognition about other
targets.

User requirement: **the LLM must generate memory entries that name the actual speaker based on
the real situation, and produce more detailed content**.

## Root Cause

1. **No naming constraint at the prompt-generation side**: the DIRECT_TEMPLATE sections
   【他人认知】(other-cognition), 【用户信息】(user-info) and 【用户记忆】(user-memory) in
   `prompt.py` only said "用户" without telling the LLM who the current speaker is or requiring
   the target to be named → the LLM defaulted to the generic term "用户".
2. **Ownerless background review persistence**: Background Review (every 5 rounds) wrote
   declarative user facts into `user_facts` **without a `user_id` column** in the INSERT, and the
   `run_review` / `_trigger_background_review` call chain never carried `user_id` → even when
   multiple speakers exist in the conversation, review-persisted facts were all attributed
   globally.
3. **No speaker annotation in the review prompt**: `build_review_prompt` rendered only
   `[用户]: content` and gave the LLM no per-message speaker, so declarative facts could not be
   attributed.

## Solution

### 1. `prompt.py` — name the speaker + require detail at generation time

- 【他人认知】now reads "你对当前对话对象 `{current_user_label}` 的新认识（**必须点名对象、具体描述其言行特点，禁止用笼统的"用户"二字**）".
- 【用户信息】now reads "key=值, key=值（**针对当前对话对象 `{current_user_label}`**）".
- 【用户记忆】now reads "关于当前对话对象 `{current_user_label}` 的信息（喜好、习惯、身份），**具体详细描述**，没有可留空".
- `_prepare_ctx` injects `current_user_label = ctx.get("user_id") or "用户"` (`user_id` comes from
  `main.py._gather_context`; the batch path uses the last speaker).

### 2. `review.py` — attribute declarative facts with user_id

- `persist_insight(..., user_id="")`: the declarative branch now INSERTs a `user_id` column into
  `user_facts` and the dedup condition includes `user_id`.
- `run_review(..., user_id="")`: signature passes user_id through.
- `llm_call(..., user_id="")` / `_write_review_prompt_file(..., user_id="")`: the inter-node channel
  review prompt file now carries user_id so the callback keeps attribution.
- `build_review_prompt`: user messages with user_id render as `[用户]（说话对象: agent:X）: content`
  so the LLM knows who each declarative fact targets.

### 3. `main.py` — carry user_id through the trigger chain

- `_get_recent_conversation` SELECTs the `user_id` column.
- `_trigger_background_review` / `_run_background_review` gain a user_id parameter passed to
  `review.run_review`.
- Both call sites pass the real user_id: `_on_pool_batch` (batch path, last speaker) and
  `_on_parsed` (single path, current user_id).
- `_on_review_response` (inter-node channel callback) reads user_id from `data` and passes it
  through.

## Impact

- `nodes/node_python_aaa_cognition/prompt.py`: three DIRECT_TEMPLATE sections + `_prepare_ctx`.
- `nodes/node_python_aaa_cognition/review.py`: `build_review_prompt` / `persist_insight` /
  `run_review`.
- `nodes/node_python_aaa_cognition/main.py`: `_get_recent_conversation` / `_trigger_background_review`
  / `_run_background_review` / `_on_review_response` / two call sites.
- Single-user (GUI direct) behavior unchanged: `current_user_label` falls back to "用户", review
  user_id is empty and facts stay global.
- The platform package `tests/message_pool/` is untouched (no business logic there).

## Verification

1. Prompt build check: with `user_id=agent:1` all three DIRECT_TEMPLATE sections render "当前对话对象
   agent:1"; without user_id they fall back to "用户".
2. Review persistence check: `persist_insight({'type':'declarative',...}, db, identity, 'agent:1')`
   → `user_facts` row with `user_id='agent:1'`; `build_review_prompt` output contains
   "（说话对象: agent:1）".
3. Acceptance regression: `& nodes/node_python_aaa_cognition/venv/Scripts/python.exe
   tests/message_pool/infra_acceptance_test.py` → 57/57 pass, no regression.
4. Lint: no diagnostics for main.py / review.py / prompt.py.
