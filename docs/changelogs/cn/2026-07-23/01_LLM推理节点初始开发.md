# 01 — LLM 推理节点初始开发

> 日期：2026-07-23 | 涉及文件：9 | 变更类型：新建

---

## 一、问题描述

原 BNOS 系统中，LLM 推理能力内嵌在 AAA 认知节点的 `main.py` 中，仅支持单一 `qwen_api` 后端。这导致：

1. 推理逻辑与业务逻辑耦合，无法单独调试 LLM 输出
2. 切换供应商（本地/云端）需要修改 AAA 代码
3. API Key 散落在配置中，无法统一管理
4. 其他节点（如 Live2D）无法直接复用推理能力

## 二、目标

将 LLM 推理独立为 `node_python_llm_infer` 节点，遵循 BNOS 节点开发规范，做到：

- 独立进程 + 独立 venv，崩溃不影响其他节点
- 不依赖任何 BNOS 模块（纯 stdin/stdout 通信）
- 支持多后端（本地 llama.cpp / 云端 API），配置切换
- 使用多端口 + 类型过滤代替 if-else 数据分发
- 模块拆分：`main.py` 仅做路由，`config.py` 加载配置，`backends.py` 封装业务

## 三、修改方案

### 3.1 目录结构

```
node_python_llm_infer/
├── node_config.json     # 核心配置（9 参数 + 2 输入端口 + 2 输出端口）
├── main.py              # 路由入口（55 行业务代码 + 框架桥接）
├── config.py            # 配置加载（惰性加载 node_config.json）
├── backends.py          # 三后端实现 + 工厂 + 供应商默认值
├── listener.py          # 轮询守护进程 + 本地服务生命周期管理
├── start.bat            # Windows 启动脚本
├── start.sh             # Linux/macOS 启动脚本
├── requirements.txt     # 依赖：仅 requests
└── setup_local_llm.py   # 本地 llama.cpp 二进制下载脚本
```

### 3.2 架构拆分

参照 AAA 认知节点的模块化模式，将原单体 `main.py` 拆分为三个文件：

**config.py** — 惰性加载 + 参数提取：

```python
NODE_DIR = os.path.dirname(os.path.abspath(__file__))
_config = None

def load_config():
    global _config
    if _config is not None:
        return _config
    path = os.path.join(NODE_DIR, "node_config.json")
    _config = json.load(open(path, "r", encoding="utf-8")) if os.path.exists(path) else {}
    return _config

def extract_params(config=None):
    if config is None:
        config = load_config()
    return {p["name"]: p.get("default") for p in config.get("parameters", [])}

def resolve(p):
    return os.path.normpath(os.path.join(NODE_DIR, p)) if not os.path.isabs(p) else p
```

**backends.py** — 三个后端 + 工厂 + 供应商配置 + 工具函数：

- `find_cli_path(basename)` — 跨平台 exe 查找
- `CLOUD_VENDOR_DEFAULTS` — 5 供应商默认值
- `LlamaServerBackend` — llama-server HTTP 后端（模型常驻，低延迟）
- `LlamaCliBackend` — llama-cli CLI 后端（零配置，每次加载模型）
- `CloudApiBackend` — 云端多供应商（OpenAI/Anthropic/Google/DeepSeek/custom）
- `create_backend()` — 工厂函数

**main.py** — 瘦身路由：

```python
class MyNode:
    def __init__(self):
        self._backend = None
        self._cfg = None

    def process(self, data):
        cmd = data.get("cmd")
        if cmd == "init_check":
            return self._handle_init_check()
        # 懒初始化后端
        if self._backend is None:
            self._cfg = load_config()
            params = extract_params(self._cfg)
            self._backend = create_backend(params.get("model_type"), params)
        # 提取 prompt → 推理 → 返回
        prompt_text = (data.get("content") or data.get("data") or data.get("prompt") or "").strip()
        if not prompt_text:
            return {"_port": "default", "data_type": "text", "content": "", "error": "empty prompt"}
        result_text = self._backend.infer(...)
        return {"_port": "default", "data_type": "text", "content": result_text}
```

### 3.3 node_config.json 规范

使用 BNOS 开发规范规定的 11 种控件类型，每个 `input_port` 明确标注 `source` 字段：

| 参数 | type | 说明 |
|------|------|------|
| `model_type` | enum | `http_server` / `cli_local` / `cloud` |
| `model_path` | file | GGUF 模型路径 |
| `llama_port` | int | 本地服务端口 |
| `cloud_vendor` | enum | `openai` / `anthropic` / `google` / `deepseek` / `custom_openai` |
| `api_base` | string | API Base URL |
| `api_key` | password | API Key |
| `cloud_model` | string | 云端模型名 |
| `max_tokens` | int | 最大生成 Token |
| `temperature` | float | 温度 |

### 3.4 复合节点 / EXE 兼容

- 所有路径以 `__file__` 为基准，不依赖 `os.getcwd()`
- 模块级无 I/O 副作用，配置使用惰性加载
- `process(data)` 为顶层纯函数，可直接 `import` 调用
- 无模块级可变全局状态

## 四、验证方法

1. `python -c "from main import MyNode, process"` — 模块导入零副作用
2. `python -c "from backends import create_backend, CloudApiBackend"` — 后端模块可独立使用
3. `echo '{"content":"hello"}' | python main.py` — stdout 输出合法 JSON
4. 测试 `init_check`：`echo '{"cmd":"init_check"}' | python main.py` → `type=status`

## 五、修改文件清单

| 文件 | 改动 |
|------|------|
| `nodes/node_python_llm_infer/node_config.json` | 新建：9 参数 + 2 输入端口 + 2 输出端口 |
| `nodes/node_python_llm_infer/main.py` | 新建：路由层 + 框架桥接 + `__main__` |
| `nodes/node_python_llm_infer/config.py` | 新建：配置惰性加载 |
| `nodes/node_python_llm_infer/backends.py` | 新建：三后端 + 工厂 |
| `nodes/node_python_llm_infer/listener.py` | 新建：轮询守护进程 |
| `nodes/node_python_llm_infer/start.bat` | 新建：Windows 启动脚本 |
| `nodes/node_python_llm_infer/start.sh` | 新建：Linux/macOS 启动脚本 |
| `nodes/node_python_llm_infer/requirements.txt` | 新建：仅 requests |

---

**最后更新**：2026-07-23
