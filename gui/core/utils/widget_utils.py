"""控件尺寸自适应工具 — 解决字体放大后文字溢出固定尺寸控件的问题。

背景：全局 QSS 按钮 padding 固定（如 8px 16px），若按钮再用 setFixedWidth(56)
等固定宽度，字体一旦放大（系统 DPI 缩放 / 主题字号变大），文字就会超出按钮
边界。Qt 按钮的 sizeHint 本会按字体 + padding 计算，固定宽度剥夺了它。

约定：文本按钮一律不用 setFixedWidth，改用 fit_button_width() 设置最小宽度
（不小于文本+padding 所需），让布局在空间充足时正常展示、空间不足时允许
压缩而不是溢出。
"""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractButton


def fit_button_width(btn: QAbstractButton, *, padding: int = 36) -> None:
    """按钮最小宽度按文本自适应：fontMetrics 计算文本宽 + 左右 padding。

    - padding 参考全局 QSS 的 padding: 8px 16px（左右 32px）+ 少量余量
    - 只设置 minimumWidth，不固定宽度：保留 Qt sizeHint 的自适应扩展能力
    """
    fm = btn.fontMetrics()
    width = fm.horizontalAdvance(btn.text()) + padding
    if width > btn.minimumWidth():
        btn.setMinimumWidth(width)
