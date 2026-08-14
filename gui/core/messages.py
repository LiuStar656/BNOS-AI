"""UI 消息协议 — 组件间协作的统一事件名清单（单一事实源）。

阶段4目标（核心一刀）：组件间运行时协作从"直接方法调用"改为"消息发布订阅"。
组件对外只订阅它关心的消息，调用方只 publish，不再 import 对方内部方法。
AI 操控 UI 也走同一条消息通道（阶段6/7 复用）。

消息清单：
- THEME_CHANGED:            主题变更（组件自查换肤刷新，沿用既有事件名 "theme_changed"）
- PAGE_ACTIVATED:           页面被激活 (data=page_id) — 替代 main_window 直接调页面私有方法
- DATA_REFRESH_REQUESTED:   数据刷新请求 (data=页面 id 或 None=当前页) — AI 操控入口
"""

# 主题变更（组件自查换肤刷新）
THEME_CHANGED = "theme_changed"

# 页面被激活（data: page_id）
PAGE_ACTIVATED = "ui.page_activated"

# 数据刷新请求（data: 页面 id 或 None=当前页）
DATA_REFRESH_REQUESTED = "ui.data_refresh_requested"

# 页面导航请求（data: page_id）— AI 操控入口（navigate_page 工具）
NAVIGATE_REQUEST = "ui.navigate_request"

# AI 活动事件（data: {"type", "text", "ts"}）— 实时事件推送（P0-2）
AI_EVENT = "ai.event"
