# Inter-Agent Multi-Round Dialogue & Topic Round Control (Platform Topic End)

## Problem

The platform message flow was one-way ("user danmaku → agent reply"); an agent's
broadcast never re-entered the pool, so agents could not hold a continuous dialogue
with each other on a topic. There was also no way to limit how many rounds a topic
conversation lasted, nor to actively end the current topic.

## Root Cause

- `step()` / `drain_queue()` broadcast a speech only into chat history, not back into
  the pool — other agents never saw each other's utterances in the next round.
- The platform had no "round limit / topic end" mechanism; the main loop could only
  be driven by user-danmaku batches.

## Solution

### 1. Platform multi-round dialogue & topic end `platform_runner.py`

- New state: `topic_rounds` (default 10, 0 = unlimited), `topic_active`,
  `topic_ended`, `agent_speech_count`.
- `_feed_agent_speech(agent_id, content)`: **re-enqueues** the broadcast speech into the
  pool (source=agent, user_id=agent_id, `dedup=False`) so other agents perceive it next
  round — this forms inter-agent multi-round dialogue; every successfully enqueued
  utterance counts as 1 round, and reaching `topic_rounds` triggers `_end_topic`.
- `_end_topic()`: the platform **actively announces the topic has ended** — enqueues a
  role=system announcement into the pool + chat history (with the total round count),
  publishes a `topic_ended` event; afterwards speeches are no longer re-enqueued/counted
  and agents may answer the announcement one last time before the conversation stops.
- `step()` and `drain_queue()` call `_feed_agent_speech` after broadcasting.

**Round semantics**: only "successfully enqueued agent speeches" count; dedup-dropped
messages, silent decisions, and an agent's background thinking/summaries (which never
touch the pool) are excluded.

### 2. Pool dedup toggle `message_pool.py`

- `enqueue_input(..., dedup=True)`: agent re-enqueue passes `dedup=False` — every agent
  utterance is a real dialogue round and must not be killed by same-user-same-text
  dedup (60s window), which exists to throttle user danmaku.

### 3. Chat history rendering `data_export.py`

- `render_chat_history_md` now renders `role=system` (platform topic-end announcement).

### 4. Launch script `run_pool_experiment.py`

- New `--topic-rounds N` flag (default 10, 0 = unlimited).
- Main loop reworked to be **session-driven**: agent re-enqueue sustains the dialogue;
  user danmaku only acts as an opener/refresher when the pool is empty; on reaching
  `--topic-rounds` the platform announces the topic end and stops injecting.
- `_run_meta.json` records `topic_rounds`; the run prints the total round count and
  ending state.

### 5. Acceptance test `infra_acceptance_test.py`

- New I3 "topic rounds": 3 assertions — agent speech re-enqueued into the pool
  (source=agent), `topic_ended` after N rounds, and the topic-end announcement written
  to chat history (role=system) (36 → 39).

## Affected Files

| File | Change |
|------|--------|
| `tests/message_pool/platform_runner.py` | `topic_rounds` control, speech re-enqueue (`_feed_agent_speech`), platform topic end (`_end_topic`) |
| `tests/message_pool/message_pool.py` | `enqueue_input` `dedup` parameter |
| `tests/message_pool/data_export.py` | md renders role=system |
| `tests/message_pool/run_pool_experiment.py` | `--topic-rounds` flag, session-driven main loop |
| `tests/message_pool/infra_acceptance_test.py` | New I3 assertions (36→39) |
| `tests/message_pool/README.md` | Multi-round flow, --topic-rounds flag |

## Verification

- `infra_acceptance_test.py`: all 39 assertions pass.
- Smoke `--agents 2 --rounds 3 --topic-rounds 3 --fake-llm`: platform announced
  "current topic ended (3 agent-speech rounds)" after 3 rounds.
- **Real test `--agents 2 --rounds 20 --topic-rounds 10 --gid test10`**: two agents
  held a natural 10-round conversation on "聊聊最近的生活" (puzzle/blank-space/map
  metaphors evolving continuously, with each agent picking up the other's points —
  confirming the re-enqueue mechanism); after round 10 the platform announced the
  topic end (role=system in `chat_history.md`); the agent answered once more and the
  conversation stopped; all 14 tables / chat history / events / decisions / evolution
  were archived.
