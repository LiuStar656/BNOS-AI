# 01 — Chat Bubble Layout & Alignment Refactor

> Date: 2026-07-28 | Files touched: 7 | Type: Refactor

---

## 1. Problem

Multiple issues in the chat bubble component:

- **Trailing whitespace misalignment**: The internal QSpacerItem used for alignment caused uneven spacing between chat bubbles, especially when combined with the outer layout alignment logic
- **Inaccurate bubble width**: `QTextDocument.doc.size().width()` returns the document layout width (which may be larger than actual content), resulting in overly wide bubbles
- **Streaming width drift**: The previous "only-increase" width strategy (`_current_width`) prevented bubbles from shrinking when text was replaced, causing persistent oversized bubbles in some edge cases
- **Live2D JS console encoding**: Japanese/Chinese characters in JS console output produced garbled text in the Python terminal
- **Knowledge panel**: The `feelings` table label was misleading, the `diaries` table was missing from labels, and `self_cognition`/`other_cognition` queried too many rows

## 2. Root Cause

1. **Spacer inside ChatBubble**: `ChatBubble.__init__` added a `QSpacerItem` on the left (AI) or right (user) side of the text browser to achieve alignment. This interfered with the outer `QVBoxLayout` when trying to apply `setAlignment` at the page level, causing inconsistent spacing.

2. **`doc.size().width()` vs content width**: The previous code used `QTextDocument.size().width()` to determine bubble width. However, `QTextDocument.size()` reflects the document layout area (which can be inflated by `setTextWidth` or default margins), not the actual rendered text width line by line.

3. **Only-increase width strategy**: The `_current_width` member tracked the maximum width ever computed. During streaming, if a wide line appeared early and was later replaced with narrower content, the bubble would stay at the old wide width.

4. **Missing encoding handling**: `print(f"[JS-...] {msg}")` directly passed the message string; characters outside the console encoding caused automatic replacement with `?` characters.

5. **Static query limits**: `knowledge_panel.py` used a hardcoded `LIMIT 200` for all tables, including `self_cognition` and `other_cognition` which only ever have 1 meaningful row.

## 3. Solution

### 3.1 Layout & Alignment Decoupling (chat_bubble.py + chat_page.py)

The spacer was removed from `ChatBubble`, and alignment responsibility was moved to the outer `chat_page.py` layout:

```python
# Before (chat_bubble.py): internal spacer for alignment
if role == "user":
    layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))
    layout.addWidget(self._browser)
else:
    layout.addWidget(self._browser)
    layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))

# After: just the browser, alignment handled externally
layout.addWidget(self._browser)
```

```python
# Added in chat_page.py _append_bubble:
alignment = Qt.AlignmentFlag.AlignRight if role == "user" else Qt.AlignmentFlag.AlignLeft
self._msg_layout.setAlignment(bubble, alignment)
```

### 3.2 Width Measurement via QFontMetrics (chat_bubble.py)

Replaced `doc.size().width()` with per-line `QFontMetrics.horizontalAdvance()`:

```python
# Before: using doc.size().width()
height = int(doc.size().height()) + 28
width = int(doc.size().width()) + 36  # inaccurate

# After: QFontMetrics per-line measurement
fm = self._browser.fontMetrics()
max_line_w = 0
for line in self._text.split("\n"):
    w = fm.horizontalAdvance(line)
    if w > max_line_w:
        max_line_w = w
width = max_line_w + padding_h
width = min(width, self._max_width)  # cap at 600px
```

Also set `doc.setTextWidth(self._max_width)` so the document auto-wraps at the maximum bubble width:

```python
doc.setTextWidth(self._max_width)
```

### 3.3 _on_doc_resized Fix (chat_bubble.py)

Previously `_on_doc_resized` only updated height and preserved the existing width. Now it updates both height and width on every document size change:

```python
# Before
def _on_doc_resized(self):
    height = int(doc.size().height()) + 28
    self._browser.setFixedHeight(max(height, 10))
    if self._current_width > 0:
        self._browser.setFixedWidth(self._current_width)

# After
def _on_doc_resized(self):
    self._adjust_size(update_width=True)
```

### 3.4 Live2D JS Console Encoding Fix (live2d_page.py)

Added explicit encoding with `errors="replace"`:

```python
# Before
print(f"[JS-{levels.get(level, str(level))}] {msg} ({src}:{line})")

# After
import sys
line_content = f"[JS-{levels.get(level, str(level))}] {msg} ({src}:{line})"
print(line_content.encode(sys.stdout.encoding, errors="replace").decode(sys.stdout.encoding, errors="replace"))
```

### 3.5 Knowledge Panel Updates (knowledge_panel.py)

- Added `"diaries": "日记"` table label
- Changed `"feelings": "想法"` → `"feelings": "情感"`
- Limited `self_cognition` / `other_cognition` to 1 row each

```python
limit = 1 if tname in ("self_cognition", "other_cognition") else 200
```

## 4. Impact

| File | Change Type | Impact |
|------|-------------|--------|
| `gui/widgets/chat_bubble.py` | Refactor | -80 lines changed; removed spacer, new QFontMetrics width calc, simplified _on_doc_resized |
| `gui/pages/chat_page.py` | Enhancement | +3 lines; alignment logic added to _append_bubble |
| `gui/pages/live2d_page.py` | Bug Fix | +2 lines; encoding safe print for JS console |
| `gui/widgets/knowledge_panel.py` | Enhancement | +5/-3 lines; new table label, limited query per table |
| `gui/pages/conversation_history.json` | Data | Updated conversation history data |
| `bnos_status.json` | Data | Updated service status data |
| `docs/design/[ANALYSIS]-awesome-llm-apps组件复用分析.md` | New | 359-line component reuse analysis |

## 5. Verification

1. Send a short user message → bubble should be right-aligned and tightly sized to content
2. Send a long message exceeding 600px → bubble should cap at 600px and wrap text
3. Stream an AI reply → width should dynamically recalculate with each chunk
4. Switch conversations → alignment (user=right, AI=left) should be preserved
5. Open Live2D page with JS console output containing CJK characters → no garbled output
6. Check knowledge panel → "diaries" category visible; self_cognition/other_cognition shows 1 entry each
