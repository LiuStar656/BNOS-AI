# 02 方案方向修正：聊天 = DSH 原生 + smart 模式

## 问题描述

Phase 0 实现的是「在 DSH web 里嵌入独立 BNOS 聊天页签（conversation.view
slot）」，与既定方案（`[PLAN]-DSH-web承载AAA主流程与BNOS资产迁移方案` §3.2
"bridge 接管 ui-conversation"）一致。但用户确认：**聊天不应嵌入/接管**，
应直接用 **DSH 原生聊天**，把 BNOS 聊天做成 **模式中的一种**（smart / AAA 助理）。

## 修正结论

- **聊天 = DSH 原生 `ui-conversation` + smart 模式**：第 5 个预设
  `smart（AAA 助理）` 让 DSH agent 以 **AAA 为主要 agent** 运转
  （AAA 人格骨架 / 记忆注入 / 工具纪律 + aaa-engine MCP 认知工具）；
  用户在「设置 → Agent 预设」选 smart 即为"与 AAA 对话"
- **不做独立 BNOS 聊天页签、不接管 ui-conversation**；Phase 0 的 bridge 聊天链路
  仅作技术验证保留，代码暂不重构
- **bridge 角色调整**：不再承担聊天转发，作为 bnos-memory 等资产插件的
  数据通道候选（待决策项 2）
- **模式体系理清**：DSH 预设（standard/smart，用户级切换）≠ AAA 意图门
  （daily/work，smart 内部任务级自动判定）

## 修改文件

| 文件 | 改动 |
|------|------|
| `docs/design/[PLAN]-DSH-web承载AAA主流程与BNOS资产迁移方案（待决策）.md` | 升 v1.1：§1.2/§1.3/§1.4/§3.1 架构图/§3.2 聊天方案/§3.3 模式体系/§四 Phase 0-1/§七 影响范围/§八 待决策项/§五 风险 全部对齐新方向 |
| `docs/design/[PLAN]-DSH工具分配与模式复用闭环方案.md` | 补充载体：smart 模式 = BNOS 聊天在 DSH web 的形态；GUI 切换 → DSH web「设置 → Agent 预设」；工具图谱 web 化（Phase 2） |

## 验证方法

- 文档通读无旧方向残留（"接管/嵌入/独立聊天页签"仅存在于修正说明中）
- 后续 Phase 1 按 smart 预设落地：官方 preset + aaa-engine MCP + 意图门 + 工具裁剪 + 工具日志
