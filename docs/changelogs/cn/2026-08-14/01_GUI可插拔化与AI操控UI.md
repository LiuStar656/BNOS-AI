# 01 GUI 可插拔化与 AI 操控 UI（7 阶段）

## 问题描述

GUI 主题/图标/页面/皮肤/流程均为硬编码静态结构，AI（AAA 节点）无法产出并应用变更；
对标 DeepSeek Harness WebUI 的"UI 可插拔 + AI 实时操控 UI"，需要让 agent 产出
（皮肤、图标、页面、流程）直接应用到 UI，且变更可见、可审批、可回退。

## 根因分析

- 取色散落 15+ 组件硬编码色值，改主题需逐个改文件
- 图标为裸符号，无法运行时覆盖
- 页面写死注册，无插槽机制
- 无皮肤包/提案/审批治理链路，AI 变更无法受控生效

## 修改方案（7 阶段）

| 阶段 | 能力 | 产出 |
|---|---|---|
| 1 | ThemeEngine：token→全局 QSS 唯一生成器 | `gui/core/theme_engine.py`，全组件 token 化 |
| 2 | IconRegistry：语义图标运行时覆盖 | `gui/core/icon_registry.py` |
| 3 | UiRegistry：页面插槽化（注册即出现） | `gui/core/ui_registry.py` |
| 4 | 消息事件化：跨组件协作走消息 | `gui/core/messages.py` |
| 5 | 皮肤包机制：AI 产出落盘安装 | `gui/core/skin_registry.py`（install/scan/list/remove） |
| 6 | 提案卡片：pending→审批→可回退 | `gui/core/proposal_store.py` + `proposals_page.py` |
| 7 | 工具闭环：AI 写请求→GUI 执行→回结果 | `gui/core/tool_registry.py` + `tool_bridge.py` + `tools_page.py` |

AI 调用链路：AAA 输出【工具调用】→ main.py 解析 → gui_tools.call_tool →
ToolBridge 轮询（`nodes/shared/gui_tool_requests/` → `gui_tool_responses/`）→
ToolRegistry handler → 破坏性变更生成提案，审批后生效。

## 影响范围

- GUI 全组件取色统一走 theme_engine token；25 个工具暴露给 AI
- 换肤即时生效（THEME_CHANGED → apply_global 重绘），提案 revert 可回退

## 验证方法

- offscreen 实例化 6 页面 + theme_engine apply_global
- 工具桥冒烟：写请求文件 → 轮询 → 响应
- 换肤链路：create_skin_proposal → approve → 重绘 → revert 恢复
