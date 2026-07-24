# BNOS AI 伴侣 — 总体开发方案

> 日期：2026-07-23 | 版本：v2.0 | 状态：[PLAN]

---

## 目录

1. [项目概述与愿景](#一项目概述与愿景)
2. [系统架构](#二系统架构)
3. [节点详细设计](#三节点详细设计)
4. [共享数据库设计](#四共享数据库设计)
5. [数据流与通信协议](#五数据流与通信协议)
6. [GUI 客户端设计](#六gui-客户端设计)
7. [分阶段实施计划](#七分阶段实施计划)
8. [技术决策记录](#八技术决策记录)
9. [风险评估](#九风险评估)

---

## 一、项目概述与愿景

### 1.1 项目定位

构建一个**完全本地化的 AI 数字伴侣系统**，以 BNOS 为编排引擎，融合 AAA（认知记忆）、Lumi_Nox（多用户记忆）、My-Neuro（Live2D 外壳/语音）、Grok Build（工具执行）、Logseq（知识图谱）、MOSS-TTS（本地 TTS）六大组件，打造一个具备自主记忆、情感演化、工具调用、知识管理能力的 AI 有机体。

### 1.2 设计隐喻

| 概念 | 对应组件 | 职责 |
|------|----------|------|
| 大脑 | AAA + LN | 认知循环、记忆读写、情感演化 |
| 面孔 | My-Neuro Live2D + MOSS-TTS | 表情动作、语音合成、视觉呈现 |
| 手脚 | Grok Build (MCP) | 外部工具调用与执行 |
| 海马体 | Logseq | 知识图谱、长期文档归档 |
| 神经系统 | BNOS | 编排调度、进程隔离、文件协议通信 |

### 1.3 核心理念

- **AI 是独立主体**：AI 拥有自己的记忆、认知、情感，不是用户的工具，而是数字伴侣
- **完全本地化**：所有数据和模型本地存储运行，云端模型作为可选增强
- **无限成长**：通过 BNOS 的 DAG 节点编排，AI 的能力可以持续扩展，不需要修改核心代码
- **进程级隔离**：每个功能模块独立进程 + 独立 venv，崩溃不互相影响

### 1.4 目标用户

- 希望拥有本地 AI 数字伴侣的个人用户
- 通过轻量 GUI 客户端进行配置和监控，无需编程知识

---

## 二、系统架构

### 2.1 核心设计原则

本方案采用 **多源输入 + 中枢多端口 + 单出口多类型** 的星型拓扑：

- **AAA 是唯一中枢 + 统一记忆入口**：所有输入源都汇聚到 AAA 的多输入端口，到达即写 DB
- **记忆输入来源可无限扩展**：当前用文本输入，未来可接入 ASR、视觉、环境传感器、系统监控等
- **单输出端口 + data_type 路由**：prompt → LLM, tool_call → Grok, reply → Live2D, knowledge → Logseq
- **GUI 通过 shared/gui_input.json 直接与 AAA 通信**：GUI 写 gui_input.json → AAA 直接读取处理
- **并行决策路径**：
  - 无工具路径：输入源 → AAA → LLM → AAA → Live2D/Logseq
  - 有工具路径：输入源 → AAA → LLM → AAA → Grok → AAA → LLM → AAA → Live2D/Logseq

### 2.2 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    BNOS 编排引擎（开发工具）                    │
│  可视化 DAG 画布 → 生成轻量化运行时引擎 → 放入项目根目录        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ 生成
┌─────────────────────────────────────────────────────────────┐
│              项目运行时（用户侧，不含 BNOS IDE）                │
│                                                             │
│  ★ 多源输入层（Phase 1: 仅 text，Phase 2+: 全部接入）         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │
│  │ ASR 语音  │ │ 视觉观察  │ │ 环境/系统 │                    │
│  │asr_input │ │vision_in │ │ env_input│                    │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘                    │
│       │ text       │ json       │ json                      │
│       └────────────┼────────────┘                          │
│                    ▼                                        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           AAA 认知记忆中枢（统一记忆入口）               │   │
│  │           (aaa_cognition)                            │   │
│  │                                                      │   │
│  │  多输入端口（到达即写 DB，按 source 标签区分来源）:      │   │
│  │  ├── gui_input    (text)   ← GUI 文本输入(P1)          │   │
│  │  ├── asr_input    (text)   ← 语音识别文本(P2+)        │   │
│  │  ├── vision_input (json)   ← 视觉观察数据(P2+)        │   │
│  │  ├── env_input    (json)   ← 环境/系统信息(P2+)       │   │
│  │  ├── llm_response (text)   ← LLM 推理结果             │   │
│  │  └── tool_result  (json)   ← Grok 工具执行结果        │   │
│  │                                                      │   │
│  │  内部直接写 DB（到达即写，source 字段标记来源）:         │   │
│  │  ├── 任何 input 端口到达 → INSERT memory(source=xxx)  │   │
│  │  ├── llm_response 到达 → INSERT 认知/感受/摘要         │   │
│  │  └── tool_result 到达 → INSERT memory(source=tool)    │   │
│  │                                                      │   │
│  │  单输出端口 → output.json, status 端口 → status.json   │   │
│  │  data_type 路由:                                      │   │
│  │  ├── "prompt"    → LLM 推理节点                       │   │
│  │  ├── "tool_call" → Grok 工具执行节点                   │   │
│  │  ├── "reply"     → Live2D 面孔节点                    │   │
│  │  └── "knowledge" → Logseq 写入节点                    │   │
│  └──────────────────────────────────────────────────────┘   │
│       │          │          │            │                 │
│  ┌────┼────┐ ┌───┼───┐ ┌───┴───┐ ┌─────┴────┐             │
│  ▼    ▼    │ │   ▼   │ │       │ │          │             │
│ ┌──────┐ ┌──┴┐│ ┌──────┐│ ┌───────┐│                       │
│ │ LLM  │ │Grok│ │Live2D││ │Logseq ││                       │
│ │推理  │ │工具│ │ +TTS ││ │知识库 ││                       │
│ └──┬───┘ └──┬─┘│ └──────┘│ └───────┘│                       │
│    │        │  │                                                │
│    └────────┼──┘                                                │
│     llm_response   tool_result                                 │
│     回传 AAA        回传 AAA                                   │
│                                                                │
│  ┌─────────────────────────────────────────────────────────────┘
│  │                                                              │
│  ▼                                                              │
│  共享数据库 (SQLite, shared/chatbot.db)                       │
└─────────────────────────────────────────────────────────────┘
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              轻量 PySide6 GUI 客户端                   │   │
│  │  配置管理 │ 日志查看 │ 节点状态监控 │ 对话界面(可选)    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌────────────────────┐  ┌─────────────────┐                │
│  │  共享 SQLite DB    │  │  Logseq 知识库   │                │
│  │  (chatbot.db)      │  │  目录            │                │
│  └────────────────────┘  └─────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 节点拓扑（BNOS DAG 连线）

```
★ 多源输入层（Phase 1: text 由 GUI 直接输入，Phase 2+: 全部接入）
  ┌──────────┐ ┌──────────┐ ┌──────────┐
  │asr_input │ │vision_in │ │ env_input│  ...可无限扩展
  └──────────┘ └────┬─────┘ └────┬─────┘
                     │ json       │ json
                     ▼            ▼
┌─────────────────────────────────────────────────────┐
│                  AAA 认知记忆中枢                     │
│                (aaa_cognition)                      │
│                                                     │
│  Input Ports (多端口 + filter 路由):                  │
│  ┌──────────┬──────────┬──────────┬──────────┐     │
│  │gui_input │asr_input │vision_in │ env_input│     │
│  └──────────┴──────────┴──────────┴──────────┘     │
│  ┌──────────────┬──────────────┐                   │
│  │ llm_response │ tool_result  │                   │
│  └──────────────┴──────────────┘                   │
│                                                     │
│  Output Ports:                                       │
│  ├── default: prompt / tool_call / reply / knowledge│
│  └── status: JSON（GUI 状态查询）                    │
└─────┼───────────────────────────────────────────────┘
      │
      ├── data_type: "prompt" ──────→ [LLM 推理节点]
      │    llm_infer port: prompt (filter: prompt)
      │    llm_infer 输出 text ──────→ AAA llm_response 端口
      │
      ├── data_type: "tool_call" ───→ [Grok 工具执行节点]
      │    grok_hands port: tool_call (filter: tool_call)
      │    grok_hands 输出 json ─────→ AAA tool_result 端口
      │
      ├── data_type: "reply" ───────→ [Live2D 面孔 + TTS 节点]
      │    live2d_face port: reply_text (filter: reply)
      │
      └── data_type: "knowledge" ───→ [Logseq 写入节点]
           logseq_writer port: entry (filter: knowledge)
```

### 2.4 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 编排引擎 | BNOS (Python/PySide6) | 开发期使用 IDE，运行时使用轻量引擎 |
| 记忆系统 | Python + SQLite + FAISS | AAA 认知循环 + LN 多用户结构 |
| LLM 推理 | Python (wrapper) + llama.cpp (C++) | 统一推理入口：双后端（本地 Qwen3-1.7B / 云端 API） |
| Live2D 渲染 | PixiJS + Cubism SDK 4.x | 从 My-Neuro 提取，去除冗余功能 |
| TTS 合成 | MOSS-TTS-Local-Transformer-v1.5 | 本地部署，48kHz，支持流式+声音克隆 |
| 工具执行 | Grok Build (Rust) | MCP 协议客户端 |
| 知识图谱 | Logseq | Markdown 解析 + 双向链接 |
| GUI 客户端 | PySide6 | 轻量级，非 Web |
| 通信协议 | 文件 JSON (BNOS 标准) | stdin/stdout + output.json |

---

## 三、节点详细设计

### 3.1 节点总览

| 节点 ID | 名称 | 语言 | 来源 | 优先级 |
|---------|------|------|------|--------|
| `aaa_cognition` | AAA 认知记忆中枢（统一记忆入口） | Python | AAA + LN 重构 | P0 |
| `llm_infer` | LLM 推理（唯一算力入口） | Python | 新建 | P0 |
| `live2d_face` | Live2D 面孔 + TTS | JS + Python | My-Neuro 提取 | P0 |
| `grok_hands` | Grok 工具执行（纯执行） | Rust | Grok Build 封装 | P1 |
| `logseq_writer` | Logseq 知识写入 | Python | 新建 | P1 |
| `asr_input` | 语音识别输入 | Python | 新建（预留） | P2 |
| `vision_input` | 视觉观察输入 | Python | 新建（预留） | P2 |
| `env_input` | 环境/系统监控输入 | Python | 新建（预留） | P2 |

---

### 3.2 AAA 提示词拼接站 (`aaa_cognition`)

**来源**：从 AAA 项目 `main.py` 重构，去除内嵌 LLM 调用和定时任务线程。

**定位**：不是认知引擎，是**提示词拼接站**。不做推理、不做决策，只负责四件事：

```
1. 收集 → 从内存拿当前输入 + 从 DB 拿历史上下文 + 多源数据
2. 拼接 → 按模板格式化成 prompt
3. 转发 → 发 LLM，收节标记文本
4. 分发 → 解析节标记 → 按 data_type 路由到下游节点
       + 并行写 DB（所有持久化数据）
```

真正的"智能"在 LLM 推理节点，AAA 只是一个高效的数据搬运工 + 格式化工具。

#### 职责

- 接收输入 → 直连路径的数据直接在内存中用，DB 路径的从 DB 一次读取
- 并行写 DB（fire-and-forget，不阻塞推理链路）
- 构建 prompt → 发送到 LLM 推理节点
- 接收节标记文本 → 解析 + 路由输出
- 需要 FAISS 检索？→ 内部检索 → 重建 prompt → 再次发送 LLM
- 需要工具调用？→ 输出 tool_call 到 Grok 节点
  - 无需工具？→ 注入情绪标签 → 输出 reply/knowledge 到下游
- 接收 Grok 工具结果 → 并行写 DB + 重建 prompt → 再次发送 LLM

#### 多输入端口设计

| 端口名 | filter (data_type) | 来源节点 | 说明 |
|--------|-------------------|----------|------|
| `gui_input` | `text` | GUI 客户端 | 用户原始输入，到达后立即写入 long_term_memory |
| `llm_response` | `text` | llm_infer | LLM 返回的节标记原始文本，AAA 内解析为 13 字段后写 DB |
| `tool_result` | `json` | grok_hands | Grok 工具执行结果，到达后写入 long_term_memory 作为上下文 |

#### 单输出端口设计

只有一个输出端口 `default`，通过 `output.json` 的 `data_type` 字段区分内容类型，BNOS 的 `port_mappings` + `filter` 机制自动路由到对应下游节点。

| data_type | 内容格式 | 目标节点 | 说明 |
|-----------|---------|----------|------|
| `prompt` | `{"prompt": "...", "need_json": true}` | llm_infer | 拼接好的完整 prompt |
| `tool_call` | `{"tool_name": "...", "args": {...}}` | grok_hands | 工具调用指令 |
| `reply` | `"<开心>今天天气确实不错呢"` | live2d_face | 含情绪标签的最终回复文本 |
| `emotion` | `{"energy":85,"emotion":90,"focus":70,"empathy":80}` | live2d_face | 4 维情绪数值 |
| `knowledge` | `{"entry":"用户喜欢晴天","tags":"天气,偏好"}` | logseq_writer | 需归档的知识条目 |

#### 核心状态机

```
                    ┌─────────────┐
     gui_input ───→│  IDLE       │
         │         └──────┬──────┘
         │                │ ① 输入在内存中直接使用（不读 DB）
         │                │   fire-and-forget 写 DB（并行，不等结果）
         │                │   从 DB 读历史上下文（感受/认知/摘要/用户信息）
         │                │   拼接 prompt
         │                ▼
         │         ┌─────────────┐
         │         │  WAIT_LLM   │──→ 输出 data_type:"prompt" → LLM
         │         └──────┬──────┘
         │                │ ② llm_response 到达
         │                │   fire-and-forget 写 DB（并行）+ 解析节标记
         │                ▼
         │         ┌─────────────┐
         │         │  DECIDING    │
         │         └──┬───┬───┬──┘
         │            │   │   │
         │   需要检索?│   │需要工具?│  都不需要?
         │            ▼   ▼        ▼
         │   ┌────────┐ ┌────────┐ ┌──────────┐
         │   │FAISS   │ │WAIT_   │ │  FINAL   │
         │   │搜索    │ │TOOL    │ │  输出    │
         │   │→重建   │ │→输出   │ │→输出reply│
         │   │prompt  │ │tool_   │ │+knowledge│
         │   │→WAIT_  │ │call    │ └──────────┘
         │   │LLM     │ │→Grok   │
         │   └────────┘ └───┬────┘
         │                  │ ③ tool_result 到达
         │                  │   fire-and-forget 写 DB（并行）
         │                  ▼
         │           ┌─────────────┐
         │           │  WAIT_LLM   │→ 重建 prompt(含工具结果) → LLM
         │           └─────────────┘
         │
         └── 并行路径：用户输入同时到达 AAA（用于推理）和 DB（用于持久化）
```

#### DB 作为数据中枢（两种路径，统一持久化）

```
核心规则：任何需要持久化的数据都必须写入 DB。
区别只在于数据到 AAA 的路径是直连还是走 DB：

★ 直连路径（当前对话数据）
  数据直接送到 AAA 处理 + 并行写 DB
  适用：用户文本、LLM 回复、工具结果
  原因：当前轮次的对话数据 AAA 已经在内存里了，不需要从 DB 拿

★ DB 中转路径（多源聚合数据）
  数据先写 DB → AAA 从 DB 一次查询取出全部
  适用：视觉、环境、ASR 等需要多源聚合的数据
  原因：数据来自不同来源，先汇入 DB，AAA 一次查询全部，避免多端口维护

★ 通用规则
  产生数据 → 写入 DB（持久化）── 适用所有数据，无一例外
```

```
Phase 1（text only）:
  gui_input ───→ AAA 处理（直连） + DB（并行写）

Phase 2+（多源）:
  gui_input ───→ AAA 处理（直连） + DB（并行写）
  asr_input  ──→ DB（先写）──┐
  vision_in  ──→ DB（先写）──┤
  env_input  ──→ DB（先写）──┼──→ AAA build_context() 一次查询取出全部
                             │
  新增输入源 = 一个 DB writer + 一个 source 标签
  AAA 代码零改动
```

#### AAA 的统一上下文读取

```python
def build_context(self, current_input_text=None):
    """构建 prompt 上下文"""
    
    # 多源数据从 DB 一次读取（不管多少来源，一条 SQL）
    latest_inputs = self.db.read_latest_by_source()
    # 返回: {"text": "...", "asr": "...", "vision": "...", "env": "..."}
    
    # 直连路径的数据用参数传入（已在内存中），DB 路径的从 latest_inputs 取
    ctx = {
        "self_cognition": self.db.read_self_cognition(),
        "recent_feelings": self.db.read_recent_feelings(),
        "other_cognition": self.db.read_other_cognition(),
        "user_text": current_input_text or latest_inputs.get("text", ""),
        "asr_text": latest_inputs.get("asr", ""),
        "vision_text": latest_inputs.get("vision", ""),
        "env_text": latest_inputs.get("env", ""),
        # ... 其他字段
    }
    return ctx
```

```
DB 读取汇总:
  write 方向（各来源写入）:
    输入源 → INSERT INTO memory (content, role, source)
    写入后如果需要触发 AAA 认知循环 → 发信号到 AAA 的对应端口

  read 方向（AAA 一次查询）:
    AAA build_context() →
      SELECT content FROM memory 
      WHERE id IN (SELECT MAX(id) FROM memory GROUP BY source)
      + self_cognition / feelings / event_summary / user_info / self_info
      
  一次 DB 查询拿到全部上下文，不管多少输入源，查询次数不变
```

#### 具体时机

```
时机 1：gui_input 端口收到数据 (Phase 1)
  → [并行] fire-and-forget INSERT INTO memory (content, role='user', source='text')
  → [并行] current_input_text 直接在内存中使用 → 构建 prompt → 输出到 LLM

时机 1b~1d：asr / vision / env 端口收到数据 (Phase 2+)
  → 输入源各自写 DB（INSERT memory, source='asr'/'vision'/'env'）
  → 通知 AAA "新数据就绪" → AAA build_context() 从 DB 一次读取全部来源

时机 2：llm_response 端口收到数据
  → [并行] fire-and-forget 写 DB（memory + feelings + event_summary + cognitions + infos）
  → [并行] 解析节标记 → 判断路径 → 输出到下游

时机 3：tool_result 端口收到数据
  → [并行] fire-and-forget INSERT INTO memory (content, role='tool', source='grok')
  → [并行] 重建 prompt(含工具结果) → 输出到 LLM
```

#### 配置文件 (`node_config.json`)

```jsonc
{
  "node_name": "aaa_cognition",
  "language": "python",

  // === 参数面板 ===
  "parameters": [
    {"name": "db_path", "type": "file", "label": "数据库路径", "default": "../shared/chatbot.db"},
    {"name": "faiss_index_path", "type": "file", "label": "FAISS 索引路径", "default": "../shared/faiss_index.bin"},
    {"name": "max_history_summary", "type": "int", "label": "历史摘要条数", "default": 3, "min": 1, "max": 10},
    {"name": "max_tool_rounds", "type": "int", "label": "最大工具调用轮数", "default": 3, "min": 1, "max": 10}
  ],
  "resource_limit": {"memory_mb": 512, "cpu_percent": 80},

  // === 多输入端口（filter 自动路由，所有 input 到达即写 DB） ===
  "input_ports": [
    // ---- Phase 1 核心端口 ----
    {"name": "gui_input",    "label": "GUI 输入",     "type": "text", "required": false, "source": "node"},
    {"name": "llm_response", "label": "LLM 响应",     "type": "text", "required": false, "source": "node"},
    {"name": "tool_result",  "label": "工具结果",     "type": "json", "required": false, "source": "node"}
  ],

  "filter": {
    "gui_input":    {"data_type": "text", "source": "gui"},
    "llm_response": {"data_type": "text", "source": "llm"},
    "tool_result":  {"data_type": "tool_result"}
  },

  // === 输出端口（主输出 + 状态反馈） ===
  "output_ports": [
    {"name": "default", "label": "中枢输出", "type": "default"},
    {"name": "status",  "label": "状态反馈", "type": "json"}
  ],

  // === 输出路由（port_mappings 指定 data_type → 目标节点/端口） ===
  "port_mappings": {
    "prompt":    {"target_node": "llm_infer",     "target_port": "prompt"},
    "tool_call": {"target_node": "grok_hands",    "target_port": "tool_call"},
    "reply":     {"target_node": "live2d_face",   "target_port": "reply_text"},
    "knowledge": {"target_node": "logseq_writer", "target_port": "entry"}
  }
}
```

> **注意**：当前 `aaa_cognition` 节点已创建完整的 `node_config.json`，见 [节点目录](nodes/node_python_aaa_cognition/node_config.json)。其中 `parameters[].type` 使用了 `"number"`，应修正为 `"int"` / `"float"` 以符合 BNOS 规范；`filter.llm_response` 已正确设为 `{"data_type": "text"}`。

#### 关键改动（相比原版 AAA）

| 原版 AAA | 新设计 |
|----------|--------|
| 内嵌 LLM 调用 (qwen_api) | LLM 独立为节点，通过 data_type:"prompt" 发送，llm_response 端口接收 |
| 内嵌定时任务线程 | **删除** |
| 仅 user_input 一个入口 | **多源记忆输入**：gui_input / asr / vision / env 等，统一 DB 写入 |
| 多输出端口 | 单输出端口 + data_type 字段区分 |
| __init__ 中创建所有依赖 | 多输入端口动态接收，到达即写 DB |
| 确定性哈希向量 | 保留 FAISS（Phase 2 升级真 embedding） |
| 无状态反馈端口 | **新增** status 端口，GUI 可查询初始化/运行状态 |
| 独立的 gui_adapter + user_input 节点 | **AAA 内置**：AAA 直接读取 gui_input.json，合并 GUI 适配 + 用户输入处理 + 认知拼接 |
| 无会话上下文感知 | **新增会话上下文感知**：实时跟踪会话状态（IDLE/CHATTING/ENDED），计算对话时间间隔 |
#### 会话上下文感知

详见 [AAA 节点开发方案 → 十三、会话上下文感知](nodes/node_python_aaa_cognition/开发方案.md#十三会话上下文感知)。

**设计概要**（参考 Lumi_Nox 状态机 + 时间戳机制）：

- **状态定义**：`IDLE`（空闲）→ `CHATTING`（对话中）→ `ENDED`（结束）
- **时间间隔计算**：通过 DB 中 `conversation_state` 表记录 `last_input_time`、`last_reply_time` 等时间戳，每次 `_gather_context()` 时计算 `time_since_last_input`、`time_since_session_start` 等字段注入 prompt
- **轻量化检测**：不依赖跨进程信号，通过"5 分钟无输入自动标记 ENDED" + "下次输入自动恢复 CHATTING" 推断应用生命周期
- **Prompt 注入**：新增 `{session_status}`、`{time_since_last_input}`、`{time_since_session_start}`、`{input_count_this_session}` 字段

#### AAA 节点处理代码

```python
# ===== 1. Prompt 模板（节标记格式，含多源上下文字段） =====

PROMPT_TEMPLATE = """
### 可用工具（按需调用）
- web_search(query) — 联网搜索
- code_exec(language, code) — 执行代码
- file_read(path) — 读取文件
- file_write(path, content) — 写入文件

### 输入上下文
你的自我认知：{self_cognition}
你的最近感受：{recent_feelings}
你的他人认知（对用户）：{other_cognition}

本轮输入：
  用户文本：{user_text}
  语音输入：{asr_text}
  视觉观察：{vision_text}
  环境/系统：{env_text}

当前日期时间：{current_date} {current_time}
你的当前状态：{current_state}
历史摘要：{history_summary}
用户信息：{user_info}
你的自我信息：{self_info}
记忆检索结果：{faiss_top5}

### 输出格式（节标记，不需要的节省略）
【自然回复】
给用户看的回复文本

【心情】
1-4个字：开心、难过、好奇、平静、生气、惊讶、害羞、俏皮

【想法】
1-2句话描述你的内心想法

【当前状态】
清醒、打盹、小憩、午休、睡眠 中选一个

【事件摘要】
本轮对话核心摘要，1-2句话

【语意检索】
需要回忆的关键词

【自我认知】
对自己的新认识

【他人认知】
对用户的新认识

【用户信息】
key=值, key=值

【自我信息】
key=值, key=值

【知识条目】
值得归档的知识内容

【知识标签】
逗号分隔标签

【工具调用】
工具名 | 参数名=值
多工具每行一个
"""

# ===== 2. 节标记解析器 =====
import re

def parse_llm_output(text: str) -> dict:
    """将 LLM 的节标记文本解析为结构化 dict"""
    pattern = re.compile(r'【(.+?)】\s*\n(.*?)(?=\n【|$)', re.DOTALL)
    result = {}
    for match in pattern.finditer(text):
        key = match.group(1).strip()
        value = match.group(2).strip()
        if not value:
            continue
        if key == "工具调用":
            tools = []
            for line in value.split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = line.split("|", 1)
                if len(parts) != 2:
                    continue
                args = {}
                for kv in parts[1].split(","):
                    kv = kv.strip()
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        args[k.strip()] = v.strip()
                tools.append({"tool_name": parts[0].strip(), "args": args})
            result[key] = tools
        else:
            result[key] = value
    return result


# ===== 3. AAA 中枢主循环 =====

class AAACognitionNode:
    def __init__(self, db_path, faiss_path, config):
        self.db = SQLiteDB(db_path)
        self.faiss = FAISSSearch(faiss_path)
        self.config = config
        self.state = "IDLE"

    def build_context(self):
        """读取 DB 构建 prompt 上下文字典（多源字段可能为空）"""
        ctx = {
            "self_cognition": self.db.read_self_cognition(),
            "recent_feelings": self.db.read_recent_feelings(),
            "other_cognition": self.db.read_other_cognition(),
            "user_text": self.db.read_latest_input(source="text") or "",
            "asr_text": self.db.read_latest_input(source="asr") or "",
            "vision_text": self.db.read_latest_input(source="vision") or "",
            "env_text": self.db.read_latest_input(source="env") or "",
            "current_date": datetime.now().strftime("%Y-%m-%d"),
            "current_time": datetime.now().strftime("%H:%M:%S"),
            "current_state": self._calc_state(),
            "history_summary": self.db.read_history_summary(limit=3),
            "user_info": self.db.read_user_info(),
            "self_info": self.db.read_self_info(),
            "faiss_top5": self.faiss.search(last_input, top_k=5) if faiss_triggered else "",
        }
        return ctx

    def on_port_input(self, port_name: str, data):
        """多端口输入处理：输入直接用于推理，DB 写并行 fire-and-forget"""
        if port_name in ("gui_input", "asr_input", "vision_input"):
            # [并行] fire-and-forget 写 DB，不等待
            source = {"gui_input": "text", "asr_input": "asr", "vision_input": "vision"}[port_name]
            threading.Thread(target=self.db.insert_memory, args=(data, "user", source), daemon=True).start()
            # [并行] 直接用内存中的 data 构建 prompt → 发给 LLM
            prompt = PROMPT_TEMPLATE.format(**self.build_context(current_input=data))
            self.write_output([{"data_type": "prompt", "content": prompt}])

        elif port_name == "env_input":
            # 环境信息只写 DB，不触发认知循环
            threading.Thread(target=self.db.insert_memory, args=(data, "system", "env"), daemon=True).start()

        elif port_name == "llm_response":
            # [并行] fire-and-forget 写 DB + 解析节标记
            threading.Thread(target=self._write_parsed_to_db, args=(parsed,), daemon=True).start()
            parsed = parse_llm_output(data)
            # 直接用内存中的 parsed 做路由判断
            outputs = self._route_outputs(parsed)
            self.write_output(outputs)

        elif port_name == "tool_result":
            # [并行] fire-and-forget 写 DB + 重建 prompt
            threading.Thread(target=self.db.insert_memory, args=(data, "tool", "grok"), daemon=True).start()
            prompt = PROMPT_TEMPLATE.format(**self.build_context())
            prompt += f"\n工具执行结果：{data}"
            self.write_output([{"data_type": "prompt", "content": prompt}])

        elif port_name == "init_check":
            # GUI 初始化检测：检查 DB/FAISS/配置 → 写 status.json
            status = self._run_init_check(data)
            self.write_status(status)


def _mood_to_tag(mood: str) -> str:
    """心情文本 → Live2D 情绪标签"""
    mapping = {
        "开心": "开心", "高兴": "开心", "愉快": "开心",
        "难过": "难过", "伤心": "难过", "低落": "难过",
        "生气": "生气", "愤怒": "生气",
        "惊讶": "惊讶", "震惊": "惊讶", "好奇": "惊讶",
        "害羞": "害羞", "俏皮": "俏皮",
    }
    for k, v in mapping.items():
        if k in mood:
            return v
    return ""
```

#### 多源记忆输入设计要点

| 输入源 | data_type | 触发认知循环? | DB source 标签 | 格式示例 |
|--------|-----------|:---:|--------|------|
| gui_input | text | **是** | `text` | `"今天天气怎么样"` |
| asr_input | text | **是** | `asr` | `"帮我查一下天气"` |
| vision_input | json | **是** | `vision` | `{"scene":"房间","objects":["杯子","书"]}` |
| env_input | json | **否** | `env` | `{"cpu":45,"mem":60,"hour":14}` |
| llm_response | text | — | `llm` | 节标记文本 |
| tool_result | json | — | `grok` | `{"result":"..."}` |

- **env_input 不触发认知循环**：环境数据是持续背景，仅作为 prompt 的当前上下文字段注入
- **每次触发认知循环时，所有多源上下文字段一起注入 prompt**（空字段显示为空）
- Phase 1 只实现 gui_input（由 GUI 直接写入 gui_input.json），其余端口预留在 node_config 中但无上游连线，不影响运行

---

---

### 3.3 LLM 推理节点 (`llm_infer`)

**来源**：新建，封装 llama.cpp server API + 云端 API 统一适配层

**定位**：系统**唯一**的 LLM 推理提供者。本地 llama.cpp 和云端 API 都走此节点，Grok 等其他节点不持有任何推理能力。

**职责**：
- 接收 AAA 发来的 prompt（data_type: "prompt"）
- 根据 `model_type` 配置，调用本地 llama.cpp 或云端 API 进行推理
- 返回**节标记文本**给 AAA（data_type: "text"）
- **不做任何工具调用、不做任何决策**，纯粹输入 prompt → 输出文本

**三后端设计**：

```
llm_infer 节点
├── http_server  → llama-server.exe 常驻 HTTP 服务 (localhost:8080/v1) → Qwen3-1.7B Q4_K_M
├── cli_local    → llama-cli.exe 子进程调用（零配置，每次加载模型）     → Qwen3-1.7B Q4_K_M
└── cloud_openai → 云端 API (OpenAI 兼容格式)                          → Qwen-Max / GPT-4o
```

| 后端 | `model_type` | 延迟 | 流式 | 适用场景 |
|------|-------------|------|------|----------|
| HTTP Server | `http_server` | 低（模型常驻） | 支持 | 默认，日常对话 |
| CLI Local | `cli_local` | 高（每次加载） | 不支持 | 零配置部署、低频调用 |
| 云端 API | `cloud_openai` | 取决于网络 | 支持 | 高质量推理、联网 |

通过 GUI 或 node_config 的 `model_type` 参数一键切换，调用层接口统一为 OpenAI 兼容格式。

**输入端口**：

| 端口名 | filter (data_type) | 说明 |
|--------|-------------------|------|
| `prompt` | `prompt` | AAA 拼接好的完整 prompt |

**输出端口**：

| 端口名 | data_type | 目标 |
|--------|-----------|------|
| `default` | `text` | AAA llm_response 端口（节标记文本） |

**配置文件**：

```jsonc
{
  "node_name": "llm_infer",
  "language": "python",
  "parameters": [
    {"name": "model_type", "type": "enum", "label": "模型类型", "options": ["http_server", "cli_local", "cloud_openai"], "default": "http_server"},
    {"name": "model_path", "type": "file", "label": "本地模型路径", "default": ""},
    {"name": "api_base", "type": "string", "label": "API Base URL", "default": "http://localhost:8080/v1"},
    {"name": "api_key", "type": "password", "label": "API Key", "default": ""},
    {"name": "cloud_model", "type": "string", "label": "云端模型名", "default": "qwen-max"},
    {"name": "max_tokens", "type": "int", "label": "最大 Token", "default": 2048, "min": 256, "max": 32768},
    {"name": "temperature", "type": "float", "label": "温度", "default": 0.7, "min": 0, "max": 2.0, "step": 0.1}
  ],
  "input_ports": [
    {"name": "prompt", "label": "Prompt 输入", "type": "text", "required": true, "source": "node"}
  ],
  "filter": {
    "prompt": {"data_type": "prompt"}
  },
  "output_ports": [
    {"name": "default", "label": "LLM 响应", "type": "default"}
  ]
}
```

**设计决策**：LLM 独立为节点的原因：
- **统一推理入口**：本地 llama.cpp 和云端 API 切换无需修改任何其他节点
- **Grok 不持算力**：Grok 仅执行工具，工具结果需要推理时回传 AAA → LLM 节点
- 方便调试：单独查看 AAA 发出的 prompt 和 LLM 返回的节标记文本
- 未来扩展：Live2D 等节点也可能需要 LLM（直接连到此节点）

---

### 3.4 Live2D 面孔节点 (`live2d_face`)

**来源**：从 My-Neuro 提取核心 Live2D 渲染 + 情绪映射 + MOSS-TTS

**职责**：
- 加载和渲染 Live2D Cubism 4.x 模型
- 接收 AAA 发来的 `reply`（含 `<情绪>` 标签文本），触发 Expression + Motion
- 接收 AAA 发来的 `emotion`（4 维情绪数值），用于情绪状态展示
- 去除情绪标签后调用 MOSS-TTS 朗读纯文本
- 同步嘴型、字幕
- 提供透明无边框桌面窗口

**多输入端口设计**：

| 端口名 | filter (data_type) | 说明 |
|--------|-------------------|------|
| `reply_text` | `reply` | 含情绪标签的回复文本（情绪已内嵌，无需独立端口） |
| `init_check` | `json` | GUI 初始化检测信号 |

**输出端口**：

| 端口名 | data_type | 说明 |
|--------|-----------|------|
| `status` | `json` | 初始化状态反馈给 GUI |

**情绪标签机制**（继承 My-Neuro，无需修改）：

```
收到 "reply" → EmotionMotionMapper 解析 <开心> <惊讶> 等标签
  → 查 emotion_actions.json → 播放 Live2D Motion
  → 查 emotion_expressions.json → 播放 Live2D Expression
  → 去除标签 → 纯文本 → MOSS-TTS 朗读
```

**支持的 6 种情绪**：开心、生气、难过、惊讶、害羞、俏皮

**配置文件**：

```jsonc
{
  "node_name": "live2d_face",
  "language": "python",
  "parameters": [
    {"name": "model_path", "type": "directory", "label": "Live2D 模型目录", "default": ""},
    {"name": "character_name", "type": "string", "label": "角色名称", "default": "肥牛"},
    {"name": "tts_engine", "type": "enum", "label": "TTS 引擎", "options": ["moss_tts_local", "none"], "default": "moss_tts_local"},
    {"name": "moss_tts_model", "type": "string", "label": "MOSS-TTS 模型路径", "default": ""},
    {"name": "expression_config", "type": "file", "label": "表情配置文件", "default": "./emotion_expressions.json"},
    {"name": "motion_config", "type": "file", "label": "动作配置文件", "default": "./emotion_actions.json"},
    {"name": "window_transparent", "type": "bool", "label": "透明窗口", "default": true},
    {"name": "window_on_top", "type": "bool", "label": "窗口置顶", "default": true}
  ],
  "input_ports": [
    {"name": "reply_text",  "label": "回复文本",   "type": "text", "required": false, "source": "node"},
    {"name": "init_check",  "label": "初始化检测", "type": "json", "required": false, "source": "node"}
  ],
  "filter": {
    "reply_text":  {"data_type": "reply"},
    "init_check":  {"data_type": "json"}
  },
  "output_ports": [
    {"name": "default",  "label": "主输出", "type": "default"},
    {"name": "status",   "label": "状态反馈", "type": "json"}
  ]
}
```

**与 My-Neuro 的差异**：
- **去除**：插件系统（工具调用交给 Grok Build）
- **去除**：MCP 管理器（交给 Grok Build）
- **去除**：直播功能（弹幕、ASR 等）
- **去除**：WebUI 控制面板（由 PySide6 GUI 替代）
- **去除**：MemOS 记忆系统（由 AAA+LN 替代）
- **保留**：Live2D Cubism 渲染核心
- **保留**：emotion-expression-mapper.js + emotion-motion-mapper.js
- **保留**：TTS 播放引擎
- **新增**：MOSS-TTS 后端接入

---

### 3.6 Grok 工具执行节点 (`grok_hands`)

**来源**：封装 Grok Build 的 MCP 客户端

**定位**：纯工具执行器。**不调用任何 API、不持有任何 LLM、不做任何推理判断**。算力统一由 llm_infer 节点提供。

**职责**：
- 接收 AAA 发来的工具调用请求（data_type: "tool_call"）
- 通过 MCP 协议执行外部工具（web_search、code_exec、file_read/write 等）
- 返回原始工具执行结果给 AAA（data_type: "json"）
- AAA 收到结果后写 DB → 构建含工具结果的新 prompt → 发给 llm_infer 推理

**输入端口**：

| 端口名 | filter (data_type) | 说明 |
|--------|-------------------|------|
| `tool_call` | `tool_call` | 工具调用指令 `{tool_name, args}` |

**输出端口**：

| 端口名 | data_type | 目标 |
|--------|-----------|------|
| `default` | `json` | AAA tool_result 端口 |

**算力回路**：

```
AAA 检测 tool_call → Grok 执行工具
                         │
                         ▼ 返回原始结果
                       AAA 写 DB + 重建 prompt
                         │
                         ▼
                    llm_infer 推理（唯一算力提供者）
                         │
                         ▼
                       AAA 解析 + 最终输出
```

Grok 仅执行，不吃算力。如果工具结果需要理解和总结，由 AAA 拼接回 prompt，llm_infer 统一推理。

**配置文件**：

```jsonc
{
  "node_name": "grok_hands",
  "language": "rust",
  "parameters": [
    {"name": "mcp_server_list", "type": "text", "label": "MCP 服务器列表 (JSON)", "default": "[]"},
    {"name": "max_exec_time", "type": "int", "label": "最大执行时间(秒)", "default": 30}
  ],
  "input_ports": [
    {"name": "tool_call", "label": "工具调用", "type": "json", "required": true, "source": "node"}
  ],
  "filter": {
    "tool_call": {"data_type": "tool_call"}
  },
  "output_ports": [
    {"name": "default", "label": "工具结果", "type": "default"}
  ]
}
```

---

### 3.7 Logseq 知识写入节点 (`logseq_writer`)

**来源**：新建

**职责**：
- 接收 AAA 发来的知识条目（data_type: "knowledge"）
- 转换为 Logseq 格式 Markdown（含标签、属性、双向链接）
- 写入 Logseq 的 pages/ 或 journals/ 目录

**输入端口**：

| 端口名 | filter (data_type) | 说明 |
|--------|-------------------|------|
| `entry` | `knowledge` | 知识条目 `{"entry": "...", "tags": "...", "source": "..."}` |

**输出端口**：

| 端口名 | data_type | 说明 |
|--------|-----------|------|
| `default` | `text` | 写入的文件路径 |

**Markdown 模板**：

```markdown
- 用户提到喜欢《星际穿越》
  tags:: 电影, 科幻, 用户偏好
  source:: 对话 2026-07-23
  created:: 2026-07-23
```

**配置文件**：

```jsonc
{
  "node_name": "logseq_writer",
  "language": "python",
  "parameters": [
    {"name": "logseq_pages_dir", "type": "directory", "label": "Logseq pages 目录", "default": ""}
  ],
  "input_ports": [
    {"name": "entry", "label": "知识条目", "type": "json", "required": false, "source": "node"}
  ],
  "filter": {
    "entry": {"data_type": "knowledge"}
  },
  "output_ports": [
    {"name": "default", "label": "写入路径", "type": "default"}
  ]
}
```

---

---

### 3.7 预留扩展输入节点

以下节点 Phase 1 仅预留 node_config, Phase 2+ 逐个接入，均连到 AAA 的对应端口：

#### ASR 语音输入节点 (`asr_input`) - P2

```jsonc
{
  "node_name": "asr_input",
  "language": "python",
  "parameters": [
    {"name": "model_type", "type": "enum", "label": "ASR 引擎", "options": ["faster_whisper", "whisper_cpp", "vosk"], "default": "faster_whisper"},
    {"name": "model_size", "type": "enum", "label": "模型大小", "options": ["tiny", "base", "small", "medium"], "default": "small"}
  ],
  "output_ports": [
    {"name": "default", "label": "识别文本", "type": "default"}
  ]
}
```

#### 视觉观察节点 (`vision_input`) - P2

```jsonc
{
  "node_name": "vision_input",
  "language": "python",
  "parameters": [
    {"name": "capture_mode", "type": "enum", "label": "采集模式", "options": ["camera", "screenshot", "video"], "default": "camera"},
    {"name": "interval_sec", "type": "int", "label": "采集间隔(秒)", "default": 5, "min": 1, "max": 60},
    {"name": "vision_model", "type": "enum", "label": "视觉模型", "options": ["llama.cpp_mmproj", "cloud_api"], "default": "cloud_api"}
  ],
  "output_ports": [
    {"name": "default", "label": "视觉描述 JSON", "type": "default"}
  ]
}
```

#### 环境/系统监控节点 (`env_input`) - P2

```jsonc
{
  "node_name": "env_input",
  "language": "python",
  "parameters": [
    {"name": "interval_sec", "type": "int", "label": "采集间隔(秒)", "default": 30, "min": 5, "max": 300},
    {"name": "monitor_cpu", "type": "bool", "label": "监控 CPU", "default": true},
    {"name": "monitor_mem", "type": "bool", "label": "监控内存", "default": true},
    {"name": "monitor_time", "type": "bool", "label": "监控时间", "default": true}
  ],
  "output_ports": [
    {"name": "default", "label": "环境数据 JSON", "type": "default"}
  ]
}
```

---

## 四、共享数据库设计

### 4.1 数据库选型

SQLite，单文件 `shared/chatbot.db`，AAA 节点独占写入，其他节点只读或通过 AAA 间接写入。

### 4.2 写入者约定

| 写入者 | 写入时机 | 写入的表 |
|--------|----------|----------|
| AAA（gui_input 到达时） | 并行 fire-and-forget | `long_term_memory`（source='text', role='user'） |
| AAA（asr_input 到达时） | 并行 fire-and-forget | `long_term_memory`（source='asr', role='user'） |
| AAA（vision_input 到达时） | 并行 fire-and-forget | `long_term_memory`（source='vision', role='user'） |
| AAA（env_input 到达时） | 并行 fire-and-forget | `long_term_memory`（source='env', role='system'） |
| AAA（llm_response 到达时） | 并行 fire-and-forget | `long_term_memory`, `feelings`, `event_summary`, `self_cognition`, `other_cognition`, `user_info`, `self_info` |
| AAA（tool_result 到达时） | 并行 fire-and-forget | `long_term_memory`（source='grok', role='tool'） |

### 4.3 表结构（融合 AAA + LN）

```sql
-- ===== AAA 原有表 =====
-- 自我认知（AI 对自己的认知）
CREATE TABLE self_cognition (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 他人认知（AI 对用户的认知）
CREATE TABLE other_cognition (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 感受表（心情 + 想法）
CREATE TABLE feelings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mood TEXT,      -- 心情
    thought TEXT,   -- 想法
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 长期记忆（统一记忆表，source 区分输入来源）
CREATE TABLE long_term_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT,              -- 内容文本
    role TEXT DEFAULT 'user',  -- user / assistant / tool / system
    source TEXT DEFAULT 'text',-- 来源：text / asr / vision / env / llm / grok / manual
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 事件摘要（对话摘要，同步到 FAISS）
CREATE TABLE event_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    keywords TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 用户信息（键值对）
CREATE TABLE user_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(key)
);

-- 自我信息（键值对）
CREATE TABLE self_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(key)
);

-- ===== LN 新增表（多用户支持） =====
-- 用户身份表
CREATE TABLE user_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity_key TEXT NOT NULL UNIQUE,
    display_name TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 用户事实表（结构化记忆）
CREATE TABLE user_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity_key TEXT NOT NULL,
    category TEXT,              -- identity / background / preference / project
    fact_content TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    source TEXT DEFAULT 'llm',  -- llm / manual
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (identity_key) REFERENCES user_profiles(identity_key)
);

-- 用户对话消息表
CREATE TABLE user_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity_key TEXT NOT NULL,
    content TEXT NOT NULL,
    role TEXT DEFAULT 'user',
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (identity_key) REFERENCES user_profiles(identity_key)
);
```

### 4.4 AAA 输出 → LN 多用户记忆写入映射

#### 身份识别策略

```
Phase 1（单用户）:
  identity_key 固定为 "default_user"
  首次启动自动创建: INSERT OR IGNORE INTO user_profiles (identity_key, display_name) VALUES ('default_user', '用户')

Phase 2+（多用户）:
  方案 A: GUI 选择当前对话身份 → identity_key 随 gui_input 传到 AAA
  方案 B: AAA 根据 LLM 的"他人认知"自动判断 → 匹配 user_profiles 中最相似的身份
  方案 C: 首次对话时 LLM 输出"用户信息 name=小明" → AAA 自动创建新 user_profile
```

#### AAA 字段 → LN 表写入映射

```
每次 llm_response 到达后，AAA 解析节标记，写入 LN 专属表：

【自然回复】 → user_messages
  INSERT INTO user_messages (identity_key, content, role='assistant')

【他人认知】 → user_facts (category='cognition')
  INSERT INTO user_facts (identity_key, category='cognition', fact_content, source='llm')
  例: "用户小明喜欢在晚上工作"

【用户信息】 → user_facts (category='background')
  解析 "key=值, key=值" 拆成多条 fact
  INSERT INTO user_facts (identity_key, category='background', fact_content)

【知识条目】 → user_facts (category='preference')
  标签含"习惯/偏好/用户/日常"时写入
  INSERT INTO user_facts (identity_key, category='preference', fact_content)
```

#### 写入代码

```python
def _write_ln_tables(parsed: dict, identity_key: str):
    """AAA 解析结果 → LN 多用户记忆表（并行 fire-and-forget）"""
    
    if reply := parsed.get("自然回复"):
        db.insert_user_message(identity_key, reply, role="assistant")
    
    if cognition := parsed.get("他人认知"):
        db.insert_user_fact(identity_key, "cognition", cognition)
    
    if user_info := parsed.get("用户信息"):
        for kv in user_info.split(","):
            if "=" in kv:
                k, v = kv.split("=", 1)
                db.insert_user_fact(identity_key, "background", f"{k.strip()}={v.strip()}")
    
    if knowledge := parsed.get("知识条目"):
        tags = parsed.get("知识标签", "")
        if any(t in tags for t in ["习惯", "偏好", "用户", "日常"]):
            db.insert_user_fact(identity_key, "preference", knowledge)
```

#### prompt 注入

```
build_context() 按当前 identity_key 读取用户专属上下文:

  用户 {display_name} 的背景:
  {从 user_facts 读取该用户的 background/cognition/preference}
  
  与该用户的历史对话:
  {从 user_messages 读取该用户最近 N 条}
```

---

## 五、数据流

## 五、数据流与通信协议

### 5.1 完整一轮对话数据流（无工具路径）

```
Step 1: 用户输入
  GUI 写 gui_input.json → AAA 直接读取
  {"data_type": "text", "content": "帮我查一下今天天气"}

Step 2: AAA 收到 gui_input（gui_input 端口）
  ├─ [并行] fire-and-forget INSERT INTO memory (content='帮我查...', source='text')
  ├─ [并行] 读 DB 历史上下文: self_cognition, feelings, event_summary, user_info
  ├─ 当前输入 "帮我查一下今天天气" 直接在内存中使用（不读 DB）
  ├─ 构建 prompt #1（不带 FAISS 检索结果）
  └─ 输出 → {"data_type": "prompt", "content": "### 可用工具\n..."}

Step 3: LLM 推理
  llm_infer 收到 prompt 端口
  → 推理 → 返回节标记文本
  【自然回复】好的，我帮你查一下~
  【语意检索】今天天气
  【工具调用】
  web_search | query=北京天气今天

Step 4: AAA 收到 llm_response（llm_response 端口）
  ├─ [并行] fire-and-forget 写 DB（memory + feelings 等）
  ├─ 解析节标记 → "语意检索"="今天天气" → 需要 FAISS
  ├─ [并行] 内部执行 FAISS.search("今天天气")
  ├─ 构建 prompt #2（带 FAISS 结果 + 当前输入直接注入，不读 DB）
  └─ 输出 {"data_type": "prompt", "content": "### 角色\n..."}

Step 5: LLM 推理（第二轮）
  → 返回节标记文本
  【自然回复】今天北京晴天<开心>
  【心情】愉快
  ...

Step 6: AAA 收到 llm_response（llm_response 端口）
  ├─ [并行] fire-and-forget 写 DB:
  │   INSERT INTO memory (content, role='assistant', source='llm')
  │   INSERT INTO feelings (mood='愉快', thought='...')
  │   INSERT INTO event_summary (summary='用户查询天气...')
  │   FAISS.add(summary)
  ├─ [并行] 解析节标记 → 判断：无需工具调用
  ├─ 注入情绪标签: "今天北京晴天<开心>"
  └── 输出多个 data_type（BNOS 自动分发给下游）:
      {"data_type": "reply",    "content": "今天北京晴天<开心>"}
      {"data_type": "knowledge","content": {"entry":"用户关心天气","tags":"天气"}}

Step 7: 下游节点并行消费
  live2d_face (reply_text 端口) → 解析 <开心> → 播表情/动作 → MOSS-TTS 朗读
  logseq_writer → 写入 Logseq pages/
```

### 5.2 完整一轮对话数据流（有工具路径）

```
Step 1-5: 同上（用户输入 → AAA → LLM → AAA）

Step 6: AAA 解析 LLM 返回的 JSON
  → 判断：需要工具调用（如 JSON 中包含 tool_call 指令）
  └── 输出 {"data_type": "tool_call", "tool_name": "web_search", "args": {"query":"..."}}

Step 7: Grok 工具执行
  grok_hands 收到 tool_call 端口
  → MCP 协议调用外部工具
  → 输出 {"data_type": "json", "result": "搜索结果显示..."}

Step 8: AAA 收到 tool_result（tool_result 端口）
  ├── 立即写 DB: INSERT INTO long_term_memory (tool_result, role='tool')
  ├── 重建 prompt（含工具结果）
  └── 输出 {"data_type": "prompt", "prompt": "...[含工具结果]..."}

Step 9: LLM 推理（第三轮）
  → 返回最终 JSON

Step 10: AAA 收到 llm_response
  ├── 写入全部 DB 表
  └── 输出 reply / emotion / knowledge（同无工具路径 Step 6）
```

### 5.3 情绪标签注入协议

AAA 节点输出 `reply` 时自动注入情绪标签，直接使用 LLM 输出的 `心情` 字段：

```python
def inject_emotion_tag(reply_text: str, mood: str) -> str:
    """
    根据 LLM 输出的心情文本，在回复前注入 Live2D 情绪标签
    """
    mood_to_tag = {
        "开心": "开心", "高兴": "开心", "愉快": "开心", "兴奋": "开心",
        "难过": "难过", "伤心": "难过", "低落": "难过", "沮丧": "难过",
        "生气": "生气", "愤怒": "生气", "烦躁": "生气",
        "惊讶": "惊讶", "震惊": "惊讶", "好奇": "惊讶",
        "害羞": "害羞",
        "俏皮": "俏皮", "调皮": "俏皮",
    }
    for k, v in mood_to_tag.items():
        if k in mood:
            return f"<{v}>{reply_text}"
    return reply_text
```
```

### 5.4 output.json 协议规范

AAA 中枢节点单输出端口的所有 data_type：

```jsonc
// data_type: "prompt" — 发给 LLM 推理节点
{"data_type": "prompt", "prompt": "### 可用工具...", "need_json": false}

// data_type: "tool_call" — 发给 Grok 工具节点
{"data_type": "tool_call", "tool_name": "web_search", "args": {"query": "北京天气"}}

// data_type: "reply" — 发给 Live2D 面孔节点 (reply_text 端口)
{"data_type": "reply", "content": "今天北京晴天<开心>"}

// data_type: "knowledge" — 发给 Logseq 写入节点
{"data_type": "knowledge", "content": {"entry": "用户关心天气", "tags": "天气, 日常", "source": "对话 2026-07-23"}}
```

### 5.5 并行执行说明

AAA 在最终输出阶段可以同时输出多条不同 data_type 的消息。BNOS 的 listener 检测到 `output.json` 更新后，会根据 `port_mappings` + 各下游节点的 `filter` 配置，**并行**将数据路由到对应节点的对应端口：

```
AAA output.json 更新
  │
  ├── data_type:"reply"     → live2d_face 的 reply_text 端口    ┐
  └── data_type:"knowledge" → logseq_writer 的 entry 端口       ┘  并行
```

Live2D 收到 reply 后，内部并行处理：解析情绪标签 → 切换表情/动作 + MOSS-TTS 语音合成同时进行。

---

## 六、GUI 客户端设计

### 6.1 定位

轻量 PySide6 桌面应用，与 BNOS IDE 完全分离。BNOS 是开发工具，GUI 是用户客户端。

### 6.2 功能模块

| 模块 | 功能 |
|------|------|
| **仪表盘** | 所有节点运行状态概览（绿/黄/红指示灯、CPU/内存占用） |
| **配置中心** | 修改各节点的 `node_config.json` 参数（API Key、模型路径、性能参数等） |
| **日志查看器** | 实时查看各节点的 stdout/stderr 日志，支持过滤和搜索 |
| **对话界面**（可选） | 纯文本对话窗口，显示 AI 回复 |
| **记忆管理**（可选） | 查看/编辑用户事实、认知、摘要 |

### 6.3 界面布局

```
┌─────────────────────────────────────────────┐
│  [仪表盘] [配置] [日志] [对话] [记忆]         │  ← Tab 切换
├─────────────────────────────────────────────┤
│                                             │
│  ┌─ 节点状态 ─────────────────────────────┐  │
│  │ 🟢 AAA 认知中枢      运行中   CPU 2%    │  │
│  │ 🟢 LLM 推理          运行中   CPU 15%   │  │
│  │ 🟢 Live2D 面孔       运行中   GPU 8%    │  │
│  │ 🟡 Grok 工具执行     等待中             │  │
│  │ ⚪ Logseq 写入        未启动             │  │
│  └────────────────────────────────────────┘  │
│                                             │
│  [启动全部] [停止全部] [重启某节点]            │
└─────────────────────────────────────────────┘
```

### 6.4 与 BNOS 引擎的通信

GUI 直接与 AAA 通信（通过 gui_input.json），AAA 处理输入并通过各节点的 status 端口收集状态：

```
GUI ──→ shared/gui_input.json（写） ──→ AAA 直接读取处理
GUI ←── 各节点的 status.json（AAA 汇总或各节点独立输出）
```

| 通信方向 | 机制 | 说明 |
|----------|------|------|
| GUI → AAA | `shared/gui_input.json` | GUI 写 gui_input.json → AAA 直接读取 |
| 节点 → GUI | 各节点 `status.json` | 各节点独立输出 status.json，GUI 直接读取 |
| 配置变更 | 修改 `node_config.json` | GUI 直接修改各节点的配置文件（需重启生效） |
| 日志查看 | 监听 stdout/stderr 日志文件 | GUI 实时 tail 各节点的日志输出 |

---

## 七、分阶段实施计划

### Phase 0：基础设施搭建

**目标**：BNOS 生成轻量运行时引擎 + 共享 DB 搭建

| 任务 | 说明 |
|------|------|
| BNOS 运行时生成器 | BNOS IDE 新增"导出运行时"功能，将当前 DAG 生成精简版引擎 |
| 共享数据库创建 | 创建 `shared/chatbot.db`，初始化全部 10 张表 |
| 项目骨架搭建 | 创建 `nodes/`、`shared/`、`gui/`、`logs/` 目录结构 |
| 节点模板创建 | 使用 BNOS 的 `python_create_node` 工具创建各节点骨架（含多端口配置） |

### Phase 1：核心对话链路（无工具）— P0

**目标**：AAA + LLM + Live2D 基础对话链路跑通

| 任务 | 来源 | 说明 |
|------|------|------|
| **AAA 认知中枢节点**（合并 gui_adapter + user_input） | AAA `main.py` | 提取 DataReader/DataWriter，改为多输入端口+单输出端口+data_type 路由；直接读取 gui_input.json |
| **LLM 推理节点** | 新建 | Python 封装 llama.cpp server API，OpenAI 兼容格式 |
| **Live2D 面孔节点** | My-Neuro | 提取渲染核心 + 情绪映射 + MOSS-TTS，多输入端口 |
| 端到端联调 | — | gui_input → AAA → LLM → AAA → Live2D 完整链路 |

### Phase 2：记忆增强 + 工具调用 + 知识图谱 — P1

| 任务 | 说明 |
|------|------|
| **FAISS 检索集成** | AAA 内两轮 LLM 调用：首轮判断是否需要检索 → 二轮带 FAISS 结果 |
| **多用户记忆支持** | 融合 LN 的 `user_profiles` + `user_facts` 表 |
| **Grok 工具执行节点** | 封装 Grok Build MCP 客户端，tool_call/tool_result 回路 |
| **AAA 工具调用回路** | AAA 解析 LLM 输出 → 判断 tool_call → Grok → 结果回传 → 再次 LLM |
| **Logseq 写入节点** | AAA 输出 knowledge → Logseq Markdown 格式写入 |

### Phase 3：GUI + 打包 — P2

| 任务 | 说明 |
|------|------|
| **PySide6 GUI 客户端** | 仪表盘 + 配置中心 + 日志查看器 |
| **打包分发** | PyInstaller 打包为一键启动包 |

### Phase 4：增强功能 — P3

| 任务 | 说明 |
|------|------|
| 视觉感知节点 | 集成 Supervision，桌面截图分析 |
| 云端模型切换 | LLM 节点支持一键切换本地/云端 |
| 多角色支持 | Live2D 节点支持多模型切换 |
| 声音克隆 | MOSS-TTS 角色声音自定义 |

---

## 八、技术决策记录

| # | 决策 | 理由 | 日期 |
|---|------|------|------|
| 1 | AAA 为唯一中枢，多输入端口 + 单输出端口 | 避免多节点点对点连线混乱；data_type 字段实现单端口多类型路由 | 2026-07-23 |
| 2 | LLM 独立为节点，不绑在 AAA 内 | 模型可替换；Grok 不持推理算力，统一由 llm_infer 入口 | 2026-07-23 |
| 3 | TTS 绑在 Live2D 节点内 | 表情/动作/语音需要精确同步，拆分增加复杂度 | 2026-07-23 |
| 4 | Grok 不持算力，纯工具执行 | 推理算力统一由 llm_infer 提供；Grok 仅执行 MCP 工具，结果回传 AAA → LLM | 2026-07-23 |
| 5 | 工具调用用 Grok Build (MCP)，不用 My-Neuro 插件 | MCP 是开放标准，Grok Build 是 Rust 原生实现 | 2026-07-23 |
| 6 | 记忆用 AAA + LN，不用 MemOS | MemOS 依赖 Qdrant/BM25/CrossEncoder 太重，本地部署复杂 | 2026-07-23 |
| 7 | GUI 用 PySide6，不用 Web | 用户要本地桌面应用，PySide6 与 BNOS 同栈 | 2026-07-23 |
| 8 | Logseq 用于知识图谱，不自建 | Logseq 已有双向链接/标签/属性/查询，避免重复造轮子 | 2026-07-23 |
| 9 | 流式输出改为完整文本 | BNOS 节点间用 output.json 传递完整结果，避免流式分片复杂性 | 2026-07-23 |
| 10 | 模型选 Qwen3-1.7B Q4_K_M，llm_infer 支持切云端 | 本地轻量；双后端一键切换，不锁定单一推理后端 | 2026-07-23 |
| 11 | **删除定时触发器节点** | 用户输入是唯一驱动源；AAA 不再输出 schedule_trigger | 2026-07-23 |
| 12 | **输入/输出直达数据库** | AAA 收到 gui_input/llm_response/tool_result 立即写 DB | 2026-07-23 |
| 13 | **单输出端口 + data_type 路由** | AAA 输出只有一个端口，通过 data_type 字段区分类型，BNOS port_mappings 自动分发 | 2026-07-23 |
| 14 | **gui_adapter + user_input 合并到 AAA** | GUI 输入本质是简单的文件写入（gui_input.json），不需要独立节点做中转；AAA 直接监听文件更高效，减少进程间通信和 node_config 维护成本 | 2026-07-24 |
| 15 | **AAA 内置轻量化会话上下文感知** | 通过 DB 表记录会话状态和时间戳，AAA 内部计算时间间隔并注入 prompt。不依赖跨进程信号，通过超时推断应用生命周期。参考 Lumi_Nox 状态机设计，但实现极简（无独立状态机、无事件总线） | 2026-07-24 |

---

## 九、风险评估

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| Qwen3-1.7B 输出不稳定 | AAA JSON 解析失败 | 中 | 使用 AAA 的 fallback 机制；提示词强化 JSON 格式约束 |
| Live2D 从 Electron 提取困难 | Live2D 节点开发延期 | 中 | 保留 PixiJS + Cubism SDK 核心，仅去除 Electron 壳 |
| MOSS-TTS 延迟过高 | 对话响应慢 | 中 | 使用流式 TTS；考虑火山引擎作为云端降级方案 |
| 多节点进程管理复杂 | 用户启动困难 | 低 | PySide6 GUI 一键启动/停止所有节点 |
| 1.7B 模型回复质量不足 | 用户体验差 | 中 | 支持一键切换到云端大模型（Qwen-Max/GPT-4o） |
| AAA 单点故障 | 整个系统瘫痪 | 低 | 进程级隔离，崩溃自动重启；DB 写入是幂等的 |
| Grok 工具调用超时 | 对话卡住 | 中 | AAA 设置 max_tool_rounds 限制 + 超时降级为无工具回复 |

---

## 十、分阶段实施计划

### 核心原则

每个阶段结束时，必须能**实际运行并观察到效果**。阶段内可细分步骤，但步骤间不累积技术债。

```
阶段 N 前: [部分功能可用]
阶段 N 中: [逐个步骤实现，每一步都可运行]
阶段 N 后: [新功能可用，可演示]
```

---

### Phase 0 — 基础环境就绪

**目标**：确认所有节点文件存在、配置正确、能启动

| 步骤 | 操作 | 可验证结果 |
|------|------|-----------|
| 0.1 | 创建 `shared/` 目录，初始化 `chatbot.db`（建表 SQL） | 数据库文件存在，表结构正确 |
| 0.2 | 修复所有 `node_config.json` 规范问题（`number`→`int`、`resource_limit`） | ruff 检查通过，无 key 缺失 |
| 0.3 | 每个节点独立运行 `init_check`，确认返回 ok | 收到 6 个 `{"status": "ok"}` |
| 0.4 | 准备 llm_infer 的模型文件（下载 qwen3-1.7b-q4_k_m.gguf） | 模型文件就位 |

**耗时**：1-2 小时

**Phase 0 完成后效果**：
```
所有节点可通过 BNOS 画布正常注册、init_check 返回 ok
```

---

### Phase 1 — 最小对话链路（打字→思考→显示）

**目标**：用户打字输入 → AI 回复 → 显示在屏幕上。先做通再做快。

**涉及节点**：`aaa_cognition`（合并 gui_adapter + user_input）、`llm_infer`、`live2d_face`

| 步骤 | 内容 | 可验证结果 |
|------|------|-----------|
| **1.1** | **llm_infer 接入 http_server 后端** — 将已写完的 `LlamaServer` 类接入 `process()`，接收 prompt 调用 HTTP API 返回文本 | `python main.py '{"data_type":"text","content":"你好"}'` → 返回 LLM 回复文本 |
| **1.2** | **aaa_cognition 实现简化 process()** — 不做 context 拼接、不做多端口路由，仅将 gui_input 原样转发为 prompt 到 llm_infer，接收回复后写入 `output.json`（不写 DB） | gui_input → aaa → llm_infer → reply 文本可输出 |
| **1.3** | **openai 兼容格式适配** — 确认 gui_input/aaa/llm_infer 间数据格式统一（data_type + content 格式） | 全链路数据格式验证通过 |
| **1.4** | **BNOS 画布链路联调** — 在画布上连线 aaa → llm_infer → live2d_face（GUI 输入由 AAA 直接读取 gui_input.json），验证完整流式打字回复 | 用户打字 → AI 文字回复出现在 Live2D 界面 |

**耗时**：3-5 天

**Phase 1 完成后效果**：
```
GUI 输入 ──→ AAA(合并 gui_adapter+user_input) ──→ llm_infer ──→ live2d_face
                                                               └── 显示 AI 回复文字
```

---

### Phase 2 — 记忆（DB 读写 + 上下文）

**目标**：AI 能记住刚才说过的话，对话有连续性。

**涉及节点**：`aaa_cognition`（核心改造）、`llm_infer`（支持流式）

| 步骤 | 内容 | 可验证结果 |
|------|------|-----------|
| **2.1** | **实现 chatbot.db 建表与初始化** — 创建 `chat_history`、`short_term_memory`、`long_term_memory` 三张表，AAA 启动时自动创建 | DB 文件生成，表结构正确 |
| **2.2** | **AAA 实现 write_to_db()** — 收到 llm_response 后解析标签（`<think>`、`<reply>` 等），分别写入对应表 | DB 中有数据记录 |
| **2.3** | **AAA 实现 build_context() 基础版** — 从 DB 读取最近 N 条 chat_history，拼接为 system_prompt 的 context 部分 | 发送给 llm_infer 的 prompt 中包含历史消息 |
| **2.4** | **llm_infer 支持流式输出** — process() 支持 `{"stream": true}` 参数，逐 token 写入 output.json | 前端可看到逐字输出的效果 |
| **2.5** | **Node_config 面板调参** — 调整 max_history_summary、temperature 等参数，观察 AI 回复变化 | GUI 面板修改参数后 AI 行为改变 |

**耗时**：2-3 天

**Phase 2 完成后效果**：
```
用户: "我叫小明"
 AI: "你好小明！"
用户: "我叫什么名字？"     ← 依赖 Phase 2 的记忆
 AI: "你叫小明"
```

---

### Phase 3 — 知识持久化（Logseq + FAISS）

**目标**：重要对话存入 Logseq 知识库，支持语义检索。

**涉及节点**：`logseq_writer`、`aaa_cognition`（FAISS 检索）

| 步骤 | 内容 | 可验证结果 |
|------|------|-----------|
| **3.1** | **logseq_writer 实现实际文件写入** — 接收 entry 内容，写入 Logseq pages 目录下的 .md 文件 | Logseq 中可见新 page 生成 |
| **3.2** | **AAA 知识路由** — `port_mappings.knowledge` 激活，将 long_term_memory 内容分流到 logseq_writer | Logseq page 内容与 AI 长期记忆一致 |
| **3.3** | **FAISS 索引构建与检索** — 对 long_term_memory 做 embedding → FAISS index，`gather_context()` 做相似度召回 | 查询相关知识时，AI 能引用历史记录 |

**耗时**：2-3 天

**Phase 3 完成后效果**：
```
对话 → long_term_memory → logseq_writer → Logseq 知识库
                        → FAISS index  → 上下文增强
```

---

### Phase 4 — 工具调用（AI 操控电脑）

**目标**：AI 能调用 grok_hands 执行简单工具操作。

**涉及节点**：`grok_hands`、`aaa_cognition`（tool_call 路由 + tool_result 回传）

| 步骤 | 内容 | 可验证结果 |
|------|------|-----------|
| **4.1** | **grok_hands MCP 集成** — 实现 MCP 客户端，连接 grok_hands 的 MCP 服务器，暴露 3-5 个简单工具（打开文件、截图、鼠标点击） | `python main.py '{"tool":"open_notepad"}'` → 实际打开记事本 |
| **4.2** | **AAA tool_call 路由** — LLM 回复包含 `<tool_call>` 标签时，解析出工具名+参数，通过 port_mappings 发送到 grok_hands | LLM 说"打开计算器"→ 计算器实际启动 |
| **4.3** | **tool_result 回传闭环** — grok_hands 执行结果通过 `_processed` 标记回传 AAA → AAA 拼接为下一次 LLM 调用的一部分 | LLM 知道工具执行结果并据此继续对话 |
| **4.4** | **最大工具调用轮数限制** — 实现 max_tool_rounds 参数控制，防止无限循环 | 超过轮数后 AI 停止调用工具 |

**耗时**：5-7 天

**Phase 4 完成后效果**：
```
用户: "打开记事本然后写一行 Hello"
 AI: 执行 tool_call → grok_hands → 打开记事本
     看到 tool_result → 继续调用 → 写入文字
     最终回复: "已打开记事本并写入 Hello"
```

---

### Phase 5 — 多模态输入（语音 + 环境感知）

**目标**：AI 能听能看能感知。

**涉及节点**：`asr_input`、`env_input`、`vision_input`（新建）

| 步骤 | 内容 | 可验证结果 |
|------|------|-----------|
| **5.1** | **asr_input Whisper 集成** — 接入 whisper-main，实时语音识别，输出 text 数据流 | 说话 → ASR 节点输出识别文本 |
| **5.2** | **env_input psutil 采集** — 每 5s 采集 CPU/内存/进程/网络数据，输出 JSON | 环境数据实时更新到 output.json |
| **5.3** | **AAA 多输入端口整合** — asr_input 和 env_input 的数据通过 input_ports 进入 AAA，按 filter 分流处理 | 语音输入和环境数据同步影响 AI 回复 |
| **5.4** | **vision_input 节点创建** — 接入 supervision，实时摄像头检测，输出物体/人脸坐标 | 摄像头画面分析结果输出 |

**耗时**：4-6 天

**Phase 5 完成后效果**：
```
麦克风 → asr_input ──┐
摄像头 → vision ────┼──→ AAA ──→ llm_infer ──→ reply
环境   → env_input ─┘
```

---

### Phase 6 — 稳定化与用户体验

**目标**：系统可靠运行，容错恢复，配置面板完善。

| 步骤 | 内容 | 可验证结果 |
|------|------|-----------|
| **6.1** | **各节点 status 收集** — 各节点输出独立 status.json，GUI 或 AAA 定期汇总 | 控制面板实时显示所有节点运行状态 |
| **6.2** | **错误处理与重试** — AAA 处理 LLM 超时、工具调用失败的降级策略 | 拔掉网线 → AI 回复"网络异常，请稍后重试" |
| **6.3** | **节点启动顺序检测** — Phase 启动脚本检查依赖关系，等待上游就绪 | 一键启动所有节点，按顺序自动等待 |
| **6.4** | **GUI 配置面板完善** — 各节点 parameters 同步到 GUI 侧边栏 | 侧边栏可调整所有节点的可配置参数 |

**耗时**：3-5 天

---

### 阶段依赖关系图

```
Phase 0: 环境就绪
    │
    ▼
Phase 1: 最小对话链路  ◄── 最优先，拿到运行效果
    │
    ├──── Phase 2: 记忆（依赖 Phase 1 的链路）
    │         │
    │         ▼
    │    Phase 3: 知识持久化（依赖 Phase 2 的 DB）
    │
    ├──── Phase 4: 工具调用（可独立于 Phase 2/3 进行）
    │
    └──── Phase 5: 多模态（可独立进行）
                │
                ▼
          Phase 6: 稳定化（依赖所有节点就绪）
```

---

## 十一、实现现状与节点索引

### 11.1 总体状态

| 节点 | 方案状态 | 实现状态 | 关键缺口 |
|------|---------|---------|----------|
| `aaa_cognition` | ✅ [完成](nodes/node_python_aaa_cognition/开发方案.md) | 🟢 核心链路完成并测试通过 | 已合并 gui_adapter + user_input，直接监听 gui_input.json；`process()` 实现完整：上下文拼接、节标记解析、情绪注入、DB 持久化；AAA → LLM → AAA 端到端循环验证成功；**会话上下文感知设计方案已完成，待实现** |
| `llm_infer` | ✅ [完成](nodes/node_python_llm_infer/开发方案.md) | 🟢 云端 API 后端接入并测试通过 | `process()` + `CloudApiBackend` 完整链路通过 DeepSeek 真实 API 验证；三后端类齐全（http_server/cli_local/cloud） |
| `live2d_face` | ✅ [完成](nodes/node_js_live2d_face/开发方案.md) | 🟢 核心逻辑完整 | 情绪解析、TTS 集成、init_check 均已实现 |
| `grok_hands` | ✅ [完成](nodes/node_rust_grok_hands/开发方案.md) | 🟡 基础编译可用，缺 MCP 集成 | 仅 hello-world 级别 |
| `logseq_writer` | ✅ [完成](nodes/node_python_logseq_writer/开发方案.md) | 🟡 生成 .md 内容但未写磁盘 | 返回文件内容，未实际写入 Logseq 目录 |
| `asr_input` | ✅ [完成](nodes/node_python_asr_input/开发方案.md) | 🔴 预留状态 | 骨架存在，Whisper 集成未实施 |
| `env_input` | ✅ [完成](nodes/node_python_env_input/开发方案.md) | 🔴 预留状态 | 骨架存在，psutil 采集未实施 |
| `vision_input` | — | 🔴 预留 | Phase 2+，尚未创建节点 |

> 🟢 = 可用 &nbsp; 🟡 = 部分实现 &nbsp; 🔴 = 未实现/骨架

### 11.2 各节点开发方案索引

每个节点的开发方案包含：定位说明、端口定义、`node_config.json` 模版、处理逻辑伪代码、依赖清单、测试计划。详见对应文件：

| 节点 | 方案文件 | 代码目录 |
|------|---------|---------|
| AAA 认知中枢 | [aaa_cognition/开发方案.md](nodes/node_python_aaa_cognition/开发方案.md) | [aaa_cognition/](nodes/node_python_aaa_cognition/) |
| LLM 推理 | [llm_infer/开发方案.md](nodes/node_python_llm_infer/开发方案.md) | [llm_infer/](nodes/node_python_llm_infer/) |
| Live2D 面孔 | [live2d_face/开发方案.md](nodes/node_js_live2d_face/开发方案.md) | [live2d_face/](nodes/node_js_live2d_face/) |
| Grok 工具 | [grok_hands/开发方案.md](nodes/node_rust_grok_hands/开发方案.md) | [grok_hands/](nodes/node_rust_grok_hands/) |
| Logseq 写入 | [logseq_writer/开发方案.md](nodes/node_python_logseq_writer/开发方案.md) | [logseq_writer/](nodes/node_python_logseq_writer/) |
| ASR 语音输入 | [asr_input/开发方案.md](nodes/node_python_asr_input/开发方案.md) | [asr_input/](nodes/node_python_asr_input/) |
| 环境监控 | [env_input/开发方案.md](nodes/node_python_env_input/开发方案.md) | [env_input/](nodes/node_python_env_input/) |

### 11.3 node_config.json 规范差异修正

各节点开发方案中的 `node_config.json` 与当前实现存在差异，此处记录标准化修正：

| 节点 | 字段 | 方案定义 | 当前实现 | 修正方向 |
|------|------|---------|---------|---------|
| aaa_cognition | `filter.llm_response` | `{"data_type": "text"}` | `{"data_type": "parsed"}` | 统一为 `text`（LLM 返回原始文本，在 AAA 内解析） |
| aaa_cognition | `parameters[].type` | `"int"` / `"float"` | 用了 `"number"` | 改为 `"int"` / `"float"`（BNOS 规范） |
| llm_infer | `model_type` 选项 | `["http_server", "cli_local", "cloud_openai"]`（3 后端） | `["http_server", "cli_local", "cloud_api"]`（当前实装） | 方案与实现需统一 |
| all | `resource_limit` | 方案中未定义 | 实现中部分有 | 统一添加 `resource_limit.memory_mb: 512` |
| live2d_face | `parameters` | 含 TTS 相关参数 | 缺少部分 TTS 参数 | 需同步方案中的完整参数列表 |

### 11.4 管线依赖顺序

节点启动顺序（按依赖关系）：

```
Phase 1 核心：
  ① shared/chatbot.db 初始化（手动或 AAA 首次启动自动创建）
  ② live2d_face（Live2D 模型加载 + TTS 服务就绪）
  ③ llm_infer（LLM 模型加载 / API 连接）
  ④ aaa_cognition（DB + FAISS 初始化）← 所有上游就绪后启动

Phase 2 扩展（不阻塞核心链路）：
  ⑦ logseq_writer（Logseq 目录验证）
  ⑧ grok_hands（MCP 服务器连接）
  ⑨ asr_input / env_input（预留节点）
```

### 11.5 开发优先级（按当前实现状态定）

参照各节点方案与实际代码的差距，推荐执行顺序：

| 优先级 | 节点 | 工作量估计 | 前置依赖 |
|--------|------|-----------|---------|
| **P0** ✅ | aaa_cognition — `process()` 完成，AAA → LLM → AAA 全链路已测试通过 | — | — |
| **P0** ✅ | llm_infer — 云端 API 后端接入，AAA + LLM 端到端验证通过 | — | — |
| **P1** | aaa_cognition — 会话上下文感知实现 | 小 (1天) | DB 结构就绪 |
| **P1** | logseq_writer — 实际写磁盘 | 小 (0.5天) | Logseq pages 目录配置 |
| **P1** | 端到端联调 | 中 (2-3天) | P0 完成 |
| **P2** | grok_hands — MCP 工具执行 | 大 (5-7天) | Rust 编译环境 |
| **P2** | asr_input — Whisper 集成 | 中 (3-5天) | whisper-main 依赖 |
| **P2** | env_input — psutil 采集 | 小 (0.5天) | — |
| **P3** | vision_input — 新建节点 | 大 (5-7天) | supervision 集成 |

---

> 本方案基于 BNOS V2.0.32、AAA V1、Lumi_Nox、My-Neuro、Grok Build 五大项目的全部产出物汇总设计。
>
> 各节点详细开发方案见 `nodes/<node_name>/开发方案.md`，实现现状跟踪见第十节。
>
> 开发与设计：**Ahdong&Shouey Team**
