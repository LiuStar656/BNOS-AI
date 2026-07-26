# 02 — 多供应商云端 API 支持

> 日期：2026-07-23 | 涉及文件：3 | 变更类型：增强

---

## 一、问题描述

原设计仅支持两种云端供应商（OpenAI / Anthropic），且每个供应商的 API 格式和鉴权方式差异大。新需求要求支持 DeepSeek，未来还可能增加更多供应商。

如果继续在 `infer()` 中堆叠 if-else 来判断供应商，会导致：
1. 每增加一个供应商就要修改 `infer()` 的 if-else 链
2. 供应商特定逻辑（API URL、鉴权头、响应解析）散落在各处
3. 无法为新供应商设定独立的默认值（api_base / model）

## 二、目标

实现可扩展的多供应商适配层，核心诉求：
- 新增供应商只需在字典中加一条记录，不修改任何方法
- 每个供应商独立默认值（api_base / model）
- 用户可在面板中覆盖默认值

## 三、修改方案

### 3.1 CLOUD_VENDOR_DEFAULTS 字典

```python
CLOUD_VENDOR_DEFAULTS = {
    "openai":    {"api_base": "https://api.openai.com/v1",                "model": "gpt-4o"},
    "anthropic": {"api_base": "https://api.anthropic.com",                "model": "claude-3-5-sonnet-20241022"},
    "google":    {"api_base": "https://generativelanguage.googleapis.com", "model": "gemini-2.0-flash"},
    "deepseek":  {"api_base": "https://api.deepseek.com/v1",              "model": "deepseek-chat"},
    "custom_openai": {"api_base": "https://api.openai.com/v1",            "model": "gpt-4o-mini"},
}
```

`CloudApiBackend.__init__` 中按 `cloud_vendor` 加载默认值，用户配置可覆盖：

```python
defaults = CLOUD_VENDOR_DEFAULTS.get(self.vendor, CLOUD_VENDOR_DEFAULTS["openai"])
self.api_base = (config.get("api_base") or "").strip() or defaults["api_base"]
self.cloud_model = (config.get("cloud_model") or "").strip() or defaults["model"]
```

### 3.2 三个 `_infer_*` 私有方法

每个方法适配一种 API 格式，由 `infer()` 统一入口路由：

| 供应商 | 方法 | API 格式 | 鉴权方式 |
|--------|------|---------|---------|
| openai / deepseek / custom_openai | `_infer_openai` | `POST /v1/chat/completions` → `choices[0].message.content` | `Bearer {api_key}` |
| anthropic | `_infer_anthropic` | `POST /v1/messages` → `content[].text` | `x-api-key` |
| google | `_infer_google` | `POST /v1/models/{model}:generateContent` → `candidates[].content.parts[].text` | `?key={api_key}` |

```python
def infer(self, prompt, max_tokens=2048, temperature=0.7):
    if self.vendor == "anthropic":
        return self._infer_anthropic(prompt, max_tokens, temperature)
    elif self.vendor == "google":
        return self._infer_google(prompt, max_tokens, temperature)
    else:
        return self._infer_openai(prompt, max_tokens, temperature)
```

openai / deepseek / custom_openai 均走 `_infer_openai` 路径，因为三者都使用 OpenAI 兼容格式。vendor 差异仅体现在默认值上。

### 3.3 node_config.json 补充

`cloud_vendor` 枚举选项增加 `"deepseek"`，默认值设为 `"deepseek"`。同时 `api_key` / `api_base` / `cloud_model` 默认值改为 DeepSeek 配置，即开即用。

### 3.4 增强错误报告

原 `resp.raise_for_status()` 仅抛出 "400 Client Error"，不包含响应体。新增 `_check_response()` 辅助函数：

```python
def _check_response(resp):
    if not resp.ok:
        try:
            body = resp.json()
            detail = json.dumps(body, ensure_ascii=False)
        except Exception:
            detail = resp.text[:500]
        raise requests.HTTPError(
            f"{resp.status_code} {resp.reason} | {detail}",
            response=resp,
        )
```

现在 400 错误会显示完整原因，例如：`400 Bad Request | Failed to parse the request body as JSON: messages[0].content: lone leading surrogate in hex escape`。

## 四、验证方法

1. `python -c "from backends import CloudApiBackend; b = CloudApiBackend({'cloud_vendor':'deepseek','api_key':'sk-...'}); print(b.infer('hi', 10, 0.5))"` — DeepSeek API 调用正常
2. `python -c "from backends import CloudApiBackend; b = CloudApiBackend({'cloud_vendor':'openai','api_key':'sk-...'}); print(b.infer('hi', 10, 0.5))"` — OpenAI API 调用正常
3. 无 `api_key` 时，错误消息清晰：不打印 "400 Client Error" 而是响应体详情

## 五、修改文件清单

| 文件 | 改动 |
|------|------|
| `nodes/node_python_llm_infer/backends.py` | 新增 `_check_response()`、`deepseek` 供应商、`CloudApiBackend` 三方法 |
| `nodes/node_python_llm_infer/node_config.json` | `cloud_vendor` 增加 `"deepseek"` 选项，默认值改为 DeepSeek 配置 |
| `nodes/node_python_llm_infer/main.py` | `except` 块相应捕获 `_check_response` 抛出的增强错误 |

---

**最后更新**：2026-07-23
