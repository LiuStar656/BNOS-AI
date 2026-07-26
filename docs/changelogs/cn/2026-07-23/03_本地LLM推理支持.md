# 03 — 本地 LLM 推理支持

> 日期：2026-07-23 | 涉及文件：4 | 变更类型：新增

---

## 一、问题描述

之前 LLM 推理仅支持云端 API 模式，无法在离线或无网络环境下运行。项目需求支持本地部署的 llama.cpp 推理，且需要两种使用模式：

1. **HTTP Server 模式**：模型常驻，低延迟，适合日常对话
2. **CLI 模式**：每次调用加载模型，零配置，适合低频使用

此外，本地部署流程应尽量简化——用户下载 llama.cpp 二进制和 GGUF 模型后即可运行，无需手动编译。

## 二、目标

- 实现 `LlamaServerBackend`（HTTP Server 模式）
- 实现 `LlamaCliBackend`（CLI 模式）
- 提供 `setup_local_llm.py` 一键下载脚本
- 本地服务生命周期自动管理（listener 管理 server 进程）

## 三、修改方案

### 3.1 LlamaServerBackend

llama-server.exe 作为子进程由节点启动和管理：

```python
class LlamaServerBackend:
    def __init__(self, config):
        self.model_path = config.get("model_path")
        self.port = int(config.get("llama_port", 8080))
        self.host = "127.0.0.1"
        self.server_process = None

    def start(self) -> bool:
        # 幂等设计：/health 已响应 200 ? 直接返回 True
        if self.health():
            return True
        if not self.model_path or not os.path.isfile(self.model_path):
            return False
        # 启动 llama-server 子进程，等待 60s 就绪
        self.server_process = subprocess.Popen([...])
        for _ in range(60):
            if self.health():
                return True
            time.sleep(1)
        return False

    def infer(self, prompt, max_tokens, temperature):
        # 通过 OpenAI 兼容 API 调用
        resp = requests.post(f"{self.api_base}/chat/completions", json={...})
        return resp.json()["choices"][0]["message"]["content"]

    def stop(self):
        if self.server_process:
            self.server_process.terminate()
            self.server_process = None
```

**幂等启动**：即使 `main.py` 被 listener 多次 subprocess 调用，server 只需启动一次。

### 3.2 LlamaCliBackend

每次调用启动 `llama-cli.exe`，通过临时文件传递 prompt（避免命令行长度限制）：

```python
class LlamaCliBackend:
    def infer(self, prompt, max_tokens, temperature):
        fd, prompt_file = tempfile.mkstemp(suffix=".txt", text=True)
        os.write(fd, prompt.encode("utf-8"))
        os.close(fd)
        result = subprocess.run([self._cli_path, "-m", self.model_path, "-f", prompt_file, ...], capture_output=True)
        # 清洗 llama-cli 的调试输出
        output = self._clean_llama_output(result.stdout)
        return output
```

### 3.3 listener.py 生命周期管理

listener 启动时自动启动本地后端，退出时自动清理：

```python
def _start_local_backend():
    """启动本地推理服务（仅 http_server 模式需要）"""
    config = load_config()
    if config.get("model_type") != "http_server":
        return
    from backends import LlamaServerBackend
    backend = LlamaServerBackend(config)
    if not backend.start():
        log("llama-server 启动失败", "ERROR")

def cleanup():
    _stop_local_backend()

atexit.register(cleanup)
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)
```

### 3.4 setup_local_llm.py

一键下载脚本，自动检测平台和架构：

```
python setup_local_llm.py
python setup_local_llm.py --version b4656
python setup_local_llm.py --list-releases
```

下载的 llama.cpp 二进制放入 `llama_cpp_bin/` 目录：

```
llama_cpp_bin/
├── llama-server.exe    # HTTP 服务模式（默认）
├── llama-cli.exe       # CLI 模式（备选）
├── llama.dll
├── ggml.dll
└── ...
```

### 3.5 跨平台 exe 查找

`find_cli_path()` 统一工具函数，自动适应 Linux/macOS/Windows：

```python
def find_cli_path(basename):
    node_dir = os.path.dirname(os.path.abspath(__file__))
    if os.name == "nt":
        names = [basename + ".exe", basename]
    else:
        names = [basename, basename + ".exe"]
    candidates = [
        os.path.join(node_dir, "llama_cpp_bin", n) for n in names
    ] + [
        os.path.join(node_dir, n) for n in names
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(...)
```

## 四、验证方法

1. `python setup_local_llm.py` — 下载 llama.cpp 二进制成功
2. `python -c "from backends import find_cli_path; print(find_cli_path('llama-server'))"` — 路径查找正确
3. node_config.json 中 `model_type=http_server` 时，listener 启动后 `_start_local_backend()` 自动调用
4. `model_type=cli_local` 时，每次 `infer()` 调用 `llama-cli.exe` 子进程

## 五、修改文件清单

| 文件 | 改动 |
|------|------|
| `nodes/node_python_llm_infer/backends.py` | 新增 `LlamaServerBackend`、`LlamaCliBackend`、`find_cli_path()` |
| `nodes/node_python_llm_infer/listener.py` | 新增 `_start_local_backend()`、`cleanup()`、信号处理 |
| `nodes/node_python_llm_infer/setup_local_llm.py` | 新建：一键下载脚本 |
| `nodes/node_python_llm_infer/node_config.json` | `model_path` 增加 `file_filter` 为 `GGUF 模型 (*.gguf)` |

---

**最后更新**：2026-07-23
