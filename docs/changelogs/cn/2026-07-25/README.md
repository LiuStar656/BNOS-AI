# 2026-07-25 更新总览

[返回总索引](../README.md)

---

## 更新目录

- [01 Live2D 预览页 Bug 修复](./01_Live2D预览页修复.md)
- [02 Live2D 桌面悬浮组件](./02_Live2D桌面悬浮组件.md)
- [03 UI 框架重构：浮动面板、自定义标题栏、无边框窗口](./03_UI框架重构.md)
- [04 附件上传与处理功能](./04_附件上传功能.md)
- [05 插件系统设计方案](./05_插件系统设计方案.md)
- [06 Markdown 渲染、主题优化与页面动画](./06_Markdown渲染与主题优化.md)
- [07 多对话聊天 UI 优化](./07_多对话聊天UI优化.md)

---

## 摘要

| # | 核心改动 | 根因 | 影响 |
|---|---------|------|------|
| 01 | Live2D 预览页：修复 `AttributeError`、`ImportError`、0x0 canvas 三个 Bug | PySide6 API 变更、隐藏控件尺寸为 0 | Live2D 预览页正常显示 |
| 02 | 新增 Live2D 桌面悬浮窗与预览管理页 | 新功能需求 | 桌面 Live2D 角色显示 |
| 03 | 重构 UI 框架：FloatingPanel、TitleBar、无边框窗口 | 统一二级窗口容器、美化外观 | 全局 UI 架构升级 |
| 04 | 新增附件上传与处理功能 | 支持文件传输 | 聊天可发送图片/文档 |
| 05 | 新增插件系统设计方案 | 架构规划 | 框架文档补充 |
| 06 | Markdown 渲染、8 套主题、页面动画、Toast 通知 | 提升交互体验 | GUI 视觉效果全面升级 |
| 07 | 多对话管理、归档、历史持久化、聊天气泡优化 | 多对话需求 | 完整的对话管理系统 |

---

## 修改文件清单

### 新增文件

| 文件 | 所属 |
|------|------|
| `gui/widgets/conversation_list.py` | #07 |
| `gui/dialogs/archive_panel.py` | #07 |
| `gui/widgets/markdown_renderer.py` | #06 |
| `gui/widgets/toast.py` | #06 |
| `gui/widgets/floating_panel.py` | #03 |
| `gui/widgets/title_bar.py` | #03 |
| `gui/widgets/live2d_overlay.py` | #02 |
| `docs/design/BNOS AI插件系统设计方案.md` | #05 |

### 新建/重命名文件

| 文件 | 改动 |
|------|------|
| `gui/pages/settings_panel.py` | 从 `settings_page.py` 重命名 +#03 |

### 重大修改文件

| 文件 | 改动 |
|------|------|
| `gui/main_window.py` | 无边框窗口、FloatingPanel 集成、Live2D 集成 |
| `gui/pages/chat_page.py` | 多对话支持、历史持久化、附件集成 |
| `gui/widgets/chat_bubble.py` | Markdown 渲染、自适应宽度 |
| `gui/widgets/chat_input.py` | 圆角容器样式、附件上传 |
| `gui/widgets/sidebar.py` | 弹出菜单布局 |
| `gui/core/config.py` | 主题预设系统、Live2D 配置 |
| `gui/core/message_manager.py` | request_id 过滤、附件字段 |
| `gui/core/state.py` | 多对话状态管理 |
| `gui/pages/live2d_page.py` | 大幅扩展：模型管理、服务控制 |
| `gui/pages/settings_page.py` | 数据库管理功能 |
| `gui/resources/theme.py` | 动态主题色注入 |
| `gui/widgets/color_picker.py` | 重构为 FloatingPanel 子类 |
| `gui/widgets/floating_panel.py` | 半透明支持 |
| `gui/widgets/toast.py` | 新增通知组件 |
| `gui/core/utils/dialog_utils.py` | 透明对话框基类 |
| `gui/widgets/live2d_overlay.py` | 半透明支持 |

---

## 文件变更统计

| 指标 | #01 | #02 | #03 | #04 | #05 | #06 | #07 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 涉及文件 | 2 | 11 | 14 | 7 | 3 | 14 | 22 |
| 新增行数 | ~350 | ~785 | ~1,490 | ~828 | ~369 | ~1,359 | ~1,810 |
| **总计行数** | | | | | | | **~5,000+** |

---

**最后更新**：2026-07-25
