# 2026-08-08 Changelog Overview

[Back to Index](../README.md)

---

## Updates

- [01 Message Pool Multi-User Interaction Infrastructure](#01-message-pool-multi-user-interaction-infrastructure)
- [02 Message Pool Data Collection & Multi-Agent Launch Script](#02-message-pool-data-collection--multi-agent-launch-script)
- [03 Role Seed System GUI & Personality Formatting](#03-role-seed-system-gui--personality-formatting)
- [04 Map as a Dedicated Sidebar Page](#04-map-as-a-dedicated-sidebar-page)
- [05 Database Redundancy Cleanup & MemOS Index Deduplication](#05-database-redundancy-cleanup--memos-index-deduplication)
- [06 Knowledge Graph Physics Engine Fixes](#06-knowledge-graph-physics-engine-fixes)
- [07 Knowledge Graph Semantic Data Filtering & "Ideas" Category](#07-knowledge-graph-semantic-data-filtering--ideas-category)
- [08 Random Role Seeds, Self-Introductions & Topic Broadcast](#08-random-role-seeds-self-introductions--topic-broadcast)
- [09 Inter-Agent Multi-Round Dialogue & Topic Round Control](#09-inter-agent-multi-round-dialogue--topic-round-control)
- [10 Yield Mechanism (Anti-Self-Talk) & Chatroom Terminology](#10-yield-mechanism-anti-self-talk--chatroom-terminology)
- [11 Topic Report Generator: Mutual Cognition & Personality Drift](#11-topic-report-generator-mutual-cognition--personality-drift)
- [12 Cognition Memory Generation Names the Speaker](#12-cognition-memory-generation-names-the-speaker)
- [13 Agent Subprocess Architecture: Multiple Independent AAA Processes](#13-agent-subprocess-architecture-multiple-independent-aaa-processes)
- [14 Stream-of-Consciousness Sync: Silent Decisions Also Carry Thoughts](#14-stream-of-consciousness-sync-silent-decisions-also-carry-thoughts)
- [15 API Call Statistics: Experiment Report Records Total and Per-Agent Counts](#15-api-call-statistics-experiment-report-records-total-and-per-agent-counts)

---

## Summary

| # | Core change | Root cause | Impact |
|---|------------|------------|--------|
| 01 | Built the multi-user interaction experiment infrastructure (F1–F8, no experiments) per the `[PLAN] 消息池与弹幕式消息处理方案` design: AAA side adds `_on_pool_batch` batch entry, `batch_mode` explicit `{action: reply|silent}` decisions, v6.0 user_id migration and per-user cognition isolation; platform side adds the `tests/message_pool/` package (event bus / danmaku pool / @ mention routing / speech arbiter / collector / agent bridge / platform orchestration) | Multi-agent danmaku scenarios need batched consumption, speaker attribution, per-user cognition isolation, silent handling, a single speech floor, and structured data collection — the existing single-message `_on_text` path and user-less memory cannot support this | GUI direct path and existing tests are unaffected (new parameters have defaults); the pool experiment can reuse the platform package to orchestrate multiple agents and collect events/decisions/evolution data |
| 02 | Completed experiment data collection and launching: new `data_export.py` (per-agent raw DB exported by table + chat history md render), `collector.py`/`platform_runner.py` add `chat_history.jsonl` (user danmaku + agent broadcasts), new `run_pool_experiment.py` launch script (`--agents` default 5, count adjustable) | The experiment needs raw DB per-table dumps, message-pool chat history, and one-command multi-agent launching; the original platform only had events/decisions/evolution and the DB export logic was scattered in an old acceptance script | Each run gets an independent timestamped archive (runs/) with db/{agent}_final/ per-table JSON + sqlite, chat_history, events/decisions/evolution, _run_meta |
| 03 | Role seed system Phase 3/4 wrap-up: `write_seed_background` now writes to `event_summary` (source='seed', idempotent); `format` merged with "clear database" — wipes ALL tables (incl. fixed_cognition) + resets personality + clears GUI chat history; seed slider labels unified to full-width colons | Seed backgrounds landed in the QA table with wrong semantics; formatting did not fully clear the DB and duplicated the clear feature; slider labels used half-width colons | Settings panel keeps a single "personality formatting (wipe & redo)" entry; repeated formatting never duplicates seed backgrounds |
| 04 | Map moved from the settings floating panel to a dedicated sidebar page: new `location_page.py` (LocationPage), sidebar adds a "Map" tab, main_window registers and lazy-loads it, settings panel loses its map area | The map is runtime state visualization; mixing it with settings config bloated the panel and limited its space | Sidebar switches to the standalone map page; map components load on demand |
| 05 | DB redundancy cleanup + MemOS index dedup: v5.4 migration `DROP TABLE retrieval_log` (dead table); MemOS index drops the user_messages source (only long_term_memory + diaries), dead `_fetch_feeling` removed; data browser gains mood_value/personality_seed translations, drops the retrieval_log entry | retrieval_log was never written; dialogue is already merged into long_term_memory as QA, so dual-source indexing duplicated retrieval hits | Retrieval returns no duplicates; every table in the data browser has a Chinese label |
| 06 | Knowledge graph physics fixes: nodes spawn at the same coordinate (canvas center) with random impulse; force scale L scales repulsion radius and attraction balance (clamped 25–120), center gravity fixed; rectangular bounce replaced by a circular soft boundary (no boundary force within 750px); `_expand_scene_to_fit` grows the canvas dynamically; edges stream in | Random spawns broke the physics initial state; L only scaled repulsion strength so the force scale felt dead; the margin=30 rectangular bounce pushed nodes into a square outline at high L | At max force scale nodes spread freely into a round distribution with no square outline; L=1 default layout behavior unchanged |
| 07 | Knowledge graph semantic data filtering & "Ideas" category: `MEMORY_QUERIES` v4 filters (feelings only with thought, long_term_memory drops tool/diary/short entries, diaries added, GRAPH_INDEX_VERSION 3→4); feelings category unified to 'feelings' (v5); browser label "情感"→"想法"; graph hover shows [想法] | Low-distinction records (pure mood words / tool returns / full diary texts) and transient metadata tables flooded the graph; ideas (thought) were not presented as "ideas" | The 117-node graph now holds only valid semantic memories; the data browser shows an "Ideas" filter |
| 08 | Multi-agent startup initialization: random role seeds (4-D vector 0.1–0.9 + random style from a 6-entry pool, `--seed` reproducible) + each agent self-introduces from its role seed (stage=self_intro) + the platform broadcasts a topic after the intros (`--topic` > `topic.txt` > default); fixed `init_character` silently failing to write personality_seed on fresh DBs | The fixed seed made every agent start identical; startup had no self-intro/topic phases and topics were not configurable | Distinct roles every run; chat_history includes self-intros and the topic; `_run_meta.json` records seed/topic; edit `topic.txt` to change the topic between restarts |
| 09 | Inter-agent multi-round dialogue & topic round control: broadcast speeches re-enqueue into the pool (source=agent, dedup=False) so other agents reply next round; `--topic-rounds N` (default 10, 0=unlimited; counts only successfully enqueued agent speeches, background thinking/summaries excluded) triggers a platform topic-end announcement (role=system + topic_ended event); `enqueue_input` gained a `dedup` flag; session-driven main loop | Agent broadcasts never re-entered the pool so agents could not converse with each other; topic-session length was uncontrollable | Acceptance 39/39; real test: 2 agents held a natural 10-round conversation (evolving puzzle metaphor), platform announced the end after round 10, the agent answered once more, then the conversation stopped |
| 10 | Yield mechanism (anti-self-talk): the last agent to broadcast is skipped for the next batch (exempt when `@`-mentioned; yield released when everyone else stays silent to avoid stalls); zero AAA intrusion (identity is tracked by the platform via agent_id); fixed a latent bug where `arbiter.release()` semantics silently dropped QUEUE speeches; unified 弹幕→chatroom terminology | Fixed dispatch order + first-come-first-served arbitration gave agent:0 a systematic speech advantage; QUEUE speeches were never broadcast | Acceptance 42/42; real 2-agent 10-round test alternates 5:5 with no self-talk; queued speeches broadcast correctly |
| 11 | Topic report generator `topic_report.py`: at topic end writes `topic_report.md` analyzing mutual cognition memory (other_cognition source×target matrix + bidirectional verdict + excerpts) and personality drift tendency (initial seed vs final vector Euclidean distance); `_run_meta.json` now records each agent's initial seed; report auto-generated at teardown; **n-agent full coverage** (auto-discovers all agents via glob, verified with 3-agent fixture + real run) (aligned with the experiment design's collection method) | evolution.json only had other-cognition counts and could not answer "did agents come to know each other" nor "did personalities drift"; personality_seed holds only the final vector, so without persisted seeds no drift baseline existed | Acceptance 57/57 (new U6, 15 checks); backfilled real run yield10 shows mutual cognition formed (0→1 ×4, 1→0 ×3) and drift 0 (short topic never hits the evolution threshold); 3-agent fake run shows 3×3+other matrix, correct gid; old runs without seeds fall back to the first decisions.jsonl snapshot; fixed run_dir containing `_final` excluding all agent DBs |
| 12 | Cognition memory generation names the actual speaker: DIRECT_TEMPLATE 他人认知/用户信息/用户记忆 now inject `current_user_label` (user_id, fallback 用户) and demand named-target, detailed descriptions; Background Review persistence chain (build_review_prompt / persist_insight / run_review / trigger chain / response callback) carries user_id so declarative user facts land in user_facts with speaker attribution | LLM generated other-cognition/user-info/user-memory with the generic "用户" and review-persisted declarative facts were written without user_id → ownerless memories are ambiguous and cross-contaminate in multi-person scenarios | Prompt building verified (三段渲染"当前对话对象 agent:1"); review declarative lands with user_id='agent:1'; acceptance 57/57, no regression; single-user behavior unchanged (fallback 用户 / global facts) |
| 13 | Agent subprocess architecture (F9): the platform becomes the parent process, one independent AAA subprocess per Agent. New `aaa_serve.py` resident service (one-JSON-per-line protocol over stdin/stdout: ping / pool_batch / flush_review / shutdown; LLM injected via env vars; AAA_SKIP_HEAVY=1 skips model loading); `agent_bridge.py` switched to subprocess bridging (auto-restart on crash + stderr log redirection + close reclamation); `platform_runner.py` parallel decisions + @ priority arbitration (sorted by mention after decisions complete, not first-come-first-served); `run_pool_experiment.py` subprocess mode by default with `--inline` single-process control retained | Single-process multi-instance sharing the memos index risks races/native crashes, crash cascade, and no real parallelism under GIL; LLM is an HTTP direct connection so concurrency comes naturally | Process-level isolation (per-subprocess memos index / background threads), crash isolation with auto-restart, parallel decision speedup; memory budget ~80MB per subprocess (Agent ≤ 5); zero AAA node code changes |
| 14 | Stream-of-consciousness sync: silent decisions (`action=silent`) now also carry thought/mood. prompt.py makes 想法 mandatory (must write the inner stream even when 自然回复 is empty) and clarifies 自然回复 empty = silent; main.py batch-mode fallback (no thought → "收到消息，保持观察，暂不回应", no mood → "平静"); reply/no-reply still decided solely by whether 自然回复 has text (decision logic unchanged). Test stability: I1/I2 shared fake_llm counter replaced with per-Agent deterministic LLMs (removes F9 parallel-thread race), U7 ping threshold 1s→2s | Real LLM emitted no 想法 section when silent; `parse_llm_output` skips empty sections → silent records in decisions.jsonl had empty thought/mood; fake LLM always emits thoughts so smoke testing never caught it | Temporary script verified 3 scenarios (reply+thought / silent+thought / silent fallback); `infra_acceptance_test.py` 64/64 twice in a row; GUI single-user conversation unaffected (batch_mode=False bypasses the fallback) |
| 15 | API call statistics: aaa_serve `_make_llm` counting wrapper (decisions + background reviews all pass through llm_fn) + new `llm_stats` protocol request; agent_bridge new `llm_stats()` (subprocess queries child count / inline decision-path count); run_pool_experiment platform-direct counting + teardown persists `llm_stats.json` (mode/fake_llm/platform_direct/per_agent/total); topic_report adds "四、API 调用量统计" section (total + subprocess/direct split + per-Agent detail with share, graceful degradation when missing) | Under the subprocess architecture LLM calls happen inside AAA subprocesses, invisible to the platform — no stats channel existed in the protocol, so API cost and call distribution could not be audited | Acceptance 68/68 (U7 llm_stats 2 checks + U6 report 2 checks); smoke total=35 (subprocess 32 + direct 3); the 5-Agent 40-round real experiment report shows total and per-Agent detail |

---

### 01 Message Pool Multi-User Interaction Infrastructure

See [01_MessagePoolMultiUserInfrastructure.md](./01_MessagePoolMultiUserInfrastructure.md).

### 02 Message Pool Data Collection & Multi-Agent Launch Script

See [02_MessagePoolDataCollectionAndLauncher.md](./02_MessagePoolDataCollectionAndLauncher.md).

### 03 Role Seed System GUI & Personality Formatting

See [03_RoleSeedGUIAndPersonalityFormatting.md](./03_RoleSeedGUIAndPersonalityFormatting.md).

### 04 Map as a Dedicated Sidebar Page

See [04_MapAsSidebarPage.md](./04_MapAsSidebarPage.md).

### 05 Database Redundancy Cleanup & MemOS Index Deduplication

See [05_DBRedundancyCleanupAndMemOSIndexDedup.md](./05_DBRedundancyCleanupAndMemOSIndexDedup.md).

### 06 Knowledge Graph Physics Engine Fixes

See [06_KGForcePhysicsEngineFixes.md](./06_KGForcePhysicsEngineFixes.md).

### 07 Knowledge Graph Semantic Data Filtering & "Ideas" Category

See [07_KGSemanticDataFilteringAndIdeasCategory.md](./07_KGSemanticDataFilteringAndIdeasCategory.md).

### 08 Random Role Seeds, Self-Introductions & Topic Broadcast

See [08_RandomRoleSeedsSelfIntroAndTopic.md](./08_RandomRoleSeedsSelfIntroAndTopic.md).

### 09 Inter-Agent Multi-Round Dialogue & Topic Round Control

See [09_InterAgentDialogueAndTopicRounds.md](./09_InterAgentDialogueAndTopicRounds.md).

### 10 Yield Mechanism (Anti-Self-Talk) & Chatroom Terminology

See [10_YieldMechanismAndChatroomTerminology.md](./10_YieldMechanismAndChatroomTerminology.md).

### 11 Topic Report Generator: Mutual Cognition & Personality Drift

See [11_TopicReportGeneratorMutualCognitionAndPersonalityDrift.md](./11_TopicReportGeneratorMutualCognitionAndPersonalityDrift.md).

### 12 Cognition Memory Generation Names the Speaker

See [12_CognitionMemoryNamesSpeaker.md](./12_CognitionMemoryNamesSpeaker.md).

### 13 Agent Subprocess Architecture: Multiple Independent AAA Processes

See [13_AgentSubprocessPlatform.md](./13_AgentSubprocessPlatform.md).

### 14 Stream-of-Consciousness Sync: Silent Decisions Also Carry Thoughts

See [14_StreamOfConsciousnessSync.md](./14_StreamOfConsciousnessSync.md).

### 15 API Call Statistics: Experiment Report Records Total and Per-Agent Counts

See [15_API_CallStatistics.md](./15_API_CallStatistics.md).

---

## Modified Files

### New Files

| File | # |
|------|---|
| `tests/message_pool/__init__.py` | 01、10 (wording) |
| `tests/message_pool/event_bus.py` | 01 |
| `tests/message_pool/message_pool.py` | 01、09、10 (wording) |
| `tests/message_pool/router.py` | 01 |
| `tests/message_pool/arbiter.py` | 01、10 (release semantics fix) |
| `tests/message_pool/collector.py` | 01、02、10 (wording) |
| `tests/message_pool/agent_bridge.py` | 01、10 (wording)、13 (subprocess bridging)、15 (llm_stats + inline counting) |
| `tests/message_pool/platform_runner.py` | 01、02、08、09、10 (yield mechanism)、13 (parallel decisions + priority arbitration) |
| `tests/message_pool/data_export.py` | 02、08、09、10 (wording) |
| `tests/message_pool/run_pool_experiment.py` | 02、08、09、10 (wording)、13 (--inline + aaa_env + cleanup)、15 (direct counting + llm_stats.json) |
| `tests/message_pool/topic.txt` | 08 |
| `tests/message_pool/infra_acceptance_test.py` | 01、02、08、09、10 (42 checks)、11 (U6, 9 checks)、13 (U7, 7 checks)、14 (per-agent deterministic fake LLM + ping threshold)、15 (llm_stats 2 checks + report stats 2 checks) |
| `tests/message_pool/topic_report.py` | 11、15 (API stats section) |
| `tests/message_pool/aaa_serve.py` | 13、15 (counting wrapper + llm_stats protocol) |
| `tests/message_pool/README.md` | 01、02、08、09、10、11 |
| `docs/cogevo/[PLAN] 消息池与弹幕式消息处理方案（多用户交互实验）.md` | 01、10 (wording) |
| `gui/pages/location_page.py` | 04 |

### Major Changes

| File | Change | # |
|------|--------|---|
| `nodes/node_python_aaa_cognition/db.py` | v6.0 user_id column migration (user_messages / event_summary / other_cognition / user_facts); user_id dimension in `_dedup_and_merge` / `_write` / `_write_parsed`; new `g_where_identity_user` (user-specific first, global fallback) | 01 |
| `nodes/node_python_aaa_cognition/main.py` | new `_on_pool_batch` (batched write + F5 merged context + `_observe_counter`); `_on_parsed` batch_mode explicit decisions; `_gather_context` user_id / batch_items / pool_batch_section; fixed lost reflection-round pending context | 01 |
| `nodes/node_python_aaa_cognition/prompt.py` | cognition-label and user-text placeholders in `_CONTEXT_HEADER` (per-user rendering and batch section); #12 他人认知/用户信息/用户记忆 inject `current_user_label` (named target + detailed); #14 想法 mandatory (write inner stream even when silent) + 自然回复 empty = silent | 01、12、14 |
| `nodes/node_python_aaa_cognition/main.py` | #14 `_on_parsed` batch-mode fallback defaults for thought/mood (silent decisions carry state) | 14 |
| `tests/message_pool/collector.py` | New chat_history.jsonl output and `chat()` method | 02 |
| `tests/message_pool/platform_runner.py` | inject/step/drain_queue record chat history (role=user / agent) | 02 |
| `tests/message_pool/platform_runner.py` | New `record_speech` (self-intro, no pool enqueue) and `announce` (topic broadcast, pool enqueue + role=topic record) | 08 |
| `tests/message_pool/data_export.py` | Chat-history md renders role=topic and agent stage labels | 08 |
| `tests/message_pool/run_pool_experiment.py` | Random role seeds (--seed reproducible), self-intro phase, topic broadcast (--topic/--topic-file), init_character ensure-table fix | 08 |
| `tests/message_pool/platform_runner.py` | `topic_rounds` round control, broadcast re-enqueue (`_feed_agent_speech`), platform topic end (`_end_topic`) | 09 |
| `tests/message_pool/platform_runner.py` | `step()` parallel `process_batch` across target agents + @ mention priority arbitration after decisions complete (mentioned agent wins even if slower) | 13 |
| `tests/message_pool/message_pool.py` | `enqueue_input` `dedup` flag (agent re-enqueue skips dedup) | 09 |
| `tests/message_pool/run_pool_experiment.py` | `--topic-rounds` flag (default 10, 0=unlimited), session-driven main loop | 09 |
| `tests/message_pool/run_pool_experiment.py` | `_run_meta.json` records per-agent initial seeds; calls `generate_topic_report` at teardown for topic_report.md | 11 |
| `tests/message_pool/topic_report.py` | New: mutual-cognition matrix / bidirectional verdict / excerpts; personality drift (initial seed vs final vector Euclidean distance); E3 metrics table | 11 |
| `tests/message_pool/data_export.py` | Chat-history md renders role=system (platform topic-end announcement) | 09 |
| `nodes/node_python_aaa_cognition/db.py` | `write_seed_background` target changed from long_term_memory to event_summary (source='seed'); v5.2 migration adds event_summary.source | 03 |
| `nodes/node_python_aaa_cognition/main.py` | `clear` removed; `format` wipes all tables + `reset_personality_seed` + `_clear_conversation_history` | 03 |
| `nodes/node_python_aaa_cognition/review.py` | #12 build_review_prompt annotates speaker (user_id); persist_insight/run_review carry user_id so declarative facts land in user_facts with speaker attribution | 12 |
| `nodes/node_python_aaa_cognition/main.py` | #12 review trigger chain (`_get_recent_conversation` / `_trigger_background_review` / `_run_background_review` / `_on_review_response`) carries user_id | 12 |
| `gui/pages/settings_panel.py` | "clear database" merged into "personality formatting"; seed slider full-width colons | 03、04 |
| `gui/dialogs/personality_dialog.py` | Slider labels use full-width colons | 03 |
| `gui/widgets/sidebar.py` | New "Map" tab | 04 |
| `gui/main_window.py` | Registers location page; lazy load in `_after_page_switch` | 04 |
| `nodes/node_python_aaa_cognition/db.py` | v5.4 migration drops retrieval_log (creation statement removed) | 05 |
| `nodes/node_python_aaa_cognition/memos.py` | Index source drops user_messages (only long_term_memory + diaries); `_fetch_feeling` dead code removed | 05 |
| `gui/widgets/knowledge_panel.py` | Translations added for mood_value/personality_seed, retrieval_log entry removed | 05 |
| `gui/widgets/knowledge_graph.py` | Same-coordinate spawn; force-scale L scaling (repulsion radius / attraction balance); fixed gravity; circular soft boundary replacing rectangular bounce; `_expand_scene_to_fit`; streaming edges; node display reset with impulse | 06 |
| `nodes/node_python_aaa_cognition/memos.py` | MEMORY_QUERIES v4 semantic filtering + diaries added (GRAPH_INDEX_VERSION 3→4); feelings category → 'feelings' (GRAPH_INDEX_VERSION 4→5) | 07 |
| `gui/widgets/knowledge_panel.py` | TABLE_LABELS feelings "情感"→"想法" | 07 |
| `gui/widgets/knowledge_graph.py` | CATEGORY_LABELS mapping + hover tooltip shows "想法" | 07 |

---

**Last updated**: 2026-08-08
