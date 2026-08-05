# BNOS AI GUI 设计系统改造方案

> **参考源**：`references/hermes-agent-main/apps/desktop/DESIGN.md`
> **目标**：借鉴 Hermes Desktop 的设计系统理念，建立 BNOS AI 的标准化 UI 框架

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