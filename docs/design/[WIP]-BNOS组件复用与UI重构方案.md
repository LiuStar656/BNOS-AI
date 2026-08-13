# BNOS 组件复用与 UI 重构方案

> 日期：2026-07-25 | 版本：v1.0 | 状态：[PLAN]

## 目录

- [一、背景与现状评估](#一背景与现状评估)
- [二、目标](#二目标)
- [三、方案设计](#三方案设计)
  - [3.1 可复用组件清单](#31-可复用组件清单)
  - [3.2 设计① — FloatingPanel 适配与复用](#32-设计--floatingpanel-适配与复用)
  - [3.3 设计② — TitleBar 适配与复用（明亮版）](#33-设计--titlebar-适配与复用明亮版)
  - [3.4 设计③ — WeChat 风格多功能发送框](#34-设计--wechat-风格多功能发送框)
  - [3.5 设计④ — 附件传输链路](#35-设计--附件传输链路)
  - [3.6 设计⑤ — ColorPickerPopup 重写为 FloatingPanel 子类](#36-设计--colorpickerpopup-重写为-floatingpanel-子类)
  - [3.7 最终 UI 结构](#37-最终-ui-结构)
- [四、分阶段实施计划](#四分阶段实施计划)
- [五、风险评估](#五风险评估)
- [六、测试计划](#六测试计划)
- [七、影响范围](#七影响范围)

---

## 一、背景与现状评估

### 当前 UI 架构

```
MainWindow (QMainWindow, 原生标题栏)
  ├─ Sidebar (左侧导航)
  └─ QStackedWidget + StatusBar
      ├─ ChatPage    — QLineEdit + SendButton（简陋）
      ├─ Live2DPage  — QWebEngineView（预览页）
      ├─ NodePage    — 节点管控
      ├─ MCPPage     — MCP 配置
      └─ SettingsPage — 设置 + 数据库管理
```

### 存在的问题

| 问题 | 描述 |
|------|------|
| **消息输入框简陋** | `QLineEdit` 单行输入，无多行支持、无附件发送、无工具栏 |
| **二级窗口无统一风格** | `ColorPickerPopup` 是独立 `QDialog`，与主窗口风格割裂 |
| **标题栏为系统原生** | 主窗口使用 Windows 原生标题栏，无自定义样式、无深色模式适配 |
| **无标准浮动/弹出面板** | 所有弹出窗口需自建，无统一基类 |
| **发送框无状态反馈** | 无法直观展示发送状态、附件预览、输入提示 |

---

## 二、目标

1. **复用 BNOS 参考项目中的 `FloatingPanel` 和 `TitleBar`（明亮版）**，保持与现有 `gui/` 结构一致
2. **FloatingPanel 接管所有二级窗口**：`ColorPickerPopup` 改为继承 `FloatingPanel`
3. **TitleBar 替换主窗口原生标题栏**：MainWindow 设置 `FramelessWindowHint`，顶部嵌入自定义标题栏
4. **重构发送框为 WeChat 风格**：多行输入 + 工具栏（图片/文件/表情/发送）+ 附件预览
5. **附件传输链路**：通过 `gui_input.json` 的 `attachments` 字段传递文件信息给 AAA 节点

---

## 三、方案设计

### 3.1 可复用组件清单

BNOS 参考项目中可直接复用的 UI 组件：

| 组件 | 参考文件 | 核心类 | 功能 |
|------|---------|--------|------|
| **FloatingPanel** | `references/.../ui/core/dock/floating_panel.py` | `FloatingPanel(QDialog)` | 无边框/半透明/可拖动/标题栏+关闭/ESC关闭 |
| **TitleBar（明亮版）** | `references/.../ui/core/dark_title_bar.py` | `DarkTitleBar(QWidget)` 参考 | 明亮标题栏+菜单+最小化/最大化/关闭+拖移（配色改为白底） |
| **ThemedDialogBase** | `references/.../ui/core/utils/dialog_utils.py` | `ThemedDialogBase(QDialog)` | 深色对话框基类（类似于 FloatingPanel 的另一种风格） |
| **Codicon 图标** | `gui/resources/icons/codicon.py` | `CodiconManager` | 已集成，提供 `codicon.get_char("icon_name")` |

### 3.2 设计① — FloatingPanel 适配与复用（明亮版）

**适配为 `gui/widgets/floating_panel.py`**

将 BNOS 的 `FloatingPanel` 复制到项目中，去掉 BNOS i18n 依赖（`from ui.core.i18n.i18n import t`），改为直接传字符串。**同时将配色从深色改为明亮版**：

| 样式项 | BNOS 深色（参考） | 适配后明亮版 |
|--------|-----------------|-------------|
| 容器背景 | `rgba(30,30,30,220)` | `rgba(255,255,255,240)` |
| 容器边框 | `1px solid rgba(255,255,255,25)` | `1px solid rgba(0,0,0,15)` |
| 标题文字 | `color: white;` | `color: #333;` |
| 按钮文字 | `rgba(255,255,255,150)` | `rgba(0,0,0,50%)` |
| 按钮 hover | `rgba(255,255,255,30)` | `rgba(0,0,0,8%)` |
| 关闭 hover | `rgba(255,80,80,100)` | `rgba(232,17,35,0.1)` |
| 底部提示 | `rgba(255,255,255,80)` | `rgba(0,0,0,40%)` |

```python
class FloatingPanel(QDialog):
    """浮动面板基类 — 统一所有悬浮窗的样式、拖动和生命周期管理"""

    closed = Signal()

    def __init__(self, parent=None, title="面板"):
        super().__init__(parent)
        self.parent_window = parent
        self.drag_position = None

        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._setup_frame(title)

    # 对外接口:
    #   self.content_layout  → 子类添加内容
    #   self.hint(text)      → 设置底部提示
    #   self.set_title(text) → 动态改标题
```

保留的核心能力：
- 半透明深色容器（`rgba(30,30,30,220)` + `border-radius: 8px`）
- 标题栏（标题 + 最小化/关闭按钮，QLabel 样式）
- 全局拖拽（`mousePressEvent` / `mouseMoveEvent` / `mouseReleaseEvent`）
- ESC 关闭（`event()` 拦截）
- 显示时自动激活（`showEvent`）
- `closed` 信号 + `closeEvent` 生命周期

### 3.3 设计② — TitleBar 适配与复用（明亮版）

**适配为 `gui/widgets/title_bar.py`**

将 BNOS 的 `DarkTitleBar` 复制到项目中，去掉对 `QMenuBar` 的强制依赖（可选传入）。**类名改为 `TitleBar`，配色改为明亮版**：

| 样式项 | BNOS 深色（参考） | 适配后明亮版 |
|--------|-----------------|-------------|
| 标题栏背景 | `#1e1e1e` | `rgba(255,255,255,245)` |
| 底部边框 | `1px solid #3c3c3c` | `1px solid rgba(0,0,0,12)` |
| 标题文字 | `#cccccc` | `#333` |
| 按钮默认文字 | `#cccccc` | `#555` |
| 按钮 hover 背景 | `#3a3a3a` | `rgba(0,0,0,6%)` |
| 关闭 hover 背景 | `#e81123` | `rgba(232,17,35,0.12)` |
| 关闭 hover 文字 | `white` | `#d32f2f` |
| 菜单文字 | `#cccccc` | `#333` |
| 菜单 hover | `#094771` | `#1a73e8` |

```python
class TitleBar(QWidget):
    """明亮版自定义标题栏（VSCode 风格上白下灰）"""

    minimize_clicked = Signal()
    maximize_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, parent=None, title="BNOS AI 伴侣", menubar=None):
        ...
```

保留的核心能力：
- 标题 + 可选菜单栏
- 最小化/最大化/还原/关闭按钮（文字改为 codicon 图标）
- 标题栏拖拽移动窗口（鼠标事件 + 位置偏移）
- 顶部 6px 保留给 resize（不响应拖拽）
- 双击标题栏最大化/还原
- 关闭按钮 hover 变红色（`#e81123`）
- `set_maximized_state()` 保持按钮状态同步

**集成到 MainWindow：**

```python
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowSystemMenuHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 替换中央布局为：标题栏 + 内容区
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._title_bar = TitleBar(self, "BNOS AI 伴侣")
        main_layout.addWidget(self._title_bar)

        # 内容区复用现有的 Sidebar + StackedWidget
        content = QWidget()
        content.setObjectName("mainContent")
        ...  # 现有的 HBoxLayout(Sidebar + right_side)
        main_layout.addWidget(content, 1)

        # 信号连接
        self._title_bar.minimize_clicked.connect(self.showMinimized)
        self._title_bar.maximize_clicked.connect(self._toggle_maximized)
        self._title_bar.close_clicked.connect(self.close)

    def _toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._title_bar.set_maximized_state(self.isMaximized())
```

**窗口 resize 实现：**

FramelessWindowHint 下窗口失去原生 resize 能力。使用现存 `_RESIZE_MARGIN = 6` 保证顶部可 resize。四周边缘也需增加 resize 逻辑（可选实现），或者使用 `WindowSystemMenuHint` 保留系统菜单的 resize 能力（简单方案）。

### 3.4 设计③ — WeChat 风格多功能发送框

**新建 `gui/widgets/chat_input.py`**

```
┌─────────────────────────────────────────────────────────────┐
│  ┌──────────────────────────────────────────────────────┐  │
│  │  多行输入区域 (placeholder="输入消息...")              │  │  ← QTextEdit
│  │  (支持 Shift+Enter 换行, Enter 发送)                  │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  📎 图片  │  📄 文件  │  😊 表情  │         │  📤 发送 │  │  ← 工具栏
│  └──────────────────────────────────────────────────────┘  │
│  附件预览条:  [📷 screenshot.png  ✕]  [📎 report.pdf  ✕]   │  ← QFlowLayout 缩略图
└─────────────────────────────────────────────────────────────┘
```

**组件构成：**

```python
class ChatInput(QWidget):
    """WeChat 风格多功能输入栏"""

    send_requested = Signal(str, list)  # (text, attachments)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 1. 文本输入区
        self._text_edit = QTextEdit()
        self._text_edit.setPlaceholderText("输入消息...")
        self._text_edit.setFixedHeight(80)
        self._text_edit.setAcceptRichText(False)  # 纯文本
        layout.addWidget(self._text_edit)

        # 2. 附件预览条（动态显示已选择的附件）
        self._attachments: list[dict] = []   # [{type, name, path}]
        self._attachment_bar = AttachmentBar()
        self._attachment_bar.setVisible(False)
        layout.addWidget(self._attachment_bar)

        # 3. 工具栏
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 2, 4, 2)
        toolbar.setSpacing(8)

        self._img_btn = ToolButton(codicon.get_char("file-media"), "图片")
        self._img_btn.clicked.connect(self._pick_image)
        toolbar.addWidget(self._img_btn)

        self._file_btn = ToolButton(codicon.get_char("file"), "文件")
        self._file_btn.clicked.connect(self._pick_file)
        toolbar.addWidget(self._file_btn)

        self._emoji_btn = ToolButton(codicon.get_char("smiley"), "表情")
        self._emoji_btn.clicked.connect(self._pick_emoji)
        toolbar.addWidget(self._emoji_btn)

        toolbar.addStretch()

        self._send_btn = QPushButton(f" {codicon.get_char('send')} 发送")
        self._send_btn.setObjectName("sendButton")
        toolbar.addWidget(self._send_btn)

        layout.addLayout(toolbar)

        # 信号
        self._send_btn.clicked.connect(self._do_send)
        self._text_edit.installEventFilter(self)

    def eventFilter(self, obj, event):
        """Enter 发送, Shift+Enter 换行"""
        if obj is self._text_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return and not event.modifiers() & Qt.ShiftModifier:
                self._do_send()
                return True
        return super().eventFilter(obj, event)

    def _do_send(self):
        text = self._text_edit.toPlainText().strip()
        if not text and not self._attachments:
            return
        self.send_requested.emit(text, self._attachments)
        self._text_edit.clear()
        self._attachments.clear()
        self._attachment_bar.clear()
        self._attachment_bar.setVisible(False)
```

**附件栏 (AttachmentBar)：**

```python
class AttachmentBar(QWidget):
    """附件预览条 — 显示已选择文件的缩略图/文件名 + 删除按钮"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 2, 4, 2)
        self._layout.setSpacing(6)

    def add_attachment(self, attach: dict):
        """添加附件标签：{type, name, path}"""
        tag = QFrame()
        tag.setObjectName("attachmentTag")
        # ... 文件名 + 删除按钮 ✕
        remove_btn = QPushButton(chr(0xEA76))  # codicon close
        remove_btn.clicked.connect(lambda: self._remove(attach))
        # ... 添加到 layout

    def _remove(self, attach: dict):
        # 从 self._attachments 移除 + 从界面移除
        pass
```

**键盘快捷键：**
- `Enter` → 发送
- `Shift+Enter` → 换行
- `Ctrl+V` 粘贴图片 → 自动添加到附件列表

### 3.5 设计④ — 附件传输链路

**GUI → AAA：**

```json
// gui_input.json
{
  "data_type": "text",
  "source": "gui",
  "content": "看看这张图片",
  "attachments": [
    {"type": "image", "name": "截图.png", "path": "C:/Users/.../截图.png"},
    {"type": "file",  "name": "report.pdf", "path": "C:/Users/.../report.pdf"}
  ],
  "request_id": "a1b2c3d4"
}
```

**AAA `_on_text` 处理：**

AAA **不主动读取附件内容**，仅将附件路径信息传递给 LLM，由 LLM 自行决定是否通过 `file_read` 工具读取：

```python
def _on_text(self, data, dbp):
    text = data.get("content", "")
    attachments = data.get("attachments", [])
    
    # 仅构建附件上下文告知 LLM 路径，不提前读取内容
    ctx = self._gather_context(text, dbp, attachments)
    return {
        "_port": "prompt", "data_type": "prompt", "content": pt.build(ctx),
        "request_id": data.get("request_id"),
    }
```

`_gather_context` 中构建的 `attachment_context` 示例输出：
```
用户附带了以下附件（你可通过 file_read("路径") 读取内容）：
  1. 类型: image | 名称: 截图.png | 路径: C:/cache/.../截图.png
  2. 类型: file  | 名称: report.pdf | 路径: C:/cache/.../report.pdf

如需查看附件内容，请调用 file_read("路径")。
若你无法处理（如不支持该文件类型），请在回复中告知用户。
```

**GUI 侧附件缓存：**

发送前先将附件拷贝到 `gui/cache/attachments/` 目录，保证路径在对话期间稳定可用：

```python
ATTACHMENT_CACHE = GUI_DIR / "cache" / "attachments"

def send_text(self, text, attachments=None):
    ...
    if attachments:
        cached = []
        for att in attachments:
            dest = self._cache_attachment(att)
            cached.append({**att, "path": str(dest)})
        data["attachments"] = cached
    ...

def _cache_attachment(self, att):
    ATTACHMENT_CACHE.mkdir(parents=True, exist_ok=True)
    dest = ATTACHMENT_CACHE / f"{uuid.uuid4().hex[:8]}_{att['name']}"
    shutil.copy2(att["path"], str(dest))
    return dest
```

**支持的附件类型：**

| 类型 | GUI 操作 | 传输方式 |
|------|---------|----------|
| `image` | 文件选择器选图片；Ctrl+V 粘贴 | 缓存到本地 → 路径传给 AAA → 拼入 prompt → LLM 决定是否 `file_read` 或使用视觉能力 |
| `file` | 文件选择器选任意文件 | 同上 |
| `audio`（后续） | 录音按钮 | 预留 |

### 3.6 设计⑤ — ColorPickerPopup 重写为 FloatingPanel 子类

**当前状态：** `ColorPickerPopup` 是独立 `QDialog`，硬编码白色背景样式，与主 UI 风格割裂。

**改为继承 FloatingPanel：**

```python
class ColorPickerPopup(FloatingPanel):
    """颜色选择器弹出窗口 — 继承 FloatingPanel 统一风格"""

    color_selected = Signal(QColor)

    def __init__(self, current_color: QColor, parent=None):
        super().__init__(parent, title="选择颜色")
        self.setFixedSize(400, 360)

        self._current = QColor(current_color)
        self._result: QColor | None = None

        self._setup_content()

    def _setup_content(self):
        # self.content_layout 添加内容（色板网格 + 预览 + 确认按钮）
        ...
```

改动：
- 删除 `__init__` 中的 `setWindowFlags`、`setAttribute`、`setStyleSheet`（由父类提供）
- 内容添加到 `self.content_layout` 而非 `QVBoxLayout(self)`
- `get_color` 静态方法行为不变

### 3.7 最终 UI 结构

```
MainWindow (FramelessWindowHint)
  ├─ TitleBar (明亮自定义标题栏)
  │    ├─ 窗口标题
  │    ├─ [─] [□] [✕] 按钮
  │    └─ 拖拽移动 + 双击最大化
  └─ Content (现有内容区)
       ├─ Sidebar
       └─ QStackedWidget + StatusBar
            ├─ ChatPage
            │    ├─ 消息列表 (ScrollArea + ChatBubble)
            │    └─ ChatInput (WeChat 风格)
            │         ├─ QTextEdit (多行)
            │         ├─ AttachmentBar (附件预览)
            │         └─ 工具栏 (图片/文件/表情/发送)
            ├─ Live2DPage
            ├─ NodePage
            ├─ MCPPage
            └─ SettingsPage
                 └─ ColorPickerPopup (FloatingPanel 子类)

所有二级窗口 → FloatingPanel 子类
```

---

## 四、分阶段实施计划

> 状态: `[OK]` — 2026-07-25 实施完成

### Phase 0 — 组件适配（无功能变更）

1. ✅ **`gui/widgets/floating_panel.py`** — 从 BNOS 复制适配，去掉 i18n 依赖，配色改为明亮版
2. ✅ **`gui/widgets/title_bar.py`** — 同上，适配 TitleBar（明亮版），类名 `DarkTitleBar` → `TitleBar`
3. ✅ 验证：两个组件 `py_compile` 通过

### Phase 1 — 标题栏替换

4. ✅ **MainWindow 设置 `FramelessWindowHint` + `WA_TranslucentBackground` + 嵌入 `TitleBar`**
5. ✅ 标题栏信号连接（最小化/最大化/关闭 + `_toggle_maximized`）
6. ✅ 窗口 resize 边界处理（`mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent` 实现 6px 边缘 resize）
7. ✅ `py_compile` 通过

### Phase 2 — FloatingPanel 落地

8. ✅ **`gui/widgets/color_picker.py`** — 改为继承 `FloatingPanel`，内容 `self.content_layout`，浮动面板明亮风格
9. ✅ 删除独立 QDialog 的标志和样式（`setWindowTitle`/`setStyleSheet` 移除，由父类提供）

### Phase 3 — WeChat 发送框（已完成）

10. ✅ **`gui/widgets/chat_input.py`** — 新文件，完整实现（QTextEdit + 工具栏 + 附件预览）
11. ✅ **`gui/pages/chat_page.py`** — 用 `ChatInput` 替换 `QLineEdit + SendButton`
12. ✅ `ChatInput.send_requested` 信号连接到 `MessageManager.send_text`
13. ✅ **`gui/core/message_manager.py`** — `send_text` 支持 `attachments` 参数，写入 `gui_input.json`

### Phase 4 — AAA 附件处理（已完成）

14. ✅ **`main.py` `_gather_context`** — 解析 `attachments` 字段，构建 attachment_context 告知 LLM 附件路径信息，由 LLM 自行通过 `file_read` 决定是否读取
15. ✅ **`prompt.py`** — 模板添加 `{attachment_context}` 占位，`file_read` 工具描述强化
16. ✅ **`message_manager.py`** — `send_text` 支持 `attachments` 参数 + 附件拷贝到 `gui/cache/attachments/` 缓存

---

## 五、风险评估

| 风险 | 等级 | 应对 |
|------|------|------|
| `FramelessWindowHint` 下窗口无法 resize | 高 | 使用 TitleBar 顶部 6px resize 保留区域；四周边缘 resize 通过重写 `nativeEvent` 或使用 `WindowSystemMenuHint` |
| TitleBar 关闭信号直接连 `self.close` 无法保存配置 | 低 | 改连接 `closeEvent` 即可，`closeEvent` 中已有 `_save_window_geometry` |
| `FloatingPanel` 半透明背景与现有亮色主题不协调 | 低 | `FloatingPanel._container_style()` 可被子类覆盖；ColorPickerPopup 可覆盖为白色主题 |
| 附件传递大文件（>10MB）时文件 IO 阻塞 | 中 | 限制文件大小（默认 10MB），超过仅传文件名；图片 base64 编码在子线程执行 |
| Enter 发送与 IME 输入法冲突 | 低 | `eventFilter` 中检测 IME 状态：输入法未提交时不触发发送 |
| `FloatingPanel` 拖动时可能超出屏幕边界 | 低 | 在 `mouseMoveEvent` 中增加屏幕边界限制（可选） |

---

## 六、测试计划

### Phase 1 — 标题栏
1. 窗口可拖拽移动（标题栏区域）
2. 顶部 6px 边缘可 resize
3. 双击标题栏 → 最大化/还原
4. 最小化/关闭按钮正常工作
5. 最大化状态下窗口位置正确（不遮挡任务栏）
6. 窗口尺寸记忆（`_save_window_geometry`）正常

### Phase 2 — FloatingPanel
7. ColorPickerPopup 弹出为浮动面板样式
8. 可拖拽、可关闭、ESC 可关闭
9. 颜色选择功能正常

### Phase 3 — 发送框
10. Enter 发送消息，Shift+Enter 换行
11. 图片按钮 → 文件选择器 → 显示缩略图预览
12. 文件按钮 → 文件选择器 → 显示文件名预览
13. 附件删除按钮正常工作
14. Ctrl+V 粘贴图片（来自剪贴板）→ 自动添加到附件
15. 纯文字发送（无附件）与传统行为一致
16. 发送后输入框清空、附件清空
17. 发送状态锁启用时输入框禁用

### 回归
- 现有聊天功能（发送/接收/气泡）不受影响
- Live2D 预览页不受影响
- 设置页、节点页、MCP 页不受影响

---

## 七、影响范围

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `gui/widgets/floating_panel.py` | **新建** | 从 BNOS 适配 FloatingPanel |
| `gui/widgets/title_bar.py` | **新建** | 从 BNOS 适配 TitleBar（明亮版） |
| `gui/widgets/chat_input.py` | **新建** | WeChat 风格多功能输入栏 |
| `gui/widgets/color_picker.py` | **修改** | 改为继承 FloatingPanel |
| `gui/main_window.py` | **修改** | 设 FramelessWindowHint + 嵌入 TitleBar + resize 边界处理 |
| `gui/pages/chat_page.py` | **修改** | 用 ChatInput 替换 QLineEdit + 发送按钮 |
| `gui/core/message_manager.py` | **修改** | `send_text` 支持 `attachments` 参数 |
| `gui/core/config.py` | 不改 | 仅 theme 相关，无需新配置项 |
| `gui/core/event_bus.py` | 不改 | 主题变更事件流程不变 |
| `gui/core/state.py` | 不改 | AppState 不涉及 |
| `gui/widgets/sidebar.py` | 不改 | 侧边栏不变 |
| `gui/widgets/status_bar.py` | 不改 | 状态栏不变（可后续跟随主题） |
| AAA `main.py` | **可选** | 附件处理（Phase 4） |

**不涉及**：Live2D 悬浮窗、节点文件协议、listener.py、JS 文件、数据库。
