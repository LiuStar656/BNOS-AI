# 08 GUI 开发规范（工程+样式+配置三层）

## 背景

让 AI 直接操控 GUI（22 个 ui.* 工具、AI 协作改预设/换肤）之后，缺一份"告诉 AI 怎么改 GUI"的规范文件——对应 DSH 的 `AGENTS.md + web-styling.md + config-catalog.md` 三层体系。此前 GUI 侧无模块 README、无样式规范、无配置说明，硬编码色散落各组件。

## 内容

- 新增 `docs/design/[OK]-GUI开发规范.md`（v1.0）：
  - **工程层**：目录结构、核心模块职责表、页面注册（ui_registry 插槽/冲突即设计）、消息协议（messages.py）、GUI↔节点文件通道协议（gui_input/gui_reply/mode.json/dsh_task_in.json）
  - **样式层**：主题 token 体系（8 预设+皮肤包+兜底表）、取色规则（Token 优先禁裸色）、组件规则（右键菜单 QMenu(self)、fit_button_width 禁 setFixedWidth）、聊天 UI 微信风规范、换肤闭环
  - **配置层**：gui_config.json 结构、节点配置归节点自治、共享协议原子写、工具清单由 to_file 生成
  - **AI 操控规则** + **审查清单**（改 GUI 提交前逐项勾选）
- 新增 `gui/README.md`：模块索引（指向规范 + 核心文件速查 + 关键约定）

## 验证

- 规范全部条目基于现网代码核实（theme_engine/config/ui_registry/messages 逐项对照）
- 现有已知违规（chat_page/settings_panel 硬编码色）在规范中登记为"现状治理"项
