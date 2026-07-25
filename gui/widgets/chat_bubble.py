"""消息气泡组件 — 支持 Markdown 渲染 + 代码语法高亮，QQ/微信风格"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import QHBoxLayout, QSpacerItem, QWidget, QSizePolicy, QTextBrowser
from PySide6.QtGui import QFontMetrics, QFont

from gui.core.config import AppConfig
from gui.widgets.markdown_renderer import get_markdown_parser


class ChatBubble(QWidget):
    """消息气泡组件。

    用户气泡右对齐（绿底），AI 气泡左对齐（白底）。
    支持 Markdown 渲染和代码语法高亮。
    气泡宽度随内容自适应，最大宽度不超过 600px。
    """

    def __init__(self, text: str, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        self._text = text
        self._config = AppConfig()
        self._parser = get_markdown_parser()
        self._max_width = 600

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # 水平布局：spacer + text_browser 实现左右对齐
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 8, 24, 8)
        layout.setSpacing(0)

        # ─── QTextBrowser（替代 QLabel）─────────────
        self._browser = QTextBrowser()
        self._browser.setReadOnly(True)
        self._browser.setOpenExternalLinks(False)
        self._browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._browser.setMaximumWidth(self._max_width)
        self._browser.setFrameShape(QTextBrowser.Shape.NoFrame)  # 去掉边框
        self._browser.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._browser.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )

        # 高度自适应 — 文档内容变化时更新高度
        self._browser.document().documentLayout().documentSizeChanged.connect(
            self._adjust_size
        )

        # 渲染 Markdown 内容
        self._render_content(text)

        # 应用主题
        self._apply_theme()

        # 初始高度
        QTimer.singleShot(0, self._adjust_size)

        # 对齐
        if role == "user":
            layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))
            layout.addWidget(self._browser)
        else:
            layout.addWidget(self._browser)
            layout.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))

    # ─── 内容渲染 ──────────────────────────────────

    def _render_content(self, text: str):
        """Markdown → HTML → QTextBrowser"""
        colors = self._config.get_all_colors()
        fg = colors["bubble_user_text"] if self.role == "user" else colors["bubble_ai_text"]
        html_body = self._parser.parse_to_html(text)
        full_html = f"""
<!DOCTYPE html>
<html><head><style>
body {{ margin:0; padding:0; color:{fg};
       font-size:14px; line-height:1.6;
       font-family:'Segoe UI','Microsoft YaHei','PingFang SC',sans-serif; }}
a {{ color:{colors['accent_color']}; text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
code {{ background:rgba(0,0,0,0.06); padding:2px 6px; border-radius:4px;
       font-family:'Consolas','Fira Code','Courier New',monospace; font-size:0.9em; }}
pre {{ background:#272822; color:#f8f8f2; padding:12px; border-radius:8px;
       overflow-x:auto; font-family:'Consolas','Fira Code','Courier New',monospace;
       line-height:1.4; }}
pre code {{ background:transparent; padding:0; border-radius:0; }}
blockquote {{ border-left:3px solid {colors['border_color']}; margin:8px 0;
            padding:4px 12px; color:{colors['text_secondary']}; }}
table {{ border-collapse:collapse; margin:8px 0; width:100%; }}
th, td {{ border:1px solid {colors['border_color']}; padding:6px 10px; text-align:left; }}
th {{ background:rgba(0,0,0,0.03); }}
</style></head>
<body>
<div style="padding:12px 16px;">
{html_body}
</div>
</body></html>"""
        self._browser.setHtml(full_html)

    def _adjust_size(self):
        """根据文档内容调整 QTextBrowser 高度和宽度（宽度自适应）"""
        try:
            doc = self._browser.document()
            # 计算高度
            height = int(doc.size().height())
            self._browser.setFixedHeight(max(height, 40))

            # 计算宽度：用 QFontMetrics 估算最大宽度（考虑 padding 24）
            font = QFont("Segoe UI", 14)
            fm = QFontMetrics(font)
            # 估算最大宽度：取文本最长行宽度，加 padding，不超过 max_width
            lines = self._text.split("\n")
            max_line_width = 0
            for line in lines:
                if len(line) > 0:
                    line_width = fm.horizontalAdvance(line)
                    if line_width > max_line_width:
                        max_line_width = line_width
            # 加 padding 24 (12+16)
            content_width = max_line_width + 24 + 20  # 留20余量
            final_width = min(max(content_width, 80), self._max_width)
            self._browser.setFixedWidth(final_width)
        except RuntimeError:
            pass

    # ─── 主题 ──────────────────────────────────────

    def _apply_theme(self):
        """应用主题颜色到气泡外壳（圆角 + 边距 + 背景）"""
        colors = self._config.get_all_colors()
        bg = colors["bubble_user_bg"] if self.role == "user" else colors["bubble_ai_bg"]
        _border_radius = "16px"
        _extra_radius = (
            "border-bottom-right-radius: 4px;"
            if self.role == "user"
            else "border-bottom-left-radius: 4px;"
        )
        self._browser.setStyleSheet(f"""
            QTextBrowser {{
                border: none;
                border-radius: {_border_radius};
                {_extra_radius}
                padding: 0px;
                background-color: {bg};
            }}
        """)

    # ─── 公共方法 ──────────────────────────────────

    def minimumSizeHint(self):
        hint = self._browser.sizeHint()
        return QSize(hint.width() + 48, hint.height() + 16)

    def set_text(self, text: str):
        self._text = text
        self._render_content(text)
        QTimer.singleShot(0, self._adjust_size)
        self.updateGeometry()

    def append_text(self, text: str):
        self._text += text
        self._render_content(self._text)
        QTimer.singleShot(0, self._adjust_size)
        self.updateGeometry()
