# 04 — File Attachment Upload & Processing

> Date: 2026-07-25 | Files: 7 | Type: New Feature

---

## I. Overview

WeChat-style file attachment support for the chat input:

1. **Attachment button**: Left side of input toolbar
2. **File selection**: Images, documents, audio files
3. **Attachment preview**: Thumbnail preview above input area
4. **Local caching**: Auto-copy to conversation-specific cache directory
5. **LLM self-reading**: AAA node reads attached files autonomously

---

## II. Implementation

### 2.1 ChatInput Extension

```python
class ChatInput(QWidget):
    """WeChat-style input with attachment support"""

    # New signals
    fileAttached = Signal(list)  # attached file paths
    sendMessage = Signal(str, list)  # (text, attachments)
```

**UI Layout:**
```
ChatInput
├── Attachment preview (collapsible)
├── Input Toolbar
│   ├── Attachment button
│   └── Send button
└── QTextEdit input area
```

### 2.2 Caching Logic

```python
_ATTACHMENT_CACHE_DIR = "attachments"  # conversation-specific
_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp",
                       ".pdf", ".doc", ".docx", ".txt",
                       ".mp3", ".wav", ".wma", ".m4a"}
```

### 2.3 AAA Node Handling

```json
{
  "message": "user text",
  "attachments": [
    {"path": "/abs/path/file.jpg", "type": "image/jpeg"}
  ]
}
```

---

## III. Design Decisions

| Decision | Reason |
|----------|--------|
| Copy to local cache | Prevent broken paths from moved/deleted files |
| LLM self-read | Follow BNOS "Don't Replace Programming" principle |
| Disable on REST-only | Prevent unresponsive upload without WebSocket |

---

**Last updated**: 2026-07-25
