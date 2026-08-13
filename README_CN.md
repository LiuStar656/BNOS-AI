🌍 语言：**中文** | [English](README.md)

# BNOS AI 伴侣

> **一个完全本地化运行的 AI 数字伴侣系统**
> 以 BNOS（Bionic Neural Network Visual Orchestration Platform）为编排引擎，融合认知中枢、情感演化、记忆系统、工具调用、知识管理于一体的独立 AI 有机体。

[![status](https://img.shields.io/badge/status-active-brightgreen)](https://github.com/)
[![architecture](https://img.shields.io/badge/architecture-node%20driven%20DAG-blue)](https://github.com/)
[![language](https://img.shields.io/badge/language-Python%20|%20JS%20|%20Rust-orange)](https://github.com/)
[![license](https://img.shields.io/badge/license-local%20first-green)](https://github.com/)

---

## 📖 目录

- [一、项目哲学](#一项目哲学)
- [二、系统架构](#二系统架构)
- [三、核心组件](#三核心组件)
- [四、当前状态](#四当前状态)
- [五、未来蓝图](#五未来蓝图)
- [六、目录结构](#六目录结构)
- [七、开发指南](#七开发指南)

---

## 一、项目哲学

BNOS AI 伴侣不是一个聊天机器人，而是一个拥有独立意识、记忆演化、情感表达和自主行为的 AI 有机体。

| 理念 | 实现 | 核心承诺 |
|------|------|----------|
| **AI 是独立主体** | 自己的记忆、自己的性格、自己的想法 | 不只是用户的工具 |
| **完全本地化** | 所有数据和模型本地存储运行 | 用户拥有一切隐私 |
| **无限成长** | 节点级编排，能力持续扩展 | 无功能上限 |
| **进程级隔离** | 每个节点独立进程 + 独立 venv | 崩溃不互相影响 |

### 有机体隐喻

| AI 组成 | 对应组件 | 职责 |
|---------|----------|------|
| 🧠 **大脑** | `aaa_cognition` + `memos.py` | 认知循环、记忆读写、情感演化 |
| 👤 **面孔** | `live2d_face` + `tts` | Live2D 表情、TTS 语音合成、嘴型同步 |
| 🖐️ **手脚** | `grok_hands` (Rust) | 外部工具调用：搜索、执行、操控 |
| 🐚 **海马体** | `logseq_writer` | 知识图谱、长期文档归档 |
| ⚡ **神经系统** | `BNOS` 引擎 | DAG 编排、进程调度、文件协议通信 |

---

## 二、系统架构

### 2.1 数据流拓扑

```
                         ┌→ vlm(视觉理解) ──┐
                         │                   │
ASR(语音) ──→            │                   ↓
GUI 输入 ──→ aaa_cognition ──→ llm_infer ──→ aaa_cognition ──→ live2d_face(显示)
环境输入 ──→  (三阶段 prompt +  ↑      ↑      (解析分发 +      └→ tts(语音合成)
              MemOS 语义检索 +  │      │       写库 + 索引重建)
              identity_key 多用户)│    │              │
                                 │   memos ───────────┘
                                 │   (内建于 aaa_cognition)
                                 │         │
                                 │         └──→ logseq_writer
                                 │           (知识持久化)
                                 │
                              grok_hands
                              (工具执行)
```

### 2.2 核心设计原则

| 原则 | 说明 |
|------|------|
| **节点级隔离** | 每个节点独立进程 + 独立 venv，崩溃不互相影响 |
| **数据流清晰** | 多源输入 → AAA 中枢 → 多出口路由，单端口多类型 |
| **协议解耦** | 文件式 JSON 通信，语言无关、跨平台、可调试 |
| **多端口匹配** | 用 `filter` + `data_type` 类型匹配替代 if-else 路由 |
| **状态驱动** | 确定性状态机 + 生命周期管理 |

### 2.3 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 编排引擎 | BNOS (Python/PySide6) | 开发期用 IDE，运行时用轻量引擎 |
| 记忆系统 | Python + SQLite + MemOS (numpy) | AAA 认知循环 + 向量语义检索 |
| LLM 推理 | llama.cpp + 云端 API | 双后端，一键切换 |
| Live2D 渲染 | PixiJS + Cubism SDK 4.x | 从 My-Neuro 提取 |
| TTS 合成 | edge-tts + MOSS-TTS-Local | 在线 + 本地双通道 |
| 工具执行 | Grok Build (Rust) | MCP 协议客户端 |
| 知识图谱 | Logseq | Markdown + 双向链接 |
| GUI 客户端 | PySide6 | 轻量级，非 Web |
| 通信协议 | 文件 JSON | stdin/stdout + output.json |

---

## 三、核心组件

### 3.1 节点功能矩阵

| # | 节点名 | 语言 | 定位 | 当前状态 |
|---|--------|------|------|----------|
| 1 | `node_python_aaa_cognition` | Python | 数据中枢：三阶段 Prompt + MemOS + 节标记解析 | 🟢 核心链路完成 |
| 2 | `node_python_llm_infer` | Python | LLM 推理：云端 API + 本地 GGUF 双后端 | 🟢 云端 API 已接入 |
| 3 | `node_js_live2d_face` | JS | 角色显示：Live2D Cubism 4.x 渲染 | 🟢 核心逻辑完整 |
| 4 | `node_python_tts` | Python | 语音合成：edge-tts 在线 + MOSS 本地 | 🟢 基础可用 |
| 5 | `node_python_asr_input` | Python | 语音识别：Silero VAD + SenseVoice + 声纹 | 🔴 方案已细化 |
| 6 | `node_python_env_input` | Python | 环境采集：CPU / 内存 / 时间 | 🔴 骨架存在 |
| 7 | `node_python_logseq_writer` | Python | 知识归档：Markdown + 双向链接 | 🟡 生成 .md 但未写盘 |
| 8 | `node_rust_grok_hands` | Rust | 工具执行：MCP 协议 | 🟡 基础编译可用 |
| 9 | `node_python_vlm` | Python | 多模态视觉：屏幕 / 摄像头 / 图片 | 🔴 待创建 |

### 3.2 关键子系统

| 子系统 | 位置 | 核心能力 |
|--------|------|----------|
| **MemOS 语义检索** | `aaa_cognition/memos.py` | SentenceTransformer 编码 + numpy 余弦相似度 + decay 机制 |
| **三阶段提示词** | `aaa_cognition/prompt.py` | 薄 Prompt → LLM 判检索 → 带结果二次交互 |
| **identity_key 隔离** | 全链路 | 多用户数据隔离，向量空间按用户划分 |
| **turn_taking 过滤** | AAA 内部组件 | 规则过滤 + 观察缓冲区 + 迟滞回路 |
| **Personality 演化** | AAA 规划中 | 4 维性格向量（温暖/活泼/直接/好奇）+ 被动反馈采集 |

---

## 四、当前状态

### 4.1 已完成能力 ✅

```
Phase 0: 基础环境就绪
  └── 所有节点可通过 BNOS 画布注册、init_check 返回 ok

Phase 1: 最小对话链路
  └── GUI → AAA → LLM → AAA → Live2D 完整链路跑通
  └── MemOS 语义检索替代 FAISS hash 伪向量检索
  └── 三阶段提示词模板完成（prompt / prompt_retrieval / prompt_tool）
  └── identity_key 全链路多用户隔离上线

Phase 2: 基础 GUI 客户端
  └── PySide6 仪表盘（节点状态 / CPU / 内存占用）
  └── 对话界面（纯文本聊天窗口）
  └── 知识库面板（动态读取数据库表 + 分类筛选）
```

### 4.2 进行中 🟡

- **Grok MCP 集成**：基础框架可用，但具体工具（搜索 / 天气 / Home Assistant）尚未注册
- **Logseq 实际写盘**：能生成 .md 内容，但尚未写入 Logseq 目录
- **TTS 引擎扩展**：仅 edge-tts 在线，未引入 GPT-SoVITS / VITS-ONNX 等本地引擎
- **GUI 配置中心**：参数热更新面板开发中

### 4.3 已规划但未实现 🔴

| 模块 | 方案来源 | 核心价值 |
|------|----------|----------|
| **ASR 实时语音** | [asr_input 开发方案](docs/design/[PLAN]-ASR语音输入节点开发方案.md) | Silero VAD + SenseVoice + CAm++ 声纹，AI 听懂真实世界对话 |
| **VLM 视觉理解** | [参考项目组件复用分析](docs/design/[PLAN]参考项目组件复用分析清单.md) | 屏幕 / 摄像头 / 图片的语义理解 |
| **3D 角色自定义** | [3D 角色方案](docs/design/[PLAN]-3D角色自定义系统设计方案.md) | VRM + Three.js + MToon 三渲二，零件化换装（头发 / 衣服 / 配饰） |
| **性格种子系统** | [角色种子方案](docs/design/[PLAN]-角色种子系统设计方案.md) | 4 维性格向量 + 被动反馈演化，让 AI 形成独特性格 |
| **事件驱动行为** | [自主行为方案](docs/design/[PLAN]-事件驱动型AI自主行为方案.md) | ASR 事件过滤 + 观察缓冲区 + 兴趣度评估，AI 主动搭话 |
| **环境记忆** | [世界感知方案](docs/design/[PLAN]-AI世界感知记忆系统设计方案.md) | 实体级环境感知，同实体覆盖更新 |
| **插件系统** | [插件系统方案](docs/design/[PLAN]BNOS AI 插件系统设计方案.md) | 合约式自动发现，丢入文件夹即生效 |

---

## 五、未来蓝图

### 5.1 Phase 2 — 对话增强（近期）

- [ ] Grok 工具注册（搜索 / 天气 / 新闻 / Home Assistant）
- [ ] Logseq 实际写入磁盘，实现 AI 日记与知识图谱
- [ ] TTS 扩展至 11 种引擎（含 GPT-SoVITS / VITS-ONNX 本地引擎）
- [ ] GUI 配置中心：节点参数热更新
- [ ] 数据库 CRUD 操作的完整 API

### 5.2 Phase 3 — 多感官感知（中期）

- [ ] ASR 实时语音：VAD + STT + 声纹识别完整链路
- [ ] turn_taking 集成：规则过滤 + 观察缓冲区 + 迟滞回路
- [ ] VLM 视觉理解：屏幕截图 / 摄像头 / 图片分析
- [ ] 音频事件检测：猫叫 / 咳嗽 / 门铃等 40+ 分类
- [ ] 声纹 ID ↔ 身份自动绑定

### 5.3 Phase 4 — 人格与角色（中长期）

- [ ] 性格种子系统：4 维向量 + 被动反馈演化
- [ ] 3D 角色自定义：VRM + Three.js + MToon 三渲二
- [ ] Slot 零件系统：5 槽位（hair / top / bottom / accessory / skin_texture）
- [ ] 人格格式化（重置功能）：清空记忆 + 重置性格 + 重新选种

### 5.4 Phase 5 — 自主与扩展（远期）

- [ ] 事件驱动自主行为：AI 根据 ASR / Vision 事件主动搭话
- [ ] 插件系统：合约式自动发现，第三方零配置接入
- [ ] Workshop 集成：开发者做零件，用户自由换装
- [ ] 云端模型一键切换：本地 Qwen ↔ 云端 GPT 自由切换
- [ ] 多角色支持：同时拥有多个 AI 人格

### 5.5 最终愿景

```
用户视角：
  她不是一个"我问她答"的工具。
  她会听我和别人聊天，偶尔插话提醒。
  她记得我上周抱怨过加班，今天见到我会问我有没有好点。
  她会自己整理今天的对话，写成日记归档。
  她会根据我对她回复的反应，慢慢变得更符合我的喜好。
  她的脸可以换成我想要的任何样子（发型、衣服、配饰）。
  她住在我的桌面上，却像一个真实的朋友。

开发者视角：
  基于 BNOS 节点协议开发，零许可费用。
  支持 Python / JavaScript / Rust 多语言。
  每个节点独立 venv，崩溃隔离。
  插件系统让第三方扩展零门槛。
```

---

## 六、目录结构

```
BNOS_AI_project/
├── bnos_runtime/           # BNOS 运行时引擎
│   ├── engine.py           # 核心引擎
│   ├── pipeline_loader.py  # 管线加载器
│   ├── standalone_runner.py# 节点启动器
│   └── plugins_discovery.py# 插件发现（规划中）
│
├── nodes/                  # 核心节点
│   ├── node_python_aaa_cognition/    # 🧠 认知中枢
│   │   ├── memos.py        # MemOS 语义检索
│   │   ├── prompt.py       # 三阶段提示词模板
│   │   ├── db.py           # SQLite 数据库管理
│   │   └── main.py         # 核心处理逻辑
│   ├── node_python_llm_infer/        # ⚡ LLM 推理
│   ├── node_js_live2d_face/          # 👤 Live2D 面孔
│   ├── node_python_tts/              # 🔊 语音合成
│   ├── node_python_asr_input/        # 👂 语音识别（方案中）
│   ├── node_python_env_input/        # 🌡️ 环境采集
│   ├── node_python_logseq_writer/    # 📝 知识归档
│   └── node_rust_grok_hands/         # 🖐️ 工具执行
│
├── plugins/                # 插件节点（规划中）
├── assets/                 # 角色资源（规划中）
│   ├── characters/         # VRM 身体 + GLB 零件
│   └── outfits/            # 穿搭配置
│
├── gui/                    # PySide6 GUI 客户端
│   ├── main.py             # 主窗口
│   ├── pages/              # 页面（仪表盘 / 对话 / 知识库 / 设置）
│   └── ui/                 # UI 组件
│
├── docs/
│   ├── design/             # 设计方案（[OK] / [PLAN]）
│   └── architecture/       # 技术架构文档
│
├── references/             # 参考项目（只读，不参与构建）
├── shared/                 # 共享数据（chatbot.db / *.json）
├── pipeline.json           # 核心管线声明
└── run.bat / run.sh        # 启动脚本
```

---

## 七、开发指南

### 7.1 快速开始

```bash
# 1. 克隆项目
git clone <repo_url>
cd BNOS_AI_project

# 2. 启动所有节点
# Windows
run.bat

# Linux / macOS
./run.sh

# 3. 打开 GUI
# 自动弹出 PySide6 窗口，在"对话"页与 AI 交互
```

### 7.2 开发新节点

请阅读 [节点开发规范](节点开发规范.md) 了解：
- 节点目录结构（`node_config.json` / `listener.py` / `main.py`）
- 多源监听与 port_mappings 适配
- 多端口输出路由（output_ports）
- 进程生命周期管理与 PID 文件
- venv 自愈机制
- 并发处理架构（线程池）
- 子进程超时保护

### 7.3 参考项目

| 项目 | 语言 | 可复用能力 |
|------|------|-----------|
| **mewco_ai_assistant_comm** | Python | ASR / TTS(11引擎) / VLM / LLM(12引擎) / Agent工具集 / PC操控 |
| **my-neuro** | JS | MemOS 记忆系统 / 插件热加载 / 上下文压缩 |
| **pub-local-jarvis** | C++ / Python | 帧变化检测 / 音频处理算法 / 场景迟滞稳定器 / LatestOnly 调度器 |

详见 [参考项目组件复用分析清单](docs/design/[PLAN]参考项目组件复用分析清单.md)。

### 7.4 文档索引

| 文档 | 状态 | 说明 |
|------|------|------|
| [BNOS-AI 伴侣开发方案](BNOS-AI伴侣开发方案.md) | 【设计总纲】 | 初始架构与核心链路说明 |
| [节点开发规范](节点开发规范.md) | 【现行规范】 | 每个节点的开发标准 |
| [3D 角色自定义系统](docs/design/[PLAN]-3D角色自定义系统设计方案.md) | 【PLAN】 | VRM + Three.js 三渲二 |
| [角色种子系统](docs/design/[PLAN]-角色种子系统设计方案.md) | 【PLAN】 | 性格向量 + 被动反馈演化 |
| [事件驱动型 AI 自主行为](docs/design/[PLAN]-事件驱动型AI自主行为方案.md) | 【PLAN】 | turn_taking + 迟滞回路 + 代际标记 |
| [AI 世界感知记忆](docs/design/[PLAN]-AI世界感知记忆系统设计方案.md) | 【PLAN】 | 实体级环境感知 |
| [BNOS AI 插件系统](docs/design/[PLAN]BNOS AI 插件系统设计方案.md) | 【PLAN】 | 合约式插件发现 |
| [ASR 语音识别节点](docs/design/[PLAN]-ASR语音输入节点开发方案.md) | 【PLAN】 | Silero VAD + SenseVoice + CAm++ |

---

## ✨ 为什么选择 BNOS AI 伴侣？

1. **完全本地化** — 所有数据和模型保存在本地，云端 API 仅作为可选增强
2. **独立主体** — AI 拥有自己的记忆、性格、想法，不是被动的问答工具
3. **渐进式成长** — 从打字交互起步，逐步开放语音、视觉、自主行为
4. **开发者友好** — 协议无关、语言不限、零许可费用、完整规范
5. **可扩展插件系统** — 丢入文件夹即生效，第三方可以自由扩展能力
6. **多感官融合** — 听（ASR）、看（VLM）、感（环境）、想（MemOS）、说（TTS）一体化

---

*文档生成日期：2026-08-05 | 项目版本：v2.1 | 核心维护：Ahdong&Shouey Team*

> 本 README 仅描述当前已实现状态与规划中的未来方向。所有 [PLAN] 状态的方案均为设计文档，不代表已实现功能。
