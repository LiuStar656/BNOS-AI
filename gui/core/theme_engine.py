"""主题引擎 — 语义 token 字典 → 全局 QSS 的唯一生成与统一取色入口。

阶段1目标：把散落在各组件里的颜色读写收口到 ThemeEngine。
组件只通过 token 名取色，不写裸色值；换肤链路统一经此刷新。

设计要点：
- 单例，token 字典来自 AppConfig 主题配置（8 套预设 + 用户自定义）
- _TOKEN_DEFAULTS 提供旧预设未定义的新 token 兜底值（= 亮色主题原硬编码色，
  保证迁移后视觉不变）
- generate_global_qss() 由 token 生成全局 QSS（含组件级选择器规则），
  借助 Qt QSS 级联机制，setStyleSheet 换肤即时生效、无需重启
"""

from __future__ import annotations

from gui.core.config import AppConfig

# 新语义 token 兜底默认值（旧预设未定义时使用，值为原硬编码色，视觉不变）
_TOKEN_DEFAULTS: dict[str, str] = {
    "success_color": "#07C160",     # 成功/恢复动作（原 archive 恢复按钮）
    "success_hover": "#06AD56",
    "danger_color": "#d32f2f",      # 危险/删除动作 hover
    "icon_color": "#555555",        # 次要图标色（原 chat_input 附件图标）
    "icon_muted": "#999999",        # 弱图标色（原 chat_input 删除按钮）
    "disabled_bg": "#b0c4de",       # 禁用态背景（原全局按钮 disabled）
    "scrollbar_hover": "#a0a0a0",   # 滚动条滑块 hover
    "list_selected_bg": "#cce5ff",  # 列表选中背景（原 TreeWidget::item:selected）
    "card_hover": "#eef2f7",        # 卡片 hover 背景（原性格预设卡片）
    "neutral_btn_hover": "#e8e8e8", # 中性按钮 hover（原"稍后再说"）
    "slider_groove": "#e0e0e0",     # 滑块轨道底色
    "separator": "#eeeeee",         # 分隔线
    "danger_hover": "#b71c1c",      # 危险动作 hover（深红）
    "status_ok": "#4caf50",         # 状态-正常（绿）
    "status_warn": "#ff9800",       # 状态-警告（橙）
    "status_error": "#f44336",      # 状态-错误（红）
}


class ThemeEngine:
    """主题引擎（单例）。

    - tokens: 当前主题语义 token 字典
    - get(key, default): 组件统一取色入口（主题 → 默认表 → 调用方默认）
    - generate_global_qss(): 由 token 生成全局 QSS
    - apply_global(widget): 应用全局 QSS（换肤即时生效）
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._config = AppConfig()
        self._initialized = True

    # ─── token 访问 ──────────────────────────────

    @property
    def tokens(self) -> dict:
        """当前主题完整 token 字典"""
        return self._config.get_all_colors()

    def get(self, key: str, default: str | None = None) -> str:
        """统一取色入口：主题字典 → 兜底默认表 → 调用方默认值"""
        value = self.tokens.get(key)
        if value:
            return value
        if key in _TOKEN_DEFAULTS:
            return _TOKEN_DEFAULTS[key]
        return default or ""

    # ─── 全局 QSS 生成与应用 ──────────────────────

    def generate_global_qss(self) -> str:
        """由 token 生成全局 QSS（含组件级选择器规则，供 Qt 级联生效）"""
        c = lambda key: self.get(key)  # noqa: E731 — token 取值（带兜底）
        return f"""
QMainWindow {{ background: transparent; }}
QWidget#centralWidget {{ background-color: {c('bg_primary')}; border: none; border-radius: 8px; }}

QLabel {{ color: {c('text_primary')}; }}
QLineEdit {{
    background-color: {c('bg_secondary')};
    color: {c('text_primary')};
    border: 1px solid {c('border_color')};
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 14px;
}}
QLineEdit:focus {{ border-color: {c('accent_color')}; }}
QLineEdit:disabled {{ background-color: {c('bg_chat')}; color: {c('text_secondary')}; }}

QPushButton {{
    background-color: {c('accent_color')};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 14px;
}}
QPushButton:hover {{ background-color: {c('accent_hover')}; }}
QPushButton:pressed {{ background-color: {c('accent_color')}; }}
QPushButton:disabled {{ background-color: {c('disabled_bg')}; color: {c('icon_muted')}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background-color: transparent;
    width: 8px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: {c('border_color')};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background-color: {c('scrollbar_hover')}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

QScrollBar:horizontal {{ height: 0; }}

QTextEdit {{
    background-color: {c('bg_secondary')};
    color: {c('text_primary')};
    border: 1px solid {c('border_color')};
    border-radius: 8px;
    padding: 8px;
    font-size: 14px;
}}

QTreeWidget {{
    background-color: {c('bg_secondary')};
    color: {c('text_primary')};
    alternate-background-color: {c('bg_primary')};
    border: 1px solid {c('border_color')};
    border-radius: 4px;
    font-size: 12px;
}}
QTreeWidget::item {{ padding: 4px 8px; }}
QTreeWidget::item:selected {{
    background-color: {c('list_selected_bg')};
    color: {c('text_primary')};
}}
QTreeWidget::item:hover {{
    background-color: {c('bg_primary')};
}}
QHeaderView::section {{
    background-color: {c('bg_primary')};
    color: {c('text_secondary')};
    border: none;
    border-right: 1px solid {c('border_color')};
    border-bottom: 1px solid {c('border_color')};
    padding: 4px 8px;
    font-size: 11px;
}}

QDialog {{ background: transparent; color: {c('text_primary')}; }}
QDialog QLabel {{ color: {c('text_primary')}; }}
QMessageBox {{ background-color: {c('bg_secondary')}; }}
QMessageBox QLabel {{ color: {c('text_primary')}; }}
QComboBox {{
    background-color: {c('bg_secondary')};
    color: {c('text_primary')};
    border: 1px solid {c('border_color')};
    border-radius: 4px;
    padding: 4px 8px;
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background-color: {c('bg_secondary')};
    color: {c('text_primary')};
    selection-background-color: {c('sidebar_active')};
    selection-color: {c('sidebar_active_text')};
}}

QGroupBox {{
    color: {c('text_primary')};
    border: 1px solid {c('border_color')};
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 18px;
    font-weight: bold;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}

QSplitter::handle {{ background-color: {c('border_color')}; width: 1px; }}
QToolTip {{
    background-color: {c('bg_secondary')};
    color: {c('text_primary')};
    border: 1px solid {c('border_color')};
    padding: 4px 8px;
    font-size: 12px;
}}
QProgressBar {{
    background-color: {c('border_color')};
    color: {c('text_secondary')};
    border: none;
    border-radius: 2px;
    text-align: center;
}}
QProgressBar::chunk {{ background-color: {c('accent_color')}; border-radius: 2px; }}
"""

    def apply_global(self, widget) -> None:
        """应用全局 QSS（Qt 级联：已存在组件即时重绘，无需重启）"""
        widget.setStyleSheet(self.generate_global_qss())


# 模块级单例
theme_engine = ThemeEngine()
