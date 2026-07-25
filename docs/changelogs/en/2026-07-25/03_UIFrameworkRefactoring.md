# 03 — UI Framework Refactoring: FloatingPanel, TitleBar, Frameless Window

> Date: 2026-07-25 | Files: 14 | Type: Refactoring

---

## I. Overview

Major UI framework refactoring:

1. **FloatingPanel**: Unified container for all secondary windows (settings, node management, color picker, archive)
2. **TitleBar**: Custom title bar with light theme styling
3. **Frameless Window**: Hidden native borders, custom edge resize via `WM_NCHITTEST`
4. **ColorPickerPopup**: Refactored as FloatingPanel subclass
5. **Database Management**: Backup/restore/clear functionality
6. **Request ID Filtering**: Fix stale reply targeting

---

## II. Core Architecture

### 2.1 FloatingPanel

```python
class FloatingPanel(QDialog):
    """Floating panel base — frameless, translucent, scrollable content"""

    def __init__(self, parent=None, title="Floating Panel"):
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
```

**Structure:**

```
FloatingPanel (QDialog)
├── Outer transparent window
├── _container (QWidget) → translucent bg + rounded border
│   ├── Title bar (title + close button)
│   ├── Separator
│   └── QScrollArea
│       └── content (injected by set_content_widget)
```

### 2.2 TitleBar

```python
class TitleBar(QWidget):
    """Light theme custom title bar — for frameless main window"""
    minimizeClicked = Signal()
    maximizeClicked = Signal()
    closeClicked = Signal()
```

### 2.3 Frameless Window with Edge Resize

```python
self.setWindowFlags(Qt.FramelessWindowHint)
self.setAttribute(Qt.WA_TranslucentBackground)
self.setAutoFillBackground(False)

# nativeEvent for WM_NCHITTEST
def nativeEvent(self, eventType, message):
    if eventType == b"windows_generic_MSG":
        msg = ctypes.wintypes.MSG.from_address(int(message))
        if msg.message == 0x0084:  # WM_NCHITTEST
            # Calculate edge hit, return HTLEFT/HTRIGHT/HTTOP/HTBOTTOM
```

Edge margin: `_RESIZE_MARGIN = 8` pixels.

---

## III. Modified Files

| File | Changes |
|------|---------|
| `gui/widgets/floating_panel.py` | New: FloatingPanel base class (187 lines) |
| `gui/widgets/title_bar.py` | New: Custom title bar (191 lines) |
| `gui/main_window.py` | Frameless window + edge resize (+157 lines) |
| `gui/widgets/color_picker.py` | Refactored as FloatingPanel subclass (+36 lines) |
| `gui/pages/settings_page.py` | New DB management (+118 lines) |
| `gui/core/message_manager.py` | request_id filtering (+57 lines) |

---

**Last updated**: 2026-07-25
