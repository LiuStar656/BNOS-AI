"""消息气泡组件 - Qt 原生 Markdown 渲染，微信风格"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
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

        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        # 水平布局：只有 text_browser
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 0, 24, 0)
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

        # 初始尺寸（同步计算，避免布局使用默认尺寸）
        self._adjust_size(True)

        # 对齐由外层 layout 控制，这里不需要 spacer 了
        layout.addWidget(self._browser)

    # ─── 内容渲染 ──────────────────────────────────

    def _render_content(self, text: str):
        """用 Qt 原生 Markdown 渲染"""
        doc = self._browser.document()  # 缓存复用
        # 清除默认 document margin，避免与 QSS padding 叠加
        doc.setDocumentMargin(0)
        # 设置文档布局宽度 = 最大气泡宽度，使文本在达到最大宽度时自动换行
        doc.setTextWidth(self._max_width)

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
        """根据文档内容调整 QTextBrowser 高度和宽度

        宽度策略：
        - 用 font metrics 测量最宽行的像素宽度，气泡紧贴内容
        - 达到最大宽度（600px）时换行
        """
        try:
            doc = self._browser.document()
            # 高度 = 文档内容高度 + QSS padding 14*2
            height = int(doc.size().height()) + 28
            self._browser.setFixedHeight(max(height, 10))

            if update_width:
                fm = self._browser.fontMetrics()
                padding_h = 36

                # 逐行测量，取最宽行
                max_line_w = 0
                for line in self._text.split("\n"):
                    w = fm.horizontalAdvance(line)
                    if w > max_line_w:
                        max_line_w = w

                width = max_line_w + padding_h
                # 最小宽度 = 3 个字符宽
                min_width = fm.averageCharWidth() * 3 + padding_h
                width = max(width, min_width)
                # 达到最大宽度时换行
                width = min(width, self._max_width)
                self._browser.setFixedWidth(width)
        except RuntimeError:
            pass

    def _on_doc_resized(self):
        """文档尺寸变化时更新高度和宽度"""
        self._adjust_size(update_width=True)

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

    def set_text(self, text: str):
        self._text = text
        self._render_content(text)
        self._adjust_size(True)
        self.updateGeometry()

    def append_text(self, text: str):
        """流式追加文本 — 宽度随内容自动重算"""
        self._text += text
        self._render_content(self._text)
        # 延迟调整尺寸，确保文档布局已更新
        QTimer.singleShot(0, lambda: self._adjust_size(True))
        self.updateGeometry()
