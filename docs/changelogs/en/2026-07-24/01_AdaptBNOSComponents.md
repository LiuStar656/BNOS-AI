# 01 Adapt Reusable UI Components from BNOS Reference Project

---

## Summary

- **Core Change**: Referenced the BNOS reference project at `referencees/BNOS---Bionic-Neural-Network-Visual-Orchestration-Platform-main`, copied its reusable UI infrastructure components to `gui/core/`, adapted them to the bright theme, and cleaned up BNOS-specific dependencies
- **Root Cause**: The BNOS reference project contains mature desktop UI infrastructure (dialog system, Toast notifications, thread pool, shortcut manager). Reusing them avoids reinventing the wheel while maintaining architectural consistency
- **Impact**: Added 3 modules with 9 files total; the GUI layer now has a complete infrastructure suite

---

## Details

### 1. Module Breakdown

| Module | Directory | Files | Responsibility |
|--------|-----------|-------|----------------|
| Utilities | `gui/core/utils/` | `dialog_utils.py` `file_utils.py` `log_viewer.py` | General UI utility functions |
| Toast | `gui/core/toast/` | `toast_notification.py` `toast_queue_manager.py` | Auto-dismissing notification popups |
| System | `gui/core/system/` | `thread_pool.py` `shortcut_manager.py` | Cross-component system services |

### 2. Adaptation Strategy

- **Theme conversion**: BNOS dark theme (`#1e1e1e` bg, `#cccccc` text) → bright theme (`#ffffff` bg, `#333333` text, `#1a73e8` accent)
- **Dependency cleanup**: Removed BNOS-specific imports (`ui.core.i18n`, `ui.core.logger`)
- **Feature trimming**: Removed BNOS-specific features (canvas dock positioning, node path resolution)
- **Shortcut reset**: Changed defaults from editor-scene to chat-scene (Ctrl+Enter send, Ctrl+N new chat)

### 3. Source Reference

| Our File | Reference Source |
|----------|-----------------|
| `gui/core/utils/dialog_utils.py` | `referencees/.../ui/core/utils/dialog_utils.py` |
| `gui/core/utils/file_utils.py` | `referencees/.../ui/core/utils/file_utils.py` |
| `gui/core/utils/log_viewer.py` | `referencees/.../ui/core/utils/log_viewer.py` |
| `gui/core/toast/toast_notification.py` | `referencees/.../ui/core/toast/toast_notification.py` |
| `gui/core/toast/toast_queue_manager.py` | `referencees/.../ui/core/toast/toast_queue_manager.py` |
| `gui/core/system/thread_pool.py` | `referencees/.../ui/core/system/thread_pool.py` |
| `gui/core/system/shortcut_manager.py` | `referencees/.../ui/core/system/shortcut_manager.py` |

---

## Verification

1. `from gui.core.utils.dialog_utils import ThemedDialogBase, themed_message, themed_input` — no import errors
2. `from gui.core.toast.toast_queue_manager import ToastQueueManager` — no import errors
3. `from gui.core.system.thread_pool import thread_pool` — no import errors
4. `from gui.core.system.shortcut_manager import ShortcutManager` — no import errors
