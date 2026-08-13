"""
统一明亮主题对话框工具 — 自绘对话框组件
适配自 BNOS 参考项目，改为明亮主题风格
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

_STYLE_CONTAINER = (
    "QWidget { background-color: #ffffff; border-radius: 8px; border: 1px solid #d0d0d0; }"
)
_STYLE_TITLE = "color: #333333; font-size: 13px; font-weight: bold; background: transparent;"
_STYLE_LABEL = "color: #666666; font-size: 12px; background: transparent;"
_STYLE_INPUT = "background: #ffffff; color: #333333; border: 1px solid #d0d0d0; border-radius: 4px; padding: 6px 10px; font-size: 13px;"
_STYLE_BTN_OK = "QPushButton { background: #1a73e8; color: white; border: none; border-radius: 4px; padding: 6px 20px; } QPushButton:hover { background: #1557b0; }"
_STYLE_BTN_GREY = "QPushButton { background: #f0f0f0; color: #333; border: 1px solid #d0d0d0; border-radius: 4px; padding: 6px 20px; } QPushButton:hover { background: #e0e0e0; }"
_STYLE_TEXT = "background: #ffffff; color: #333333; border: 1px solid #d0d0d0; border-radius: 4px; font-size: 12px;"


class ThemedDialogBase(QDialog):
    """明亮主题对话框基类 — 不设 Qt 父窗口，避免与 WA_TranslucentBackground 父窗口冲突"""

    def __init__(self, parent_window=None, title="", width=400, height=200):
        super().__init__()
        self._parent_window = parent_window  # 仅用于居中定位
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(width, height)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        self._container = QWidget()
        self._container.setStyleSheet(_STYLE_CONTAINER)
        outer_layout.addWidget(self._container)

        self._main_layout = QVBoxLayout(self._container)
        self._main_layout.setContentsMargins(14, 10, 14, 10)
        self._main_layout.setSpacing(6)

        self._title_bar = QHBoxLayout()
        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(_STYLE_TITLE)
        self._title_bar.addWidget(self._title_label)
        self._title_bar.addStretch()

        self._close_label = QLabel("x")
        self._close_label.setStyleSheet(
            "color: #999999; font-size: 14px; padding:0 5px; background:transparent;"
        )
        self._close_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_label.mousePressEvent = lambda e: self.reject()
        self._title_bar.addWidget(self._close_label)

        self._main_layout.addLayout(self._title_bar)

    def get_main_layout(self):
        return self._main_layout

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()

    def center_on_parent(self):
        parent = self._parent_window
        if parent and parent.isVisible():
            pc = parent.mapToGlobal(parent.rect().center())
            self.move(pc.x() - self.width() // 2, pc.y() - self.height() // 2)
        else:
            from PySide6.QtWidgets import QApplication

            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)

    def add_button_row(self, buttons):
        br = QHBoxLayout()
        br.addStretch()
        for text, style, callback in buttons:
            btn = QPushButton(text)
            btn.setStyleSheet(style)
            btn.clicked.connect(callback)
            br.addWidget(btn)
        self._main_layout.addLayout(br)

    def exec(self):
        self.center_on_parent()
        return super().exec()


def themed_input(parent, title, prompt, default=""):
    """自绘输入弹窗"""
    dlg = ThemedDialogBase(parent, title, 380, 150)
    lay = dlg.get_main_layout()

    lb = QLabel(prompt)
    lb.setStyleSheet(_STYLE_LABEL)
    lay.addWidget(lb)

    e = QLineEdit(default)
    e.setStyleSheet(_STYLE_INPUT)
    lay.addWidget(e)

    def on_accept():
        dlg.accept()

    dlg.add_button_row([("取消", _STYLE_BTN_GREY, dlg.reject), ("确定", _STYLE_BTN_OK, on_accept)])

    e.returnPressed.connect(dlg.accept)

    return e.text().strip() if dlg.exec() == QDialog.DialogCode.Accepted else None


MSG_ACCEPT = 1
MSG_REJECT = 0
MSG_CANCEL = -1


def themed_message(parent, title, text, mode="info"):
    """统一消息弹窗"""
    dlg = ThemedDialogBase(parent, title, 440, 180)
    lay = dlg.get_main_layout()

    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setStyleSheet(_STYLE_LABEL)
    lay.addWidget(lb, 1)

    if mode in ("info", "warning", "error"):
        dlg.add_button_row([("确定", _STYLE_BTN_OK, dlg.accept)])
    elif mode == "question":
        dlg.add_button_row(
            [("否", _STYLE_BTN_GREY, dlg.reject), ("是", _STYLE_BTN_OK, dlg.accept)]
        )
    elif mode == "question3":
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(_STYLE_BTN_GREY)
        no_btn = QPushButton("否")
        no_btn.setStyleSheet(_STYLE_BTN_GREY)
        yes_btn = QPushButton("是")
        yes_btn.setStyleSheet(_STYLE_BTN_OK)

        def _on_yes():
            dlg.done(MSG_ACCEPT)

        def _on_no():
            dlg.done(MSG_REJECT)

        def _on_cancel():
            dlg.done(MSG_CANCEL)

        yes_btn.clicked.connect(_on_yes)
        no_btn.clicked.connect(_on_no)
        cancel_btn.clicked.connect(_on_cancel)

        br = QHBoxLayout()
        br.addStretch()
        br.addWidget(cancel_btn)
        br.addWidget(no_btn)
        br.addWidget(yes_btn)
        lay.addLayout(br)

    result = dlg.exec()
    if mode == "question":
        return result == QDialog.DialogCode.Accepted
    if mode == "question3":
        return result
    return None


def show_text_dialog(parent, title, content, width=600, height=400):
    """显示文本查看对话框"""
    dlg = ThemedDialogBase(parent, title, width, height)
    lay = dlg.get_main_layout()

    te = QTextEdit()
    te.setReadOnly(True)
    te.setPlainText(content)
    te.setStyleSheet(_STYLE_TEXT)
    lay.addWidget(te, 1)

    dlg.add_button_row([("关闭", _STYLE_BTN_GREY, dlg.reject)])
    dlg.exec()
