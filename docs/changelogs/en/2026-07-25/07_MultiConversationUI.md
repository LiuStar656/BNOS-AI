# 07 — Multi-Conversation Chat UI Optimization

> Date: 2026-07-25 | Files: 22 | Type: UI Optimization

---

## I. Overview

Final integration commit for 2026-07-25, covering:

1. **Multi-Conversation Management**: Create/switch/rename/archive conversations
2. **Chat Bubble Markdown**: Native Markdown with adaptive width
3. **Sidebar Redesign**: Popup menu layout
4. **Input Redesign**: Rounded container with attachment support
5. **Archive Panel**: Restore deleted conversations
6. **Node Management**: Process detection & cleanup
7. **Chat History Persistence**: Auto-save & load
8. **FloatingPanel Transparency**: Theme-following translucency
9. **Engine Start/Stop Fix**: PowerShell process management

---

## II. Core Changes

### 2.1 Conversation Management

```python
class ConversationList(QWidget):
    conversationSelected = Signal(str)  # conversation_id
    addConversation = Signal()
    deleteConversation = Signal(str)
```

Features:
- **New conversation**: "+" button in sidebar
- **Switch**: Click list item, instant content switching
- **Rename**: Right-click → enter new title
- **Delete**: Right-click → move to archive (DB intact)
- **Auto-title**: Generated from first message content

### 2.2 Archive Panel

```python
class ArchivePanel(FloatingPanel):
    """Archived conversation management panel"""
    # Restore conversation / Permanently delete
```

### 2.3 Engine Process Management Fix

```python
def _stop_engine(self, node_name):
    """Use PowerShell to force-kill engine processes"""
    ps_command = f'''
    Get-Process | Where-Object {{
        $_.ProcessName -like "*node_python*" -or
        $_.CommandLine -like "*{node_name}*"
    }} | Stop-Process -Force
    '''
```

Fixes WMIC process detection inaccuracies on some systems.

---

## III. Known Bugs Fixed

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| History lost on restart | In-memory only | JSON persistence |
| Node manager flickering | Rebuild on every notification | Data cache comparison |
| Engine won't restart | WMIC inaccurate process detection | PowerShell matching |
| FloatingPanel not transparent | Parent window transparency conflict | Remove parent association |

---

## IV. Modified Files

| File | Changes |
|------|---------|
| `gui/widgets/conversation_list.py` | New: Conversation list (367 lines) |
| `gui/pages/chat_page.py` | Multi-conversation + history persistence (+259 lines) |
| `gui/main_window.py` | Frameless + FloatingPanel integration (+195 lines) |
| `gui/widgets/chat_bubble.py` | Markdown rendering optimization (+174 lines) |
| `gui/pages/settings_panel.py` | Renamed + refactored (+142 lines) |
| `gui/dialogs/archive_panel.py` | New: Archive panel (154 lines) |
| `gui/core/state.py` | Multi-conversation state (+111 lines) |

---

**Last updated**: 2026-07-25
