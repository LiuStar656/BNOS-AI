# Multi-Agent Random Role Seeds, Self-Introductions & Topic Broadcast

## Problem

At multi-agent experiment startup every agent used the same fixed role seed
(`{"warmth":0.6, "playfulness":0.4, "directness":0.5, "curiosity":0.5}`), so
initial personalities were identical; the launch flow went straight into the
danmaku loop with no "self-introduction" phase; and the platform had no
"topic broadcast" mechanism, leaving no way to change the experiment topic.

## Root Cause

- `init_character` hard-coded a fixed seed; `run_pool_experiment.py` never randomized it.
- The platform only had `inject()` (user danmaku enqueue) and `step()` (batch dispatch);
  there were no initialization-stage APIs for "broadcast self-introduction" or "broadcast topic".
- No topic configuration existed (neither CLI flag nor config file).
- Follow-up finding: `init_character` called `save_personality` directly on a brand-new
  database, but that function only INSERTs and never creates tables — the `personality_seed`
  table of new databases stayed empty (silent write failure, False return ignored).

## Solution

### 1. Platform initialization-stage APIs `platform_runner.py`

- `record_speech(agent_id, content, stage=...)`: records an agent utterance to chat history
  (**without enqueueing to the pool**; used for initialization display such as self-intros).
- `announce(content, role="topic", user_id="platform", priority=5, enqueue=True)`: platform
  topic/announcement broadcast — by default enqueues into the pool (all agents perceive it in
  the next `step()`) and records chat history (role=topic); `enqueue=False` only records.

### 2. Chat history rendering for new roles `data_export.py`

- `render_chat_history_md` now supports `role=topic` ("platform topic" line) and the `stage`
  label on `role=agent` entries (e.g. `（self_intro）`).

### 3. Launch-script initialization flow `run_pool_experiment.py`

- `random_seed(rng)`: random 4-D personality vector (0.1–0.9) + one of 6 speaking-style
  descriptions, written into `personality_seed` (preset_name="随机种子").
- `--seed INT`: pin the RNG to reproduce the same set of role seeds (default None = random each run).
- `build_intro_prompt` / `gen_self_intro`: build a self-intro prompt from the role seed and call
  the LLM; the result is broadcast via `plat.record_speech(..., stage="self_intro")`.
- `resolve_topic(args)`: priority `--topic text` > `--topic-file` (default
  `tests/message_pool/topic.txt`) > built-in default; broadcast via `plat.announce(topic)`.
- `init_character` fixed: `db.ensure(db_path)` (idempotent table creation) before `save_personality`.
- `_run_meta.json` records `seed` and `topic`; startup prints each agent's random seed and style.

### 4. Default topic file `topic.txt` (new)

- Edit the file to change the topic of the next experiment (effective on restart); or pass `--topic`.

### 5. Acceptance test `infra_acceptance_test.py`

- 3 new integration assertions: self-intro recorded (stage=self_intro), topic recorded
  (role=topic + platform), topic enqueued into the pool; user_messages ownership assertion
  now includes the platform topic (33 → 36 assertions).

## Affected Files

| File | Change |
|------|--------|
| `tests/message_pool/run_pool_experiment.py` | Random role seeds (--seed), self-intro phase, topic broadcast (--topic/--topic-file), init_character ensure-table fix |
| `tests/message_pool/platform_runner.py` | New `record_speech` / `announce` |
| `tests/message_pool/data_export.py` | Chat-history md renders role=topic and stage labels |
| `tests/message_pool/topic.txt` | New: default topic file (edit to change topic) |
| `tests/message_pool/infra_acceptance_test.py` | 3 new initialization assertions (33→36) |
| `tests/message_pool/README.md` | Startup flow (random seed / self-intro / topic), new flags, topic.txt notes |

## Verification

- `infra_acceptance_test.py`: all 36 assertions pass.
- `run_pool_experiment.py --agents 3 --rounds 2 --fake-llm --seed 42` smoke run passed:
  - The 3 agents got distinct random seeds (e.g. warmth 0.61 / 0.18 / 0.12) and
    `personality_seed` is correctly persisted (was empty before the fix).
  - `chat_history.jsonl` contains, in order: 3 self_intro entries + 1 topic entry
    (user_id=platform) + danmaku + agent broadcasts.
  - `_run_meta.json` records seed=42 and the topic; all 14 tables exported and md rendered.
