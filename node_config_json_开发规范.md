﻿﻿﻿﻿﻿﻿# node_config.json 多输入面板组件开发规范

## 概述

`node_config.json` 是每个节点的核心配置文件，位于 `nodes/<node_name>/` 目录下。它定义了节点的参数控件、输入/输出端口，直接驱动画布上的面板模式渲染和锚点生成。

### 执行流程

```
node_config.json  (你在写)
    │
    ▼
NodeConfigParser        → 解析 parameters / input_ports / output_ports
    │
    ├──▶ WidgetRegistry  → 按 param.type 创建对应 Qt 控件
    │
    └──▶ AnchorManager   → 按 input_port.source 决定是否生成画布锚点
              │
              └── DetailedNodeStyle  → 整体布局 + 渲染
```

### 涉及的核心文件

| 文件 | 职责 |
|------|------|
| `ui/core/node_config_parser.py` | `ParameterDef` / `InputPortDef` / `OutputPortDef` 数据类 + 解析方法 |
| `ui/canvas/parameter_widgets/` | `WidgetRegistry` 注册表，11 种控件类型 |
| `ui/canvas/items/anchor_manager.py` | `PortSource` 枚举，控制锚点生成逻辑 |
| `ui/canvas/items/styles/detailed.py` | `DetailedNodeStyle`，面板模式的视觉渲染 |

---

## 一、顶层字段

```jsonc
{
  "node_name": "my_node",       // 必须与目录名一致
  "listen_upper_file": "",      // 上游监听文件（运行时自动填充）
  "output_file": "./output.json",
  "output_type": "",
  "filter": {},
  "out_connections": {},
  "port_mappings": {},

  "parameters":    [],   // ★ 参数控件
  "input_ports":   [],   // ★ 输入端口
  "output_ports":  []    // ★ 输出端口
}
```

---

## 二、input_ports — 输入端口

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | `string` | **是** | 端口唯一标识，对应上游节点的 `output_ports[*].name` |
| `label` | `string` | 否 | 面板中显示的标签文字 |
| `type` | `string` | 否 | 数据类型（`string` / `int` / `float` / `any`），默认 `"default"` |
| `required` | `bool` | 否 | 是否必须有上游连线，默认 `false` |
| `description` | `string` | 否 | 提示文字（暂未渲染到 UI） |
| **`source`** | `string` | 否 | **关键字段**，控制端口渲染方式，见下方详解 |
| `filter` | `dict` | 否 | **v2.1+** 端口级过滤规则，仅对 `source="node"` 有效。格式同顶层 `filter`，`{}` 或缺失表示不过滤 |

### source 字段详解

```python
# anchor_manager.py  PortSource 枚举
NODE  = "node"    # 需要上游连线 → 画布生成 10px 小锚点
EDIT  = "edit"    # 用户手动输入 → 面板内控件（无锚点）
PARAM = "param"   # 可选参数含默认值 → 面板内控件（无锚点）
FILE  = "file"    # 外部文件引用 → 面板内控件（无锚点）
```

**只有 `source == "node"` 才会生成可连线的画布锚点**，其余三种均渲染为面板内参数控件。

### source 选用决策树

```
这个端口的数据从哪来？
  ├── 必须从上游节点连线 → source: "node"
  │     ✓ LLM 的 prompt、图片生成器的 image_input
  │
  ├── 用户在面板里输入 → source: "edit"
  │     ✓ 模型名称下拉框、路径输入框
  │
  ├── 有默认值、用户可按需修改 → source: "param"
  │     ✓ temperature=0.7、max_tokens=4096
  │
  └── 外部文件路径 → source: "file"
        ✓ 波形文件、模型权重路径
```

### 完整示例

```jsonc
"input_ports": [
  {
    "name": "prompt",
    "label": "提示词",
    "type": "string",
    "required": true,
    "source": "node"            // ← 需要连线，生成小锚点
  },
  {
    "name": "context",
    "label": "上下文",
    "type": "string",
    "required": false,
    "source": "node"            // ← 可选连线，生成小锚点
  },
  {
    "name": "model_name",
    "label": "模型名称",
    "type": "string",
    "required": false,
    "source": "edit"            // ← 无锚点，面板内下拉框
  },
  {
    "name": "temperature",
    "label": "温度",
    "type": "float",
    "required": false,
    "source": "param"           // ← 无锚点，面板内滑块（有默认值）
  }
]
```

> **注意**：目前锚点管理器会**始终生成一个 default 主输入锚点（16px）**，输出的锚点也是单个 default。`input_ports` 中 `source=node` 的端口会被渲染为**10px 小锚点**，供节点内部分线连接。

---

## 三、output_ports — 输出端口

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | `string` | **是** | 端口唯一标识，供下游节点的 `input_ports[*].name` 引用 |
| `label` | `string` | 否 | 面板中显示的标签文字 |
| `type` | `string` | 否 | 数据类型，默认 `"default"` |
| `description` | `string` | 否 | 提示文字 |

### 示例

```jsonc
"output_ports": [
  { "name": "response",    "label": "响应文本",   "type": "string" },
  { "name": "tokens_used", "label": "Token 用量", "type": "int" }
]
```

> **当前实现**：画布右侧生成一个 default 输出锚点（16px），多输出端口独立锚点的功能尚未完全实现。`output_ports` 主要用于元数据声明。

---

## 四、parameters — 参数控件

### 通用字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | `string` | **是** | 参数唯一标识 |
| `type` | `string` | **是** | 控件类型，必须为 WidgetRegistry 支持的 11 种之一 |
| `label` | `string` | **是** | 面板中显示的标签 |
| `default` | `any` | 否 | 默认值 |
| `required` | `bool` | 否 | 是否必填，默认 `false` |

### 控件类型全览

WidgetRegistry 支持 11 种控件类型，每种有各自的专属字段：

---

#### `string` — 单行文本

```jsonc
{ "name": "api_key", "type": "string", "label": "API Key", "default": "" }
```

无额外专属字段。

---

#### `text` — 多行文本

```jsonc
{ "name": "system_prompt", "type": "text", "label": "系统提示词",
  "default": "你是一个智能助手", "rows": 3 }
```

| 专属字段 | 类型 | 说明 |
|----------|------|------|
| `rows` | `int` | 文本框行数，默认 1 |

---

#### `password` — 密码输入

```jsonc
{ "name": "secret_token", "type": "password", "label": "密钥", "default": "" }
```

输入内容以 `●` 遮蔽。无额外专属字段。

---

#### `int` — 整数

```jsonc
{ "name": "max_tokens", "type": "int", "label": "最大 Token 数",
  "default": 4096, "min": 1, "max": 128000, "step": 1 }
```

| 专属字段 | 类型 | 说明 |
|----------|------|------|
| `min` | `float` | 最小值 |
| `max` | `float` | 最大值 |
| `step` | `float` | 步长 |

---

#### `float` — 浮点数

```jsonc
{ "name": "temperature", "type": "float", "label": "温度",
  "default": 0.7, "min": 0.0, "max": 2.0, "step": 0.1, "decimals": 2 }
```

| 专属字段 | 类型 | 说明 |
|----------|------|------|
| `min` | `float` | 最小值 |
| `max` | `float` | 最大值 |
| `step` | `float` | 步长 |
| `decimals` | `int` | 小数位数，默认 2 |

---

#### `bool` — 复选框

```jsonc
{ "name": "stream_mode", "type": "bool", "label": "流式输出", "default": true }
```

`default` 必须是 `true` 或 `false`。无额外专属字段。

---

#### `enum` — 下拉框（静态选项）

```jsonc
{ "name": "model_name", "type": "enum", "label": "模型",
  "default": "gpt-4o",
  "options": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "claude-3.5-sonnet", "gemini-2.0-flash"] }
```

| 专属字段 | 类型 | 说明 |
|----------|------|------|
| `options` | `list[str]` | 下拉选项列表 |

---

#### `enum` — 下拉框（动态选项，v1.1）

```jsonc
{ "name": "node_list", "type": "enum", "label": "目标节点",
  "dynamic_options": { "source": "running_nodes", "filter": { "language": "python" } } }
```

| 专属字段 | 类型 | 说明 |
|----------|------|------|
| `dynamic_options` | `object` | 动态选项配置（`source` / `filter` 子字段） |

> 如果同时指定 `options` 和 `dynamic_options`，`dynamic_options` 优先。

---

#### `file` — 文件选择器

```jsonc
{ "name": "api_key_file", "type": "file", "label": "密钥文件",
  "default": "", "file_filter": "文本文件 (*.txt *.key)" }
```

| 专属字段 | 类型 | 说明 |
|----------|------|------|
| `file_filter` | `string` | 文件类型过滤器，格式为 `"描述 (*.ext1 *.ext2)"` |

---

#### `directory` — 目录选择器

```jsonc
{ "name": "output_dir", "type": "directory", "label": "输出目录", "default": "./output" }
```

无额外专属字段。

---

#### `color` — 颜色选择器

```jsonc
{ "name": "accent_color", "type": "color", "label": "强调色", "default": "#49cc90" }
```

`default` 应为十六进制颜色值（`#RRGGBB` 或 `#AARRGGBB`）。

---

#### `range` — 滑块

```jsonc
{ "name": "retry_count", "type": "range", "label": "重试次数",
  "default": 3, "min": 0, "max": 10, "step": 1 }
```

| 专属字段 | 类型 | 说明 |
|----------|------|------|
| `min` | `float` | 最小值 |
| `max` | `float` | 最大值 |
| `step` | `float` | 步长 |

---

## 五、完整参考示例

以下是一个模拟 LLM 调用节点的完整 `node_config.json`：

```jsonc
{
  "node_name": "python_node_1",
  "listen_upper_file": "",
  "output_file": "./output.json",
  "output_type": "",
  "filter": {},
  "out_connections": {},
  "port_mappings": {},

  "input_ports": [
    { "name": "prompt",      "label": "提示词",   "type": "string", "required": true,  "source": "node",
      "filter": { "type": "chat", "priority": "high" } },
    { "name": "context",     "label": "上下文",   "type": "string", "required": false, "source": "node" },
    { "name": "model_name",  "label": "模型名称", "type": "string", "required": true,  "source": "edit" },
    { "name": "temperature", "label": "温度",     "type": "float",  "required": false, "source": "param" }
  ],

  "output_ports": [
    { "name": "response",    "label": "响应文本",   "type": "string" },
    { "name": "tokens_used", "label": "Token 用量", "type": "int" }
  ],

  "parameters": [
    { "name": "model_name",    "type": "enum",      "label": "模型名称",
      "default": "gpt-4o",
      "options": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "claude-3.5-sonnet", "gemini-2.0-flash"]
    },
    { "name": "temperature",   "type": "float",     "label": "温度",
      "default": 0.7, "min": 0.0, "max": 2.0, "step": 0.1
    },
    { "name": "max_tokens",    "type": "int",       "label": "最大 Token 数",
      "default": 4096, "min": 1, "max": 128000, "step": 1
    },
    { "name": "system_prompt", "type": "text",      "label": "系统提示词",
      "default": "你是一个智能助手", "rows": 3
    },
    { "name": "stream_mode",   "type": "bool",      "label": "流式输出",
      "default": true
    },
    { "name": "api_key_file",  "type": "file",      "label": "API Key 文件",
      "default": "", "file_filter": "文本文件 (*.txt *.key)"
    },
    { "name": "output_dir",    "type": "directory", "label": "输出目录",
      "default": "./output"
    },
    { "name": "log_level",     "type": "enum",      "label": "日志级别",
      "default": "info",
      "options": ["debug", "info", "warning", "error"]
    },
    { "name": "retry_count",   "type": "range",     "label": "重试次数",
      "default": 3, "min": 0, "max": 10, "step": 1
    }
  ]
}
```

**在此示例中，面板模式将产生**：

```
┌────────────────────────────────────────┐
│ 🟢 python_node_1           [×] [-] [▢] │  ← 顶栏（Python 绿色）
├────────────────────────────────────────┤
│  [锚点]                                │  ← 左侧主输入锚点 (16px)
│  ● prompt             [可连线小锚点]    │  ← source=node → 10px 小锚点
│  ● context            [可连线小锚点]    │  ← source=node
│────────────────────────────────────────│
│  模型名称            [gpt-4o      ▾]   │  ← enum 下拉框
│  温度                [  0.7  -   +  ] │  ← float 数值
│  最大 Token 数        [4096  -   +  ] │  ← int 数值
│  系统提示词                             │
│  ┌──────────────────────────────────┐  │
│  │ 你是一个智能助手                    │  │  ← text 多行 (3 rows)
│  └──────────────────────────────────┘  │
│  流式输出            [ ☑ ]             │  ← bool 复选框
│  API Key 文件        [____] [浏览...]  │  ← file 选择器
│  输出目录             [./output] [浏览]  │  ← directory 选择器
│  日志级别            [info       ▾]   │  ← enum 下拉框
│  重试次数             [===●=======]   │  ← range 滑块 (0~10)
│────────────────────────────────────────│
│                                [锚点] │  ← 右侧输出锚点 (16px)
└────────────────────────────────────────┘
```

---

## 六、常见错误

### 1. `node_name` 与目录名不一致

```jsonc
// ❌ 目录名是 my_node，但 config 写了 other_name
{ "node_name": "other_name" }
```

**现象**：面板模式下 `_get_node_config()` 通过 `nodes_data["my_node"]` 查找 → 找不到 → 参数/端口为空。

**修复**：`node_name` **必须**与 `nodes/<目录名>/` 一致。

---

### 2. 参数 `type` 不在 WidgetRegistry 中

```jsonc
// ❌ "number" 不是有效的 type
{ "name": "count", "type": "number" }
```

**现象**：`WidgetRegistry.get("number")` 返回 `StringWidget`（fallback），参数显示为文本输入框而非数值控件。

**修复**：整数用 `"int"`，浮点数用 `"float"`。

---

### 3. `name` 未在 parameters 中定义但在 input_ports 中用 source=edit/param

```jsonc
// ❌ temperature 在 input_ports 中声明了，但 parameters 中没有
"input_ports": [
  { "name": "temperature", "source": "param" }
]
"parameters": []  // ← 空列表
```

**现象**：端口被解析为无锚点的参数端口，但面板中没有对应控件。

**修复**：`source=edit/param/file` 的端口必须在 `parameters` 中有同名条目。

---

### 4. `source` 漏写

```jsonc
// ❌ 没有 source → 默认为 None → 不生成锚点
{ "name": "prompt", "type": "string" }
```

**现象**：面板中看不到画布锚点，无法连线。

**修复**：需要连线的端口显式设置 `"source": "node"`。

---

### 5. `default` 类型不匹配

```jsonc
// ❌ bool 类型的 default 是字符串
{ "name": "enable", "type": "bool", "default": "true" }
```

**修复**：`bool` 的 `default` 必须是 JSON 布尔值 `true` / `false`（不带引号）。

---

### 6. `options` 漏写

```jsonc
// ❌ enum 没有 options → 下拉框为空
{ "name": "model", "type": "enum", "default": "gpt-4o" }
```

**修复**：`type=enum` 必须提供 `options` 数组或 `dynamic_options` 配置。

---

## 七、开发检查清单

新建节点 `node_config.json` 时请逐项确认：

- [ ] `node_name` 与目录名一致
- [ ] 顶层字段包含 `parameters` / `input_ports` / `output_ports`（至少空数组 `[]`）
- [ ] 每个 `input_port` 的 `source` 已明确指定（`node` / `edit` / `param` / `file`）
- [ ] `source=node` 的端口数量合理（锚点过多会挤占面板空间）
- [ ] `source=edit/param/file` 的端口在 `parameters` 中有对应条目
- [ ] 每个 `parameter` 的 `type` 是 WidgetRegistry 支持的 11 种之一
- [ ] `type=enum` 时提供了 `options` 或 `dynamic_options`
- [ ] `type=file` 时提供了 `file_filter`
- [ ] `type=int/float/range` 时 `min` / `max` 范围合理
- [ ] `default` 的类型与 `type` 匹配
- [ ] JSON 语法正确（无尾逗号、无注释、引号闭合）
- [ ] `resource_limit` 配置合理（如需限制资源占用）

---

## 八、resource_limit — 节点资源限制

`resource_limit` 是 node_config.json 的**可选**顶层字段，用于限制节点进程的 CPU 和内存占用。
底层实现根据操作系统自动选择：
- **Linux**：cgroups v2（CPU 硬限制 + 内存硬限制）
- **Windows**：Job Objects（CPU 硬限制 + 内存硬限制）
- **macOS**：仅进程优先级（系统 API 不支持硬限制）

### 字段说明

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|:---:|--------|------|
| `priority` | `string` | 否 | `"normal"` | 进程优先级 |
| `cpu_affinity` | `list[int]` | 否 | 全部核心 | CPU 核心绑定（macOS 忽略） |
| `cpu_percent` | `int` | 否 | 无限制 | CPU 使用率上限，100 = 1 核（macOS 忽略） |
| `memory_mb` | `int` | 否 | 无限制 | 内存硬上限，单位 MB（macOS 忽略） |

### priority 可选值

| 值 | Linux nice | Windows Priority Class | 说明 |
|----|------------|----------------------|------|
| `"low"` | 19 | IDLE_PRIORITY_CLASS | 最低优先级，后台任务 |
| `"below_normal"` | 10 | BELOW_NORMAL_PRIORITY_CLASS | 低于正常 |
| `"normal"` | 0 | NORMAL_PRIORITY_CLASS | 默认值 |
| `"above_normal"` | -5 | ABOVE_NORMAL_PRIORITY_CLASS | 高于正常 |
| `"high"` | -10 | HIGH_PRIORITY_CLASS | 高优先级，谨慎使用 |

### cpu_affinity

绑定进程到指定 CPU 核心。核心编号从 0 开始。

```jsonc
"cpu_affinity": [0, 1]   // 仅使用核心 0 和 1
```

> **macOS 不支持** `cpu_affinity`，配置后静默忽略。

### cpu_percent

`100` = 1 个完整核心。例如 `8` 核机器上配置 `200` 表示最多用 2 核。

```jsonc
"cpu_percent": 200       // 最多 2 核
"cpu_percent": 50        // 最多半核
```

> **macOS 不支持** `cpu_percent`，配置后静默忽略。

### memory_mb

内存硬上限。进程尝试分配超过限制的内存时，`malloc` / `mmap` 将失败（返回 NULL），可能导致进程崩溃或被 OOM 终止。

```jsonc
"memory_mb": 4096        // 最多 4GB
"memory_mb": 512         // 最多 512MB
```

> **macOS 不支持** `memory_mb`，配置后静默忽略。

### 完整示例

```jsonc
{
  "node_name": "stable_diffusion",
  "listen_upper_file": "",
  "output_file": "./output.json",

  "parameters": [
    { "name": "prompt", "type": "text", "label": "提示词", "default": "", "rows": 3 },
    { "name": "steps",   "type": "int",  "label": "推理步数", "default": 30, "min": 1, "max": 150 }
  ],

  "resource_limit": {
    "memory_mb": 4096,
    "cpu_percent": 200,
    "cpu_affinity": [0, 1],
    "priority": "below_normal"
  }
}
```

### 不同场景的推荐配置

| 场景 | priority | cpu_percent | memory_mb |
|------|----------|-------------|-----------|
| **轻量数据处理**（JSON 转换、文本清洗） | `"low"` | — | 256 |
| **API 调用代理**（HTTP 请求、消息队列） | `"normal"` | — | 512 |
| **LLM 推理节点**（Ollama、vLLM） | `"normal"` | — | 4096 |
| **图像/视频处理**（SD、FFmpeg） | `"below_normal"` | 200 | 4096 |
| **科学计算/训练** | `"below_normal"` | — | 8192 |
| **实时信号处理** | `"high"` | — | — |
| **文件监控/日志收集** | `"low"` | — | 128 |

### 运行时效果

当 `node_config.json` 包含 `resource_limit` 字段时，BNOS 节点启动流程自动调用：

```python
from ui.core.system.resource_limit import create_resource_limit

limit = create_resource_limit(process.pid, config["resource_limit"])
applied = limit.apply()
# applied 示例: ["priority=below_normal", "memory_mb=4096", "cpu_percent=200"]
```

如果当前平台不支持某项限制（如 macOS），该配置静默忽略，不影响节点正常启动。

### 注意事项

1. **内存限制过小会导致进程崩溃**——确保 `memory_mb` 至少大于节点的峰值内存占用
2. **CPU 限制仅在进程在用户态运行时生效**——内核态操作（I/O 等待）不计入 CPU 配额
3. **Windows 上需要管理员权限**才能对已有进程设置 Job Object 限制；无权限时限制静默失败
4. **Linux 上需要 root 或 cgroup 委派权限**才能写 `/sys/fs/cgroup/`；无权限时限制静默失败
5. **子进程会继承限制**——节点启动的 `main.py` 子进程自动纳入同一限制范围
