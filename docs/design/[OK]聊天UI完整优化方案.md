# BNOS AI 聊天 UI 完整优化方案

日期：2026-07-25 (v2 — 实现状态更新)
目标：优化现有聊天 UI，参考微信风格，添加多对话功能


## 1. 气泡优化（已完成 ✅）

### 1.1 气泡内容间距
**方案**：QTextBrowser padding 设为 `14px 18px`（在 QSS 中设置）
**状态**：已通过 QSS `padding: 14px 18px` 实现

### 1.2 气泡样式（Qt 原生 Markdown）
| 项目 | 状态 |
|------|------|
| 圆角 10px | 已实现 |
| 内容渲染 | 已切换至 Qt 原生 `QTextDocument.setMarkdown()` |
| 动态宽度 | `QSizePolicy.Maximum` + `QFontMetrics` 估算 |
| 主题颜色 | 从 `AppConfig` 动态加载 |


## 2. 输入框重构（已完成 ✅）

### 2.1 输入框容器
- `ChatInput` 自身作为圆角容器（`border-radius:10px`）
- 启用了 `WA_StyledBackground` 确保 QSS 圆角生效
- 输入框 `QTextEdit` 背景透明，无额外边框

### 2.2 功能
- 支持图片/文件选择（`QFileDialog`）
- 附件预览条 + 删除
- Enter 发送 / Shift+Enter 换行
- 主题刷新


## 3. 多对话三级布局（已完成 ✅）

### 3.1 整体布局（微信风格）
```
┌─────────────────────────────────────────────────────────┐
│ Sidebar(56px) │ ConversationList(240px) │  聊天内容页   │
│ 聊天 / Live2D │ 对话1 ✓               │  消息气泡      │
│ 节点管理      │ 对话2                 │  输入框        │
│ MCP 管理      │ 对话3                 │               │
│ 设置          │ [+ 新建]              │               │
└─────────────────────────────────────────────────────────┘
```

### 3.2 实现详情

| 组件 | 文件 | 说明 |
|------|------|------|
| `ConversationList` | `gui/widgets/conversation_list.py` | 固定宽度 240px，显示对话名称/预览/时间 |
| `ConversationItem` | 同上 | 列表单项，支持时间格式化（今天→时间，本周→周几，更早→月/日） |
| `AppState` 对话管理 | `gui/core/state.py` | 新增 `conversations` / `current_conversation_id` 属性及 CRUD 方法 |
| `ChatPage` 嵌入 | `gui/pages/chat_page.py` | 嵌入 `ConversationList`，切换时保存/加载对话消息 |

### 3.3 对话切换逻辑
- 切换对话时：`_save_current_messages()` → `clear_messages()` → `_load_conversation_messages(conv_id)`
- 消息以 `{conv_id: [(role, text), ...]}` 形式保存在 `ChatPage._conversation_messages`
- 发送消息后自动更新对话预览（前 60 字符）

### 3.4 后续计划
- 对话持久化（文件/数据库存储）
- 对话删除/重命名
- 搜索过滤
- 后端按 `conversation_id` 隔离上下文


## 4. 其他调整

| 项目 | 状态 |
|------|------|
| 消息间距 12px | 已实现 |
| 底部状态栏 | 已隐藏 |
| 主题同步 | 对话列表跟随主题刷新 |


## 实现顺序（已全部完成）
1. ✅ 气泡优化（padding、圆角）
2. ✅ 输入框重构（独立容器）
3. ✅ 多对话三级布局
4. ✅ 对话列表页
