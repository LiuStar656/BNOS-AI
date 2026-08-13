# 2026-07-26 更新总览

[返回总索引](../README.md)

---

## 更新目录

- [01 知识库面板重构与自动刷新](./01_知识库面板重构与自动刷新.md)
- [02 AAA 三阶段提示词模板重构](./02_AAA三阶段提示词模板重构.md)
- [03 Identity Key 多用户隔离系统](./03_IdentityKey多用户隔离系统.md)
- [04 数据库写入修复与长时记忆格式修正](./04_数据库写入修复与长时记忆格式修正.md)
- [05 对话管理优化与进程重构](./05_对话管理优化与进程重构.md)

---

## 摘要

| # | 核心改动 | 根因 | 影响 |
|---|---------|------|------|
| 01 | 知识库面板重构为数据库驱动模式，新增页面切换自动刷新 | 原有硬编码数据不灵活，切换页面后数据未更新 | 知识库数据实时更新，页面切换即刷新 |
| 02 | AAA 提示词拆分为自然回复/语意检索/工具调用三阶段模板 | LLM 输出格式混杂，工具调用无限循环 | 输出结构清晰，LLM 自主决策工作流 |
| 03 | 全链路引入 identity_key 实现多用户记忆隔离 | 单用户架构无法区分不同用户的数据 | 认知/画像/情感/记忆按用户隔离，为多用户铺路 |
| 04 | 修复 `_dedup_and_merge` 列名硬编码问题，修正长时记忆格式 | event_summary 表缺少 content 列导致写入静默失败 | 所有认知表正确写入，记忆存储含完整对话上下文 |
| 05 | 对话重命名/归档列表/泡泡滚动逻辑优化，进程终止脚本重写 | 用户体验反馈与 PowerShell 清理不彻底 | 操作更便捷，进程管理更可靠 |

---

## 修改文件清单

### 新增文件

| 文件 | 所属 |
|------|------|
| `docs/design/[OK]-提示词模板分层拆解方案.md` | #02 |
| `scripts/check_db_tables.py` | #04 |

### 重大修改文件

| 文件 | 改动 |
|------|------|
| `gui/widgets/knowledge_panel.py` | DB 驱动重构、自动刷新开关、图谱交互优化 | #01 |
| `gui/main_window.py` | 页面切换自动刷新知识库 | #01 |
| `nodes/node_python_aaa_cognition/prompt.py` | 拆分为三阶段模板，identity_key 注入 | #02, #03 |
| `nodes/node_python_aaa_cognition/prompt_retrieval.py` | 新增检索专用模板 | #02 |
| `nodes/node_python_aaa_cognition/prompt_tool.py` | 新增工具调用模板 | #02 |
| `nodes/node_python_aaa_cognition/main.py` | 三阶段决策逻辑、identity_key 全链路传递 | #02, #03 |
| `nodes/node_python_aaa_cognition/db.py` | 11 张表加 identity_key 列、迁移逻辑、写入修复 | #03, #04 |
| `nodes/node_python_aaa_cognition/memos.py` | 索引存储 identity_key、按用户过滤检索 | #03 |
| `nodes/node_python_aaa_cognition/parser.py` | LLM 输出解析结构调整 | #02 |
| `nodes/node_python_tts/main.py` | 情绪标签正则从方括号改为尖括号 | #04 |
| `gui/core/message_manager.py` | send_text 输出加 identity_key 字段 | #03 |
| `gui/pages/chat_page.py` | 对话重命名、归档列表加载 | #05 |
| `gui/widgets/chat_bubble.py` | 滚动到底部逻辑优化 | #05 |
| `scripts/check_db_tables.py` | 新增数据库表状态检查脚本 | #04 |

---

## 文件变更统计

| 指标 | #01 | #02 | #03 | #04 | #05 |
|------|:---:|:---:|:---:|:---:|:---:|
| 涉及文件 | 2 | 5 | 6 | 4 | 6 |
| 新增行数 | ~147 | ~672 | ~420 | ~235 | ~115 |
| **总计行数** | | | | | **~1,589+** |

---

**最后更新**：2026-07-26
