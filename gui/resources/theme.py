"""BNOS AI 明亮主题 — 聊天风格全局样式表，支持动态颜色注入"""

from gui.core.config import AppConfig


def get_light_qss():
    """获取明亮主题样式表，从AppConfig加载颜色"""
    config = AppConfig()
    colors = config.get_all_colors()
    
    return f"""
QMainWindow {{ background-color: {colors['bg_primary']}; }}
QWidget#centralWidget {{ background-color: {colors['bg_primary']}; border: none; }}

QLabel {{ color: {colors['text_primary']}; }}
QLineEdit {{
    background-color: {colors['bg_secondary']};
    color: {colors['text_primary']};
    border: 1px solid {colors['border_color']};
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 14px;
}}
QLineEdit:focus {{ border-color: {colors['accent_color']}; }}
QLineEdit:disabled {{ background-color: {colors['bg_chat']}; color: {colors['text_secondary']}; }}

QPushButton {{
    background-color: {colors['accent_color']};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 14px;
}}
QPushButton:hover {{ background-color: {colors['accent_hover']}; }}
QPushButton:pressed {{ background-color: {colors['accent_color']}; }}
QPushButton:disabled {{ background-color: #b0c4de; color: #e0e0e0; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background-color: transparent;
    width: 8px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: {colors['border_color']};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background-color: #a0a0a0; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

QScrollBar:horizontal {{ height: 0; }}

QTextEdit {{
    background-color: {colors['bg_secondary']};
    color: {colors['text_primary']};
    border: 1px solid {colors['border_color']};
    border-radius: 8px;
    padding: 8px;
    font-size: 14px;
}}

QTreeWidget {{
    background-color: {colors['bg_secondary']};
    color: {colors['text_primary']};
    alternate-background-color: {colors['bg_primary']};
    border: 1px solid {colors['border_color']};
    border-radius: 4px;
    font-size: 12px;
}}
QTreeWidget::item {{ padding: 4px 8px; }}
QTreeWidget::item:selected {{
    background-color: #cce5ff;
    color: {colors['text_primary']};
}}
QTreeWidget::item:hover {{
    background-color: {colors['bg_primary']};
}}
QHeaderView::section {{
    background-color: {colors['bg_primary']};
    color: {colors['text_secondary']};
    border: none;
    border-right: 1px solid {colors['border_color']};
    border-bottom: 1px solid {colors['border_color']};
    padding: 4px 8px;
    font-size: 11px;
}}

QDialog {{ background-color: {colors['bg_secondary']}; color: {colors['text_primary']}; }}
QDialog QLabel {{ color: {colors['text_primary']}; }}
QMessageBox {{ background-color: {colors['bg_secondary']}; }}
QMessageBox QLabel {{ color: {colors['text_primary']}; }}
QComboBox {{
    background-color: {colors['bg_secondary']};
    color: {colors['text_primary']};
    border: 1px solid {colors['border_color']};
    border-radius: 4px;
    padding: 4px 8px;
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background-color: {colors['bg_secondary']};
    color: {colors['text_primary']};
    selection-background-color: {colors['sidebar_active']};
    selection-color: {colors['sidebar_active_text']};
}}

QGroupBox {{
    color: {colors['text_primary']};
    border: 1px solid {colors['border_color']};
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 18px;
    font-weight: bold;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}

QSplitter::handle {{ background-color: {colors['border_color']}; width: 1px; }}
QToolTip {{
    background-color: {colors['bg_secondary']};
    color: {colors['text_primary']};
    border: 1px solid {colors['border_color']};
    padding: 4px 8px;
    font-size: 12px;
}}
QProgressBar {{
    background-color: {colors['border_color']};
    color: {colors['text_secondary']};
    border: none;
    border-radius: 2px;
    text-align: center;
}}
QProgressBar::chunk {{ background-color: {colors['accent_color']}; border-radius: 2px; }}
"""


# 保持向后兼容
LIGHT_QSS = get_light_qss()
