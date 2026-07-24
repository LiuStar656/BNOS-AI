"""
日志查看工具 — 统一日志对话框
适配自 BNOS 参考项目
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QPushButton, QTextEdit, QVBoxLayout


def show_log_dialog(parent, title, content, width=800, height=600):
    """显示日志查看对话框

    Args:
        parent: 父窗口
        title: 对话框标题
        content: 日志文本内容
        width: 窗口宽度（默认 800）
        height: 窗口高度（默认 600）
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(width, height)

    layout = QVBoxLayout(dialog)

    text_edit = QTextEdit()
    text_edit.setReadOnly(True)
    text_edit.setText(content)
    layout.addWidget(text_edit)

    close_button = QPushButton("关闭")
    close_button.clicked.connect(dialog.close)
    layout.addWidget(close_button)

    dialog.exec()
