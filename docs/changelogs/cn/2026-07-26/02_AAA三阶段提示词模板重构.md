# 02 — AAA 三阶段提示词模板重构

> 日期：2026-07-26 | 涉及文件：5 | 变更类型：架构重构

---

## 一、问题描述

AAA 节点传给 LLM 的提示词模板将输出格式混合在一起，LLM 需要在同一条回复里同时输出「自然回复」「语意检索」「工具调用」三个字段。当 LLM 返回「工具调用」标记时，AAA 没有对应工具（Grok 未开发），会陷入无限重试循环，导致 `output_reply.json` 始终收不到有效回复。

## 二、根因分析

1. 旧提示词将所有输出模板合并为一个大 JSON schema，LLM 必须同时输出所有字段
2. 工具调用没有后备处理——LLM 重复返回工具调用标记，AAA 不断重试
3. 记忆检索逻辑和自然回复逻辑在同一轮中处理，上下文压力大

## 三、修改方案

### 3.1 三阶段拆分

将原有 single-prompt 拆分为三个独立模板文件：

**prompt.py** — 核心提示词（第一轮，薄 prompt + 记忆简要摘要），输出模板只含「自然回复」「语意检索」「工具调用」之一的标记字段
**prompt_retrieval.py** — 带检索结果的第二轮提示词，输出模板只含自然回复
**prompt_tool.py** — 工具调用模板（预留，标记为不可用）

### 3.2 决策逻辑重构 (main.py `_on_parsed`)

```python
# 三选一决策
tool_call = parsed.get("工具调用", [])
retrieval_keywords = (parsed.get("语意检索") or "").strip()

if tool_call:
    # ② 工具调用 → 直接返回不可用提示
    return {"content": "抱歉，工具调用功能目前尚未开放。"}

if retrieval_keywords and pending:
    # ② 检索记忆 → 跑 MemOS → 第二轮 prompt → 再次发给 LLM
    memos_results = memos.retrieve(...)
    return {"content": ptr.build_second(ctx2)}

# ① 直接回复 → 正常写库 + 输出
db.write_parsed_async(parsed, dbp, ...)
```

### 3.3 输出模板分离

旧模板要求 LLM 输出：
```json
{"自然回复": "...", "语意检索": "...", "工具调用": []}
```

新模板按场景区分：

| 场景 | 模板 | 模板文件 |
|------|------|---------|
| 自然回复 | 只输出 `{"自然回复": "...", "心情": "", "记忆归档": "", "归档标签": ""}` | prompt.py |
| 语意检索 | 只输出 `{"语意检索": "关键词"}` | prompt.py |
| 工具调用 | 提示不可用 | prompt_tool.py |
| 检索后回复 | 带记忆结果的完整回复 | prompt_retrieval.py |

## 四、影响范围

- `prompt.py`：核心模板重构
- `prompt_retrieval.py`：新增检索专用模板
- `prompt_tool.py`：新增工具调用模板（标记不可用）
- `main.py`：三阶段决策逻辑重写
- `parser.py`：输出解析结构调整

## 五、验证方法

1. 发送测试消息，确认 LLM 正常返回自然回复
2. 在消息中包含记忆检索关键词，确认触发第二轮检索
3. 确认工具调用不会导致无限循环
4. 确认 `output_reply.json` 正确接收到回复
