# BNOS AI 插件系统设计方案

## 目录

- [1. 背景与目标](#1-背景与目标)
- [2. 核心概念](#2-核心概念)
- [3. 目录结构](#3-目录结构)
- [4. node_config.json 新增字段](#4-node_configjson-新增字段)
- [5. 合约发现与匹配算法](#5-合约发现与匹配算法)
- [6. BNOS AI 启动流程](#6-bnos-ai-启动流程)
- [7. plugins_discovery.py 模块设计](#7-plugins_discoverypy-模块设计)
- [8. 实现变更清单](#8-实现变更清单)
- [9. 用户使用流程](#9-用户使用流程)
- [10. 与参考资料对比](#10-与参考资料对比)
- [11. 验收方法](#11-验收方法)

---

## 1. 背景与目标

BNOS AI 当前采用「核心管线」模式：`nodes/` 中的所有节点由 `pipeline.json` 声明，开发者手动编排拓扑。这适合系统组件管理，但对于第三方/用户新增的扩展能力（如 TTS 引擎、VLM 视觉、PC 操控等），不应该要求他们修改管线或改造核心节点。

**目标**：用户将一个节点文件夹放入 `plugins/`，BNOS AI 启动时自动发现、自动匹配到核心管线，无需用户手动配置。

---

## 2. 核心概念

### 2.1 两个角色

| 角色 | 目录 | 含义 | 来源 |
|------|------|------|------|
| `core` | `nodes/` | 核心节点，构成骨架管线 | BNOS 系统自带 |
| `plugin` | `plugins/` | 插件节点，可选挂件 | 用户/第三方添加 |

### 2.2 合约（Contract）

每个节点通过 `node_config.json` 中的 `contract` 字段声明自己能消费什么消息类型、产出什么消息类型。引擎据此自动匹配路由。

### 2.3 匹配规则

插件节点作为核心管线**已有消息类型的额外消费者**，不插入管线中间，不阻塞核心流程。

```
核心管线（不变）：
  aaa_cognition ──reply──→ live2d_face
       ↓
    tool_call ──→ llm_infer ──→ aaa_cognition

插件（自动匹配）：
  TTS 节点 ← 额外消费 reply ── 产出 audio
  VLM 节点 ← 额外消费 tool_call 中的截图请求
  logseq_writer ← 额外消费 knowledge（已存在）
```

---

## 3. 目录结构

```
BNOS_AI_project/
├── nodes/                          # 核心节点（role=core）
│   ├── node_python_aaa_cognition/
│   ├── node_python_llm_infer/
│   ├── node_js_live2d_face/
│   ├── node_python_asr_input/
│   ├── node_python_env_input/
│   ├── node_python_logseq_writer/
│   ├── node_rust_grok_hands/
│   └── shared/                     # 共享数据目录
│       ├── chatbot.db
│       ├── faiss.index
│       ├── gui_input.json
│       ├── gui_reply.json
│       └── ...
│
├── plugins/                        # 插件节点（role=plugin）
│   ├── node_python_tts/            # 例如：独立 TTS 引擎
│   ├── node_python_vlm/            # 例如：多模态视觉
│   └── ...
│
├── pipeline.json                   # 核心管线（不含插件）
├── pipeline_auto.json              # 自动生成的完整管线（含插件，BNOS AI 启动时生成）
├── bnos_runtime/
│   ├── engine.py
│   ├── pipeline_loader.py
│   └── plugins_discovery.py        # [新增] 插件发现与合约匹配
├── gui/
│   └── main.py                     # → 启动前调用 plugins_discovery
└── run.bat
```

---

## 4. node_config.json 新增字段

### 4.1 role 与 contract

```json
{
  "node_name": "node_python_tts",
  "role": "plugin",                    // "core" | "plugin"
  "entry": "listener.py",
  "language": "python",

  "contract": {
    "consumes": [
      {
        "data_type": "reply",
        "description": "AI 回复文本，用于语音合成"
      }
    ],
    "produces": [
      {
        "data_type": "audio",
        "description": "合成后的音频数据"
      }
    ]
  },

  "input_ports": [
    {
      "label": "回复文本",
      "name": "reply",
      "required": false,
      "source": "node",
      "type": "string"
    }
  ],
  "output_ports": [
    {
      "label": "音频输出",
      "name": "default",
      "output_file": "./output_audio.json",
      "type": "default"
    }
  ]
}
```

### 4.2 contract.consumes 规则

- `data_type` — 匹配核心管线中其他节点输出的 `filter` 键或消息中的 `data_type` 字段
- 一个插件可以消费多种消息类型（如 VLM 需要 `text` 和 `tool_call`）
- 允许多个插件消费同一种消息类型（如多个 TTS 引擎都消费 `reply`）

### 4.3 核心节点无需 contract

`role=core` 的节点不需要 `contract` 字段，它们由 `pipeline.json` 直接定义拓扑。`contract` 是插件系统需要的东西。

---

## 5. 合约发现与匹配算法

### 5.1 扫描阶段

`plugins_discovery.py` 启动时执行：

```
1. 扫描 plugins/ 目录下所有子文件夹
2. 对于每个文件夹，尝试读取 node_config.json
3. 校验 role 是否为 "plugin"，contract 是否合法
4. 合法 → 加入可用插件列表；不合法 → 跳过（不影响启动）
```

### 5.2 匹配阶段

分析核心管线所有节点的 `filter` 和 `input_ports`，提取整个管线中出现的 `data_type` 集合：

```
核心管线 data_type 集合（来自现有节点）：
  - text        (aaa_cognition filter.gui_input)
  - parsed      (aaa_cognition filter.llm_response)
  - prompt      (llm_infer filter.prompt)
  - reply       (live2d_face filter.reply)
  - knowledge   (logseq_writer filter.knowledge)
  - tool_call   (grok_hands filter.tool_call)
  - tool_result (aaa_cognition filter.tool_result)
```

对每个插件，检查它 `consumes` 中的 `data_type` 是否存在于该集合：

- **完全匹配** → 自动生成路由，插件启动
- **部分匹配** → 匹配的 data_type 生效，未匹配的跳过（日志警告，不阻塞启动）
- **完全不匹配** → 跳过插件（日志警告，不阻塞启动）

### 5.3 生成 pipeline_auto.json

匹配成功后，插件作为**独立的额外节点**加入管线，自动生成其 `port_mappings`：

```
plugin.contract.consumes.data_type = "reply"
  → 查找核心管线中有哪些节点输出 "reply"
  → aaa_cognition.output_ports 中有 port name = "reply"
  → aaa_cognition 的 output_file = "./output_reply.json"
  → 生成 port_mappings: { "reply": "../node_python_aaa_cognition/output_reply.json" }
```

生成的 `pipeline_auto.json` 包含核心管线 + 所有匹配成功的插件，引擎直接读取此文件。

---

## 6. BNOS AI 启动流程

```
run.bat
  └→ gui/main.py
        │
        ├─ 1. 清理旧文件
        │
        ├─ 2. plugins_discovery.py
        │      │
        │      ├─ 扫描 plugins/ 目录
        │      ├─ 读取每个插件的 contract
        │      ├─ 与核心管线 data_type 集合匹配
        │      ├─ 生成 pipeline_auto.json
        │      └─ 报告：已匹配 N 个插件，跳过 M 个
        │
        ├─ 3. 启动引擎（读取 pipeline_auto.json）
        │
        └─ 4. 启动 GUI
```

引擎和现有核心节点**完全无感知**——它们不知道有插件存在，只是正常的消息收发。

---

## 7. plugins_discovery.py 模块设计

```python
class PluginContract:
    consumes: list[dict]   # [{"data_type": "reply", ...}]
    produces: list[dict]   # [{"data_type": "audio", ...}]

class PluginDef:
    node_name: str
    node_dir: Path
    entry: str
    language: str
    contract: PluginContract
    parameters: list[dict]
    resource_limit: dict | None

class PluginDiscovery:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.plugins_dir = project_root / "plugins"
        self.pipeline_path = project_root / "pipeline.json"

    def scan_plugins(self) -> list[PluginDef]:
        """扫描 plugins/ 目录，返回所有合法的插件定义"""

    def extract_core_data_types(self) -> set[str]:
        """分析 pipeline.json 中所有核心节点的 filter/input_ports，返回 data_type 集合"""

    def match_plugins(self, plugins: list[PluginDef], core_types: set[str]) -> list[tuple[PluginDef, set[str]]]:
        """匹配每个插件的 consumes 与核心 data_type，返回 (插件, 匹配上的 data_type 集合)"""

    def generate_pipeline(self, matched: list[tuple[PluginDef, set[str]]]) -> dict:
        """生成 pipeline_auto.json（核心管线 + 匹配的插件）"""

    def run(self) -> dict:
        """一键执行：扫描 → 匹配 → 生成 → 返回报告"""
        plugins = self.scan_plugins()
        core_types = self.extract_core_data_types()
        matched = self.match_plugins(plugins, core_types)
        pipeline = self.generate_pipeline(matched)
        # 写 pipeline_auto.json
        with open(self.project_root / "pipeline_auto.json", "w") as f:
            json.dump(pipeline, f, indent=2, ensure_ascii=False)
        return {"total": len(plugins), "matched": len(matched), "skipped": len(plugins) - len(matched)}
```

---

## 8. 实现变更清单

### 8.1 新增文件

| 文件 | 行数估计 | 职责 |
|------|---------|------|
| `bnos_runtime/plugins_discovery.py` | ~200 行 | 插件扫描、合约匹配、pipeline 生成 |
| `plugins/`（目录） | — | 用户放插件节点的位置 |

### 8.2 修改文件

| 文件 | 改动量 | 改动内容 |
|------|-------|---------|
| `gui/main.py` | +15 行 | 在 `_start_engine()` 前调用 `PluginDiscovery.run()` |
| `run.bat` | 不改 | 无改动，启动流程不变 |

### 8.3 不改的文件

| 文件 | 理由 |
|------|------|
| `bnos_runtime/engine.py` | 引擎不感知插件，读 `pipeline_auto.json` 与读 `pipeline.json` 逻辑相同 |
| `bnos_runtime/pipeline_loader.py` | 不涉及插件概念 |
| `bnos_runtime/standalone_runner.py` | 节点启动逻辑不变 |
| 所有核心 `nodes/` 下的 `node_config.json` | 核心节点无需 `contract` |
| 所有核心 `nodes/` 下的业务代码 | 完全无感知 |

---

## 9. 用户使用流程

```
开发者：
  1. 在 BNOS（开发工具）中开发节点，role 设为 "plugin"
  2. 在 contract 中声明 consumes/produces 的 data_type
  3. 把节点文件夹压缩发布

用户：
  1. 下载插件 zip
  2. 解压到 BNOS_AI_project/plugins/ 下
  3. 启动 BNOS AI（run.bat）
  4. 控制台输出： "[Plugin] 发现 1 个新插件: node_python_tts（已自动接入）"
  5. 开始使用，无需任何配置

卸载：
  1. 删除 plugins/ 下对应文件夹
  2. 重启 BNOS AI → 插件消失，核心管线不受影响
```

---

## 10. 与参考资料对比

### Minecraft 模组系统
- Minecraft：`mods/` → ClassLoader 加载 → Mixin 注入游戏循环
- BNOS AI：`plugins/` → `plugins_discovery.py` 匹配 → 自动生成管线拓扑
- 相同点：丢进文件夹即生效，不影响核心
- 不同点：BNOS AI 是数据流驱动而非事件注入，插件不修改核心节点行为

### my-neuro (肥牛AI) 插件系统
- 肥牛：热加载插件 → plugin-manager.js 运行时注册
- BNOS AI：启动时静态扫描 → 生成管线文件
- BNOS AI 更简单的原因：节点是进程级，不支持也不需要在运行时热加载进程

### mewco (枫云AI)
- mewco：单体应用，所有模块在 main.py 中硬编码
- BNOS AI：模块是独立进程，通过契约自动集成
- BNOS AI 不需要任何代码修改即可扩展

---

## 11. 验收方法

### 11.1 验收环境与前置条件

| 项 | 要求 |
|------|------|
| 操作系统 | Windows 10/11（与 `run.bat` 启动脚本一致） |
| Python 版本 | 3.10+（与核心节点 venv 一致） |
| 项目根目录 | `BNOS_AI_project/`，含完整 `nodes/` 核心节点及 `pipeline.json` |
| 核心节点 | `node_python_aaa_cognition`、`node_python_llm_infer`、`node_js_live2d_face`、`node_python_asr_input`、`node_python_env_input`、`node_python_logseq_writer`、`node_rust_grok_hands` 均可正常启动 |
| 核心管线 data_type | `text`、`parsed`、`prompt`、`reply`、`knowledge`、`tool_call`、`tool_result` 在 `pipeline.json` 中均有声明 |
| 插件目录 | `plugins/` 目录存在且可读写；验收前可清空 |
| 待测模块 | `bnos_runtime/plugins_discovery.py` 已实现 `PluginDiscovery` 类及 `scan_plugins`/`extract_core_data_types`/`match_plugins`/`generate_pipeline`/`run` 方法 |
| 启动入口 | `gui/main.py` 在 `_start_engine()` 前已接入 `PluginDiscovery.run()` 调用 |
| 测试插件 | 至少准备 2 个合法插件样例：`node_python_tts`（consumes=`reply`，produces=`audio`）、`node_python_vlm`（consumes=`tool_call`） |
| 日志输出 | 控制台可查看插件发现/匹配/跳过日志 |
| 文本编辑器 | 用于校验 `pipeline_auto.json` 内容（如 VS Code） |

### 11.2 功能验收用例

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| F1 | 插件目录扫描发现插件 | 1. 在 `plugins/` 下放置合法的 `node_python_tts` 文件夹（含 `node_config.json`、`main.py`、`listener.py`）；2. 执行 `run.bat` 启动 BNOS AI | `plugins_discovery.py` 扫描到该文件夹，控制台输出含"发现 1 个新插件: node_python_tts（已自动接入）" | 扫描结果包含该插件，`run()` 返回 `total=1` | 核心 |
| F2 | role 字段识别 | 1. 在 `plugins/` 放置 `node_config.json` 中 `role="plugin"` 的节点；2. 另放置一个 `role="core"` 或缺失 `role` 字段的节点；3. 启动 BNOS AI | 仅 `role="plugin"` 的节点被加入插件列表；`role="core"` 或无 `role` 的节点不被当作插件处理 | 插件列表只含 `role="plugin"` 的节点 | 核心 |
| F3 | contract.consumes 字段校验与解析 | 1. 放置一个 `contract.consumes=[{"data_type":"reply","description":"AI 回复文本"}]` 的 TTS 插件；2. 启动 BNOS AI | `consumes` 被正确解析，`data_type="reply"` 提取成功，进入匹配阶段 | `PluginContract.consumes` 包含 `{"data_type":"reply"}`，无解析错误 | 核心 |
| F4 | 核心管线 data_type 集合提取 | 1. 调用 `PluginDiscovery.extract_core_data_types()`，读取 `pipeline.json` 中所有核心节点的 `filter` 与 `input_ports`；2. 打印返回集合 | 返回集合包含 `text`、`parsed`、`prompt`、`reply`、`knowledge`、`tool_call`、`tool_result` | 集合内容与核心节点声明的 `data_type` 完全一致 | 核心 |
| F5 | 合约完全匹配 | 1. 放置 TTS 插件（`consumes=[reply]`），核心管线存在 `reply` 类型；2. 启动 BNOS AI | 插件匹配成功，被加入 `pipeline_auto.json`，`match_plugins` 返回 `(插件, {reply})` | 插件出现在 `pipeline_auto.json`，匹配集合非空 | 核心 |
| F6 | pipeline_auto.json 生成 | 1. 完成 F5 匹配后查看项目根目录；2. 用文本编辑器打开 `pipeline_auto.json` 校验 | `pipeline_auto.json` 已生成，JSON 合法，包含核心管线全部节点 + 匹配成功的插件节点 | 文件存在、JSON 合法、含核心节点和插件节点 | 核心 |
| F7 | port_mappings 自动生成 | 1. 放置 TTS 插件 `consumes` 声明 `data_type="reply"`；2. 查找核心节点 `aaa_cognition` 的 `output_reply.json`；3. 检查 `pipeline_auto.json` 中该插件的 `port_mappings` | 自动生成 `port_mappings: {"reply": "../node_python_aaa_cognition/output_reply.json"}` | `port_mappings` 指向正确的上游 `output` 文件路径 | 核心 |
| F8 | 插件节点进程启动 | 1. 完成 F5-F7 后引擎读取 `pipeline_auto.json` 启动所有节点；2. 查看系统进程列表 | 插件 `listener.py` 作为独立进程启动，与核心节点并行运行 | 插件进程存在且未立即退出 | 核心 |
| F9 | 插件消费核心消息 | 1. 触发核心管线产生 `reply` 消息（如 `aaa_cognition` 输出回复）；2. 观察 TTS 插件 `main.py` 的输入 | TTS 插件 `main.py` 从 stdin 收到包含 `reply` 的 JSON 数据并触发处理逻辑 | 插件成功接收并处理 `reply` 消息 | 核心 |
| F10 | 引擎与核心节点无感知 | 1. 接入 TTS + VLM 两个插件后启动；2. 对比未接入插件时 `aaa_cognition`、`llm_infer`、`live2d_face` 等核心节点的输入输出 | 核心节点行为与无插件时完全一致，消息收发正常 | 核心节点输出、消息流不受插件影响 | 核心 |
| F11 | 合约部分匹配 | 1. 放置一个 `consumes=[{"data_type":"reply"},{"data_type":"unknown_type"}]` 的插件；2. 启动 BNOS AI | `reply` 匹配成功，`unknown_type` 被跳过，日志输出警告，不阻塞启动 | 插件仍针对 `reply` 接入，有警告日志，启动正常 | 非核心 |
| F12 | 合约完全不匹配 | 1. 放置一个 `consumes=[{"data_type":"nonexistent_type"}]` 的插件；2. 启动 BNOS AI | 插件被跳过，日志输出警告，不阻塞启动 | 插件未进入 `pipeline_auto.json`，核心正常启动 | 非核心 |
| F13 | 插件卸载 | 1. 删除 `plugins/node_python_tts` 文件夹；2. 重启 BNOS AI | 该插件从 `pipeline_auto.json` 消失，核心管线不受影响 | 重启后 `pipeline_auto.json` 不含该插件 | 非核心 |
| F14 | 启动报告输出 | 1. 接入 3 个插件（2 个匹配、1 个跳过）；2. 启动 BNOS AI，查看控制台输出 | 控制台输出"发现 2 个新插件，跳过 1 个"（或等价报告） | 报告 `matched`/`skipped` 数字与实际一致 | 非核心 |
| F15 | 插件 produces 产出 | 1. TTS 插件处理 `reply` 后产出 `audio`；2. 检查插件的 `output_audio.json` | `output_audio.json` 写入成功，内容含 `data_type="audio"` | 产出文件存在且符合 JSON 协议 | 非核心 |

### 11.3 边界与异常验收

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| E1 | plugins/ 目录为空 | 1. 清空 `plugins/` 目录下所有子文件夹；2. 启动 BNOS AI | 正常启动，`pipeline_auto.json` 仅含核心管线，无报错 | 启动无异常，核心管线完整 | 核心 |
| E2 | plugins/ 目录不存在 | 1. 删除整个 `plugins/` 目录；2. 启动 BNOS AI | 自动创建或正常跳过，不影响启动流程 | 启动成功，无崩溃 | 核心 |
| E3 | node_config.json 缺失 | 1. 在 `plugins/` 下放置一个不含 `node_config.json` 的空文件夹 `bad_plugin/`；2. 启动 BNOS AI | 跳过该文件夹，不影响其他插件和启动 | 该文件夹被跳过，有日志记录，其他插件正常 | 核心 |
| E4 | node_config.json 格式错误 | 1. 在 `plugins/` 下放置一个 `node_config.json` 内容为非法 JSON（如 `{role: plugin,`）的文件夹；2. 启动 BNOS AI | 跳过该插件，记录警告日志，不阻塞启动 | 跳过且不崩溃，核心管线正常 | 核心 |
| E5 | contract 字段缺失 | 1. 放置一个 `role="plugin"` 但无 `contract` 字段的节点；2. 启动 BNOS AI | 跳过该插件并输出警告 | 插件被跳过，有警告日志 | 非核心 |
| E6 | 插件依赖缺失/启动失败 | 1. 放置一个 `main.py` 中 `import` 未安装第三方库的插件；2. 启动 BNOS AI | 插件进程启动失败，但核心管线和其他插件不受影响 | 核心管线正常运行，仅该插件失败 | 非核心 |
| E7 | 多插件消费同一 data_type | 1. 在 `plugins/` 放置两个均 `consumes=[reply]` 的 TTS 插件（如 `node_python_tts_a`、`node_python_tts_b`）；2. 启动 BNOS AI | 两个插件都接入，都消费 `reply` 消息 | 两个插件均出现在 `pipeline_auto.json` 中 | 非核心 |
| E8 | 大量插件扫描性能 | 1. 在 `plugins/` 下放置 50 个合法插件文件夹；2. 启动 BNOS AI，记录从启动到 GUI 出现的耗时 | 扫描 + 匹配 + 生成管线在合理时间内完成 | 启动耗时增量 < 5 秒 | 非核心 |

### 11.4 验收结论判定标准

| 验收等级 | 判定标准 |
|------|---------|
| **通过** | 所有"核心"项全部通过 |
| **附条件通过** | 核心项全通过，非核心项 ≤2-3 项不通过且有补救计划 |
| **不通过** | 任一核心项不通过 |

#### 验收记录模板

```
============================================================
           BNOS AI 插件系统 验收记录表
============================================================

功能名称：BNOS AI 插件系统（plugins 自动发现与合约匹配）
验收日期：______年____月____日
验收人员：________________  /  __________________
版本号：  v______
环境说明：Windows ____ / Python ____ / 项目路径 ____________

------------------------------------------------------------
一、功能验收用例（11.2）
------------------------------------------------------------
[ ] F1  插件目录扫描发现插件              [通过 / 不通过 / N/A]
[ ] F2  role 字段识别                      [通过 / 不通过 / N/A]
[ ] F3  contract.consumes 字段校验与解析    [通过 / 不通过 / N/A]
[ ] F4  核心管线 data_type 集合提取        [通过 / 不通过 / N/A]
[ ] F5  合约完全匹配                       [通过 / 不通过 / N/A]
[ ] F6  pipeline_auto.json 生成            [通过 / 不通过 / N/A]
[ ] F7  port_mappings 自动生成             [通过 / 不通过 / N/A]
[ ] F8  插件节点进程启动                   [通过 / 不通过 / N/A]
[ ] F9  插件消费核心消息                   [通过 / 不通过 / N/A]
[ ] F10 引擎与核心节点无感知               [通过 / 不通过 / N/A]
[ ] F11 合约部分匹配                       [通过 / 不通过 / N/A]
[ ] F12 合约完全不匹配                     [通过 / 不通过 / N/A]
[ ] F13 插件卸载                           [通过 / 不通过 / N/A]
[ ] F14 启动报告输出                       [通过 / 不通过 / N/A]
[ ] F15 插件 produces 产出                 [通过 / 不通过 / N/A]

------------------------------------------------------------
二、边界与异常验收（11.3）
------------------------------------------------------------
[ ] E1  plugins/ 目录为空                  [通过 / 不通过 / N/A]
[ ] E2  plugins/ 目录不存在                [通过 / 不通过 / N/A]
[ ] E3  node_config.json 缺失              [通过 / 不通过 / N/A]
[ ] E4  node_config.json 格式错误          [通过 / 不通过 / N/A]
[ ] E5  contract 字段缺失                  [通过 / 不通过 / N/A]
[ ] E6  插件依赖缺失/启动失败              [通过 / 不通过 / N/A]
[ ] E7  多插件消费同一 data_type           [通过 / 不通过 / N/A]
[ ] E8  大量插件扫描性能                   [通过 / 不通过 / N/A]

------------------------------------------------------------
三、不通过项说明（如有）
------------------------------------------------------------
编号：______
现象：______________________________________________________
复现步骤：__________________________________________________
影响范围：__________________________________________________
补救计划：__________________________________________________

------------------------------------------------------------
四、验收结论
------------------------------------------------------------
[ ] 通过        （所有核心项全部通过）
[ ] 附条件通过  （核心项全通过，非核心项 ≤3 项不通过且有补救计划）
[ ] 不通过      （任一核心项不通过）

验收人签字：________________     日期：______年____月____日
复核人签字：________________     日期：______年____月____日
============================================================
```
