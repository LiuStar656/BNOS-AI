# 2026-07-28 更新总览

[返回总索引](../README.md)

---

## 更新目录

- [01 聊天气泡布局与对齐逻辑重构](./01_聊天气泡布局与对齐逻辑重构.md)

---

## 摘要

| # | 核心改动 | 根因 | 影响 |
|---|---------|------|------|
| 01 | 重构 ChatBubble 组件，移除内部 spacer 布局，对齐逻辑移至外层 layout 统一处理；改用 font metrics 逐行测量替代 doc.size().width()；修复聊天记录对齐问题；优化 Live2D JS 控制台输出编码；更新知识库数据库表标签与查询逻辑 | QTextDocument doc.size().width() 返回布局宽度而非实际内容宽度导致气泡尾部留白；内部 spacer 干扰外层 layout 对齐控制；JS 控制台输出含不可编码字符导致乱码 | 气泡尺寸紧贴文本无多余留白，流式追加宽度自动重算；用户/AI 气泡按 role 正确对齐；Live2D 控制台输出稳定无乱码；知识库面板新增"日记"分类，self_cognition/other_cognition 仅显示最新 1 条 |

---

## 修改文件清单

### 新增文件

| 文件 | 所属 |
|------|------|
| `docs/design/[OK]-awesome-llm-apps组件复用分析.md` | #01 |

### 重大修改文件

| 文件 | 改动 | 所属 |
|------|------|------|
| `gui/widgets/chat_bubble.py` | 移除 spacer 布局、font metrics 逐行测量替代 doc.size().width()、流式追加宽度自动重算 | #01 |
| `gui/pages/chat_page.py` | 消息气泡添加时根据 role 设置对齐方式 | #01 |
| `gui/pages/live2d_page.py` | JS 控制台输出编码修复，使用 errors="replace" | #01 |
| `gui/widgets/knowledge_panel.py` | 新增"日记"表标签，self_cognition/other_cognition 限制返回 1 条 | #01 |
| `docs/design/[OK]-awesome-llm-apps组件复用分析.md` | 新增组件复用分析文档（359 行） | #01 |

---

## 文件变更统计

| 指标 | #01 |
|------|:---:|
| 涉及文件 | 5 |
| 新增行数 | ~434 |
| 删除行数 | ~57 |
| **净增行数** | **~377** |

---

**最后更新**：2026-07-28
