# TTS 热开关方案

> 日期：2026-07-25 | 版本：v1.0 | 状态：[PLAN]

## 目录

- [一、背景与现状评估](#一背景与现状评估)
- [二、目标](#二目标)
- [三、方案设计](#三方案设计)
  - [3.1 核心思路：GUI 单一拥有 TTS 进程](#31-核心思路gui-单一拥有-tts-进程)
  - [3.2 改动 1 - server.py 去掉 TTS 启动](#32-改动-1---serverpy-去掉-tts-启动)
  - [3.3 改动 2 - listener.js 加端口占用检查](#33-改动-2---listenerjs-加端口占用检查)
  - [3.4 改动 3 - Live2DPage 直接管理 TTS 生命周期](#34-改动-3---live2dpage-直接管理-tts-生命周期)
  - [3.5 改动 4 - renderer.js 去硬编码兜底 + 尊重运行时标志](#35-改动-4---rendererjs-去硬编码兜底--尊重运行时标志)
  - [3.6 改动后数据流与所有权](#36-改动后数据流与所有权)
- [四、分阶段实施计划](#四分阶段实施计划)
- [五、风险评估](#五风险评估)
- [六、测试计划](#六测试计划)
- [七、影响范围](#七影响范围)

---

## 一、背景与现状评估

### 当前 TTS 架构

TTS 服务（`tts_server.py`，端口 8084）是 Live2D 语音播放链路的合成端。实际消费方只有渲染层 `renderer.js`（`fetch` 8084 取音频），Live2D 节点的 `main.js` 仅拼接 `tts_url` 字符串放入 `output.json`，并不调用 TTS。

当前存在 **两条 TTS 启动链路同时活跃**，没有单一拥有者：

| 链路 | 启动点 | 触发 |
|------|--------|------|
| A（GUI 渲染服务） | `gui/live2d/server.py:31` `start_tts()` | `Live2DPage._start_server()` Popen server.py，无任何开关判断 |
| B（BNOS 节点管线） | `nodes/node_js_live2d_face/listener.js:255` `startTTS()` | GUI `main.py:115` 自动启动 bnos 引擎，引擎按 `pipeline.json` 拉起 Live2D 节点 listener.js |

`pipeline.json` 包含 `node_js_live2d_face`，因此 GUI 运行时两条链路同时触发，**抢绑 8084 端口**，一个成功一个静默失败（`HTTPServer` 绑定 `OSError`）。

### 问题汇总

| 问题 | 根因 | 影响 |
|------|------|------|
| 无法热开关 | GUI 不持有 TTS 进程句柄，句柄在 server.py 全局变量里 | 想停 TTS 只能 kill 整个 server.py，连带停渲染服务 |
| 8084 孤儿进程泄漏 | `_stop_server()`（`live2d_page.py:390`）只 kill `_server_proc`，server.py 的 `finally: tts_process.kill()` 在强杀下不执行；`_kill_port` 只清 3000 从不清 8084 | 关 GUI 后 8084 被占，下次启动 TTS 绑定失败 |
| TTS 双重启动冲突 | server.py 与 listener.js 同时启动 TTS 抢 8084 | 端口冲突，行为不确定 |
| `tts_enabled` 标志形同虚设 | `main.js:79` 用它控制 tts_url 生成，但 `renderer.js:375` 有硬编码兜底 `http://127.0.0.1:8084/tts?text=...`，tts_url 为空仍播放 | 节点配置里关 TTS 无效 |

---

## 二、目标

1. 运行时可在 GUI 上热开/热关 TTS，不影响 Live2D 渲染服务
2. TTS 进程有**单一拥有者**，启停用真实 PID，无孤儿、无端口冲突
3. 顺带修复 8084 孤儿泄漏、双重启动冲突、`tts_enabled` 失效三个已存在问题
4. 保留 Live2D 节点独立运行（脱离 GUI）时自启 TTS 的能力，符合 BNOS"节点可独立运行"原则

---

## 三、方案设计

### 3.1 核心思路：GUI 单一拥有 TTS 进程

让 `Live2DPage` 像管理 `_server_proc` 一样**直接持有 TTS 进程句柄**，`server.py` 退化为纯渲染服务，`listener.js` 仅在端口空闲时自启。运行时开关由 GUI 持有，并推送到前端控制播放。

### 3.2 改动 1 - server.py 去掉 TTS 启动

文件：`gui/live2d/server.py`

- 删除 `start_tts()`（L31-45）、全局 `tts_process`（L29）、`main()` 里的调用（L114）、`finally` 里的 `tts_process.kill()`（L123-124）。
- 更新文件顶部 docstring，去掉"自动启动 TTS 服务"。
- server.py 变成纯静态 + `/output` 服务，职责单一。

**这一步同时修复 8084 孤儿进程泄漏。**

### 3.3 改动 2 - listener.js 加端口占用检查

文件：`nodes/node_js_live2d_face/listener.js`

- `startTTS()`（L255）启动前先探测 8084 是否已被占用：复用 `httpGet` 请求 `http://127.0.0.1:{port}/health`，若已通则记日志"端口已占用，跳过 TTS 启动"并 return。
- 已占用 = GUI 已接管，跳过；空闲 = 节点独立运行，自启。
- 保留节点 standalone 能力，消除双重启动冲突，符合 BNOS"节点可独立运行"原则。

### 3.4 改动 3 - Live2DPage 直接管理 TTS 生命周期

文件：`gui/pages/live2d_page.py`

新增状态与常量：

- `TTS_PORT = 8084`、配置键 `tts_enabled`（复用 `AppConfig`）
- `self._tts_proc: subprocess.Popen | None = None`
- `self._tts_enabled = AppConfig().get("tts_enabled", True)`

新增方法：

- `_tts_script_path()`：返回 `nodes/node_js_live2d_face/tts_server.py`
- `_start_tts()`：`_kill_port(8084)` 清理残留 -> `Popen tts_server.py --port 8084` -> 存 `_tts_proc`。已运行则跳过。
- `_stop_tts()`：`_tts_proc.kill()` + `wait(timeout=3)`（真实 PID，无孤儿）-> 置 None。
- `_toggle_tts()`：翻转 `_tts_enabled` -> `AppConfig` 持久化 -> 按值 `_start_tts()`/`_stop_tts()` -> 调用 `_push_tts_flag()`。
- `_push_tts_flag()`：对预览页和桌面悬浮窗两个 webview 执行 `runJavaScript("window.TTS_ENABLED = {true/false}")`。

接入既有流程：

- `_start_server()` 末尾：若 `_tts_enabled` 则 `_start_tts()`。
- `_stop_server()`：先 `_stop_tts()` 再停渲染服务。
- 页面加载完成（`_on_preview_page_loaded`）：`_push_tts_flag()` 同步当前状态到前端。

UI：

- 左侧面板"桌面显示"按钮上方加一个"TTS 语音"开关按钮，绑定 `_toggle_tts`，按 `_tts_enabled` 显示开/关文本与样式。

### 3.5 改动 4 - renderer.js 去硬编码兜底 + 尊重运行时标志

文件：`gui/live2d/renderer.js`

- 删除 L375 的 `|| \`http://127.0.0.1:8084/tts?text=...\`` 兜底，改为 `const finalTtsUrl = ttsUrl;`。
- `handleNewData()` 在 `playTTS` 调用前判断 `if (!window.TTS_ENABLED) return;`，关闭时直接跳过，避免每 500ms 对 8084 发失败请求刷错误日志。

### 3.6 改动后数据流与所有权

```
                       TTS 进程 (8084) 拥有者
  ┌─────────────────────────────────────────────────────┐
  │ GUI 运行时: Live2DPage._tts_proc (唯一)              │
  │   ├─ server.py 不再启 TTS                            │
  │   ├─ listener.js 探测到 8084 占用 -> 跳过            │
  │   └─ 热开关: _toggle_tts() 启停 _tts_proc            │
  ├─────────────────────────────────────────────────────┤
  │ 节点独立运行时: listener.js.startTTS() (端口空闲)    │
  └─────────────────────────────────────────────────────┘

  播放控制:
    GUI 开关 -> AppConfig.tts_enabled -> window.TTS_ENABLED
    renderer.js: window.TTS_ENABLED=false 则跳过 playTTS（不 fetch 8084）
```

---

## 四、分阶段实施计划

### Phase 0 - 解耦与所有权上移

1. 改动 1：server.py 去掉 TTS 启动（同时修复孤儿泄漏）
2. 改动 3 的进程管理部分：Live2DPage 接管 `_tts_proc`，`_start_server`/`_stop_server` 接入
3. 验证：GUI 启停一次，确认 8084 随 GUI 启停、无孤儿

### Phase 1 - 冲突消除

4. 改动 2：listener.js startTTS 加端口占用检查
5. 验证：GUI 运行时 listener.js 日志显示"跳过 TTS 启动"；单独跑节点能自启 TTS

### Phase 2 - 运行时热开关 UI

6. 改动 3 的 UI 部分：左侧面板加"TTS 语音"开关按钮 + `_toggle_tts` + 持久化
7. 改动 4：renderer.js 去兜底 + 尊重 `window.TTS_ENABLED`
8. 改动 3 的 `_push_tts_flag`：页面加载与切换时同步标志到两个 webview
9. 验证：运行时点按钮可即时开/关语音，刷新页面后状态保持

---

## 五、风险评估

| 风险 | 等级 | 应对 |
|------|------|------|
| `_kill_port(8084)` 误杀非本项目的 8084 占用进程 | 中 | 仅在 `_start_tts` 启动前调用一次；`_stop_tts` 优先用真实 PID kill，`_kill_port` 仅作启动前清理兜底 |
| listener.js 端口探测与 GUI 启动存在竞态（两者几乎同时启动） | 低 | 探测失败则跳过，最坏情况是节点侧 TTS 启动失败并记日志，GUI 侧 `_kill_port`+重启保证最终所有权归 GUI |
| `window.TTS_ENABLED` 未注入时 renderer.js 默认行为 | 低 | renderer.js 中 `if (!window.TTS_ENABLED) return;` 需处理 undefined：未注入时默认放行（`window.TTS_ENABLED !== false` 才播放），避免页面加载初期误禁 |
| 桌面悬浮窗 webview 未同步到标志 | 低 | `_push_tts_flag` 同时推送预览页与 overlay 两个 webview；overlay 在 `_toggle_desktop` 创建后也需立即推送一次 |
| 节点独立运行模式下改 listener.js 影响行为 | 低 | 端口占用检查是纯增量防御逻辑，端口空闲时行为与原来完全一致 |

---

## 六、测试计划

### 单元/手动验证

1. **基本启停**：启动 GUI -> 8084 可访问；关闭 GUI -> 8084 释放（`netstat -ano | findstr :8084` 无 LISTENING）。
2. **孤儿修复**：连续启动关闭 GUI 3 次，每次 TTS 都能成功绑定 8084，无端口占用报错。
3. **双重启动消除**：GUI 运行时查看 listener.js 输出，应见"端口已占用，跳过 TTS 启动"。
4. **热开关**：GUI 运行中点"TTS 语音"关 -> 发送对话，Live2D 嘴型不动、无音频；点开 -> 下条对话正常播放。
5. **状态持久化**：关闭 TTS 后重启 GUI，按钮显示"关"，且不播放；开启后重启，显示"开"且播放。
6. **渲染不受影响**：热开关 TTS 期间 Live2D 模型渲染、表情切换、Ctrl+滚轮缩放等均正常。
7. **节点独立模式**：脱离 GUI 直接跑 `nodes/node_js_live2d_face/listener.js`，8084 空闲时能自启 TTS。
8. **renderer 无错误日志**：TTS 关闭时，浏览器控制台不应每 500ms 出现 8084 fetch 失败错误。

### 回归

- Live2D 预览页/桌面悬浮窗所有既有交互（拖拽、缩放、模型切换、表情）不受影响。

---

## 七、影响范围

| 文件 | 改动 |
|------|------|
| `gui/live2d/server.py` | 删除 TTS 启动相关代码，变纯渲染服务 |
| `gui/pages/live2d_page.py` | 新增 TTS 进程管理、热开关方法、UI 按钮、标志推送 |
| `gui/live2d/renderer.js` | 去掉 8084 硬编码兜底，尊重 `window.TTS_ENABLED` |
| `nodes/node_js_live2d_face/listener.js` | `startTTS` 加端口占用检查 |
| `gui_config.json`（运行时生成） | 新增 `tts_enabled` 配置项 |

不涉及：AAA 节点、LLM 节点、节点间文件协议、bnos_runtime 引擎。
