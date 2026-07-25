"""Markdown 渲染器 — 使用 mistune + Pygments 实现代码语法高亮

从 ai-chat-gui 项目适配，提取核心渲染逻辑为独立模块。
"""

from __future__ import annotations

import mistune
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer, TextLexer
from pygments.formatters import HtmlFormatter
from pygments.util import ClassNotFound


class PygmentsRenderer(mistune.HTMLRenderer):
    """使用 Pygments 进行代码高亮的 mistune 渲染器"""

    def __init__(self, style="monokai", css_class="code-highlight", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style = style
        self.css_class = css_class

    def block_code(self, code, info=None):
        """渲染代码块 — 使用内联样式以兼容 QTextBrowser"""
        if not code or not code.strip():
            return ""

        lexer = self._get_lexer(code, info)
        # noclasses=True 生成内联样式，兼容 QTextBrowser 的 setHtml
        formatter = HtmlFormatter(
            style=self.style,
            noclasses=True,
            nowrap=False,
            linenos=False,
        )
        return highlight(code, lexer, formatter)

    def _get_lexer(self, code, info):
        """获取合适的词法分析器"""
        if not info:
            try:
                return guess_lexer(code)
            except ClassNotFound:
                return TextLexer()

        aliases = {
            "js": "javascript",
            "ts": "typescript",
            "py": "python",
            "rb": "ruby",
            "sh": "bash",
            "shell": "bash",
            "zsh": "bash",
            "yml": "yaml",
            "md": "markdown",
            "cs": "csharp",
            "c++": "cpp",
            "h++": "cpp",
            "hpp": "cpp",
        }
        lang = aliases.get(info.lower().strip(), info.lower().strip())
        try:
            return get_lexer_by_name(lang, stripall=True)
        except ClassNotFound:
            try:
                return guess_lexer(code)
            except ClassNotFound:
                return TextLexer()

    def codespan(self, text):
        """渲染行内代码"""
        escaped = mistune.escape(text)
        return f'<code class="inline-code">{escaped}</code>'


class MarkdownParser:
    """Markdown 解析器封装 — 单例模式"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_parser()
        return cls._instance

    def _init_parser(self):
        self.renderer = PygmentsRenderer(style="monokai")
        self.markdown = mistune.create_markdown(
            renderer=self.renderer, plugins=["table", "strikethrough", "url"]
        )

    def parse_to_html(self, text: str) -> str:
        """将 Markdown 转换为 HTML"""
        if not text:
            return ""
        return self.markdown(text)


def get_markdown_parser() -> MarkdownParser:
    """获取 Markdown 解析器单例"""
    return MarkdownParser()
