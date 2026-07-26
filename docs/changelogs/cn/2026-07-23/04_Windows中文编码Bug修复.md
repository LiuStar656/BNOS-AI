# 04 — Windows 中文编码 Bug 修复

> 日期：2026-07-23 | 涉及文件：2 | 变更类型：修复

---

## 一、问题描述

通过子进程调用 `main.py` 时，如果输入包含中文，DeepSeek API 返回 `400 Bad Request`：

```
[输出] code=0  type=default
[错误] 400 Bad Request | Failed to parse the request body as JSON: messages[0].content: lone leading surrogate in hex escape at line 1 column 135
```

但直接在 Python 进程中 import `main.py` 并调用 `process()` 时，相同中文输入却能正常返回推理结果。行为不一致。

## 二、根因分析

`main.py` 的 `__main__` 块通过 `sys.stdin.read()` 读取输入。在 Windows 上，`sys.stdin` 的默认编码是系统区域编码（简体中文系统为 `cp936`，即 GBK）。

测试脚本通过 `subprocess.run(input=..., encoding="utf-8")` 传入 UTF-8 字节流，但子进程中的 `sys.stdin` 以 GBK 解码这些字节。当文本包含非 ASCII 中文时，UTF-8 字节序列被 GBK 错误解码，产生**无效的 surrogate 字符**（如 `\uDxxx`）。这些 surrogate 字符随后被 `requests` 库序列化为 JSON 请求体发送给 DeepSeek API，API 无法解析而返回 400。

**流程：**

```
UTF-8 中文 → subprocess.stdin (encoding=utf-8) → 子进程 sys.stdin (cp936) → 解码出 surrogate
→ json.loads 失败或 data 含坏字符 → requests.post(json=...) 序列化含 surrogate → DeepSeek 400
```

**为什么直接 import 不报错？**

直接 `from main import process` 在同一进程内调用，不经过 stdin/stdout 管道，字符串在 Python 对象层面传递，不存在编码转换问题。

## 三、修改方案

在 `__main__` 块中，在读取 `sys.stdin` 之前显式设置编码为 UTF-8：

```python
# ❌ 修改前
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ...

# ✅ 修改后
if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    ...
```

`sys.stdin.reconfigure(encoding="utf-8")` 确保无论系统区域编码是什么，stdin 都以 UTF-8 解码输入字节。

此外，新增 `_check_response()` 增强错误报告（见 #02），使类似问题可通过错误消息中的响应体直接定位，不再需要猜测。

## 四、影响范围

仅影响 Windows 平台，Linux/macOS 上 `sys.stdin` 默认编码已经是 UTF-8。

修复后所有中文输入（prompt / 节点配置中的中文描述）在 Windows 上均可正常通过 stdin 传入。

## 五、验证方法

1. `python -c "print('\u4e2d\u6587')" | python main.py` — 中文通过管道传入正常推理
2. 工作流模拟测试（`_test_workflow.py`）三个用例全部通过，包括中文 prompt
3. 在 Windows cmd / PowerShell / Git Bash 三种终端下测试，中文均正常

## 六、修改文件清单

| 文件 | 改动 |
|------|------|
| `nodes/node_python_llm_infer/main.py` | 第 116 行新增 `sys.stdin.reconfigure(encoding="utf-8")` |
| `nodes/node_python_llm_infer/backends.py` | 新增 `_check_response()` 使错误消息包含 API 响应体（辅助定位） |

---

**最后更新**：2026-07-23
