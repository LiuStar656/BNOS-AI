# Map as a Dedicated Sidebar Page

## Problem

The location map lived inside the settings floating panel — deep entry, small space, and mismatched with the "AI location info" standalone visualization. It needed to move to its own sidebar tab.

## Root Cause

- The settings panel is meant for configuration (theme, personality params, personality formatting); a runtime map view mixed in made it bloated.
- The sidebar already has a tab system (Knowledge / Settings); a dedicated map page fits the existing navigation and gives the map far more room.

## Solution

1. **`gui/pages/location_page.py` (new)**: `LocationPage`, a standalone map page holding the map view and location info.
2. **`gui/widgets/sidebar.py`**: added a "地图" (Map) tab.
3. **`gui/main_window.py`**: registered the location page; `_after_page_switch` lazy-loads it so the map components are not initialized at startup.
4. **`gui/pages/settings_panel.py`**: removed the map area, restoring the settings panel to pure configuration duties.

## Impact

| File | Change |
|------|--------|
| `gui/pages/location_page.py` (new) | Standalone map page LocationPage |
| `gui/widgets/sidebar.py` | New "Map" tab |
| `gui/main_window.py` | Registers location page; lazy load in `_after_page_switch` |
| `gui/pages/settings_panel.py` | Map area removed |

## Verification

- After GUI launch the sidebar shows a "Map" tab; clicking it switches to the standalone map page.
- Map components are not initialized before first switch (lazy load); settings panel has no map remnants.
