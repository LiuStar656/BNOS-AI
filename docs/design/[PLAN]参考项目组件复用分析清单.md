# 参考项目组件复用分析清单

> 分析日期：2026-07-25 | **更新日期：2026-07-26**
> 分析对象：`references/mewco_ai_assistant_comm-main`(枫云AI助手), `references/my-neuro-main`(肥牛AI), `references/pub-local-jarvis-main`(AI Jarvis本地桌面助手)
> 
> **本次更新要点**：MemOS 语义检索已完成(集成到 aaa_cognition)、三阶段提示词重构完成、identity_key 多用户隔离上线、TTS 节点已独立、管线架构更新、新增 pub-local-jarvis-main 组件复用分析（感知算法/稳定性机制/提示词工程）

---

## 一、BNOS 现有节点总览

### 1.1 活跃管线节点

```
GUI输入 ──→ aaa_cognition(三阶段提示词+MemOS检索) ──→ llm_infer(LLM推理) ──→ aaa_cognition(解析+写库+索引重建)
                  ↑                                       │                         │
                  └── identity_key 全链路 ──────────────────┘                         │
                   (多用户隔离)                                                       ↓
                                                                              live2d_face(显示+TTS)
                                                                                    logseq_writer(知识归档)
```

### 1.2 所有节点功能矩阵

| # | 节点名 | 语言 | 功能 | 当前能力 | 短板 |
|---|--------|------|------|---------|------|
| 1 | `node_python_aaa_cognition` | Python | 数据中枢 | prompt构建(三阶段模板)/MemOS语义检索/节标记解析/路由/DB管理(11表)/identity_key多用户隔离/日记 | 无外部工具路由(Grok未接) |
| 2 | `node_python_llm_infer` | Python | LLM推理 | 云端API + 本地GGUF推理 | Function Calling原生支持弱，引擎少 |
| 3 | `node_js_live2d_face` | JS | 角色显示 | Live2D渲染 | 无内置TTS（已分流到独立 `node_python_tts`） |
| 4 | `node_python_tts` | Python | 语音合成 | edge-tts 在线合成，情绪标签过滤 | 引擎单一，仅1种在线引擎 |
| 5 | `node_python_asr_input` | Python | 语音识别 | Whisper文件识别 | 无麦克风录音、无声纹、无音频事件 |
| 6 | `node_python_env_input` | Python | 环境采集 | CPU/内存/时间 | 功能单一 |
| 7 | `node_python_logseq_writer` | Python | 知识归档 | 写入Logseq笔记 | 功能单一，运行良好 |
| 8 | `node_rust_grok_hands` | Rust | 工具执行 | 代码沙箱执行 | 功能单一 |
| 9 | `python_node_demo` | Python | 模板 | — | — |

---

## 二、从 mewco_ai_assistant_comm-main（枫云AI助手）可复用组件

mewco 为纯 Python 单体应用，模块可直接提取为独立节点。

### 2.1 ASR 语音识别 `asr.py` 【补全现有节点：增强 asr_input】

**源码**: [references/mewco_ai_assistant_comm-main/asr.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/asr.py)

| 特性 | 说明 |
|------|------|
| 核心引擎 | sherpa-onnx SenseVoice (zh/en/ja/ko/yue) |
| 录音方式 | PyAudio 实时麦克风采集，静音检测自动停止 |
| 声音活动检测 | 分贝满量程(dBFS)计算 |
| 声纹识别 | CAm++ 说话人嵌入模型，余弦相似度阈值验证 |
| 音频事件检测 | Zipformer 音频分类器，支持 40+ 种声音事件（喷嚏/猫叫/门铃等） |
| 情感识别 | SenseVoice 内置情感输出（HAPPY/SAD/ANGRY等） |

**建议**: 增强现有 `node_python_asr_input`，加入 sherpa-onnx 引擎 + 声纹 + 音频事件。

### 2.2 TTS 语音合成 `tts.py` 【增强现有节点：node_python_tts】

**源码**: [references/mewco_ai_assistant_comm-main/tts.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/tts.py)

| 特性 | 说明 |
|------|------|
| 支持引擎数 | 11 种 |
| 在线引擎 | edge-tts (多语种/多音色)、Paddle-TTS (百度翻译) |
| 离线引擎 | VITS-ONNX (内置低延迟)、ZipVoice (内置) |
| 本地 API 引擎 | GPT-SoVITS、OmniVoice、Qwen-TTS、Index-TTS、VoxCPM |
| 系统引擎 | pyttsx3 (Windows 自带) |
| 自定义引擎 | OpenAI 兼容 TTS API |
| 流式播放 | 可选按标点切片流式合成 |
| 播放控制 | 打断(alt+g)、音量放大、情感变化 |

**建议**: 当前 `node_python_tts` 仅有 edge-tts 基础引擎。参考 mewco 的 11 引擎实现扩展 `node_python_tts`，增加离线引擎和 GPT-SoVITS 等本地引擎支持。

### 2.3 VLM 多模态视觉 `vlm.py` 【新建节点】

**源码**: [references/mewco_ai_assistant_comm-main/vlm.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/vlm.py)

| 特性 | 说明 |
|------|------|
| 输入源 | 屏幕截图、摄像头、上传图片 |
| 核心能力 | 图像编码(base64) → VLM API |
| 支持引擎 | GLM-4.6V-Flash、千问Qwen3.5-4B、Ollama VLM、LM Studio、KoboldCpp、llama.cpp、自定义API-VLM |

**建议**: **新建 `node_python_vlm`**，为 aaa_cognition 提供视觉理解能力。

### 2.4 LLM 多Provider引擎 `llm.py` 【补全现有节点：扩展 llm_infer】

**源码**: [references/mewco_ai_assistant_comm-main/llm.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/llm.py)

| 特性 | 说明 |
|------|------|
| 引擎数量 | 12 种 |
| 云端引擎 | GLM-4.7-Flash、千问Qwen3-8B/3.5-4B、DeepSeek-R1-8B、星火Lite |
| 本地引擎 | Ollama、LM Studio、KoboldCpp、llama.cpp、Transformers |
| 平台引擎 | Dify 聊天助手、AnythingLLM 知识库 |
| 自定义引擎 | 任意 OpenAI 兼容 API |
| 记忆管理 | 4 级轮数限制（超长/长期/中期/短期） |
| 思维链过滤 | 自动去除 `</think>` 标记 |

**建议**: 参考其12引擎统一接口模式扩展现有 `node_python_llm_infer`。

### 2.5 Agent 工具集 `agent.py` 【补全现有节点：注册工具到 grok_hands】

**源码**: [references/mewco_ai_assistant_comm-main/agent.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/agent.py)

> `node_rust_grok_hands` 已是工具执行引擎，不需要另建节点。  
> mewco 的各类工具应作为**工具实现**注册到 grok_hands + aaa_cognition 体系内。

| 工具 | 说明 | 集成方式 |
|------|------|---------|
| 意图识别 | LLM 驱动的严格意图匹配 | 并入 `aaa_cognition` 的 prompt 构建逻辑 |
| 音乐播放 | data/music 目录 MP3 播放 | grok_hands 注册为 tool |
| 天气查询 | wttr.in API，自动提取城市名 | grok_hands 注册为 tool |
| 热搜新闻 | 微博热搜 + 中国新闻网 RSS + IT之家 | grok_hands 注册为 tool |
| 系统状态 | CPU/内存/GPU/网络延迟/ping | 已有 `env_input`，增强即可 |
| 视频生成 | CogVideoX-Flash 云端 | grok_hands 注册为 tool |
| 网页开发 | LLM 生成 HTML 代码并打开 | grok_hands 注册为 tool |
| PPT/Excel 生成 | Markdown→PPT/Excel 转换 | grok_hands 注册为 tool |
| Home Assistant | 智能家居灯/风扇/插座控制 | grok_hands 注册为 tool |
| AI 写作 | 自动文本输入 | grok_hands 注册为 tool |
| 屏幕操作 | 翻译/解释/总结/续写屏幕内容 | 依赖 VLM 节点，组合实现 |

### 2.6 联网搜索 `websearch.py` 【补全现有节点：注册工具到 grok_hands】

**源码**: [references/mewco_ai_assistant_comm-main/websearch.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/websearch.py)

| 特性 | 说明 |
|------|------|
| 搜索引擎 | 百度搜索（页面抓取） |
| 解析方式 | BeautifulSoup 解析 |
| 返回格式 | title + abstract + url + rank |

**建议**: 作为 grok_hands 的工具注册。

### 2.7 PC 操控 `agi_pc_lite.py` + `function.py` 【新建节点】

**源码**: [references/mewco_ai_assistant_comm-main/agi_pc_lite.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/agi_pc_lite.py) + [function.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/function.py)

| 特性 | 说明 |
|------|------|
| OCR 识别 | RapidOCR（OpenVINO 加速） |
| OCR 点击 | 文字识别后自动点击 |
| 音量控制 | pycaw 系统音量增减 |
| 自动输入 | keyboard 模拟键盘打字 |
| 屏幕浮球 | 圆形浮球菜单，支持拖拽 |

**建议**: **新建 `node_python_pc_control`**。

### 2.8 IM 机器人 `im_bot.py` 【新建节点】

**源码**: [references/mewco_ai_assistant_comm-main/im_bot.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/im_bot.py)

| 平台 | 接入方式 |
|------|---------|
| 钉钉 | dingtalk_stream (Stream 模式) |
| 飞书 | lark_oapi (WebSocket 模式) |
| QQ | botpy (C2C 消息) |

**建议**: **新建 `node_python_im_bot`**。

### 2.9 主动感知引擎 `ase.py` 【补全现有节点：可并入 aaa_cognition】

**源码**: [references/mewco_ai_assistant_comm-main/ase.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/ase.py)

| 特性 | 说明 |
|------|------|
| 活跃度 | 高(1-2min) / 中(4-6min) / 低(8-11min) |
| 触发方式 | 随机选择问候/VLM看图/上下文闲聊 |
| 场景 | 支持纯文本模式和多智能体模式 |

**建议**: 可并入 `aaa_cognition` 或独立节点，低优先级。

### 2.10 系统初始化与配置管理 `sys_init.py` 【补全现有节点：增强 AppConfig】

| 特性 | 说明 |
|------|------|
| 配置加载 | JSON 文件读写，130+ 项默认配置 |
| 配置热加载 | 运行时动态重载配置 |

**建议**: 参考其 `config.json` 的配置管理模式来增强现有 `AppConfig` 的配置持久化能力。

### 2.11 mewco 组件源路径汇总

| 组件 | 源文件 | 操作类型 |
|------|--------|---------|
| ASR 语音识别 | [asr.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/asr.py) | 补全 asr_input |
| TTS 语音合成 | [tts.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/tts.py) | 增强现有节点 |
| VLM 多模态视觉 | [vlm.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/vlm.py) | 新建节点 |
| LLM 多Provider引擎 | [llm.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/llm.py) | 补全 llm_infer |
| Agent 工具集 | [agent.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/agent.py) | 注册工具到 grok_hands |
| 联网搜索 | [websearch.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/websearch.py) | 注册工具到 grok_hands |
| PC 操控 | [agi_pc_lite.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/agi_pc_lite.py) + [function.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/function.py) | 新建节点 |
| IM 机器人 | [im_bot.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/im_bot.py) | 新建节点 |
| 主动感知引擎 | [ase.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/ase.py) | 补全 aaa_cognition |
| 配置管理 | [sys_init.py](file:///e:/杂项/BNOS_AI_project/references/mewco_ai_assistant_comm-main/sys_init.py) | 补全 AppConfig |

---

## 三、从 my-neuro-main（肥牛AI）可复用组件

肥牛AI 架构更复杂，核心价值在插件系统和记忆系统。

### 3.1 MemOS 记忆系统 【✅ 已完成 — 集成到 aaa_cognition】

**源码参考**: [plugins-dlc/memos/memos_system/](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/plugins-dlc/memos/memos_system/)

**实际实现位置**: [nodes/node_python_aaa_cognition/memos.py](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/memos.py)

> ⚠️ **注意区隔**: 已经通过 `node_python_logseq_writer` 做了**用户可见的知识笔记归档**（面向人）。  
> MemOS 解决的是**AI内部的语义记忆检索**（面向AI）—— 对话中实时查找相关记忆，与 Logseq 是互补关系，不是替代。

#### 3.1.1 实现总结

MemOS 已作为内建模块集成到 `aaa_cognition` 内，采用**轻量内嵌方案**（非 Qdrant 独立服务）：

| 组件 | 技术选型 | 与参考方案差异 |
|------|---------|--------------|
| **向量编码** | SentenceTransformer (`all-MiniLM-L6-v2`) | 同参考，但无 Qdrant 依赖 |
| **向量存储** | in-memory `np.ndarray` + `.npz` 持久化 | 轻量化，替换 Qdrant |
| **检索算法** | numpy 余弦相似度 | 内置计算，无网络开销 |
| **索引维护** | 增量重建（每次回复后异步追加） | 无感知延迟 |
| **检索时机** | 两轮交互：LLM 先决定是否需检索，AAA 再执行 | 按需检索，避免每次必查 |
| **用户隔离** | `_entry_identity_keys` 数组 + identity_key 过滤 | 新增，参考方案无此能力 |
| **LLM记忆加工** | 异步摘要 + 重要性评分 + decay 机制 | 后添加补全 |

#### 3.1.2 已实现的能力

- ✅ 真实语义向量嵌入（替代旧 FAISS hash）
- ✅ 三个模板（prompt/prompt_retrieval/prompt_tool）按场景分流
- ✅ 两轮交互：薄 prompt → LLM 判断 → 按需检索 → 第二轮带结果
- ✅ 按 identity_key 用户隔离检索
- ✅ 增量索引重建（不阻塞主线程）
- ✅ 知识图谱索引（`rebuild_knowledge_index`，供 Logseq 关联用）
- ✅ 去重合并（Jaccard 相似度）+ 重要性/decay 机制

#### 3.1.3 未实现（可后续补）

- Qdrant / FAISS 硬索引（当前 in-memory 数组重启重建，但增量很快）
- LLM 驱动的记忆摘要与重要性评分（当前用简单 decay，可升级）
- 多类型记忆（图像/偏好/工具 — 当前只做文本）

### 3.2 MCP 协议支持 【补全现有节点：集成进 grok_hands】

**源码**: [live-2d/js/ai/mcp-manager.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/js/ai/mcp-manager.js)

> `node_rust_grok_hands` 已是工具执行引擎。MCP 协议支持应**集成进 grok_hands**，而不是另建节点。

| 特性 | 说明 | 集成方式 |
|------|------|---------|
| 传输层 | stdio + HTTP 双模式 | grok_hands 添加 MCP client 支持 |
| 工具注册 | MCPToolRegistry 统一管理 | 扩展 grok_hands 的工具注册表 |
| 自动同步 | tools 文件夹自动扫描 | 可选功能 |

**建议**: 低优先级，作为 grok_hands 的增强功能（P3），先专注直接工具注册即可。

### 3.3 插件热加载架构 【架构参考，不直接复用】

**源码**: [live-2d/js/core/plugin-manager.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/js/core/plugin-manager.js)

| 特性 | 说明 |
|------|------|
| 热加载 | enabled_plugins.json 驱动，支持运行时增减 |
| 分三层 | built-in / community / marketplace |
| 元数据驱动 | metadata.json 声明插件信息 |
| 工具注册 | 插件通过 context.registerTool 动态注册 |
| 文件监听 | 源码变更自动重载 |

**建议**: **架构参考**，如果将来 BNOS 要做插件市场，此设计可直接借鉴。

### 3.4 内置插件清单（23个）

> 源路径前缀: `references/my-neuro-main/live-2d/plugins/built-in/`

| 插件 | 源路径 | 功能 | 复用 |
|------|--------|------|------|
| `web-search` | [web-search/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/web-search/index.js) | Tavily 联网搜索 | ✅ 工具类 |
| `web-navigator` | [web-navigator/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/web-navigator/index.js) | 浏览器网页导航 | ✅ 工具类 |
| `pc-control` | [pc-control/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/pc-control/index.js) | 基于VLM的屏幕元素点击 | ✅ 工具类 |
| `code-executor` | [code-executor/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/code-executor/index.js) | 代码执行 | 已有 grok_hands |
| `music` | [music/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/music/index.js) | 音乐播放（分离伴奏/人声） | ✅ 工具类 |
| `screenshot` | [screenshot/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/screenshot/index.js) | 截图 | ✅ VLM前置 |
| `translation` | [translation/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/translation/index.js) | 翻译 | ✅ 工具类 |
| `schedule` | [schedule/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/schedule/index.js) | 日程管理 | ✅ 工具类 |
| `diary` | [diary/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/diary/index.js) | AI 日记 | ✅ 可并入 memos |
| `memos` | [memos/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/memos/index.js) | 记忆系统插件 | ✅ 并入 memos |
| `rag-memory` | [rag-memory/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/rag-memory/index.js) | RAG增强检索 | ✅ 并入 memos |
| `mood-chat` | [mood-chat/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/mood-chat/index.js) | 情绪对话 | ⚠️ 参考价值有限 |
| `note` | [note/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/note/index.js) | 笔记功能 | ❌ 已有 logseq_writer |
| `bilibili-live` | [bilibili-live/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/bilibili-live/index.js) | B站直播集成 | ✅ 独立功能 |
| `minecraft` | [minecraft/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/minecraft/index.js) | 游戏内聊天 | ⚠️ 小众场景 |
| `sfx` | [sfx/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/sfx/index.js) | 音效播放 | ✅ 低优先级 |
| `auto-chat` | [auto-chat/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/auto-chat/index.js) | 自动聊天 | ✅ 参考ASE |
| `keyboard` | [keyboard/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/keyboard/index.js) | 键盘快捷键 | ❌ GUI 层功能，不应下沉到节点 |
| `mouse-click` | [mouse-click/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/mouse-click/index.js) | 鼠标点击 | ✅ 并入 pc_control |
| `typing` | [typing/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/typing/index.js) | 自动打字 | ✅ 并入 pc_control |
| `wait` | [wait/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/wait/index.js) | 等待/延时 | ✅ 工具类 |
| `ai-log` | [ai-log/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/ai-log/index.js) | AI日志记录 | ✅ 并入 logseq_writer |
| `context-compressor` | [context-compressor/index.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/plugins/built-in/context-compressor/index.js) | 上下文压缩 | ❌ 不适用（aaa的摘要机制已解决窗口膨胀问题） |

### 3.5 上下文压缩（不适用）

**源码**: [live-2d/js/ai/ContextCompressor.js](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/js/ai/ContextCompressor.js)

**说明**: aaa_cognition 的 prompt 设计已用 `{history_summary}`（最新 N 条事件摘要）替代原始对话原文的历史上下文，不存在 token 膨胀问题。ContextCompressor 的上下文窗口裁剪能力在 BNOS 体系中不适用。

### 3.6 语音对话管线架构 【架构参考】

**源码**: [live-2d/js/ai/conversation/](file:///e:/杂项/BNOS_AI_project/references/my-neuro-main/live-2d/js/ai/conversation/)

| 模块 | 说明 |
|------|------|
| VoiceChatFacade.js | 统一对外接口 |
| ConversationCore.js | 核心对话逻辑 |
| ASRController.js | ASR 控制器 |
| InputRouter.js | 消息路由（拦截/合并/分发） |
| MessageInitializer.js | 消息初始化（系统提示词等） |

**建议**: 其 **InputRouter** 的消息路由设计思路可用于改进 `aaa_cognition` 的输入处理。

### ~~3.7 WebUI 控制面板（不适用）~~

项目走 PySide6 GUI 路线，my-neuro-main 的 Flask WebUI 不适用，跳过。

---

## 四、从 pub-local-jarvis-main（AI Jarvis）可复用组件

> 分析对象：`references/pub-local-jarvis-main`
> 项目定位：本地全双工桌面 AI 助手（C++20 原生 Worker + Python FastAPI + Electron）
> 复用原则：**算法移植，不复用框架代码**。jarvis 用 C++ 实现，BNOS 用 Python，但感知算法和稳定性机制可直接重写。

### 4.1 感知层算法（填补 vision_input 空白）

| 组件 | jarvis 源文件 | 核心价值 | BNOS 适配方式 | 操作类型 |
|------|-------------|---------|-------------|---------|
| 帧变化检测 | `native/src/fingerprint.cpp` | 32×18网格采样+FNV-1a哈希+双阈值(3%像素/3.0均值) | Python重写，嵌入vision_input内部 | 新建节点辅助 |
| 空闲检测 | `native/src/fingerprint.cpp` | 2分钟无变化进入空闲，随机提醒60-120s | Python重写，嵌入env_input或aaa | 补全现有节点 |
| DXGI屏幕采集 | `native/src/windows/dxgi_capture.cpp` | Desktop Duplication+GDI降级双路径 | 用Python mss/dxcam替代，降级思路参考 | 新建节点辅助 |

### 4.2 音频处理算法（增强 asr_input）

| 组件 | jarvis 源文件 | 核心价值 | BNOS 适配方式 | 操作类型 |
|------|-------------|---------|-------------|---------|
| 降混单声道 | `native/src/audio.cpp` | 多声道->单声道，clamp[-1,1] | Python重写(纯numpy) | 补全asr_input |
| 线性插值重采样 | `native/src/audio.cpp` | 48kHz->16kHz，零依赖 | Python重写(纯numpy) | 补全asr_input |
| 精确窗口组装器 | `native/src/audio.cpp` | 保证音频窗口完整不截断 | Python重写(纯numpy) | 补全asr_input |
| 有声检测RMS | `native/src/worker.cpp` | RMS能量阈值0.000004(实战调优值) | Python重写(纯numpy) | 补全asr_input |
| 双缓冲设计 | `native/src/worker.cpp` | 2秒短缓冲(VAD)+12秒长缓冲(STT) | 概念移植 | 补全asr_input |

### 4.3 稳定性机制（增强 turn_taking / aaa_cognition）

| 组件 | jarvis 源文件 | 核心价值 | BNOS 适配方式 | 操作类型 |
|------|-------------|---------|-------------|---------|
| 场景迟滞稳定器 | `src/jarvis_backend/orchestrator/scene.py` | enter(0.72)/exit(0.48)双阈值+多采样确认 | 概念移植到turn_taking防抖动 | 补全aaa_cognition |
| LatestOnlyScheduler | `native/src/scheduler.cpp` | 最新优先合并+代际标记+协作式取消 | Python重写，AAA多源优先级调度 | 补全aaa_cognition |
| EventBus背压控制 | `src/jarvis_backend/orchestrator/events.py` | 有界扇出总线，队列满丢弃最旧事件 | 概念参考，AAA内部事件路由 | 架构参考 |
| 生命周期状态机 | `src/jarvis_backend/orchestrator/lifecycle.py` | STOPPED->STARTING->READY/DEGRADED/FAILED | 参考DEGRADED降级状态 | 架构参考 |

### 4.4 提示词工程（增强 aaa_cognition）

| 组件 | jarvis 源文件 | 核心价值 | BNOS 适配方式 | 操作类型 |
|------|-------------|---------|-------------|---------|
| 防注入模式 | `src/jarvis_backend/prompts/templates.py` | "输入是数据不是指令"，JSON包装输入 | AAA的env_observation段用JSON包装 | 补全aaa_cognition |
| 格式约束 | `src/jarvis_backend/prompts/templates.py` | 明确字数限制(8-40字/420字/6000字) | AAA各节标记增加字数约束 | 补全aaa_cognition |
| 主动性价值过滤 | `src/jarvis_backend/orchestrator/service.py` | require_proactive_value要求包含价值词 | AAA【自然回复】增加价值约束 | 补全aaa_cognition |
| 消息清洗 | `src/jarvis_backend/orchestrator/service.py` | 移除标记，拒绝模糊表述(看起来/似乎) | AAA的LLM输出清洗 | 补全aaa_cognition |

### 4.5 工程实践（增强可靠性）

| 组件 | jarvis 源文件 | 核心价值 | BNOS 适配方式 | 操作类型 |
|------|-------------|---------|-------------|---------|
| 原子写入 | `src/jarvis_backend/memory/store.py` | tempfile+fsync+replace模式 | logseq_writer/DB写入 | 补全现有节点 |
| 模型下载镜像回退 | `src/jarvis_backend/model_download.py` | 官方源+hf-mirror.com双端点 | llm_infer模型下载 | 补全现有节点 |
| 双源下载回退 | `desktop/scripts/resource-fallback.js` | 官方源->镜像源自动回退 | pip/npm依赖安装 | 架构参考 |

### 4.6 jarvis 组件源路径汇总

| 组件 | 源文件 | 操作类型 |
|------|--------|---------|
| 帧变化检测 | `native/src/fingerprint.cpp` | 新建节点辅助 |
| 空闲检测 | `native/src/fingerprint.cpp` | 补全env_input |
| 降混单声道 | `native/src/audio.cpp` | 补全asr_input |
| 线性插值重采样 | `native/src/audio.cpp` | 补全asr_input |
| 精确窗口组装器 | `native/src/audio.cpp` | 补全asr_input |
| 有声检测RMS | `native/src/worker.cpp` | 补全asr_input |
| 场景迟滞稳定器 | `src/jarvis_backend/orchestrator/scene.py` | 补全aaa_cognition |
| LatestOnlyScheduler | `native/src/scheduler.cpp` | 补全aaa_cognition |
| 防注入模式 | `src/jarvis_backend/prompts/templates.py` | 补全aaa_cognition |
| 原子写入 | `src/jarvis_backend/memory/store.py` | 补全现有节点 |
| 模型下载镜像回退 | `src/jarvis_backend/model_download.py` | 补全llm_infer |

### 4.7 不可复用组件

| jarvis 组件 | 不可复用原因 |
|------------|-------------|
| C++命名管道协议 | BNOS用文件JSON通信 |
| Electron桌面端 | BNOS用PySide6 |
| FastAPI HTTP API | BNOS节点不暴露HTTP |
| llama.cpp-omni全双工 | BNOS的LLM交互模式不同 |
| NSIS打包流水线 | BNOS用PyInstaller |

---

## 五、最终优先级路线图

### P0 - 必须补的核心能力 ✅ MemOS 已完成

> MemOS 语义检索已作为内建模块集成到 `aaa_cognition` 内（`memos.py`），替代了旧 FAISS hash 伪向量检索。  
> 详情见 [3.1 MemOS 记忆系统](#31-memos-记忆系统--已完成--集成到-aaa_cognition)。

### P1 - 增强对话体验

| 优先级 | 建议节点名 | 源项目 | 源文件 | 核心价值 | 操作类型 | 预估工作 |
|--------|-----------|--------|--------|---------|---------|---------|
| P1 | **node_python_tts** | mewco | `tts.py` | 扩展现有节点，从1种引擎增加到11种（含离线引擎） | 增强现有节点 | 1-2天 |
| P1 | **增强 asr_input** | mewco | `asr.py` | sherpa-onnx+声纹+音频事件 | 补全现有节点 | 1-2天 |
| P1 | **node_python_vlm** | mewco | `vlm.py` | 屏幕/摄像头/图片理解 | 新建节点 | 1-2天 |
| P1 | **audio_utils.py** | jarvis | `audio.cpp`+`worker.cpp` | 降混/重采样/窗口组装/有声检测(纯numpy) | 补全asr_input | 0.5天 |
| P1 | **场景迟滞稳定器** | jarvis | `scene.py` | 双阈值+多采样确认，防turn_taking抖动 | 补全aaa_cognition | 0.5天 |
| P1 | **提示词防注入** | jarvis | `templates.py` | "输入是数据不是指令"，JSON包装 | 补全aaa_cognition | 0.5天 |
| P1 | **LatestOnlyScheduler** | jarvis | `scheduler.cpp` | 多源优先级调度+代际标记 | 补全aaa_cognition | 0.5天 |

### P2 - 扩展Agent能力

| 优先级 | 建议节点名 | 源项目 | 源文件 | 核心价值 | 操作类型 | 预估工作 |
|--------|-----------|--------|--------|---------|---------|---------|
| P2 | **注册工具到 grok_hands** | mewco | `agent.py` | 天气/新闻/HA/Office等工具 | 补全现有节点 | 1-2天 |
| P2 | **注册搜索工具到 grok_hands** | mewco | `websearch.py` | 联网搜索 | 补全现有节点 | 1天 |
| P2 | **node_python_pc_control** | mewco | `agi_pc_lite.py`+`function.py` | OCR屏控/音量/自动输入 | 新建节点 | 1-2天 |
| P2 | **node_python_im_bot** | mewco | `im_bot.py` | 飞书/钉钉/QQ多渠道 | 新建节点 | 1-2天 |
| P2 | **帧变化检测** | jarvis | `fingerprint.cpp` | 32×18网格+双阈值，避免每帧调VLM | 新建节点辅助 | 0.5天 |
| P2 | **空闲检测** | jarvis | `fingerprint.cpp` | 2分钟无变化进入空闲+随机提醒 | 补全env_input | 0.3天 |
| P2 | **原子写入** | jarvis | `store.py` | tempfile+fsync+replace崩溃安全 | 补全现有节点 | 0.2天 |
| P2 | **模型下载镜像回退** | jarvis | `model_download.py` | 官方源+hf-mirror.com回退 | 补全llm_infer | 0.5天 |

### P3 - 锦上添花

| 优先级 | 建议节点名 | 源项目 | 源文件 | 核心价值 | 操作类型 | 预估工作 |
|--------|-----------|--------|--------|---------|---------|---------|
| P3 | **ASE主动感知** | mewco | `ase.py` | AI主动发起对话 | 补全现有节点(并入aaa_cognition) | 1天 |
| P3 | **配置管理增强** | mewco | `sys_init.py` | 配置持久化与热加载 | 补全现有节点(增强AppConfig) | 0.5天 |

---

## 六、当前管线架构（更新于 2026-07-26）

```
                             ┌→ vlm(视觉理解) ──┐
                             │                    │
ASR(语音) ──→               │                    ↓
GUI输入 ───→  aaa_cognition ──→ llm_infer ──→ aaa_cognition ──→ live2d_face(显示+TTS)
环境输入 ──→  (三阶段prompt+   ↑      ↑        (解析分发+        TTS(语音合成)
             MemOS语义检索+    │      │         写库+索引重建)
             identity_key     │      │              │
             多用户隔离)      │   memos ─────────────┘
                              │   (内建于aaa_cognition → 按需检索)
                              │         │              ↓
                              │         └──→ → → → → logseq_writer
                              │           (记忆关联持久化)
                              │
                         grok_hands — 待注册工具(天气/搜索/HA等)
```

### 相比原计划的关键变更

| 维度 | 原计划 | 当前状态 |
|------|--------|---------|
| MemOS | 独立节点 `node_python_memos` + Qdrant | 内建模块 `memos.py` + numpy 余弦相似度 |
| 提示词 | 单模板混合输出 | 三阶段模板（prompt/prompt_retrieval/prompt_tool） |
| 用户隔离 | 无 | identity_key 全链路（DB/检索/提示词） |
| TTS | JS 节点内嵌 | 已有独立 `node_python_tts`（需增强引擎数） |
| Grok | Rust 基础框架 | 仍为 Rust 框架，工具未注册 |
| 感知算法 | 无（vision_input未实现） | jarvis帧变化检测+音频处理算法可复用 |

---

*本文档由 AI 自动生成，基于对三个参考项目的完整源码分析。*
