# 04 — Windows Chinese Encoding Bug Fix

> Date: 2026-07-23 | Files affected: 2 | Type: Fix

---

## 一、Problem

When calling `main.py` via subprocess with Chinese input, the DeepSeek API returned `400 Bad Request`:

```
[Output] code=0  type=default
[Error] 400 Bad Request | Failed to parse the request body as JSON: messages[0].content: lone leading surrogate in hex escape at line 1 column 135
```

However, when importing `main.py` directly in the same Python process and calling `process()` with the same Chinese input, the inference worked correctly. Behavior was inconsistent.

## 二、Root Cause

`main.py`'s `__main__` block reads input via `sys.stdin.read()`. On Windows, `sys.stdin` defaults to the system locale encoding (Chinese Simplified: `cp936`, i.e., GBK).

The test script passes UTF-8 bytes via `subprocess.run(input=..., encoding="utf-8")`, but the child process's `sys.stdin` decodes these bytes as GBK. When the text contains non-ASCII Chinese characters, UTF-8 byte sequences are decoded incorrectly as GBK, producing **invalid surrogate characters** (e.g., `\uDxxx`). These surrogate characters are then serialized into the JSON request body by the `requests` library, and the DeepSeek API cannot parse them, returning 400.

**Flow:**

```
UTF-8 Chinese → subprocess.stdin (encoding=utf-8) → child sys.stdin (cp936) → surrogate chars
→ json.loads fails or data contains bad chars → requests.post(json=...) serializes surrogates → DeepSeek 400
```

**Why doesn't direct import fail?**

`from main import process` calls within the same process — no stdin/stdout pipe involved, strings passed at the Python object level, no encoding conversion issue.

## 三、Solution

In the `__main__` block, explicitly set stdin encoding to UTF-8 before reading:

```python
# ❌ Before
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ...

# ✅ After
if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    ...
```

`sys.stdin.reconfigure(encoding="utf-8")` ensures that regardless of the system locale encoding, stdin decodes input bytes as UTF-8.

Additionally, `_check_response()` was added (see #02) to make similar issues directly identifiable through the response body in error messages, eliminating guesswork.

## 四、Impact

Only affects Windows platform. On Linux/macOS, `sys.stdin` default encoding is already UTF-8.

After the fix, all Chinese input (prompts, Chinese descriptions in node config) works correctly via stdin on Windows.

## 五、Verification

1. `python -c "print('中文')" | python main.py` — Chinese piped via stdin, inference works
2. Workflow simulation test (`_test_workflow.py`) all 3 test cases pass, including Chinese prompt
3. Tested on Windows cmd / PowerShell / Git Bash — Chinese input works correctly on all three

## 六、Files Changed

| File | Change |
|------|--------|
| `nodes/node_python_llm_infer/main.py` | Line 116: added `sys.stdin.reconfigure(encoding="utf-8")` |
| `nodes/node_python_llm_infer/backends.py` | Added `_check_response()` for API error body in messages (aids debugging) |

---

**Last updated**: 2026-07-23
