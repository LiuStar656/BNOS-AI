# GUI Pluggability & AI UI Control (7 Phases)

## Problem

The GUI's theme/icons/pages/skins/flows were hardcoded and static; AI (the AAA node)
could not produce and apply changes. To match DeepSeek Harness WebUI's "pluggable UI +
AI-driven UI control", the agent's output (skins, icons, pages, flows) must be applied
to the UI with visible, approvable, and revertible changes.

## Root Cause

- Colors scattered across 15+ widgets as hardcoded values; theming meant editing files
- Icons were raw glyphs with no runtime override
- Pages hard-registered without a slot mechanism
- No skin package / proposal / approval governance chain; AI changes could not apply safely

## Solution (7 Phases)

| Phase | Capability | Output |
|---|---|---|
| 1 | ThemeEngine: token→global QSS single generator | `gui/core/theme_engine.py`, all widgets tokenized |
| 2 | IconRegistry: semantic icons, runtime override | `gui/core/icon_registry.py` |
| 3 | UiRegistry: page slots (register to appear) | `gui/core/ui_registry.py` |
| 4 | Message events: cross-widget collaboration via messages | `gui/core/messages.py` |
| 5 | Skin packages: AI-produced, installed to disk | `gui/core/skin_registry.py` (install/scan/list/remove) |
| 6 | Proposal cards: pending→approve→revert | `gui/core/proposal_store.py` + `proposals_page.py` |
| 7 | Tool loop: AI writes request→GUI executes→returns result | `gui/core/tool_registry.py` + `tool_bridge.py` + `tools_page.py` |

AI call chain: AAA outputs 【工具调用】→ main.py parses → gui_tools.call_tool →
ToolBridge polling (`nodes/shared/gui_tool_requests/` → `gui_tool_responses/`) →
ToolRegistry handler → destructive changes become proposals, effective after approval.

## Impact

- All widget colors go through theme_engine tokens; 25 tools exposed to AI
- Skinning applies instantly (THEME_CHANGED → apply_global redraw), proposals revertible

## Verification

- Offscreen instantiation of 6 pages + theme_engine apply_global
- Tool-bridge smoke: write request file → poll → response
- Skinning chain: create_skin_proposal → approve → redraw → revert restore
