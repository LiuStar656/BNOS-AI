# [PLAN] 长文本分割向量化内存检索方案（Document Memory RAG）

> 日期：2026-08-08 | 版本：v1.0 | 状态：[PLAN]
> 相关文件：`document_rag.py`（新增）、`doc_parsers.py`（新增）、`main.py`、`prompt.py`、`memos.py`

## 目录

- [一、背景与现状评估](#一背景与现状评估)
- [二、目标](#二目标)
- [三、核心概念](#三核心概念)
- [四、方案设计](#四方案设计)
  - [4.1 新增/修改模块](#41-新增修改模块)
  - [4.2 doc_parsers.py — 文件解析](#42-doc_parserspy--文件解析)
  - [4.3 document_rag.py — 核心类](#43-document_ragpy--核心类)
  - [4.4 分割算法（512 token）](#44-分割算法512-token)
  - [4.5 Prompt 注入](#45-prompt-注入)
  - [4.6 主流程接线](#46-主流程接线)
- [五、分阶段实施计划](#五分阶段实施计划)
- [六、关键设计决策](#六关键设计决策)
- [七、风险评估](#七风险评估)
- [八、验收方法](#八验收方法)

---

## 一、背景与现状评估

| 现状 | 说明 |
|------|------|
| GUI 附件 | 已支持发送 txt/docx/pdf，缓存到 `gui/cache/attachments/`（`chat_input.py` + `message_manager.py`） |
| AAA 处理 | `main.py#L107` 接收 attachments，但仅提示 LLM 用 `file_read()` 主动读取 |
| 向量化 | `memos.py#L68` 已有 SentenceTransformer（384 维，all-MiniLM-L6-v2）可复用 |
| 缺失 | docx/pdf 解析库（`python-docx`/`pypdf` 均未安装）；无文档级内存检索 |

**痛点**：当前携带长文本附件时，LLM 需自己 file_read 全文，受上下文窗口限制无法处理长文档，且没有"按问题检索相关片段"的能力。

---

## 二、目标

附件（txt/docx/pdf）→ 解析为纯文本 → 按每片段最大 512 token 分割 → 向量化到内存 → 进入"自动向量检索回答状态"（区别于记忆检索）。每轮输入携带相似文本片段给 LLM 生成（其他 prompt 不变）；当用户连续超过 5 次输入相似度低于 0.4 时抛弃内存片段。

---

## 三、核心概念

| 概念 | 说明 |
|------|------|
| **文档态（DOCUMENT_ACTIVE）** | 加载文档成功后进入的状态，区别于普通对话 |
| **文档检索（doc retrieval）** | 每轮输入对**内存片段向量**做相似度检索，与长期记忆检索完全隔离 |
| **内存生命周期** | 会话级：加载 → 活跃 → 连续低相关抛弃，不落库、不进入图谱 |

### 3.1 状态机

```
INACTIVE ──携带文档附件──→ DOCUMENT_ACTIVE ──连续5次 max_sim<0.4──→ 抛弃内存 → INACTIVE
                              │
                              └──每轮输入：best_sim>=0.4 → 携带top-3片段，streak清零
                                                best_sim<0.4  → 不携带，streak+1
```

---

## 四、方案设计

### 4.1 新增/修改模块

```
nodes/node_python_aaa_cognition/
├── document_rag.py   ★ 新增 — DocumentMemory 类（内存态检索）
├── doc_parsers.py    ★ 新增 — txt/docx/pdf → 纯文本
└── main.py           ✎ 修改 — _gather_context 注入 doc_context
    └── prompt.py     ✎ 修改 — 模板新增 {doc_context}
```

### 4.2 doc_parsers.py — 文件解析

| 类型 | 方案 | 依赖 |
|------|------|------|
| txt | 标准库读取，UTF-8 → GBK 兜底 | 无 |
| docx | python-docx（段落+表格遍历） | `python-docx`（需安装） |
| pdf | pypdf 逐页提取（扫描件无文本层则警告跳过） | `pypdf`（需安装） |

```python
class DocumentParseError(Exception):
    """解析失败（文件损坏/类型不支持/无文本层）"""

def extract_text(path: str) -> str:
    """按扩展名分发解析，返回纯文本；失败抛 DocumentParseError"""
```

### 4.3 document_rag.py — 核心类

```python
class DocumentMemory:
    CHUNK_MAX_TOKENS = 512   # 每片段最大 token
    TOP_K = 3                # 每轮携带片段数
    SIM_THRESHOLD = 0.4      # 相似度阈值
    LOW_SIM_LIMIT = 5        # 连续低相似度抛弃阈值
    MAX_CHUNKS = 200         # 片段数上限（大文档保护）

    _active: bool
    _chunks: list[str]       # 分割后的片段
    _vecs: np.ndarray        # (N, 384) 内存向量矩阵
    _low_streak: int         # 连续低相似度计数

    def load_document(self, text: str) -> int:
        """解析+分割+向量化，成功返回片段数；失败抛错"""

    def retrieve(self, query: str) -> tuple[list[str], list[float]]:
        """对 query 编码，与 _vecs 点积求相似度，返回 top-k 片段及分数"""

    def track_relevance(self, query: str) -> bool:
        """
        best_sim >= 0.4 → streak=0，返回 True（携带片段）
        best_sim <  0.4 → streak+1，返回 False（不携带）
        streak > LOW_SIM_LIMIT（即第6次）→ clear()，返回 False
        """

    @property
    def active(self) -> bool:
        return self._active

    def clear(self):
        """清空内存片段与向量，退出文档态"""
```

**与 memos 的关系**：复用 `memos._get_model()` 的同一模型实例做编码，但**独立持有向量矩阵**，不写 `memos._embeddings`、不写 DB、不进知识图谱——严格隔离。

### 4.4 分割算法（512 token）

1. 全文按换行切段落，段落按 `。！？；\n` 切句
2. 贪心合并：句块累积至接近 512 token（tiktoken `cl100k_base` 计数）
3. 超出则按句边界截断，支持 32 token 重叠（可选开关）
4. 空块丢弃，片段数超过 `MAX_CHUNKS` 时截断

### 4.5 Prompt 注入

```markdown
### 文档参考（内存态，来自你本会话附带的文档）
根据当前问题从文档中检索到的相关片段：
[片段1]（相关度 0.87）…内容…
[片段2]（相关度 0.75）…内容…
```

- 文档态激活时：注入 `{doc_context}`，替换原"请用 file_read 读取"提示
- 非文档态：`{doc_context}` 为空串，**其他 prompt 完全不变**

### 4.6 主流程接线

```
_on_text(user_text, attachments)
  ├─ 若 attachments 含 txt/docx/pdf → document_rag.load_document(...)
  │    加载成功 → 文档态激活（streak 清零）
  ├─ 每轮 _gather_context：
  │    if document_rag.active:
  │        chunks, sims = document_rag.retrieve(user_text)   # top-3
  │        doc_context = format(chunks, sims)
  │        document_rag.track_relevance(user_text)            # 更新 streak
  └─ prompt.py 填充 {doc_context}
```

---

## 五、分阶段实施计划

| Phase | 任务 | 文件 | 交付标准 |
|:----:|------|------|---------|
| 0 | 安装依赖 `python-docx`、`pypdf`、`tiktoken` 到 AAA venv | `requirements.txt` | 三个库可 import |
| 1 | 文件解析 | `doc_parsers.py` | txt/docx/pdf 三格式可提取纯文本，损坏文件抛错不崩溃 |
| 2 | 分割 + 向量化 | `document_rag.py` | 512 token 分割正确，向量矩阵建立 |
| 3 | 检索 + 抛弃状态机 | `document_rag.py` | top-3 携带、streak 计数、>5 抛弃 |
| 4 | Prompt 注入 | `main.py` + `prompt.py` | 文档态注入片段，非文档态 prompt 不变 |
| 5 | 验收 | 见 §八 | 全部用例通过 |

---

## 六、关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 向量化实现 | 复用 memos 模型，独立矩阵 | 不重复加载模型，且隔离长期记忆 |
| token 计数 | tiktoken cl100k_base | 精确 512 token；DeepSeek 词表接近但不强制一致 |
| 低相关行为 | <0.4 不携带片段 | 无关输入不污染 LLM；仅累计 streak |
| 抛弃阈值 | 连续 6 次（>5）清空 | 用户原话"超过5次"即第 6 次触发 |
| 数据落库 | 不落库、不进图谱 | 会话级临时知识，避免污染长期记忆（吸取定位数据经验） |

---

## 七、风险评估

| 风险 | 影响 | 概率 | 缓解 |
|------|:----:|:----:|------|
| 扫描版 PDF 无文本层 | 中 | 中 | 警告提示"无法提取文字"，不崩溃 |
| 大文档（>1万token） | 中 | 中 | 片段数上限（MAX_CHUNKS=200）保护内存 |
| 编码异常（txt） | 低 | 低 | UTF-8→GBK 兜底链 |
| 与记忆检索混淆 | 高 | 低 | 独立类 + 独立矩阵 + 验收隔离用例 |
| tiktoken 下载失败 | 低 | 低 | 首次调用时异常兜底为字符近似 |

---

## 八、验收方法

### 8.1 验收环境与前置条件

| 项 | 要求 |
|------|------|
| AAA 节点 | `node_python_aaa_cognition` 可正常启动，venv 已安装 python-docx/pypdf/tiktoken |
| GUI | 附件发送功能可用（chat_input 已支持） |
| 测试文件 | 准备 txt/docx/pdf 各一份（各约 1500 token），另备一份损坏 pdf |

### 8.2 功能验收

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| F1 | txt/docx/pdf 解析 | 三种格式各上传一份 | 三种均提取成功进入文档态 | 均返回片段数 >0 | 核心 |
| F2 | 512 token 分割 | 上传 1000 token 文本 | 分割为 2 段（512+488），无超限段 | 每段 ≤512 token | 核心 |
| F3 | 相关检索 | 问"文档中关于 XX 的内容" | 携带相关片段 | Prompt 含 top-k 片段及分数 | 核心 |
| F4 | 非文档态不变 | 无附件正常对话 | prompt 与改造前完全一致 | `{doc_context}` 为空串 | 核心 |
| F5 | 携带格式 | 查看文档态完整 Prompt | 含 `### 文档参考` 段 | 格式正确 | 核心 |

### 8.3 状态机验收（边界行为）

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| S1 | 低相关计数 | 连续 4 次输入 <0.4 | 仍活跃，不携带片段 | active=True，streak=4 | 核心 |
| S2 | 抛弃触发 | 连续 6 次（>5）<0.4 | 内存清空，退回普通对话 | active=False，chunks=[] | 核心 |
| S3 | 中途命中 | 第 3 次输入 >0.4 | streak 清零，后续重新计数 | streak=0，携带片段 | 核心 |
| S4 | 新文档替换 | 文档态再传新文档 | 旧内存整体替换 | chunks 为新文档片段 | 核心 |
| S5 | 无附件不激活 | 未传附件直接对话 | 不进入文档态 | active=False | 核心 |

### 8.4 版本兼容与复用

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| V1 | 依赖版本锁定 | 查看 requirements.txt | 三个库已记录版本 | 版本号明确 | 核心 |
| V2 | 模型复用 | 文档态检索日志 | document_rag 与 memos 共用同一模型实例 | 无二次加载日志 | 核心 |

### 8.5 数据边界与容错（经验补强重点）

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| D1 | 不污染长期记忆 | 文档会话后查库 | `long_term_memory` 无新增记录 | 无文档片段记录 | 核心 |
| D2 | 不进知识图谱 | 触发图谱重建 | 图谱节点/边不含文档片段 | 图谱数据源无文档 | 核心 |
| D3 | 知识面板隔离 | 打开知识面板 | 不显示文档片段卡片 | 无文档片段 | 核心 |
| D4 | 损坏文件容错 | 上传损坏 pdf/docx | 提示错误，不崩溃，不进入文档态 | 抛 DocumentParseError 被捕获 | 核心 |
| D5 | 大文件保护 | 上传超长文档 | 片段数截断至 200 | 无内存溢出，正常检索 | 非核心 |
| D6 | LLM 语义容错 | 文档态下闲聊（不相关） | 不携带片段，仅计数 | 无无关片段注入 | 非核心 |

### 8.6 验收结论判定标准

| 验收等级 | 判定标准 |
|------|---------|
| **通过** | 所有核心项全部通过 |
| **附条件通过** | 核心项全通过，非核心项 ≤2 项不通过且有补救计划 |
| **不通过** | 任一核心项不通过 |

#### 验收记录模板

```
功能名称：长文本分割向量化内存检索（Document Memory RAG）
验收日期：____-____-____
验收人员：__________

功能验收：  ☐ F1  ☐ F2  ☐ F3  ☐ F4  ☐ F5
状态机：    ☐ S1  ☐ S2  ☐ S3  ☐ S4  ☐ S5
版本兼容：  ☐ V1  ☐ V2
数据边界：  ☐ D1  ☐ D2  ☐ D3  ☐ D4  ☐ D5  ☐ D6

验收结论：☐ 通过  ☐ 附条件通过  ☐ 不通过
问题记录：
_______________________________________________
```
