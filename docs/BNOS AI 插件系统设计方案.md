# BNOS AI 插件系统设计方案

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
