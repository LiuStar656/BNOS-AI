# 01 — Live2D 预览页 Bug 修复

> 日期：2026-07-25 | 涉及文件：2 | 变更类型：修复

---

## 一、Bug 1：`AttributeError: 'builtin_function_or_method' object has no attribute 'connect'`

### 问题描述

GUI 启动时崩溃，终端输出：

```
File "gui/pages/live2d_page.py", line 181, in __init__
  self._web_view.page().javaScriptConsoleMessage.connect(self._on_js_console)
AttributeError: 'builtin_function_or_method' object has no attribute 'connect'
```

### 根因分析

`javaScriptConsoleMessage` 是 `QWebEnginePage` 的**虚方法**（virtual method），不是 Qt Signal。PySide6 不允许对虚方法调用 `.connect()`。该方法是 QWebEnginePage 在 JS 产生控制台输出时自动调用的回调，需要在子类中重写（override）来捕获，而非通过信号连接。

### 修改方案

1. 在文件顶部已定义了 `_Live2DWebPage(QWebEnginePage)` 子类，但从未被使用
2. 实例化 `_Live2DWebPage` 并通过 `self._web_view.setPage()` 替换默认页面
3. 连接自定义 `page_console` Signal 到处理器

**代码对比：**

```python
# ❌ 修改前 — 直接对虚方法调用 .connect()
self._web_view = QWebEngineView()
# ... 设置 settings ...
self._web_view.page().javaScriptConsoleMessage.connect(self._on_js_console)

# ✅ 修改后 — 使用自定义 WebPage 子类的 Signal
self._web_view = QWebEngineView()
self._web_page = _Live2DWebPage()
self._web_view.setPage(self._web_page)
self._web_page.page_console.connect(self._on_js_console)
# ... 设置 settings ...
```

### `_Live2DWebPage` 类设计

```python
class _Live2DWebPage(QWebEnginePage):
    """自定义 WebPage，捕获 JS 控制台输出到 Python 终端"""
    page_console = Signal(object, str, int, str)  # level, msg, line, src

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        try:
            self.page_console.emit(level, message, lineNumber, sourceID)
        except Exception:
            pass
        super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)
```

---

## 二、Bug 2：`ImportError: cannot import name 'QWebEnginePage'`

### 问题描述

```
from PySide6.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
ImportError: cannot import name 'QWebEnginePage' from 'PySide6.QtWebEngineWidgets'
```

### 根因分析

在 PySide6 中，`QWebEnginePage` 位于 `PySide6.QtWebEngineCore` 模块，而非 `PySide6.QtWebEngineWidgets`。`QtWebEngineWidgets` 只包含 `QWebEngineView`。

### 修改方案

```python
# ❌ 修改前
from PySide6.QtWebEngineWidgets import QWebEngineView, QWebEnginePage

# ✅ 修改后
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
```

---

## 三、Bug 3：Live2D 预览页 canvas 尺寸为 0x0 导致模型不可见

### 问题描述

模型加载成功但不可见，终端输出：

```
[JS-INFO] [Live2D] 模型加载成功: /2D/feiniu.model3.json
[JS-INFO] [Live2D] 画布尺寸: 0 x 0
```

用户必须在预览页右键 → 重新加载才能正常显示模型。

### 根因分析

Live2D 预览页的 `QWebEngineView` 位于 `QStackedWidget` 中。默认显示聊天页，Live2D 页处于隐藏状态。隐藏的控件尺寸为 0，导致 `initRenderer()` 中 `window.innerWidth` 和 `window.innerHeight` 均为 0，PIXI 创建了 0x0 的 WebGL 上下文。

后续即使 `resizeRenderer()` 调整 canvas 尺寸，已初始化的 WebGL 上下文也无法恢复正常渲染。

### 修改方案

采用 **"后台预加载 + 首次显示时重新加载"** 策略：

1. **后台预加载**：`__init__` 中保留 1.5 秒定时器导航页面（同时让服务器有时间启动）
2. **`showEvent` 重载**：首次切换到 Live2D 标签页时，调用 `web_view.reload()` 重新加载页面
3. **重新加载后**：`initRenderer()` 以正确的 WebView 尺寸运行，canvas 尺寸正常

```python
# __init__ 中
QTimer.singleShot(1500, self._load_preview)  # 后台预加载

def showEvent(self, event):
    """页面变为可见时，若 canvas 是 0x0（后台加载导致），重新加载页面。"""
    super().showEvent(event)
    if self._preview_loaded and not self._page_shown:
        self._page_shown = True
        print("[Live2D] 页面首次可见，重新加载渲染器...")
        QTimer.singleShot(100, lambda: self._web_view.reload())
```

同时，在 `renderer.js` 中添加 `resizeRenderer()` 作为备用：

```javascript
function resizeRenderer() {
    if (!app) return;
    const W = window.innerWidth;
    const H = window.innerHeight;
    if (W === 0 || H === 0) return;
    app.renderer.resize(W, H);
    updateModelTransform();
    console.log('[Live2D] 渲染器已调整尺寸:', W, 'x', H);
}
```

### 备选方案（未采用）

- **延迟加载**：不在 `__init__` 中导航，仅在 `showEvent` 时首次导航 → 用户切换到标签页时需等待，体验差
- **仅 `resizeRenderer()`**：PIXI 在 0x0 WebGL 上下文初始化后无法通过 resize 恢复，必须 reload

---

## 四、验证方法

1. 启动程序，GUI 不应崩溃
2. 切换至 Live2D 标签页，模型应正常显示（canvas 大小正常）
3. 在模型列表中切换不同模型，预览应正常更新
4. 右键重新加载页面，模型仍应正常显示
5. 切换到其他标签页再切回，模型应保持可见

---

## 五、修改文件清单

| 文件 | 改动 |
|------|------|
| `gui/pages/live2d_page.py` | 修复 `AttributeError`（改用 `_Live2DWebPage` 子类 + Signal）、修复 `ImportError`（`QWebEnginePage` 从 `QtWebEngineCore` 导入）、新增 `showEvent` 重新加载逻辑 |
| `gui/live2d/renderer.js` | 新增 `resizeRenderer()` 函数 |

## 六、文件变更统计

| 类型 | 数量 |
|------|:----:|
| 修改文件 | 2 |
| **总计** | **2** |

---

**最后更新**：2026-07-25
