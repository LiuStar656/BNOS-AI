# 2026-07-27 Update Overview

[Back to Index](../README.md)

---

## Table of Contents

- [01 Knowledge Panel Auto-Refresh & Conversation Management Optimization](./01_KnowledgePanelAutoRefresh.md)
- [02 Design Document System Update: New Plans & Integration](./02_DesignDocumentSystemUpdate.md)
- [03 Knowledge Panel Data Loading & Display Optimization](./03_KnowledgePanelDataLoading.md)

---

## Summary

| # | Core Change | Root Cause | Impact |
|---|------------|------------|--------|
| 01 | Knowledge panel auto-refresh (page switch + 10s timer + manual button); Message Manager `cancel_ongoing()` method; chat bubble layout margin/size optimization; conversation switching pending-reply routing & send state reset | Knowledge panel data stale on page switch; no way to cancel in-flight send requests; chat bubble margins inconsistent; switching conversations could receive stale replies | Real-time knowledge data; cleaner conversation lifecycle; reliable reply routing per conversation |
| 02 | New storage system 3-tier architecture redesign plan; plugin system design plan; event-driven autonomous behavior plan (major update); component reuse analysis inventory; new character seed system (683 lines) & 3D character customization (528 lines) design docs; added turn-lag/generation markers/prompt injection prevention to main dev doc; added Jarvis component reuse analysis; deleted duplicate/outdated docs | Expanding system complexity required formal design documentation across multiple domains | Clear architectural roadmap; component reuse strategy formalized; 5 new design docs, 2 major updates |
| 03 | Dynamic DB table scanning for filter buttons (replacing hardcoded list); new content display formats (period, keywords); updated label text; new environment memory design doc (134 lines); two new design analysis docs (661 + 928 lines) | Static filter list missed new tables; content display didn't cover period/keyword formats | Self-adapting filter buttons; richer data display; 3 new design docs |

---

## Changed Files

### New Files

| File | Topic |
|------|-------|
| `scripts/check_db_tables.py` | #01 |
| `docs/design/[PLAN]-角色种子系统设计方案.md` | #02 |
| `docs/design/[PLAN]-3D角色自定义系统设计方案.md` | #02 |
| `docs/design/[PLAN]-AI世界感知记忆系统设计方案.md` | #03 |
| `docs/design/[ANALYSIS]-Soul-of-Waifu组件复用分析.md` | #03 |
| `docs/design/[ANALYSIS]-Airi-SillyTavern组件复用分析.md` | #03 |

### Major Changes

| File | Change | Topic |
|------|--------|-------|
| `gui/widgets/knowledge_panel.py` | Auto-refresh on page switch, manual refresh button; dynamic DB table scanning; new content display formats | #01, #03 |
| `gui/main_window.py` | Page-switch triggers knowledge panel refresh | #01 |
| `gui/core/message_manager.py` | New `cancel_ongoing()` method | #01 |
| `gui/pages/chat_page.py` | Conversation switching: pending reply routing, send state reset | #01 |
| `gui/widgets/chat_bubble.py` | Layout margin & size calculation optimization, removed redundant QTimer calls | #01 |
| `scripts/check_db_tables.py` | New DB table check script | #01 |
| `docs/design/[OK]-提示词模板分层拆分方案.md` | New prompt template layering design doc | #01 |
| `docs/design/[PLAN]-事件驱动型AI自主行为方案.md` | Major update: turn-lag, generation markers, prompt injection prevention | #02 |
| `docs/design/[PLAN]参考项目组件复用分析清单.md` | Added Jarvis component reuse analysis | #02 |

---

## File Stats

| Metric | #01 | #02 | #03 |
|--------|:---:|:---:|:---:|
| Files touched | 6 | 10+ | 4 |
| Lines added | ~155 | ~1,900+ | ~1,750+ |
| **Total lines** | | | **~3,800+** |

---

**Last updated**: 2026-07-27
