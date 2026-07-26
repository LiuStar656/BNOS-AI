"""消息气泡组件 - Qt 原生 Markdown 渲染，微信风格"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import QHBoxLayout, QSpacerItem, QWidget, QSizePolicy, QTextBrowser
from PySide6.QtGui import QFontMetrics, QFont, QTextDocument

from gui.core.config import AppConfig


class ChatBubble(QWidget):
    """消息气泡组件。

    用户气泡右对齐，AI 气泡左对齐。
    使用 Qt 原生 QTextDocument.setMarkdown() 渲染 Markdown。
    气泡宽度随内容自适应，最大宽度不超过 600px。
    """

    def __init__(self, text: str, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        self._text = text
        self._config = AppConfig()
        self._max_width = 600
        self._current_width = 0  # 当前实际宽度，流式时只增不减

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # 水平布局：spacer + text_browser 实现左右对齐
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 4, 24, 4)
        layout.setSpacing(0)

        # ─── QTextBrowser ─────────────────────
        self._browser = QTextBrowser()
        self._browser.setReadOnly(True)
        self._browser.setOpenExternalLinks(True)
        self._browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._browser.setMaximumWidth(self._max_width)
        self._browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        self._browser.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._browser.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )

        # 高度自适应（但流式追加时只更新高度，不更新宽度）
        self._browser.document().documentLayout().documentSizeChanged.connect(
            self._on_doc_resized
        )

        # 渲染 Markdown 内容（Qt 原生）
        self._render_content(text)

        # 应用主题
        self._apply_theme()

        # 初始尺寸
        QTimer.singleShot(0, lambda: self._adjust_size(True))

        # 对齐
        if role == "user":
            layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))
            layout.addWidget(self._browser)
        else:
            layout.addWidget(self._browser)
            layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))

    # ─── 内容渲染 ──────────────────────────────────

    def _render_content(self, text: str):
        """用 Qt 原生 Markdown 渲染"""
        doc = self._browser.document()  # 缓存复用
        # 清除默认 document margin，避免与 QSS padding 叠加
        doc.setDocumentMargin(0)

        # 设置文档默认样式表（影响 Markdown 转换后的 HTML 元素）
        colors = self._config.get_all_colors()
        doc.setDefaultStyleSheet(f"""
            body {{ font-family: 'Segoe UI','Microsoft YaHei','PingFang SC',sans-serif;
                    font-size: 14px; line-height: 1.6; }}
            code {{ background: rgba(0,0,0,0.06); padding: 2px 6px;
                    border-radius: 4px;
                    font-family: 'Consolas','Fira Code','Courier New',monospace; }}
            pre {{ background: #272822; color: #f8f8f2; padding: 12px;
                   border-radius: 8px; }}
            pre code {{ background: transparent; padding: 0; }}
            blockquote {{ border-left: 3px solid {colors['border_color']};
                          margin: 8px 0; padding: 4px 12px;
                          color: {colors['text_secondary']}; }}
            a {{ color: {colors['accent_color']}; }}
            table {{ border-collapse: collapse; margin: 8px 0; }}
            th, td {{ border: 1px solid {colors['border_color']};
                      padding: 6px 10px; }}
            th {{ background: rgba(0,0,0,0.03); }}
        """)

        # Qt 原生 Markdown 渲染
        doc.setMarkdown(
            text,
            QTextDocument.MarkdownFeature.MarkdownDialectCommonMark,
        )

    def _adjust_size(self, update_width: bool = True):
        """根据文档内容调整 QTextBrowser 高度和宽度"""
        try:
            doc = self._browser.document()
            # 高度 = 文档内容高度 + QSS padding 14*2，无额外最小值
            height = int(doc.size().height()) + 28
            self._browser.setFixedHeight(max(height, 10))

            # 宽度：流式追加时只增不减，防止窄栏内容堆叠截断
            if update_width:
                self._current_width = self._calc_content_width()
                self._browser.setFixedWidth(self._current_width)
        except RuntimeError:
            pass

    def _calc_content_width(self) -> int:
        """根据当前文本内容估算气泡宽度（只增不减）"""
        font = QFont("Segoe UI", 14)
        fm = QFontMetrics(font)
        # QSS padding left+right = 18+18 = 36px
        padding_h = 36
        max_line_w = 0
        for line in self._text.split("\n"):
            if line:
                w = fm.horizontalAdvance(line)
                if w > max_line_w:
                    max_line_w = w
        pw = max_line_w + padding_h
        # 最小宽度 = 一个字宽 + padding（避免空内容时宽度为 0）
        min_w = int(fm.averageCharWidth()) + padding_h
        w = max(pw, min_w)
        # 只增不减
        if w > self._current_width:
            self._current_width = w
        return min(self._current_width, self._max_width)

    def _on_doc_resized(self):
        """文档尺寸变化时仅更新高度，宽度不变"""
        try:
            doc = self._browser.document()
            height = int(doc.size().height()) + 28  # +QSS padding 14*2
            self._browser.setFixedHeight(max(height, 10))
            # 保持已有宽度
            if self._current_width > 0:
                self._browser.setFixedWidth(self._current_width)
        except RuntimeError:
            pass

    # ─── 主题 ──────────────────────────────────────

    def _apply_theme(self):
        """应用主题颜色到气泡外壳（圆角 + 背景，QSS 原生）"""
        colors = self._config.get_all_colors()
        bg = colors["bubble_user_bg"] if self.role == "user" else colors["bubble_ai_bg"]
        fg = colors["bubble_user_text"] if self.role == "user" else colors["bubble_ai_text"]
        self._browser.setStyleSheet(f"""
            QTextBrowser {{
                border: none;
                border-radius: 10px;
                padding: 14px 18px;
                background-color: {bg};
                color: {fg};
                font-size: 14px;
                font-family: 'Segoe UI','Microsoft YaHei','PingFang SC',sans-serif;
            }}
        """)

    # ─── 公共方法 ──────────────────────────────────

    def minimumSizeHint(self):
        hint = self._browser.sizeHint()
        return QSize(hint.width() + 48, hint.height() + 16)

    def set_text(self, text: str):
        self._text = text
        self._render_content(text)
        QTimer.singleShot(0, lambda: self._adjust_size(True))
        self.updateGeometry()

    def append_text(self, text: str):
        """流式追加文本 — 宽度自动增长（只增不减）"""
        self._text += text
        self._render_content(self._text)
        QTimer.singleShot(0, lambda: self._adjust_size(True))
        self.updateGeometry()
