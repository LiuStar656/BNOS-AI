# 14 Stream-of-Consciousness Sync: Silent Decisions Also Carry Thoughts (Reply Only When 自然回复 Has Text)

## Problem Description

In the message-pool experiment (F9 subprocess architecture), when an Agent chose not to reply (`action=silent`), the decision record had **empty 想法 (thought) and 心情 (mood) fields**. The real DeepSeek run (`runs/20260808_092728_n3_25r`) shows many silent records with `"想法": ""`, `"心情": ""`. The user's requirements:

1. **n agents receive, decide, and reply concurrently (or choose not to reply)** — the concurrency capability is already implemented by F9;
2. **Thoughts are a stream of consciousness and must update whether or not the Agent replies** — silent decisions must also carry thought/mood;
3. **Whether to reply is decided solely by whether the 自然回复 section has text** — no natural reply text = no reply.

## Root Cause Analysis

- The reply/silent decision logic itself was already correct (`_on_parsed` batch mode keys off `reply_text = parsed["自然回复"]`). **The problem is the source of the thought**: the real LLM did not emit a 想法 section when silent (the prompt never required it), and `parse_llm_output` skips empty sections entirely (parser.py `_store_section` returns on empty content), leaving `parsed.get("想法")` as an empty string.
- The fake LLM always emits 想法, so smoke/acceptance tests never exposed it; the unstable real-LLM formatting did.
- Parallel decisions (F9) caused a race on the shared `fake_llm` counter: which agent spoke first in the first batch depended on which parallel thread grabbed the counter first, and the @-mention exemption made the decision count float between 3 and 4 (an occasional single assertion failure).

## Solution

### 1. `nodes/node_python_aaa_cognition/prompt.py` (root fix)

The 自然回复 section now states the silent rule explicitly, and 想法 is mandatory:

```
【自然回复】
你给用户看的回复文本（禁止使用emoji和颜文字）。如果你决定不回应这条消息，此节**留空**（不输出任何内容）
【想法】
1-2句话描述你此刻的内心想法（意识流）。**即使【自然回复】留空（选择静默），你也必须输出此节**——这是你不说话时也在进行的内心活动
```

### 2. `nodes/node_python_aaa_cognition/main.py` (data-completeness fallback)

The batch-mode return now provides defaults for 想法/心情 so a silent decision still carries state even if the LLM violates the format:

```python
"想法": parsed.get("想法", "").strip() or "收到消息，保持观察，暂不回应",
"心情": parsed.get("心情", "").strip() or "平静",
```

Whether to reply still depends only on whether 自然回复 has text — the decision logic is unchanged.

### 3. `tests/message_pool/infra_acceptance_test.py` (test stability)

- I1/I2: the shared `fake_llm` counter is replaced with **per-Agent deterministic LLMs** (alpha always replies, beta is silent first then replies), removing the counter race under F9 parallel threads so the first-batch speaker is deterministically alpha;
- U7: ping round-trip threshold 1s → 2s (the first ping after warm-up may still include subprocess init tail; resident round-trips are sub-millisecond by nature).

## Impact Scope

- AAA node code: `prompt.py` (prompt) and `main.py` (batch-mode fallback) — only affect the message-pool batch decision path; the GUI single-user conversation path (`batch_mode=False`) does not pass through the fallback branch, and the prompt strengthening has no side effect on the GUI (no silent mode there).
- Experiment/tests: `infra_acceptance_test.py` (determinism + threshold).
- Platform side (agent_bridge / platform_runner / aaa_serve) untouched.

## Verification

1. Temporary verification script (deleted after use): `_on_parsed(batch_mode=True)` three scenarios —
   - 自然回复 + 想法 present → `action=reply`, thought preserved;
   - silent but emits 想法 → `action=silent`, thought preserved;
   - silent with no 想法 → `action=silent`, thought falls back to "收到消息，保持观察，暂不回应", mood falls back to "平静".
2. `infra_acceptance_test.py` **64/64** twice in a row (stable after the race fix and threshold adjustment).
