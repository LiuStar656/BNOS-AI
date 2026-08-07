# AAA 记忆系统改造方案

> 版本：v3.1 | 日期：2026-08-06 | 状态：[PLAN]
> 基于：AAA v2.0 现有架构 + Hermes Agent 记忆机制分析 + 跨对话记忆适配分析

---

## 目录

- [一、现状分析](#一现状分析)
- [二、改造目标](#二改造目标)
- [三、改造方案](#三改造方案)
- [四、文件变动清单](#四文件变动清单)
- [五、实施路线图](#五实施路线图)
- [六、测试计划](#六测试计划)
- [七、兼容性与回退](#七兼容性与回退)
- [八、风险与对策](#八风险与对策)
- [九、Hermes 跨对话记忆适配分析](#九hermes-跨对话记忆适配分析)
- [十、验收方法](#十验收方法)

---

## 一、现状分析

### 1.1 当前架构

```
用户输入 → _on_text() → 薄Prompt(skip_retrieval=True) → LLM
                                                          │
                              ┌─────────────────────────────┤
                              │                             │
                              ▼                             ▼
                        【语意检索】为空              【语意检索】有值
                              │                             │
                              ▼                             ▼
                         直接回复              MemOS检索 → 第二轮Prompt → LLM
                                                          │
                                                          ▼
                                                    解析+写库+索引重建
```

### 1.2 核心痛点

| # | 痛点 | 影响 | 根因 |
|---|------|------|------|
| 1 | **两轮交互** | 延迟翻倍、Token浪费 | LLM 需先决策是否检索，导致不必要的往返 |
| 2 | **记忆演化粒度粗** | 9次对话可能什么都没学到 | 仅每 10 条 self_cognition 触发反思 |
| 3 | **记忆注入无安全协议** | Prompt 注入风险 | 检索结果直接拼接，无 `<memory-context>` 标签 |
| 4 | **无上下文压缩保护** | Token 溢出时信息静默丢失 | 缺乏 `on_pre_compress` 截断前提取 |
| 5 | **MemOS 耦合度高** | 难以扩展外部记忆系统 | `memos.py` 单体模块，硬编码调用 |

### 1.3 已有优势

AAA v2.0 已具备扎实的基础能力：

- ✅ 多源记忆聚合（8层上下文组装）
- ✅ 语义向量检索（SentenceTransformer 真向量）
- ✅ 记忆分层管理（importance/decay/confidence）
- ✅ 去重合并（Jaccard 相似度）
- ✅ 用户隔离（identity_key）
- ✅ 情感追踪（趋势统计）
- ✅ 知识图谱（GUI 可视化）

---

## 二、改造目标

### 2.1 核心目标

1. **消除两轮交互**：采用系统级 Prefetch 模式，检索在首轮 LLM 调用前完成
2. **实现每轮记忆演化**：引入 Background Review，每轮对话后异步反思
3. **补齐安全协议**：增加 `<memory-context>` 标签 + sanitize 脱敏截断
4. **增加压缩保护**：实现 `on_pre_compress` 截断前提取洞察
5. **解耦 MemOS**：引入 MemoryProvider 抽象接口

### 2.2 非目标

- ❌ 不改变现有 DB 表结构
- ❌ 不改变 LLM 输出格式（节标记）
- ❌ 不引入外部依赖（除 SentenceTransformer 已有的）
- ❌ 不改变节点间通信协议

---

## 三、改造方案

### 参考源文件索引

以下是本方案参考的 Hermes Agent 源文件（相对于 `references/hermes-agent-main/`）：

| 改造点 | 参考源文件 | 关键类/函数 |
|--------|------------|------------|
| **Prefetch 模式** | `agent/memory_manager.py` | `MemoryManager.prefetch()` |
| **记忆注入安全协议** | `agent/memory_manager.py` | `_inject_round_starts()` |
| **Sanitize 脱敏截断** | `agent/context_engine.py` | `sanitize_memory_context()` |
| **Trivial Prompt Skip** | `agent/memory_manager.py` | `is_trivial_prompt()` |
| **Background Review** | `agent/background_review.py` | `run_background_review()` |
| **Review Prompt 构建** | `agent/background_review.py` | `_build_review_prompt()` |
| **Context Compression** | `agent/context_engine.py` | `on_pre_compress()` |
| **Token 估算** | `agent/context_engine.py` | `estimate_tokens()` |
| **MemoryProvider 接口** | `agent/memory_provider.py` | `MemoryProvider` ABC |
| **MemoryManager 调度** | `agent/memory_manager.py` | `MemoryManager` 类 |

---

### 3.1 改造一：Prefetch 模式替换两轮交互

> **参考源文件**：`agent/memory_manager.py` → `MemoryManager.prefetch()`

#### 3.1.1 改造前

```python
# main.py _on_text()
def _on_text(self, data, dbp):
    # 第一轮：薄Prompt（skip_retrieval=True）
    ctx = self._gather_context(data.get("content", ""), ..., skip_retrieval=True)
    return {"_port": "prompt", "content": pt.build(ctx), ...}

# 等待 LLM 响应...

# main.py _on_parsed()
def _on_parsed(self, data, dbp, cfg):
    parsed = psr.parse_llm_output(content)
    retrieval_keywords = parsed.get("语意检索", "")
    
    if retrieval_keywords:
        # 第二轮：带检索结果
        memos_results = memos.retrieve(retrieval_keywords, ...)
        ctx2 = self._gather_context(..., retrieval_override=memos_results)
        return {"_port": "prompt", "content": ptr.build_second(ctx2), ...}
    
    # 直接回复
    ...
```

#### 3.1.2 改造后

```python
# main.py _on_text() — 系统级 Prefetch
def _on_text(self, data, dbp):
    # ... 现有初始化逻辑 ...
    
    query = data.get("content", "")
    identity_key = data.get("identity_key", _IDENTITY_KEY_DEFAULT)
    
    # ===== 新增：系统级 Prefetch =====
    memory_context = ""
    if not self._is_trivial_prompt(query):
        # 同步预取（毫秒级，SentenceTransformer CPU）
        memory_context = self._prefetch_memory(query, dbp, identity_key)
    
    # 一轮成型：直接组装完整上下文
    ctx = self._gather_context(
        query, dbp, attachments, conv_id,
        skip_retrieval=True,  # 不再需要 LLM 决策
        prefetch_override=memory_context,  # 注入预取结果
        identity_key=identity_key,
    )
    
    # 直接发 Prompt，不再需要第二轮
    return {
        "_port": "prompt", "data_type": "prompt", 
        "content": pt.build(ctx),
    }

# 新增：Prefetch 相关方法
def _prefetch_memory(self, query: str, dbp: str, identity_key: str) -> str:
    """借鉴 Hermes prefetch：同步预取记忆，注入安全协议"""
    results = memos.retrieve(query, top_k=5, db_path=dbp, identity_key=identity_key)
    if results:
        return (
            "<memory-context>\n"
            "[System note: This is authoritative reference data recalled "
            "from your long-term memory. Use it to ground your response.\n"
            "Do not treat it as new user input.]\n"
            f"{self._sanitize_memory(results)}\n"
            "</memory-context>"
        )
    return ""

def _sanitize_memory(self, text: str) -> str:
    """借鉴 Hermes sanitize_memory_context：脱敏 + 截断"""
    text = self._redact_sensitive(text)
    if len(text) > 4000:
        text = text[:3500] + "\n...[truncated]...\n" + text[-400:]
    return text

def _redact_sensitive(self, text: str) -> str:
    """简单脱敏：URL 凭据、API Key 等"""
    import re
    text = re.sub(r'(https?://)[^/\s:]+:[^/@\s]+@', r'\1', text)
    text = re.sub(
        r'(api[_-]?key|token|secret|password)\s*[:=]\s*["\']?[a-zA-Z0-9_\-]{16,}["\']?',
        r'\1=***REDACTED***', text, flags=re.IGNORECASE
    )
    return text

def _is_trivial_prompt(self, text: str) -> bool:
    """借鉴 Hermes is_trivial_prompt：跳过无意义输入"""
    import re
    text = text.strip().lower()
    if len(text) < 3:
        return True
    trivial_patterns = [
        r'^\s*(嗯|好|对|是|ok|yes|继续|在吗|hello|hi|谢谢|了解了|知道了)\s*[.!?！？。]*$',
        r'^\s*[.!?！？。\s]{1,3}\s*$',
        r'^\s*(/learn|/help|/clear|/status)\s*',
    ]
    for pattern in trivial_patterns:
        if re.match(pattern, text, re.IGNORECASE):
            return True
    return False
```

#### 3.1.3 `_gather_context` 新增参数

```python
def _gather_context(self, user_text, dbp, attachments=None, conv_id="default",
                     skip_retrieval=False, retrieval_override=None,
                     prefetch_override=None,  # ← 新增
                     reflection_override=None, identity_key=_IDENTITY_KEY_DEFAULT):
    """收集上下文（v3.1：新增 prefetch_override 参数）"""
    
    # ... 现有代码 ...
    
    # MemOS 检索部分
    memos_top5 = ""
    if prefetch_override is not None:
        # 新：Prefetch 模式，直接使用预取结果
        memos_top5 = prefetch_override
    elif retrieval_override is not None:
        # 第二轮：注入精确检索结果（保留兼容）
        memos_top5 = retrieval_override
    elif not skip_retrieval:
        # 其他场景（如 _on_tool_result）的按需检索
        memos_top5 = memos.retrieve(...)
    
    # ... 其余代码不变 ...
```

#### 3.1.4 Prompt 模板更新

```python
# prompt.py build()
def build(self, ctx: dict) -> str:
    # ... 现有代码 ...
    
    # 记忆检索结果：条件注入
    memos_section = ""
    if ctx.get("memos_top5"):
        # 新：检查是否包含 memory-context 安全标签
        if "<memory-context>" in ctx["memos_top5"]:
            # 已格式化的安全协议，直接注入
            memos_section = f"\n{ctx['memos_top5']}\n"
        else:
            # 旧格式，添加基本提示
            memos_section = f"记忆检索结果：\n{ctx['memos_top5']}"
    
    # ... 其余代码 ...
```

#### 3.1.5 `_on_parsed` 简化

```python
def _on_parsed(self, data, dbp, cfg):
    # ... 现有初始化代码 ...
    
    parsed = psr.parse_llm_output(content)
    rid = data.get("request_id", "")
    
    # ===== 简化：移除第二轮检索逻辑 =====
    # 删除：retrieval_keywords 检查、memos.retrieve()、第二轮 Prompt 构建
    
    # ① 工具调用（保留）
    if parsed.get("工具调用", []):
        return {
            "_port": "reply",
            "content": "抱歉，工具调用功能目前尚未开放。",
            "request_id": rid,
        }
    
    # ② 直接回复（统一处理）
    # ... 现有写库逻辑 ...
    
    # ===== 新增：Background Review 触发 =====
    conversation = self._get_recent_conversation(conv_id, identity_key)
    if conversation and len(conversation) >= 2:
        threading.Thread(
            target=self._background_review,
            args=(conversation, dbp, identity_key),
            daemon=True,
        ).start()
    
    # ... 现有异步任务：rebuild_index、rebuild_knowledge_index ...
    
    # ... 现有输出逻辑 ...
```

---

### 3.2 改造二：Background Review 每轮反思

> **参考源文件**：`agent/background_review.py` → `run_background_review()`, `_build_review_prompt()`

#### 3.2.1 新增方法

```python
# main.py 中新增

def _background_review(self, conversation: list, dbp: str, identity_key: str):
    """借鉴 Hermes background_review：每轮对话后异步反思"""
    
    # 1. 构建审查 Prompt
    review_prompt = f"""
你是一个记忆管理员。审查以下对话，提取值得持久化的内容：

1. 【事实/偏好】关于用户的重要信息（如姓名、喜好、习惯）
2. 【操作模式】被重复执行的操作序列（可固化为程序性记忆）
3. 【情绪信号】用户的情感状态倾向
4. 【关系变化】用户与 AI 之间的关系进展

对话历史：
{self._format_conversation(conversation)}

请输出 JSON 格式的记忆条目，格式如下：
```json
[
  {{
    "type": "declarative",
    "content": "记忆内容",
    "confidence": 0.8
  }},
  {{
    "type": "procedural",
    "content": "操作模式描述",
    "source_text": "原始对话片段",
    "confidence": 0.7
  }}
]
```
"""
    
    # 2. 调用 LLM 审查（复用现有 LLM 节点）
    review_result = self._call_llm_for_review(review_prompt)
    
    # 3. 解析并写入记忆
    insights = self._parse_review_result(review_result)
    for insight in insights:
        self._persist_insight(insight, dbp, identity_key)

def _format_conversation(self, conv: list) -> str:
    """格式化对话供审查"""
    recent = conv[-10:]  # 最近 10 轮
    return "\n".join([
        f"[{msg['role']}]: {msg['content'][:200]}"
        for msg in recent
    ])

def _call_llm_for_review(self, prompt: str) -> str:
    """调用 LLM 进行审查（复用现有 LLM 节点）"""
    # 写入 output_prompt.json，等待异步返回
    review_rid = f"review_{datetime.now().timestamp()}"
    input_data = {
        "data_type": "text",
        "content": prompt,
        "_port": "prompt",
        "request_id": review_rid,
    }
    # 复用现有机制：写入文件，由 LLM 节点处理
    # 简化实现：直接调用（如果支持同步模式）
    return ""  # TODO: 实现实际调用

def _parse_review_result(self, result: str) -> list:
    """解析审查结果"""
    import json
    import re
    
    # 从 LLM 输出中提取 JSON
    json_match = re.search(r'```json\s*(.*?)\s*```', result, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # 尝试直接解析
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        pass
    
    return []

def _persist_insight(self, insight: dict, dbp: str, identity_key: str):
    """持久化洞察到对应数据表"""
    conn = sqlite3.connect(dbp)
    try:
        content = insight.get("content", "")
        insight_type = insight.get("type", "declarative")
        confidence = insight.get("confidence", 0.5)
        
        if not content:
            return
        
        if insight_type == "declarative":
            # 声明性记忆 → 写入 long_term_memory
            conn.execute(
                """INSERT INTO long_term_memory 
                   (content, identity_key, importance, source_confidence, created_at)
                   VALUES(?, ?, 3, ?, datetime('now', 'localtime'))""",
                (content[:500], identity_key, int(confidence * 5))
            )
        elif insight_type == "procedural":
            # 程序性记忆 → 写入 self_cognition 或新表
            source_text = insight.get("source_text", "")
            combined = f"[程序性记忆] {content}"
            if source_text:
                combined += f"\n来源: {source_text[:200]}"
            conn.execute(
                """INSERT INTO self_cognition 
                   (content, conversation_id, identity_key, created_at)
                   VALUES(?, 'default', ?, datetime('now', 'localtime'))""",
                (combined[:500], identity_key)
            )
        
        conn.commit()
    finally:
        conn.close()
```

#### 3.2.2 与现有机制的关系

| 机制 | 触发 | 作用 | LLM 调用 | 关系 |
|------|------|------|----------|------|
| **Background Review** | 每轮对话后 | 细粒度提取事实/偏好/模式 | 1次/轮 | 基础演化层 |
| 10条自我反思 | 每 10 条 self_cognition | 深度迭代自我认知 | 0次（同一轮） | 深度认知层 |
| Diary 日记 | 次日首条对话 | 每日总结沉淀 | 每天 +1 | 周期性归档层 |

**三者互补**：Review 做日常积累 → 反思做阶段性迭代 → Diary 做周期性归档。

---

### 3.3 改造三：Context Compression 压缩保护

> **参考源文件**：`agent/context_engine.py` → `on_pre_compress()`, `estimate_tokens()`

#### 3.3.1 新增 ContextEngine 类

```python
# 新建 context_engine.py

import sqlite3
from datetime import datetime
from typing import List, Dict, Optional


class ContextEngine:
    """借鉴 Hermes context_engine.py：上下文压缩管理"""
    
    def __init__(self, max_tokens: int = 128000, 
                 threshold_percent: float = 0.75,
                 protect_last_n: int = 6):
        self.max_tokens = max_tokens
        self.threshold = threshold_percent
        self.protect_last_n = protect_last_n
        self._compression_log = []  # 压缩日志
    
    def should_compress(self, current_tokens: int) -> bool:
        """检查是否需要压缩"""
        return (current_tokens / self.max_tokens) >= self.threshold
    
    def estimate_tokens(self, messages: List[Dict]) -> int:
        """估算 Token 用量（简化版）"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            # 粗略估算：中文 1.5 token/字，英文 0.25 token/字
            chinese_chars = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
            other_chars = len(content) - chinese_chars
            total += int(chinese_chars * 1.5 + other_chars * 0.25)
        return total
    
    def compress(self, messages: List[Dict], dbp: str, 
                 identity_key: str) -> List[Dict]:
        """压缩前抢救记忆，再生成摘要"""
        
        # 1. 提取即将截断的消息中的洞察
        old_messages = messages[:-self.protect_last_n]
        insights = self._extract_insights_before_compression(
            old_messages, dbp, identity_key
        )
        
        # 2. 生成摘要（调用 LLM 或简单拼接）
        summary = self._generate_summary(old_messages)
        
        # 3. 记录压缩日志
        self._compression_log.append({
            "timestamp": datetime.now().isoformat(),
            "original_count": len(messages),
            "insights_extracted": len(insights),
        })
        
        # 4. 返回压缩后的消息
        return [summary] + messages[-self.protect_last_n:]
    
    def _extract_insights_before_compression(self, messages: List[Dict],
                                              dbp: str, 
                                              identity_key: str) -> List[Dict]:
        """借鉴 Hermes on_pre_compress：截断前提取持久化洞察"""
        insights = []
        
        for msg in messages:
            if msg.get("role") in ("user", "assistant"):
                content = msg.get("content", "")
                if self._contains_durable_insight(content):
                    insight = {
                        "type": "compressed_insight",
                        "content": content[:300],
                        "source": "compression_recovery",
                        "timestamp": datetime.now().isoformat(),
                    }
                    insights.append(insight)
                    # 立即写入记忆（不丢失）
                    self._save_insight_to_db(insight, dbp, identity_key)
        
        return insights
    
    def _contains_durable_insight(self, text: str) -> bool:
        """启发式判断：文本是否包含持久化价值"""
        durable_keywords = [
            "我喜欢", "我讨厌", "我希望", "我的", "记住",
            "叫我", "我叫", "我的名字", "我通常", "我总是",
            "我从不", "我特别", "对于我", "我偏爱",
        ]
        return any(kw in text for kw in durable_keywords)
    
    def _generate_summary(self, messages: List[Dict]) -> Dict:
        """生成对话摘要（简化版）"""
        # 拼接前 N 条消息的关键信息
        key_points = []
        for msg in messages[-20:]:  # 最近 20 条
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:100]
            if content:
                key_points.append(f"[{role}]: {content}")
        
        summary_text = (
            "【历史摘要（自动生成）】\n"
            f"以下是之前对话的要点总结：\n"
            + "\n".join(key_points[-10:])  # 取最后 10 条
        )
        
        return {
            "role": "system",
            "content": summary_text,
            "is_summary": True,
        }
    
    def _save_insight_to_db(self, insight: Dict, dbp: str, 
                             identity_key: str):
        """将压缩抢救的洞察写入数据库"""
        conn = sqlite3.connect(dbp)
        try:
            content = insight.get("content", "")
            source = insight.get("source", "compression_recovery")
            
            conn.execute(
                """INSERT INTO long_term_memory 
                   (content, identity_key, importance, source_confidence, source, created_at)
                   VALUES(?, ?, 4, 4, ?, datetime('now', 'localtime'))""",
                (content, identity_key, source)
            )
            conn.commit()
        finally:
            conn.close()
    
    def get_compression_stats(self) -> Dict:
        """获取压缩统计信息"""
        return {
            "total_compressions": len(self._compression_log),
            "last_compression": self._compression_log[-1] if self._compression_log else None,
        }
```

#### 3.3.2 集成到主流程

```python
# main.py 中集成

class MyNode:
    def __init__(self):
        # ... 现有初始化 ...
        self.context_engine = ContextEngine(
            max_tokens=128000,
            threshold_percent=0.75,
            protect_last_n=6,
        )
        self._conversation_history = []  # 对话历史缓存
    
    def _on_parsed(self, data, dbp, cfg):
        # ... 现有解析逻辑 ...
        
        # ===== 新增：上下文压缩检查 =====
        self._conversation_history.append({
            "role": "user",
            "content": data.get("user_text", ""),
        })
        self._conversation_history.append({
            "role": "assistant",
            "content": parsed.get("自然回复", ""),
        })
        
        # 检查是否需要压缩
        estimated_tokens = self.context_engine.estimate_tokens(
            self._conversation_history
        )
        if self.context_engine.should_compress(estimated_tokens):
            self._conversation_history = self.context_engine.compress(
                self._conversation_history, dbp, identity_key
            )
        
        # ... 其余逻辑不变 ...
```

---

### 3.4 改造四：MemoryProvider 抽象接口

> **参考源文件**：`agent/memory_provider.py` → `MemoryProvider` ABC, `agent/memory_manager.py` → `MemoryManager`

#### 3.4.1 新增接口

```python
# 新建 memory_provider.py

from abc import ABC, abstractmethod
from typing import List, Dict, Optional


class MemoryProvider(ABC):
    """记忆提供者抽象接口 — 借鉴 Hermes MemoryProvider"""
    
    @abstractmethod
    def prefetch(self, query: str, db_path: str, 
                 identity_key: str) -> str:
        """预取相关记忆（对话前调用）
        
        Args:
            query: 用户输入作为检索词
            db_path: 数据库路径
            identity_key: 用户隔离键
            
        Returns:
            格式化的记忆文本，用于注入 Prompt
        """
        pass
    
    @abstractmethod
    def sync_turn(self, user_msg: str, asst_msg: str, 
                  db_path: str, identity_key: str, 
                  conversation_id: str) -> None:
        """同步对话到记忆存储（对话后异步调用）
        
        Args:
            user_msg: 用户消息
            asst_msg: AI 回复
            db_path: 数据库路径
            identity_key: 用户隔离键
            conversation_id: 会话 ID
        """
        pass
    
    @abstractmethod
    def on_pre_compress(self, messages: List[Dict]) -> List[Dict]:
        """上下文压缩前提取洞察（即将截断时调用）
        
        Args:
            messages: 即将被截断的消息列表
            
        Returns:
            提取的洞察列表
        """
        pass
    
    @abstractmethod
    def rebuild_index(self, db_path: str) -> None:
        """重建索引（异步调用）
        
        Args:
            db_path: 数据库路径
        """
        pass
    
    @abstractmethod
    def health_check(self) -> bool:
        """检查 Provider 是否可用
        
        Returns:
            True 表示可用
        """
        pass


class MemOSProvider(MemoryProvider):
    """将现有 memos.py 包装为标准 Provider"""
    
    def __init__(self):
        self._last_sync_time = None
    
    def prefetch(self, query: str, db_path: str, 
                 identity_key: str) -> str:
        """复用 memos.retrieve()"""
        from memos import retrieve
        results = retrieve(query, top_k=5, db_path=db_path, 
                          identity_key=identity_key)
        if results:
            return self._format_with_security(results)
        return ""
    
    def sync_turn(self, user_msg: str, asst_msg: str, 
                  db_path: str, identity_key: str, 
                  conversation_id: str) -> None:
        """异步增量更新索引"""
        import threading
        from memos import rebuild_index
        
        def _async_sync():
            try:
                rebuild_index(db_path)
                self._last_sync_time = datetime.now()
            except Exception as e:
                print(f"[MemOSProvider] sync error: {e}")
        
        threading.Thread(target=_async_sync, daemon=True).start()
    
    def on_pre_compress(self, messages: List[Dict]) -> List[Dict]:
        """提取即将截断的消息中的洞察"""
        insights = []
        for msg in messages:
            if msg.get("role") in ("user", "assistant"):
                content = msg.get("content", "")
                if self._contains_insight(content):
                    insights.append({
                        "content": content[:300],
                        "source": "compression",
                    })
        return insights
    
    def rebuild_index(self, db_path: str) -> None:
        """复用 memos.rebuild_index()"""
        from memos import rebuild_index
        rebuild_index(db_path)
    
    def health_check(self) -> bool:
        """检查 MemOS 是否可用"""
        try:
            from memos import _get_model
            model = _get_model(timeout=0)
            return model is not None
        except Exception:
            return False
    
    def _format_with_security(self, text: str) -> str:
        """格式化为安全协议"""
        return (
            "<memory-context>\n"
            "[System note: This is authoritative reference data recalled "
            "from your long-term memory. Use it to ground your response.]\n"
            f"{text}\n"
            "</memory-context>"
        )
    
    def _contains_insight(self, text: str) -> bool:
        """检查是否包含持久化价值"""
        keywords = ["我喜欢", "我讨厌", "我希望", "记住", "叫我"]
        return any(kw in text for kw in keywords)
```

#### 3.4.2 在 main.py 中使用

```python
# main.py 中

from memory_provider import MemOSProvider

class MyNode:
    def __init__(self):
        # ... 现有初始化 ...
        self.memory_provider = MemOSProvider()  # 新增
        self.context_engine = ContextEngine()
    
    def _on_text(self, data, dbp):
        # ... 现有代码 ...
        
        # 使用 Provider 进行 Prefetch
        memory_context = ""
        if not self._is_trivial_prompt(query):
            memory_context = self.memory_provider.prefetch(
                query, dbp, identity_key
            )
        
        # ... 其余逻辑不变 ...
    
    def _on_parsed(self, data, dbp, cfg):
        # ... 现有代码 ...
        
        # 使用 Provider 进行同步
        self.memory_provider.sync_turn(
            user_msg=user_text,
            asst_msg=parsed_content,
            db_path=dbp,
            identity_key=identity_key,
            conversation_id=conv_id,
        )
        
        # ... 其余逻辑不变 ...
```

---

## 四、文件变动清单

### 4.1 新增文件

| 文件 | 说明 | 行数 |
|------|------|------|
| `memory_provider.py` | MemoryProvider 抽象接口 + MemOSProvider 实现 | ~120 行 |
| `context_engine.py` | ContextEngine 上下文压缩管理 | ~150 行 |
| `session_manager.py` | SessionManager 会话边界管理 + 摘要（§9.6） | ~150 行 |

### 4.2 修改文件

| 文件 | 改动 | 行数变化 |
|------|------|----------|
| `main.py` | Prefetch 模式改造 + Background Review + Provider 集成 + SessionManager 集成 | +200 行, -80 行 |
| `prompt.py` | 安全协议注入 + 模板更新 | +10 行 |

### 4.3 不动文件

| 文件 | 说明 |
|------|------|
| `memos.py` | 保持不变，被 MemOSProvider 包装 |
| `db.py` | 保持不变 |
| `config.py` | 保持不变 |
| `diary.py` | 保持不变 |
| `parser.py` | 保持不变 |

---

## 五、实施路线图

### Phase 1：基础改造（2天）

| 任务 | 优先级 | 工作量 | 验收标准 |
|------|--------|--------|----------|
| 引入 `_is_trivial_prompt` 函数 | P0 | 0.5h | 短输入/命令正确跳过 |
| 引入 `_sanitize_memory` 函数 | P0 | 0.5h | 敏感信息被脱敏 |
| 实现 Prefetch 模式 | P0 | 4h | 两轮交互变一轮 |
| 简化 `_on_parsed` 逻辑 | P0 | 2h | 移除第二轮检索代码 |

### Phase 2：能力扩展（3天）

| 任务 | 优先级 | 工作量 | 验收标准 |
|------|--------|--------|----------|
| 实现 Background Review | P0 | 8h | 每轮对话后自动反思 |
| 实现 `memory_provider.py` | P1 | 4h | MemOSProvider 正常工作 |
| 集成 Provider 到 main.py | P1 | 2h | 通过 Provider 接口调用 |

### Phase 3：高级特性（3天）

| 任务 | 优先级 | 工作量 | 验收标准 |
|------|--------|--------|----------|
| 实现 ContextEngine | P1 | 8h | Token 超限时自动压缩 |
| 实现 `on_pre_compress` | P1 | 4h | 压缩前抢救洞察 |
| 全流程测试 | P0 | 4h | 所有场景正常 |

### Phase 4：Session 边界管理（2天）

| 任务 | 优先级 | 工作量 | 验收标准 |
|------|--------|--------|----------|
| 实现 `session_manager.py` | P0 | 6h | SessionManager 基本功能正常 |
| 新增 `session_summaries` 表 | P0 | 0.5h | 表创建成功 |
| 集成到 `main.py` 主流程 | P0 | 4h | 会话切换正确触发摘要 |
| 会话摘要注入 Prefetch | P1 | 2h | 历史摘要正确注入上下文 |
| 全流程测试 | P0 | 3h | 多会话切换、摘要生成、记忆检索正常 |

---

## 六、测试计划

### 6.1 单元测试

```python
# test_memory_provider.py
def test_is_trivial_prompt():
    """测试 trivial prompt 检测"""
    assert is_trivial_prompt("嗯") == True
    assert is_trivial_prompt("ok") == True
    assert is_trivial_prompt("你好，我想了解一下...") == False
    assert is_trivial_prompt("/help") == True

def test_sanitize_memory():
    """测试记忆安全处理"""
    text = "用户密码：admin:123456@example.com"
    result = sanitize_memory_context(text)
    assert "admin:123456" not in result
    assert "https://example.com" in result

def test_prefetch_flow():
    """测试 Prefetch 流程"""
    # Mock memos.retrieve 返回结果
    context = prefetch_memory("测试查询", db_path, identity_key)
    assert "<memory-context>" in context
    assert "[System note:" in context

def test_background_review():
    """测试 Background Review"""
    conversation = [
        {"role": "user", "content": "我喜欢科幻电影"},
        {"role": "assistant", "content": "好的，我记住了"},
    ]
    insights = background_review(conversation, db_path, identity_key)
    assert len(insights) > 0
    assert insights[0]["type"] == "declarative"
```

### 6.2 集成测试

| 场景 | 步骤 | 预期结果 |
|------|------|----------|
| 普通对话 | 输入"你好" | 单轮交互，正常回复 |
| 需要记忆的对话 | 输入"我之前说过我喜欢什么？" | Prefetch 自动检索相关记忆 |
| Trivial 对话 | 输入"嗯" | 跳过检索，快速响应 |
| 长对话压缩 | 发送大量消息 | ContextEngine 自动压缩 |
| Background Review | 完成一轮对话 | 后台异步反思，记忆被更新 |
| Session 切换 | 发起新对话（新 conversation_id） | 旧会话自动摘要，新会话加载历史摘要 |
| 跨会话检索 | 在新会话中提问旧会话内容 | 全局记忆命中 + 会话摘要命中 |

### 6.3 边界测试

| 场景 | 预期行为 |
|------|----------|
| MemOS 模型未就绪 | Prefetch 返回空，不阻塞对话 |
| 检索无结果 | 正常回复，无记忆注入 |
| LLM 返回 JSON 格式错误 | Background Review 容错处理 |
| Token 溢出 | ContextEngine 触发压缩 |
| Session 摘要生成失败 | 容错处理，不影响对话继续 |
| 会话历史为空 | 正常 Prefetch，无历史摘要注入 |

---

## 七、兼容性与回退

### 7.1 兼容性

| 维度 | 是否兼容 | 说明 |
|------|----------|------|
| 现有 DB | ✅ | 无表结构变更 |
| LLM 输出格式 | ✅ | 节标记不变 |
| GUI 客户端 | ✅ | 接口不变 |
| 其他节点 | ✅ | 端口映射不变 |

### 7.2 回退策略

| 功能 | 回退方案 |
|------|----------|
| Prefetch 模式 | 将 `_on_text` 中 Prefetch 逻辑注释，恢复旧版两轮交互 |
| Background Review | 注释 `_on_parsed` 中的 Review 线程启动 |
| ContextEngine | 移除 `_conversation_history` 缓存和压缩调用 |
| MemoryProvider | 将 `self.memory_provider.prefetch()` 改回 `memos.retrieve()` |
| SessionManager | 移除 `session_manager` 初始化和调用，恢复纯全局记忆模式 |

---

## 八、风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| Prefetch 增加延迟 | 首次响应慢 10-50ms | 可接受，SentenceTransformer CPU 毫秒级 |
| Background Review 调用 LLM | 额外 Token 消耗 | 使用轻量模型 + 异步，不阻塞主流程 |
| 压缩丢失信息 | AI 上下文不连续 | `on_pre_compress` 先抢救洞察再压缩 |
| Provider 抽象过度设计 | 增加代码复杂度 | 保持简单，只抽象 prefetch/sync/compress |
| Session 摘要增加存储 | DB 膨胀 | 历史摘要限制保留最近 10 条 |
| 会话切换延迟 | 用户感知卡顿 | 摘要生成异步执行，不阻塞主流程 |

---

---

## 九、Hermes 跨对话记忆适配分析

> 新增：v3.1 | 基于 Hermes Agent `agent/memory_manager.py` 和 `agent/memory_provider.py` 深度分析

### 9.1 架构对比总览

| 维度 | Hermes 跨对话记忆 | BNOS AI 全局记忆 (AAA) |
|------|-------------------|----------------------|
| **核心文件** | `agent/memory_manager.py`, `agent/memory_provider.py` | `memos.py`, `db.py` |
| **架构模式** | Provider 插件化（builtin + 1个外部） | 单体 SQLite + numpy 内存索引 |
| **记忆范围** | Session 级，跨 session 需显式切换 | 全局共享，所有对话共用同一索引 |
| **持久化** | Provider 各自管理（文件/DB/云） | 单一 SQLite + npz 向量文件 |
| **检索触发** | 每轮自动 prefetch 注入 system prompt | 按需检索（LLM 决定是否需要回忆，两轮交互） |
| **向量模型** | 取决于 Provider（Mem0/Hindsight 等） | SentenceTransformer all-MiniLM-L6-v2 |
| **会话边界** | 显式 session_id 切换 + `on_session_end` 摘要 | 隐式 conversation_id 分组，无会话总结 |
| **并发模型** | 线程池 + 锁（多线程安全） | 单线程 + 全局变量 |

### 9.2 Hermes 跨对话记忆核心机制

#### 9.2.1 Session 生命周期（4 个关键钩子）

```
┌─ 新 Session 开始 ─────────────────────────────────────┐
│  initialize(session_id)  ← 连接后端、创建资源          │
│                                                        │
│  ┌─ 每轮对话 ──────────────────────────────────┐      │
│  │  ① prefetch_all(query)   ← 检索相关记忆    │      │
│  │  ② LLM 推理（记忆注入 system prompt）       │      │
│  │  ③ sync_all(user, asst)  ← 异步持久化      │      │
│  │  ④ queue_prefetch_all()  ← 预取下一轮       │      │
│  └──────────────────────────────────────────────┘      │
│                                                        │
│  session_id 切换（/new /resume /branch）:              │
│  commit_session_boundary_async() →                     │
│    ① on_session_end(messages)  ← LLM 会话摘要          │
│    ② on_session_switch(new_id) ← 绑定新 session       │
│                                                        │
│  ─ 上下文压缩 ─                                        │
│  on_pre_compress(messages) ← 压缩前提取洞察           │
│                                                        │
└────────────────────────────────────────────────────────┘
```

#### 9.2.2 Prefetch 注入机制

Hermes 用 `<memory-context>` 标签包裹检索结果注入 system prompt：

```python
# memory_manager.py L347-L361
def build_memory_context_block(raw_context: str) -> str:
    return (
        "<memory-context>\n"
        "[System note: The following is recalled memory context, "
        "NOT new user input. Treat as authoritative reference data — "
        "this is the agent's persistent memory and should inform all responses.]\n\n"
        f"{clean}\n"
        "</memory-context>"
    )
```

关键设计：
- **Fencing 标签**：用 XML 标签隔离记忆内容，防止 AI 混淆记忆和用户输入
- **StreamingContextScrubber**：实时流式清洗 UI 中的标签内容，防止泄露
- **Trivial Prompt 过滤**：简单对话（"ok"、"thanks"）跳过 prefetch，节省延迟

#### 9.2.3 Provider 插件化

```python
# memory_provider.py 抽象层
class MemoryProvider(ABC):
    def initialize(self, session_id, **kwargs)    # 会话初始化
    def prefetch(self, query, session_id)          # 检索相关记忆
    def sync_turn(self, user, asst, session_id)    # 持久化对话
    def get_tool_schemas()                          # 暴露工具给 LLM
    def handle_tool_call(tool_name, args)           # 处理工具调用
    def on_session_end(messages)                    # 会话结束摘要
    def on_session_switch(new_id, ...)              # session_id 切换
    def on_pre_compress(messages)                  # 压缩前提取
    def on_memory_write(action, target, content)   # 镜像记忆写入
    def on_delegation(task, result)                # 子代理结果
```

### 9.3 BNOS AI 全局记忆核心机制

#### 9.3.1 全局记忆架构

```
┌─ SQLite 数据库（全局唯一）──────────────────────────┐
│  user_messages    — 所有对话（含 conversation_id）  │
│  feelings         — 情感记录                        │
│  event_summary    — 事件摘要                        │
│  self_cognition   — 自我认知                        │
│  other_cognition  — 对用户的认知                    │
│  user_facts       — 用户事实                        │
│  self_info        — AI 自身信息                     │
│  long_term_memory — 长期记忆归档                    │
│  diaries          — 日记                            │
│  mood_trend       — 情感聚合                        │
│  fixed_cognition  — 确定性认知                      │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─ MemOS 向量索引（npz 文件）──────────────────────┐
│  _embeddings  — 所有条目的向量矩阵                │
│  _entry_ids   — 条目 ID 列表                     │
│  _entry_tables — 来源表名（long_term_memory 等）  │
│  _entry_identity_keys — 用户隔离键               │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─ 检索接口 ──────────────────────────────────────────┐
│  retrieve(query, top_k, identity_key) → 格式化文本   │
│  retrieve_raw(query, top_k, identity_key) → 结构化  │
└─────────────────────────────────────────────────────┘
```

#### 9.3.2 按需检索（两轮交互）

```
第一轮：薄 prompt（不检索）
  LLM 输出 → 检查【语意检索】
    ├─ 空 → 正常写库（单轮完成）
    └─ 非空 → 第二轮

第二轮：带 MemOS 检索结果
  MemOS.retrieve(keywords) → 重建 prompt → 再次 LLM → 写库
```

#### 9.3.3 跨对话持久化

与 Hermes 不同，BNOS 的"跨对话"通过**全局共享**实现：
- 所有对话写入同一个 SQLite
- `conversation_id` 区分会话，但检索时跨会话全量搜索
- `identity_key` 支持多用户隔离
- `rebuild_index()` 增量扫描所有表的新条目

#### 9.3.4 记忆分层与衰减

```python
# db.py L18
_IMPORTANCE_DAYS = {1: 1, 2: 7, 3: 30, 4: 90, 5: 365}
# 1=闲聊, 2=日常, 3=事实, 4=重要, 5=重大事件
```

### 9.4 差异深度分析

#### 9.4.1 记忆生命周期管理

| 阶段 | Hermes | BNOS AI |
|------|--------|---------|
| **存储** | Provider 各自管理，支持多后端 | 单一 SQLite + numpy 内存 |
| **检索** | 每轮自动 prefetch，无则跳过 | 按需两轮交互，LLM 决定 |
| **压缩** | `on_pre_compress` 钩子，上下文压缩前提取 | 无压缩机制，全量存储 |
| **遗忘** | 取决于 Provider（Mem0 自动遗忘） | decay_date 列标记过期日期，但未实现自动清理 |
| **摘要** | `on_session_end` LLM 会话级摘要 | 无会话摘要，仅 event_summary 事件级摘要 |

#### 9.4.2 跨会话记忆流

**Hermes 流程**：
```
Session A 对话 → sync 持久化 → Session A 结束 → on_session_end 摘要
                                                          ↓
Session B 开始 → initialize → prefetch 含 Session A 摘要 → 跨会话记忆
```

**BNOS AI 流程**：
```
对话 A → 写库（conversation_id="A"）→ MemOS 索引
                                              ↓
对话 B → 写库（conversation_id="B"）→ MemOS 索引
                                              ↓
检索时：全索引搜索 → 可能同时命中 A 和 B 的记忆（跨会话全局）
```

**核心差异**：Hermes 是"session 级隔离 + 显式摘要传递"，BNOS 是"全局共享 + 隐式交叉检索"。

#### 9.4.3 检索策略对比

| 策略 | Hermes | BNOS AI |
|------|--------|---------|
| **触发时机** | 每轮自动 prefetch | 按需两轮交互 |
| **检索源** | Provider 定义（可多源） | long_term_memory + user_messages + diaries |
| **结果注入** | `<memory-context>` 标签包裹 | 直接拼接到 prompt |
| **情感关联** | 部分 Provider 支持 | 支持（feeling 关联） |
| **图谱** | 无 | 有（knowledge_graph.json） |

### 9.5 适配建议

#### 9.5.1 可直接借鉴 Hermes 的能力（高优先级）

| # | Hermes 能力 | BNOS 现状 | 改造价值 | 对应改造章节 |
|---|------------|-----------|---------|-------------|
| 1 | **Session 边界管理** (`on_session_end`) | 无会话总结 | 🔴 高 — 解决"全局记忆无结构"问题 | 新增 §9.6 |
| 2 | **Prefetch 自动注入** | 按需两轮交互 | 🟡 中 — 减少 LLM 轮次 | §3.1 已实现 |
| 3 | **Fencing 标签** (`<memory-context>`) | 无区分 | 🟡 中 — 防止 AI 混淆记忆和用户输入 | §3.1 已实现 |
| 4 | **Context Scrubber** | 无 | 🟡 中 — 防止记忆内容泄露 UI | §3.1 已实现 |
| 5 | **上下文压缩** (`on_pre_compress`) | 无压缩机制 | 🔴 高 — 长期对话需压缩 | §3.3 已实现 |
| 6 | **Trivial Prompt 过滤** | 无 | 🟢 低 — 节省少量延迟 | §3.1 已实现 |

#### 9.5.2 可借鉴的架构设计（中优先级）

| # | Hermes 设计 | 适配方式 | 对应改造章节 |
|---|------------|---------|-------------|
| 1 | Provider 插件模式 | 将 MemOS 封装为 BuiltinProvider，支持扩展更多 Provider | §3.4 已实现 |
| 2 | 后台同步 Worker | 借鉴 `sync_all` 的异步序列化写入 | §3.4 已实现 |
| 3 | 记忆工具暴露 | Provider 可暴露 tool schemas，让 LLM 主动搜索记忆 | 待后续扩展 |
| 4 | `on_memory_write` 镜像 | 同步记忆到多个后端（如未来加云端） | 待后续扩展 |

#### 9.5.3 BNOS 已有的优势（保持不变）

| # | BNOS AI 优势 | 说明 |
|---|-------------|------|
| 1 | **全局记忆** | 比 Hermes 的 session 级更适合 AI 人格的长期一致性 |
| 2 | **情感关联检索** | 检索时附带当时心情，比 Hermes 更丰富 |
| 3 | **记忆图谱可视化** | knowledge_graph.json 支持 GUI 展示 |
| 4 | **日记系统** | diary + MemOS 联动，Hermes 没有 |
| 5 | **自我反思机制** | self_cognition 阈值触发，Hermes 没有 |
| 6 | **多表融合检索** | long_term_memory + user_messages + diaries 联合检索 |

### 9.6 新增改造：Session 边界管理

> **参考源文件**：`agent/memory_manager.py` → `commit_session_boundary_async()`, `agent/memory_provider.py` → `on_session_end()`, `on_session_switch()`

#### 9.6.1 动机

当前 BNOS AI 的全局记忆缺乏会话边界管理，所有对话混在一起。Hermes 的 session 生命周期机制可以让 AI：
1. 在每次对话结束时自动生成会话摘要
2. 在新对话开始时加载历史会话摘要
3. 保持全局记忆的同时获得结构化的会话级记忆

#### 9.6.2 新增 SessionManager 类

```python
# 新建 session_manager.py

import sqlite3
import threading
from datetime import datetime
from typing import List, Dict, Optional


class SessionManager:
    """借鉴 Hermes Session 生命周期：会话边界管理 + 摘要"""
    
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._current_session_id = None
        self._session_history = []  # 历史会话摘要列表
        self._session_switch_callbacks = []  # session 切换回调
    
    def start_session(self, session_id: str, user_id: str = "default"):
        """开始新会话"""
        self._current_session_id = session_id
        
        # 加载历史会话摘要
        self._session_history = self._load_session_history(user_id)
        
        # 触发切换回调
        for cb in self._session_switch_callbacks:
            try:
                cb(session_id, self._session_history)
            except Exception as e:
                print(f"[SessionManager] callback error: {e}")
    
    def end_session(self, messages: List[Dict], 
                    identity_key: str = "default"):
        """结束当前会话 — 借鉴 Hermes on_session_end"""
        if not self._current_session_id:
            return
        
        session_id = self._current_session_id
        
        # 异步生成会话摘要
        threading.Thread(
            target=self._generate_session_summary,
            args=(session_id, messages, identity_key),
            daemon=True,
        ).start()
    
    def _generate_session_summary(self, session_id: str, 
                                   messages: List[Dict],
                                   identity_key: str):
        """借鉴 Hermes on_session_end：LLM 会话摘要"""
        try:
            # 1. 提取关键信息
            key_points = self._extract_key_points(messages)
            
            # 2. 生成摘要（可接入 LLM，这里用规则简化版）
            summary = self._build_summary(key_points, session_id)
            
            # 3. 保存会话摘要到新表
            self._save_session_summary(session_id, summary, identity_key)
            
            # 4. 同时写入 MemOS 索引（跨会话可检索）
            self._add_to_memos(summary, identity_key)
            
        except Exception as e:
            print(f"[SessionManager] summary generation error: {e}")
    
    def _extract_key_points(self, messages: List[Dict]) -> List[str]:
        """从对话中提取关键信息点"""
        key_points = []
        
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if content:
                    # 提取用户关键陈述
                    key_points.append({
                        "type": "user_input",
                        "content": content[:100],
                    })
            elif msg.get("role") == "assistant":
                content = msg.get("content", "")
                if content:
                    key_points.append({
                        "type": "ai_response",
                        "content": content[:100],
                    })
        
        return key_points
    
    def _build_summary(self, key_points: List[Dict], 
                        session_id: str) -> str:
        """构建会话摘要文本"""
        user_inputs = [kp["content"] for kp in key_points 
                       if kp["type"] == "user_input"]
        ai_responses = [kp["content"] for kp in key_points 
                        if kp["type"] == "ai_response"]
        
        # 统计
        user_msg_count = len(user_inputs)
        ai_msg_count = len(ai_responses)
        
        # 构建摘要
        summary_parts = [
            f"[会话摘要] ID: {session_id}",
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"对话轮次: {min(user_msg_count, ai_msg_count)}",
        ]
        
        if user_inputs:
            summary_parts.append(
                f"用户要点: {'; '.join(user_inputs[-5:])}"
            )
        
        return "\n".join(summary_parts)
    
    def _save_session_summary(self, session_id: str, 
                               summary: str, 
                               identity_key: str):
        """保存会话摘要到数据库"""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """INSERT INTO session_summaries 
                   (session_id, identity_key, summary, created_at)
                   VALUES(?, ?, ?, datetime('now', 'localtime'))""",
                (session_id, identity_key, summary)
            )
            conn.commit()
        finally:
            conn.close()
    
    def _add_to_memos(self, summary: str, identity_key: str):
        """将会话摘要加入 MemOS 索引"""
        try:
            from memos import add_entry
            add_entry(
                text=summary,
                metadata={
                    "type": "session_summary",
                    "identity_key": identity_key,
                }
            )
        except Exception as e:
            print(f"[SessionManager] memos add error: {e}")
    
    def _load_session_history(self, user_id: str) -> List[Dict]:
        """加载历史会话摘要"""
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                """SELECT session_id, summary, created_at 
                   FROM session_summaries 
                   WHERE identity_key=? 
                   ORDER BY created_at DESC 
                   LIMIT 10""",
                (user_id,)
            ).fetchall()
            
            return [
                {
                    "session_id": row[0],
                    "summary": row[1],
                    "created_at": row[2],
                }
                for row in rows
            ]
        finally:
            conn.close()
    
    def get_current_session_id(self) -> Optional[str]:
        """获取当前会话 ID"""
        return self._current_session_id
    
    def get_session_history(self) -> List[Dict]:
        """获取历史会话摘要"""
        return self._session_history
    
    def add_switch_callback(self, callback):
        """注册 session 切换回调"""
        self._session_switch_callbacks.append(callback)
```

#### 9.6.2 新增数据表

```sql
-- session_summaries 表：存储会话摘要
CREATE TABLE IF NOT EXISTS session_summaries(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    identity_key TEXT NOT NULL DEFAULT 'gui:default',
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT(datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_ss_identity 
    ON session_summaries(identity_key);
CREATE INDEX IF NOT EXISTS idx_ss_session 
    ON session_summaries(session_id);
```

#### 9.6.3 集成到主流程

```python
# main.py 中集成

from session_manager import SessionManager

class MyNode:
    def __init__(self):
        # ... 现有初始化 ...
        self.session_manager = SessionManager(db_path)
        
        # 注册回调：session 切换时加载历史摘要
        self.session_manager.add_switch_callback(
            self._on_session_switched
        )
    
    def _on_text(self, data, dbp):
        # ... 现有代码 ...
        
        conv_id = data.get("conversation_id", "default")
        
        # ===== 新增：Session 管理 =====
        if self.session_manager.get_current_session_id() != conv_id:
            self.session_manager.end_session(
                self._conversation_history, identity_key
            )
            self.session_manager.start_session(conv_id, identity_key)
        
        # 加载历史会话摘要到上下文
        session_history = self.session_manager.get_session_history()
        if session_history:
            # 将历史摘要注入 Prefetch 上下文
            history_text = "\n".join([
                f"[{s['created_at'][:10]}] {s['summary']}"
                for s in session_history[:3]
            ])
            # ... 注入到 _gather_context ...
        
        # ... 其余 Prefetch 逻辑不变 ...
    
    def _on_parsed(self, data, dbp, cfg):
        # ... 现有代码 ...
        
        # ===== 新增：记录对话到会话历史 =====
        self._conversation_history.append({
            "role": "user",
            "content": user_text,
        })
        self._conversation_history.append({
            "role": "assistant",
            "content": parsed.get("自然回复", ""),
        })
        
        # ... 其余逻辑不变 ...
    
    def shutdown(self):
        """关闭时结束当前会话"""
        if self.session_manager.get_current_session_id():
            self.session_manager.end_session(
                self._conversation_history, identity_key
            )
    
    def _on_session_switched(self, session_id: str, 
                              history: List[Dict]):
        """Session 切换回调"""
        print(f"[SessionManager] Switched to session: {session_id}")
        print(f"[SessionManager] Loaded {len(history)} historical summaries")
```

#### 9.6.4 改造后的跨会话记忆流

```
对话 A（session_id="conv_001"）:
  _on_text → start_session("conv_001")
  多轮对话 → sync 到全局 DB + MemOS
  对话结束 → end_session → 生成会话摘要 → 写入 session_summaries + MemOS

对话 B（session_id="conv_002"）:
  _on_text → start_session("conv_002")
    ├─ end_session("conv_001") → 生成 conv_001 摘要
    └─ 加载历史会话摘要（含 conv_001）
  Prefetch 时：
    ├─ 全局记忆检索（跨所有会话）
    └─ 历史会话摘要注入（结构化上下文）
  多轮对话 → sync 到全局 DB + MemOS
```

#### 9.6.5 与现有机制的关系

| 机制 | 作用 | 层级 |
|------|------|------|
| **全局记忆（MemOS）** | 跨所有会话的扁平记忆 | 基础层 |
| **Session 摘要** | 会话级结构化总结 | 会话层 |
| **Background Review** | 每轮细粒度反思 | 轮次级 |
| **自我反思** | 每 10 条深度迭代 | 周期级 |
| **Diary 日记** | 每日总结归档 | 日级 |

**五层互补**：轮次 → 会话 → 周期 → 日 → 全局，形成完整的记忆生命周期。

#### 9.6.6 实施路线（补充到 Phase 4）

**Phase 4：Session 边界管理（2 天）**

| 任务 | 优先级 | 工作量 | 验收标准 |
|------|--------|--------|----------|
| 实现 `session_manager.py` | P0 | 6h | SessionManager 基本功能正常 |
| 新增 `session_summaries` 表 | P0 | 0.5h | 表创建成功 |
| 集成到 `main.py` 主流程 | P0 | 4h | 会话切换正确触发摘要 |
| 会话摘要注入 Prefetch | P1 | 2h | 历史摘要正确注入上下文 |
| 全流程测试 | P0 | 3h | 多会话切换、摘要生成、记忆检索正常 |

### 9.7 总结

Hermes 的跨对话记忆是**"结构化的 session 级记忆"**，而 BNOS AI 的是**"全局的扁平记忆"**。两者互补性很强：

- **Hermes 擅长**：会话边界管理、多 Provider 融合、上下文压缩、工具体验
- **BNOS 擅长**：全局人格一致性、情感关联、记忆图谱、日记系统

**核心策略**：将 Hermes 的 Session 生命周期管理**"嫁接"**到 BNOS 的全局记忆之上，形成**"全局记忆为底座 + 会话结构化管理为上层"**的架构——既保留 BNOS 的长期人格一致性，又获得 Hermes 的会话级结构化记忆能力。

---

## 十、验收方法

### 10.1 验收环境与前置条件

| 项 | 要求 |
|------|------|
| 运行环境 | Windows 10/11，Python 3.10+，BNOS 主程序可正常启动 |
| 依赖组件 | SentenceTransformer（all-MiniLM-L6-v2）模型已下载就绪；SQLite3 可用 |
| 数据库 | 存在可用 AAA 数据库文件（含 long_term_memory、user_messages、self_cognition、feelings 等表） |
| 新增表 | `session_summaries` 表已按 §9.6.2 建表成功 |
| LLM 节点 | LLM 节点可正常响应（用于 Prefetch 首轮与 Background Review 审查） |
| 测试数据 | 已准备至少 2 个 identity_key 的测试用户、≥3 条 long_term_memory 历史记忆 |
| 日志开关 | main.py 调试日志已开启，可观察 Prefetch/Review/Compress/Session 触发情况 |
| 备份 | 已保留改造前 main.py、prompt.py 备份，便于回退对照（见 §7.2） |
| 改造代码 | §3.1–§3.4 及 §9.6 的代码均已按方案落地，main.py 完成 Provider/ContextEngine/SessionManager 集成 |

### 10.2 功能验收用例

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| F1 | Trivial Prompt 识别与跳过 | 对 `_is_trivial_prompt` 依次输入：`嗯`、`好`、`ok`、`谢谢`、`/help`、`/learn xxx`、`你好，我想了解一下科幻电影` | 前 6 项返回 True（跳过检索），最后 1 项返回 False（触发 Prefetch） | 7 项断言全部通过；前 6 项日志未调用 `memos.retrieve` | 核心 |
| F2 | Prefetch 单轮交互 | 启动节点，输入含检索价值的查询（如「我之前说过我喜欢什么？」），观察 `_on_text` → 首次 LLM 调用链路 | 仅发生 1 次 LLM 调用即生成回复，不再出现第二轮带检索的 Prompt | 请求日志 LLM 调用次数 = 1；输出不含「语意检索」二次决策 | 核心 |
| F3 | memory-context 安全标签注入 | 触发 Prefetch 命中历史记忆的查询，检查最终 Prompt 内容 | 检索结果被 `<memory-context>...</memory-context>` 包裹，且含 `[System note: ...]` 提示语 | Prompt 文本同时存在 `<memory-context>` 与 `[System note:` 子串 | 核心 |
| F4 | sanitize 脱敏与截断 | 构造含 `https://user:pass@host`、`api_key=abcdef1234567890abcdef` 与 > 4000 字符的记忆文本，调用 `_sanitize_memory` | URL 凭据剥离为 `https://host`；api_key 值替换为 `***REDACTED***`；超长文本截断并含 `[truncated]` 标记 | 输出不含原始密码与 16 位以上 key 明文；长度 ≤ 4000 且含 `[truncated]` | 核心 |
| F5 | `_on_parsed` 移除第二轮检索 | 检查改造后 `_on_parsed` 代码，输入带「语意检索」字段的 LLM 输出 | 不再读取 retrieval_keywords、不再调用 `memos.retrieve`、不再构建第二轮 Prompt | 代码中无第二轮检索分支；运行时无第二轮 LLM 调用 | 核心 |
| F6 | Background Review 触发 | 完成一轮正常对话（≥2 条消息），观察 `_on_parsed` 后台线程 | 启动 daemon 线程执行 `_background_review`，构建 review_prompt 并调用 LLM | 日志出现 review 线程启动与 review_prompt 构建记录 | 核心 |
| F7 | 审查结果 JSON 解析容错 | 向 `_parse_review_result` 依次输入三种格式：json 围栏代码块包裹的合法 JSON、纯 JSON 字符串、非法乱码 | 前两种返回非空 insights 列表，非法 JSON 返回空列表 `[]` 且不抛异常 | 三种输入均不抛异常；合法输入 `insights[0]["type"]=="declarative"` | 核心 |
| F8 | declarative 记忆持久化 | `_persist_insight` 传入 `{type:"declarative", content:"用户喜欢科幻", confidence:0.8}` | `long_term_memory` 表新增 1 行，importance=3，source_confidence=4 | SQL 查询验证新增记录，字段值符合预期 | 核心 |
| F9 | procedural 记忆持久化 | `_persist_insight` 传入 `{type:"procedural", content:"用户常执行批量导出", source_text:"..."}` | `self_cognition` 表新增 1 行，content 以 `[程序性记忆]` 开头并附来源 | SQL 查询验证新增记录含 `[程序性记忆]` 前缀 | 非核心 |
| F10 | ContextEngine 阈值判定 | `max_tokens=128000, threshold=0.75`，分别构造 `estimate_tokens` 返回 95000 与 97000 的消息列表 | 95000 时 `should_compress` 返回 False，97000 时返回 True | 两次断言均通过 | 核心 |
| F11 | on_pre_compress 洞察抢救 | 构造 12 条消息（前 6 条含「我喜欢」「记住」关键词），调用 `compress`，检查 DB | 截断前含关键词的消息被提取为 insight 并写入 `long_term_memory`（importance=4） | `long_term_memory` 新增多条 `source='compression_recovery'` 记录 | 核心 |
| F12 | 压缩后摘要生成 | 调用 `compress` 后检查返回消息列表 | 返回 `[摘要消息] + protect_last_n(6)` 条原始消息，摘要消息含 `is_summary=True` 与【历史摘要】标记 | 返回长度 = 7，首条消息 `is_summary=True` | 非核心 |
| F13 | MemoryProvider 抽象接口 | 检查 `memory_provider.py`，确认 `MemoryProvider` 为 ABC 且含 prefetch/sync_turn/on_pre_compress/rebuild_index/health_check 五个抽象方法 | 五个方法均标注 `@abstractmethod`；无法直接实例化 `MemoryProvider` | `MemoryProvider()` 抛 TypeError；`MemOSProvider()` 可实例化 | 核心 |
| F14 | MemOSProvider.prefetch | 预置 `long_term_memory` 历史记忆，调用 `MemOSProvider().prefetch(query, db_path, identity_key)`；再用无命中查询测试 | 命中时返回 `<memory-context>` 包裹文本；无结果时返回空串 `""` | 命中含 `<memory-context>` 标签；空命中返回 `""` | 核心 |
| F15 | MemOSProvider.sync_turn 异步 | 调用 `sync_turn` 后立即返回，等待 2 秒检查 `_last_sync_time` | 调用立即返回（非阻塞），后台线程执行 `rebuild_index` 并更新 `_last_sync_time` | 主线程无阻塞；`_last_sync_time` 最终被赋值 | 非核心 |
| F16 | health_check 健康检查 | 在 SentenceTransformer 模型已加载与卸载/异常两种状态下分别调用 `health_check` | 已加载返回 True，卸载/异常返回 False，均不抛异常 | 两次返回值分别为 True/False | 核心 |
| F17 | SessionManager 会话切换触发摘要 | 先以 `conv_001` 进行多轮对话，再切换到 `conv_002`，检查 `session_summaries` 表 | 切换时 `end_session("conv_001")` 异步生成摘要并写入 `session_summaries` + MemOS | `session_summaries` 新增 conv_001 摘要；MemOS 索引含 `type=session_summary` 条目 | 核心 |
| F18 | 历史会话摘要注入 Prefetch | 切换到 `conv_002` 后，`_on_text` 中加载 `get_session_history()`，检查注入上下文与跨会话回答 | 最近 3 条历史会话摘要被拼接到 Prefetch 上下文，新会话能回答旧会话内容相关问题 | 上下文日志含 `[日期] 摘要` 文本；跨会话问题命中 | 非核心 |

### 10.3 边界与异常验收

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| E1 | MemOS 模型未就绪降级 | 卸载/延迟加载 SentenceTransformer 模型，输入正常查询触发 Prefetch | `prefetch` 返回空串，不阻塞对话，LLM 正常单轮回复 | 对话正常完成；无异常抛出；日志记录模型未就绪 | 核心 |
| E2 | 检索无结果 | 清空/隔离测试 DB 的 `long_term_memory`，输入需检索查询 | `prefetch` 返回空串，Prompt 不含 memory-context 段，LLM 正常回复 | Prompt 中无 `<memory-context>`；回复正常 | 核心 |
| E3 | LLM 审查结果格式错误容错 | mock `_call_llm_for_review` 返回乱码/截断 JSON | `_parse_review_result` 返回 `[]`，不写入记忆，不抛异常 | 无异常；`long_term_memory`/`self_cognition` 无新增脏数据 | 核心 |
| E4 | Token 溢出触发压缩 | 持续对话使 `estimate_tokens` 超过 96000（max=128000×0.75） | `should_compress` 返回 True，`compress` 被调用，`_conversation_history` 被压缩 | 压缩后 `_conversation_history` 长度 = 7；`compression_log` 新增 1 条 | 核心 |
| E5 | Session 摘要生成失败容错 | mock `_generate_session_summary` 抛异常，执行会话切换 | 异常被捕获打印，不影响新会话开始与对话继续 | 切换不抛异常；新会话 Prefetch 正常 | 核心 |
| E6 | 会话历史为空 | 全新 DB（`session_summaries` 为空）启动首次会话 | `start_session` 加载空历史，Prefetch 仅走全局记忆，不报错 | `get_session_history()` 返回 `[]`；对话正常 | 非核心 |
| E7 | 跨用户隔离 | identity_key="userA" 写入记忆后，以 identity_key="userB" 检索相同查询 | userB 的 prefetch 不命中 userA 的记忆 | 返回空或仅 userB 自身记忆；无串用户数据 | 核心 |
| E8 | Background Review 异步不阻塞 | 完成 1 轮对话，mock review LLM 慢响应 5s，计时 `_on_parsed` 主流程耗时 | 主流程响应不受 5s review 影响，回复先于 review 完成 | 主流程耗时 < 1s（不含 LLM 本身）；review 在后台完成 | 非核心 |

### 10.4 验收结论判定标准

| 验收等级 | 判定标准 |
|------|---------|
| **通过** | 所有「核心」项全部通过 |
| **附条件通过** | 核心项全通过，非核心项 ≤ 3 项不通过且有补救计划 |
| **不通过** | 任一「核心」项不通过 |

#### 验收记录模板

```
# AAA 记忆系统改造方案 验收记录

验收日期：__________  验收人：__________  方案版本：v3.1

## 一、功能验收用例

- [ ] F1  Trivial Prompt 识别与跳过        [核心]   □通过 □不通过  备注：____________
- [ ] F2  Prefetch 单轮交互                [核心]   □通过 □不通过  备注：____________
- [ ] F3  memory-context 安全标签注入      [核心]   □通过 □不通过  备注：____________
- [ ] F4  sanitize 脱敏与截断              [核心]   □通过 □不通过  备注：____________
- [ ] F5  _on_parsed 移除第二轮检索        [核心]   □通过 □不通过  备注：____________
- [ ] F6  Background Review 触发           [核心]   □通过 □不通过  备注：____________
- [ ] F7  审查结果 JSON 解析容错           [核心]   □通过 □不通过  备注：____________
- [ ] F8  declarative 记忆持久化           [核心]   □通过 □不通过  备注：____________
- [ ] F9  procedural 记忆持久化            [非核心] □通过 □不通过  备注：____________
- [ ] F10 ContextEngine 阈值判定          [核心]   □通过 □不通过  备注：____________
- [ ] F11 on_pre_compress 洞察抢救         [核心]   □通过 □不通过  备注：____________
- [ ] F12 压缩后摘要生成                  [非核心] □通过 □不通过  备注：____________
- [ ] F13 MemoryProvider 抽象接口         [核心]   □通过 □不通过  备注：____________
- [ ] F14 MemOSProvider.prefetch          [核心]   □通过 □不通过  备注：____________
- [ ] F15 MemOSProvider.sync_turn 异步    [非核心] □通过 □不通过  备注：____________
- [ ] F16 health_check 健康检查           [核心]   □通过 □不通过  备注：____________
- [ ] F17 SessionManager 会话切换触发摘要 [核心]   □通过 □不通过  备注：____________
- [ ] F18 历史会话摘要注入 Prefetch       [非核心] □通过 □不通过  备注：____________

## 二、边界与异常验收

- [ ] E1 MemOS 模型未就绪降级             [核心]   □通过 □不通过  备注：____________
- [ ] E2 检索无结果                       [核心]   □通过 □不通过  备注：____________
- [ ] E3 LLM 审查结果格式错误容错         [核心]   □通过 □不通过  备注：____________
- [ ] E4 Token 溢出触发压缩               [核心]   □通过 □不通过  备注：____________
- [ ] E5 Session 摘要生成失败容错         [核心]   □通过 □不通过  备注：____________
- [ ] E6 会话历史为空                     [非核心] □通过 □不通过  备注：____________
- [ ] E7 跨用户隔离                       [核心]   □通过 □不通过  备注：____________
- [ ] E8 Background Review 异步不阻塞     [非核心] □通过 □不通过  备注：____________

## 三、验收结论

核心项通过：______ / 20      非核心项通过：______ / 6

验收等级：□ 通过    □ 附条件通过    □ 不通过

遗留问题与补救计划：____________________________________________

验收人签字：__________     日期：__________
```

---

**最后更新**：2026-08-06
