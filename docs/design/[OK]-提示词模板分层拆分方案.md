# 提示词模板分层拆分方案

## 问题

原 `prompt.py` 的 `TEMPLATE` 将三种输出格式（直接回复／检索记忆／工具调用）合并在一个超长字符串中，用 `━━━` 分隔线区隔。导致：
- 代码臃肿，三个职责挤在一个变量里
- 第一轮 prompt 包含另外两个选项的完整格式，浪费上下文
- 第二轮（检索结果）模板也塞在同一个文件中，职责不清

## 方案

拆分为三个独立文件，每种路径一个模板文件，共享上下文头。

### 文件结构

```
node_python_aaa_cognition/
├── prompt.py              # 第一轮：三选一决策模板
│   ├── _CONTEXT_HEADER    # 共享上下文头（self_cognition, user_text 等）
│   ├── DIRECT_TEMPLATE    # 模板一：直接回复（含完整字段）
│   ├── RETRIEVAL_TEMPLATE # 模板二：检索记忆（仅【语意检索】格式）
│   ├── TOOL_TEMPLATE      # 模板三：工具调用（仅【工具调用】格式）
│   ├── build()            # 第一轮综合构建：DIRECT_TEMPLATE + 简短选项提示
│   ├── build_direct()     # 独立构建直接回复模板
│   ├── build_retrieval()  # 独立构建检索记忆模板
│   ├── build_tool()       # 独立构建工具调用模板
│   └── _prepare_ctx()     # 共享条件字段填充
│
├── prompt_retrieval.py    # 第二轮：检索记忆后带结果的回复模板
│   ├── SECOND_TEMPLATE    # 上下文 + 检索结果 + 直接回复格式
│   └── build_second()     # 构建第二轮模板
│
└── prompt_tool.py         # 工具调用模板（预留，当前功能未开放）
    └── build_tool_response()  # 返回「未开放」提示
```

### 模板定义

**模板一 — DIRECT_TEMPLATE（直接回复）：**
```
上下文头 + 输出格式（自然回复、心情、想法、事件摘要、
自我/他人认知、用户/自我信息、记忆归档、归档标签）
```

**模板二 — RETRIEVAL_TEMPLATE（检索记忆）：**
```
上下文头 + 【语意检索】需要回忆的关键词
```

**模板三 — TOOL_TEMPLATE（工具调用）：**
```
上下文头 + 【工具调用】工具名 | 参数名=值
```

**第二轮 — SECOND_TEMPLATE（检索后回复）：**
```
上下文头 + 记忆检索结果 + 【自然回复】（同直接回复格式）
```

### 上下文优化

第一轮 `build()` 不再附加另外两个选项的完整格式（约 200 字符），改为一句简短提示：

```
（注意：你也可以输出【语意检索】关键词 来检索记忆，或输出【工具调用】来调用工具。）
```

LLM 知道节标记的格式即可输出，无需重复展示。

### 调用流程

```
第一轮（prompt.build）
  ┌─ 直接回复 → LLM 输出完整字段 → _on_parsed 写库 + 输出
  ├─ 检索记忆 → LLM 输出关键词 → AAA 检索
  │                           └─ 第二轮（prompt_retrieval.build_second）
  │                              LLM 根据检索结果输出完整回复
  └─ 工具调用 → LLM 输出调用 → _on_parsed 返回「未开放」

第二轮不经过 prompt.build，直接走 prompt_retrieval.build_second。
```

### main.py 改动

```python
import prompt as pt              # 第一轮
import prompt_retrieval as ptr   # 第二轮检索
import prompt_tool as ptoo       # 工具调用

# _on_text → 第一轮
return {"content": pt.build(ctx)}

# _on_parsed → 触发检索时
return {"content": ptr.build_second(ctx2)}
```

## 效果

- 三个模板常量独立、纯净，互不污染
- 每种路径一个文件，职责清晰
- 第一轮 prompt 节省 ~28% 字符（因去掉完整附录）
- 新增路径（如工具调用正式上线）只需加文件，不改已有代码
