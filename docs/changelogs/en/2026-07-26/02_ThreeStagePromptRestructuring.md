# 02 — AAA Three-Stage Prompt Restructuring

> Date: 2026-07-26 | Files touched: 5 | Type: Architecture Refactor

---

## 1. Problem

AAA's prompt template mixed all output formats into a single JSON schema. The LLM had to simultaneously output "direct reply", "semantic retrieval", and "tool call" fields. When the LLM returned a tool-call marker and there was no corresponding tool (Grok not implemented), AAA entered an infinite retry loop, never writing to `output_reply.json`.

## 2. Root Cause

1. Old prompt merged all output templates into a single large JSON schema
2. No fallback handling for tool calls — LLM kept returning tool-call markers
3. Memory retrieval and direct reply logic processed in the same round, increasing context pressure

## 3. Solution

### 3.1 Three-Stage Split

Separated the single prompt into three independent template files:

- **prompt.py**: Core prompt (first round, thin prompt + memory summary). Output template contains only one of: direct reply / retrieval / tool call marker
- **prompt_retrieval.py**: Second-round prompt with retrieval results. Output template only for direct reply
- **prompt_tool.py**: Tool-call template (reserved, marked as unavailable)

### 3.2 Decision Logic Refactor (main.py `_on_parsed`)

```python
# Three-way decision
tool_call = parsed.get("工具调用", [])
retrieval_keywords = (parsed.get("语意检索") or "").strip()

if tool_call:
    return {"content": "Tool calls are currently unavailable."}

if retrieval_keywords and pending:
    memos_results = memos.retrieve(...)
    return {"content": ptr.build_second(ctx2)}

# Direct reply
db.write_parsed_async(parsed, dbp, ...)
```

### 3.3 Separated Output Templates

| Scenario | Output Template | Template File |
|----------|----------------|---------------|
| Direct reply | `{"自然回复": "...", "心情": "", "记忆归档": "", "归档标签": ""}` | prompt.py |
| Semantic retrieval | `{"语意检索": "keywords"}` | prompt.py |
| Tool call | Mark as unavailable | prompt_tool.py |
| Retrieval + reply | Full reply with memory results | prompt_retrieval.py |

## 4. Impact

- `prompt.py`: Core template restructured
- `prompt_retrieval.py`: New retrieval template
- `prompt_tool.py`: New tool-call template
- `main.py`: Three-stage decision logic rewritten
- `parser.py`: Output parser restructured
