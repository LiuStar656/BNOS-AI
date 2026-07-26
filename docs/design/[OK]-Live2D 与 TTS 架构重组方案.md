# BNOS — Live2D 与 TTS 架构重组方案

> 日期：2026-07-26 | 版本：v3.0 | 状态：[PLAN]

---

## 一、现状

### 两套独立的 Live2D 渲染链路

```
AAA output_reply.json
  ↓
  ├── 节点层: listener.js(轮询) → main.js(情绪提取) → output.json
  │       ↓  SSE 推送
  │    live2d-server.js (Node.js, :3000)
  │       ↓
  │    renderer/renderer.js (浏览器端)
  │
  └── GUI 层: gui/live2d/server.py (Python, :3000, 轮询 500ms)
          ↓
       gui/live2d/renderer.js (QWebEngineView 内)
          ↓
       live2d_overlay.py (桌面悬浮窗)
```

两套同时运行，**互相竞争端口 3000 和 8084**。

### TTS 服务的归属混乱

`tts_server.py` 同时被三条路径启动：

| 启动者 | 方式 |
|--------|------|
| `listener.js`（节点） | 启动时 subprocess `python tts_server.py --port 8084` |
| `gui/pages/live2d_page.py`（GUI） | 进入 Live2D 页时 subprocess `python tts_server.py --port 8084` |
| `live2d-server.js`（节点 HTTP 模式） | 启动时 subprocess `python tts_server.py --port 8084` |

三条路径互相撞端口，靠端口占用检测（谁先占谁赢）来规避冲突。

---

## 二、问题分析

| 问题 | 说明 |
|------|------|
| **代码冗余** | 两套 HTTP 服务（Node.js + Python），两套 renderer.js，两套轮询/SSE 逻辑 |
| **端口竞争** | :3000 和 :8084 在多进程中争抢 |
| **数据源重复** | 节点层和 GUI 层同时轮询同一份 `output.json` |
| **Live2D 渲染不是节点职责** | 渲染 + 口型同步 + 桌面悬浮窗是 UI 行为，不应放在数据管道节点层 |
| **TTS 进程管理混乱** | 三个启动者、无统一生命周期、端口抢占式共存 |

---

## 三、核心设计原则

| 原则 | 说明 |
|------|------|
| **所有后端进程由引擎管理器统一管理** | TTS 也是后端进程，应与 AAA、LLM 同级管理 |
| **GUI 只消费和展示，不管理进程生命周期** | 不直接 subprocess.Popen 任何后端服务 |
| **节点 entry 驱动启动** | 引擎读 `node_config.json` 的 `entry` 字段决定启动哪个入口文件 |
| **音频用 HTTP 直出，不走节点协议** | 前端 fetch → Web Audio API 播放 → 口型同步，不绕路 |

---

## 四、目标架构

### 节点层（引擎管理器统一启停）

```
pipeline.json:
  nodes: ["node_python_aaa_cognition", "node_python_llm_infer", "node_python_tts"]

引擎 `start_all()`:
  ├── Popen(["python", "main.py"], cwd=nodes/node_python_aaa_cognition)  → AAA
  ├── Popen(["python", "main.py"], cwd=nodes/node_python_llm_infer)      → LLM
  └── Popen(["python", "main.py", "--port", "8084"], cwd=nodes/node_python_tts) → TTS
```

**TTS 就是一个标准 BNOS Python 节点**，`node_config.json` 设置 `entry: "main.py"`，引擎直接 Popen 它。没有 listener，没有子进程管理。

### `main.py` 内部结构（单进程）

```python
# node_python_tts/main.py — 单进程，HTTP 服务 + BNOS 消息循环
import sys, json, threading

# 线程 1：HTTP 服务 (:8084)，供前端 fetch 音频
threading.Thread(target=http_server, args=(port,), daemon=True).start()

# 主线程：BNOS 消息循环（接收 AAA 的 reply）
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("data_type") == "reply":
        text = extract_text(msg["content"])
        emotion = extract_emotion(msg["content"])
        audio = synthesize(text, emotion)   # 合成
        play_audio(audio)                    # 直接播放
        cache_path = save_cache(audio)       # 写入 audio_cache/ 供 fetch
        print(json.dumps({
            "data_type": "reply",
            "status": "playing",
            "text": text,
            "emotion": emotion,
            "audio_url": f"/audio_cache/{cache_path}",
        }), flush=True)
```

### 数据流

```
节点层:
  AAA _on_parsed() → 解析节标记
    ├─ reply → output_reply.json（GUI server.py 轮询用）
    └─ port_mapping → TTS 节点 stdin
         {"data_type": "reply", "content": "[开心]你好呀", "request_id": "xxx"}
            ↓
         TTS main.py 收到
           ├─ 合成 → 直接播放（出声）
           ├─ 存 audio_cache/
           └─ stdout → {"status": "playing", "emotion": "开心", "text": "你好呀"}

GUI 层（唯一 Live2D 渲染出口）:
  gui/live2d/server.py (:3000)
    ├── 轮询 AAA 的 output_reply.json
    ├── 静态文件服务（renderer.js, Live2D 模型, audio_cache/）
    └── /output 端点 → 返回情绪+文字

  gui/live2d/renderer.js
    ├── 500ms 轮询 /output
    ├── 打字机效果（文字逐字出现）
    ├── 情绪切换（表情/动作）
    ├── fetch http://localhost:8084/tts?text=xxx → 播放 → AnalyserNode → 口型同步 ✅
    └── 文本驱动口型（fallback）

  gui/pages/live2d_page.py
    └── 模型选择/缩放/拖拽（不管理任何进程）

  gui/widgets/live2d_overlay.py
    └── 桌面悬浮窗（透明窗口, 鼠标视线跟随）
```

### 引擎管理方式

TTS 是标准 Python 节点，引擎不需要任何特殊处理：

```python
# engine.py / standalone_runner.py
# .py 节点统一走这个分支
proc = subprocess.Popen([str(python_exe), "main.py", "--port", "8084"],
                        cwd=node_path, ...)

# 停止时 taskkill /F 杀这一个进程
# 没有子进程，没有孤儿进程问题
```

---

## 五、具体改动

### 5.1 废弃的目录和文件

| 路径 | 说明 |
|------|------|
| `nodes/node_js_live2d_face/` | **整个目录废弃**，其 listener/main/live2d-server/renderer/ 不再维护 |

### 5.2 新建 `nodes/node_python_tts/`

| 文件 | 来源 | 说明 |
|------|------|------|
| `main.py` | 新建 | 节点入口（引擎直接拉起），HTTP 服务线程 + stdin 消息循环 + 音频合成播放 |
| `tts_engines/` | 从旧节点原样复制 | edge-tts / qwen3 / voxcpm2 等引擎适配器 |
| `emotion_expressions.json` | 从旧节点复制 | 情绪→表情映射 |
| `emotion_actions.json` | 从旧节点复制 | 情绪→动作映射 |
| `node_config.json` | 新建 | `entry: "main.py"`，定义 TTS 参数（端口、引擎、音色） |
| `requirements.txt` | 新建 | Python 依赖 |

`node_config.json` 内容：

```json
{
  "node_name": "node_python_tts",
  "language": "python",
  "entry": "main.py",
  "filter": {},
  "port_mappings": {},
  "input_ports": [
    {"name": "default", "label": "回复文本", "type": "text", "required": false, "source": "node"}
  ],
  "output_ports": [
    {"name": "default", "label": "状态反馈", "type": "json"}
  ],
  "parameters": [
    {"name": "port", "type": "int", "label": "HTTP 端口", "default": 8084},
    {"name": "engine", "type": "str", "label": "TTS 引擎", "default": "edge_tts"},
    {"name": "voice", "type": "str", "label": "音色", "default": "zh-CN-XiaoxiaoNeural"}
  ]
}
```

### 5.3 pipeline.json

```json
{
  "name": "BNOS_AI_project",
  "nodes": [
    "node_python_aaa_cognition",
    "node_python_llm_infer",
    "node_python_tts"
  ],
  "edges": [
    {"from": "node_python_aaa_cognition", "to": "node_python_llm_infer",
     "source_port": "prompt", "target_port": "prompt"},
    {"from": "node_python_llm_infer", "to": "node_python_aaa_cognition",
     "source_port": "default", "target_port": "llm_response"},
    {"from": "node_python_aaa_cognition", "to": "node_python_tts",
     "source_port": "reply", "target_port": "default"}
  ]
}
```

### 5.4 AAA 的改动

| 改动 | 说明 | 工作量 |
|------|------|:----:|
| `node_config.json` | `port_mappings` 中 `reply → live2d_face` 改为 `reply → tts` | 0.1h |
| `main.py` | 无需改动（reply 逻辑不变，port_mapping 决定目标节点） | 0 |

### 5.5 GUI 端的改动

| 文件 | 改动 | 工作量 |
|------|------|:----:|
| `gui/live2d/server.py` | 改读 `aaa_cognition/output_reply.json`（而非节点版 output_reply.json）；移除 `../nodes/node_js_live2d_face/` 依赖 | 0.5h |
| `gui/pages/live2d_page.py` | 移除 `_start_tts()`/`_stop_tts()` 方法；不再管理 TTS 进程 | 0.5h |
| `gui/live2d/renderer.js` | TTS URL 改为 `http://localhost:8084/tts`（和现在一样，不变） | 0 |

**总工作量**: 约 4-6h

---

## 六、变更汇总

| 维度 | 改前 | 改后 |
|------|------|------|
| `node_js_live2d_face` | 存在（JS 节点，含 listener/main/server/renderer/tts） | **废弃删除** |
| `node_python_tts` | 不存在 | **新建**，`entry: "main.py"`，无 listener，单进程 |
| AAA `port_mappings` | `reply → live2d_face` | `reply → tts` |
| `pipeline.json` | `node_js_live2d_face` | `node_python_tts` |
| TTS 进程管理 | 三方争抢（listener.js/ GUI / live2d-server.js） | 引擎管理器统一管理 |
| TTS HTTP 服务 | `tts_server.py` 作为子进程 | `main.py` 自身线程，无子进程 |
| Live2D 渲染 | 节点层 + GUI 层两套 | **GUI 层唯一出口** |
| 音频口型同步 | `fetch → AnalyserNode`，不变 | `fetch → AnalyserNode`，不变 |

---

## 七、向后兼容

| 影响维度 | 是否兼容 | 说明 |
|:--------:|:--------:|------|
| 现有输出文件 | ✅ | `output_reply.json` 位置不变，GUI 的 server.py 只需改读取路径 |
| 现有 GUI 用户 | ✅ | 渲染、TTS、悬浮窗、口型同步功能完全不变 |
| 现有 TTS 配置 | ✅ | `tts_engines/` 原样迁移 |
| 节点画布 | ✅ | 旧节点删除，新节点 `node_python_tts` 替代 |
| TTS 热开关 | ✅ | GUI 仍通过前端 `window.TTS_ENABLED` 控制是否发声 |
