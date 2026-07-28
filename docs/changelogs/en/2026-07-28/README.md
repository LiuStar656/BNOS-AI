# 2026-07-28 Update Overview

[Back to Index](../README.md)

---

## Table of Contents

- [01 Chat Bubble Layout & Alignment Refactor](./01_ChatBubbleLayoutRefactor.md)

---

## Summary

| # | Core Change | Root Cause | Impact |
|---|------------|------------|--------|
| 01 | ChatBubble layout restructured: removed internal spacer, alignment moved to outer layout; switched to QFontMetrics-based pixel width measurement; fixed Live2D JS console encoding; updated knowledge_panel table labels and limited self_cognition/other_cognition to 1 entry | QTextDocument doc.size().width() reflects layout width not content width; spacer interference with alignment; missing encoding handling for JS console output | Accurate bubble sizing, correct user/AI alignment, clean JS console output, optimized knowledge panel queries |

---

## Changed Files

### New Files

| File | Topic |
|------|-------|
| `docs/design/[ANALYSIS]-awesome-llm-apps组件复用分析.md` | #01 |

### Major Changes

| File | Change | Topic |
|------|--------|-------|
| `gui/widgets/chat_bubble.py` | Removed internal spacer; QFontMetrics-based width calc; doc.setTextWidth for auto-wrap | #01 |
| `gui/pages/chat_page.py` | Set bubble alignment by role in `_append_bubble` | #01 |
| `gui/pages/live2d_page.py` | Fixed JS console output encoding with `errors="replace"` | #01 |
| `gui/widgets/knowledge_panel.py` | Added "diaries" table label; limited self_cognition/other_cognition to 1 entry | #01 |
| `docs/design/[ANALYSIS]-awesome-llm-apps组件复用分析.md` | New component reuse analysis doc (359 lines) | #01 |

---

## File Stats

| Metric | #01 |
|--------|:---:|
| Files touched | 7 |
| Lines added | ~434 |
| Lines removed | ~57 |
| **Net change** | **+377** |

---

**Last updated**: 2026-07-28
