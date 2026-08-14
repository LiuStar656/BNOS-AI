# DSH Settings/Control Components into GUI (DSH Manage Page)

## Problem

All DSH (DeepSeek Harness) settings and operations — model config, sessions, tasks,
plugins, tools, workspace, agent presets — could only be done inside DSH (CLI/web).
The user asked: **not** an embedded DSH web panel, but native BNOS GUI forms for
everything that needs to be set/modified/controlled, without entering DSH.

## Root Cause

- The old 「DSH 配置」page only covered model config; the control surface was too narrow
  (user: "DSH control doesn't cover all function controls, it's empty")
- The startup splash was missing the node_dsh node (user: "no dsh node startup in flash")

## Solution

「DSH 管理」page (`gui/pages/dsh_manage_page.py`, `page.dsh_manage`) with **9 tabs**:

| Tab | Content |
|---|---|
| Model config | provider baseURL / default model / model list / max tokens (headless+web dual-patch sync) |
| Sessions | dsh_home/sessions list (resume/copy id/export zip/delete/clean) |
| Tasks | submit task (sync wait)/cancel task/recent result |
| Tool switches | merged `tool-*` list from base/headless bundles (18), enable/disable per row |
| Plugins | `dsh plugin add/remove` wrapper (sub-thread, no freeze) + installed plugin list |
| Workspace | `nodes/shared/dsh_workspace` file browse/create/rename/delete (path-safe) |
| Runtime params | extra.patch.yml editor (YAML validation + atomic write) |
| General/security | sandbox permission mode + session telemetry + default temperature |
| Agent presets | default preset + copy-create custom Agent + persona + agent.cordis.yml/preset.yml editor + delete |

Supporting chain: runtime.json `preset`/`temperature` → node_dsh main.py injects
`DSH_PRESET`/`DSH_TEMPERATURE` → headless roster mount + `agent/request` merge;
extra.patch.yml loaded via `--patch` (`_patch_has_entries()` skips empty patches).

## Impact

- `pipeline.json` adds `node_dsh`; splash shows 「DSH 执行」
- Session 「resume」 auto-fills the task page session_id; workspace files are task-referencable

## Verification

- Offscreen instantiation of 9 tabs; `!!js` platform-expression roundtrip
- dump-config: sandbox/telemetry/persona overridden by extra.patch
- Real task end-to-end: temperature injection, persona in system, preset recorded in header
