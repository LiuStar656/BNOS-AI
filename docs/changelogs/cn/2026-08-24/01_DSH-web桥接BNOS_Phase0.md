# 01 DSH web 桥接 BNOS（Phase 0 bridge 最小原型）

## 问题描述

1. **DSH web UI 与 BNOS 互不可见**：DSH（DeepSeek Harness）web 是可用的
   统一 UI 载体，但无法与 BNOS 节点体系（AAA 大脑 / LLM 推理 / 文件协议）通信；
   GUI 与 AAA 的对话链路只存在于桌面 GUI，浏览器端无法触达 AAA。
2. **节点层需零改动**：PLAN（`[PLAN]-DSH-web承载AAA主流程与BNOS资产迁移方案`）
   要求 BNOS 专属资产以 slot 插件挂载、文件协议复用，不能为 web 改造节点层。
3. **验证载体选择**：dsh_desktop 桌面壳本质是「启动 `dsh web` + 原生窗口承载」，
   bridge 插件机制与 UI 载体无关，先用 DSH 官方 web 模式（浏览器）验证最快。

## 修改方案

### Phase 0：bridge 最小原型（本日完成）

- **新增 `nodes/node_dsh/bridge/bnos-chat/`（npm 包 `@bnos/bridge`）**：
  - `lib/index.js`（宿主半边，`inject: ["webServer"]`）：
    - `POST /bnos/api/send` — 拦截 web 输入，原子写 `gui_input.json`
      （协议与 `MessageManager.send_text` 同构：`data_type:"text"`、
      `source:"gui"`、`identity_key:"gui:web"`、`conversation_id`、`request_id`）
    - `GET /bnos/api/poll` — mtime + md5 判新，读 `gui_reply.json` 返回回复
    - shared 目录定位：`BNOS_SHARED_DIR` env 优先且权威，兜底向上找 `nodes/shared`
  - `lib/client.js`（浏览器半边，classic script）：
    - `window.__ModuleLoader__.load({id: "@bnos/bridge", ...})` 注册
    - `ctx.slots.inject("conversation.view", ...)` 注册「BNOS」聊天页签
      （`id:"bnos-chat"`、`order:40`、label "BNOS"）
    - 发送 `fetch("/bnos/api/send")` + `setInterval` 轮询 `/bnos/api/poll`（300ms）
    - `request_id` 过滤在途回复；`<pending/>`/`<silent/>` 标签剥离
    - 面板：消息区（你/AAA 角色）+ 输入框 + 发送按钮，busy 状态锁
- **新增 `nodes/node_dsh/web_server.py`**：DSH web 启动器
  - 注入 `DSH_HOME`（节点内 dsh_home）、`DEEPSEEK_API_KEY`（复用 llm 节点
    `local_config.json` → `node_config.json` → env，运行时注入不落盘）、
    `BNOS_SHARED_DIR`（nodes/shared）
  - 运行 `node bin.js --profile web --port <port>`，解析输出 URL
  - 缺 key 只警告不退出（web UI 可正常启动）
- **web profile 注册插件**：`dsh_home/profiles/web/cordis.patch.yml` 追加
  `{id: bnos-bridge, name: '@bnos/bridge', config: {}}` 条目；npm `file:`
  依赖安装（junction 链接，改源码即改即用）

### Bug 修复（桥接链路联调发现）

| 文件 | 修复 |
|------|------|
| `bridge/bnos-chat/lib/client.js` | 注册 id `bnos-bridge` → `@bnos/bridge`（client-modules 按**包名**校验注册，否则 boot 报 "loaded without registering"） |
| `nodes/node_python_llm_infer/listener.py` | pipeline edge 解析只取源节点默认 `output_file`，忽略 `source_port` → 对齐 AAA 版逻辑（匹配 `output_ports`），否则 LLM 监听 `output_default.json` 收不到 AAA 的 `output_prompt.json` |
| `nodes/node_python_aaa_cognition/main.py` | 【工作模式】判定 `"需要" in wm` 子串误判「不需要」→ 排除 `"不需要" not in wm` |

## 关键链路

```
web（浏览器 BNOS 页签）→ fetch /bnos/api/send
  → bridge 写 nodes/shared/gui_input.json（MessageManager 同构）
  → AAA listener 轮询 → _on_text → prompt → LLM 节点
  → LLM（DeepSeek cloud）推理 → 写 output.json → AAA _on_parsed 解析写库
  → AAA 写 nodes/shared/gui_reply.json（data_type:"reply"）
  → bridge /bnos/api/poll（mtime+md5 判新 + request_id 过滤）→ web 渲染回复
```

## 验证方法

- `GET /plugins/@bnos/bridge/client.js` 返回 200；boot graph 含 `@bnos/bridge`
- 浏览器页签环出现「BNOS」（对话 · 轨迹 · BNOS），面板标题「BNOS 聊天 · 桥接 dsh web（AAA 日常模式）」
- 端到端：BNOS 面板发送「你好呀，我叫小明，我们聊聊天吧」→ AAA 日常模式
  经真实 DeepSeek 推理返回完整回复，约 8 秒内显示（用户「你」/回复「AAA」）
- `gui_input.json` 写入 `identity_key:"gui:web"`，`gui_reply.json` 含
  `request_id` 匹配，poll 返回 `{ok:true, reply:{content, request_id, pending}}`
