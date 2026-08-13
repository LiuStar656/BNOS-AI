# Airi & SillyTavern 组件复用分析

> 日期：2026-07-27 | 版本：v1.0 | 状态：[ANALYSIS]
> 来源：`references/airi-main`、`references/SillyTavern-release`

## BNOS 设计约束（复用过滤策略）

1. **一用户对应一 AI** — AI 记忆深度绑定数据库，不是可随意替换的角色卡
2. **已有 grok_hands 工具系统** — 工具调用/MCP 已被 grok build 覆盖
3. **BNOS 是节点化架构** — 节点间通过合约匹配的 JSON 文件协议通信，非单体调用

---

## 一、Airi 项目概况

**仓库**：[airi-main](file:///e:/杂项/BNOS_AI_project/references/airi-main)

Airi 是一个"Neuro-sama 复刻"——一个赛博生命体容器（AI 伴侣/虚拟角色）。Monorepo 架构，三个前端入口：Stage Web（浏览器 PWA）、Stage Tamagotchi（Electron 桌面）、Stage Pocket（Capacitor 移动端）。

**技术栈**：Vue 3 + Pinia + Vite + TypeScript + UnoCSS；Hono（Node.js 服务端）+ Drizzle ORM + PostgreSQL；`@moeru/eventa`（IPC/RPC）；`injeca`（DI）

### 核心架构图

```
┌──────────────────────────────────────────────────────────┐
│                    Agent Runtime (core-agent)              │
│  Ports: SessionPort │ LLMPort │ ContextPort │ StreamPort  │
│           ↓                ↓              ↓               │
│  ChatOrchestratorRuntime (DI 注入，环境无关)                 │
│    ┌──────────────────────────────────────────────────┐   │
│    │  Hook 系统：beforeSend │ onToken │ onStreamEnd   │   │
│    │  ContextRegistry：多源上下文注入                   │   │
│    │  ResponseCategorizer：LLM 响应分类路由              │   │
│    └──────────────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────┤
│                    Plugin / Extension Host                 │
│  插件生命周期: announced → preparing → configured → ready  │
│  插件类型: Local (in-process) / Remote (WebSocket)         │
│  Kit APIs: resources │ permissions │ sessions │ bindings   │
├──────────────────────────────────────────────────────────┤
│                    Services (独立 Node 进程)                │
│  minecraft (4层认知) │ discord-bot │ telegram-bot         │
│  satori-bot │ computer-use-mcp │ twitter-services         │
└──────────────────────────────────────────────────────────┘
```

---

## 二、SillyTavern 项目概况

**仓库**：[SillyTavern-release](file:///e:/杂项/BNOS_AI_project/references/SillyTavern-release)（v1.18.0）

SillyTavern 是 LLM 前端社区最成熟的项目之一，以丰富的提示工程能力和社区插件生态著称。

**技术栈**：Node.js (Express) + vanilla JS (ES modules) + jQuery；Handlebars 模板引擎；chevrotain 解析器（宏系统）；sentence-transformers (ONNX) 客户端嵌入

### 核心架构图

```
┌──────────────────────────────────────────────────────────┐
│                    Prompt Engineering Layer               │
│  PromptManager ── PromptCollection ── Injection Engine   │
│    (位置/深度/顺序/触发器控制)                              │
│  ├─ System Prompt Layer (main/nsfw/jailbreak)             │
│  ├─ Context Layer (story_string/example_separator)        │
│  ├─ Instruct Layer (input/output/system sequences)        │
│  ├─ World Info Layer (lorebook/keyword matching)          │
│  ├─ Character Layer (description/personality/scenario)    │
│  └─ Macro System (chevrotain-based parser)               │
├──────────────────────────────────────────────────────────┤
│                    Extension System                        │
│  16 内置扩展: memory │ vectors │ regex │ tts │ translate  │
│  Manifest 加载: manifest.json → event hooks → API surface │
├──────────────────────────────────────────────────────────┤
│                    Backend Adapters                        │
│  20+ LLM/API 后端: OpenAI │ Claude │ Gemini │ Ollama ...  │
│  Text Completions │ Chat Completions │ NovelAI │ Horde    │
└──────────────────────────────────────────────────────────┘
```

---

## 三、核心模块逐项分析

### 3.1 提示词模板引擎（SillyTavern — PromptManager.js）

**源码**：[PromptManager.js](file:///e:/杂项/BNOS_AI_project/references/SillyTavern-release/public/scripts/PromptManager.js)

SillyTavern 最成熟的模块之一，支持多层嵌套的提示词构建。

#### Prompt 数据模型

```javascript
Prompt {
  identifier: string,
  role: 'system'|'user'|'assistant',
  content: string,
  position: string|number,
  injection_position: RELATIVE(0)|ABSOLUTE(1),
  injection_depth: number,
  injection_order: number,
  forbid_overrides: boolean,
  injection_trigger: string[]  // 按生成类型触发
}
```

#### 注入系统

- **INJECTION_POSITION**: `RELATIVE`（基于聊天的深度位置）或 `ABSOLUTE`（固定位置）
- **深度控制**: 提示词在聊天历史中的深度，可精确控制出现在第几条消息附近
- **顺序控制**: 同一深度下的提示词排序
- **触发器控制**: 按生成类型（normal/continue/impersonate）选择性注入
- **可覆盖**: `main` 和 `jailbreak` 支持被角色卡覆盖

#### 渲染管线

1. Dry-run 模拟上下文填充 → 2. Token 计数 → 3. 可拖拽排序 → 4. 快速编辑 → 5. 导入/导出

#### 30+ 预设模板（context/instruct/sysprompt/reasoning）

| 预设类型 | 数量 | 示例 |
|---------|:---:|------|
| context | 36 | Default, Adventure, ChatML, Llama 3, Mistral, NovelAI... |
| instruct | 38 | Alpaca, ChatML, Command R, DeepSeek, Llama 3, Vicuna... |
| sysprompt | 13 | Actor, Roleplay, Story, Chain of Thought, Expert... |
| reasoning | 5 | DeepSeek, OpenAI Harmony, Think XML... |

#### 对 BNOS 的价值

BNOS 的 AAA prompt 构建相对简单。SillyTavern 的注入引擎可以提供：
- **分层的 prompt 优先级**：AI 种子性格 → 用户画像 → 对话历史 → Lorebook → 输出格式约束
- **按触发类型注入**：普通对话 vs 继续 vs 仿写的不同 prompt 配方
- **深度位置控制**：长上下文中的 prompt 注入策略

**工作量参考**：约 2 天（基于现有 AAA prompt 构建流程改造）

---

### 3.2 World Info / Lorebook 引擎（SillyTavern）→ BNOS 独立设计

**源码参考**：[world-info.js](file:///e:/杂项/BNOS_AI_project/references/SillyTavern-release/public/scripts/world-info.js)

> **BNOS 不直接复用 SillyTavern 的 World Info，而是从其理念引发独立设计：AI 世界感知记忆系统**
> 详见：[PLAN]-AI世界感知记忆系统设计方案.md

SillyTavern 的 Lorebook 是一个**静态**的上下文注入引擎——需要人工编写条目。其设计本身有参考价值，但 BNOS 的需求是**动态、自积累**的：

#### 匹配逻辑

```javascript
world_info_insertion_strategy = {
  evenly: 0,           // 角色和世界均匀分布
  character_first: 1,  // 角色优先
  global_first: 2      // 全局优先
}
world_info_logic = {
  AND_ANY: 0,  // 主键或次键任一匹配
  NOT_ALL: 1,  // 主键和次键都不匹配
  NOT_ANY: 2,  // 任一个不匹配
  AND_ALL: 3   // 主键和次键都匹配
}
```

#### 扫描系统

- **深度缓冲区**：扫描最多 1000 条消息的深度
- **递归缓冲区**：递归扫描支持嵌套匹配
- **注入缓冲区**：控制注入 prompt 的位置
- **偏斜系统**：最小激活次数控制

#### 时序效果

| 效果 | 说明 |
|------|------|
| **Sticky** | 条目首次激活后持续 N 条消息 |
| **Cooldown** | 条目激活后 N 条消息内不可重激活 |
| **Delay** | 条目在 N 条消息后激活 |
| **Protected** | 条目不会被后续匹配移除 |

#### 输出类别

- `worldInfoString`：完整 WI 字符串
- `worldInfoBefore`/`worldInfoAfter`：在 prompt 之前/之后的 WI
- `worldInfoExamples`：示例条目
- `worldInfoDepth`：基于深度的条目
- `outletEntries`：命名注入点

#### 对 BNOS 的价值

BNOS 有 MemOS（向量检索），但没有世界设定引擎。SillyTavern 的 WI 提供了：
- **关键词+正则匹配**：比纯向量检索更轻量、更可控
- **时序控制**：Sticky/Cooldown/Delay 让设定不是一次性注入，而是持续影响
- **注入位置控制**：before/after/depth 控制设定出现在 prompt 的哪里
- **角色绑定**：一个角色可以有多个 lorebook

**工作量参考**：约 2 天（基于现有 MemOS 的向量检索基础 + 新增关键词匹配层）

---

### 3.3 宏系统（SillyTavern）

**源码**：[macros.js](file:///e:/杂项/BNOS_AI_project/references/SillyTavern-release/public/scripts/macros.js)

基于 **chevrotain** 解析器的完整宏系统。

#### 引擎架构

```
MacroLexer (Tokenizer) → MacroParser (CST) → MacroCstWalker (Interpreter)
```
- `MacroRegistry.js` — 宏注册中心
- `MacroEngine.js` — 主引擎
- `MacroEnvBuilder.js` — 环境变量构建
- `MacroBrowser.js` — 宏浏览器 UI
- `MacroDiagnostics.js` — 错误报告

#### 内置宏类别

| 类别 | 宏示例 |
|------|--------|
| Core | `{{input}}`, `{{lastMessage}}`, `{{char}}`, `{{user}}` |
| Chat | `{{chatHistory}}`, `{{allMessages}}`, `{{messageCount}}` |
| Environment | `{{time}}`, `{{date}}`, `{{weekday}}` |
| Instruct | `{{instruction}}` |
| State | `{{getvar}}`, `{{setvar}}` |
| Variable | `{{var::name}}` |

#### 对 BNOS 的价值

BNOS 目前没有宏系统。prompt 构建是 Python 字符串拼接。引入宏系统的好处：
- **在 node_config.json 中使用宏**：如 `{character}对{user}说：{content}`
- **模板化 prompt**：与角色种子系统的性格向量配合
- **运行时变量**：当前时间、上下文长度、对话轮数等

**工作量参考**：约 1-2 天（可以用 Python 的 `string.Template` 或 Jinja2 轻量实现，不需自己写解析器）

---

### 3.4 RAG / 向量检索系统（SillyTavern）

**源码**：[extensions/vectors/index.js](file:///e:/杂项/BNOS_AI_project/references/SillyTavern-release/public/scripts/extensions/vectors/index.js)

#### Embedding 源

| 源 | 类型 | 说明 |
|-------|------|------|
| Transformers.js | 本地 | ONNX 浏览器内推理 |
| OpenAI / OpenRouter | 云端 | API 调用 |
| Cohere / Ollama / vLLM | 云端 | 第三方 API |
| WebLLM | 本地 | 浏览器内 LLM |

#### 功能特性

| 功能 | 说明 |
|------|------|
| **聊天向量化** | 每条消息嵌入到向量索引 |
| **Data Bank** | 文件附件独立嵌入 |
| **WI 集成** | 可选将 WI 内容包含到向量搜索 |
| **摘要嵌入** | 先在嵌入前做摘要（减少 token 量） |
| **分块** | 可配置的消息分块大小 + 分隔符 |
| **评分阈值** | 嵌入相似度打分 + 可配置阈值 |
| **渐进扫描** | 分批处理 + 进度跟踪 |

#### 配置参数

```javascript
settings = {
  depth: 2,          // 扫描深度
  protect: 5,        // 保护最近的 N 条消息
  insert: 3,         // 插入多少条检索结果
  query: 2,          // 查询最近的消息数
  message_chunk_size: 400,
  score_threshold: 0.25,
}
```

#### 对 BNOS 的价值

BNOS 的 MemOS 已有 numpy 内置的语义向量检索引擎（SentenceTransformer + @ 内积）。SillyTavern 提供的补充：
- **Data Bank**：文件附件索引（BNOS 没有文件级别的记忆增强）
- **摘要嵌入**：先在嵌入前做摘要，减少向量索引大小
- **渐进扫描**：分批处理的性能优化模式
- **评分阈值控制**：可配置的相似度阈值

**工作量参考**：约 1 天（Data Bank + 摘要嵌入）

---

### 3.5 Airi Agent Runtime（端口适配器模式）

**源码**：[packages/core-agent/src/index.ts](file:///e:/杂项/BNOS_AI_project/references/airi-main/packages/core-agent/src/index.ts)

Airi 的核心 Agent 运行时使用**端口适配器（六边形架构）**：

```typescript
// 抽象端口
interface AgentSessionPort { createSession(), getSession(), appendMessages() }
interface AgentLLMPort { stream() }
interface AgentContextPort { ingest(), snapshot() }
interface AgentForegroundStreamPort { patch(), reset() }

// DI 注入的具体实现
const runtime = createChatOrchestratorRuntime({
  session: concreteSessionPort,
  llm: concreteLLMPort,
  context: concreteContextPort,
  stream: concreteStreamPort,
})
```

#### Hook 系统

10+ 生命周期 hooks：
```typescript
beforeMessageComposed → afterSend → onTokenLiteral → 
onStreamEnd → onChatTurnComplete → onAssistantResponseEnd
```

#### Context Registry（多源上下文注入）

```typescript
const context = createContextRegistry()
// 任何模块都可以注入上下文（网页搜索、游戏状态、日历...）
context.ingest({ lane: 'system', text: '当前游戏状态：...' })
// 注入策略：ReplaceSelf（替换同类）/ AppendSelf（追加）
```

#### 对 BNOS 的价值

BNOS 的 AAA 节点用 `main.py` 做编排，逻辑是线性的。Airi 的端口适配器模式提供了：
- **AAA 节点重构参考**：将 `_on_text()` → `_on_llm_response()` 等回调抽象为端口
- **Hook 系统**：支持插件/扩展在生命周期中注入行为（如：在 LLM 返回后先触发工具调用）
- **Context Registry**：多源上下文注入（ASR + 环境 + 视觉），对应 BNOS 的多输入端口

---

### 3.6 Airi 插件/扩展主机系统

**源码**：[packages/plugin-sdk/](file:///e:/杂项/BNOS_AI_project/references/airi-main/packages/plugin-sdk/)

Airi 的插件系统设计很完整，包含：

| 组件 | 说明 |
|------|------|
| **扩展系统** | 扩展声明 capability、permission、config schema |
| **插件主机** | 管理插件生命周期（load/unload/reload），支持 Node/Web 运行环境 |
| **本地/远程插件** | 本地（in-process）或远程（WebSocket）两种加载方式 |
| **Kit APIs** | 提供给扩展的 API 表面：resources、permissions、kits、sessions |
| **通道抽象** | `channels/local/event-target/` 和 `channels/remote/websocket/` |

#### 模块生命周期

```
announced → preparing → prepared → configuration-needed → configured → ready → failed
```

#### 事件协议（100+ 定义事件）

| 事件类别 | 示例 |
|---------|------|
| 模块事件 | announce, prepare, configure, status, capability |
| 权限事件 | declare, request, granted, denied |
| 输入事件 | `input:text`, `input:text:voice`, `input:voice` |
| 输出事件 | `output:gen-ai:chat:message`, `output:gen-ai:chat:complete` |
| Spark 事件 | `spark:notify`, `spark:command`, `spark:emit` |
| 上下文事件 | `context:update` |

#### 对 BNOS 的价值

虽然 BNOS 有节点系统（DAG 级），但 Airi 的插件设计提供了：
- **节点生命周期管理参考**：announce → configure → ready 的标准化流程
- **事件协议设计**：100+ 事件类型的分类法可参考用于 BNOS 节点间的事件通信
- **本地/远程插件**：BNOS 未来可能有远程节点（移动端/云端节点）

---

### 3.7 Airi Spark Agent 协议（多智能体协调）

**源码**：[packages/plugin-protocol/src/index.ts](file:///e:/杂项/BNOS_AI_project/references/airi-main/packages/plugin-protocol/src/index.ts)

Airi 的 Spark 协议用于**AI Agent 之间的通信和协调**，是文档中最独特的设计之一。

#### spark:notify（通知）
```typescript
interface SparkNotify {
  urgency: 'immediate' | 'soon' | 'later'
  payload: { type: string, data: any }
}
```

#### spark:command（命令）
```typescript
interface SparkCommand {
  interrupt: 'force' | 'soft' | 'none'  // 打断策略
  priority: number                       // 优先级
  guidance: 'proposal' | 'instruction' | 'memory-recall'
  persona: string                        // 以谁的身份
  options: { risk: string, fallback: string }[]  // 选项
}
```

#### 消费组策略

```typescript
// 消息分发策略
'first'          // 第一个消费者处理
'round-robin'    // 轮询
'priority'       // 按优先级
'sticky'         // 粘性分配
```

#### 对 BNOS 的价值

BNOS 目前节点间通信是"写 JSON 文件 → 对方轮询读取"的简单模式。Spark 协议的启发：
- **AAA → grok_hands 的调用模式**：AAA 可以发 `spark:command` 给 grok，而不是直接写 `output.json` 等轮询
- **消费组**：一个事件可以被多个节点消费（如：一条用户消息同时触发 AAA 写入记忆 + 环境监控）
- **打断策略**：全双工语音场景下，用户打断 AI 说话可以用 `force` 打断

---

### 3.8 四层认知架构（Airi Minecraft Service）

**源码**：[services/minecraft/src/main.ts](file:///e:/杂项/BNOS_AI_project/references/airi-main/services/minecraft/src/main.ts)

Minecraft bot 实现了生物启发的四层认知模型：

```
玩家操作/环境事件
      │
      ▼
┌──────────┐
│ 感知层    │  原始事件处理 + YAML 规则引擎（派生信号）
│Perception │  → "收到伤害" / "发现矿石" / "天黑了"
└────┬─────┘
     │
     ▼
┌──────────┐
│ 反射层    │  FSM 即时反应（50ms 内）
│  Reflex  │  → 自动进食 / 防御 / 躲避危险
└────┬─────┘
     │
     ▼
┌──────────┐
│ 意识层    │  LLM 驱动的规划/推理（JavaScript 沙箱）
│ Conscious│  → "天黑了，我应该回家睡觉"
└────┬─────┘
     │
     ▼
┌──────────┐
│ 行动层    │  任务执行器 + 类型化动作注册表
│  Action  │  → 执行移动到点 / 挖掘 / 合成
└──────────┘
```

#### 对 BNOS 的价值

这个四层模型可以直接映射到 BNOS 的节点架构：

| 认知层 | BNOS 对应 | 说明 |
|--------|----------|------|
| Perception | `env_input` + `vision_in` 节点 | 环境事件处理 |
| Reflex | AAA 的 turn_taking | 50ms 级别的即时响应（打断/微笑） |
| Conscious | `aaa_cognition` | LLM 驱动的核心认知循环 |
| Action | `grok_hands` | 工具执行器 |

BNOS 目前 Reflex 层在 AAA 内部是纯 if-else 逻辑（turn_taking_timeout），可以独立为 Reflex 层。

---

### 3.9 Airi VAD（客户端 Web Worker + Silero）

**源码**：[apps/stage-web/src/workers/vad/vad.ts](file:///e:/杂项/BNOS_AI_project/references/airi-main/apps/stage-web/src/workers/vad/vad.ts)

Airi 的 VAD 在**浏览器 Web Worker**中运行 Silero VAD 模型，通过 HuggingFace Transformers.js 加载。

#### 事件驱动

```
speech-start ──→ 用户开始说话
speech-end   ──→ 用户停止说话（进入静音计数）
speech-ready ──→ 最终的语音段已准备好（加上前后 padding）
debug        ──→ 模型输出概率值（调试用）
```

#### 关键参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| speechThreshold | 激活概率阈值 | 0.5 |
| exitThreshold | 退出概率阈值 | 0.35 |
| minSilenceDurationMs | 静音多久算结束 | 300ms |
| speechPadMs | 语音前后 padding | 64ms |
| maxBufferDuration | 单次最大语音段 | 2000ms |

#### 磁滞窗口

`speechThreshold(0.5)` 和 `exitThreshold(0.35)` 之间的差值形成**磁滞窗口**，防止 VAD 在临界值附近频繁 on/off 切换。

#### 对 BNOS 的价值

BNOS 如果要实现全双工语音，有两种 VAD 方案：
- **Python 方案**（参考 SoW）：`PyAudio + Silero VAD`，约 500MB 模型文件
- **JS 方案**（参考 Airi）：`Web Worker + Transformers.js`，浏览器端推理，约 10MB

Web Worker 方案不阻塞主线程，适合与 Three.js/Live2D 渲染共存。

---

### 3.10 SillyTavern 预设系统

**路径**：[default/content/presets/](file:///e:/杂项/BNOS_AI_project/references/SillyTavern-release/default/content/presets/)

预设系统分为 5 层：

| 层级 | 控制 | BNOS 对应 |
|------|------|:---------:|
| **context** | 故事模板、示例分隔符、角色名渲染 | `llm_infer` 的 system_prompt |
| **instruct** | 输入/输出/系统序列格式 | 无独立配置 |
| **sysprompt** | 角色设定 prompt | 种子系统的性格向量 |
| **reasoning** | 思维链指令 | 无 |
| **samplers** | 温度/top_p/频率惩罚等 | `llm_infer` 参数 |

#### Context 预设 JSON 结构

```json
{
  "story_string": "{{#if system}}{{system}}\n{{/if}}{{#if wiBefore}}{{wiBefore}}\n{{/if}}...",
  "example_separator": "***",
  "chat_start": "***",
  "story_string_position": 0,
  "story_string_depth": 1,
  "names_as_stop_strings": true,
  "trim_sentences": false
}
```

#### 对 BNOS 的价值

BNOS 的 `llm_infer` 节点目前只有 `system_prompt` 一个输入。预设系统可以提供：
- **模板组合**：context + instruct + sysprompt 各层独立配置，组合成完整 prompt
- **社区共享**：预设模板可导出/导入，类似 SoW 的角色卡生态
- **多模型适配**：不同模型需要不同的 instruct 格式（Alpaca/ChatML/Llama 3...）

**工作量参考**：约 1 天（`llm_infer` 节点增加预设选择 + 模板渲染）

---

## 四、与 BNOS 设计文档的对照

### 4.1 与事件驱动型 AI 自主行为方案

| BNOS 方案 | Airi Spark 协议 | SillyTavern 对应 |
|-----------|---------------|-----------------|
| 事件三层过滤 | ❌ 无直接对应 | ❌ 无 |
| 观察缓冲区 | ❌ 无 | ❌ 无 |
| 迟滞回路 | ❌ 无 | ❌ 无 |
| **AI 间通信** | ✅ spark:command 多 Agent 协调 | ❌ 无 |
| **Hook 系统** | ✅ beforeSend/afterSend/onStreamEnd | ✅ eventSource 事件系统 |
| 防注入 | ❌ 无 | ❌ 无 |

### 4.2 与 3D 角色自定义系统

| BNOS 方案 | Airi | SillyTavern |
|-----------|------|-------------|
| VRM 渲染 | ✅ Stage VRM 渲染器 | ❌ 无 3D |
| Live2D 渲染 | ✅ `stage-ui-live2d` | ✅ expressions 扩展 |
| 角色换装 | ❌ 无直接对应 | ❌ 无 |
| **表情系统** | ❌ 无直接对应 | ✅ 29 种情绪表情图 |

### 4.3 与角色种子系统

| BNOS 方案 | Airi | SillyTavern |
|-----------|------|-------------|
| 性格向量 | ❌ 固定角色卡 | ❌ 固定角色卡 |
| 种子演化 | ❌ 无 | ❌ 无 |
| **角色卡格式** | ✅ CCC V3（PNG/JSON/MD 导出） | ✅ V2 卡（主流社区标准） |
| 多角色切换 | ✅ 角色卡系统 | ✅ 角色卡系统 |
| **Lorebook** | ✅ world 扩展类型 | ✅ World Info 引擎 |

### 4.4 与插件系统

| BNOS 方案 | Airi | SillyTavern |
|-----------|------|-------------|
| 节点级合约匹配 | ❌ 插件 SDK | ✅ 扩展系统 |
| 独立进程节点 | ✅ 独立进程服务 | ❌ 浏览器扩展 |
| 生命周期管理 | ✅ announce→configure→ready | ✅ manifest 加载 |
| **多 Agent 协调** | ✅ Spark 协议 | ❌ 无 |
| 工具调用 | ❌ 通过 MCP | ❌ 通过 API |

---

## 五、BNOS 可直接参考/复用的组件（按 BNOS 设计约束过滤）

### 🟢 P0 高价值推荐

| 模块 | 来源 | 工作量 | 依据 |
|------|------|:-----:|------|
| **世界感知记忆系统** | SillyTavern WI 启发 → [BNOS 独立设计](file:///e:/杂项/BNOS_AI_project/docs/design/[PLAN]-AI世界感知记忆系统设计方案.md) | ~1.3 天 | AI 在交互中逐步认知自身世界 |
| **提示词分层模板** | SillyTavern PromptManager | ~2 天 | 将 AAA 的固定 prompt 拆为 context/instruct/sysprompt 多层，注入引擎控制位置和深度 |
| **四层认知架构** | Airi Minecraft Service | ~1 天 | Perception→Reflex→Conscious→Action，拆解 AAA 节点为独立层次 |
| **Spark Agent 通信协议** | Airi Plugin Protocol | ~2 天 | spark:command 替代 AAA→grok 的轮询模式，支持打断/优先级 |

### 🟡 P1 中价值可选

| 模块 | 来源 | 工作量 | 依据 |
|------|------|:-----:|------|
| **RAG Data Bank** | SillyTavern vectors | ~1 天 | 文件附件独立向量索引，BNOS 没有文件级记忆 |
| **宏系统** | SillyTavern macros | ~1 天 | Python string.Template 轻量实现，用于 node_config.json 模板化 |
| **Web Worker VAD** | Airi VAD Worker | ~1 天 | 全双工语音的备选方案（JS 端 ~10MB vs Python ~500MB） |
| **预设系统** | SillyTavern presets | ~1 天 | llm_infer 增加预设选择，适配不同模型格式 |

### 🟢 直接代码参考（低工作量）

| 模块 | 来源 | 说明 |
|------|------|------|
| **VAD 磁滞窗口** | Airi VAD | speechThreshold/exitThreshold 防止频繁切换 |
| **Prompt 注入策略** | SillyTavern PromptManager | RELATIVE/ABSOLUTE 位置，深度/顺序/触发器控制 |
| **Hook 系统模式** | Airi Agent Runtime | beforeSend/onStreamEnd 生命周期钩子 |
| **Context Registry** | Airi Agent Runtime | 多源上下文注入的轻量实现 |

### 🔴 不推荐（设计冲突或 grok 已覆盖）

| 模块 | 来源 | 原因 |
|------|------|------|
| **角色卡系统（CCC/V2）** | 两者 | 一用户一 AI，不需要角色切换 |
| **Extension SDK** | 两者 | BNOS 有 DAG 节点系统 |
| **多 Backend 支持** | SillyTavern | BNOS 有特定 LLM 配置 |
| **第三方平台服务** | Airi (Discord/Telegram) | 桌面 AI 场景 |
| **工具调用/MCP** | 两者 | grok_hands 已覆盖 |

---

## 六、综合复用优先级一览

| 优先级 | 模块 | 来源 | 工作量 | 补充 BNOS 哪个缺口 |
|--------|------|------|:-----:|-------------------|
| **1** | 神经激素系统 | SoW | 0.5天 | AI 情绪深度 |
| **2** | 世界感知记忆系统 | SillyTavern 启发 | 1.3天 | AI 世界观（动态自积累） |
| **3** | 提示词分层模板 | SillyTavern | 2天 | prompt 工程质量 |
| **4** | FBX 动画集成 | SoW | 1天 | VRM 角色动作 |
| **5** | Spark Agent 协议 | Airi | 2天 | AAA→grok 通信 |
| **6** | 全双工语音管线 | SoW | 2-3天 | 实时语音交互 |
| **7** | 四层认知架构 | Airi | 1天 | AAA 节点重构 |
| **8** | 窗口上下文感知 | SoW | 0.5天 | AI 主动性 |
| **9** | 宏系统 | SillyTavern | 1天 | prompt 模板化 |
| **10** | 预设系统 | SillyTavern | 1天 | 多模型适配 |

---

## 七、风险与注意事项

1. **SillyTavern 是 AGPL-3.0 协议**，引用设计思路没问题，不建议直接复制代码
2. **Airi 使用了大量未发布/Alpha 包**（@moeru/eventa、injeca、vchord），这些库还在早期开发阶段，参考设计模式即可
3. **SillyTavern 的 WI 扫描最多 1000 条消息**，对本地 LLM 可能有性能影响。BNOS 集成时建议限制扫描深度（如最多 50 条）
4. **Airi 的 Spark 协议需要事件代理**（类似消息队列），BNOS 现有 JSON 文件协议是轮询模式。如果不用消息队列，可以用 Redis pub/sub 替代
5. **四层认知架构中的 Reflex 层**需要在 50ms 内响应，BNOS 目前是秒级轮询。Reflex 层需要独立的事件监听机制
6. **Prompt 分层模板**会增加 prompt 长度。SillyTavern 有 token 计数，BNOS 集成时也需要配套的 token 估算

---

*本文档基于 Airi（main 分支）和 SillyTavern v1.18.0 源码分析生成，与 BNOS 现有设计文档对照分析。*
