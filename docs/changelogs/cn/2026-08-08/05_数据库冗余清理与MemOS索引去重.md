# 数据库冗余清理与 MemOS 索引去重

## 问题描述

逐表审查数据库后确认存在冗余：`retrieval_log` 表从未写入任何数据（死表）；MemOS 语义索引同时索引 `user_messages` 与 `long_term_memory`，对话内容被索引两次导致检索结果重复；数据浏览面板存在未翻译的表（mood_value、personality_seed）与已删除表的残留翻译。

## 根因分析

- `retrieval_log` 是早期设计遗留，建表后无任何写入路径，属于无意义冗余表。
- 对话已以合并 QA 形式写入 `long_term_memory`（source='exchange'），`user_messages` 是原始对话原文，双源同时建索引会让同一段对话以两个向量出现，检索命中重复。
- 数据浏览的翻译表（`TABLE_LABELS`）未同步新增表与已删表。

## 修改方案

1. **`nodes/node_python_aaa_cognition/db.py`**：v5.4 幂等迁移 `DROP TABLE IF EXISTS retrieval_log`，同时移除建表语句，彻底清除冗余表。
2. **`nodes/node_python_aaa_cognition/memos.py`**：`rebuild_index` / `retrieve` 移除 `user_messages` 索引源，只索引 `long_term_memory` + `diaries`；删除死代码 `_fetch_feeling`。
3. **`gui/widgets/knowledge_panel.py`**：`TABLE_LABELS` 补充 `mood_value`（情绪值）/ `personality_seed`（性格种子）翻译，移除 `retrieval_log` 残留翻译。

## 影响范围

| 文件 | 改动 |
|------|------|
| `nodes/node_python_aaa_cognition/db.py` | v5.4 迁移删除 retrieval_log 表（含移除建表） |
| `nodes/node_python_aaa_cognition/memos.py` | 索引源移除 user_messages（只索引 long_term_memory + diaries）；删除 `_fetch_feeling` 死代码 |
| `gui/widgets/knowledge_panel.py` | 翻译补全 mood_value/personality_seed，移除 retrieval_log 翻译 |

## 验证方法

- 数据库确认 `retrieval_log` 表不存在（新库不再建、旧库迁移删除）。
- MemOS 索引重建后，同一对话内容只对应一个索引条目，检索无重复命中。
- 数据浏览面板所有表名均有中文翻译。
