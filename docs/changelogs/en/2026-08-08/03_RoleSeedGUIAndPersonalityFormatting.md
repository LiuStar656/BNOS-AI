# Role Seed System Phase 3 GUI & Phase 4 Personality Formatting

## Problem

Phases 0–2 of the role seed system (engine: personality vector table, dynamic mood values, seed background writing) were done. This change completes Phase 3 (GUI integration) and Phase 4 (personality formatting) and fixes three legacy issues:

1. Personality formatting wrote seed backgrounds into `long_term_memory`, but that table stores dialogue QAs — seed backgrounds should be written into `event_summary`.
2. Formatting did not clear the database; "clear database" and "personality formatting" were two separate overlapping features that should be merged.
3. The seed slider dimension names used a single half-width colon, inconsistent with other panels.

## Root Cause

- `write_seed_background` wrote to `long_term_memory` (QA semantics), so backgrounds were later retrieved by the graph/MemOS as dialogue QA — a semantic mismatch.
- The `format` command only reset some tables, not `fixed_cognition`, `personality_seed`, or the GUI conversation-history JSON; a separate `clear` command duplicated the logic.
- Slider labels hardcoded a half-width colon, inconsistent with the rest of the UI.

## Solution

### AAA Node Side (nodes/node_python_aaa_cognition/)

1. **`db.py`**: `write_seed_background` now writes to `event_summary` with `source='seed'`, idempotent per `identity_key` (prevents duplicate accumulation after formatting); `ensure()` adds v5.2 idempotent migration `ALTER TABLE event_summary ADD COLUMN source`.
2. **`main.py`**: removed the `clear` command; `format` now clears ALL user tables (incl. `fixed_cognition`) → `reset_personality_seed` → new `_clear_conversation_history` wipes the GUI conversation-history JSON (design §10.5).

### GUI Side

3. **`settings_panel.py`**: removed the "clear database" button, keeping only "人格格式化（清空并重来）" with a confirmation dialog describing full wipe + personality reset; seed slider labels changed to full-width colons.
4. **`personality_dialog.py`**: slider labels changed to full-width colons (consistent with the settings panel).

## Impact

| File | Change |
|------|--------|
| `nodes/node_python_aaa_cognition/db.py` | `write_seed_background` target changed from long_term_memory to event_summary (source='seed'); v5.2 migration adds event_summary.source |
| `nodes/node_python_aaa_cognition/main.py` | `clear` removed; `format` wipes all tables + resets personality + clears conversation-history JSON; new `_clear_conversation_history` |
| `gui/pages/settings_panel.py` | "clear database" removed, merged into "personality formatting"; seed slider full-width colons |
| `gui/dialogs/personality_dialog.py` | Slider labels use full-width colons |

## Verification

- All three files compile cleanly (no diagnostics).
- Settings panel shows only the "personality formatting" button; running it wipes all tables, resets personality to default, and clears chat history.
- Seed backgrounds land in `event_summary` with `source='seed'`; repeated formatting does not duplicate (idempotent).
