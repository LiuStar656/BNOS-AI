# 02 — Multi-Vendor Cloud API Support

> Date: 2026-07-23 | Files affected: 3 | Type: Enhancement

---

## 一、Problem

The original design supported only two cloud vendors (OpenAI / Anthropic), each with different API formats and authentication methods. The new requirement demanded DeepSeek support, with more vendors likely in the future.

Continuing to stack if-else branches in `infer()` would lead to:
1. Every new vendor requires modifying the if-else chain
2. Vendor-specific logic (API URL, auth headers, response parsing) scattered across methods
3. No way to set independent defaults (api_base / model) per vendor

## 二、Goal

Implement an extensible multi-vendor adapter layer:
- Adding a vendor means adding one entry to a dict, not modifying any methods
- Each vendor has independent defaults (api_base / model)
- Users can override defaults in the panel

## 三、Solution

### 3.1 CLOUD_VENDOR_DEFAULTS Dictionary

```python
CLOUD_VENDOR_DEFAULTS = {
    "openai":    {"api_base": "https://api.openai.com/v1",                "model": "gpt-4o"},
    "anthropic": {"api_base": "https://api.anthropic.com",                "model": "claude-3-5-sonnet-20241022"},
    "google":    {"api_base": "https://generativelanguage.googleapis.com", "model": "gemini-2.0-flash"},
    "deepseek":  {"api_base": "https://api.deepseek.com/v1",              "model": "deepseek-chat"},
    "custom_openai": {"api_base": "https://api.openai.com/v1",            "model": "gpt-4o-mini"},
}
```

`CloudApiBackend.__init__` loads defaults by `cloud_vendor`, user config can override:

```python
defaults = CLOUD_VENDOR_DEFAULTS.get(self.vendor, CLOUD_VENDOR_DEFAULTS["openai"])
self.api_base = (config.get("api_base") or "").strip() or defaults["api_base"]
self.cloud_model = (config.get("cloud_model") or "").strip() or defaults["model"]
```

### 3.2 Three `_infer_*` Private Methods

Each method adapts one API format, routed by the unified `infer()` entry:

| Vendor | Method | API Format | Auth |
|--------|--------|-----------|------|
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

openai / deepseek / custom_openai all use `_infer_openai` since they all follow the OpenAI-compatible format. Vendor differences only affect defaults.

### 3.3 node_config.json Update

`cloud_vendor` enum options added `"deepseek"`, default set to `"deepseek"`. `api_key` / `api_base` / `cloud_model` defaults changed to DeepSeek config for plug-and-play.

### 3.4 Enhanced Error Reporting

Original `resp.raise_for_status()` only throws "400 Client Error" without the response body. Added `_check_response()` helper:

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

Now 400 errors show the full reason, e.g.: `400 Bad Request | Failed to parse the request body as JSON: messages[0].content: lone leading surrogate in hex escape`.

## 四、Verification

1. `python -c "from backends import CloudApiBackend; b = CloudApiBackend({'cloud_vendor':'deepseek','api_key':'sk-...'}); print(b.infer('hi', 10, 0.5))"` — DeepSeek API call works
2. `python -c "from backends import CloudApiBackend; b = CloudApiBackend({'cloud_vendor':'openai','api_key':'sk-...'}); print(b.infer('hi', 10, 0.5))"` — OpenAI API call works
3. With no `api_key`, error messages are clear: shows response body instead of "400 Client Error"

## 五、Files Changed

| File | Change |
|------|--------|
| `nodes/node_python_llm_infer/backends.py` | Added `_check_response()`, `deepseek` vendor, `CloudApiBackend` three methods |
| `nodes/node_python_llm_infer/node_config.json` | Added `"deepseek"` to `cloud_vendor` options, defaults changed to DeepSeek |
| `nodes/node_python_llm_infer/main.py` | `except` blocks catch enhanced errors from `_check_response` |

---

**Last updated**: 2026-07-23
