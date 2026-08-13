# 2026-07-23 更新总览

[返回总索引](../README.md)

---

## 更新目录

- [01 LLM 推理节点初始开发](./01_LLM推理节点初始开发.md)
- [02 多供应商云端 API 支持](./02_多供应商云端API支持.md)
- [03 本地 LLM 推理支持](./03_本地LLM推理支持.md)
- [04 Windows 中文编码 Bug 修复](./04_Windows中文编码Bug修复.md)

---

## 摘要

| # | 核心改动 | 根因 | 影响 |
|---|---------|------|------|
| 01 | 新建 `node_python_llm_infer` 节点，含 config/backend 模块拆分和启动脚本 | 系统需要唯一 LLM 推理提供者，替代 AAA 内嵌推理 | 独立的 LLM 推理节点，支持本地和云端双后端 |
| 02 | 实现 `CloudApiBackend` 的 5 供应商适配（OpenAI/Anthropic/Google/DeepSeek/custom） | 项目需要灵活切换不同 LLM 供应商 | 节点配置 `cloud_vendor` 即可一键切换供应商 |
| 03 | 实现 `LlamaServerBackend` 和 `LlamaCliBackend` 两个本地后端，含生命周期管理 | 离线场景和零配置部署需求 | 本地推理可通过 `http_server` / `cli_local` 模式独立运行 |
| 04 | 修复 Windows 上 stdin 编码导致 DeepSeek API 400 错误 | `sys.stdin` 默认 cp936 编码导致中文 surrogate 字符 | 所有中文输入在 Windows 下正常推理 |

---

## 修改文件清单

### 新增文件

| 文件 | 所属 |
|------|------|
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

### 重大修改文件

| 文件 | 改动 |
|------|------|
| `nodes/node_python_llm_infer/main.py` | 重构：从单体 200+ 行拆分为路由层（55 行），结构对齐 AAA 节点模式 |
| `nodes/node_python_llm_infer/backends.py` | 增强：新增 `_check_response()` 错误报告、`deepseek` 供应商、`health()` 幂等方法 |
| `nodes/node_python_llm_infer/node_config.json` | 参数调整：修复 type 无效值、补充专属字段、新增 `deepseek` 供应商选项 |

---

## 文件变更统计

| 指标 | #01 | #02 | #03 | #04 |
|------|:---:|:---:|:---:|:---:|
| 涉及文件 | 9 | 3 | 4 | 2 |
| 新增行数 | ~480 | ~120 | ~180 | ~10 |
| **总计行数** | | | | **~790** |

---

**最后更新**：2026-07-23
