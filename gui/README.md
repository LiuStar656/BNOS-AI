# GUI 层

BNOS AI 桌面客户端 — PySide6 实现，微信风格聊天 + 主题换肤 + AI 操控 UI（工具桥）。
本目录是"代码"；改 GUI 必须遵守的规则见 **开发规范**。

## 开发规范

**→ [docs/design/[OK]-GUI开发规范.md](../docs/design/%5BOK%5D-GUI开发规范.md)**

规范 = 工程层（目录/页面注册/消息协议/节点通信）+ 样式层（Token 优先/组件规则/聊天 UI/换肤闭环）+ 配置层（gui_config.json/node_config.json/共享协议）+ AI 操控规则。改代码前先读它。

## 目录结构

```
gui/
├── main.py             # 启动入口
├── main_window.py      # 主窗口（消费 ui_registry 插槽组装页面）
├── core/               # 核心基础设施（config/theme_engine/event_bus/messages/
│                       #   ui_registry/tool_registry/tool_bridge/message_manager...）
├── pages/              # 页面（chat/settings/dsh_manage/live2d/location/mcp/...）
├── widgets/            # 业务组件（chat_bubble/sidebar/chat_input/knowledge_panel...）
├── dialogs/            # 对话框（archive_panel/personality_dialog）
└── resources/          # 静态资源（icons + theme.py 兼容层）
```

## 核心文件速查

| 文件 | 用途 |
|------|------|
| `core/config.py` | AppConfig：主题/配置持久化（gui_config.json） |
| `core/theme_engine.py` | 主题引擎：token → 全局 QSS + 统一取色 |
| `core/event_bus.py` + `core/messages.py` | 组件间消息发布订阅（消息名单一事实源） |
| `core/ui_registry.py` | 页面插槽注册中心（页面组装不硬编码在 main_window） |
| `core/tool_registry.py` | AI 操控工具注册（22 工具） |
| `core/tool_bridge.py` | 工具桥：GUI ↔ AAA 节点文件通道 |
| `core/message_manager.py` | 消息收发（gui_input/gui_reply 轮询） |
| `core/workflow_store.py` | 流程库（dsh.* 执行步骤直连 node_dsh 节点） |
| `pages/chat_page.py` | 聊天页（微信风气泡 + 日常/工作模式切换） |
| `pages/settings_panel.py` | 设置面板（主题/预设/模式关键词） |

## 关键约定（完整见规范）

- 颜色一律 `theme_engine.get(key)`，禁裸色值
- 新页面必须在 `ui_registry` 注册，main_window 不硬编码
- 组件协作走 event_bus + messages 常量
- 文本按钮用 `fit_button_width`，禁 `setFixedWidth`
- 聊天气泡：用户右绿 / AI 左白 / 宽度自适应 / 下往上堆叠
