# Workflow Steps Drive the DSH Executor

## Problem

workflow_store already had flow schemas + dual-engine scores (dopamine / use-it-or-lose-it),
but flow steps had no real execution capability — they could not hand tasks to an
external executor.

## Root Cause

- DSH (DeepSeek Harness) was already integrated as an execution organ (dsh.run_task
  tool); flow steps should reuse that execution chain instead of building their own
- A synchronous "submit DSH task and wait for the final answer" semantics was needed
  for flow steps

## Solution

- `gui/core/tool_registry.py` adds `dsh.run_task` (async submit) / `dsh.run_task_sync`
  (sync wait for the final answer, used by flow steps) / `dsh.check_task` (late results)
- `dsh.run_task_sync` supports `session_id` (resume same session for multi-turn) and
  `timeout` (default 600s, matching node_dsh); after timeout the task keeps running in
  the background and can be checked with `dsh.check_task`
- AAA side `gui_tools.py::workflows_text()` injects the flow list (with real-time
  dual-engine scores); main.py parses 【流程选择】to route into `ui.run_workflow`

## Impact

- Flow execution is now real; DSH task results flow back
- Users can let AAA pick and run a DSH task through conversation

## Verification

- `tool_registry.execute("dsh.run_task")` submit + `dsh.check_task` smoke
- Flow-selection chain: LLM outputs 【流程选择】→ main.py flow branch → ui.run_workflow
