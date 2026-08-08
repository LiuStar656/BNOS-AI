# Yield Mechanism (Anti-Self-Talk) & Chatroom Terminology Unification

## Problem

A real 2-agent test showed a "single-agent dominance" issue: almost all speech came from
agent:0 while agent:1 spoke only occasionally — the conversation looked like agent:0
talking to itself, so multi-agent interaction balance was not achieved.

## Root Cause

- Without `@` mentions, `pick_speaker` returns the fixed order `[agent:0, agent:1]` and the
  arbiter is **first-come-first-served** — every batch had agent:0 decide and claim the
  floor first; agent:1 decided later and often chose `silent` under the context. The fixed
  order gave agent:0 a systematic speech advantage, with no rotation or yield mechanism.
- A latent bug surfaced too: `arbiter.release()` returned the **replacement** rather than the
  **released** speaker. After `step()` released at its end (promoting the queued speaker to
  current), `drain_queue()` found an empty queue and returned None — **QUEUE speeches were
  never broadcast / re-enqueued / counted (lost)**.

## Solution

### 1. Yield mechanism (platform_runner.py — no AAA changes)

- New `_last_speaker` / `_yield_pending`: if the last **agent broadcast** was from this
  agent, skip its decision this batch (do not answer itself), giving other agents a chance
  (i.e. "skip when the latest chat history entry is yourself").
- **`@` mentions are exempt** (explicit user intent wins).
- **Anti-stall**: when a batch yields nothing because everyone else stayed silent, the yield
  is released so the previous speaker may continue.
- External input (user messages / topic) does **not** reset `last_speaker` (other agents get
  the first chance to respond).
- `step()` and `drain_queue()` update `_last_speaker` after broadcasting.

### 2. Fix lost QUEUE speeches (arbiter.py)

- `release()` now returns the **released current speaker** (the queued replacement becomes
  the new current and is returned by the next `release()`), so every queued speech is
  released, broadcast, re-enqueued, and counted — nothing is lost.

### 3. Terminology: 弹幕 → 聊天室 (chatroom)

- 『弹幕』(danmaku) was only a concept borrowed from Lumi_Nox; this scenario is really a
  **chatroom** (people speak in time order, agents see the full chat log and join naturally).
  Unified wording across the plan doc, README, and code comments; code identifiers
  (`message_pool` / `enqueue_input` / `POOL_DANMAKU` ...) are kept unchanged.

## Affected Files

| File | Change |
|------|--------|
| `tests/message_pool/platform_runner.py` | Yield mechanism `_last_speaker`/`_yield_pending` (mention-exempt, anti-stall release) |
| `tests/message_pool/arbiter.py` | `release()` returns the released speaker; fixes lost QUEUE speeches |
| `tests/message_pool/infra_acceptance_test.py` | U4 adapted to new release semantics; I2 yield assertion; I4 yield fairness (both agents speak / no consecutive same-speaker); 42 checks |
| `tests/message_pool/README.md` etc. | 弹幕→chatroom wording; yield mechanism docs |

## Verification

- Acceptance test **42/42 pass** (new: previous speaker yields, no same-agent consecutive
  broadcast, both agents speak, queued replacement released correctly).
- **Real test `--agents 2 --rounds 20 --topic-rounds 10 --gid yield10`**: speech sequence
  `agent:0, agent:1, agent:0, agent:1, ...` **alternates 5:5** — no longer single-agent
  self-talk; agent:1's queued speech broadcasts correctly (direct evidence of the queue-loss
  fix); the dialogue truly picks up the other's points ("窗边的天光" ↔ "天光和云自己会走过来").
