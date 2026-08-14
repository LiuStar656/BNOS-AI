"""BNOS AI 主题样式 — 由 ThemeEngine 统一生成全局 QSS（保持向后兼容）"""

from gui.core.theme_engine import theme_engine


def get_light_qss():
    """获取当前主题全局样式表（由 ThemeEngine 生成，含 token 兜底）"""
    return theme_engine.generate_global_qss()


# 保持向后兼容
LIGHT_QSS = get_light_qss()
