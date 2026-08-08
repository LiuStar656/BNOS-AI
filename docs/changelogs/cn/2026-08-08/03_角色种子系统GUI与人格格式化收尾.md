# 角色种子系统 Phase 3 GUI 与 Phase 4 人格格式化收尾

## 问题描述

角色种子系统 Phase 0-2（引擎：性格向量表、动态情绪值、种子背景写入）已完成，本次收尾 Phase 3（GUI 面板集成）与 Phase 4（人格格式化），并修复三个遗留问题：

1. 人格格式化会把种子背景写入 `long_term_memory`，但该表存的是对话 QA，种子背景应写入事件摘要 `event_summary`。
2. 格式化时没有清空数据库；"清空数据库"与"人格格式化"是两个独立功能，逻辑重叠应合并。
3. 性格种子 UI 的维度名只用一个半角冒号，与其他面板的全角冒号不统一。

## 根因分析

- `write_seed_background` 原实现写 `long_term_memory`（QA 语义），背景记忆属于"事件摘要"类型，写入后会被图谱/MemOS 当作对话 QA 检索，语义错位。
- `format` 命令只重置部分表，未覆盖 `fixed_cognition`、`personality_seed` 与 GUI 侧对话历史 JSON，格式化不彻底；同时存在独立的 `clear` 命令造成功能重复。
- 滑块维度名硬编码半角冒号，与界面其他标签风格不一致。

## 修改方案

### AAA 节点侧（nodes/node_python_aaa_cognition/）

1. **`db.py`**：`write_seed_background` 改为写入 `event_summary`（`source='seed'`，按 `identity_key` 幂等去重，防止格式化后重复累积）；`ensure()` 增加 v5.2 幂等迁移 `ALTER TABLE event_summary ADD COLUMN source`。
2. **`main.py`**：删除 `clear` 命令；`format` 命令改为彻底清空全部用户表（含 `fixed_cognition`）→ `reset_personality_seed` 重置性格 → 新增 `_clear_conversation_history` 清空 GUI 对话历史 JSON（方案 §10.5）。

### GUI 侧

3. **`settings_panel.py`**：删除"清空数据库"按钮，仅保留"人格格式化（清空并重来）"，确认弹窗文案改为"清空数据库中的全部数据 + 重置性格"；性格参数滑块维度名补全角冒号。
4. **`personality_dialog.py`**：滑块维度名补全角冒号（与设置面板一致）。

## 影响范围

| 文件 | 改动 |
|------|------|
| `nodes/node_python_aaa_cognition/db.py` | `write_seed_background` 写入目标从 long_term_memory 改为 event_summary（source='seed'）；v5.2 迁移增加 event_summary.source 列 |
| `nodes/node_python_aaa_cognition/main.py` | 删除 clear 命令；format 彻底清空全部表 + 重置性格 + 清对话历史 JSON；新增 `_clear_conversation_history` |
| `gui/pages/settings_panel.py` | 移除"清空数据库"按钮，合并为"人格格式化"；性格参数维度名全角冒号 |
| `gui/dialogs/personality_dialog.py` | 滑块维度名全角冒号 |

## 验证方法

- 三个文件编译通过（GetDiagnostics 无报错）。
- GUI 设置面板确认：仅"人格格式化（清空并重来）"一个按钮，执行后全部表清空、性格重置为默认预设、对话历史清空。
- 种子背景写入 `event_summary` 且 `source='seed'`，重复格式化不产生重复记录（幂等）。
