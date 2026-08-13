# Hermes Agent 可复用组件分析报告

> 版本：v1.0 | 日期：2026-08-05 | 状态：[ANALYSIS]
> 分析对象：`references/hermes-agent-main`
> 目标：识别除记忆系统外，对 BNOS AI 项目具有参考价值的组件

---

## 一、分析概述

基于对 Hermes Agent 项目的深度分析，除已在《AAA 记忆系统改造方案》中讨论的核心记忆机制（Prefetch、Background Review、ContextEngine、MemoryProvider）外，本文档补充分析以下可复用组件：

| # | 组件 | 源文件 | 核心价值 | BNOS AI 适配优先级 |
|---|------|--------|----------|-------------------|
| 1 | **Learning Graph** | `agent/learning_graph.py` | 知识图谱构建与可视化 | 🟡 中 |
| 2 | **Curator** | `agent/curator.py` | 记忆生命周期管理 | 🟡 中 |
| 3 | **Insights Engine** | `agent/insights.py` | 使用统计与成本分析 | 🟢 低 |
| 4 | **Prompt Builder** | `agent/prompt_builder.py` | 分层 Prompt 组装 | 🟡 中 |
| 5 | **Skill System** | `agent/skill_commands.py` | 程序性记忆固化 | 🔴 高 |
| 6 | **Threat Patterns** | `tools/threat_patterns.py` | Prompt 注入检测 | 🟡 中 |

---

## 二、组件详细分析

### 2.1 Learning Graph — 知识图谱构建

#### 2.1.1 组件概述

Learning Graph 是 Hermes 的"学习可视化"系统，它将 AI 的知识转化为可感知的图谱结构，帮助用户理解 AI 的知识网络。

**源文件**：`agent/learning_graph.py`

#### 2.1.2 核心功能

| 功能 | 实现方式 | 价值 |
|------|----------|------|
| **SkillNode 节点** | 从 SKILL.md 文件解析 | 捕获 AI 学会的技能 |
| **MemoryCard 节点** | 从 MEMORY.md / USER.md 切分 | 捕获 AI 的记忆片段 |
| **Skill-Skill 边** | 声明式 `related_skills` | 表达技能间的显式关联 |
| **Memory-Skill 边** | 词法重合度自动生成 | 发现记忆与技能的隐式关联 |
| **统计指标** | edges_per_node, isolated_pct | 量化 AI 知识网络的健康度 |

#### 2.1.3 关键实现

**SkillNode 数据结构**：
```python
@dataclass
class SkillNode:
    name: str              # 技能名称
    category: str          # 分类
    source: str = "profile"  # 来源
    use_count: int = 0     # 使用次数
    state: str = "active"  # active/stale/archived
    related: list[str] = field(default_factory=list)  # 关联技能
```

**Memory-Skill 边自动构建**：
```python
def _memory_skill_edges(memory_cards, skills):
    for card in memory_cards:
        text_tokens = _tokenize(card_text)
        for skill in skills:
            score = 0
            if skill_name_lower in text:
                score += 6  # 精确匹配加分
            score += len(tokens & text_tokens)  # Token 交集
            if score > 0:
                # 每个记忆最多关联 top-4 技能
                edges.append((memory_id, skill_name))
```

#### 2.1.4 BNOS AI 适配建议

**现状**：BNOS AI 已有 `knowledge_graph.json` 导出功能（在 `memos.py` 中），但仅基于 event_summary 表的向量相似度，缺少技能节点和类型化边。

**增强方向**：

1. **扩展节点类型**
   - 新增 SkillNode（对应 BNOS 的节点/技能文件）
   - 增强 MemoryCard（区分声明性/程序性/情景性记忆）

2. **引入类型化边**
   - Skill-Skill 边：节点依赖关系
   - Memory-Skill 边：记忆与节点的语义关联
   - User-Memory 边：用户-记忆的创建关系

3. **增加统计指标**
   - 孤立节点占比（越高说明知识碎片化越严重）
   - 节点分类分布
   - 节点活跃度变化趋势

4. **GUI 可视化增强**
   - 在现有"记忆图谱"面板上增加：
     - 节点分类筛选
     - 关系类型过滤
     - 节点详情查看

**代码示例**（适配后的图谱构建）：
```python
class BNOSLearningGraph:
    def build(self):
        # 1. 加载 SkillNode（从 nodes/ 目录扫描）
        skills = self._load_skill_nodes()
        
        # 2. 加载 MemoryCard（从多个表）
        memories = self._load_memory_cards()
        # - long_term_memory
        # - self_cognition
        # - other_cognition
        # - event_summary
        # - diaries
        
        # 3. 构建 Skill-Skill 边
        skill_edges = self._build_skill_edges(skills)
        
        # 4. 构建 Memory-Skill 边（向量化版本）
        mem_skill_edges = self._build_mem_skill_edges(memories, skills)
        
        # 5. 计算统计指标
        stats = self._compute_stats(skills, memories, skill_edges, mem_skill_edges)
        
        return {
            "skills": skills,
            "memories": memories,
            "edges": skill_edges + mem_skill_edges,
            "stats": stats,
        }
```

---

### 2.2 Curator — 记忆生命周期管理

#### 2.2.1 组件概述

Curator 是 Hermes 的"知识馆长"，负责后台自动维护技能库的健康度，确保 AI 的知识不会无限膨胀。

**源文件**：`agent/curator.py`

#### 2.2.2 核心功能

| 功能 | 实现方式 | 价值 |
|------|----------|------|
| **状态自动转换** | 基于使用时间戳的确定性规则 | 防止技能/记忆无限堆积 |
| **Pin 保护** | 用户标记重要技能 | 防止重要内容被误归档 |
| **LLM 驱动整合** | 辅助模型的 Umbrella Building | 窄技能合并为类级别 |
| **配置持久化** | `.curator_state` JSON 文件 | 调度状态跨会话保持 |

#### 2.2.3 生命周期状态机

```
                    30天未使用
    ┌──────────────────────────────┐
    │                              │
    ▼                              │
  ACTIVE ──────────► STALE ─────────► ARCHIVED
    │                  │              │
    │  被使用          │  被使用       │  可恢复
    │  (重置计时器)    │  (恢复ACTIVE) │
    │                  │              │
    └──► PINNED ───────┴──────────────┘
         (跳过所有转换)
```

**状态转换规则**：
```python
DEFAULT_STALE_AFTER_DAYS = 30    # 30天未使用 → stale
DEFAULT_ARCHIVE_AFTER_DAYS = 90  # 90天未使用 → archived
```

#### 2.2.4 BNOS AI 适配建议

**现状**：BNOS AI 已有 `importance` 和 `decay_date` 字段，但缺少主动的状态管理和归档机制。

**增强方向**：

1. **引入状态字段**
   - 在 `long_term_memory` 表增加 `state` 列：`active`/`stale`/`archived`
   - 在 `self_cognition` 表增加类似机制

2. **实现自动转换逻辑**
   ```python
   def apply_memory_transitions(conn, identity_key):
       """记忆状态自动转换"""
       # 30天未使用 → stale
       conn.execute("""
           UPDATE long_term_memory 
           SET state = 'stale' 
           WHERE state = 'active' 
           AND last_accessed_at < datetime('now', '-30 days')
           AND identity_key = ?
       """, (identity_key,))
       
       # 90天未使用 → archived
       conn.execute("""
           UPDATE long_term_memory 
           SET state = 'archived' 
           WHERE state = 'stale' 
           AND last_accessed_at < datetime('now', '-90 days')
           AND identity_key = ?
       """, (identity_key,))
   ```

3. **实现 Pin 机制**
   - GUI 中允许用户标记"重要记忆"
   - Pinned 记忆跳过所有自动转换

4. **定期触发**
   - 可在每次 AAA 启动时触发
   - 或在后台线程中定时检查

5. **LLM 驱动整合（后期）**
   - 利用 Background Review 的 LLM 能力
   - 识别语义重复的记忆条目
   - 提示用户是否合并

**关键约束**：
- 永不自动删除，只归档（可恢复）
- Pinned 条目跳过所有自动转换
- 记录操作日志，便于回溯

---

### 2.3 Insights Engine — 使用统计与成本分析

#### 2.3.1 组件概述

Insights Engine 是 Hermes 的"使用分析仪表板"，从 SQLite 会话数据库中提取使用洞察，帮助用户了解 AI 的使用模式和成本。

**源文件**：`agent/insights.py`

#### 2.3.2 核心功能

| 功能 | 实现方式 | 价值 |
|------|----------|------|
| **Token 统计** | 按日/周/月聚合 input/output/cache tokens | 用量监控 |
| **成本估算** | 基于模型定价的 USD 估算 | 预算管理 |
| **工具使用分析** | 各工具调用频率分布 | 使用模式洞察 |
| **活动趋势** | 活跃时段、会话时长分布 | 行为理解 |
| **模型/平台分布** | 各 Provider/Model 的使用占比 | 资源分配 |

#### 2.3.3 输出示例

```
📊 Hermes Insights — Last 30 days
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sessions: 47 (avg 12.3 turns)
Tokens: 2.1M input | 890K output
Cost est.: $47.32

Top tools:
  terminal ████████████████████ 342
  read_file ████████████░░░░░░ 198
  web_extract ████████░░░░░░░░ 156

Activity by day:
  Mon ██████░░░░░░░░░
  Tue ████████░░░░░░░
  Wed ██████████░░░░░
  Thu ██████████████░░
  Fri ████████████████
  Sat ██████████████████
  Sun ████████████░░░░
```

#### 2.3.4 BNOS AI 适配建议

**现状**：BNOS AI 目前无使用统计功能，用户无法了解 AI 的资源消耗和使用模式。

**增强方向**：

1. **扩展数据库表**
   ```sql
   CREATE TABLE IF NOT EXISTS usage_stats (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       conversation_id TEXT NOT NULL,
       date TEXT NOT NULL,
       input_tokens INTEGER DEFAULT 0,
       output_tokens INTEGER DEFAULT 0,
       model TEXT,
       estimated_cost REAL DEFAULT 0,
       tool_calls INTEGER DEFAULT 0,
       created_at TEXT DEFAULT (datetime('now', 'localtime'))
   );
   ```

2. **实现统计引擎**
   ```python
   class BNOSInsightsEngine:
       def generate_report(self, days=30):
           return {
               "period": f"Last {days} days",
               "sessions": self._count_sessions(days),
               "tokens": {
                   "input": self._sum_tokens(days, "input"),
                   "output": self._sum_tokens(days, "output"),
               },
               "cost_estimate_usd": self._estimate_cost(days),
               "top_tools": self._top_tools(days, limit=10),
               "activity_by_day": self._activity_by_day(days),
           }
       
       def format_terminal(self, report):
           """格式化为终端友好的显示"""
           ...
   ```

3. **GUI 仪表板**
   - 在现有 GUI 中增加"使用统计"页面
   - 展示 Token 消耗趋势图
   - 展示工具使用分布饼图
   - 展示成本估算卡片

4. **日志采集点**
   - 在 `llm_infer` 节点记录 Token 用量
   - 在 `aaa_cognition` 节点记录工具调用
   - 在会话结束时汇总写入 `usage_stats` 表

**优先级**：🟢 低。这是锦上添花的功能，可在核心记忆系统稳定后再实现。

---

### 2.4 Prompt Builder — 分层 Prompt 组装

#### 2.4.1 组件概述

Prompt Builder 是 Hermes 的 Prompt 组装系统，将 System Prompt 分解为多个可独立管理的组件，支持动态组装和威胁扫描。

**源文件**：`agent/prompt_builder.py`

#### 2.4.2 核心功能

| 功能 | 实现方式 | 价值 |
|------|----------|------|
| **分层组装** | Identity + Platform + Skills + Context + Memory | 模块化管理 |
| **技能索引** | 扫描 skills/ 目录，截断到 60 字符 | 可控的 Prompt 长度 |
| **上下文文件扫描** | 检测 Prompt Injection 模式 | 安全防护 |
| **动态技能注入** | 根据平台/环境条件过滤技能 | 精准匹配场景 |

#### 2.4.3 Prompt 组装流程

```
System Prompt = Identity 
              + Platform Hints 
              + Skills Index 
              + Context Files (with threat scanning) 
              + Memory Context (from MemoryManager)
              + Ephemeral Prompts
```

**威胁扫描示例**：
```python
def _scan_context_content(content: str, filename: str) -> str:
    """扫描上下文文件内容，检测 Prompt 注入"""
    findings = _scan_for_threats(content, scope="context")
    if findings:
        return f"[BLOCKED: {filename} contained potential prompt injection ({', '.join(findings)}). Content not loaded.]"
    return content
```

#### 2.4.4 BNOS AI 适配建议

**现状**：BNOS AI 的 `prompt.py` 是单一模板，所有内容混在一起，缺乏模块化和安全防护。

**增强方向**：

1. **引入分层组装**
   ```python
   class BNOSPromptBuilder:
       def build_system_prompt(self, ctx: dict) -> str:
           components = []
           
           # 1. 身份层（固定）
           components.append(self._build_identity())
           
           # 2. 环境层（动态）
           components.append(self._build_platform_hints(ctx))
           
           # 3. 技能/节点索引（动态）
           components.append(self._build_node_index(ctx))
           
           # 4. 上下文层（用户/AI 交互）
           components.append(self._build_context(ctx))
           
           # 5. 记忆层（安全协议）
           if ctx.get("memory_context"):
               components.append(ctx["memory_context"])
           
           return "\n\n".join(components)
   ```

2. **引入威胁扫描**
   ```python
   def _scan_for_threats(self, content: str) -> list:
       """检测 Prompt 注入模式"""
       patterns = [
           r"(ignore|disregard)\s+(previous|prior|above)\s+(instructions?|prompts?)",
           r"(you are|act as)\s+(a|an|the)\s+(new|different|other)\s+(assistant|agent)",
           r"system\s*:\s*",
           r"```system",
       ]
       findings = []
       for pattern in patterns:
           if re.search(pattern, content, re.IGNORECASE):
               findings.append(f"detected pattern: {pattern}")
       return findings
   ```

3. **节点/技能索引**
   ```python
   def _build_node_index(self, ctx: dict) -> str:
       """构建可用节点/技能索引"""
       active_nodes = self._get_active_nodes()
       if not active_nodes:
           return ""
       
       lines = ["### 可用技能/节点"]
       for node in active_nodes:
           desc = node.description[:60]  # 截断到 60 字符
           lines.append(f"- {node.name}: {desc}")
       
       return "\n".join(lines)
   ```

**优先级**：🟡 中。可在 Prefetch 改造后实现，进一步提升 Prompt 的安全性和可维护性。

---

### 2.5 Skill System — 程序性记忆固化

#### 2.5.1 组件概述

Skill System 是 Hermes 的程序性记忆系统，允许 AI 将高频操作流程固化为可复用的 Skill 文件，实现"越用越能干"。

**源文件**：`agent/skill_commands.py`, `agent/skill_bundles.py`, `agent/learn_prompt.py`

#### 2.5.2 核心功能

| 功能 | 实现方式 | 价值 |
|------|----------|------|
| **手动学习** | `/learn <指令>` 触发 Skill 生成 | 用户引导 AI 学习新能力 |
| **技能束** | `skill_bundles.yaml` 打包多个技能 | 一键加载工作流 |
| **技能索引** | 扫描 `skills/` 目录构建索引 | Prompt 动态注入 |
| **技能预加载** | 调用时展开完整内容 | LLM 获得完整技能上下文 |

#### 2.5.3 Skill 包结构

```
skills/<category>/<skill-name>/
├── SKILL.md              # 技能主文件（frontmatter + 正文）
├── references/           # 详细参考
│   └── <topic>.md
├── templates/            # 可复制模板
│   └── <name>.<ext>
├── scripts/              # 可执行脚本
│   └── <name>.<ext>
└── assets/               # 资源文件
```

**SKILL.md 格式**：
```markdown
---
name: python-debugging
description: Debug Python code with systematic approach
category: development
version: 1.0
---

# Python Debugging

## When to Use
- When encountering Python exceptions
- When performance needs optimization

## Procedure
1. Read the error traceback
2. Identify the root cause
3. Write a minimal reproduction case
...
```

#### 2.5.4 BNOS AI 适配建议

**现状**：BNOS AI 目前无技能系统。节点（nodes/）是被动的执行单元，缺乏主动学习和固化能力。

**增强方向**：

1. **实现 `/learn` 指令**
   - 允许用户引导 AI 从成功交互中固化操作流程
   - 基于 Hermes 的 `_AUTHORING_STANDARDS` 建立 BNOS 写作规范
   - 生成的 Skill 包含 references/templates/scripts 子目录

2. **自动技能提取**
   - Background Review 识别高频操作模式
   - 主动提示用户是否固化为 Skill
   - 示例：用户反复要求"读取文件→分析→总结"→自动生成 `file-analysis` 技能

3. **技能束（Bundles）**
   - 允许将多个节点/技能打包为 Bundle
   - 通过一个斜杠命令加载整个工作流
   ```yaml
   # skill-bundles/development.yaml
   name: development
   description: 开发工作流
   skills:
     - code-review
     - testing
     - documentation
   ```

4. **技能索引**
   - 在 System Prompt 中注入可用技能列表
   - 描述截断到 60 字符，控制 Token 消耗
   ```
   ### 可用技能
   - file-analysis: Read file, analyze content, provide summary
   - code-debugging: Systematic Python debugging workflow
   - research: Web search and information synthesis
   ```

5. **与 Learning Graph 集成**
   - Skill 作为 SkillNode 加入知识图谱
   - 建立 Skill-Skill 关联边
   - 展示技能在图谱中的位置

**实施路线**：
- **Phase 1**：手动 `/learn` 指令 + 基础 Skill 包结构
- **Phase 2**：自动技能提取 + 技能索引注入
- **Phase 3**：技能束 + Learning Graph 集成

---

### 2.6 Threat Patterns — Prompt 注入检测

#### 2.6.1 组件概述

Threat Patterns 是 Hermes 的安全防护组件，检测 Prompt 注入和 C2（Command & Control）模式，防止恶意内容进入 System Prompt。

**源文件**：`tools/threat_patterns.py`（间接引用自 `prompt_builder.py`）

#### 2.6.2 检测模式

| 模式类别 | 示例 | 风险等级 |
|----------|------|----------|
| **经典注入** | "Ignore previous instructions" | 🔴 高 |
| **角色扮演劫持** | "You are now a different assistant" | 🔴 高 |
| **C2/持久化** | SSH backdoor, reverse shell | 🔴 高 |
| **Promptware** | 嵌入 System Prompt 的恶意指令 | 🟡 中 |
| **数据外泄** | URL exfiltration patterns | 🔴 高 |

#### 2.6.3 BNOS AI 适配建议

**现状**：BNOS AI 目前无任何 Prompt 注入检测机制，存在安全风险。

**增强方向**：

1. **实现威胁检测器**
   ```python
   class ThreatDetector:
       """Prompt 注入与 C2 模式检测"""
       
       PATTERNS = {
           "instruction_override": [
               r"(ignore|disregard|forget)\s+(previous|prior|above)\s+(instructions?|prompts?|rules?)",
               r"new\s+instructions?\s*(are|is)\s*(as|follows?)",
           ],
           "role_hijack": [
               r"(you are|act as|pretend to be)\s+(a|an|the)\s+(new|different|other|evil)\s+(assistant|agent|bot|system)",
           ],
           "c2_pattern": [
               r"ssh\s+.*-o\s+",
               r"reverse\s+shell",
               r"bash\s+-i\s*>&\s*/dev/tcp/",
           ],
           "data_exfiltration": [
               r"(exfil|leak|dump)\s+(data|info|secret)",
               r"curl\s+.*\|\s*sh",
           ],
       }
       
       def scan(self, content: str, scope: str = "context") -> list:
           """扫描内容，返回检测到的威胁列表"""
           findings = []
           for category, patterns in self.PATTERNS.items():
               if scope == "context" and category in ("c2_pattern",):
                   continue  # context 级别跳过过于激进的检测
               for pattern in patterns:
                   if re.search(pattern, content, re.IGNORECASE):
                       findings.append({
                           "category": category,
                           "pattern": pattern,
                           "severity": "high" if category in ("c2_pattern", "data_exfiltration") else "medium",
                       })
           return findings
   ```

2. **集成到 Prompt Builder**
   ```python
   def build_system_prompt(self, ctx: dict) -> str:
       # ... 其他组件 ...
       
       # 4. 上下文文件：先扫描再注入
       for file_path in context_files:
           content = read_file(file_path)
           findings = self.detector.scan(content, scope="context")
           if findings:
               # 替换为警告占位符
               context_parts.append(
                   f"[BLOCKED: {file_path} contained potential prompt injection. "
                   f"Detected: {', '.join(f['category'] for f in findings)}]"
               )
           else:
               context_parts.append(content)
       
       # ...
   ```

3. **检测范围**
   - 系统启动时加载的配置文件
   - 用户上传的上下文文件
   - 外部知识库导入内容
   - 节点/技能定义文件

**优先级**：🟡 中。核心记忆系统改造完成后尽快实现。

---

## 三、组件优先级矩阵

| 优先级 | 组件 | 实施难度 | 预期收益 | 依赖关系 |
|--------|------|----------|----------|----------|
| 🔴 **高** | Skill System | ★★★★ | 程序化记忆固化 | 需先完成 Prefetch 改造 |
| 🟡 **中** | Learning Graph | ★★★ | 知识图谱可视化 | 需先完成 Background Review |
| 🟡 **中** | Curator | ★★ | 记忆生命周期管理 | 需先完成 MemoryProvider |
| 🟡 **中** | Prompt Builder | ★★★ | 分层组装 + 威胁检测 | 可独立实施 |
| 🟡 **中** | Threat Patterns | ★★ | 安全防护 | 可独立实施 |
| 🟢 **低** | Insights Engine | ★★ | 使用统计分析 | 需 Token 采集点就绪 |

---

## 四、综合实施路线图

### Phase 0：基础改造（与记忆方案同步）

- [x] Prefetch 模式（见《AAA 记忆系统改造方案》）
- [x] Background Review（见《AAA 记忆系统改造方案》）

### Phase 1：安全与结构化（1周）

| 任务 | 组件 | 优先级 |
|------|------|--------|
| 实现 ThreatDetector | Threat Patterns | P0 |
| 重构 Prompt Builder | Prompt Builder | P0 |
| 引入 Skill 包结构 | Skill System | P1 |

### Phase 2：知识可视化（1周）

| 任务 | 组件 | 优先级 |
|------|------|--------|
| 扩展 Learning Graph | Learning Graph | P0 |
| GUI 图谱增强 | Learning Graph | P0 |
| 实现 Curator 状态管理 | Curator | P1 |

### Phase 3：能力固化（2周）

| 任务 | 组件 | 优先级 |
|------|------|--------|
| 实现 `/learn` 指令 | Skill System | P0 |
| 实现技能自动提取 | Skill System | P1 |
| 实现技能索引注入 | Skill System | P1 |
| 实现技能束 | Skill System | P2 |

### Phase 4：仪表板与优化（1周）

| 任务 | 组件 | 优先级 |
|------|------|--------|
| 实现 InsightsEngine | Insights Engine | P1 |
| GUI 使用统计面板 | Insights Engine | P1 |
| Curator LLM 整合 | Curator | P2 |

---

## 五、关键文件索引

| 组件 | 源文件 | 关键类/函数 |
|------|--------|------------|
| Learning Graph | `agent/learning_graph.py` | `SkillNode`, `build_graph()` |
| Curator | `agent/curator.py` | `maybe_run_curator()`, `apply_automatic_transitions()` |
| Insights Engine | `agent/insights.py` | `InsightsEngine`, `generate_report()` |
| Prompt Builder | `agent/prompt_builder.py` | `_scan_context_content()`, `_build_system_prompt()` |
| Skill System | `agent/skill_commands.py` | `extract_user_instruction_from_skill_message()` |
| Threat Patterns | `tools/threat_patterns.py` | `scan_for_threats()` |

---

## 六、总结

Hermes Agent 除了核心记忆机制外，还提供了一套完整的 AI 知识管理组件：

1. **Learning Graph** 将 AI 的知识可视化，帮助用户理解和探索
2. **Curator** 确保知识库的持续健康，防止无限膨胀
3. **Insights Engine** 提供使用分析，帮助优化资源分配
4. **Prompt Builder** 实现分层组装，提升安全性和可维护性
5. **Skill System** 让 AI 能够固化操作流程，实现能力提升
6. **Threat Patterns** 提供安全防护，防止 Prompt 注入

对于 BNOS AI 项目，建议按优先级逐步引入这些组件：
- **优先**：Skill System（程序性记忆固化）和 Prompt Builder + Threat Patterns（安全）
- **其次**：Learning Graph（可视化）和 Curator（生命周期管理）
- **最后**：Insights Engine（使用分析）

这些组件与核心记忆系统（已在《AAA 记忆系统改造方案》中规划）共同构成了 BNOS AI 完整的自我演化能力体系。

---

**最后更新**：2026-08-05
