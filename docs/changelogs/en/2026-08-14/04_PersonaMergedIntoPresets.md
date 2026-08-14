# Persona Merged into Agent Presets (Goal/Persona Tab Removed)

## Problem

The GUI had a standalone 「目标/人格」(Goal/Persona) tab writing a global
`system-prompt.persona`. The user questioned: isn't persona AAA's responsibility?
Isn't creating Agent presets DeepSeek Harness's job?

## Root Cause

- **Persona belongs to the preset** is DSH's official semantics: `dsh-persona`
  (`@deepseek-ai/dsh-persona`) is a scope-only composable row, mountable only inside a
  preset's `agent.cordis.yml`; a global mount conflicts with the deployment persona
- The old tab's global `system-prompt.persona` silently overrode every task's persona,
  conflicting with "persona belongs to preset" and overlapping AAA's persona role — design error

## Solution

- Removed the `PersonaTab` class and the 「目标/人格」tab (10 tabs → 9)
- Persona editing moved into the Agent Presets edit dialog: `read_preset_persona` /
  `write_preset_persona` read/write the `id: persona` row in agent.cordis.yml;
  empty text = remove the row (that Agent inherits the deployment default persona)
- `_migrate_drop_global_persona()` idempotently cleans leftover `system-prompt` rows in
  extra.patch.yml (runs on first page open, prevents silent override)
- Preset cards show a persona summary (truncated to 80 chars)
- `!!js` platform expressions roundtrip intact via `_JsExpr`/`_PresetLoader`/`_PresetDumper`

## Impact

- GUI tabs 10 → 9; persona entry moved into the preset edit dialog
- Agents without the row (cleared) inherit the deployment default, matching DSH semantics

## Verification

- Offscreen instantiation: 9 tabs, no 「目标/人格」, PresetsTab has persona editor
- Persona roundtrip: write Chinese persona → first row `id: persona` → clear removes → restore
- `!!js` expressions write/read back intact; migration idempotent
