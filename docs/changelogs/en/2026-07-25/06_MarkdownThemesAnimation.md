# 06 — Markdown Rendering, Theme Optimization & Page Animation

> Date: 2026-07-25 | Files: 14 | Type: UI Upgrade

---

## I. Overview

Major GUI upgrades:

1. **Markdown Renderer**: mistune + Pygments with syntax highlighting
2. **Chat Bubble Refactor**: QTextBrowser for rich text display
3. **8 Theme Presets**: One-click theme switching
4. **Page Sliding Animation**: Smooth transitions
5. **Toast Notification System**: Independent popup component
6. **Config Persistence**: Theme selection saved to gui_config.json

---

## II. Core Implementation

### 2.1 Markdown Renderer

```python
class MarkdownRenderer:
    """mistune + Pygments Markdown renderer engine"""
    _markdown: mistune.HTMLRenderer | None = None
    _highlight: HighlightMixin | None = None
```

Rendering pipeline: `Markdown text → AST → HTML with code blocks → Pygments highlighted HTML → QTextBrowser.setHtml()`

### 2.2 Theme Presets

| Theme | Style | Primary Color |
|-------|-------|--------------|
| `ubuntu` | Ubuntu orange | #E95420 |
| `blue` | Classic blue | #1a73e8 |
| `green` | Fresh green | #2e7d32 |
| `purple` | Elegant purple | #7b1fa2 |
| `dark` | Dark mode | #333333 |
| `warm` | Warm tone | #bf360c |
| `ocean` | Ocean blue | #00695c |
| `gray` | Minimalist gray | #616161 |

---

**Last updated**: 2026-07-25
