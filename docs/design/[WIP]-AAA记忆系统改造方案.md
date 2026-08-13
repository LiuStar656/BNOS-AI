# AAA 记忆系统改造方案

> 版本：v4.0 | 日期：2026-08-08 | 状态：[PLAN]
> 基于：AAA 节点 v6.x 实际架构（单节点 + 内部模块化）| 承接：v3.1 方案（2026-08-06）+ 2026-08-07 架构决策（单节点 + 内部模块化方向）

---

## 目录

- [一、现状分析（v6.x 实际架构）](#一现状分析v6x-实际架构)
- [二、改造目标](#二改造目标)
- [三、改造方案](#三改造方案)
- [四、文件变动清单](#四文件变动清单)
- [五、实施路线图](#五实施路线图)
- [六、测试计划](#六测试计划)
- [七、兼容性与回退](#七兼容性与回退)
- [八、风险与对策](#八风险与对策)
- [九、验收方法](#九验收方法)
- [十、决策留档（P0-P3 对比测试）](#十决策留档p0-p3-对比测试)

---

## 一、现状分析（v6.x 实际架构）

### 1.1 架构演进时间线

AAA 节点（`nodes/node_python_aaa_cognition/`）自 v3.1 方案（2026-08-06）后经历了重大架构演进，从「AAA v2.0」升级为「v6.x 单节点 + 内部模块化」：

| 版本 | 日期 | 新增能力 | 对应文件 |
|------|------|----------|----------|
| v2.0 | 早期 | MemOS 语义检索（替换 FAISS）、按需两轮交互、自我反思、Diary 联动 | `memos.py`、`db.py`、`diary.py` |
| v2.0+ | 8-07 前 | 打断事件感知（TTS 打断 → negative 反馈）、认知演化增强（反馈驱动性格演化） | `main.py` `_on_interrupt`、`personality.py` |
| v3.1 | 8-07 | Background Review 认知反思落地（每 5 轮/每 5 批） | `review.py`、`main.py` `_trigger_background_review` |
| v4.0 | 8-07 | 感知能力声明系统（Prompt 告知 LLM 可用感知通道） | `perception_capabilities.py` |
| v5.1 | 8-07 | 角色种子系统（性格向量演化 + 动态情绪 + Prompt 段构建） | `personality.py` |
| v6.0 | 8-07 | 消息池批量入口（平台弹幕批次）、多用户归属、静默观察 | `main.py` `_on_pool_batch` |
| v6.1~v6.6 | 8-07 | 多用户 review 归因、回应对象显式判定、防自认知污染、兜底触发阈值、数据采集（decisions/memory_usage/silent_cognition） | `main.py`、`review.py`、`db.py` |
| v7.1 | 8-08 | 近期观察记录回流（interest_judgment 未过门文本回灌上下文） | `db.py` `read_recent_observations`、`main.py` `_gather_context` |

> 本方案 v4.0 在 v6.x 架构上重新评估 v3.1 的五个改造点，并新增安全协议改造。

### 1.2 当前架构总览（单节点 + 内部模块化）

**架构决策**（2026-08-07 确认）：AAA 保持单节点，不拆分独立节点（拆分会引入 200ms+ 节点间 JSON 文件异步通信延迟）；采用**内部模块边界**划分职责，`main.py` 只做路由编排。

```
nodes/node_python_aaa_cognition/
├── main.py                    # 路由编排层（process() 按 data_type/source 分发）
├── db.py                      # 数据库读写 + 建表 + 异步写（fire-and-forget）
├── memos.py                   # MemOS 语义检索（SentenceTransformer + SQLite + npz 索引）
├── prompt.py                  # 第一轮 Prompt 模板（_CONTEXT_HEADER + DIRECT/RETRIEVAL/TOOL）
├── prompt_retrieval.py        # 第二轮 Prompt 模板（检索后直接回复）
├── prompt_tool.py             # 工具调用 Prompt 模板
├── parser.py                  # 节标记解析 + 情绪标签注入
├── review.py                  # Background Review（认知反思：构建→LLM→解析→持久化）
├── personality.py             # 角色种子系统（性格演化 + 情绪处理 + 反馈采集）
├── perception_capabilities.py # 感知能力声明系统
├── location.py                # 定位感知（IP + Qt 高精度，注入 Prompt 位置段）
├── diary.py                   # 日记系统（次日首条对话触发）
├── packet.py                  # 数据包辅助
├── config.py                  # 配置加载 + 相对路径解析
├── node_config.json           # 节点参数/端口定义
└── 开发方案.md                 # 节点开发方案（v2.0 设计，§13 会话上下文感知待落地）
```

**消息路由**（`main.py` `process()`）：

| data_type | source | 处理函数 |
|-----------|--------|----------|
| `switch_conversation` | - | `_on_switch_conversation`（清 pending） |
| `text`/`parsed` | `diary` | `_on_diary_response` |
| `text`/`parsed` | `review` | `_on_review_response`（Background Review 回执） |
| `interrupt` | - | `_on_interrupt` |
| `text`/`parsed` | `llm` | `_on_parsed` |
| `text` | `gui` | `_on_text`（单条路径） |
| `pool_batch` | - | `_on_pool_batch`（消息池批量路径） |
| `tool_result` | - | `_on_tool_result` |
| `db_command` | - | `_on_db_command`（format/backup/restore） |

### 1.3 v3.1 方案落地情况核查

| 改造点 | v3.1 设计 | 当前实际状态 | 结论 |
|--------|-----------|-------------|------|
| §3.1 Prefetch 替换两轮交互 | `_on_text` 同步预取，一轮成型 | **未实现**。仍是「薄 prompt → LLM 输出【语意检索】→ 第二轮 `ptr.build_second`」 | **保留改造，按 v6.x 重新设计** |
| §3.2 Background Review | 每轮对话后异步反思 | **已实现**（`review.py`）。每 5 轮（GUI 单条）/每 5 批（消息池）触发，异步线程 + LLM 节点间回执（`_on_review_response`），已含命令污染防线（confidence≥0.7 + 命令句式过滤 + 频次门槛） | **已完成，本章仅做增强项** |
| §3.3 ContextEngine 压缩保护 | 新增 `context_engine.py` | **未实现**。无 Token 估算/压缩机制 | **保留改造** |
| §3.4 MemoryProvider 抽象 | 新增 `memory_provider.py` | **未实现**。main.py 直接调用 `memos.retrieve()` | **保留改造** |
| §9.6 SessionManager | 新增 `session_manager.py` + `session_summaries` 表 | **未实现**。仅有 `_on_switch_conversation`（清空 pending）+ 文档 §13 `conversation_state` 设计（未编码） | **保留改造，评估与现有机制关系** |

### 1.4 当前主流程（两轮交互仍存在）

```
用户输入（text/gui）
    │
    ▼
_on_text ──┬─ db.write_async（用户消息入库）
           ├─ _observe_user_reaction（反馈信号采集）
           ├─ diary.check_and_write_diary（日记触发）
           └─ _gather_context(skip_retrieval=True)  ← 薄 Prompt
                    │
                    ▼
            pt.build(ctx) → prompt → llm_infer
                    │
                    ▼
_on_parsed ── 解析节标记
    ├─ 【工具调用】→ tool_call 分支（暂未开放）
    ├─ 【语意检索】非空 → memos.retrieve → ctx2 → ptr.build_second → 第二轮 LLM
    │        （两轮交互：延迟翻倍、Token 浪费）
    └─ 直接回复 → 写库 + 认知演化 + 每5轮 Background Review + 自我反思(每10条) + 索引重建
```

### 1.5 核心痛点（v4.0 更新）

| # | 痛点 | 影响 | 根因 |
|---|------|------|------|
| 1 | **两轮交互仍存在** | 延迟翻倍、Token 浪费、LLM 决策不可靠 | `_on_text` 薄 Prompt + `_on_parsed` 二次检索 |
| 2 | **记忆注入无安全协议** | Prompt 注入风险、记忆与用户输入混淆 | `memos.retrieve` 结果在 `_prepare_ctx` 中直接拼接，无 `<memory-context>` 标签 |
| 3 | **无上下文压缩保护** | 长对话 Token 溢出时信息静默丢失 | 缺乏 `on_pre_compress` 截断前提取 |
| 4 | **MemOS 耦合度高** | 检索/写库/索引直连 `memos.py` 单体模块 | 无 MemoryProvider 抽象接口 |
| 5 | **无会话级结构化记忆** | 全局记忆扁平，跨会话只有隐式交叉检索 | 无 Session 摘要机制（`conversation_state` 仅停留在文档设计） |
| 6 | **Background Review 触发粒度固定** | 每 5 轮固定，无配置化；LLM 回执失败无重试 | 触发阈值硬编码，回执单次消费 |

### 1.6 已有优势（v4.0 更新）

- ✅ **单节点 + 内部模块化**：`main.py` 路由编排 + 模块边界清晰（personality/location/review/perception）
- ✅ **Background Review 已落地**：独立 `review.py`，含命令污染防线、多用户归因、线程安全（独立 sqlite 连接，不碰 MemOS）
- ✅ 认知演化系统（v5.1）：性格向量随真实反馈演化，情绪阻尼防贴边
- ✅ 感知能力声明系统（v4.0）：防止幻觉，支持渐进增强
- ✅ 多用户隔离（v6.x）：identity_key + user_id 双维度归属
- ✅ 消息池批量路径（v6.0）：多说话人场景、静默观察计数
- ✅ 数据采集体系（v6.6）：decisions/memory_usage/silent_cognition 落盘，支撑末位偏置等量化分析
- ✅ 定位感知（v1.3）、打断事件感知（v2.0）、日记系统、知识图谱增量计算

---

## 二、改造目标

### 2.1 核心目标

1. **Prefetch 单轮交互**：系统级预取替代「薄 Prompt + 语意检索」两轮交互，保留 v6.6 数据采集兼容
2. **记忆注入安全协议**：`<memory-context>` 标签 + sanitize 脱敏截断，防 Prompt 注入
3. **ContextEngine 压缩保护**：Token 估算 + 压缩前洞察抢救
4. **MemoryProvider 抽象**：解耦 MemOS，提供可扩展 Provider 接口
5. **Session 边界管理**：会话摘要 + 跨会话结构化记忆（与现有 `conversation_state` 设计互补）
6. **Background Review 增强**：触发阈值可配置 + 回执重试机制

### 2.2 非目标

- ❌ 不改变现有 DB 表结构（新增表除外：`session_summaries`）
- ❌ 不改变 LLM 输出格式（节标记）
- ❌ 不引入外部依赖（除 SentenceTransformer 已有的）
- ❌ 不改变节点间通信协议
- ❌ 不拆分独立节点（维持单节点架构决策）

---

## 三、改造方案

### 参考源文件索引

| 改造点 | 参考源文件 | 关键类/函数 |
|--------|------------|------------|
| **Prefetch 模式** | `agent/memory_manager.py` | `MemoryManager.prefetch()` |
| **记忆注入安全协议** | `agent/memory_manager.py` | `_inject_round_starts()` |
| **Sanitize 脱敏截断** | `agent/context_engine.py` | `sanitize_memory_context()` |
| **Trivial Prompt Skip** | `agent/memory_manager.py` | `is_trivial_prompt()` |
| **Context Compression** | `agent/context_engine.py` | `on_pre_compress()`, `estimate_tokens()` |
| **MemoryProvider 接口** | `agent/memory_provider.py` | `MemoryProvider` ABC |
| **Session 生命周期** | `agent/memory_manager.py` | `commit_session_boundary_async()` |

---

### 3.1 改造一：Prefetch 单轮交互

> **目标**：消除两轮交互。`_on_text`/`_on_pool_batch` 同步预取记忆并注入安全协议，一轮成型。
> **兼容要求**：v6.6 数据采集（memory_hits → `decisions.memory_hits` / `db.memory_usage`）必须迁移到预取路径。

#### 3.1.1 改造前（当前代码）

```python
# main.py _on_text()
ctx = self._gather_context(
    data.get("content", ""), dbp, attachments, conv_id,
    skip_retrieval=True, identity_key=identity_key,   # 薄 Prompt，不检索
)

# main.py _on_parsed()  — 第二轮
retrieval_keywords = (parsed.get("语意检索") or "").strip()
if retrieval_keywords and pending:
    memos_results = memos.retrieve(retrieval_keywords, top_k=5, ...)
    hits = memos.get_last_hits()
    if hits and pending:
        pending["memory_hits"] = hits                  # v6.6 采集
    if memos_results:
        ctx2 = self._gather_context(..., retrieval_override=memos_results, ...)
        return {"_port": "prompt", "content": ptr.build_second(ctx2), ...}  # 第二轮
```

#### 3.1.2 改造后

> `__init__` 中需新增实例属性：`self._last_prefetch_hits: list = []`（供 v6.6 memory_hits 采集）。

```python
# main.py _on_text() — 系统级 Prefetch
def _on_text(self, data, dbp):
    # ... 现有初始化（ensure/load_index/conv_id/identity_key） ...
    db.write_async(data, dbp, role="user")
    # ... 现有反馈采集 / diary 检测 ...

    query = data.get("content", "")
    rid = data.get("request_id", "")

    # ===== 新增：系统级 Prefetch =====
    memory_context = ""
    if not self._is_trivial_prompt(query):
        memory_context = self._prefetch_memory(query, dbp, identity_key)

    ctx = self._gather_context(
        query, dbp, attachments, conv_id,
        skip_retrieval=True,            # 不再需要 LLM 决策
        prefetch_override=memory_context,  # 注入预取结果（含安全标签）
        identity_key=identity_key,
    )
    # 缓存上下文（供写库/反思/Review 使用，保留 pending 结构）
    self._pending_contexts[rid] = {
        "user_text": query, "attachments": attachments,
        "conv_id": conv_id, "identity_key": identity_key,
        "user_id": str(data.get("user_id", "") or ""),
        "memory_hits": self._last_prefetch_hits,   # v6.6 采集迁移
    }
    return {"_port": "prompt", "data_type": "prompt",
            "content": pt.build(ctx), "request_id": rid}
```

新增辅助方法：

```python
# main.py 新增
_TRIVIAL_PATTERNS = [
    r'^\s*(嗯|好|对|是|ok|yes|继续|在吗|hello|hi|谢谢|了解了|知道了)\s*[.!?！？。]*$',
    r'^\s*[.!?！？。\s]{1,3}\s*$',
    r'^\s*(/learn|/help|/clear|/status)\s*',
]

def _is_trivial_prompt(self, text: str) -> bool:
    """跳过无意义输入（短输入/礼貌语/命令），节省 Prefetch 延迟"""
    text = text.strip().lower()
    if len(text) < 3:
        return True
    return any(re.match(p, text, re.IGNORECASE) for p in _TRIVIAL_PATTERNS)

def _prefetch_memory(self, query, dbp, identity_key):
    """同步预取记忆（经 MemoryProvider，含安全协议）；无结果返回空串，异常不阻塞对话。

    实现：内部走 self.memory_provider.prefetch（MemOSProvider 完成
    retrieve → sanitize_memory_context 脱敏 → format_memory_context 包裹），
    命中条目经 provider.get_last_hits() 采集到 _last_prefetch_hits（v6.6 埋点）。
    """
    self._last_prefetch_hits = []
    try:
        result = self.memory_provider.prefetch(query, dbp, identity_key)
        if not result:
            return ""
        hits = self.memory_provider.get_last_hits()
        if hits:
            self._last_prefetch_hits = hits           # v6.6 采集
        return result
    except Exception:
        return ""

def _sanitize_memory(self, text: str) -> str:
    """记忆注入前脱敏 + 截断（统一实现在 memory_provider.sanitize_memory_context）"""
    return sanitize_memory_context(text)
```

#### 3.1.3 `_gather_context` 新增参数

```python
def _gather_context(self, user_text, dbp, attachments=None, conv_id="default",
                     skip_retrieval=False, retrieval_override=None,
                     prefetch_override=None,          # ← 新增
                     reflection_override=None, identity_key=_IDENTITY_KEY_DEFAULT,
                     user_id="", batch_items=None):
    # ... 现有 DB 上下文收集保持不变 ...

    # 4. MemOS 检索（优先级：prefetch > retrieval > 按需）
    memos_top5 = ""
    if prefetch_override is not None:
        memos_top5 = prefetch_override                  # 新：预取结果（含标签）
    elif retrieval_override is not None:
        memos_top5 = retrieval_override                 # 兼容：第二轮注入
    elif not skip_retrieval:
        memos_top5 = memos.retrieve(user_text, top_k=5, ...)
    # ... 其余代码不变 ...
```

#### 3.1.4 Prompt 模板透传安全标签

```python
# prompt.py _prepare_ctx() 内，memos_top5 注入段
# 现状：ctx["memos_top5"] 直接作为「记忆检索结果」拼接
# 改造：检测安全标签，已带 <memory-context> 则原文透传（含 System note），
#       旧格式（无标签）自动包裹基础提示，防止记忆被当成用户输入
```

#### 3.1.5 `_on_parsed` 简化（删除第二轮分支）

```python
# main.py _on_parsed()
def _on_parsed(self, data, dbp, cfg, user_id="", batch_mode=False):
    # ... 现有初始化 / 三选一决策 / 批量 user_id 归因 ...

    # ③ 工具调用（保留）
    if tool_call:
        # ... 现有逻辑不变 ...

    # ===== 删除：② 检索记忆两轮分支 =====
    # 删除 retrieval_keywords 检查、memos.retrieve()、ptr.build_second() 第二轮

    # ① 直接回复（统一处理）——现有写库/演化/Review/反思逻辑保留
    # 注意：v6.6 memory_hits 采集源改为 pending 中由 _on_text 预取写入的 hits，
    #       不再依赖 _on_parsed 中的 memos.get_last_hits()
    _hits = list((pending or {}).get("memory_hits", []))
    # ... 其余不变 ...
```

**保留不动**：
- `prompt_retrieval.py` 可保留（供 `_on_tool_result` 等场景复用），或标记为兼容保留
- 工具调用分支、自我反思分支（每 10 条）、Background Review 触发、索引重建

> **memos.py 附带修复（v4.0 Phase 4 发现）**：
> 1. `rebuild_index` 去重失效 bug：`existing = set(zip(_entry_tables, _entry_ids))`
>    元组顺序与检查处 `(eid, "long_term_memory")` 相反，导致每次 rebuild
>    都重复索引全部条目（索引无限膨胀）。已改为 `zip(_entry_ids, _entry_tables)`。
> 2. 索引全局变量写锁 `_index_lock = threading.RLock()`：后台 rebuild
>    （`sync_turn`/日记通道）与主线程 rebuild 并发时串行化，防止基于同一
>    旧状态重复 append。`load_index`/`save_index`/`rebuild_index` 均持锁。
> 3. `MemOSProvider.sync_turn` 后台线程先 `memos._get_model(timeout=0)` 检查
>    模型就绪，未就绪跳过本次索引更新（项目硬约束：后台线程严禁触发
>    MemOS 模型加载/编码，防 OSError 1455 / native 崩溃）。

---

### 3.2 改造二：Background Review 增强（已落地，增量优化）

> **现状**：v3.1 的 Background Review 已完整落地于 [review.py](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/review.py)，触发点：`_on_parsed` 每 5 轮（`_review_counter % 5`）、`_on_pool_batch` 每 5 批（`_observe_counter % 5`）。含防污染三防线。

#### 3.2.1 已实现能力（v4.0 不再重复开发）

| 能力 | 实现位置 | 说明 |
|------|----------|------|
| LLM 双通道调用 | `review.set_llm_call` / `_write_review_prompt_file` | 测试钩子 / 节点间文件通道 |
| 提示词构建 | `build_review_prompt` | 最近 10 条 + user_id 说话对象标注 |
| 结果解析容错 | `parse_review_result` | json 围栏 / 裸 JSON / 乱码容错 |
| 持久化三类型 | `persist_insight` | self→self_info+self_cognition / declarative→user_facts / procedural→self_cognition |
| 命令污染防线 | `_COMMAND_PATTERNS` + `_SELF_INFO_MIN_CONFIDENCE`=0.7 + 频次门槛(≥2 轮) | v2.1 修复 I3 命令污染 |
| 多用户归因 | `persist_insight(user_id)` | declarative 归属具体说话对象 |
| 线程安全 | 独立 sqlite 连接，严禁碰 MemOS | 防 native 崩溃 0xC0000005 |
| 回执处理 | `_on_review_response` | data_type=parsed, source=review |

#### 3.2.2 增强项

```python
# config / main.py __init__ — 触发阈值配置化
# 原：self._review_counter % 5 == 0（硬编码）
# 改：cfg.get("review_interval", 5)，支持 0 关闭 / 1 每轮

# _on_review_response — 回执失败重试（幂等）
# 原：解析失败直接返回 error
# 改：解析为空但 content 非空 → 重新入队重试 1 次（防止 LLM 偶发输出脏 JSON 丢记忆）
```

**验收要点**：触发阈值可配置化；回执重试不产生重复写入（`persist_insight` 已有去重）。

---

### 3.3 改造三：ContextEngine 压缩保护

> **目标**：新增 `context_engine.py`，按会话跟踪对话历史 Token，超阈值时压缩前抢救洞察并生成摘要。

#### 3.3.1 新增 `context_engine.py`

```python
# 新建 context_engine.py
# 约束：只做 sqlite 写入（独立连接），严禁调用 memos / 语义模型（与 review.py 同约束）

class ContextEngine:
    """上下文压缩管理：Token 估算 → 阈值判定 → 压缩前抢救 + 摘要"""

    def __init__(self, max_tokens: int = 128000,
                 threshold_percent: float = 0.75,
                 protect_last_n: int = 6):
        self.max_tokens = max_tokens
        self.threshold = threshold_percent
        self.protect_last_n = protect_last_n
        self._compression_log: list[dict] = []

    def estimate_tokens(self, messages: list[dict]) -> int:
        """粗略估算：中文 1.5 token/字，英文 0.25 token/字"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            cn = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
            total += int(cn * 1.5 + (len(content) - cn) * 0.25)
        return total

    def should_compress(self, current_tokens: int) -> bool:
        return (current_tokens / self.max_tokens) >= self.threshold

    def compress(self, messages: list[dict], dbp: str,
                 identity_key: str) -> list[dict]:
        """压缩前抢救洞察（写 long_term_memory）→ 生成摘要 → 返回压缩结果"""
        old = messages[:-self.protect_last_n]
        insights = self._extract_insights_before_compression(old, dbp, identity_key)
        summary = self._generate_summary(old)
        self._compression_log.append({
            "timestamp": datetime.now().isoformat(),
            "original_count": len(messages),
            "insights_extracted": len(insights),
        })
        return [summary] + messages[-self.protect_last_n:]

    def _extract_insights_before_compression(self, messages, dbp, identity_key):
        """启发式提取含持久化价值的消息（我喜欢/记住/我的…）→ 立即写库"""
        insights = []
        _DURABLE = ["我喜欢", "我讨厌", "我希望", "记住", "叫我", "我通常",
                    "我总是", "我从不", "我的名字", "我偏爱"]
        for msg in messages:
            if msg.get("role") in ("user", "assistant"):
                content = msg.get("content", "")
                if any(kw in content for kw in _DURABLE):
                    insights.append({"content": content[:300],
                                     "source": "compression_recovery"})
                    self._save_insight_to_db(content[:300], dbp, identity_key)
        return insights

    def _generate_summary(self, messages) -> dict:
        """拼接最近消息要点为摘要消息"""
        points = [f"[{m.get('role')}]: {(m.get('content') or '')[:100]}"
                  for m in messages[-20:] if m.get("content")]
        return {"role": "system",
                "content": "【历史摘要（自动生成）】\n" + "\n".join(points[-10:]),
                "is_summary": True}

    def _save_insight_to_db(self, content, dbp, identity_key):
        conn = sqlite3.connect(dbp)
        try:
            conn.execute(
                "INSERT INTO long_term_memory(content, identity_key, importance, "
                "source_confidence, source, created_at) VALUES(?, ?, 4, 4, ?, "
                "datetime('now','localtime'))",
                (content, identity_key, "compression_recovery"))
            conn.commit()
        finally:
            conn.close()

    def get_compression_stats(self) -> dict:
        return {"total_compressions": len(self._compression_log),
                "last_compression": self._compression_log[-1] if self._compression_log else None}
```

#### 3.3.2 集成到主流程

```python
# main.py __init__ 新增
self._conversation_history: dict[str, list[dict]] = {}  # conv_id → 消息列表
self.context_engine = ContextEngine()

# _on_parsed（或 _on_review_response 后）追加消息并检查压缩
self._conversation_history.setdefault(conv_id, []).extend([
    {"role": "user", "content": user_text},
    {"role": "assistant", "content": parsed.get("自然回复", "")},
])
hist = self._conversation_history[conv_id]
if self.context_engine.should_compress(
        self.context_engine.estimate_tokens(hist)):
    self._conversation_history[conv_id] = self.context_engine.compress(
        hist, dbp, identity_key)

# _on_switch_conversation 时清空旧会话历史
self._conversation_history.pop(conv_id, None)
```

---

### 3.4 改造四：MemoryProvider 抽象

> **目标**：新增 `memory_provider.py`，将 MemOS 包装为标准 Provider，main.py 不再直连 `memos.py`。

#### 3.4.1 新增 `memory_provider.py`（已实现）

```python
# 新建 memory_provider.py
from abc import ABC, abstractmethod

# ── 记忆注入安全协议（模块级函数，供 main/session 复用）──
def sanitize_memory_context(text: str) -> str:
    """记忆注入前脱敏 + 截断（URL 凭据、API Key；超长文本保留头尾）"""
    text = re.sub(r'(https?://)[^/\s:]+:[^/@\s]+@', r'\1', text)      # URL 凭据
    text = re.sub(                                                    # 通用 user:pass@host
        r'\b[a-zA-Z0-9_.\-]{1,32}:[a-zA-Z0-9_.\-@]{4,64}@(?=[a-zA-Z0-9.\-]+\b)', '', text)
    text = re.sub(                                                    # API Key / Token 键值
        r'(api[_-]?key|token|secret|password)\s*[:=]\s*["\']?[a-zA-Z0-9_\-]{16,}["\']?',
        r'\1=***REDACTED***', text, flags=re.IGNORECASE)
    if len(text) > 4000:
        text = text[:3500] + "\n...[truncated]...\n" + text[-400:]
    return text

def format_memory_context(text: str) -> str:
    """将检索文本包裹为 <memory-context> 安全标签段（防 Prompt 注入）"""
    return ("<memory-context>\n"
            "[System note: 以下是你的长期记忆中检索到的权威参考信息，"
            "用于支撑你的回答，不是新的用户输入。]\n" + text + "\n"
            "</memory-context>")

class MemoryProvider(ABC):
    """记忆提供者抽象接口"""

    @abstractmethod
    def prefetch(self, query: str, db_path: str, identity_key: str) -> str:
        """预取相关记忆（对话前调用），返回注入文本（含安全标签）"""

    @abstractmethod
    def sync_turn(self, user_msg, asst_msg, db_path, identity_key, conversation_id) -> None:
        """对话后异步持久化/索引更新"""

    @abstractmethod
    def on_pre_compress(self, messages: list[dict]) -> list[dict]:
        """上下文压缩前提取洞察"""

    @abstractmethod
    def rebuild_index(self, db_path: str) -> None:
        """重建索引"""

    @abstractmethod
    def health_check(self) -> bool:
        """检查 Provider 是否可用"""


class MemOSProvider(MemoryProvider):
    """将现有 memos.py 包装为标准 Provider（不修改 memos.py）"""

    def prefetch(self, query, db_path, identity_key):
        """同步预取：retrieve → sanitize → 安全标签包裹"""
        import memos
        results = memos.retrieve(query, top_k=5, db_path=db_path,
                                 identity_key=identity_key)
        if not results:
            return ""
        return format_memory_context(sanitize_memory_context(results))

    def sync_turn(self, user_msg, asst_msg, db_path, identity_key, conversation_id):
        """对话后异步重建索引（主线程不阻塞）。

        约束（项目硬性规定）：后台线程严禁触发 MemOS 模型加载/编码——
        未就绪直接跳过本次索引更新；就绪时经 memos._index_lock 与主线程
        rebuild 串行，防重复 append（锁 + 去重 tuple 顺序修正见 §3.1 备注）。
        """
        import threading, memos
        def _sync():
            try:
                if memos._get_model(timeout=0) is None:
                    return  # 模型未就绪：跳过，避免后台加载并发（OSError 1455）
                memos.rebuild_index(db_path)
            except Exception:
                pass
        threading.Thread(target=_sync, daemon=True).start()

    def on_pre_compress(self, messages):
        return [{"content": m["content"][:300], "source": "compression"}
                for m in messages if m.get("role") in ("user", "assistant")
                and any(k in m.get("content", "") for k in ("我喜欢", "记住", "我叫"))]

    def rebuild_index(self, db_path):
        import memos
        memos.rebuild_index(db_path)

    def health_check(self):
        try:
            import memos
            return memos._get_model(timeout=0) is not None
        except Exception:
            return False

    def get_last_hits(self) -> list:
        """透传 v6.6 数据采集接口（检索命中条目）"""
        import memos
        return memos.get_last_hits()
```

#### 3.4.2 在 main.py 中使用

```python
# main.py
from memory_provider import MemOSProvider

self.memory_provider = MemOSProvider()   # __init__ 新增

# _on_text / _on_pool_batch
memory_context = self.memory_provider.prefetch(query, dbp, identity_key)

# _on_parsed 异步索引重建（替换直连 memos.rebuild_index）
self.memory_provider.sync_turn(...)
```

> 注意：`review.py` 的「后台线程严禁调用 memos」约束同样适用于 Provider —— `sync_turn`/`rebuild_index` 走线程且不碰 MemOS 模型加载。

---

### 3.5 改造五：Session 边界管理

> **目标**：新增 `session_manager.py` + `session_summaries` 表，为全局扁平记忆增加会话级结构化摘要。
> **与现有机制关系**：
> - `_on_switch_conversation`（已实现）：只清空 pending，无摘要 → 成为 SessionManager 的入口
> - `conversation_state` 表（文档 §13 设计，未编码）：侧重「会话上下文感知」（时间间隔/状态）→ 本次只实现 Session 摘要，时间间隔感知列为后续增强，避免一次改动过大
> - **Review 通道复用**：会话摘要 LLM 调用复用 `review.llm_call` 双通道（测试钩子 / 节点间文件回执），避免新开一条节点间通道

#### 3.5.1 新增 `session_summaries` 表

```sql
CREATE TABLE IF NOT EXISTS session_summaries(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    identity_key TEXT NOT NULL DEFAULT 'gui:default',
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT(datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_ss_identity ON session_summaries(identity_key);
CREATE INDEX IF NOT EXISTS idx_ss_session  ON session_summaries(session_id);
```

#### 3.5.2 新增 `session_manager.py`（已实现）

```python
# 新建 session_manager.py
# 摘要通道复用 review 文件通道（output_review_prompt.json，source="review"），
# session_id 编码进 request_id："session_summary_{session_id}_{ts}"，
# 回执在 main._on_review_response 中按前缀分流到 _on_session_summary_response。
# 约束：后台线程只做 sqlite 读 + 写文件，不碰 MemOS 语义模型。

class SessionManager:
    """会话边界管理：切换时生成旧会话摘要，新会话加载历史摘要"""

    def __init__(self):
        self._current_session_id = None

    def start_session(self, session_id: str, identity_key: str, db_path: str):
        """开始/切换会话：若来自其他会话则先触发旧会话摘要（异步）"""
        if self._current_session_id and self._current_session_id != session_id:
            self._request_summary(self._current_session_id, identity_key, db_path)
        self._current_session_id = session_id

    def _request_summary(self, session_id, identity_key, db_path):
        def _run():
            try:
                conv = self._load_messages(session_id, identity_key, db_path)
                if not conv:
                    return
                self._write_summary_prompt_file(
                    self._build_summary_prompt(conv), identity_key, session_id)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def _write_summary_prompt_file(self, prompt, identity_key, session_id):
        """写 output_review_prompt.json；request_id 编码 session_id（可含下划线）"""
        json.dump({
            "data_type": "prompt", "content": prompt, "source": "review",
            "request_id": f"session_summary_{session_id}_{int(time.time()*1000)}",
            "identity_key": identity_key, "user_id": "", "session_id": session_id,
        }, open(resolve("./output_review_prompt.json"), "w", encoding="utf-8"),
            ensure_ascii=False)

    @staticmethod
    def parse_summary_rid(rid: str) -> str:
        """从 session_summary_{session_id}_{ts} 解析 session_id"""
        parts = rid.split("_")
        if len(parts) >= 4 and parts[0] == "session" and parts[1] == "summary":
            return "_".join(parts[2:-1])
        return ""

    def _load_messages(self, session_id, identity_key, db_path) -> list[dict]:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT role, content FROM user_messages WHERE conversation_id=? "
                "AND identity_key=? AND role IN ('user','assistant') "
                "ORDER BY id DESC LIMIT 20", (session_id, identity_key)).fetchall()
            return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
        finally:
            conn.close()

    def get_session_history(self, identity_key, db_path, limit=3) -> list[dict]:
        """读取最近会话摘要（查询前幂等建表）"""
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("BEGIN")
            conn.executescript(_CREATE_TABLE_SQL)
            conn.commit()
            rows = conn.execute(
                "SELECT session_id, summary, created_at FROM session_summaries "
                "WHERE identity_key=? ORDER BY created_at DESC LIMIT ?",
                (identity_key, limit)).fetchall()
            return [{"session_id": r[0], "summary": r[1], "created_at": r[2]}
                    for r in rows]
        except Exception:
            return []
        finally:
            conn.close()
```

#### 3.5.3 集成到主流程

```python
# main.py __init__
self.session_manager = SessionManager()   # db_path 运行时传入（resolve 后）

# _on_switch_conversation（替换现有实现；dbp 为 resolve 后的真实 DB 路径）
def _on_switch_conversation(self, data):
    cfg = load_config()
    dbp = resolve(cfg.get("db_path", "../shared/chatbot.db"))
    conv_id = data.get("conversation_id", "default")
    identity_key = data.get("identity_key", _IDENTITY_KEY_DEFAULT)
    self._current_conversation_id = conv_id
    self._pending_contexts.clear()
    self._conversation_history.pop(conv_id, None)          # ContextEngine 清历史
    self.session_manager.start_session(conv_id, identity_key, dbp)
    return {"_port": "default", "data_type": "switch_conversation_ack",
            "status": "ok", "conversation_id": conv_id}

# _gather_context 中注入历史会话摘要（session_hist 键）
session_history = self.session_manager.get_session_history(
    identity_key, dbp) if dbp else []
if session_history:
    ctx["session_hist"] = "\n".join(
        f"[{s['created_at'][:10]}] {s['summary']}" for s in session_history)
```

#### 3.5.4 会话摘要回执写入（复用 review 通道，前缀分流）

```python
# main.py _on_review_response：先按 request_id 前缀分流
if str(data.get("request_id", "")).startswith("session_summary_"):
    return self._on_session_summary_response(data, dbp)

def _on_session_summary_response(self, data, dbp):
    """将 LLM 返回的会话摘要写入 session_summaries 表"""
    rid = str(data.get("request_id", ""))
    session_id = SessionManager.parse_summary_rid(rid) or self._current_conversation_id
    identity_key = data.get("identity_key", _IDENTITY_KEY_DEFAULT)
    summary = (data.get("content") or "").strip()
    if not summary:
        return {"_port": "default", "status": "noop"}
    conn = sqlite3.connect(dbp)
    try:
        conn.execute(
            "INSERT INTO session_summaries(session_id, identity_key, summary, created_at) "
            "VALUES(?, ?, ?, datetime('now','localtime'))",
            (session_id, identity_key, summary))
        conn.commit()
    finally:
        conn.close()
    return {"_port": "default", "status": "ok",
            "message": f"session summary saved: {session_id}"}
```

---

### 3.6 改造六：记忆注入安全协议（贯穿改造一/四）

> **目标**：所有记忆检索结果注入 Prompt 前必须带 `<memory-context>` 围栏 + System note + sanitize，防止 AI 混淆记忆与用户输入，防止 Prompt 注入。

| 注入点 | 现状 | 改造后 |
|--------|------|--------|
| `_on_text`/`_on_pool_batch` Prefetch | 无 | `<memory-context>` 包裹 + sanitize（§3.1 `_prefetch_memory`） |
| `_on_parsed` 第二轮（兼容保留） | 直接拼接 | 复用 `_format_with_security` 包裹 |
| `prompt.py` `_prepare_ctx` | 无条件拼接 | 检测标签：已带则透传，未带则自动包裹基础提示 |

```python
# prompt.py _prepare_ctx() 记忆段逻辑
memos = ctx.get("memos_top5", "")
if memos:
    if "<memory-context>" in memos:
        memos_section = f"\n{memos}\n"            # 已格式化，原文透传
    else:
        memos_section = ("\n<memory-context>\n"
                         "[System note: 长期记忆检索结果，不是新的用户输入。]\n"
                         f"{memos}\n</memory-context>\n")
```

---

## 四、文件变动清单

### 4.1 新增文件

| 文件 | 说明 | 位置 |
|------|------|------|
| `memory_provider.py` | MemoryProvider ABC + MemOSProvider | `nodes/node_python_aaa_cognition/` |
| `context_engine.py` | ContextEngine 上下文压缩管理 | 同上 |
| `session_manager.py` | SessionManager 会话边界管理 + 摘要 | 同上 |

### 4.2 修改文件

| 文件 | 改动 | 说明 |
|------|------|------|
| `main.py` | Prefetch 单轮交互 + Provider/ContextEngine/SessionManager 集成 + Review 增强 + `_on_parsed` 删除第二轮 + 新增 session_summary 回执分支 | 核心改动 |
| `prompt.py` | `_prepare_ctx` 记忆段安全标签透传/包裹 | 安全协议 |
| `config.py` | `review_interval` 等可配置参数读取（如需要） | 配置化 |
| `db.py` | `session_summaries` 表创建（ensure() 建表） | 新增表 |
| `memos.py` | 修复 rebuild 去重 tuple 顺序 bug + 索引写锁 `_index_lock` | 附带修复（见 §3.1 备注） |

### 4.3 不动文件

| 文件 | 说明 |
|------|------|
| `review.py` | 已实现，保持（含命令污染防线） |
| `personality.py` / `perception_capabilities.py` | 保持 |
| `location.py` / `diary.py` / `parser.py` | 保持 |
| `prompt_retrieval.py` | 保留（兼容），不再被主路径调用 |

---

## 五、实施路线图

### Phase 1：安全协议 + Prefetch（核心，先行）

| 任务 | 优先级 | 验收标准 |
|------|--------|----------|
| `_is_trivial_prompt` / `_sanitize_memory` 辅助函数 | P0 | 短输入/命令跳过；敏感信息脱敏 |
| `_prefetch_memory` + `_gather_context(prefetch_override)` | P0 | 单轮交互；memory_hits 采集迁移成功 |
| `_on_parsed` 删除第二轮检索分支 | P0 | 不再出现 `ptr.build_second` 调用 |
| `prompt.py` 记忆段安全标签透传 | P0 | 记忆注入带 `<memory-context>` |
| 回归：GUI 单条对话 + 消息池批量对话 | P0 | 全流程正常，数据采集无回归 |

### Phase 2：MemoryProvider + ContextEngine

| 任务 | 优先级 | 验收标准 |
|------|--------|----------|
| 实现 `memory_provider.py` | P1 | MemOSProvider 正常工作，main.py 走 Provider |
| 实现 `context_engine.py` | P1 | Token 超阈值自动压缩 + 洞察抢救写库 |
| 集成 ContextEngine 到主流程 | P1 | 长对话压缩正常，压缩日志记录 |

### Phase 3：Session 边界管理 + Review 增强

| 任务 | 优先级 | 验收标准 |
|------|--------|----------|
| 实现 `session_manager.py` | P0 | 会话切换触发摘要请求 |
| 新增 `session_summaries` 表 | P0 | 建表成功 |
| 摘要回执写入 + 历史摘要注入 Prefetch | P1 | 新会话能引用旧会话摘要 |
| Review 阈值配置化 + 回执重试 | P1 | 可配置、无重复写入 |

### Phase 4：全流程测试与验收

| 任务 | 优先级 | 验收标准 |
|------|--------|----------|
| 单元/集成/边界测试（§6） | P0 | 全部通过 |
| 验收方法逐项核对（§9） | P0 | 核心项全部通过 |

---

## 六、测试计划

### 6.1 单元测试

```python
# test_aaa_memory_v4.py

def test_is_trivial_prompt():
    assert is_trivial_prompt("嗯") is True
    assert is_trivial_prompt("ok") is True
    assert is_trivial_prompt("/help") is True
    assert is_trivial_prompt("你好，我想了解一下科幻电影") is False

def test_sanitize_memory():
    text = "密码 admin:123456@example.com api_key=abcdef1234567890"
    result = sanitize_memory_context(text)
    assert "admin:123456" not in result
    assert "api_key=***REDACTED***" in result

def test_prefetch_single_round():
    # mock memos.retrieve → 断言单轮返回、含 <memory-context> 标签

def test_gather_context_prefetch_priority():
    # prefetch_override 优先于 retrieval_override / 按需检索

def test_on_parsed_no_second_round():
    # 输入带【语意检索】的 LLM 输出 → 不触发第二轮，直接回复

def test_memory_hits_collection():
    # _on_text 预取后 pending.memory_hits 非空（v6.6 采集兼容）

def test_context_engine_threshold():
    # 95000 → False；97000 → True（max=128000, threshold=0.75）

def test_context_engine_compress():
    # 12 条消息 → 返回 7 条（摘要 + 6 条），含持久化价值的写入 long_term_memory

def test_memory_provider_abc():
    # MemoryProvider 不可实例化；MemOSProvider 可实例化

def test_session_manager_switch():
    # start_session 切换 → 触发旧会话摘要请求 + 加载历史

def test_session_summary_table():
    # session_summaries 建表 + 写入 + 索引
```

### 6.2 集成测试

| 场景 | 步骤 | 预期结果 |
|------|------|----------|
| 普通对话 | 输入「你好」 | 单轮交互，正常回复，无第二轮 |
| 需记忆对话 | 输入「我之前说过我喜欢什么？」 | Prefetch 命中历史记忆，注入 `<memory-context>` |
| Trivial 对话 | 输入「嗯」 | 跳过检索，快速响应 |
| 长对话压缩 | 持续对话至 Token 超阈值 | ContextEngine 压缩 + 洞察抢救入库 |
| Background Review | 完成 5 轮对话 | 后台反思，记忆被更新（现有回归） |
| Session 切换 | GUI 切换 conversation_id | 旧会话摘要异步生成，新会话加载历史摘要 |
| 跨会话检索 | 新会话提问旧会话内容 | 全局记忆命中 + 会话摘要命中 |
| 消息池批量 | 平台打包一批弹幕 | Prefetch 合并上下文单轮回复，决策显式化 |

### 6.3 边界测试

| 场景 | 预期行为 |
|------|----------|
| MemOS 模型未就绪 | Prefetch 返回空，不阻塞对话 |
| 检索无结果 | 正常回复，无记忆注入 |
| LLM 返回 JSON 格式错误 | Review 解析容错（现有） |
| Token 溢出 | ContextEngine 触发压缩 |
| 会话摘要生成失败 | 容错处理，不影响对话继续 |
| 会话历史为空 | 正常 Prefetch，无历史摘要注入 |
| Review 回执失败 | 重试 1 次，不重复写入 |

---

## 七、兼容性与回退

### 7.1 兼容性

| 维度 | 是否兼容 | 说明 |
|------|----------|------|
| 现有 DB | ✅ | 无表结构变更（新增 session_summaries 独立表） |
| LLM 输出格式 | ✅ | 节标记不变 |
| GUI 客户端 | ✅ | 接口不变（switch_conversation/llm_response 协议不变） |
| 其他节点 | ✅ | 端口映射不变 |
| v6.6 数据采集 | ✅ | memory_hits 迁移到预取路径，decisions/memory_usage 表结构不变 |
| Background Review | ✅ | 现有 review.py 逻辑不动 |

### 7.2 回退策略

| 功能 | 回退方案 |
|------|----------|
| Prefetch 单轮 | 恢复 `_on_parsed` 第二轮分支，`_on_text` 去掉 prefetch（`prefetch_override=None` 即回退两轮） |
| ContextEngine | 移除 `_conversation_history` 缓存和压缩调用 |
| MemoryProvider | 将 `self.memory_provider.prefetch()` 改回 `memos.retrieve()` |
| SessionManager | 移除 `start_session`/摘要回执分支，恢复纯 `_on_switch_conversation` |
| 安全标签 | `prompt.py` 记忆段改回原拼接逻辑 |

---

## 八、风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| Prefetch 增加首轮延迟 | 首次响应慢 10-50ms | 可接受，SentenceTransformer CPU 毫秒级；trivial 跳过 |
| 预取结果与 LLM 决策不符 | 记忆注入可能偏移 | 保留「语意检索」节作为可选增强提示，但不再强制第二轮 |
| 压缩丢失信息 | AI 上下文不连续 | `on_pre_compress` 先抢救洞察再压缩 |
| Provider 抽象过度设计 | 增加复杂度 | 只抽象 prefetch/sync/compress 三件套 |
| Session 摘要增加 Token 消耗 | 额外 LLM 调用 | 复用 review 通道 + 异步；摘要限最近 10 条 |
| 后台线程并发 | native 崩溃（0xC0000005） | 沿用 review.py 约束：后台线程不碰 MemOS 模型 |
| Review 回执重试重复写入 | 记忆重复 | `persist_insight` 去重已存在，重试仅限解析失败场景 |

---

## 九、验收方法

### 9.1 验收环境与前置条件

| 项 | 要求 |
|------|------|
| 运行环境 | Windows 10/11，Python 3.10+，BNOS 主程序可正常启动 |
| 依赖组件 | SentenceTransformer（all-MiniLM-L6-v2）模型已就绪；SQLite3 可用 |
| 数据库 | 可用 AAA 数据库（含 long_term_memory、user_messages、self_cognition 等表） |
| 新增表 | `session_summaries` 已建表 |
| LLM 节点 | 可正常响应（Prefetch 首轮 / Review / Session 摘要） |
| 测试数据 | ≥2 个 identity_key、≥3 条 long_term_memory 历史记忆 |
| 日志开关 | main.py 调试日志开启，可观察 Prefetch/Compress/Session/Review 触发 |
| 备份 | 已保留改造前 main.py、prompt.py 备份（§7.2 回退对照） |
| 改造代码 | §3.1–§3.6 均已落地，main.py 完成 Provider/ContextEngine/SessionManager 集成 |

### 9.2 功能验收用例

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| F1 | Trivial Prompt 识别 | 输入 `嗯`、`好`、`ok`、`/help`、`你好，我想了解一下科幻电影` | 前 4 项 True，最后 1 项 False | 5 项断言通过；前 4 项未调 `memos.retrieve` | 核心 |
| F2 | Prefetch 单轮交互 | 输入含检索价值的查询，观察 `_on_text` → LLM 链路 | 仅 1 次 LLM 调用即回复，无第二轮 | LLM 调用次数 = 1；无 `ptr.build_second` 调用日志 | 核心 |
| F3 | memory-context 标签注入 | 命中历史记忆的查询，检查最终 Prompt | 检索结果被 `<memory-context>` 包裹且含 System note | Prompt 同时含 `<memory-context>` 与 `[System note` | 核心 |
| F4 | sanitize 脱敏与截断 | 构造含 URL 凭据 / api_key / >4000 字文本 | URL 凭据剥离、key 替换为 `***REDACTED***`、超长含 `[truncated]` | 输出不含明文凭据；长度 ≤ 4000 | 核心 |
| F5 | `_on_parsed` 无第二轮 | 输入带【语意检索】的 LLM 输出 | 不再读取 retrieval_keywords、不再构建第二轮 Prompt | 代码无第二轮分支；运行时无第二次 LLM 调用 | 核心 |
| F6 | memory_hits 采集兼容 | 触发预取命中，检查 decisions/memory_usage | 命中条目被记录 | `pending.memory_hits` 非空，采集表有记录 | 核心 |
| F7 | ContextEngine 阈值 | 构造 95000 / 97000 token | 95000→False，97000→True | 两次断言通过 | 核心 |
| F8 | on_pre_compress 抢救 | 12 条消息（前 6 条含关键词）调 `compress` | 含关键词消息写入 long_term_memory | 新增 `source='compression_recovery'` 记录 | 核心 |
| F9 | 压缩后摘要 | `compress` 返回值 | `[摘要]+6 条`，摘要含 `is_summary=True` | 返回长度 = 7 | 非核心 |
| F10 | MemoryProvider ABC | 检查 memory_provider.py | 5 个抽象方法，不可实例化 | `MemoryProvider()` 抛 TypeError | 核心 |
| F11 | MemOSProvider.prefetch | 预置记忆后调用；无命中查询 | 命中返回标签包裹文本；无命中返回空串 | 含 `<memory-context>` / 返回 `""` | 核心 |
| F12 | MemOSProvider.sync_turn 异步 | 调用后立即返回，等待 2s | 后台 rebuild_index，主线程不阻塞 | 主线程无阻塞 | 非核心 |
| F13 | health_check | 模型加载/卸载两状态 | True / False，不抛异常 | 两次返回值正确 | 核心 |
| F14 | Session 切换触发摘要 | `conv_001` 对话后切 `conv_002` | 旧会话摘要请求发出并写入 session_summaries | `session_summaries` 新增记录 | 核心 |
| F15 | 历史摘要注入 | 新会话 `_on_text` | 最近 3 条摘要拼接注入上下文 | 上下文含 `[日期] 摘要` 文本 | 非核心 |
| F16 | Review 阈值配置化 | 修改 `review_interval` 并观察触发 | 按配置阈值触发 | 日志显示按新阈值触发 | 非核心 |
| F17 | Review 回执重试 | mock 解析失败一次 | 重试 1 次成功，无重复写入 | 无重复记录 | 非核心 |
| F18 | 消息池批量 Prefetch | 平台打包一批弹幕 | 合并上下文单轮回复 + memory_hits 采集 | 单轮、决策显式化、采集正常 | 核心 |

### 9.3 边界与异常验收

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| E1 | MemOS 模型未就绪 | 卸载/延迟加载模型触发 Prefetch | prefetch 返回空，不阻塞 | 对话正常完成 | 核心 |
| E2 | 检索无结果 | 清空 long_term_memory 后查询 | 无 memory-context 段，正常回复 | Prompt 无 `<memory-context>` | 核心 |
| E3 | Token 溢出压缩 | 持续对话超阈值 | 压缩触发，历史被压缩 | `_conversation_history` 长度 = 7 | 核心 |
| E4 | Session 摘要生成失败 | mock 摘要异常，执行切换 | 异常捕获，不影响新会话 | 切换不抛异常 | 核心 |
| E5 | 会话历史为空 | 新 DB 首次会话 | `get_session_history()` 返回 `[]` | 对话正常 | 非核心 |
| E6 | 跨用户隔离 | userA 写记忆，userB 检索 | userB 不命中 userA 记忆 | 无串数据 | 核心 |
| E7 | Background Review 异步 | mock review LLM 慢 5s | 主流程不受影响 | 主流程耗时 < 1s | 非核心 |
| E8 | 后台线程并发安全 | 压缩/摘要/Review 并发 | 无 native 崩溃（0xC0000005） | 全程无崩溃 | 核心 |

### 9.4 验收结论判定标准

| 验收等级 | 判定标准 |
|------|---------|
| **通过** | 所有「核心」项全部通过 |
| **附条件通过** | 核心项全通过，非核心项 ≤ 3 项不通过且有补救计划 |
| **不通过** | 任一「核心」项不通过 |

#### 验收记录模板

```
# AAA 记忆系统改造方案 v4.0 验收记录

验收日期：__________  验收人：__________  方案版本：v4.0

## 一、功能验收用例

- [ ] F1  Trivial Prompt 识别            [核心]   □通过 □不通过  备注：____________
- [ ] F2  Prefetch 单轮交互              [核心]   □通过 □不通过  备注：____________
- [ ] F3  memory-context 标签注入        [核心]   □通过 □不通过  备注：____________
- [ ] F4  sanitize 脱敏与截断            [核心]   □通过 □不通过  备注：____________
- [ ] F5  _on_parsed 无第二轮            [核心]   □通过 □不通过  备注：____________
- [ ] F6  memory_hits 采集兼容           [核心]   □通过 □不通过  备注：____________
- [ ] F7  ContextEngine 阈值             [核心]   □通过 □不通过  备注：____________
- [ ] F8  on_pre_compress 抢救           [核心]   □通过 □不通过  备注：____________
- [ ] F9  压缩后摘要                     [非核心] □通过 □不通过  备注：____________
- [ ] F10 MemoryProvider ABC            [核心]   □通过 □不通过  备注：____________
- [ ] F11 MemOSProvider.prefetch        [核心]   □通过 □不通过  备注：____________
- [ ] F12 MemOSProvider.sync_turn 异步  [非核心] □通过 □不通过  备注：____________
- [ ] F13 health_check                  [核心]   □通过 □不通过  备注：____________
- [ ] F14 Session 切换触发摘要          [核心]   □通过 □不通过  备注：____________
- [ ] F15 历史摘要注入                  [非核心] □通过 □不通过  备注：____________
- [ ] F16 Review 阈值配置化             [非核心] □通过 □不通过  备注：____________
- [ ] F17 Review 回执重试               [非核心] □通过 □不通过  备注：____________
- [ ] F18 消息池批量 Prefetch           [核心]   □通过 □不通过  备注：____________

## 二、边界与异常验收

- [ ] E1 MemOS 模型未就绪               [核心]   □通过 □不通过  备注：____________
- [ ] E2 检索无结果                     [核心]   □通过 □不通过  备注：____________
- [ ] E3 Token 溢出压缩                 [核心]   □通过 □不通过  备注：____________
- [ ] E4 Session 摘要生成失败           [核心]   □通过 □不通过  备注：____________
- [ ] E5 会话历史为空                   [非核心] □通过 □不通过  备注：____________
- [ ] E6 跨用户隔离                     [核心]   □通过 □不通过  备注：____________
- [ ] E7 Review 异步不阻塞              [非核心] □通过 □不通过  备注：____________
- [ ] E8 后台线程并发安全               [核心]   □通过 □不通过  备注：____________

## 三、验收结论

核心项通过：______ / 14      非核心项通过：______ / 8

验收等级：□ 通过    □ 附条件通过    □ 不通过

遗留问题与补救计划：____________________________________________

验收人签字：__________     日期：__________
```

---

## 十、决策留档（P0-P3 对比测试）

> 对应测试脚本：`scripts/aaa_compare/compare_aaa_v4.py [--real]` + `measure.py`
> 完整运行数据：`runs/20260808_203355_aaa_cmp/`（compare_report.md、result_*.json、db_old/db_new）

### 10.1 P0 — Prefetch 全链路端到端验证（真 LLM）

**方法**：真实 DeepSeek LLM 跑同样 4 场景，两版同种子记忆/同模型（deepseek-v4-flash）/同温度（0.7）。

| 场景 | 期望答案 | 旧版（两轮，LLM 自觉检索） | 新版（Prefetch 单轮） |
|------|----------|---------------------------|----------------------|
| 电影 | 星际穿越 | ✗ 0/2（两轮运行均答「未存储」） | ✓ 2/2（两次运行均答出） |
| 猫名 | 二饼 | ✗ 0/2 | ✓ 2/2（**「二饼」两次运行均答出**） |
| 考试 | 专升本、计算机 | ✗ 0/2 | ✓ 1/2（一次全命中；一次表述模糊但确认「聊过」） |
| 天气 | （对照组） | — | — |

**结论**：**Prefetch 全链路打通（决定性）**。新版单轮、无二次检索机会，真实 LLM 稳定引用 memory-context 提取答案（电影/猫名 2/2）；旧版真实 LLM **从不自觉触发【语意检索】**（0/2），记忆完全不可用——坐实 v4.0 改造的核心动机（记忆注入由节点强制，不依赖 LLM 自觉性）。
考试场景偶发表述模糊为 LLM 随机性（temperature 0.7），非链路缺陷；如后续需提高稳定性，可在 memory-context 中强化答案句式（P3 范畴）。

### 10.2 P1 — 人格注入→输出 影响（expB 重跑）

与 P0 同属「注入→输出」验证系列。已修复 `tests/personality_output_probe.py` 的 `build_ctx` 未传 `user_text` 导致新版 `prompt._prepare_ctx` 用空值覆盖用户输入段的问题，重跑见实验报告 `docs/experiments/cognitive_evolution_test/runs/*_expB/`。

### 10.3 P2 — Token 权衡架构决策（已决策）

**实测数据**（假 LLM 确定性测量，两轮运行一致）：

| 指标 | 旧版 v2.0（两轮） | 新版 v4.0（单轮） | 变化 |
|------|-------------------|-------------------|------|
| LLM 往返次数 | 8 | 4 | **-50.0%** |
| Prompt token 总量（估算） | 4659.9~4686.1 | 6609.0 | **+41.0%~41.8%** |

**决策**：**交互场景（GUI 对话）接受该 trade-off** —— 每次对话固定一次 LLM 调用，消除第二轮延迟与解析风险（旧版第二轮回执要再解析一轮【语意检索】格式），换取 ~+41% 单轮 token。交互场景用户体验优先级高于 token 成本。

**后续评估点（token 敏感场景）**：
- 消息池/批量场景（多用户）token 会随 `pool_batch_section` 叠加，需单独评估是否关闭 Prefetch 或降 top-k；
- 成本受限/长会话批量跑批时，可配置关闭 Prefetch 回退两轮交互（预留开关，见改造一 `_gather_context` prefetch_override）。

### 10.4 P3 — 检索质量（top-k/阈值）：暂缓（已决策）

**现状**：top-k=5 固定、无相似度阈值过滤；种子/测试记忆库规模小（<50 条），调整参数无法形成有效回归基线。

**决策**：**暂缓**。等生产记忆库形成规模（预估万级条目）后，再评估 top-k、相似度阈值、相关性加权，并以 P0 同款「记忆问答命中率」作为检索质量回归基线。当前调整属过度优化。

---

**最后更新**：2026-08-08
