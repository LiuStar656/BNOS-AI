# 06 — Markdown 渲染、主题优化与页面动画

> 日期：2026-07-25 | 涉及文件：14 | 变更类型：UI 升级

---

## 一、升级概述

本次提交完成了 GUI 多项核心功能升级：

1. **Markdown 渲染引擎**：集成 mistune + Pygments，实现代码高亮
2. **聊天气泡重构**：改用 QTextBrowser 支持富文本显示
3. **8 套主题预设**：支持一键切换主题风格
4. **页面切换动画**：滑动过渡效果
5. **Toast 通知系统**：独立弹窗通知组件
6. **配置持久化**：主题预设存储到 gui_config.json

---

## 二、核心实现

### 2.1 Markdown 渲染器

```python
class MarkdownRenderer:
    """基于 mistune + Pygments 的 Markdown 渲染引擎"""

    _markdown: mistune.HTMLRenderer | None = None
    _highlight: HighlightMixin | None = None
```

**渲染流程：**

```
原始 Markdown 文本
    ↓ mistune.parse()
AST（抽象语法树）
    ↓ mistune.render()
HTML（包含 <pre><code> 等标签）
    ↓ Pygments.highlight()
带语法高亮的 HTML
    ↓ QTextBrowser.setHtml()
聊天气泡显示
```

支持的代码语言：Python、JavaScript、TypeScript、JSON、YAML、Shell、C++、Java 等 20+ 语言。

### 2.2 主题预设系统

在 `gui/core/config.py` 中新增 8 套主题预设：

| 主题名 | 风格 | 主色 |
|--------|------|------|
| `ubuntu` | Ubuntu 橙色系 | #E95420 |
| `blue` | 经典蓝色 | #1a73e8 |
| `green` | 清新绿色 | #2e7d32 |
| `purple` | 优雅紫色 | #7b1fa2 |
| `dark` | 深色模式 | #333333 |
| `warm` | 暖色调 | #bf360c |
| `ocean` | 海洋蓝 | #00695c |
| `gray` | 简约灰 | #616161 |

一键切换通过 `theme.py` 的 `get_light_qss()` 动态注入颜色值。

### 2.3 聊天气泡重构

```python
class ChatBubble(QWidget):
    """自适应宽度聊天气泡 — 使用 QTextBrowser 渲染 Markdown"""

    # 用户气泡: 右对齐, 绿色背景, 白色文字
    # AI 气泡: 左对齐, 白色背景, 深色文字
    # 系统消息: 居中, 灰色圆角背景
```

用 `QTextBrowser` 替代原 `QLabel`，支持富文本和 Markdown 渲染。

### 2.4 Toast 通知系统

```python
class Toast(QWidget):
    """屏幕角落 Toast 通知，支持淡入淡出动画、自动关闭、悬停保持"""

    @classmethod
    def info(cls, message, timeout=3000)
    @classmethod
    def warning(cls, message, timeout=4000)
    @classmethod
    def error(cls, message, timeout=5000)
```

**特性：**
- 四角定位（默认右下角）
- 淡入淡出动画（QPropertyAnimation）
- 鼠标悬停保持（不自动关闭）
- 主题颜色跟随

### 2.5 页面切换动画

```python
class AnimatedStackedWidget(QStackedWidget):
    """带滑动过渡动画的堆叠窗口"""

    # 使用 QPropertyAnimation 实现
    # 水平滑动，时长 200ms，QEasingCurve.OutCubic
```

---

## 三、影响范围

| 文件 | 改动 |
|------|------|
| `gui/widgets/markdown_renderer.py` | **新增**：Markdown 渲染引擎（102 行） |
| `gui/widgets/toast.py` | **新增**：Toast 通知组件（200 行） |
| `gui/core/config.py` | 新增主题预设系统（+248 行） |
| `gui/widgets/chat_bubble.py` | 重构为 QTextBrowser 渲染（+174 行） |
| `gui/widgets/chat_input.py` | 样式统一优化（+26 行） |
| `gui/pages/chat_page.py` | 集成页面动画 |
| `gui/main_window.py` | 集成 AnimatedStackedWidget |
| `gui/resources/theme.py` | 动态主题色注入 |
| `gui/pages/settings_page.py` | 主题选择 UI |
| `gui_config.json` | 主题预设持久化 |

---

## 四、设计决策

| 决策 | 理由 |
|------|------|
| mistune + Pygments | mistune 轻量快速（纯 Python），Pygments 代码高亮最成熟 |
| QTextBrowser 而非 QWebEngineView | QTextBrowser 轻量，无需额外进程，渲染简单 Markdown 足够 |
| 8 套预设 + 自定义 | 预设即开即用，自定义满足个性化需求 |
| Toast 基于 QWidget 而非 QDialog | QWidget 可无父窗口独立定位，适合屏幕角落弹窗 |

---

## 五、验证方法

1. 发送包含代码块的消息，验证代码高亮正确
2. 在设置中切换主题，验证所有页面颜色实时变化
3. 切换标签页，验证滑动动画流畅
4. 发送消息后，验证 Toast 通知弹出并自动消失
5. 悬停在 Toast 上，验证不会自动关闭

---

## 六、修改文件清单

| 文件 | 改动 |
|------|------|
| `gui/widgets/markdown_renderer.py` | 新增 |
| `gui/widgets/toast.py` | 新增 |
| `gui/widgets/chat_bubble.py` | 重构 |
| `gui/widgets/chat_input.py` | 样式优化 |
| `gui/core/config.py` | 主题预设 |
| `gui/pages/chat_page.py` | 动画集成 |
| `gui/main_window.py` | AnimatedStackedWidget |
| `gui/pages/settings_page.py` | 主题选择 |
| `gui/resources/theme.py` | 动态颜色注入 |
| `gui_config.json` | 持久化配置 |
| 设计文档 | 更新 UI 设计文档 |

---

**最后更新**：2026-07-25
