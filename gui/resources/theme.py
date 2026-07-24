"""BNOS AI 明亮主题 — 聊天风格全局样式表"""

LIGHT_QSS = """
QMainWindow { background-color: #f5f5f5; }
QWidget#centralWidget { background-color: #f5f5f5; border: none; }

QLabel { color: #333333; }
QLineEdit {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #d0d0d0;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 14px;
}
QLineEdit:focus { border-color: #1a73e8; }
QLineEdit:disabled { background-color: #f0f0f0; color: #aaaaaa; }

QPushButton {
    background-color: #1a73e8;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 14px;
}
QPushButton:hover { background-color: #1557b0; }
QPushButton:pressed { background-color: #0d47a1; }
QPushButton:disabled { background-color: #b0c4de; color: #e0e0e0; }

QScrollArea { border: none; background: transparent; }
QScrollBar:vertical {
    background-color: transparent;
    width: 8px;
    border: none;
}
QScrollBar::handle:vertical {
    background-color: #c0c0c0;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background-color: #a0a0a0; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

QScrollBar:horizontal { height: 0; }

QTextEdit {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #d0d0d0;
    border-radius: 8px;
    padding: 8px;
    font-size: 14px;
}

QTreeWidget {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    font-size: 12px;
}
QTreeWidget::item { padding: 4px 8px; }
QTreeWidget::item:selected { background-color: #e8f0fe; color: #1a73e8; }
QTreeWidget::item:hover { background-color: #f0f0f0; }
QHeaderView::section {
    background-color: #f5f5f5;
    color: #666666;
    border: none;
    border-right: 1px solid #d0d0d0;
    border-bottom: 1px solid #d0d0d0;
    padding: 4px 8px;
    font-size: 11px;
}

QDialog { background-color: #ffffff; color: #333333; }
QDialog QLabel { color: #333333; }
QMessageBox { background-color: #ffffff; }
QMessageBox QLabel { color: #333333; }
QComboBox {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    padding: 4px 8px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #333333;
    selection-background-color: #e8f0fe;
    selection-color: #1a73e8;
}

QGroupBox {
    color: #333333;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 18px;
    font-weight: bold;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }

QSplitter::handle { background-color: #d0d0d0; width: 1px; }
QToolTip {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #d0d0d0;
    padding: 4px 8px;
    font-size: 12px;
}
QProgressBar {
    background-color: #e0e0e0;
    color: #666666;
    border: none;
    border-radius: 2px;
    text-align: center;
}
QProgressBar::chunk { background-color: #1a73e8; border-radius: 2px; }
"""
