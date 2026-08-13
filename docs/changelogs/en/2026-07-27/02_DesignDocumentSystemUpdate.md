# 02 — Design Document System Update: New Plans & Integration

> Date: 2026-07-27 | Files touched: 10+ | Type: Documentation

---

## 1. Problem

The BNOS project had growing architectural complexity across multiple domains (memory storage, plugin system, character system, event-driven behavior, 3D customization) without formal design documentation to guide implementation. Existing design docs were scattered, some were outdated duplicates, and key architectural decisions lacked written rationale.

## 2. Root Cause

1. Rapid feature development outpaced documentation — many subsystems were built ad-hoc without a design-first approach.
2. No centralized inventory of component reuse opportunities existed, leading to duplicated effort.
3. The main development document (`[PLAN]-事件驱动型AI自主行为方案.md`) was missing critical sections on turn-lag mechanics, generation markers, and prompt injection prevention.
4. Duplicate and outdated design docs accumulated as the project evolved, creating confusion about which documents were authoritative.

## 3. Solution

### 3.1 New Design Documents Created

**Character Seed System** (`[PLAN]-角色种子系统设计方案.md`, 683 lines):
A comprehensive design for a seed-based character generation system that defines personality traits, behavioral patterns, and initial memory seeds for AI characters.

**3D Character Customization System** (`[PLAN]-3D角色自定义系统设计方案.md`, 528 lines):
A design plan for a 3D character customization pipeline including model loading, parameterized customization (hair, face, body), and integration with the existing Live2D rendering system.

### 3.2 Major Updates to Existing Documents

**Event-Driven Autonomous Behavior Plan** (`[PLAN]-事件驱动型AI自主行为方案.md`):
Major update adding:
- **Turn-lag mechanism**: A delay system that prevents the AI from responding too quickly, creating more natural conversation pacing
- **Generation markers**: Metadata flags attached to generated content for tracking provenance and preventing regeneration loops
- **Prompt injection prevention**: Security measures added to the prompt pipeline to sanitize user input and prevent prompt injection attacks

**Component Reuse Analysis** (`[PLAN]参考项目组件复用分析清单.md`):
Added Jarvis component reuse analysis, cataloging reusable patterns from the Jarvis backend project (prompt templates, memory systems, tool-call architectures).

### 3.3 Storage System & Plugin System Plans

New storage system 3-tier architecture redesign plan and plugin system design plan were added to formalize the architectural direction for these subsystems.

### 3.4 Cleanup

Duplicate and outdated design documents were identified and removed to keep the design directory authoritative and navigable.

## 4. Impact

- `docs/design/[PLAN]-事件驱动型AI自主行为方案.md`: Major update — turn-lag, generation markers, prompt injection prevention
- `docs/design/[PLAN]参考项目组件复用分析清单.md`: Added Jarvis component reuse analysis
- `docs/design/[PLAN]-角色种子系统设计方案.md`: New (683 lines)
- `docs/design/[PLAN]-3D角色自定义系统设计方案.md`: New (528 lines)
- Multiple other design docs: Storage system redesign plan, plugin system design plan

## 5. File Change List

| File | Lines | Description |
|------|:-----:|-------------|
| `docs/design/[PLAN]-事件驱动型AI自主行为方案.md` | ~400 added | Major update: turn-lag, generation markers, prompt injection prevention |
| `docs/design/[PLAN]参考项目组件复用分析清单.md` | ~50 added | Added Jarvis component reuse analysis |
| `docs/design/[PLAN]-角色种子系统设计方案.md` | 683 | New — character seed system design |
| `docs/design/[PLAN]-3D角色自定义系统设计方案.md` | 528 | New — 3D character customization pipeline |
| `docs/design/[PLAN]-AI世界感知记忆系统设计方案.md` | 134 | New — environment/memory perception system |
| `docs/design/[ANALYSIS]-Soul-of-Waifu组件复用分析.md` | 661 | New — Soul-of-Waifu component reuse analysis |
| `docs/design/[ANALYSIS]-Airi-SillyTavern组件复用分析.md` | 928 | New — Airi-SillyTavern component reuse analysis |
