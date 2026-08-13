# 2026-07-23 Changelog Overview

[Back to Index](../README.md)

---

## Updates

- [01 LLM Inference Node Initial Development](./01_LLMInferNodeInitialDev.md)
- [02 Multi-Vendor Cloud API Support](./02_MultiVendorCloudSupport.md)
- [03 Local LLM Inference Support](./03_LocalLLMSupport.md)
- [04 Windows Chinese Encoding Bug Fix](./04_WindowsEncodingBugFix.md)

---

## Summary

| # | Core Change | Root Cause | Impact |
|---|-------------|------------|--------|
| 01 | Created `node_python_llm_infer` node with modular config/backend split and startup scripts | System needs a dedicated LLM provider, replacing AAA-embedded inference | Independent LLM node supporting both local and cloud backends |
| 02 | Implemented `CloudApiBackend` with 5 vendor adapters (OpenAI/Anthropic/Google/DeepSeek/custom) | Project needs flexible LLM vendor switching | Switch vendor by changing `cloud_vendor` config |
| 03 | Implemented `LlamaServerBackend` and `LlamaCliBackend` with lifecycle management | Offline and zero-config deployment requirements | Local inference via `http_server` / `cli_local` modes |
| 04 | Fixed Windows stdin encoding causing DeepSeek API 400 error | `sys.stdin` defaults to cp936 encoding, producing surrogate characters for Chinese input | All Chinese input works correctly on Windows |

---

## File Change List

### New Files

| File | Section |
|------|---------|
| `nodes/node_python_llm_infer/node_config.json` | #01 |
| `nodes/node_python_llm_infer/main.py` | #01 |
| `nodes/node_python_llm_infer/config.py` | #01 |
| `nodes/node_python_llm_infer/backends.py` | #01/#02/#03 |
| `nodes/node_python_llm_infer/listener.py` | #01 |
| `nodes/node_python_llm_infer/start.bat` | #01 |
| `nodes/node_python_llm_infer/start.sh` | #01 |
| `nodes/node_python_llm_infer/requirements.txt` | #01 |
| `nodes/node_python_llm_infer/setup_local_llm.py` | #03 |
| `nodes/node_python_llm_infer/llama_cpp_bin/.gitkeep` | #03 |
| `nodes/node_python_llm_infer/models/.gitkeep` | #03 |

### Modified Files

| File | Change |
|------|--------|
| `nodes/node_python_llm_infer/main.py` | Refactored from monolithic 200+ lines to 55-line router, aligned with AAA node pattern |
| `nodes/node_python_llm_infer/backends.py` | Enhanced: added `_check_response()`, `deepseek` vendor, `health()` idempotent method |
| `nodes/node_python_llm_infer/node_config.json` | Fixed invalid types, added missing fields, added `deepseek` vendor option |

---

## File Change Statistics

| Metric | #01 | #02 | #03 | #04 |
|--------|:---:|:---:|:---:|:---:|
| Files affected | 9 | 3 | 4 | 2 |
| Lines added | ~480 | ~120 | ~180 | ~10 |
| **Total lines** | | | | **~790** |

---

**Last updated**: 2026-07-23
