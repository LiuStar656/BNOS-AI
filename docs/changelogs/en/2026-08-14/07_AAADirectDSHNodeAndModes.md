# 07 AAA Direct-to-DSH Node Channel & Daily/Work Modes

## Problem

1. **AAA→DSH detoured through the GUI**: node_dsh is already a standard BNOS node
   (listener polls `nodes/shared/dsh_task_in.json` → executes → writes `output.json`),
   but the old path was AAA → gui_tools.call_tool → GUI ToolBridge (file channel,
   **requires GUI online**) → ToolRegistry `dsh.run_task` → writing the same file.
   One extra hop + a GUI dependency.
2. **DSH results never flow back**: `dsh.run_task` submits async; AAA replies
   "submitted" and moves on without relaying the final answer.
3. **Every request goes through LLM judgment**: no daily/work mode distinction;
   each turn assembles the full context and asks the LLM "reply or call a tool",
   wasting judgment cost on work-type requests that obviously need DSH.

## Solution

### Phase 0: Node-channel client (`dsh_client.py`, GUI-free)

- New `nodes/node_python_aaa_cognition/dsh_client.py`:
  - `submit_task()` writes `dsh_task_in.json` (atomic replace, unique `task_id`,
    optional `session_id` resume, `context` payload)
  - `read_result()` reads `node_dsh/output.json` matched by `task_id`
  - `wait_result()` synchronous wait (for background threads); `push_reply()`
    writes `gui_reply.json` directly
  - `node_ready()` checks node_dsh config existence

### Phase 1: AAA tool dispatch rework + async receipt

- `main.py` ③ tool-call branch: names starting with `dsh.` → `dsh_client.submit_task`
  direct to the node (no GUI) → reply "submitted" immediately → background daemon
  thread polls `wait_result(task_id)` → on completion `push_reply()` pushes the final
  answer (reusing the original `request_id` so the GUI's stale-reply filter lets it through)
- AAA records the returned `session_id` (`_dsh_session_id`) for multi-turn resume
- `node_dsh/main.py`: new `context` field support (background context prepended to the task)

### Phase 2: Daily/Work modes (manual + automatic switch)

- New `mode_manager.py`: `nodes/shared/mode.json` mode state (atomic read/write);
  `try_switch()` keyword substring detection (longest keyword wins, e.g.
  "退出工作模式" beats "工作模式")
- Switch keywords live in the AAA `node_config.json` `mode_keywords` section
  (defaults: work = 进入工作模式/开始工作模式/…, daily = 进入日常模式/退出工作模式/…)
- GUI chat-page top bar 「日常/工作」toggle button (chat_page.py): atomically writes
  mode.json; button state syncs every second (stays consistent after AAA keyword switches)
- GUI settings panel 「模式切换关键词」group (settings_panel.py): edits the same
  node_config.json
- AAA `_on_text`:
  - NLP keyword detection first; hit → switch mode + immediate reply (no DB write, no LLM)
  - In work mode → `_direct_dsh_to_node()`: sends the full AAA context
    (`_gather_context` output: self/fixed cognition, recent feelings, history summary,
    user info; list fields joined into strings) straight to DSH, replies "submitted",
    background polling pushes the result on completion
  - Daily mode → unchanged existing path (LLM judgment)

### Phase 3: Remove dsh.* from the GUI tool bridge + workflow adaptation

- `tool_registry.py`: removed `dsh.run_task` / `dsh.run_task_sync` / `dsh.check_task`
  (AI tool list 25 → 22; `dsh.preset_*` kept as GUI management capability)
- `workflow_store.py`: `run()` routes `dsh.*` execution-class steps to the new
  `_run_dsh_direct()` (node-channel direct, task_id polling, sync-wait semantics kept)
- `tool_bridge.py`: `_HEAVY_TOOLS` emptied (dsh execution migrated; mechanism kept)
- `nodes/shared/gui_tool_schemas.json`: capability list refreshed to 22 tools

## Key Paths

```
Work mode pass-through (skips LLM judgment):
user input → AAA._on_text
  ├─ keyword switch hit? → switch + reply (no task)
  ├─ mode==work →
  │    build full ctx → submit_task(task=input, context=ctx)
  │    → reply "submitted" → background poll output.json (task_id match)
  │    → done → push_reply final answer (GUI displays)
  └─ mode==daily → existing path (LLM judgment)

DSH tool call (after LLM judgment):
LLM emits dsh.* tool → submit_task (direct to node) → async receipt (as above)
```

## Verification

- Full py_compile passes (AAA + GUI)
- mode_manager smoke: switch to work / back to daily / no false trigger on plain input
- GUI offscreen: chat_page mode button & settings_panel keyword group instantiate clean
- tool_registry: 22 tools (execution organs removed, presets kept)
- workflow_store `_run_dsh_direct`: missing task field returns a proper error, no crash
