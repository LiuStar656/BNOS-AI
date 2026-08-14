# 09 Data-Driven UI Layout Hot-Switching (Sidebar ↔ Top Nav + Revert)

## Background

The GUI already supports AI-authored, proposal-approved, revertible **theming** (colors/sizes), but the **navigation layout** was still hard-coded in `main_window._init_central`: a fixed vertical sidebar that could not be configured, switched, or reverted. User request: switch "sidebar" to "top nav" without restart, and be able to revert. This log records the full data-driven layout implementation.

## Contents

- **Layout schema**: new `gui/core/layout_spec.py` — LayoutSpec dataclass (id/name/nav_position/nav_width/nav_height/nav_mode/nav_visible/pages/window_default) + validator (enum check, numeric bounds, page-reference existence, duplicate-page detection; rejects invalid values instead of silently clamping)
- **Layout registry**: new `gui/core/layout_registry.py` — built-in `default` registered in code (not on disk) + scans `gui/resources/layouts/`; `install` with safe-id check (same as SkinRegistry); built-ins win on name collision
- **Layout engine**: new `gui/core/layout_engine.py` — `apply(spec, window)`: remove old nav → build nav per spec (SidebarNav/TopNav) → rewire signals → preserve current page → persist layout_id → publish LAYOUT_CHANGED; `bind()` for window-less entry points (proposal approval)
- **Nav view abstraction**: `gui/widgets/sidebar.py` refactored — extracted `NavView` interface (page_changed/settings_clicked/node_clicked/set_active/refresh_theme); old Sidebar → `SidebarNav` (vertical, behavior unchanged); new `gui/widgets/top_nav.py` — TopNav horizontal nav (icon/text/icon_text modes)
- **MainWindow data-driven**: `_init_central` now reads layout_id from config and assembles the nav via LayoutEngine; subscribes to `LAYOUT_REQUEST` as the unified entry; slide-animation direction follows the active layout's page order
- **Proposal governance**: `proposal_store.py` supports kind="layout" (approve: snapshot prior layout_id → install → apply; revert restores the prior layout); proposal page badge mapping adds "布局"
- **AI tool loop**: `tool_registry.py` adds `ui.list_layouts` (layout list + active state) and `ui.apply_layout` (reference an installed layout by name, or define a new one via spec JSON; both generate pending proposals); gui_tool_schemas.json auto-refreshed on tool_bridge start (tools 25→27)
- **Sample layout pack**: `gui/resources/layouts/top-nav/layout.json` — top navigation (nav_position=top)
- **Persistence**: `config.py` adds a `layout_id` default; the last layout is restored on restart

## Verification

- Offscreen automated checks, 9 assertion groups passed: registry scan / validator rejects invalid / default left sidebar / top↔default switching (page instances reused, current page preserved) / invalid spec rejected / proposal approve→revert loop / LAYOUT_REQUEST message path / tool registration count
- Real-machine visual regression (8 presets + run.bat launch) pending user confirmation

## Usage

1. User tells AI "move the nav to the top" → AAA emits `ui.apply_layout(name="top-nav")`
2. A "layout" proposal card appears → approve → top nav applies instantly (no restart, page state preserved)
3. Not satisfied → revert from the proposal page → sidebar restored; restart keeps the last layout
