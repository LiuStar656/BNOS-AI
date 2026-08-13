# 2026-07-26 Update Overview

[Back to Index](../README.md)

---

## Table of Contents

- [01 Knowledge Panel Rework & Auto-Refresh](./01_KnowledgePanelRework.md)
- [02 AAA Three-Stage Prompt Restructuring](./02_ThreeStagePromptRestructuring.md)
- [03 Identity Key Multi-User Isolation System](./03_IdentityKeyIsolationSystem.md)
- [04 Database Write Fix & Long-Term Memory Format Correction](./04_DBWriteFixAndLongTermMemory.md)
- [05 Conversation Management Optimization & Process Refactor](./05_ConversationManagementAndProcessRefactor.md)

---

## Summary

| # | Core Change | Root Cause | Impact |
|---|------------|------------|--------|
| 01 | Knowledge panel reworked to DB-driven mode; auto-refresh on page switch | Hardcoded data inflexible; stale data on page switch | Real-time knowledge data, refreshes on tab switch |
| 02 | AAA prompts split into three-stage templates (direct/retrieval/tool) | Mixed output formats caused infinite tool-call loops | Clear output structure; LLM autonomously decides workflow |
| 03 | Full-pipeline identity_key for multi-user memory isolation | Single-user architecture couldn't distinguish users | Cognition/profiles/emotions/memory isolated per user |
| 04 | Fixed `_dedup_and_merge` hardcoded column; corrected long-term memory format | event_summary missing `content` column caused silent write failures | All cognition tables write correctly; memory includes full conversation context |
| 05 | Conversation rename/archive/scroll logic; process termination rewrite | UX feedback; PowerShell cleanup unreliable | Smoother UX; more reliable process management |

---

## Changed Files

### New Files

| File | Topic |
|------|-------|
| `docs/design/[OK]-提示词模板分层拆解方案.md` | #02 |
| `scripts/check_db_tables.py` | #04 |

### Major Changes

| File | Change | Topic |
|------|--------|-------|
| `gui/widgets/knowledge_panel.py` | DB-driven refactor, auto-refresh toggle, graph interaction | #01 |
| `gui/main_window.py` | Auto-refresh on page switch | #01 |
| `nodes/node_python_aaa_cognition/prompt.py` | Three-stage templates, identity_key injection | #02, #03 |
| `nodes/node_python_aaa_cognition/prompt_retrieval.py` | New retrieval-specific template | #02 |
| `nodes/node_python_aaa_cognition/prompt_tool.py` | New tool-call template | #02 |
| `nodes/node_python_aaa_cognition/main.py` | Three-stage decision logic, identity_key pipeline | #02, #03 |
| `nodes/node_python_aaa_cognition/db.py` | 11 tables +identity_key, migration, write fix | #03, #04 |
| `nodes/node_python_aaa_cognition/memos.py` | Index stores identity_key, filter by user | #03 |
| `nodes/node_python_aaa_cognition/parser.py` | LLM output parser restructured | #02 |
| `nodes/node_python_tts/main.py` | Emotion tag regex brackets → angle brackets | #04 |
| `gui/core/message_manager.py` | send_text output includes identity_key | #03 |
| `gui/pages/chat_page.py` | Conversation rename, archive list loading | #05 |
| `gui/widgets/chat_bubble.py` | Auto-scroll-to-bottom logic | #05 |
| `scripts/check_db_tables.py` | DB table status check script | #04 |

---

## File Stats

| Metric | #01 | #02 | #03 | #04 | #05 |
|--------|:---:|:---:|:---:|:---:|:---:|
| Files touched | 2 | 5 | 6 | 4 | 6 |
| Lines added | ~147 | ~672 | ~420 | ~235 | ~115 |
| **Total lines** | | | | | **~1,589+** |

---

**Last updated**: 2026-07-26
