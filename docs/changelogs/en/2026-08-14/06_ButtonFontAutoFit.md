# Global Button Font Auto-Fit

## Problem

Button text overflowed its widget: when the font got too large and the button did not
size-adapt, part of the text extended beyond the button UI. All GUI buttons had this issue.

## Root Cause

- Global QSS button `padding: 8px 16px` is fixed
- Pages used `setFixedWidth(56/64/72/76/90)` fixed widths
- When system fonts enlarge (DPI scaling / bigger theme font), the fixed width becomes
  smaller than text + padding, so text overflows the button boundary. Qt's sizeHint would
  normally compute the width from the font, but a fixed width takes that away

## Solution

- New `gui/core/utils/widget_utils.py::fit_button_width(btn, *, padding=36)`:
  `fontMetrics().horizontalAdvance(text) + padding` computes the minimum width,
  **sets only minimumWidth, not a fixed width** (keeps sizeHint auto-extension)
- Replaced all fixed-width text buttons across 6 pages:
  - `dsh_manage_page.py`: sessions (resume/copy/export/delete), tasks, tool switches,
    preset card buttons
  - `activity_page.py` (64→fit), `workflow_page.py` (64→fit), `tools_page.py` (72→fit)
  - `node_page.py` (60+26→fit), `proposals_page.py` (64/72/90→fit)

## Impact

- Global convention: text buttons never use `setFixedWidth`; use `fit_button_width()` instead
- Button text renders fully under font/theme scaling, no overflow

## Verification

- AST syntax check on 8 files; `fit_button_width` imports without circular dependencies
- Offscreen instantiation of each page without errors
