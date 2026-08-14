# AI-Authored Presets & Skinning Closed Loop (Tool Expansion)

## Problem

Two capability requests from the user:
1. DeepSeek Harness can create new presets through AI interaction — BNOS GUI should
   also let you "tell the AI the requirements → create an Agent preset"
2. Can the tab-page UI be dynamically adjusted by telling the AI requirements
   (new style, different colors/sizes/background), like DSH?

## Root Cause

- DSH's README explicitly says user presets can be "authored by a person **or by an
  agent**", and the only creation path is `copy()` (no CLI command) — ideal for wrapping
  as AI tools
- The skinning chain was already complete (skin_registry.install → apply_skin →
  THEME_CHANGED → apply_global instant redraw + revertible proposals), but the AAA-side
  tool injection note only covered "UI/theme changes", not preset management

## Solution

- **AI-authored presets**: `gui/core/tool_registry.py` adds 7 `dsh.preset_*` tools:
  - `dsh.preset_list` (list + persona text + current default)
  - `dsh.preset_copy` (copy-create; DSH's only creation path)
  - `dsh.preset_read` (metadata/persona, or agent.cordis.yml/preset.yml content)
  - `dsh.preset_write` (write custom preset file, composition-validated)
  - `dsh.preset_persona` (read/write persona; empty string = remove)
  - `dsh.preset_remove` / `dsh.preset_set_default`
  - handlers lazy-import the pages layer to avoid circular imports
- **Skinning loop**: `nodes/node_python_aaa_cognition/gui_tools.py::tool_list_text()`
  injection note broadened from "only for UI/theme changes" to
  "UI/theme/skin, DSH tasks, Agent preset management, page navigation all callable"

## Impact

- ToolRegistry now has 25 tools (15 ui.* + 3 dsh.run_* + 7 dsh.preset_*)
- Users can tell the AI "create an Agent named xx with persona…, disable bash tool"
  and it completes; effective on the next headless task
- Layout restructuring (e.g. side tabs → top tabs) is outside skinning scope;
  it is a data-driven UI rework (a larger project)

## Verification

- `dsh.preset_list` / `preset_persona` write+read / `preset_read` / `preset_set_default`
  (incl. restore built-in) / `preset_remove` all ok, data consistent
- Skinning chain: create_skin_proposal → approve → instant redraw → revert restore
