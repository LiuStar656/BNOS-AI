# BNOS AI GUI 设计系统改造方案

> **参考源**：`references/hermes-agent-main/apps/desktop/DESIGN.md`
> **目标**：借鉴 Hermes Desktop 的设计系统理念，建立 BNOS AI 的标准化 UI 框架

---

## 目录

- [一、现状诊断](#一现状诊断)
- [二、改造目标](#二改造目标)
- [三、改造方案](#三改造方案)
- [四、实施路线图](#四实施路线图)
- [五、与 Hermes 的关键差异](#五与-hermes-的关键差异)
- [六、验收标准](#六验收标准)
- [七、验收方法](#七验收方法)
  - [7.1 验收环境与前置条件](#71-验收环境与前置条件)
  - [7.2 功能验收用例](#72-功能验收用例)
  - [7.3 边界与异常验收](#73-边界与异常验收)
  - [7.4 验收结论判定标准](#74-验收结论判定标准)

---

## 一、现状诊断

### 1.1 当前架构

```
gui/
├── main.py              # 入口
├── main_window.py       # 主窗口（QMainWindow + QStackedWidget）
├── core/                # 核心逻辑
│   ├── config.py        # AppConfig（颜色配置）
│   ├── state.py         # AppState（全局状态）
│   ├── event_bus.py     # 事件总线
│   └── message_manager.py
├── widgets/             # 组件
│   ├── sidebar.py       # 侧边栏
│   ├── chat_bubble.py   # 聊天气泡
│   ├── chat_input.py    # 输入栏
│   ├── floating_panel.py # 浮动面板
│   └── ...
├── pages/               # 页面
│   ├── chat_page.py     # 聊天页
│   ├── live2d_page.py   # Live2D 页
│   ├── mcp_page.py      # MCP 管理页
│   └── settings_panel.py
└── resources/
    └── theme.py         # QSS 主题
```

### 1.2 核心问题

| 问题 | 表现 | 影响 |
|------|------|------|
| **无设计 Token 体系** | 颜色散落在 QSS 字符串和 AppConfig 字典中 | 主题切换困难，颜色不一致 |
| **组件样式硬编码** | 按钮、卡片样式在各组件中独立定义 | 重复代码，维护成本高 |
| **反馈状态缺失** | 错误、空状态、加载状态无统一组件 | 用户体验不连贯 |
| **浮动面板行为不统一** | Settings、Node、Archive 使用不同的打开逻辑 | 增加开发和使用成本 |
| **动效参数分散** | 每个动画独立设置 duration/easing | 视觉节奏不统一 |

---

## 二、改造目标

### 2.1 设计原则（借鉴 Hermes DESIGN.md）

1. **Token 优先**：所有颜色、间距、圆角、阴影都通过 Design Token 定义
2. **单一原语**：每种 UI 模式只有一个组件实现（Button、Card、Input）
3. **反馈先行**：组件立即响应交互，持久化延后
4. **层次清晰**：Page / Overlay / Dialog 三层明确的导航模型
5. **动效一致**：统一的缓动曲线和时长，避免视觉噪音

### 2.2 目标架构

```
gui/
├── core/
│   ├── design_tokens.py    # 🆕 设计 Token 集中定义
│   ├── theme.py            # 🆕 主题管理器（基于 Token）
│   └── ...
├── components/             # 🆕 标准化组件库
│   ├── button.py           # 统一按钮（variant + size）
│   ├── card.py             # 卡片容器
│   ├── input.py            # 输入框
│   ├── search_field.py     # 搜索框
│   ├── segmented_control.py # 分段控件
│   ├── loader.py           # 加载状态
│   ├── error_state.py      # 错误状态
│   ├── empty_state.py      # 空状态
│   └── toast.py            # 通知
├── widgets/               # 业务组件（使用标准化原语）
│   ├── sidebar.py
│   ├── chat_bubble.py      # 基于 card.py
│   ├── chat_input.py       # 基于 input.py + button.py
│   └── floating_panel.py   # 标准化为 Overlay
├── dialogs/                # 覆盖层对话框
│   ├── overlay.py          # 🆕 统一 Overlay 基类
│   ├── settings_overlay.py
│   └── node_overlay.py
└── pages/                 # 页面（直接使用原语）
    ├── chat_page.py
    └── ...
```

---

## 三、改造方案

### 3.1 第一步：建立 Design Token 体系

> **参考源**：Hermes `DESIGN.md` → Stroke & color tokens, Layout tokens, Motion

#### 3.1.1 新增 `gui/core/design_tokens.py`

```python
"""设计 Token 集中管理 — 借鉴 Hermes DESIGN.md"""

from dataclasses import dataclass
from typing import Dict, Tuple

@dataclass(frozen=True)
class ColorTokens:
    """颜色 Token — 对应 Hermes 的 --ui-* tokens"""
    
    # 文本层级
    text_primary: str = "#1F2328"      # 主文本
    text_secondary: str = "#656D76"    # 次文本
    text_tertiary: str = "#8F959E"     # 辅助文本
    text_inverse: str = "#FFFFFF"     # 反色文本
    
    # 背景层级
    bg_primary: str = "#FFFFFF"       # 主背景
    bg_secondary: str = "#F6F8FA"     # 次背景
    bg_tertiary: str = "#E3E8EF"      # 第三背景
    bg_hover: str = "rgba(0,0,0,0.06)" # 悬停背景
    
    # 强调色
    theme_primary: str = "#2563EB"    # 主题色
    theme_primary_hover: str = "#1D4ED8"
    theme_danger: str = "#D1242F"     # 危险色
    theme_success: str = "#18794E"   # 成功色
    theme_warning: str = "#B06000"    # 警告色
    
    # 语义色
    sidebar_bg: str = "#F6F8FA"
    sidebar_active: str = "#E3E8EF"
    chat_user_bg: str = "#E6F4EA"     # 用户气泡背景
    chat_ai_bg: str = "#FFFFFF"      # AI 气泡背景
    
    # 边框
    border_primary: str = "#D0D7DE"
    border_focus: str = "#2563EB"


@dataclass(frozen=True)
class SpacingTokens:
    """间距 Token — 对应 Hermes 的 gutters / layout"""
    
    xs: int = 4
    sm: int = 8
    md: int = 16
    lg: int = 24
    xl: int = 32
    xxl: int = 48
    
    # 页面内边距
    page_inset_x: int = 24
    page_inset_y: int = 16
    
    # 组件间距
    component_gap: int = 12
    tight_gap: int = 4


@dataclass(frozen=True)
class RadiusTokens:
    """圆角 Token"""
    
    sm: int = 4      # 小组件（按钮、输入框）
    md: int = 8      # 中组件（卡片、面板）
    lg: int = 12     # 大组件（对话框、侧边栏）
    pill: int = 999  # 胶囊形


@dataclass(frozen=True)
class ShadowTokens:
    """阴影 Token — 对应 Hermes 的 shadow-nous"""
    
    sm: str = "0 1px 2px rgba(0,0,0,0.06)"
    md: str = "0 2px 8px rgba(0,0,0,0.08)"
    lg: str = "0 8px 32px rgba(0,0,0,0.12)"   # Overlay 阴影
    focus: str = "0 0 0 2px rgba(37,99,235,0.3)"


@dataclass(frozen=True)
class MotionTokens:
    """动效 Token — 对应 Hermes 的 Motion 章节"""
    
    # 时长（毫秒）
    duration_instant: int = 50    # 即时反馈
    duration_fast: int = 100      # 功能过渡
    duration_normal: int = 200    # 页面切换
    duration_slow: int = 300      # 强调性动效
    
    # 缓动曲线
    easing_standard: str = "OutCubic"    # 标准
    easing_in: str = "InCubic"          # 进入
    easing_out: str = "OutCubic"         # 退出
    easing_in_out: str = "InOutCubic"    # 进出


@dataclass
class DesignTokens:
    """完整设计 Token 集合"""
    colors: ColorTokens = ColorTokens()
    spacing: SpacingTokens = SpacingTokens()
    radius: RadiusTokens = RadiusTokens()
    shadow: ShadowTokens = ShadowTokens()
    motion: MotionTokens = MotionTokens()
    
    @classmethod
    def light(cls) -> "DesignTokens":
        """亮色主题 Token"""
        return cls()
    
    @classmethod
    def dark(cls) -> "DesignTokens":
        """暗色主题 Token（后续实现）"""
        return cls()
```

#### 3.1.2 新增 `gui/core/theme_manager.py`

```python
"""主题管理器 — 基于 Design Token 生成 QSS"""

from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication

from gui.core.design_tokens import DesignTokens


class ThemeManager:
    """主题管理器 — 统一管理主题切换和样式生成"""
    
    _instance: "ThemeManager | None" = None
    
    def __init__(self):
        self._tokens = DesignTokens.light()
        self._listeners: list[callable] = []
    
    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @property
    def tokens(self) -> DesignTokens:
        return self._tokens
    
    def get_qss(self) -> str:
        """基于 Token 生成全局 QSS"""
        c = self._tokens.colors
        s = self._tokens.spacing
        r = self._tokens.radius
        
        return f"""
        QWidget {{
            background-color: {c.bg_primary};
            color: {c.text_primary};
            font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;
            font-size: 13px;
        }}
        
        QPushButton {{
            border: none;
            border-radius: {r.sm}px;
            padding: {s.sm}px {s.md}px;
            background-color: {c.theme_primary};
            color: {c.text_inverse};
        }}
        QPushButton:hover {{
            background-color: {c.theme_primary_hover};
        }}
        QPushButton:pressed {{
            background-color: {c.theme_primary};
        }}
        
        /* ... 更多样式 ... */
        """
    
    def get_component_qss(self, component_type: str) -> str:
        """获取特定组件的 QSS"""
        c = self._tokens.colors
        r = self._tokens.radius
        s = self._tokens.spacing
        
        templates = {
            "card": f"""
                QCard {{
                    background-color: {c.bg_primary};
                    border: 1px solid {c.border_primary};
                    border-radius: {r.md}px;
                    padding: {s.md}px;
                }}
            """,
            "input": f"""
                QLineEdit {{
                    background-color: {c.bg_secondary};
                    border: 1px solid {c.border_primary};
                    border-radius: {r.sm}px;
                    padding: {s.sm}px {s.md}px;
                    selection-background-color: {c.theme_primary};
                }}
                QLineEdit:focus {{
                    border-color: {c.border_focus};
                }}
            """,
            "sidebar": f"""
                QSidebar {{
                    background-color: {c.sidebar_bg};
                    border-right: 1px solid {c.border_primary};
                }}
            """,
        }
        return templates.get(component_type, "")
    
    def apply_to_app(self, app: QApplication):
        """将主题应用到应用"""
        app.setStyleSheet(self.get_qss())
        self._apply_palette(app)
    
    def _apply_palette(self, app: QApplication):
        """设置 QPalette"""
        c = self._tokens.colors
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(c.bg_primary))
        palette.setColor(QPalette.ColorRole.Base, QColor(c.bg_primary))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c.bg_secondary))
        palette.setColor(QPalette.ColorRole.Text, QColor(c.text_primary))
        palette.setColor(QPalette.ColorRole.Button, QColor(c.bg_secondary))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(c.text_primary))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(c.theme_primary))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(c.text_inverse))
        app.setPalette(palette)
    
    def switch_theme(self, theme: str = "light"):
        """切换主题"""
        if theme == "light":
            self._tokens = DesignTokens.light()
        elif theme == "dark":
            self._tokens = DesignTokens.dark()
        
        # 通知所有监听者
        for listener in self._listeners:
            listener(self._tokens)
    
    def add_listener(self, callback: callable):
        """添加主题变更监听"""
        self._listeners.append(callback)
```

---

### 3.2 第二步：标准化组件库

#### 3.2.1 新增 `gui/components/button.py`

> **参考源**：Hermes `DESIGN.md` → Buttons — one component

```python
"""统一按钮组件 — 借鉴 Hermes Button 设计"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from PySide6.QtWidgets import QPushButton, QWidget

from gui.core.theme_manager import ThemeManager


class StyledButton(QPushButton):
    """标准化按钮 — 支持多种 variant 和 size"""
    
    # 按钮变体
    VARIANTS = {
        "default": "主操作按钮",
        "secondary": "次要操作按钮",
        "outline": "描边按钮",
        "ghost": "透明幽灵按钮",
        "destructive": "危险操作按钮",
        "link": "链接样式按钮",
        "icon": "图标按钮",
    }
    
    # 按钮尺寸
    SIZES = {
        "xs": (24, 32, 12),    # (高度, 水平内边距, 字体大小)
        "sm": (32, 16, 13),
        "md": (40, 24, 14),
        "lg": (48, 32, 16),
    }
    
    def __init__(self, text: str = "", parent: QWidget = None,
                 variant: str = "default", size: str = "md",
                 icon: str = ""):
        super().__init__(text, parent)
        self._variant = variant
        self._size = size
        self._icon = icon
        self._hover_anim = None
        
        self._apply_style()
        self._apply_size()
        self._setup_animation()
    
    def _apply_style(self):
        """根据 variant 应用样式"""
        tm = ThemeManager.instance()
        c = tm.tokens.colors
        r = tm.tokens.radius
        s = tm.tokens.spacing
        
        variant_styles = {
            "default": f"""
                QPushButton {{
                    background-color: {c.theme_primary};
                    color: {c.text_inverse};
                    border: none;
                    border-radius: {r.sm}px;
                }}
                QPushButton:hover {{
                    background-color: {c.theme_primary_hover};
                }}
                QPushButton:pressed {{
                    background-color: {c.theme_primary};
                }}
            """,
            "secondary": f"""
                QPushButton {{
                    background-color: {c.bg_tertiary};
                    color: {c.text_primary};
                    border: none;
                    border-radius: {r.sm}px;
                }}
                QPushButton:hover {{
                    background-color: {c.bg_hover};
                }}
            """,
            "outline": f"""
                QPushButton {{
                    background-color: transparent;
                    color: {c.text_primary};
                    border: 1px solid {c.border_primary};
                    border-radius: {r.sm}px;
                }}
                QPushButton:hover {{
                    border-color: {c.theme_primary};
                    color: {c.theme_primary};
                }}
            """,
            "ghost": f"""
                QPushButton {{
                    background-color: transparent;
                    color: {c.text_primary};
                    border: none;
                    border-radius: {r.sm}px;
                }}
                QPushButton:hover {{
                    background-color: {c.bg_hover};
                }}
            """,
            "destructive": f"""
                QPushButton {{
                    background-color: {c.theme_danger};
                    color: {c.text_inverse};
                    border: none;
                    border-radius: {r.sm}px;
                }}
                QPushButton:hover {{
                    background-color: #B4202A;
                }}
            """,
            "link": f"""
                QPushButton {{
                    background-color: transparent;
                    color: {c.theme_primary};
                    border: none;
                    text-decoration: underline;
                }}
                QPushButton:hover {{
                    color: {c.theme_primary_hover};
                }}
            """,
        }
        
        style = variant_styles.get(self._variant, variant_styles["default"])
        self.setStyleSheet(style)
    
    def _apply_size(self):
        """根据 size 应用尺寸"""
        height, padding, font_size = self.SIZES.get(self._size, self.SIZES["md"])
        self.setFixedHeight(height)
        self.setStyleSheet(self.styleSheet() + f"""
            QPushButton {{
                padding: 0 {padding}px;
                font-size: {font_size}px;
            }}
        """)
    
    def _setup_animation(self):
        """设置按压动效"""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    
    def set_variant(self, variant: str):
        """切换按钮变体"""
        self._variant = variant
        self._apply_style()
    
    def set_size(self, size: str):
        """切换按钮尺寸"""
        self._size = size
        self._apply_size()
```

#### 3.2.2 新增 `gui/components/card.py`

```python
"""卡片容器组件 — 借鉴 Hermes Widget Shell 设计"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QWidget

from gui.core.theme_manager import ThemeManager


class StyledCard(QFrame):
    """标准化卡片容器"""
    
    def __init__(self, parent: QWidget = None, 
                 title: str = "", 
                 bordered: bool = True):
        super().__init__(parent)
        self._title = title
        self._bordered = bordered
        
        self.setObjectName("StyledCard")
        self._apply_style()
        self._setup_layout()
    
    def _apply_style(self):
        """应用卡片样式"""
        tm = ThemeManager.instance()
        c = tm.tokens.colors
        r = tm.tokens.radius
        s = tm.tokens.spacing
        
        style = f"""
            QFrame#StyledCard {{
                background-color: {c.bg_primary};
                border-radius: {r.md}px;
            }}
        """
        if self._bordered:
            style += f"""
                QFrame#StyledCard {{
                    border: 1px solid {c.border_primary};
                }}
            """
        self.setStyleSheet(style)
    
    def _setup_layout(self):
        """设置卡片内部布局"""
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(12)
        
        # 标题区域
        if self._title:
            self._title_label = QLabel(self._title)
            self._title_label.setStyleSheet("font-weight: 600; font-size: 14px;")
            self._layout.addWidget(self._title_label)
    
    def set_content(self, widget: QWidget):
        """设置卡片内容"""
        self._layout.addWidget(widget)
    
    def set_header_widget(self, widget: QWidget):
        """设置自定义头部（替换标题）"""
        if hasattr(self, '_title_label'):
            self._title_label.setParent(None)
        self._layout.addWidget(widget)
```

#### 3.2.3 新增 `gui/components/loader.py` / `error_state.py` / `empty_state.py`

```python
"""反馈状态组件 — 借鉴 Hermes Loader / ErrorState / EmptyState"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QRadialGradient
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout

from gui.core.theme_manager import ThemeManager
from gui.components.button import StyledButton


class StyledLoader(QWidget):
    """加载状态组件"""
    
    def __init__(self, message: str = "加载中...", parent: QWidget = None):
        super().__init__(parent)
        self._message = message
        self._rotation = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)
    
    def start(self):
        """开始加载动画"""
        self._timer.start(30)
        self.show()
    
    def stop(self):
        """停止加载动画"""
        self._timer.stop()
        self.hide()
    
    def _rotate(self):
        """旋转动画"""
        self._rotation = (self._rotation + 6) % 360
        self.update()
    
    def paintEvent(self, event):
        """绘制加载动画"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        c = ThemeManager.instance().tokens.colors
        
        # 绘制圆环
        pen = QPen(QColor(c.theme_primary), 3)
        painter.setPen(pen)
        
        rect = self.rect().adjusted(10, 10, -10, -10)
        span = 30 * 16  # 30 degrees in 1/16 degree
        
        painter.drawArc(rect, self._rotation * 16, span)
        
        # 绘制文字
        painter.setPen(QColor(c.text_secondary))
        font = painter.font()
        font.setPointSize(11)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._message)


class StyledErrorState(QWidget):
    """错误状态组件"""
    
    def __init__(self, title: str, description: str = "", 
                 retry_text: str = "重试", parent: QWidget = None):
        super().__init__(parent)
        self._title = title
        self._description = description
        self._retry_text = retry_text
        self._retry_callback = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        """设置错误状态 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        c = ThemeManager.instance().tokens.colors
        
        # 错误图标
        self._icon_label = QLabel("⚠")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setStyleSheet(
            f"font-size: 48px; color: {c.theme_danger};"
        )
        layout.addWidget(self._icon_label)
        
        # 标题
        self._title_label = QLabel(self._title)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setStyleSheet(
            f"font-size: 16px; font-weight: 600; color: {c.text_primary};"
        )
        layout.addWidget(self._title_label)
        
        # 描述
        if self._description:
            self._desc_label = QLabel(self._description)
            self._desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._desc_label.setWordWrap(True)
            self._desc_label.setStyleSheet(
                f"color: {c.text_secondary}; max-width: 320px;"
            )
            layout.addWidget(self._desc_label)
        
        # 重试按钮
        self._retry_btn = StyledButton(
            self._retry_text, 
            variant="secondary",
            size="sm"
        )
        self._retry_btn.clicked.connect(self._on_retry)
        layout.addWidget(self._retry_btn, alignment=Qt.AlignmentFlag.AlignCenter)
    
    def set_retry_callback(self, callback):
        """设置重试回调"""
        self._retry_callback = callback
    
    def _on_retry(self):
        if self._retry_callback:
            self._retry_callback()


class StyledEmptyState(QWidget):
    """空状态组件"""
    
    def __init__(self, icon_type: str = "no_data", 
                 title: str = "暂无数据",
                 description: str = "当前没有可显示的内容",
                 action_text: str = "",
                 action_callback: callable = None,
                 parent: QWidget = None):
        super().__init__(parent)
        self._icon_type = icon_type
        self._title = title
        self._description = description
        self._action_text = action_text
        self._action_callback = action_callback
        
        self._setup_ui()
    
    def _setup_ui(self):
        """设置空状态 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        c = ThemeManager.instance().tokens.colors
        
        # 图标映射
        icons = {
            "no_data": "📭",
            "no_results": "🔍",
            "offline": "📡",
            "disabled": "🚫",
            "empty_chat": "💬",
        }
        
        icon_char = icons.get(self._icon_type, "📭")
        
        self._icon_label = QLabel(icon_char)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setStyleSheet("font-size: 48px;")
        layout.addWidget(self._icon_label)
        
        self._title_label = QLabel(self._title)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setStyleSheet(
            f"font-size: 14px; color: {c.text_primary};"
        )
        layout.addWidget(self._title_label)
        
        self._desc_label = QLabel(self._description)
        self._desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet(
            f"color: {c.text_secondary};"
        )
        layout.addWidget(self._desc_label)
        
        if self._action_text and self._action_callback:
            self._action_btn = StyledButton(
                self._action_text,
                variant="default",
                size="sm"
            )
            self._action_btn.clicked.connect(self._action_callback)
            layout.addWidget(self._action_btn, alignment=Qt.AlignmentFlag.AlignCenter)
```

---

### 3.3 第三步：浮动面板标准化

#### 3.3.1 新增 `gui/dialogs/overlay.py`

> **参考源**：Hermes DESIGN.md → Route overlays are short tasks

```python
"""覆盖层基类 — 统一管理弹出式面板的行为"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QPoint, QSize
from PySide6.QtGui import QMouseEvent, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
)

from gui.core.theme_manager import ThemeManager
from gui.components.button import StyledButton


class BaseOverlay(QWidget):
    """统一覆盖层基类 — 借鉴 Hermes OverlayView 设计"""
    
    OVERLAY_WIDTH = 400
    OVERLAY_ANIM_DURATION = 200
    
    def __init__(self, parent: QWidget = None, 
                 title: str = "",
                 overlay_width: int | None = None):
        super().__init__(parent)
        self._title = title
        self._overlay_width = overlay_width or self.OVERLAY_WIDTH
        self._is_open = False
        self._content_widget: QWidget | None = None
        
        self._setup_ui()
        self._setup_animations()
    
    def _setup_ui(self):
        """设置覆盖层 UI"""
        tm = ThemeManager.instance()
        c = tm.tokens.colors
        r = tm.tokens.radius
        s = tm.tokens.spacing
        
        self.setObjectName("BaseOverlay")
        self.setFixedWidth(self._overlay_width)
        self.setStyleSheet(f"""
            QWidget#BaseOverlay {{
                background-color: {c.bg_primary};
                border-radius: {r.lg}px;
                border: 1px solid {c.border_primary};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 标题栏
        self._title_bar = self._create_title_bar()
        layout.addWidget(self._title_bar)
        
        # 分隔线
        self._divider = QFrame()
        self._divider.setFrameShape(QFrame.Shape.HLine)
        self._divider.setStyleSheet(f"""
            QFrame {{
                color: {c.border_primary};
                background-color: {c.border_primary};
                max-height: 1px;
            }}
        """)
        layout.addWidget(self._divider)
        
        # 内容区域
        self._content_area = QWidget()
        self._content_layout = QVBoxLayout(self._content_area)
        self._content_layout.setContentsMargins(s.md, s.md, s.md, s.md)
        layout.addWidget(self._content_area, 1)
    
    def _create_title_bar(self) -> QWidget:
        """创建标题栏"""
        tm = ThemeManager.instance()
        c = tm.tokens.colors
        s = tm.tokens.spacing
        
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet(f"background-color: {c.bg_secondary};")
        
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(s.md, 0, s.md, 0)
        
        # 标题
        title_label = QLabel(self._title)
        title_label.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {c.text_primary};"
        )
        layout.addWidget(title_label)
        layout.addStretch()
        
        # 关闭按钮
        close_btn = StyledButton("✕", variant="ghost", size="xs")
        close_btn.setFixedSize(24, 24)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
        
        self._title_label = title_label
        return bar
    
    def _setup_animations(self):
        """设置开关动画"""
        self._show_anim = QPropertyAnimation(self, b"pos")
        self._show_anim.setDuration(self.OVERLAY_ANIM_DURATION)
        self._show_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        self._hide_anim = QPropertyAnimation(self, b"pos")
        self._hide_anim.setDuration(self.OVERLAY_ANIM_DURATION)
        self._hide_anim.setEasingCurve(QEasingCurve.Type.InCubic)
    
    def set_content(self, widget: QWidget):
        """设置内容组件"""
        if self._content_widget:
            self._content_widget.setParent(None)
        self._content_widget = widget
        self._content_layout.addWidget(widget, 1)
    
    def show_overlay(self, anchor: QWidget):
        """显示覆盖层"""
        self._is_open = True
        
        # 计算显示位置（锚点右侧）
        anchor_pos = anchor.mapToGlobal(anchor.rect().topRight())
        target_x = anchor_pos.x() + 8
        target_y = max(anchor_pos.y(), 100)
        
        screen = self.screen().availableGeometry()
        if target_x + self._overlay_width > screen.right():
            target_x = anchor_pos.x() - self._overlay_width - 8
        
        self.move(target_x, target_y)
        self._content_area.setMinimumHeight(200)
        self._content_area.setMaximumHeight(500)
        
        self.show()
        self.raise_()
    
    def close_overlay(self):
        """关闭覆盖层"""
        self._is_open = False
        self.hide()
    
    def is_open(self) -> bool:
        return self._is_open
    
    # 对外 API
    def open(self, anchor: QWidget):
        """打开覆盖层（公共 API）"""
        self.show_overlay(anchor)
    
    def close(self):
        """关闭覆盖层（公共 API）"""
        self.close_overlay()
    
    def toggle(self, anchor: QWidget):
        """切换覆盖层显示"""
        if self._is_open:
            self.close_overlay()
        else:
            self.show_overlay(anchor)
```

---

### 3.4 第四步：动效系统标准化

#### 3.4.1 新增 `gui/core/animation.py`

> **参考源**：Hermes DESIGN.md → Motion 章节

```python
"""动效系统 — 统一管理动画参数"""

from __future__ import annotations

from PySide6.QtCore import (
    QPropertyAnimation, QEasingCurve, QParallelAnimationGroup,
    QSequentialAnimationGroup, QTimer
)

from gui.core.design_tokens import MotionTokens


class AnimationHelper:
    """动效工具类 — 基于 Design Token"""
    
    @staticmethod
    def transition(animation: QPropertyAnimation,
                   duration_key: str = "fast",
                   easing_key: str = "standard"):
        """应用标准过渡"""
        tokens = MotionTokens()
        duration = getattr(tokens, f"duration_{duration_key}", 100)
        easing = getattr(tokens, f"easing_{easing_key}", "OutCubic")
        
        animation.setDuration(duration)
        animation.setEasingCurve(getattr(QEasingCurve.Type, easing))
    
    @staticmethod
    def fade_in(widget, duration_ms: int = 150):
        """淡入动画"""
        animation = QPropertyAnimation(widget, b"windowOpacity")
        animation.setDuration(duration_ms)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        return animation
    
    @staticmethod
    def fade_out(widget, duration_ms: int = 150):
        """淡出动画"""
        animation = QPropertyAnimation(widget, b"windowOpacity")
        animation.setDuration(duration_ms)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        return animation
    
    @staticmethod
    def scale_in(widget, duration_ms: int = 200):
        """缩放进入"""
        from PySide6.QtCore import QSize
        
        animation = QPropertyAnimation(widget, b"geometry")
        animation.setDuration(duration_ms)
        animation.setEasingCurve(QEasingCurve.Type.OutBack)
        
        start_rect = widget.geometry()
        center = start_rect.center()
        half_w, half_h = start_rect.width() // 2, start_rect.height() // 2
        
        animation.setStartValue(
            center.x() - half_w // 2, center.y() - half_h // 2,
            half_w, half_h
        )
        animation.setEndValue(start_rect)
        return animation
    
    @staticmethod
    def slide_in(widget, direction: str = "right", duration_ms: int = 200):
        """滑动进入"""
        animation = QPropertyAnimation(widget, b"pos")
        animation.setDuration(duration_ms)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        current_pos = widget.pos()
        screen_geom = widget.screen().geometry()
        
        if direction == "right":
            animation.setStartValue(-widget.width(), current_pos.y())
        elif direction == "left":
            animation.setStartValue(screen_geom.width(), current_pos.y())
        elif direction == "bottom":
            animation.setStartValue(current_pos.x(), screen_geom.height())
        
        animation.setEndValue(current_pos)
        return animation
    
    @staticmethod
    def hover_press(widget):
        """按压反馈动效"""
        from PySide6.QtCore import QSize
        
        animation = QPropertyAnimation(widget, b"minimumSize")
        animation.setDuration(100)
        animation.setEasingCurve(QEasingCurve.Type.OutQuad)
        return animation


class AnimationManager:
    """动画管理器 — 集中控制和清理动画"""
    
    def __init__(self):
        self._active_animations: list = []
    
    def add_animation(self, animation):
        """添加活动动画"""
        self._active_animations.append(animation)
        animation.finished.connect(
            lambda: self._remove_animation(animation)
        )
    
    def _remove_animation(self, animation):
        """移除已完成的动画"""
        if animation in self._active_animations:
            self._active_animations.remove(animation)
    
    def stop_all(self):
        """停止所有动画"""
        for anim in self._active_animations[:]:
            anim.stop()
        self._active_animations.clear()
    
    @property
    def is_animating(self) -> bool:
        return len(self._active_animations) > 0
```

---

## 四、实施路线图

### Phase 1：基础建设（3天）

| 任务 | 文件 | 产出 |
|------|------|------|
| 建立 Design Token 体系 | `core/design_tokens.py` | 颜色、间距、圆角、阴影、动效 Token |
| 实现 ThemeManager | `core/theme_manager.py` | 主题切换、QSS 生成 |
| 更新 theme.py | `resources/theme.py` | 迁移到 ThemeManager |

### Phase 2：组件库建设（5天）

| 任务 | 文件 | 产出 |
|------|------|------|
| 实现 StyledButton | `components/button.py` | 7 种变体、4 种尺寸 |
| 实现 StyledCard | `components/card.py` | 卡片容器 |
| 实现反馈组件 | `components/loader.py` / `error_state.py` / `empty_state.py` | 加载、错误、空状态 |
| 实现 Overlay 基类 | `dialogs/overlay.py` | 统一覆盖层行为 |
| 实现 AnimationHelper | `core/animation.py` | 动效工具类 |

### Phase 3：组件迁移（7天）

| 任务 | 文件 | 产出 |
|------|------|------|
| 迁移 chat_bubble.py | `widgets/chat_bubble.py` | 使用 StyledCard |
| 迁移 chat_input.py | `widgets/chat_input.py` | 使用 StyledButton、StyledInput |
| 迁移 sidebar.py | `widgets/sidebar.py` | 使用 Design Tokens |
| 迁移 floating_panel.py | `widgets/floating_panel.py` | 继承 BaseOverlay |
| 迁移 conversation_list.py | `widgets/conversation_list.py` | 使用 StyledCard |

### Phase 4：集成与优化（3天）

| 任务 | 文件 | 产出 |
|------|------|------|
| 集成 ThemeManager | `main_window.py` | 全局主题应用 |
| 添加键盘快捷键 | `core/system/shortcut_manager.py` | Esc 关闭覆盖层等 |
| 优化动效 | `core/animation.py` | 全局动效审查 |
| 编写使用文档 | `docs/GUI_COMPONENTS.md` | 组件使用指南 |

---

## 五、与 Hermes 的关键差异

| 维度 | Hermes (React+Electron) | BNOS (PySide6) | 差异处理 |
|------|------------------------|----------------|----------|
| **样式系统** | CSS-in-JS + Design Tokens | QSS + QPalette | Token → QSS 映射层 |
| **状态管理** | nanostores | QObject Properties | 保持现有机制 |
| **组件库** | @assistant-ui/react | 自建 components/ | 借鉴 API 设计 |
| **动效** | CSS transition | QPropertyAnimation | AnimationHelper 封装 |
| **主题切换** | CSS variables 热替换 | QStyleSheet 重新应用 | ThemeManager 统一入口 |

---

## 六、验收标准

- [ ] 所有颜色值通过 `DesignTokens` 访问，无硬编码
- [ ] 所有按钮使用 `StyledButton`，统一 variant/size
- [ ] 所有卡片容器使用 `StyledCard`
- [ ] 覆盖层（Settings/Node/Archive）继承 `BaseOverlay`
- [ ] 主题切换通过 `ThemeManager.switch_theme()` 生效
- [ ] 动画时长通过 `AnimationHelper.transition()` 设置
- [ ] 反馈状态（Error/Empty/Loading）使用统一组件
- [ ] 组件文档完备，每个组件有使用示例

---

## 七、验收方法

> 本章为「六、验收标准」提供可操作的验证步骤、结论判定标准与记录模板，用于在 Phase 1–4 完成后开展系统化验收。用例编号 F 代表功能用例，E 代表边界/异常用例；「类型」列标注「核心」的项为强制通过项。

### 7.1 验收环境与前置条件

| 项 | 要求 |
|------|------|
| 操作系统 | Windows 10 / Windows 11（与 BNOS 运行环境一致） |
| Python 版本 | 3.10 及以上 |
| GUI 框架 | PySide6 6.5 及以上 |
| 显示分辨率 | 1920×1080 及以上，需支持多显示器边缘场景验证 |
| 代码状态 | Phase 1–4 全部任务已合并至主干，无未提交变更 |
| 依赖安装 | `requirements.txt` 已安装，`PySide6` 可正常导入 |
| 启动入口 | `python gui/main.py` 可正常启动主窗口且无报错 |
| 测试数据 | 至少 1 条会话记录、1 个 MCP 配置、1 条历史归档 |
| 验收人员 | 至少 1 名开发 + 1 名设计/产品 |
| 辅助工具 | 截图工具、色彩取色器（如 PowerToys Color Picker）、任务管理器 |

### 7.2 功能验收用例

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| F1 | DesignTokens 颜色 Token 完整性 | 1. 打开 `gui/core/design_tokens.py`；2. 检查 `ColorTokens` 是否包含文本/背景/强调/语义/边框 5 类字段；3. 执行 `python -c "from gui.core.design_tokens import ColorTokens; print(ColorTokens())"` | 输出包含 `text_primary`、`bg_primary`、`theme_primary`、`sidebar_bg`、`border_primary` 等字段及对应十六进制色值 | 5 类字段全部存在，色值与方案 3.1.1 节定义一致 | 核心 |
| F2 | DesignTokens 间距/圆角/阴影/动效 Token | 1. 检查 `SpacingTokens`、`RadiusTokens`、`ShadowTokens`、`MotionTokens` 四个 dataclass；2. 实例化 `DesignTokens` 并访问 `.spacing.xs`、`.radius.md`、`.shadow.lg`、`.motion.duration_normal` | 四类 Token 字段齐全且默认值符合方案（`xs=4`、`md=8`、`duration_normal=200` 等） | 四类 Token 均可访问且数值符合定义 | 核心 |
| F3 | DesignTokens 亮色工厂方法 | 1. 执行 `DesignTokens.light()`；2. 检查返回对象类型；3. 比对 `colors.bg_primary` 值 | 返回 `DesignTokens` 实例，`bg_primary` 为 `#FFFFFF` | 类型正确且亮色 Token 值符合预期 | 核心 |
| F4 | ThemeManager 单例与全局 QSS 生成 | 1. 在两个不同模块分别调用 `ThemeManager.instance()` 并比较 `id()`；2. 调用 `tm.get_qss()` 检查返回字符串 | 两次 `instance()` 返回对象 `id` 相同；QSS 字符串包含 `QWidget`、`QPushButton` 选择器，颜色值引用自 Token（非硬编码字面量） | 单例成立且 QSS 颜色来自 Token | 核心 |
| F5 | ThemeManager 组件级 QSS | 1. 依次调用 `tm.get_component_qss("card")`、`"input"`、`"sidebar"`；2. 检查每个返回值非空；3. 验证圆角/边框颜色引用 Token | 三种组件 QSS 均非空；card 圆角为 `radius.md`，input 圆角为 `radius.sm`，sidebar 背景为 `sidebar_bg` | 三种组件 QSS 均正确生成 | 核心 |
| F6 | ThemeManager QPalette 应用与主题切换 | 1. 启动应用并调用 `tm.apply_to_app(app)`；2. 读取 `app.palette()` 的 `Window`/`Text`/`Highlight` 颜色；3. 调用 `tm.switch_theme("light")` 后再次读取 | QPalette 颜色与 `ColorTokens` 中 `bg_primary`/`text_primary`/`theme_primary` 一致；切换后 Token 实例更新 | QPalette 与 Token 同步，切换生效 | 核心 |
| F7 | ThemeManager 监听者通知 | 1. 注册监听回调 `listener`；2. 调用 `tm.switch_theme("light")`；3. 检查 `listener` 调用情况与参数 | `listener` 被调用一次，参数为切换后的 `DesignTokens` 对象 | 监听者收到通知且参数为新 Token | 核心 |
| F8 | StyledButton 7 种 variant | 1. 在测试窗口创建 7 个 `StyledButton`，variant 分别为 `default`/`secondary`/`outline`/`ghost`/`destructive`/`link`/`icon`；2. 逐个视觉检查 | 7 种 variant 视觉可区分：default 蓝底白字、secondary 灰底、outline 描边、ghost 透明、destructive 红底、link 下划线、icon 图标样式 | 7 种 variant 全部渲染正确 | 核心 |
| F9 | StyledButton 4 种 size 与动态切换 | 1. 创建 4 个 default 按钮，size 为 `xs`/`sm`/`md`/`lg`；2. 测量高度与字体；3. 对其中一个按钮调用 `set_variant("destructive")` 与 `set_size("lg")` | 高度依次为 24/32/40/48px，字体 12/13/14/16px；切换后变为红底白字且高度 48px | 4 种尺寸符合定义，动态切换生效 | 核心 |
| F10 | StyledCard 容器、标题与边框开关 | 1. 创建 `StyledCard(title="测试卡片")` 并 `set_content(widget)`；2. 创建 `StyledCard(bordered=False)` 对比；3. 显示观察 | 带 title 卡片显示圆角边框与加粗标题；`bordered=False` 无边框仅圆角背景 | 卡片样式、标题、边框开关行为正确 | 核心 |
| F11 | StyledLoader 加载动画启停 | 1. 创建 `StyledLoader("加载中...")`；2. 调用 `start()` 观察 3 秒；3. 调用 `stop()` | `start()` 后圆环以约 30ms 间隔旋转、文字居中；`stop()` 后动画停止并隐藏 | 旋转流畅，停止后隐藏 | 核心 |
| F12 | StyledErrorState 重试回调 | 1. 创建 `StyledErrorState(title="加载失败", description="网络错误")`；2. `set_retry_callback(cb)`；3. 点击「重试」按钮 | 图标 ⚠ 为红色，标题/描述正确显示；点击触发 `cb` 一次 | 视觉符合错误语义且回调触发 | 核心 |
| F13 | StyledEmptyState 图标与动作 | 1. 创建 `StyledEmptyState(icon_type="no_data", action_text="新建", action_callback=cb)`；2. 点击动作按钮 | 图标为 📭，标题/描述显示，点击按钮触发 `cb` | 图标映射正确，动作回调触发 | 非核心 |
| F14 | BaseOverlay 显示/关闭/切换与自适应定位 | 1. 创建 `BaseOverlay` 子类实例；2. 调用 `open(anchor)` 观察位置；3. `toggle(anchor)` 关闭；4. `close()` 隐藏 | `open` 显示在锚点右侧 8px；`toggle` 关闭已打开层；`close` 隐藏；动画为 OutCubic 200ms | 三种 API 行为正确，动画符合 MotionTokens | 核心 |
| F15 | 组件迁移验证 | 1. 打开聊天页发消息，检查 `widgets/chat_bubble.py` 是否基于 `StyledCard`；2. 打开设置/节点/归档面板，检查 `widgets/floating_panel.py` 是否继承 `BaseOverlay`；3. 全局搜索硬编码颜色 | 气泡使用 StyledCard，三个面板共享 BaseOverlay 行为，源码无硬编码十六进制色值 | 迁移完成且无硬编码 | 核心 |

### 7.3 边界与异常验收

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| E1 | 主题切换后全应用样式同步 | 1. 启动应用并打开多个页面/覆盖层；2. 调用 `switch_theme("light")`；3. 截图比对所有可见组件 | 所有已存在的按钮、卡片、输入框、侧边栏样式同步更新为新 Token 对应样式 | 无组件残留旧样式 | 核心 |
| E2 | BaseOverlay 屏幕边缘自适应定位 | 1. 将 anchor 移至屏幕右边缘；2. 调用 `open(anchor)`；3. 将 anchor 移至左侧再测试 | 右边缘时覆盖层显示在 anchor 左侧（不超出屏幕）；左侧时显示在右侧 | 定位自适应，不出现裁剪/超出 | 核心 |
| E3 | Overlay 动画过程中快速 toggle | 1. 调用 `open(anchor)`；2. 在动画进行中立即连续调用 `toggle(anchor)` 多次；3. 观察最终状态与进程 | 不崩溃、不卡死；动画结束后状态与最后一次调用一致 | 无异常且最终状态正确 | 核心 |
| E4 | StyledLoader 长时间运行后停止 | 1. `start()` 后保持运行 60 秒；2. 调用 `stop()`；3. 用任务管理器观察 CPU 与计时器 | 长时间运行 CPU 占用稳定，`stop()` 后计时器停止、组件隐藏，无内存泄漏迹象 | 长时运行稳定，停止后资源释放 | 非核心 |
| E5 | AnimationManager.stop_all 资源清理 | 1. 启动多个动画并 `add_animation`；2. 在动画未完成时调用 `stop_all()`；3. 检查 `is_animating` | 所有动画停止，`is_animating` 返回 `False`，活动列表清空 | 全部停止且列表为空 | 非核心 |
| E6 | StyledButton 非法 variant 回退 | 1. 创建 `StyledButton(variant="unknown_variant")`；2. 观察样式 | 不抛异常，回退到 `default` variant 样式（蓝底白字） | 非法值回退到默认，无异常 | 非核心 |
| E7 | StyledEmptyState 未知 icon_type 回退 | 1. 创建 `StyledEmptyState(icon_type="not_exist")`；2. 观察图标 | 不抛异常，回退到 `📭`（no_data）图标 | 未知类型回退到默认图标 | 非核心 |
| E8 | 主题切换性能 | 1. 编写脚本连续调用 `switch_theme("light")` 1000 次；2. 计时总耗时与单次平均；3. 观察内存占用变化 | 1000 次切换总耗时合理（建议 < 3 秒），无明显内存增长 | 性能在可接受范围内 | 非核心 |

### 7.4 验收结论判定标准

| 验收等级 | 判定标准 |
|------|---------|
| **通过** | 所有「核心」项（F1–F12、F14、F15、E1–E3）全部通过 |
| **附条件通过** | 核心项全部通过，且非核心项不通过数 ≤ 3 项，并已提供明确补救计划与修复日期 |
| **不通过** | 任一「核心」项不通过 |

#### 验收记录模板

```
## 验收记录

- 验收日期：____年__月__日
- 验收人员：____________ / ____________
- 代码版本 / Commit：____________
- 验收环境：OS ______ / Python ______ / PySide6 ______ / 分辨率 ______

### 功能验收用例

- [ ] F1  DesignTokens 颜色 Token 完整性 ............ [通过 / 不通过 / N/A]
- [ ] F2  DesignTokens 间距/圆角/阴影/动效 Token ..... [通过 / 不通过 / N/A]
- [ ] F3  DesignTokens 亮色工厂方法 ................. [通过 / 不通过 / N/A]
- [ ] F4  ThemeManager 单例与全局 QSS 生成 .......... [通过 / 不通过 / N/A]
- [ ] F5  ThemeManager 组件级 QSS ................... [通过 / 不通过 / N/A]
- [ ] F6  ThemeManager QPalette 与主题切换 .......... [通过 / 不通过 / N/A]
- [ ] F7  ThemeManager 监听者通知 ................... [通过 / 不通过 / N/A]
- [ ] F8  StyledButton 7 种 variant ................. [通过 / 不通过 / N/A]
- [ ] F9  StyledButton 4 种 size 与动态切换 ......... [通过 / 不通过 / N/A]
- [ ] F10 StyledCard 容器/标题/边框开关 ............. [通过 / 不通过 / N/A]
- [ ] F11 StyledLoader 加载动画启停 ................. [通过 / 不通过 / N/A]
- [ ] F12 StyledErrorState 重试回调 ................. [通过 / 不通过 / N/A]
- [ ] F13 StyledEmptyState 图标与动作 ............... [通过 / 不通过 / N/A]
- [ ] F14 BaseOverlay 显示/关闭/切换/自适应定位 ..... [通过 / 不通过 / N/A]
- [ ] F15 组件迁移验证 .............................. [通过 / 不通过 / N/A]

### 边界与异常验收

- [ ] E1  主题切换后全应用样式同步 .................. [通过 / 不通过 / N/A]
- [ ] E2  BaseOverlay 屏幕边缘自适应定位 ............ [通过 / 不通过 / N/A]
- [ ] E3  Overlay 动画过程中快速 toggle ............. [通过 / 不通过 / N/A]
- [ ] E4  StyledLoader 长时间运行后停止 ............. [通过 / 不通过 / N/A]
- [ ] E5  AnimationManager.stop_all 资源清理 ........ [通过 / 不通过 / N/A]
- [ ] E6  StyledButton 非法 variant 回退 ............ [通过 / 不通过 / N/A]
- [ ] E7  StyledEmptyState 未知 icon_type 回退 ...... [通过 / 不通过 / N/A]
- [ ] E8  主题切换性能 .............................. [通过 / 不通过 / N/A]

### 不通过项说明

| 编号 | 问题描述 | 严重等级 | 补救计划 | 责任人 | 预计修复日期 |
|:----:|---------|:-------:|---------|--------|-----------|
|      |         |         |         |        |           |

### 验收结论

- [ ] 通过
- [ ] 附条件通过
- [ ] 不通过

验收人签字：____________      复核人签字：____________
```