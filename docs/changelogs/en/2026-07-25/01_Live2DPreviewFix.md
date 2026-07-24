# 01 — Live2D Preview Page Bug Fixes

> Date: 2026-07-25 | Files Affected: 2 | Type: Bug Fix

---

## 1. Bug 1: `AttributeError: 'builtin_function_or_method' object has no attribute 'connect'`

### Problem

GUI crashes on startup:

```
File "gui/pages/live2d_page.py", line 181, in __init__
  self._web_view.page().javaScriptConsoleMessage.connect(self._on_js_console)
AttributeError: 'builtin_function_or_method' object has no attribute 'connect'
```

### Root Cause

`javaScriptConsoleMessage` is a **virtual method** on `QWebEnginePage`, not a Qt Signal. PySide6 does not allow calling `.connect()` on virtual methods. This method is a callback that QWebEnginePage invokes automatically when JS console output occurs; it must be overridden in a subclass, not connected as a signal.

### Fix

1. The `_Live2DWebPage(QWebEnginePage)` subclass was already defined at the top of the file but never used
2. Instantiate `_Live2DWebPage` and replace the default page via `self._web_view.setPage()`
3. Connect the custom `page_console` Signal to the handler

**Code diff:**

```python
# ❌ Before — calling .connect() on a virtual method
self._web_view = QWebEngineView()
# ... settings ...
self._web_view.page().javaScriptConsoleMessage.connect(self._on_js_console)

# ✅ After — using custom WebPage subclass with a Signal
self._web_view = QWebEngineView()
self._web_page = _Live2DWebPage()
self._web_view.setPage(self._web_page)
self._web_page.page_console.connect(self._on_js_console)
# ... settings ...
```

### `_Live2DWebPage` Class Design

```python
class _Live2DWebPage(QWebEnginePage):
    """Custom WebPage forwarding JS console output to Python via Signal."""
    page_console = Signal(object, str, int, str)  # level, msg, line, src

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        try:
            self.page_console.emit(level, message, lineNumber, sourceID)
        except Exception:
            pass
        super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)
```

---

## 2. Bug 2: `ImportError: cannot import name 'QWebEnginePage'`

### Problem

```
from PySide6.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
ImportError: cannot import name 'QWebEnginePage' from 'PySide6.QtWebEngineWidgets'
```

### Root Cause

In PySide6, `QWebEnginePage` lives in `PySide6.QtWebEngineCore`, not in `PySide6.QtWebEngineWidgets`. `QtWebEngineWidgets` only contains `QWebEngineView`.

### Fix

```python
# ❌ Before
from PySide6.QtWebEngineWidgets import QWebEngineView, QWebEnginePage

# ✅ After
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
```

---

## 3. Bug 3: Live2D Preview Canvas at 0x0 Causes Invisible Model

### Problem

The model loads successfully but is invisible. Terminal output:

```
[JS-INFO] [Live2D] 模型加载成功: /2D/feiniu.model3.json
[JS-INFO] [Live2D] 画布尺寸: 0 x 0
```

Users had to right-click → Reload in the preview page to see the model.

### Root Cause

The Live2D preview `QWebEngineView` lives inside a `QStackedWidget`. The chat page is shown by default, so the Live2D page starts hidden. Hidden widgets have zero dimensions, causing `window.innerWidth` and `window.innerHeight` to both be 0 when `initRenderer()` runs. PIXI creates a 0x0 WebGL context that cannot recover through mere resize.

### Fix

Strategy: **"Preload in background + reload when first shown"**

1. **Background preload**: Keep the 1.5s timer navigation in `__init__` (also gives the server time to start)
2. **`showEvent` override**: When first switching to the Live2D tab, call `web_view.reload()` to re-run everything with proper dimensions
3. **After reload**: `initRenderer()` runs with correct WebView dimensions; the canvas is properly sized

```python
# In __init__
QTimer.singleShot(1500, self._load_preview)  # background preload

def showEvent(self, event):
    """Reload the page when first shown (fixes 0x0 canvas from hidden init)."""
    super().showEvent(event)
    if self._preview_loaded and not self._page_shown:
        self._page_shown = True
        print("[Live2D] Page first visible, reloading renderer...")
        QTimer.singleShot(100, lambda: self._web_view.reload())
```

Also added `resizeRenderer()` in `renderer.js` as a fallback:

```javascript
function resizeRenderer() {
    if (!app) return;
    const W = window.innerWidth;
    const H = window.innerHeight;
    if (W === 0 || H === 0) return;
    app.renderer.resize(W, H);
    updateModelTransform();
    console.log('[Live2D] Renderer resized:', W, 'x', H);
}
```

### Alternatives Considered (Rejected)

- **Deferred navigation**: Navigate only in `showEvent` → user waits when first switching tabs, poor UX
- **`resizeRenderer()` only**: PIXI cannot recover a WebGL context initialized at 0x0 through resize; reload is required

---

## 4. Verification

1. Start the program; GUI must not crash
2. Switch to the Live2D tab; the model must display correctly (non-zero canvas)
3. Switch models in the list; preview must update correctly
4. Right-click → Reload; model must still display correctly
5. Switch to another tab and back; model must remain visible

---

## 5. File List

| File | Changes |
|------|---------|
| `gui/pages/live2d_page.py` | Fixed `AttributeError` (switched to `_Live2DWebPage` subclass + Signal), fixed `ImportError` (`QWebEnginePage` from `QtWebEngineCore`), added `showEvent` reload logic |
| `gui/live2d/renderer.js` | Added `resizeRenderer()` function |

## 6. Change Statistics

| Type | Count |
|------|:-----:|
| Modified files | 2 |
| **Total** | **2** |

---

**Last updated**: 2026-07-25
