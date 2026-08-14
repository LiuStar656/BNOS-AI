# 2026-08-14 Changelog Overview

[Back to index](../README.md)

---

## Contents

- [01 GUI Pluggability & AI UI Control (7 Phases)](#01-gui-pluggability--ai-ui-control-7-phases)
- [02 DSH Settings/Control Components into GUI (DSH Manage Page)](#02-dsh-settingscontrol-components-into-gui-dsh-manage-page)
- [03 Workflow Steps Drive the DSH Executor](#03-workflow-steps-drive-the-dsh-executor)
- [04 Persona Merged into Agent Presets (Goal/Persona Tab Removed)](#04-persona-merged-into-agent-presets-goalpersona-tab-removed)
- [05 AI-Authored Presets & Skinning Closed Loop (Tool Expansion)](#05-ai-authored-presets--skinning-closed-loop-tool-expansion)
- [06 Global Button Font Auto-Fit](#06-global-button-font-auto-fit)
- [07 AAA Direct-to-DSH Node Channel & Daily/Work Modes](#07-aaa-direct-to-dsh-node-channel--dailywork-modes)
- [08 GUI Development Standards (Engineering + Styling + Config)](#08-gui-development-standards-engineering--styling--config)

---

## Summary

| # | Core Change | Root Cause | Impact |
|---|------------|------------|--------|
| 01 | 7-phase GUI pluggability & AI UI control: ThemeEngine (token→global QSS), IconRegistry, UiRegistry (page slots), message events, skin packages (AI-produced, installable), proposal cards (approve/revert governance), tool loop (ToolRegistry+ToolBridge) | Match DeepSeek Harness WebUI's "pluggable UI + AI-driven UI control": let the agent apply its output (skins/icons/pages/flows) to the UI with visible, approvable, revertible changes | All widget colors go through theme_engine tokens; AI controls GUI via 25 tools; destructive changes require proposal approval |
| 02 | DSH settings/control components as native BNOS GUI forms: 「DSH 管理」page, 9 tabs (model config/sessions/tasks/tool switches/plugins/workspace/runtime params/general-security/agent presets), no DSH entry needed | User asked to move all DSH settings & control into BNOS GUI instead of operating inside the DSH web panel | headless/web double-patch sync, extra.patch runtime effect, runtime.json injected via DSH_TEMPERATURE/DSH_PRESET |
| 03 | DSH as flow executor: workflow_store steps call `dsh.run_task` (DSH execution organ), flows submit DSH tasks and wait for the final answer | Flow steps needed real execution capability; DSH (DeepSeek Harness) is the already-integrated executor | Flow execution is real; results flow back; `dsh.check_task` for late results after timeout |
| 04 | Removed the standalone 「目标/人格」Tab; persona merged into Agent Presets (the `id: persona` row in agent.cordis.yml); added `_migrate_drop_global_persona()` to clean leftover global `system-prompt` rows | The old tab wrote global `system-prompt.persona`, conflicting with DSH's official "persona belongs to preset" semantics and overlapping AAA's persona responsibility | Persona editing lives in the preset edit dialog; empty text = inherit deployment default; `!!js` expressions roundtrip intact |
| 05 | ToolRegistry expanded to 25 tools: 7 new `dsh.preset_*` (list/copy/read/write/persona/remove/set_default) enabling AI-authored presets; `gui_tools.py` injection note broadened | DSH officially allows user presets "authored by a person or by an agent"; user wanted dialog-driven preset creation like DSH | Tell the AI "create an Agent named xx with persona…" to create/customize presets, effective next headless task |
| 06 | New `fit_button_width()` helper: fontMetrics width + padding, only sets minimumWidth (keeps sizeHint); replaced all `setFixedWidth` text buttons in 6 pages | Fixed QSS padding + fixed button widths → text overflows buttons when fonts enlarge | Buttons no longer overflow under DPI/theme font scaling; convention: no setFixedWidth for text buttons |
| 07 | AAA talks to the DSH node channel directly (dsh_client.py, no GUI tool bridge) + async receipt (background polling pushes results via gui_reply.json) + daily/work modes (manual GUI button & configurable keyword auto-switch; work mode skips LLM judgment and sends the full context straight to DSH); GUI tool bridge drops the dsh execution organs (25→22 tools), workflow steps go direct to the node | node_dsh is already a standard BNOS node; forwarding should use the node channel, not the GUI tool bridge (which requires the GUI online); DSH results never flowed back; every turn paid LLM judgment cost | Forwarding no longer depends on the GUI; DSH results are pushed automatically; work-mode input goes straight to DSH without LLM judgment; keywords editable in the settings panel; workflow dsh steps keep sync-wait semantics |
| 08 | New `docs/design/[OK]-GUI开发规范.md` (engineering: layout/module duties/page registration/message protocol/node channels; styling: token-first no raw hex/component rules/WeChat-style chat UI/skinning loop; config: gui_config.json/node configs/shared protocol files) + `gui/README.md` module index | After letting AI control the GUI directly (22 tools/presets/skinning), a spec telling AI *how* to change the GUI was missing — the counterpart to DSH's AGENTS.md+web-styling.md+config-catalog; GUI had no README and hard-coded colors were scattered | AI and developers now share one rule set for GUI changes (tokens/registration/messages/buttons/bubbles/atomic writes) with a review checklist; existing hard-coded colors logged as remediation items |

---

### 01 GUI Pluggability & AI UI Control (7 Phases)

See [01_GUIPluggabilityAndAIUIControl.md](./01_GUIPluggabilityAndAIUIControl.md).

### 02 DSH Settings/Control Components into GUI (DSH Manage Page)

See [02_DSHManagePage.md](./02_DSHManagePage.md).

### 03 Workflow Steps Drive the DSH Executor

See [03_WorkflowDrivesDSHExecutor.md](./03_WorkflowDrivesDSHExecutor.md).

### 04 Persona Merged into Agent Presets (Goal/Persona Tab Removed)

See [04_PersonaMergedIntoPresets.md](./04_PersonaMergedIntoPresets.md).

### 05 AI-Authored Presets & Skinning Closed Loop (Tool Expansion)

See [05_AIAuthoredPresetsAndSkinning.md](./05_AIAuthoredPresetsAndSkinning.md).

### 06 Global Button Font Auto-Fit

See [06_ButtonFontAutoFit.md](./06_ButtonFontAutoFit.md).

### 07 AAA Direct-to-DSH Node Channel & Daily/Work Modes

See [07_AAADirectDSHNodeAndModes.md](./07_AAADirectDSHNodeAndModes.md).

### 08 GUI Development Standards (Engineering + Styling + Config)

See [08_GUIDevStandards.md](./08_GUIDevStandards.md).

---

## Modified Files

### New Files

| File | Item |
|------|------|
| `gui/core/theme_engine.py` | #01 |
| `gui/core/icon_registry.py` | #01 |
| `gui/core/ui_registry.py` | #01 |
| `gui/core/messages.py` | #01 |
| `gui/core/skin_registry.py` | #01 |
| `gui/core/proposal_store.py` | #01 |
| `gui/core/tool_registry.py` | #01、#05、#07 |
| `gui/core/tool_bridge.py` | #01、#07 |
| `gui/core/workflow_store.py` | #01、#03、#07 |
| `gui/core/utils/widget_utils.py` | #06 |
| `gui/pages/activity_page.py` | #01 |
| `gui/pages/tools_page.py` | #01 |
| `gui/pages/proposals_page.py` | #01 |
| `gui/pages/workflow_page.py` | #01、#03 |
| `gui/pages/dsh_manage_page.py` | #02、#04、#05 |
| `nodes/node_python_aaa_cognition/dsh_client.py` | #07 |
| `nodes/node_python_aaa_cognition/mode_manager.py` | #07 |
| `docs/design/[PLAN]-GUI可插拔化与AI操控UI完整方案.md` | #01 |
| `docs/design/[PLAN]-DSH设置控制组件接入GUI方案（待决策）.md` | #02、#04、#05 |
| `docs/design/[PLAN]-workflow接入DSH执行器方案（待决策）.md` | #03 |
| `docs/design/[PLAN]-DeepSeekHarness接入方案.md` | #02、#03 |
| `docs/design/[PLAN]-DSH会话续接方案（待决策）.md` | #02 |
| `docs/design/[OK]-AAA直连DSH节点与模式切换方案.md` | #07 |
| `docs/design/[OK]-GUI开发规范.md` | #08 |
| `gui/README.md` | #08 |

### Major Modified Files

| File | Change | Item |
|------|--------|------|
| `gui/core/config.py` / `gui/resources/theme.py` | Preset/token color lookup through ThemeEngine; skin apply_skin | #01 |
| `gui/main_window.py` | Pages loaded via ui_registry slots; subscribes THEME_CHANGED for instant redraw | #01 |
| `gui/widgets/{sidebar,title_bar,toast,chat_input,color_picker,floating_panel,knowledge_panel,live2d_overlay,location_map_widget}.py`, `gui/pages/{chat_page,live2d_page,location_page,mcp_page,node_page,settings_panel}.py`, `gui/dialogs/{archive_panel,personality_dialog}.py`, `gui/core/utils/dialog_utils.py` | Hardcoded colors tokenized through theme_engine | #01 |
| `gui/pages/startup_splash.py` | `NODE_LABELS` adds `node_dsh` (「DSH 执行」) | #02 |
| `gui/core/ui_registry.py` | `page.dsh_config` → `page.dsh_manage` (title 「DSH 管理」) | #02 |
| `nodes/node_dsh/harness/packages/bundle/headless/cordis.patch.yml` | Adds `agent-presets` row (enables preset roster) | #02、#04 |
| `nodes/node_dsh/harness/packages/bundle/headless/src/index.ts` | `setup` async; mounts preset via `DSH_PRESET`; merges `DSH_TEMPERATURE` in `agent/request` | #02 |
| `nodes/node_python_aaa_cognition/gui_tools.py` | Tool-bridge client (load_schemas/call_tool/tool_list_text/workflows_text); injection note broadened | #01、#05 |
| `nodes/node_python_aaa_cognition/main.py` | Parses 【工具调用】【流程选择】sections → call_tool / flow branch; dsh.* direct to node_dsh + async receipt; `_on_text` mode NLP + work pass-through; `_dsh_session_id` resume | #01、#03、#07 |
| `nodes/node_python_aaa_cognition/node_config.json` | New `mode_keywords` section (default switch keywords) | #07 |
| `nodes/node_dsh/main.py` | Injects `DSH_TEMPERATURE`/`DSH_PRESET` env; loads `--patch extra.patch.yml` (skips empty patch); `context` field prepended to the task | #02、#03、#07 |
| `nodes/node_python_aaa_cognition/prompt.py` | `_gui_tools_section()` injects tool list + flow library | #01、#03 |
| `nodes/node_python_aaa_cognition/parser.py` | New tool-call / flow-selection section parsing | #01、#03 |
| `gui/core/tool_registry.py` | Removed dsh.run_task / run_task_sync / check_task (25→22 tools) | #07 |
| `gui/core/workflow_store.py` | `run()` routes dsh.* execution-class steps to `_run_dsh_direct` (sync-wait semantics kept) | #07 |
| `gui/core/tool_bridge.py` | `_HEAVY_TOOLS` emptied (dsh execution migrated to the node channel) | #07 |
| `gui/pages/chat_page.py` | Top-bar 「日常/工作」toggle button + 1s state sync | #07 |
| `gui/pages/settings_panel.py` | 「模式切换关键词」config group (edits AAA node_config.json) | #07 |
| `gui/pages/dsh_manage_page.py` | Comment sync (task path described as node_dsh node channel) | #07 |
| `nodes/shared/gui_tool_schemas.json` | Capability list refreshed to 22 tools | #07 |
| `pipeline.json` | Engine pipeline adds `node_dsh` node | #02 |

---

**Last updated**: 2026-08-14
