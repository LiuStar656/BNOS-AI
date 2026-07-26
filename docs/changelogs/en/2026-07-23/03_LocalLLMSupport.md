# 03 — Local LLM Inference Support

> Date: 2026-07-23 | Files affected: 4 | Type: New

---

## 一、Problem

Previously, LLM inference only supported cloud API mode, making it impossible to run offline or without internet. The project requires local llama.cpp inference with two usage modes:

1. **HTTP Server mode**: Model resident in memory, low latency, suitable for daily conversation
2. **CLI mode**: Loads model per inference call, zero configuration, suitable for low-frequency usage

Additionally, the local deployment flow should be simple — users download llama.cpp binaries and a GGUF model, no compilation required.

## 二、Goal

- Implement `LlamaServerBackend` (HTTP Server mode)
- Implement `LlamaCliBackend` (CLI mode)
- Provide `setup_local_llm.py` one-click download script
- Automatic lifecycle management for local services (listener manages server process)

## 三、Solution

### 3.1 LlamaServerBackend

llama-server.exe runs as a child process managed by the node:

```python
class LlamaServerBackend:
    def start(self) -> bool:
        # Idempotent: /health already returns 200? Return True immediately
        if self.health():
            return True
        if not self.model_path or not os.path.isfile(self.model_path):
            return False
        # Start llama-server subprocess, wait 60s for readiness
        self.server_process = subprocess.Popen([...])
        for _ in range(60):
            if self.health():
                return True
            time.sleep(1)
        return False

    def infer(self, prompt, max_tokens, temperature):
        # Call via OpenAI-compatible API
        resp = requests.post(f"{self.api_base}/chat/completions", json={...})
        return resp.json()["choices"][0]["message"]["content"]

    def stop(self):
        if self.server_process:
            self.server_process.terminate()
```

**Idempotent start**: Even if `main.py` is called multiple times via subprocess, the server only starts once.

### 3.2 LlamaCliBackend

Launches `llama-cli.exe` per call, passes prompt via tempfile:

```python
class LlamaCliBackend:
    def infer(self, prompt, max_tokens, temperature):
        fd, prompt_file = tempfile.mkstemp(suffix=".txt", text=True)
        os.write(fd, prompt.encode("utf-8"))
        os.close(fd)
        result = subprocess.run([self._cli_path, "-m", self.model_path, ...], capture_output=True)
        output = self._clean_llama_output(result.stdout)
        return output
```

### 3.3 Listener Lifecycle Management

Listener auto-starts the local backend on boot and cleans up on exit:

```python
def _start_local_backend():
    config = load_config()
    if config.get("model_type") != "http_server":
        return
    from backends import LlamaServerBackend
    backend = LlamaServerBackend(config)
    if not backend.start():
        log("llama-server failed to start", "ERROR")

def cleanup():
    _stop_local_backend()

atexit.register(cleanup)
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)
```

### 3.4 setup_local_llm.py

One-click download script, auto-detects platform and architecture:

```
python setup_local_llm.py
python setup_local_llm.py --version b4656
python setup_local_llm.py --list-releases
```

Downloads llama.cpp binaries into `llama_cpp_bin/`:

```
llama_cpp_bin/
├── llama-server.exe    # HTTP service mode (default)
├── llama-cli.exe       # CLI mode (backup)
├── llama.dll
├── ggml.dll
└── ...
```

### 3.5 Cross-Platform exe Lookup

`find_cli_path()` unified utility, auto-adapts to Linux/macOS/Windows:

```python
def find_cli_path(basename):
    node_dir = os.path.dirname(os.path.abspath(__file__))
    if os.name == "nt":
        names = [basename + ".exe", basename]
    else:
        names = [basename, basename + ".exe"]
    candidates = [os.path.join(node_dir, "llama_cpp_bin", n) for n in names] \
               + [os.path.join(node_dir, n) for n in names]
    for path in candidates:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(...)
```

## 四、Verification

1. `python setup_local_llm.py` — Downloads llama.cpp binaries successfully
2. `python -c "from backends import find_cli_path; print(find_cli_path('llama-server'))"` — Path lookup correct
3. With `model_type=http_server`, `_start_local_backend()` is called on listener startup
4. With `model_type=cli_local`, each `infer()` spawns `llama-cli.exe` subprocess

## 五、Files Changed

| File | Change |
|------|--------|
| `nodes/node_python_llm_infer/backends.py` | Added `LlamaServerBackend`, `LlamaCliBackend`, `find_cli_path()` |
| `nodes/node_python_llm_infer/listener.py` | Added `_start_local_backend()`, `cleanup()`, signal handlers |
| `nodes/node_python_llm_infer/setup_local_llm.py` | New: one-click download script |
| `nodes/node_python_llm_infer/node_config.json` | `model_path` added `file_filter` as `GGUF 模型 (*.gguf)` |

---

**Last updated**: 2026-07-23
