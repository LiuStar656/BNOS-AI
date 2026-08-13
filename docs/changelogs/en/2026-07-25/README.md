# 2026-07-25 Update Summary

[Back to Index](../README.md)

---

## Table of Contents

- [01 Live2D Preview Page Bug Fix](../2026-07-25/01_Live2DPreviewFix.md)
- [02 Live2D Desktop Overlay Component](./02_Live2DDesktopOverlay.md)
- [03 UI Framework Refactoring](./03_UIFrameworkRefactoring.md)
- [04 File Attachment Upload & Processing](./04_FileAttachment.md)
- [05 Plugin System Design](./05_PluginSystemDesign.md)
- [06 Markdown Rendering, Theme Optimization & Page Animation](./06_MarkdownThemesAnimation.md)
- [07 Multi-Conversation Chat UI Optimization](./07_MultiConversationUI.md)

---

## Summary

| # | Core Change | Root Cause | Impact |
|---|-------------|-----------|--------|
| 01 | Live2D preview: fix `AttributeError`, `ImportError`, 0x0 canvas | PySide6 API changes, hidden widget size=0 | Live2D preview works |
| 02 | New Live2D desktop overlay & preview page | New feature | Desktop character display |
| 03 | UI framework: FloatingPanel, TitleBar, frameless window | Unify secondary windows, beautify UI | Global UI architecture upgrade |
| 04 | New file attachment upload & processing | Need file transfer | Chat can send images/docs |
| 05 | New plugin system design document | Architecture planning | Framework doc added |
| 06 | Markdown rendering, 8 themes, page animation, Toast | UX improvement | Full GUI visual upgrade |
| 07 | Multi-conversation, archive, history persistence, bubble UI | Multi-conversation demand | Complete conversation system |

---

## File Change Statistics

| Metric | #01 | #02 | #03 | #04 | #05 | #06 | #07 |
|--------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Files affected | 2 | 11 | 14 | 7 | 3 | 14 | 22 |
| Lines added | ~350 | ~785 | ~1,490 | ~828 | ~369 | ~1,359 | ~1,810 |
| **Total lines** | | | | | | | **~5,000+** |

---

**Last updated**: 2026-07-25
