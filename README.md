# BNOS AI Companion

🌍 Language: **English** | [中文](README_CN.md)

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10+-yellow?style=for-the-badge\&logo=python)
![PySide6](https://img.shields.io/badge/PySide6-Qt_6-green?style=for-the-badge\&logo=qt)
![Rust](https://img.shields.io/badge/Rust-Supported-orange?style=for-the-badge\&logo=rust)
![SQLite](https://img.shields.io/badge/SQLite-Storage-blue?style=for-the-badge\&logo=sqlite)
![License](https://img.shields.io/badge/License-MIT-red?style=for-the-badge)

**A fully local AI digital companion — a single AI organism, not a chatbot, not a multi-agent platform.**

</div>

***

## Overview

BNOS AI Companion is a **fully local, single-entity AI companion**. It is built on the [BNOS](https://github.com/LiuStar656/BNOS---Bionic-Neural-Network-Visual-Orchestration-Platform) orchestration engine and integrates cognition, memory, emotion evolution, tool use and knowledge management into **one AI organism** — an entity with its own memory, its own personality, and its own autonomous behavior.

The companion is structured like an organism: each "organ" is an independent node running in its own OS process and virtual environment. The BNOS engine is the nervous system that schedules them, and all organs communicate through a file-based JSON protocol.

> This project demonstrates the orchestration capability of BNOS applied to a complete, local-first AI product.

***

## Core Design Philosophy

| Principle | Implementation | Commitment |
|-----------|----------------|------------|
| **AI is an independent entity** | Own memory, own personality, own thoughts | Not merely a user tool |
| **Fully local** | All data and models stored & run locally | User owns all privacy |
| **Unlimited growth** | Node-level orchestration, capabilities keep expanding | No functional ceiling |
| **Process-level isolation** | Each node: independent process + independent venv | Crashes don't cascade |

### The Organism Metaphor

| AI Part | Corresponding Component | Responsibility |
|---------|------------------------|----------------|
| 🧠 **Brain** | `aaa_cognition` + `memos.py` | Cognition loop, memory read/write, emotion evolution |
| 👤 **Face** | `live2d_face` + `tts` | Live2D expressions, TTS speech synthesis |
| 🖐️ **Hands** | `grok_hands` (Rust) | External tool calls: search, execute, control |
| 🐚 **Hippocampus** | `logseq_writer` | Knowledge graph, long-term document archiving |
| ⚡ **Nervous system** | `BNOS` engine | DAG orchestration, process scheduling, file protocol |

***

## Architecture

### Star Topology: One Cognition Hub, Many Inputs

All input sources converge on the **AAA cognition hub** (the single memory entry point), which routes through **one output port with `data_type` routing**:

- `prompt` → LLM
- `tool_call` → Grok (Rust tools)
- `reply` → Live2D face
- `knowledge` → Logseq writer

```
ASR / GUI / env input ──→  aaa_cognition ──→  llm_infer ──→  aaa_cognition ──→  live2d_face (display)
    (3-phase prompt,         ↑                (parse,          └──→ tts (speech)
     MemOS semantic           │                write DB,
     retrieval,               └── memos        index rebuild)
     identity_key)               (built-in)

                      grok_hands (tool execution)
                      logseq_writer (knowledge persistence)
```

### Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Orchestration | BNOS (Python/PySide6) | IDE for development, lightweight engine at runtime |
| Memory | Python + SQLite + MemOS (numpy) | AAA cognition loop + vector semantic retrieval |
| LLM inference | llama.cpp + cloud API | Dual backends, one-click switch |
| Live2D rendering | PixiJS + Cubism SDK 4.x | Extracted from My-Neuro |
| TTS | edge-tts + MOSS-TTS-Local | Online + local dual channel |
| Tool execution | Grok Build (Rust) | MCP protocol client |
| Knowledge graph | Logseq | Markdown + bidirectional links |
| GUI client | PySide6 | Lightweight, non-web |
| Communication | File JSON | stdin/stdout + output.json |

***

## Node Matrix

| # | Node | Language | Role | Status |
|---|------|----------|------|--------|
| 1 | `node_python_aaa_cognition` | Python | Data hub: 3-phase prompt + MemOS + tag parsing | 🟢 Core chain complete |
| 2 | `node_python_llm_infer` | Python | LLM inference: cloud API + local GGUF | 🟢 Cloud API integrated |
| 3 | `node_js_live2d_face` | JS | Character display: Live2D Cubism 4.x | 🟢 Core logic complete |
| 4 | `node_python_tts` | Python | Speech synthesis: edge-tts + MOSS local | 🟢 Basic usable |
| 5 | `node_python_asr_input` | Python | Speech recognition: Silero VAD + SenseVoice | 🔴 Design finalized |
| 6 | `node_python_env_input` | Python | Environment sensing: CPU / memory / time | 🔴 Skeleton exists |
| 7 | `node_python_logseq_writer` | Python | Knowledge archiving: Markdown + backlinks | 🟡 Generates .md, not writing to disk |
| 8 | `node_rust_grok_hands` | Rust | Tool execution: MCP protocol | 🟡 Compiles, basic usable |
| 9 | `node_python_vlm` | Python | Multimodal vision: screen / camera / image | 🔴 To be created |

### Key Subsystems

| Subsystem | Location | Core Capability |
|-----------|----------|-----------------|
| MemOS semantic retrieval | `aaa_cognition/memos.py` | SentenceTransformer encoding + numpy cosine similarity + decay |
| 3-phase prompt | `aaa_cognition/prompt.py` | Thin prompt → LLM decides retrieval → second interaction with results |
| `identity_key` isolation | Full pipeline | Multi-user data isolation, vector space partitioned per user |
| `turn_taking` filter | AAA internals | Rule filtering + observation buffer + hysteresis loop |
| Personality evolution | AAA planned | 4-dim personality vector (warm/lively/direct/curious) + passive feedback |

***

## Key Features

- **AAA cognition loop** — a deterministic cognition cycle: perceive → retrieve → reason → act → remember, with a 3-phase prompt design.
- **Memory evolution** — SQLite + MemOS vector retrieval with decay, letting the companion's memory grow and fade like a real one.
- **Cross-vendor LLM experiments** — DeepSeek / Qwen consistency tests and long-term memory evolution studies (see `tests/`, `scripts/aaa_compare/`).
- **Traceable agent behavior** — every node writes structured JSON; the full chain GUI → LLM → face is auditable.
- **Fully local GUI** — PySide6 dashboard (node status / CPU / memory) plus a chat page and knowledge-base panel.
- **Research subproject `schemanet/`** — an independent study on gradient-free structural learning (spiking networks with Hebbian/STDP rules). See its [own README](schemanet/README.md).

***

## Quick Start

```bash
# 1. Clone
git clone https://github.com/LiuStar656/BNOS-AI.git
cd BNOS-AI

# 2. Start all nodes
run.bat        # Windows
./run.sh       # Linux / macOS

# 3. The PySide6 GUI opens automatically — chat with the AI in the "Chat" page
```

> API keys are read from environment variables only (`DEEPSEEK_API_KEY`, `QWEN_API_KEY`). No keys are hardcoded.

***

## Project Structure

```
BNOS_AI_project/
├── bnos_runtime/            # BNOS runtime engine (engine, pipeline loader, runner)
├── nodes/                   # Core nodes (each: independent process + venv)
│   ├── node_python_aaa_cognition/   # 🧠 cognition hub (memos.py / prompt.py / db.py)
│   ├── node_python_llm_infer/       # ⚡ LLM inference
│   ├── node_js_live2d_face/         # 👤 Live2D face
│   ├── node_python_tts/             # 🔊 speech synthesis
│   ├── node_python_asr_input/       # 👂 speech recognition (planned)
│   ├── node_python_env_input/       # 🌡️ environment sensing
│   ├── node_python_logseq_writer/   # 📝 knowledge archiving
│   └── node_rust_grok_hands/        # 🖐️ tool execution (Rust)
├── gui/                     # PySide6 client (dashboard / chat / knowledge / settings)
├── docs/                    # design docs & architecture docs
├── schemanet/               # research subproject (gradient-free structural learning)
├── tests/                   # consistency / evolution tests
├── scripts/                 # experiment scripts (aaa_compare, ...)
├── pipeline.json            # core pipeline declaration
└── run.bat / run.sh         # launchers
```

***

## Testing & Experiments

- `tests/llm_consistency_test.py` — cross-round consistency of the same persona.
- `tests/self_evolution_test.py` — memory/emotion evolution over many rounds.
- `tests/message_pool/` — interest-gated multi-source message platform experiments.
- `scripts/aaa_compare/` — cognition design comparisons (e1e2 / e4 / e6).
- `schemanet/` — see its report in `schemanet/docs/`.

***

## Documentation

| Doc | Status | Description |
|-----|--------|-------------|
| [BNOS-AI 伴侣开发方案](BNOS-AI伴侣开发方案.md) | Design master | Initial architecture & core chain (Chinese) |
| [节点开发规范](节点开发规范.md) | Current spec | Node development standard (Chinese) |
| [node_config_json 开发规范](node_config_json_开发规范.md) | Current spec | `node_config.json` schema (Chinese) |
| `docs/design/` | PLAN | Feature design docs (3D character, personality seed, event-driven behavior, ...) |

***

## Known Limitations

- TTS currently online-only (edge-tts); local engines planned.
- ASR, VLM and environment input nodes are designed but not yet implemented.
- `logseq_writer` generates Markdown but does not write to the Logseq directory yet.
- Local GGUF inference is wired but cloud API is the primary tested path.

***

## License

[MIT](LICENSE) © 2026 Ahdong&Shouey
