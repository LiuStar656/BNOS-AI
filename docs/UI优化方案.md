# BNOS AI — GUI 优化方案

> 分析日期: 2026-07-25
> 参考项目: `references/PySide6-PyQt-UI-Demo-main`(MessageHub) , `references/ai-chat-gui-main`(AI Chat GUI)

---

## 一、当前 BNOS GUI 架构总览

```python
gui/
├── main.py                   # 入口：启动引擎 → 启动 GUI
├── main_window.py            # 主窗口（TitleBar + Sidebar + QStackedWidget + StatusBar）
├── core/
│   ├── config.py             # AppConfig 单例（主题颜色 + 窗口配置持久化）
│   ├── event_bus.py          # 事件总线（发布-订阅模式）
│   ├── message_manager.py    # 消息收发（轮询 JSON 文件）
│   └── state.py              # 全局状态管理
├── pages/
│   ├── chat_page.py          # 聊天页（消息列表 + ChatInput）
│   ├── live2d_page.py        # Live2D 页
│   ├── node_page.py          # 节点管理页
│   ├── mcp_page.py           # MCP 管理页
│   └── settings_page.py      # 设置页（颜色选择器 + 数据库管理）
├── widgets/
│   ├── chat_bubble.py        # 聊天气泡（QLabel + WordWrap）
│   ├── chat_input.py         # 输入栏（Enter发送/Shift换行 + 附件的工具栏）
│   ├── sidebar.py            # 侧边栏（竖排图标按钮组）
│   ├── title_bar.py          # 自定义标题栏（白底 + 窗口按钮）
│   ├── status_bar.py         # 底部状态栏（引擎/模型/节点状态）
│   ├── floating_panel.py     # 浮动面板基类
│   ├── color_picker.py       # 颜色选择器（预设色板网格）
│   └── live2d_overlay.py     # Live2D 叠加层
└── resources/
    ├── theme.py              # get_light_qss() — 动态注入颜色的全局样式表
    └── icons/codicon.py      # Codicon 字体图标
```

### 当前 UI 能力评估

| 模块 | 完成度 | 评价 |
|------|:-----:|------|
| 主窗口布局 | ★★★★☆ | Sidebar + QStackedWidget 结构清晰，无边框窗口 + 边缘 resize 实现完整 |
| 侧边栏 | ★★★★★ | 图标按钮组、checked 状态、颜色动态刷新，功能齐全 |
| 聊天气泡 | ★★★☆☆ | 基本的左右对齐和圆角，但只支持纯文本，**无 Markdown 渲染** |
| 输入栏 | ★★★★★ | 工具栏（图片/文件/表情/发送）、Enter 发送 Shift+Enter 换行、附件预览条、Ctrl+V 粘贴图片，功能完整 |
| 主题系统 | ★★★★☆ | AppConfig 驱动颜色变量、event_bus 广播主题变更，架构好。**但目前只有一套亮色主题** |
| 设置页 | ★★★★☆ | 颜色选择器设计得当，数据库管理功能完整 |
| 状态栏 | ★★★★☆ | 引擎/模型/节点实时状态显示 |
| 页面切换 | ★★★☆☆ | 硬切换（无动画），与 MessageHub 的滑动动画有差距 |
| 消息管理 | ★★★☆☆ | 只有纯文本消息，无对话列表/搜索/导出等功能 |

---

## 二、参考项目可复用组件分析

### 2.1 PySide6-PyQt-UI-Demo（MessageHub）

| 可复用组件 | 源文件 | 当前BNOS状态 | 复用方式 | 估计工作量 |
|-----------|--------|-------------|---------|-----------|
| **8套 QSS 主题** | [css/](file:///e:/杂项/BNOS_AI_project/references/PySide6-PyQt-UI-Demo-main/css/) | 只有 1 套亮色主题 | 将 8 套 QSS（dark/amoled/macos/koyu/ubuntu/gri/neon）改写成 BNOS 的 `AppConfig` 颜色变量模式，加入可选主题列表 | 2h |
| **HoverButton** | [hover_button.py](file:///e:/杂项/BNOS_AI_project/references/PySide6-PyQt-UI-Demo-main/widgets/hover_button.py) | 按钮样式全部通过 QSS 写入 | 颜色从硬编码 tuple 改为 AppConfig 读取，可用于强调按钮/操作按钮替换 | 0.5h |
| **页面切换动画** | [MainUI.py#L129-L168](file:///e:/杂项/BNOS_AI_project/references/PySide6-PyQt-UI-Demo-main/MainUI.py) | 无动画，硬切换 | QPropertyAnimation + EasingCurve 左右滑动。代码独立可拷贝，不依赖其他组件 | 1h |
| **CustomTextEdit** | [custom_text_edit.py](file:///e:/杂项/BNOS_AI_project/references/PySide6-PyQt-UI-Demo-main/widgets/custom_text_edit.py) | ChatInput 已有 Enter/Shift+Enter | 它的 Enter 发送逻辑与 BNOS 一致，确认各细节后不需要修改 | 0h |
| **HoverSlider** | [hover_slider.py](file:///e:/杂项/BNOS_AI_project/references/PySide6-PyQt-UI-Demo-main/widgets/hover_slider.py) | 暂无滑块控件 | 如果未来设置页需要亮度/音量滑块则复用 | 低优先级 |
| **MultiSelectListWidget** | [multi_select_list_widget.py](file:///e:/杂项/BNOS_AI_project/references/PySide6-PyQt-UI-Demo-main/widgets/multi_select_list_widget.py) | 暂无此类需求 | 如果未来需要列表多选可复用 | 低优先级 |

### 2.2 ai-chat-gui（AI Chat GUI）

| 可复用组件 | 位置 | 当前BNOS状态 | 复用方式 | 估计工作量 |
|-----------|------|-------------|---------|-----------|
| **Markdown 渲染** | [AIChat.py#L30-L84](file:///e:/杂项/BNOS_AI_project/references/ai-chat-gui-main/AIChat.py) | ChatBubble 用 QLabel + 纯文本 | 迁移 `PygmentsRenderer` + `MarkdownParser` 到 `chat_bubble.py`，用 QTextEdit / QTextBrowser 替代 QLabel | **3h（核心改造）** |
| **代码语法高亮** | [AIChat.py#L30-L84](file:///e:/杂项/BNOS_AI_project/references/ai-chat-gui-main/AIChat.py) | 无 | Pygments Monokai 主题 + 语言别名映射完全可复用 | 随 Markdown 渲染一起完成 |
| **流式输出** | [AIChat.py#L2477-L2500](file:///e:/杂项/BNOS_AI_project/references/ai-chat-gui-main/AIChat.py) | 一次性显示 | 当前是 [message_manager.py](file:///e:/杂项/BNOS_AI_project/gui/core/message_manager.py) 轮询 JSON → 一次性 `_append_bubble()`。流式需要后端支持分块写入 JSON 或 pipe | 暂不涉及（后端能力问题） |
| **输入区图片预览** | [AIChat.py#L2017-L2079](file:///e:/杂项/BNOS_AI_project/references/ai-chat-gui-main/AIChat.py) | ChatInput 已有附件预览条 | BNOS 的附件标签（文件名 + 删除按钮）更简洁清晰。ai-chat-gui 的图片缩略图预览模式可做参考 | 0.5h 可选增强 |
| **对话列表** | [AIChat.py#L1831-L1858](file:///e:/杂项/BNOS_AI_project/references/ai-chat-gui-main/AIChat.py) | 无 | 左侧暗色对话列表面板 + 右键菜单（重命名/删除）+ 切换时保存状态 | 2h（独立功能） |
| **设置弹窗动画** | [AIChat.py#L269-L438](file:///e:/杂项/BNOS_AI_project/references/ai-chat-gui-main/AIChat.py) | SettingsPage 是 QStackedWidget 的一页 | ai-chat-gui 的 SettingsDialog 是弹出式弹窗（渐变背景圆角），风格不同但可以作为另一种交互模式的参考 | 0h（只是风格参考） |

---

## 三、优先实施计划（按实际价值排序）

### P0 — 聊天气泡支持 Markdown 渲染（最关键）

**现状**: ChatBubble 用 `QLabel` + `WordWrap`，纯文本显示。AI 回复里如果出现代码、列表、表格等结构化内容，用户看到的是原始 Markdown 文本。

**方案**: 将 ChatBubble 从 `QLabel` 改为 `QTextBrowser`（或 `QTextEdit` 只读），嵌入 ai-chat-gui 的 `PygmentsRenderer` + `MarkdownParser`。

```
改前: ChatBubble._label = QLabel(text)
       只支持纯文本，连 <b> 都不会解析

改后: ChatBubble._text_browser = QTextBrowser()
       用 mistune 解析 Markdown → HTML → setHtml()
       代码块用 Pygments 生成语法高亮 HTML
```

**代码来源**: [AIChat.py#L30-L84](file:///e:/杂项/BNOS_AI_project/references/ai-chat-gui-main/AIChat.py) 的 `PygmentsRenderer` 类 + `MarkdownParser` 单例，可以抽取为独立的 `gui/widgets/markdown_renderer.py`

**影响文件**:
- `gui/widgets/chat_bubble.py` — 核心改动
- 需新增依赖: `mistune` + `pygments`（两个纯 Python 包）

**预计工作**: 3h（包括 QTextBrowser 样式适配、气泡圆角保持、代码块样式调整）

---

### P1 — 页面切换加入滑动动画

**现状**: `QStackedWidget.setCurrentWidget()` 是硬切换，没有过渡。

**方案**: 拷贝 MessageHub 的 `QPropertyAnimation` 实现，在切换时加入水平滑动 + 缓动曲线。

**代码来源**: [MainUI.py#L129-L168](file:///e:/杂项/BNOS_AI_project/references/PySide6-PyQt-UI-Demo-main/MainUI.py)

```python
# 核心逻辑（可直接拷贝）
def slide_to(self, next_widget: QWidget, direction: int):
    self._stack_animation = QPropertyAnimation(self, b"pos")
    self._stack_animation.setDuration(250)
    self._stack_animation.setEasingCurve(QEasingCurve.OutCubic)
    # direction: 1=左滑, -1=右滑
```

**影响文件**:
- `gui/main_window.py` — 在 `_switch_page` 中加入动画
- 需新增 `from PySide6.QtCore import QPropertyAnimation, QEasingCurve`（无需额外依赖）

**预计工作**: 1h

---

### P2 — 多主题切换（QSS 主题包）

**现状**: 只有 1 套亮色主题，所有颜色在 `AppConfig.theme` 中管理。

**方案**: 将 MessageHub 的 8 套 QSS 主题转换为 BNOS 的 `AppConfig` 颜色变量格式，在设置页加一个主题选择下拉框。

转换逻辑：MessageHub 的每个主题文件（如 `dark_theme.qss`）包含完整的 QSS，颜色值是硬编码的。需要把颜色值提取成 `AppConfig` 的 `theme` 键，每个主题对应一套颜色方案：

```json
// AppConfig.themes 新增字段
{
  "themes": {
    "default_light": {
      "accent_color": "#1a73e8",
      "bg_primary": "#f5f5f5",
      "bg_chat": "#f0f2f5",
      ...
    },
    "dark": {
      "accent_color": "#64b5f6",
      "bg_primary": "#1e1e1e",
      "bg_chat": "#252526",
      ...
    },
    "amoled": { ... }
  }
}
```

用户选主题 → `AppConfig` 切换颜色方案 → `event_bus.publish("theme_changed")` → 全部组件刷新。

**影响文件**:
- `gui/core/config.py` — 增加 `themes` 字典存储
- `gui/pages/settings_page.py` — 增加主题选择下拉框
- 各 widget 的 `refresh_theme()` — 已有 event_bus 机制，不需要改动

**依赖**: 无需额外依赖（QSS 本身就是字符串替换）

**预计工作**: 3h（8 套主题的颜色提取 + 适配 + 设置页下拉框）

---

### P3 — 对话列表（可选增强）

**现状**: 一个聊天窗口，不支持多对话管理。

**方案**: 在 ChatPage 左侧加一个对话列表面板（参考 ai-chat-gui 的实现），支持新建/切换/重命名/删除对话。

**影响文件**:
- `gui/pages/chat_page.py` — 增加左侧面板
- `gui/core/message_manager.py` — 增加对话 ID 管理

**预计工作**: 2h

---

## 四、无需修改的部分

| 已有组件 | 评价 |
|---------|------|
| Sidebar | 功能完整，MessageHub 的 sidebar 与 BNOS 的设计接近，不需要改 |
| ChatInput | 功能完整度超过 ai-chat-gui 的输入栏（有附件预览条、图片/文件选择），不需要改 |
| StatusBar | 功能完整 |
| TitleBar | 功能完整 |
| ColorPicker | 自定义颜色选择器已经适配了明亮主题，功能完整 |
| EventBus | 设计良好，不需要改 |
| MessageManager | 轮询架构够用，不需要改（流式输出依赖后端） |
| FloatingPanel | 基类设计良好 |
| SettingsPage | 功能完整，只需要增加主题选择下拉框 |

---

## 五、最终建议优先级

```
本轮实施（按顺序）:
┌── P0: 🔥 Markdown 渲染（ChatBubble 改 QTextBrowser + Pygments 高亮）    3h
├── P1: 📱 页面滑动动画（QPropertyAnimation + EasingCurve）               1h
├── P2: 🎨 多主题切换（8 套 QSS 颜色方案 + 设置页下拉框）                  3h
└── P3: 💬 对话列表（多对话管理）                                           2h

总共约 9h，建议分 3 次实施（每次 3h）。
```

