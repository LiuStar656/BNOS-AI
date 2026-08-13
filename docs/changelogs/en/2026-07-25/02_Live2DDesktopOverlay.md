# 02 — Live2D Desktop Overlay Component

> Date: 2026-07-25 | Files: 11 | Type: New Feature

---

## I. Overview

New Live2D desktop overlay system, including:

1. **Live2DOverlay**: Frameless transparent window, supports drag, resize, Ctrl+wheel model scaling, mouse following
2. **Preview Management Page (live2d_page)**: Model list, server start/stop, Live2D Server config
3. **HTTP Server Integration**: Based on Node.js `express` + `live2d-viewer`

---

## II. Core Design

### 2.1 Live2DOverlay Desktop Overlay

```python
class Live2DOverlay(QWidget):
    """Live2D desktop overlay. Frameless, transparent, normal window level."""

    CONFIG_KEY = "live2d_overlay"
    SCALE_KEY = "live2d_model_scale"
    SERVER_PORT = 3000
    RESIZE_MARGIN = 12
```

**Key Features:**

| Feature | Implementation |
|---------|---------------|
| Frameless transparent | `FramelessWindowHint` + `WA_TranslucentBackground` + `setAutoFillBackground(False)` |
| Window drag | `mousePressEvent` / `mouseMoveEvent` move window |
| Bottom-right resize | `_in_resize_area()`, `SizeFDiagCursor` |
| Ctrl+wheel scaling | Calculate in Python, send absolute value via `runJavaScript` |
| Mouse following | Throttled (~30fps) `setMouseFocus(x, y)` to JS |
| Right-click menu | `contextMenuEvent` with "Close" option |
| Geometry persistence | `_save_geometry()` / `_restore_geometry()` in `AppConfig` |

### 2.2 Preview Page

New features in `live2d_page.py`:

- **Model List**: List all `.model3.json` files under `live2d-models/`
- **Server Control**: Start/Stop Live2D HTTP Server (subprocess management)
- **Port Config**: Custom server port
- **Startup Timeout**: Fallback to local static file serving on failure
- **Scale Setting**: Slider to adjust model scale

---

## III. Modified Files

| File | Changes |
|------|---------|
| `gui/widgets/live2d_overlay.py` | New: Desktop overlay component (233 lines) |
| `gui/pages/live2d_page.py` | Major expansion: model management, server control (+445 lines) |
| `gui/main_window.py` | Live2DOverlay show/hide integration |
| `gui/core/config.py` | New Live2D config keys |
| `gui_config.json` | New config items |
| `bnos_status.json` | New node status |
| `.gitignore` | New ignore rules for `live2d-models/`, `.live2d-server/` |

---

**Last updated**: 2026-07-25
