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
- [16 Reply-Context Annotation: Chat History & Decision Context Show "Who Is Responding to Whom"](#16-reply-context-annotation-chat-history--decision-context-show-who-is-responding-to-whom)
- [17 Experiment Data Quality & Mechanism Fixes: Failure/Silent Split, user_id Attribution, Last-Message Bias, Personality Evolution Break, Reply-Chain Injection](#17-experiment-data-quality--mechanism-fixes-failuresilent-split-user_id-attribution-last-message-bias-personality-evolution-break-reply-chain-injection)
- [18 Six Data-Quality Fixes & Cold-Bench Rotation for Last-Message Bias](#18-six-data-quality-fixes--cold-bench-rotation-for-last-message-bias)
- [19 Unified Batch-Order Source of Truth & Seven-Item Data Collection](#19-unified-batch-order-source-of-truth--seven-item-data-collection)
- [20 Interest-Gate Reply Mechanism](#20-interest-gate-reply-mechanism)

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
| 16 | Reply-context annotation: prompt adds conditional 【回应对象】 output section (batch scenarios only); batch_mode decisions return 【回应对象】; agent_bridge records batch_context (authors + content excerpts); data_export renders "LLM-explicit reply target > batch author list" + legacy-batch rebuild fallback (per pool-dispatch rules) | Multi-agent chat logs did not show who answers whom: no reply-target requirement in the prompt, no decision field, no renderer annotation | Acceptance 78/78 (U8, 10 checks + I1/I2, 3 checks); rerender of run 101510 shows annotations; run 103432 persists LLM-explicit reply targets and renders them with priority |
| 17 | Experiment data quality & mechanism fixes: **P0-1** failure/silent split (agent_bridge/platform_runner failures → `action=error`, collector error_count, topic_report silence rate excludes error); **P0-2** user_id attribution = LLM-explicit reply target (silent/group no attribution, no more batch-tail); **P1-3** last-message bias (`_batch_for` moves `@` messages to batch end + prompt guidance); **P1-4** personality evolution break (`_adjust_vector` evolves on neutral feedback — root cause: constant neutral reaction left pos/neg empty so nothing ever adjusted); **reply-chain injection v6.4** (Message / arbiter / re-feed / batch annotation four-layer reply_to pass-through, LLM decisions now see "who replies to whom") | Post-mortem of the balance-exhausted 5a40r_v2 run exposed: 189 HTTP-402 failures fell into silent (84% fake silence rate), user_id attribution pointed at the batch tail (3 runs in a row), last-message bias created cognition black holes, zero personality drift while mood moved (pipeline break); missing reply chain made LLM decisions inconsistent with what humans read | Acceptance 96/96 (U9, 12 checks + U10, 6 checks); llm_stats fix verified total=291 with all agents > 0; pending: rerun the 5-Agent 40-round experiment after recharging |
| 18 | Six data-quality fixes (driven by the 111908 data-verification post-mortem): **A** self-cognition pollution guard (batch_mode attribution excludes `reply_target == identity_key`); **B** silence-template split by action (reply with no thought falls back to empty string; only silent uses "收到消息，保持观察"); **C** ghost-speech accounting (residual batches after topic_ended get `topic_ended=True` in decisions; evolution records agent_speech_count/rounds_metric="processed_batches" triple bookkeeping); **D** truncation defense (max_tokens 2048→4096 + parser strips incomplete section markers); **E** cold-bench rotation (the least-responded speaker moves to batch end, `@` priority exempt); **F** forced mood-tag output (both reply and silent must emit an 【情绪调整】 number) | Reported numbers were wrong (6 bidirectional pairs, not 7; 7-11 decisions per agent, not 12-15 — llm_stats call counts were misread) + 6 confirmed issues: agent:2 self-cognition pollution, silence-template leaking into a reply, 4 ghost replies after topic end, truncated replies, last-message bias leaving agent:0 a cognition black hole (stable across experiments), agent:3 mood stuck at 0.0 | Acceptance 111/111 (U11, 15 checks); v2 rerun evidence: agent:0 black hole broken (matrix column 1/2/3/4), 8 bidirectional pairs, 0 truncations, 0 template pollution, 0 self-cognition, 4 ghost speeches flagged; llm_stats total=62 with no 402; personality drift still 0 (short experiments cannot reach the evolution threshold — threshold lowering pending) |
| 19 | v6.6 six-issue fixes + seven-item data collection (driven by the 111908 analysis report): **P0-1** batch-order single source of truth (Message.seq global number + `ordered` single source; decisions/events cross-validated); **P0-2** empty user_id filtering (batch-mode skip_empty_other on the write side + defensive read-side filter); **P1-3** ghost-speech source fuse (step/drain_queue return early when `not topic_active`); **P1-4** truncation detection + retry (is_truncated dual signals: unclosed section marker / has 自然回复 but missing 情绪调整); **P1-5** last-message-bias quantification (reply_target_pos / batch_last_author / mention_responded / attribution_ok); **P1-6** evolution fallback threshold 30→10; **collection**: memory_usage table (P0-1), silent_cognition table (P0-2), evolution.trajectory (P0-3), topic_report chapters 5–11 (P1-4/P1-5/P2-6/P2-7) | v2 analysis report leftovers: two batch-order sources, empty attribution polluting the cognition matrix, ghost speeches not eliminated (35 vs 30), round_9_agent_1 truncation, last-message bias still high, zero personality drift (threshold 30 unreachable) | Acceptance 142/142 (U12, 31 checks); v3 rerun evidence: P0-1/P0-2/P1-3/P1-4 eliminated (events carry seq from the same source, matrix has no empty key, 31 vs 30 with normal fuse, 0 truncations); P1-5 quantified at 80.6% still present (collection achieved); P1-6 threshold 10 still not hit (lower to ≤5 pending); collected: silent_cognition 6, full trajectories, bidirectional 0→6, attribution accuracy 93%, memory_hits 0 (no retrieval triggered) |
| 20 | v7.0 interest-gate reply mechanism (explicit reply-target determination — the mechanistic fix for the 80.6% last-message bias seen in 5a30r_v3): new `interest_gate.py` (platform-shared multilingual model, encode-once/compare-many; interest anchor = latest speech; `sim(msg, anchor) ≥ 0.60` passes); the gate decides only *who* decides (LLM context stays the full batch); non-passing agents skip the LLM (call savings); judgments (**detected text + interest value**, explicit user requirement) are written to each agent's `interest_judgment` table; `@`/`reply_to` pass directly (direct); when none pass, the highest-interest agent passes via interest_floor; arbitration order `@ > interest > cold bench`; threshold calibrated to 0.600 on real v3 data (0.7 drops 68% of real replies)**; v7.1 increment: recent-observation injection (option a) — the latest N non-passed (`passed=0`) detected texts are injected into passing agents' context via `db.read_recent_observations()` as the 【近期观察记录】 section, making "seen but unanswered" recallable at zero extra LLM calls**; **v7.2 increment: bystander reply-entry judgment + sliding attention window — `judge_sequence` judges messages one-by-one by seq from oldest to newest (no dedup per speaker: 1's first speech, 2's second-earliest, 1's third reply judged independently); the first passing speech = the reply-entry point (target + target_speaker persisted); a passing agent's decision context = the `(own latest speech, entry message]` reply window (no own speeches, no truncation); never-spoken agents use the pool start as the lower bound; `batch_context` = window + `batch_full` = full batch (dual bookkeeping); anchor slides with each speech** | Last-message bias roots in "the reply target is freely inferred by the LLM" (using the last message as a shortcut); cold-bench rotation only relocates the bias; disinterested agents were also forced to call the LLM every batch (wasted calls); whole-batch "highest interest" judgment dilutes interesting messages and cannot express "start replying after so-and-so" | Acceptance 158/158 (U13, 16 checks) → v7.1 U13.7 (5 checks) → 163/163 → **v7.2 U13.8 (6 checks) → 169/169**; 5a20r_v2 real run: last-position reply rate 80.6%→58.8%, 25 of 55 judgments rejected (25 LLM calls saved of 33 total), 55 interest_judgment rows fully queryable; 5a20r_v3 (gate + injection, new seeds): last-position 66.7%, bidirectional cognition **6 pairs** (v2 had 3, no black hole), low-curiosity agents not silenced — confirming the black hole is a seed×topic combination effect; **v4 real run (20-round philosophical): total=33 vs v3's 41 (-19.5%), per-decision input -22% (window narrowing), agent:1/3 33/33 passed=0 evidencing genuine disinterest; 60-round new topic (AI self-awareness): 60/60 rounds, total=102, per-agent 16-22 extremely even, per-round cost 1.70 flat — cost follows participation, not round count; Experiment B linkage: group C extreme contrast (warmth 0.1 vs 0.9) d=+0.962 / p=0.0000 highly significant, the "state→output" loop proven for the first time; real-drift groups show no significance (statistical-power shortfall, not injection failure)**; open: topic-tunnel effect, injection's standalone contribution needs 40+ rounds, isomorphic-batch comparison needed to confirm the bias drop |

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

### 16 Reply-Context Annotation: Chat History & Decision Context Show "Who Is Responding to Whom"

See [16_ReplyContextAnnotation.md](./16_ReplyContextAnnotation.md).

### 17 Experiment Data Quality & Mechanism Fixes: Failure/Silent Split, user_id Attribution, Last-Message Bias, Personality Evolution Break, Reply-Chain Injection

See [17_DataQualityAndMechanismFixes.md](./17_DataQualityAndMechanismFixes.md).

### 18 Six Data-Quality Fixes & Cold-Bench Rotation for Last-Message Bias

See [18_SixDataQualityFixesAndColdBenchRotation.md](./18_SixDataQualityFixesAndColdBenchRotation.md).

### 19 Unified Batch-Order Source of Truth & Seven-Item Data Collection

See [19_UnifiedBatchOrderAndSevenItemDataCollection.md](./19_UnifiedBatchOrderAndSevenItemDataCollection.md).

### 20 Interest-Gate Reply Mechanism

See [20_InterestGateReplyMechanism.md](./20_InterestGateReplyMechanism.md).

---

## Modified Files

### New Files

| File | # |
|------|---|
| `tests/message_pool/__init__.py` | 01、10 (wording) |
| `tests/message_pool/event_bus.py` | 01 |
| `tests/message_pool/message_pool.py` | 01、09、10 (wording)、17 (Message reply_to field) |
| `tests/message_pool/router.py` | 01 |
| `tests/message_pool/arbiter.py` | 01、10 (release semantics fix)、17 (request_speech/queue reply_to pass-through) |
| `tests/message_pool/collector.py` | 01、02、10 (wording)、17 (error_count) |
| `tests/message_pool/agent_bridge.py` | 01、10 (wording)、13 (subprocess bridging)、15 (llm_stats + inline counting)、16 (batch_context)、17 (failure→error + reply_to) |
| `tests/message_pool/platform_runner.py` | 01、02、08、09、10 (yield mechanism)、13 (parallel decisions + priority arbitration)、17 (_batch_for @-to-end + error branch + reply_to re-feed) |
| `tests/message_pool/data_export.py` | 02、08、09、10 (wording)、16 (reply-target annotation + legacy rebuild) |
| `tests/message_pool/run_pool_experiment.py` | 02、08、09、10 (wording)、13 (--inline + aaa_env + cleanup)、15 (direct counting + llm_stats.json) |
| `tests/message_pool/topic.txt` | 08 |
| `tests/message_pool/infra_acceptance_test.py` | 01、02、08、09、10 (42 checks)、11 (U6, 9 checks)、13 (U7, 7 checks)、14 (per-agent deterministic fake LLM + ping threshold)、15 (llm_stats 2 checks + report stats 2 checks)、16 (U8, 10 checks)、17 (U9, 12 checks + U10, 6 checks) |
| `tests/message_pool/topic_report.py` | 11、15 (API stats section)、17 (error stats, silence rate excludes failures) |
| `tests/message_pool/aaa_serve.py` | 13、15 (counting wrapper + llm_stats protocol)、17 (fallback user_id not batch-tail) |
| `tests/message_pool/README.md` | 01、02、08、09、10、11 |
| `docs/cogevo/[PLAN] 消息池与弹幕式消息处理方案（多用户交互实验）.md` | 01、10 (wording) |
| `gui/pages/location_page.py` | 04 |
| `docs/changelogs/en/2026-08-08/18_SixDataQualityFixesAndColdBenchRotation.md` | 18 |
| `docs/changelogs/en/2026-08-08/19_UnifiedBatchOrderAndSevenItemDataCollection.md` | 19 |
| `docs/changelogs/en/2026-08-08/20_InterestGateReplyMechanism.md` | 20 |
| `tests/message_pool/interest_gate.py` | 20 |
| `tests/message_pool/calibrate_interest_threshold.py` | 20 |
| `docs/cogevo/[PLAN]-兴趣门控回复机制.md` | 20 |
| `tests/personality_output_probe.py` | 20 v7.2 (Experiment B: personality-drift output-impact verification) |

### Major Changes

| File | Change | # |
|------|--------|---|
| `nodes/node_python_aaa_cognition/db.py` | v6.0 user_id column migration (user_messages / event_summary / other_cognition / user_facts); user_id dimension in `_dedup_and_merge` / `_write` / `_write_parsed`; new `g_where_identity_user` (user-specific first, global fallback) | 01 |
| `nodes/node_python_aaa_cognition/main.py` | new `_on_pool_batch` (batched write + F5 merged context + `_observe_counter`); `_on_parsed` batch_mode explicit decisions; `_gather_context` user_id / batch_items / pool_batch_section; fixed lost reflection-round pending context | 01 |
| `nodes/node_python_aaa_cognition/prompt.py` | cognition-label and user-text placeholders in `_CONTEXT_HEADER` (per-user rendering and batch section); #12 他人认知/用户信息/用户记忆 inject `current_user_label` (named target + detailed); #14 想法 mandatory (write inner stream even when silent) + 自然回复 empty = silent; #16/#17 【回应对象】 conditional output section + guidance to pick from the whole batch (not necessarily last, @ priority) | 01、12、14、16、17 |
| `nodes/node_python_aaa_cognition/main.py` | #14 `_on_parsed` batch-mode fallback defaults for thought/mood (silent decisions carry state); #16/#17 batch_mode returns 【回应对象】; batch user_id attribution = reply target; `_fmt_pool_msg` renders "回应谁" reply chain into batch context | 14、16、17 |
| `nodes/node_python_aaa_cognition/personality.py` | `_adjust_vector` evolves on neutral feedback (personality zero-drift root cause fix) | 17 |
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
| `nodes/node_python_aaa_cognition/main.py` | 18 batch_mode attribution excludes self-cognition (`reply_target == identity_key` → user_id cleared); silence-template split by action (reply with no thought falls back to empty; silent uses "收到消息，保持观察") | 18 |
| `tests/message_pool/platform_runner.py` | 18 cold-bench rotation (`_responded` counts + least-responded speaker moved to batch end; @ priority exempt; platform/single messages excluded); `_end_topic` sets `collector.topic_ended`; evolution records agent_speech_count / rounds_metric="processed_batches" triple bookkeeping | 18 |
| `tests/message_pool/collector.py` | 18 `topic_ended` field (residual batches after topic end get `topic_ended=True` in decisions) | 18 |
| `tests/message_pool/aaa_serve.py` | 18 max_tokens 2048→4096 (truncation defense) | 18 |
| `tests/message_pool/run_pool_experiment.py` | 18 MAX_TOKENS 2048→4096 (truncation defense) | 18 |
| `nodes/node_python_aaa_cognition/parser.py` | 18 `_SECTION_FRAGMENT` strips incomplete section markers (unclosed `【情绪调整` lines no longer merge into the previous section) | 18 |
| `nodes/node_python_aaa_cognition/prompt.py` | 18 【情绪调整】 section hardened to force output (both reply and silent must emit a number) | 18 |
| `tests/message_pool/infra_acceptance_test.py` | 18 U11, 15 checks (A1/A2 self-cognition, B1/B2 silence template, C1-C3 ghost bookkeeping, D1/D2 truncation, E1-E5 cold bench, F1 mood tag) |
| `nodes/node_python_aaa_cognition/db.py` | 19 `_write_parsed` gains `skip_empty_other` (batch mode filters empty attribution); new `_write_memory_usage`/`record_memory_usage` (memory_usage table) and `_write_silent_cognition`/`record_silent_cognition` (silent_cognition table) | 19 |
| `nodes/node_python_aaa_cognition/memos.py` | 19 `_retrieve_hits` thread-local + `get_last_hits()` (P0-1 retrieval-hit pass-through) | 19 |
| `nodes/node_python_aaa_cognition/main.py` | 19 `_on_parsed` batch path returns `memory_hits`/`silent_cognition_written`/`cognition_sections`; `skip_empty_other=batch_mode`; truncation retry (inline path) | 19 |
| `nodes/node_python_aaa_cognition/parser.py` | 19 `is_truncated` dual signals (unclosed section marker / has reply but missing mood tag) + retry | 19 |
| `nodes/node_python_aaa_cognition/personality.py` | 19 `_FALLBACK_TRIGGER_COUNT` 30→10 (evolution fallback) | 19 |
| `tests/message_pool/message_pool.py` | 19 `Message.to_dict()` carries `seq` (global number); `enqueue_input` increments `_seq` (P0-1 source of truth) | 19 |
| `tests/message_pool/platform_runner.py` | 19 `ordered = {a: _batch_for(a, batch)}` single source; process_batch passes `mention_targets`; `_trajectory()` (P0-3); step/drain_queue `not topic_active` fuse (P1-3) | 19 |
| `tests/message_pool/agent_bridge.py` | 19 batch_context carries seq/pos; `reply_target_pos`/`batch_last_author`/`mention_targets`/`mention_responded`/`attribution_ok` (P1-5) | 19 |
| `tests/message_pool/aaa_serve.py` | 19 subprocess path `is_truncated` truncation retry | 19 |
| `tests/message_pool/topic_report.py` | 19 new chapters 5–11: last-message-bias quantification / @-mention response + attribution / mood-behavior / memory_hits / silent_cognition / trajectory / cognition-network timeline | 19 |
| `tests/message_pool/infra_acceptance_test.py` | 19 U12, 31 checks (P0-1 seq single source, P0-2 empty-attribution filter, P1-4 is_truncated four states, P1-5 quantification fields, P1-6 threshold-10 trigger, collection persistence, report-section rendering) | 19 |
| `nodes/node_python_aaa_cognition/db.py` | 20 ensure() adds the interest_judgment table (detected text / interest value / passed / reason) | 20 |
| `nodes/node_python_aaa_cognition/db.py` | 20 v7.1 adds `read_recent_observations()` (passed=0 filter + id-desc dedup + limit, error-safe) | 20 v7.1 |
| `nodes/node_python_aaa_cognition/main.py` | 20 v7.1 `_gather_context` injects recent_observations (cfg.recent_observations_limit, default 5) | 20 v7.1 |
| `nodes/node_python_aaa_cognition/prompt.py` | 20 v7.1 renders the 【近期观察记录】 section in `_CONTEXT_HEADER` (omitted when empty; 1-on-1 unaffected) | 20 v7.1 |
| `tests/message_pool/platform_runner.py` | 20 step() gate pre-filter (non-passing agents skip the LLM) + anchor updates (self-intro / after speech) + arbitration sort key (@ > interest > cold bench) | 20 |
| `tests/message_pool/run_pool_experiment.py` | 20 `--gate-threshold`/`--gate-model`/`--no-gate` + interest_gate config persisted to _run_meta | 20 |
| `tests/message_pool/topic_report.py` | 20 chapter 12 interest-gate collection (judgment count / pass rate / interest distribution / reason distribution / per-agent median) | 20 |
| `tests/message_pool/infra_acceptance_test.py` | 20 U13, 16 checks (encode-once, gate judgment, anchor update, persistence fields, platform integration, arbitration) + v7.1 U13.7, 5 checks (observation filter/limit/tolerance/prompt render) | 20 |
| `tests/message_pool/interest_gate.py` | 20 v7.2 adds `judge_sequence` (oldest-to-newest one-by-one no-dedup judgment + target/target_speaker persistence, direct priority) | 20 v7.2 |
| `tests/message_pool/platform_runner.py` | 20 v7.2 reply-entry window: `_msg_history`/`_last_speech_seq`/`_window_for` (`(own latest speech, entry message]`, no own speeches) + judge_sequence integration + gate_windows persistence | 20 v7.2 |
| `tests/message_pool/agent_bridge.py` | 20 v7.2 process_batch gains a window param + `decision["window_size"]` + `batch_context` = window / `batch_full` = full batch (dual bookkeeping) | 20 v7.2 |
| `tests/message_pool/infra_acceptance_test.py` | 20 v7.2 U13.8, 6 checks (one-by-one judgment, independent per-speaker judgment, direct priority, window range, never-spoken lower bound, batch_context/batch_full integration) → 169/169 | 20 v7.2 |

---

**Last updated**: 2026-08-08
