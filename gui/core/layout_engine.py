"""布局应用器 — 依 LayoutSpec 重建主窗口导航容器（不重启、页面实例复用）。

数据驱动 UI 布局动态调整方案（Phase 1）：
- apply(spec, main_window)：读 spec → 重建导航容器 → 保持当前页 → 持久化 layout_id
  → 发布 LAYOUT_CHANGED（组件自查刷新，阶段4 模式）
- 页面栈 _pages 复用（不重建页面实例，只重排导航容器）
- 与换肤正交：布局只操作结构，样式仍走 ThemeEngine token

持久化约定：apply 成功即视为「当前布局」，layout_id 写入 gui_config.json（重启恢复）。
窗口默认尺寸（window_default）保留于 spec，切换布局不强制拉扯用户当前窗口尺寸。
"""

from __future__ import annotations

from gui.core.event_bus import event_bus
from gui.core.layout_spec import LayoutSpec
from gui.core.messages import LAYOUT_CHANGED


class LayoutEngine:
    """布局应用器（单例）— 依 LayoutSpec 重建导航容器。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._window = None
        return cls._instance

    def __init__(self):
        pass

    # ─── 绑定主窗口（proposal 审批等无窗口上下文入口使用） ──

    def bind(self, main_window) -> None:
        self._window = main_window

    # ─── 应用布局 ─────────────────────────────────

    def apply(self, spec: LayoutSpec, main_window=None) -> str | None:
        """应用布局：成功返回 None，失败返回错误信息（不改变任何状态）。

        main_window 缺省时使用 bind() 绑定的窗口（提案审批路径）。
        """
        win = main_window or self._window
        if win is None:
            return "布局引擎未绑定主窗口"
        errs = spec.errors()
        if errs:
            return "布局校验失败: " + "; ".join(errs)

        # 记录当前页（重建后恢复选中态与显示）
        current_page = win._stack.currentWidget()
        current_id = None
        for pid, wid in win._pages.items():
            if wid is current_page:
                current_id = pid
                break

        # 1) 销毁旧导航容器（从父布局解绑，deleteLater 延后回收）
        old_nav = getattr(win, "_nav_view", None)
        if old_nav is not None:
            parent = old_nav.parentWidget()
            if parent is not None and parent.layout() is not None:
                parent.layout().removeWidget(old_nav)
            old_nav.setParent(None)
            old_nav.deleteLater()

        # 2) 按 spec 创建新导航容器（NavView 接口：SidebarNav / TopNav）
        nav = self._create_nav(spec)
        win._nav_view = nav
        self._insert_nav(win, nav, spec)

        # 3) 重连导航信号
        nav.page_changed.connect(win._switch_page)
        nav.settings_clicked.connect(win._on_open_settings)
        nav.node_clicked.connect(win._on_open_node)

        # 4) 保持当前页 + 导航选中态（旧导航失效后由事件循环回收）
        if current_id:
            nav.set_active(current_id)
        if current_page is not None and win._stack.currentWidget() is not current_page:
            win._stack.setCurrentWidget(current_page)

        # 5) 记住当前 spec（页面切换动画方向等查询用）
        win._layout_spec = spec

        # 6) 持久化当前布局（重启恢复）
        from gui.core.config import AppConfig

        cfg = AppConfig()
        cfg.set("layout_id", spec.id)
        cfg.save()

        # 7) 广播布局变更（组件自查刷新）
        event_bus.publish(LAYOUT_CHANGED, spec.id)
        return None

    # ─── 内部 ─────────────────────────────────────

    def _create_nav(self, spec: LayoutSpec):
        """按 nav_position 创建导航容器"""
        if spec.nav_position == "top":
            from gui.widgets.top_nav import TopNav

            return TopNav(spec)
        from gui.widgets.sidebar import SidebarNav

        return SidebarNav(spec)

    def _insert_nav(self, win, nav, spec: LayoutSpec) -> None:
        """把导航容器插入内容区布局（left=行首纵栏，top=标题栏下横栏）"""
        nav.setVisible(spec.nav_visible)
        if spec.nav_position == "top":
            # 标题栏与内容区之间
            win._main_layout.insertWidget(1, nav)
        else:
            # 内容区行首（right_side 保持伸缩）
            win._content_layout.insertWidget(0, nav)


# 模块级单例
layout_engine = LayoutEngine()
