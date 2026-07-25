"""
WeChat 风格多功能发送框

多行输入 + 工具栏（图片/文件/表情/发送）+ 附件预览
支持 Enter 发送、Shift+Enter 换行、Ctrl+V 粘贴图片
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)

from gui.core.config import AppConfig
from gui.resources.icons.codicon import codicon


class AttachmentWidget(QFrame):
    """附件标签 — 图标 + 文件名 + 删除按钮"""

    remove_requested = Signal(object)  # 传出附件 dict

    def __init__(self, attach: dict, parent=None):
        super().__init__(parent)
        self._attach = attach
        self.setObjectName("attachmentTag")
        self.setStyleSheet("""
            #attachmentTag {
                background-color: rgba(0,0,0,0.05);
                border:1px solid rgba(0,0,0,0.12);
                border-radius:4px;
                padding:4px 6px;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        # 图标
        icon_name = "file-media" if attach.get("type") == "image" else "file"
        icon_label = QLabel(codicon.get_char(icon_name))
        icon_label.setStyleSheet("font-size:14px; color:#555;")
        layout.addWidget(icon_label)

        # 文件名
        name_label = QLabel(attach.get("name", ""))
        name_label.setStyleSheet("color:#333; font-size:12px;")
        name_label.setMaximumWidth(100)
        layout.addWidget(name_label)

        # 删除按钮
        del_btn = QPushButton(codicon.get_char("close"))
        del_btn.setFixedSize(16, 16)
        del_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color:#999;
                font-size:10px;
            }
            QPushButton:hover { color:#d32f2f; }
        """)
        del_btn.clicked.connect(lambda: self.remove_requested.emit(self._attach))
        layout.addWidget(del_btn)


class AttachmentBar(QWidget):
    """附件预览条 — 横向排列附件标签"""

    attachment_removed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4,2,4,2)
        self._layout.setSpacing(6)
        self._layout.addStretch()

    def add_attachment(self, attach: dict):
        tag = AttachmentWidget(attach)
        tag.remove_requested.connect(self._on_remove)
        self._layout.insertWidget(self._layout.count()-1, tag)
        self.setVisible(True)

    def _on_remove(self, attach: dict):
        sender = self.sender()
        if sender:
            sender.deleteLater()
        self.attachment_removed.emit(attach)
        # 无附件时隐藏
        if self._layout.count() <=1:
            self.setVisible(False)

    def clear(self):
        while self._layout.count() >1:
            item = self._layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self.setVisible(False)


class ChatInput(QWidget):
    """WeChat 风格多功能输入栏"""

    send_requested = Signal(str, list)  # (text, attachments)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = AppConfig()
        self._attachments: list[dict] = []
        self._enabled = True

        # 外层圆角容器
        self.setObjectName("chatInput")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build_ui()
        self._apply_styles()

    def _build_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0,0,0,0)
        outer_layout.setSpacing(0)
        
        # 内层内容
        inner_layout = QVBoxLayout()
        inner_layout.setContentsMargins(0,0,0,0)
        inner_layout.setSpacing(0)
        
        # 输入框
        self._text_edit = QTextEdit()
        self._text_edit.setObjectName("chatInputEdit")
        self._text_edit.setPlaceholderText("输入消息...")
        self._text_edit.setFixedHeight(72)
        self._text_edit.setAcceptRichText(False)
        self._text_edit.document().setDocumentMargin(0)  # 清除默认 margin，避免与 QSS padding 叠加
        self._text_edit.installEventFilter(self)
        inner_layout.addWidget(self._text_edit)
        
        # 附件预览条
        self._attachment_bar = AttachmentBar()
        self._attachment_bar.attachment_removed.connect(self._remove_attachment)
        inner_layout.addWidget(self._attachment_bar)
        
        # 工具栏
        toolbar = QWidget()
        toolbar.setObjectName("chatInputToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8,4,8,4)
        toolbar_layout.setSpacing(4)
        
        self._img_btn = QPushButton(codicon.get_char("file-media"))
        self._img_btn.setToolTip("发送图片")
        self._img_btn.setObjectName("chatToolBtn")
        self._img_btn.clicked.connect(self._pick_image)
        toolbar_layout.addWidget(self._img_btn)
        
        self._file_btn = QPushButton(codicon.get_char("file"))
        self._file_btn.setToolTip("发送文件")
        self._file_btn.setObjectName("chatToolBtn")
        self._file_btn.clicked.connect(self._pick_file)
        toolbar_layout.addWidget(self._file_btn)
        
        self._emoji_btn = QPushButton(codicon.get_char("smiley"))
        self._emoji_btn.setToolTip("表情")
        self._emoji_btn.setObjectName("chatToolBtn")
        toolbar_layout.addWidget(self._emoji_btn)
        
        toolbar_layout.addStretch()
        
        self._send_btn = QPushButton("  发送  ")
        self._send_btn.setObjectName("chatSendBtn")
        self._send_btn.setFixedHeight(27)
        self._send_btn.clicked.connect(self._do_send)
        toolbar_layout.addWidget(self._send_btn)
        
        inner_layout.addWidget(toolbar)
        outer_layout.addLayout(inner_layout)

    def _apply_styles(self):
        colors = self._config.get_all_colors()
        self.setStyleSheet(f"""
            #chatInput {{
                background-color: {colors['bg_secondary']};
                border:1px solid {colors['border_color']};
                border-radius:10px;
            }}
            #chatInputEdit {{
                background-color: transparent;
                color: {colors['text_primary']};
                border:none;
                padding:10px 14px;
                font-size:14px;
                font-family:'Segoe UI', 'Microsoft YaHei', 'PingFang SC', sans-serif;
            }}
            #chatInputToolbar {{
                background-color: transparent;
                border-top:1px solid {colors['border_color']};
            }}
            QPushButton#chatToolBtn {{
                background: transparent;
                border: none;
                color: {colors['text_secondary']};
                font-size: 18px;
                padding:4px 10px;
                border-radius:4px;
            }}
            QPushButton#chatToolBtn:hover {{
                background-color: rgba(0,0,0,0.06);
                color: {colors['text_primary']};
            }}
            QPushButton#chatSendBtn {{
                background-color: {colors['accent_color']};
                color: white;
                border: none;
                border-radius:6px;
                font-size:13px;
                padding:4px 18px;
            }}
            QPushButton#chatSendBtn:hover {{
                background-color: {colors['accent_hover']};
            }}
            QPushButton#chatSendBtn:disabled {{
                background-color: {colors['border_color']};
                color: {colors['text_secondary']};
            }}
        """)

    def eventFilter(self, obj, event):
        if obj is self._text_edit and event.type() == event.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Return and not (event.modifiers() & Qt.ShiftModifier):
                self._do_send()
                return True
        return super().eventFilter(obj, event)

    def _pick_image(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"
        )
        for p in paths:
            self._add_attachment(p, "image")

    def _pick_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择文件", "",
            "所有文件 (*.*)"
        )
        for p in paths:
            self._add_attachment(p, "file")

    def _add_attachment(self, path: str, att_type: str):
        from pathlib import Path
        p = Path(path)
        attach = {"type": att_type, "name": p.name, "path": str(p)}
        self._attachments.append(attach)
        self._attachment_bar.add_attachment(attach)

    def _remove_attachment(self, attach: dict):
        if attach in self._attachments:
            self._attachments.remove(attach)

    def _do_send(self):
        text = self._text_edit.toPlainText().strip()
        if not text and not self._attachments:
            return
        self.send_requested.emit(text, self._attachments[:])
        self._text_edit.clear()
        self._attachments.clear()
        self._attachment_bar.clear()

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self._text_edit.setEnabled(enabled)
        self._send_btn.setEnabled(enabled)

    def set_focus(self):
        self._text_edit.setFocus()
