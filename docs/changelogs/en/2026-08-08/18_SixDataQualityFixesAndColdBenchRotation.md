# 18 Six Data-Quality Fixes: Self-Cognition Pollution, Silent-Template-on-Reply, Ghost-Speech Metering, Truncation Defense, Cold-Bench Rotation, Mood-Tag Guidance

## Problem

A data-audit report on the real 5-Agent 30-round run (20260808_110344, exp_5a30r) exposed 6 issues; 2 were numeric mistakes in the previous summary ("7 mutual-cognition pairs" was actually 6; "~12-15 decisions per agent" was actually 7-11), 4 were data/mechanism defects:

- **A Self-cognition pollution**: `other_cognition` gained agent:2→agent:2=1 (in round_11, the post-topic-end residual batch, agent:2 replied to its own previous speech; the attribution logic did not exclude "reply target == self");
- **B Silent template on a reply**: round_3_agent_0 had `action=reply` (full content) but "想法"="收到消息，保持观察，暂不回应" — the thought fallback ignored `action` and reused the silent copy;
- **C Ghost-speech metering chaos**: after topic end (topic_ended 11:07:29), round_11 still produced 4 reply decisions (11:07:35-51). The platform correctly refused to re-enqueue them, yet decisions recorded 35 replies vs 30 enqueued events, and three round metrics disagreed (evolution rounds=11 vs agent_speech_count=30 vs config 60/30);
- **D Reply truncation**: round_3_agent_0 content ended mid-sentence ("你晾衣服要拨开薄荷"); round_6_agent_0's thought contained the dangling section marker "【情绪调整" (max_tokens=2048 truncated; the broken marker failed the section regex and leaked into the previous section);
- **E Last-message bias reproduced a third time**: nearly every reply target was the author of the batch's last message (rounds 4/6/8/9/10). agent:0 spoke 10 times (most of all) yet no agent formed cognition of it — matrix column 0 all zeros, identical to the 5a40r "agent:0 black hole", a stable cross-experiment systemic defect;
- **F Missing mood tags**: agent:3's short replies carried no 【情绪调整】→ mood stayed 0.0 (parser defaults to 0.0).

## Root Cause

| Issue | Root cause |
|---|---|
| A self-cognition | `main.py` `_on_parsed` batch attribution `user_id = _target` did not exclude `_target == identity_key` |
| B silent template on reply | thought fallback `or "收到消息，保持观察，暂不回应"` ignored `action` |
| C ghost-speech metering | `_feed_agent_speech` correctly refuses re-enqueue after topic end, but decisions/evolution carry no "topic ended" flag; three round metrics were not distinguished |
| D truncation | AAA subprocess `max_tokens=2048` occasionally truncated under batch load; `parser._SECTION_LINE` requires a complete 【】on its own line, so a broken marker line merged into the previous section |
| E last-message bias | P1-3 only handled @ scenarios; without @ the last author is still the natural focus, so the first speaker (agent:0) is never replied to |
| F missing mood tags | prompt did not mandate 【情绪调整】; LLM omitted it on short replies |

## Fixes

### A Prevent self-cognition (main.py)
`_on_parsed` batch attribution: `_target == identity_key` → `user_id = ""` (no self-cognition rows).

### B Split silent template by action (main.py)
Thought fallback uses `_is_reply = bool(reply_text)`: reply without thought → `""`; silent without thought → the keep-watching template.

### C Ghost-speech metering (collector.py + platform_runner.py)
1. `collector.py`: new `topic_ended` state; `decision()` appends `topic_ended=True` after topic end;
2. `platform_runner.py` `_end_topic()`: also sets `collector.topic_ended = True`;
3. `write_evolution()`: extra fields `agent_speech_count` / `topic_ended` / `rounds_metric="processed_batches"`.

### D Truncation defense (aaa_serve.py + run_pool_experiment.py + parser.py)
1. `max_tokens` 2048 → 4096 in both LLM call sites;
2. `parser.py`: new `_SECTION_FRAGMENT` (`^【[^】]{1,16}$`); dangling section-marker lines are skipped, not merged into the previous section.

### E Cold-bench rotation for last-message bias (platform_runner.py)
1. `__init__`: new `_responded` counter (times each agent was replied to);
2. `_feed_agent_speech`: `reply_to` hitting an agent increments it;
3. `_batch_for`: without @, move the least-replied agent's message to the end of the batch — the last-message bias now serves the ignored; @ scenarios keep P1-3 priority; platform/user messages never rotate.

### F Mood-tag guidance (prompt.py)
【情绪调整】now mandates: "无论回复还是静默，此节都必须输出一个数字，禁止留空或省略" (must output a number whether replying or silent).

## Impact

- AAA node: `main.py`, `parser.py`, `prompt.py`;
- Experiment infra: `platform_runner.py`, `collector.py`, `aaa_serve.py`, `run_pool_experiment.py`;
- GUI single-user path unaffected (batch_mode=False bypasses batch attribution / action-split fallback; parser fragment defense is a general hardening).

## Verification

`infra_acceptance_test.py` adds U11 (A-F, 15 checks) → **111/111** (96 + 15):

| Case | Covers |
|---|---|
| A1/A2 | target=self → user_id cleared; target=other → kept (control) |
| B1/B2 | reply w/o thought → empty; silent w/o thought → keep-watching template |
| C1/C2/C3 | post-end decision flags topic_ended=True; platform announce sets collector flag; evolution writes the 3 metering fields |
| D1/D2 | dangling marker stripped; normal markers unaffected |
| E1-E5 | cold-bench to last; @ priority; already-last keeps order; platform messages excluded; reply_to increments counter |
| F1 | prompt mandates a mood-adjustment number |

**Re-run evidence (20260808_111908, exp_5a30r_v2, 30 rounds)**:

| Metric | v1 (before) | v2 (after) |
|---|---|---|
| Matrix column for agent:0 | all zeros (black hole) | **1/2/3/4 entries** |
| Mutual-cognition pairs | 6 (agent:0 entirely one-way) | **8 (incl. agent:0 ↔ all)** |
| Speech distribution (replies) | 10/8/7/5/5 | **8/8/8/6/5** |
| Self-cognition rows | 1 | **0** |
| Replies with silent template | 1 | **0** |
| Truncated replies | 2 | **0** |
| Ghost-speech flagged | none | **4 rows with topic_ended=True** |
| API calls | total=64 | total=62 (subprocess 57 + direct 5) |
