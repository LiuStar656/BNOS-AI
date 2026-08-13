# 01 — LLM Inference Node Initial Development

> Date: 2026-07-23 | Files affected: 9 | Type: New

---

## 一、Problem

In the original BNOS system, LLM inference was embedded inside the AAA cognition node's `main.py`, supporting only a single `qwen_api` backend. This caused:

1. Inference logic coupled with business logic — cannot debug LLM output independently
2. Switching vendors (local/cloud) requires modifying AAA code
3. API Keys scattered across configuration files
4. Other nodes (e.g., Live2D) cannot reuse inference capability directly

## 二、Goal

Extract LLM inference into an independent `node_python_llm_infer` node, following BNOS node development standards:

- Independent process + independent venv — crashes don't affect other nodes
- No BNOS module dependencies (pure stdin/stdout communication)
- Support multiple backends (local llama.cpp / cloud API), configured via parameters
- Use multi-port + type filtering instead of if-else data dispatching
- Modular structure: `main.py` only routes, `config.py` loads config, `backends.py` encapsulates business logic

## 三、Solution

### 3.1 Directory Structure

```
node_python_llm_infer/
├── node_config.json     # Core config (9 params + 2 input ports + 2 output ports)
├── main.py              # Router entrypoint (55 lines business + framework bridge)
├── config.py            # Config loader (lazy-loads node_config.json)
├── backends.py          # Three backends + factory + vendor defaults
├── listener.py          # Polling daemon + local service lifecycle management
├── start.bat            # Windows startup script
├── start.sh             # Linux/macOS startup script
├── requirements.txt     # Dependencies: only requests
└── setup_local_llm.py   # Local llama.cpp binary download script
```

### 3.2 Architecture Split

Following AAA cognition node's modular pattern, the monolithic `main.py` was split into three files:

**config.py** — Lazy loading + parameter extraction:

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

**backends.py** — Three backends + factory + vendor config + utilities:

- `find_cli_path(basename)` — Cross-platform exe lookup
- `CLOUD_VENDOR_DEFAULTS` — 5 vendor defaults
- `LlamaServerBackend` — llama-server HTTP backend (model resident, low latency)
- `LlamaCliBackend` — llama-cli CLI backend (zero config, loads model per call)
- `CloudApiBackend` — Multi-vendor cloud (OpenAI/Anthropic/Google/DeepSeek/custom)
- `create_backend()` — Factory function

**main.py** — Thin router:

```python
class MyNode:
    def __init__(self):
        self._backend = None
        self._cfg = None

    def process(self, data):
        cmd = data.get("cmd")
        if cmd == "init_check":
            return self._handle_init_check()
        if self._backend is None:
            self._cfg = load_config()
            params = extract_params(self._cfg)
            self._backend = create_backend(params.get("model_type"), params)
        prompt_text = (data.get("content") or data.get("data") or data.get("prompt") or "").strip()
        if not prompt_text:
            return {"_port": "default", "data_type": "text", "content": "", "error": "empty prompt"}
        result_text = self._backend.infer(...)
        return {"_port": "default", "data_type": "text", "content": result_text}
```

### 3.3 node_config.json Specification

Uses the BNOS 11 widget types, each `input_port` explicitly specifies the `source` field:

| Parameter | Type | Description |
|-----------|------|-------------|
| `model_type` | enum | `http_server` / `cli_local` / `cloud` |
| `model_path` | file | GGUF model path |
| `llama_port` | int | Local service port |
| `cloud_vendor` | enum | `openai` / `anthropic` / `google` / `deepseek` / `custom_openai` |
| `api_base` | string | API Base URL |
| `api_key` | password | API Key |
| `cloud_model` | string | Cloud model name |
| `max_tokens` | int | Max generation tokens |
| `temperature` | float | Temperature |

### 3.4 Composite Node / EXE Compatibility

- All paths based on `__file__`, no dependency on `os.getcwd()`
- No module-level I/O side effects, configuration uses lazy loading
- `process(data)` is a top-level pure function, importable directly
- No module-level mutable global state

## 四、Verification

1. `python -c "from main import MyNode, process"` — Module import with zero side effects
2. `python -c "from backends import create_backend, CloudApiBackend"` — Backend module usable independently
3. `echo '{"content":"hello"}' | python main.py` — stdout outputs valid JSON
4. Test `init_check`: `echo '{"cmd":"init_check"}' | python main.py` → `type=status`

## 五、Files Changed

| File | Change |
|------|--------|
| `nodes/node_python_llm_infer/node_config.json` | New: 9 params + 2 input ports + 2 output ports |
| `nodes/node_python_llm_infer/main.py` | New: router + framework bridge + `__main__` |
| `nodes/node_python_llm_infer/config.py` | New: lazy config loading |
| `nodes/node_python_llm_infer/backends.py` | New: three backends + factory |
| `nodes/node_python_llm_infer/listener.py` | New: polling daemon |
| `nodes/node_python_llm_infer/start.bat` | New: Windows startup script |
| `nodes/node_python_llm_infer/start.sh` | New: Linux/macOS startup script |
| `nodes/node_python_llm_infer/requirements.txt` | New: only requests |

---

**Last updated**: 2026-07-23
