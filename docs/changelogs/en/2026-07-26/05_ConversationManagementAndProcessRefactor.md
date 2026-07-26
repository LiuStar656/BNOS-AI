# 05 — Conversation Management Optimization & Process Refactor

> Date: 2026-07-26 | Files touched: 6 | Type: UI Enhancement

---

## 1. Problem

Multiple conversation management UX issues: conversations couldn't be renamed, archived conversations didn't load correctly in the archive panel, chat bubbles didn't auto-scroll to bottom, and process cleanup relied on unreliable PowerShell scripts.

## 2. Root Cause

1. Rename UI interaction missing; no callback in right-click menu
2. Archive panel read `conversation_history.json` but didn't update UI state
3. No forced scroll-to-bottom after new messages
4. PowerShell process cleanup could miss child processes

## 3. Solution

### 3.1 Conversation Rename (chat_page.py)

Implemented rename callback in conversation list right-click menu.

### 3.2 Archive Panel (chat_page.py)

Fixed archive loading logic to properly update UI state on restore.

### 3.3 Bubble Auto-Scroll (chat_bubble.py)

```python
def _auto_scroll(self):
    scrollbar = self._scroll_area.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())
```

### 3.4 Process Termination (engine.py/process_killer.py)

Replaced PowerShell cleanup with native Python process management using `subprocess.Popen.kill()`.

## 4. Impact

- `gui/pages/chat_page.py`: Rename and archive logic
- `gui/widgets/chat_bubble.py`: Auto-scroll
- `bnos_runtime/engine.py`: Process termination
- `bnos_runtime/process_killer.py`: Native process cleanup
