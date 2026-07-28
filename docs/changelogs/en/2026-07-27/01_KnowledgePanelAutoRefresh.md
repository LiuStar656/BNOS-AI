# 01 — Knowledge Panel Auto-Refresh & Conversation Management Optimization

> Date: 2026-07-27 | Files touched: 6 | Type: Enhancement

---

## 1. Problem

1. **Knowledge panel data staleness**: When switching tabs to the knowledge page, data remained stale from the last 10-second timer load. Users had to wait up to 10 seconds for fresh data after switching pages.
2. **No cancel mechanism for in-flight sends**: When switching conversations mid-send, there was no way to cancel the outstanding send request, potentially causing stale replies to arrive in the wrong conversation.
3. **Chat bubble layout inconsistency**: Margins and size calculations in chat bubbles were not optimized, causing visual misalignment in some layouts.
4. **Conversation switching reply routing**: When switching conversations, the pending reply from the old conversation could still be routed to the new conversation's display, mixing messages across conversations.

## 2. Root Cause

1. `KnowledgePanel._load_data()` was only called during construction and on the 10-second timer; page-switch in `main_window.py` did not trigger a reload.
2. `MessageManager` had no `cancel_ongoing()` API — once a send was initiated, it could not be aborted programmatically.
3. `ChatBubble` layout used inconsistent margin calculations and redundant `QTimer` instances that accumulated over time.
4. `ChatPage._on_conversation_changed()` did not reset the `send_state` or clear the pending reply context before loading a new conversation.

## 3. Solution

### 3.1 Page-Switch Auto-Refresh (main_window.py)

Added a trigger in `_switch_page` for the knowledge page:

```python
# In _switch_page, after slide animation:
if page_id == "knowledge" and hasattr(target, "_load_data"):
    target._load_data()
```

This ensures the knowledge panel reloads data from the database every time the user switches to it via the sidebar, in addition to the existing 10-second timer. The same logic is duplicated in both code paths (immediate switch and animated switch) to handle both UI modes.

### 3.2 Manual Refresh Button (knowledge_panel.py)

A manual refresh button was already present in the bottom bar; it remained functional and was retained. The button calls `_load_data()` directly.

### 3.3 Cancel Ongoing Send (message_manager.py)

Added a new method to abort in-flight sends:

```python
def cancel_ongoing(self):
    """取消正在进行的发送（对话切换时调用，不再等待旧回复）"""
    self._cancel_timeout()
    self._current_request_id = ""
```

This stops the 60-second timeout timer and clears the `_current_request_id` so that any incoming reply with a stale ID gets filtered out by the existing `request_id` mismatch check.

### 3.4 Conversation Switching Resets (chat_page.py)

In `_on_conversation_changed()`, added:

```python
# Reset send state lock so the new conversation can send immediately
self._state.send_state = "idle"
if self._msg_mgr:
    self._msg_mgr.cancel_ongoing()
    self._msg_mgr.send_switch_conversation(conv_id)
```

This ensures the `sending` lock is released, any pending request is cancelled, and a switch-conversation message is sent to the backend.

### 3.5 Chat Bubble Optimization (chat_bubble.py)

- Fixed margin and size calculations to ensure consistent bubble widths and spacing.
- Removed redundant `QTimer` instances that were no longer needed after the layout refactor.

## 4. Impact

- `gui/widgets/knowledge_panel.py`: Auto-refresh on page switch + manual refresh button + 10s timer
- `gui/main_window.py`: Page-switch refresh trigger added
- `gui/core/message_manager.py`: New `cancel_ongoing()` method
- `gui/pages/chat_page.py`: Conversation switching: send state reset, pending reply routing
- `gui/widgets/chat_bubble.py`: Layout margin & size optimization, removed redundant timers
- `scripts/check_db_tables.py`: New DB table health check script

## 5. File Change List

| File | Lines Changed | Description |
|------|:------------:|-------------|
| `gui/widgets/knowledge_panel.py` | ~10 | 10s timer already existed; bottom-bar refresh button retained |
| `gui/main_window.py` | ~4 | Added `_load_data()` call on page switch |
| `gui/core/message_manager.py` | ~5 | New `cancel_ongoing()` method |
| `gui/pages/chat_page.py` | ~8 | Send state reset + `cancel_ongoing()` call on conversation switch |
| `gui/widgets/chat_bubble.py` | ~30 | Layout margin/size optimization, removed redundant QTimer calls |
| `scripts/check_db_tables.py` | ~50 | New DB table check script |
| `docs/design/[OK]-提示词模板分层拆分方案.md` | ~48 | New prompt template layering design doc |
