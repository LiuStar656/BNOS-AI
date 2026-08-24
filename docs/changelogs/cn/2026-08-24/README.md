# 2026-08-24 更新总览

[返回总索引](../README.md)

---

## 更新目录

- [01 DSH web 桥接 BNOS（Phase 0 bridge 最小原型）](#01-dsh-web-桥接-bnosphase-0-bridge-最小原型)
- [02 方案方向修正：聊天 = DSH 原生 + smart 模式](#02-方案方向修正聊天--dsh-原生--smart-模式)

---

## 摘要

| # | 核心改动 | 根因 | 影响 |
|---|---------|------|------|
| 01 | DSH web ↔ BNOS 文件协议桥接：新增 `@bnos/bridge` 插件（宿主 `lib/index.js` 注册 `/bnos/api/send`+`/bnos/api/poll` 路由，客户端 `lib/client.js` 在 `conversation.view` slot 注册「BNOS」聊天页签）+ `web_server.py` 启动器（注入 DSH_HOME/DEEPSEEK_API_KEY/BNOS_SHARED_DIR）；联调修复 3 处 bug（client 注册 id 需用包名、LLM listener pipeline 解析忽略 source_port、AAA 工作模式「不需要」子串误判） | 按 `[PLAN]-DSH-web承载AAA主流程与BNOS资产迁移方案` Phase 0 打通最小原型：浏览器聊天 → AAA 日常模式回复完整显示，节点层零改动、文件协议复用 | 浏览器可访问 DSH web 并在「BNOS」页签与 AAA 对话（真实 DeepSeek 推理回复）；桥接机制验证通过，后续可在 dsh_desktop 桌面壳 profile 挂载同一插件 |
| 02 | 方案方向修正：聊天改为 **DSH 原生 `ui-conversation` + smart 模式**（AAA 为主要 agent），不做独立 BNOS 聊天页签/不接管原生；bridge 角色调整为资产数据通道候选；两个 PLAN 文档升 v1.1 | 用户确认聊天应直接复用 DSH 原生，把 BNOS 聊天做成「模式的一种」而非页面内嵌 | 后续 Phase 1 按 smart 预设落地（官方 preset + aaa-engine MCP + 意图门 + 工具裁剪 + 工具日志）；Phase 0 bridge 代码暂保留不重构 |

---

### 01 DSH web 桥接 BNOS（Phase 0 bridge 最小原型）

详见 [01_DSH-web桥接BNOS_Phase0.md](./01_DSH-web桥接BNOS_Phase0.md)。

---

### 02 方案方向修正：聊天 = DSH 原生 + smart 模式

详见 [02_方案方向修正_聊天为DSH原生加smart模式.md](./02_方案方向修正_聊天为DSH原生加smart模式.md)。

---

## 修改文件清单

### 新增文件

| 文件 | 所属 |
|------|------|
| `nodes/node_dsh/bridge/bnos-chat/package.json` | #01 |
| `nodes/node_dsh/bridge/bnos-chat/lib/index.js` | #01 |
| `nodes/node_dsh/bridge/bnos-chat/lib/client.js` | #01 |
| `nodes/node_dsh/web_server.py` | #01 |

### 重大修改文件

| 文件 | 改动 | 所属 |
|------|------|------|
| `nodes/node_dsh/dsh_home/profiles/web/cordis.patch.yml` | 追加 `bnos-bridge` 插件条目（`name:'@bnos/bridge'`） | #01 |
| `nodes/node_dsh/package.json` | 新增 `@bnos/bridge: file:bridge/bnos-chat` | #01 |
| `nodes/node_dsh/bridge/bnos-chat/lib/client.js` | 注册 id 改为包名 `@bnos/bridge` | #01 |
| `nodes/node_python_llm_infer/listener.py` | pipeline edge 解析匹配 source_port 的 output_ports（对齐 AAA） | #01 |
| `nodes/node_python_aaa_cognition/main.py` | 【工作模式】判定排除「不需要」子串误判 | #01 |
| `docs/design/[PLAN]-DSH-web承载AAA主流程与BNOS资产迁移方案（待决策）.md` | 升 v1.1：聊天方向改为 DSH 原生 + smart 模式（§1.2/1.3/1.4/3.1/3.2/3.3/四/五/七/八） | #02 |
| `docs/design/[PLAN]-DSH工具分配与模式复用闭环方案.md` | 补充载体为 DSH web 原生聊天；GUI 引用改为 DSH web 预设切换；工具图谱 web 化 | #02 |

---

**最后更新**：2026-08-24
