# BNOS GUI — 知识库面板开发方案

> 日期：2026-07-26 | 状态：**OK** ✅

---

## 一、定位

GUI 内的知识可视化组件，取代原有的 `node_python_logseq_writer` 独立节点方案。

**核心原则**：
- AAA 的 DB（`chatbot.db`）是知识的**唯一持久化来源**
- GUI 直接读 DB，不做数据同步
- 不额外启动进程，不增加延迟

### 为什么不做 Logseq 文件写入

| 方案 | 问题 |
|------|------|
| 独立 logseq_writer 节点 | 只为 `open().write()` 开一个进程，不值 |
| AAA 顺带写 markdown | 两份数据（DB + .md），可能不同步 |
| **GUI 读 DB 展示** | 唯一来源，无同步问题，自由渲染 |

用户需要浏览知识时，**Logseq/Obsidian 应作为可选的导出目标**，而不是实时写入目标。

---

## 二、数据来源

直接从 AAA 的 `chatbot.db` 读取（`gui/live2d/` 已有关键字读取示例）。
语义关联数据来自 `memos` 模块生成的向量索引文件（`memos_index.npz`）。

### 核心表

| 表名 | 内容 | 展示方式 |
|------|------|---------|
| `user_facts` | 用户事实（`category=background` 用户画像，`category=preference` 偏好） | 卡片列表，按分类分组 |
| `fixed_cognition` | 固定认知（跨对话的长期自我认知） | 置顶卡片 |
| `self_info` | AI 的自我信息键值对 | 键值表 |
| `other_cognition` | AI 对用户的认知 | 时间线 |
| `event_summary` | 对话事件摘要 | 时间线 |
| `self_cognition` | 自我认知变化历史 | 时间线 |
| `feelings` | 心情与想法 | 情感卡片 |
| `long_term_memory` | 长期记忆（含向量索引） | 知识图谱节点 |

### 向量索引

`memos.py`（AAA 节点内）使用 SentenceTransformer 为知识条目生成 384 维向量：

- 索引文件：`shared/memos_index.npz`（与 `chatbot.db` 同级）
- 模型：`all-MiniLM-L6-v2`，首次使用时自动下载（~80MB）
- 更新时机：AAA 写入新知识时增量更新，启动时全量重建

### 查询示例

```python
import sqlite3

DB_PATH = "../shared/chatbot.db"  # 相对 gui/ 目录

def get_knowledge_entries(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    result = {}

    # 用户画像（background）
    cursor.execute(
        "SELECT content FROM user_facts WHERE category='background' ORDER BY id DESC LIMIT 20"
    )
    result["background"] = [row[0] for row in cursor.fetchall()]

    # 用户偏好（preference）
    cursor.execute(
        "SELECT content FROM user_facts WHERE category='preference' ORDER BY id DESC LIMIT 50"
    )
    result["preference"] = [row[0] for row in cursor.fetchall()]

    # 固定认知
    cursor.execute(
        "SELECT key, value FROM fixed_cognition ORDER BY updated_at DESC"
    )
    result["fixed"] = {row[0]: row[1] for row in cursor.fetchall()}

    # AI 自我信息
    cursor.execute(
        "SELECT key, value FROM self_info ORDER BY id DESC LIMIT 20"
    )
    result["self_info"] = {row[0]: row[1] for row in cursor.fetchall()}

    conn.close()
    return result
```

### 更新时机

- 打开知识库面板时**全量读取**
- 面板可见期间，每隔 30 秒自动刷新（用 DB 修改时间或 `id` 最大变化检测）
- 用户手动点击刷新按钮
- **不**实时轮询（知识写入频率低，实时性要求不高）

---

## 三、UI 设计

### 3.1 入口

- 侧边栏新增"知识库"按钮（在"设置"和"节点管理"之间）
- 点击打开 `KnowledgePanel` 浮动面板

### 3.2 布局 — 双视图模式

面板支持两种视图，通过顶部 Tab 切换：

#### 视图 A：卡片列表（默认）

```
┌─────────────────────────────────────────┐
│  知识库                          [关闭] │  ← 标题栏
├─────────────────────────────────────────┤
│  [列表] [图谱]                          │  ← 视图切换
├─────────────────────────────────────────┤
│  [全部] [用户画像] [偏好] [固定认知] [情感] │  ← 分类筛选
├─────────────────────────────────────────┤
│                                         │
│  ┌─ 用户画像 ──────────────────────┐    │
│  │ 张三, 程序员, 喜欢喝冰美式      │    │  ← 分类卡片
│  │ 居住在杭州, 养了一只猫         │    │
│  └────────────────────────────────┘    │
│                                         │
│  ┌─ 偏好 ──────────────────────────┐    │
│  │ 🏷 饮食 · 冰美式               │    │  ← 带标签的知识卡片
│  │ 🏷 音乐 · 古典乐               │    │
│  │ 🏷 电影 · 星际穿越             │    │
│  └────────────────────────────────┘    │
│                                         │
│  ┌─ 固定认知 ──────────────────────┐    │
│  │ ⭐ 我的名字: Neu                 │    │  ← 置顶，带确认次数
│  │ ⭐ 我的性格: 温柔, 好奇         │    │
│  └────────────────────────────────┘    │
│                                         │
│  ┌─ 最近情感 ──────────────────────┐    │
│  │ 😊 开心 (07-26 14:30)           │    │
│  │ 🤔 好奇 (07-26 13:15)           │    │
│  └────────────────────────────────┘    │
│                                         │
│  共 24 条知识              [导出] [刷新] │  ← 底部操作栏
└─────────────────────────────────────────┘
```

#### 视图 B：知识关联图谱

```
┌─────────────────────────────────────────┐
│  知识库                          [关闭] │
├─────────────────────────────────────────┤
│  [列表] [图谱]                          │  ← 选中"图谱"
├─────────────────────────────────────────┤
│                                         │
│            ┌──── 冰美式 ────┐            │
│           /    sim:0.82      \           │
│    ┌─ 咖啡因过敏 ─┐      ┌─ 程序员 ─┐    │  ← 节点=知识条目
│    │  sim:0.75    │      │ sim:0.68 │    │    边=语义相似度
│    └──────────────┘      └──────────┘    │    粗细=相似度值
│           \                /             │
│            ┌── 喜欢写 Python ──┐          │
│            │    sim:0.71      │          │
│            └─────────────────┘          │
│                                         │
│  相似度阈值: [====●=========] 0.60     │  ← 滑动条调节
│  共 24 节点 · 86 条关联    [重新计算]   │
└─────────────────────────────────────────┘
```

图谱交互：
- **节点拖拽**：自由排列布局
- **悬停高亮**：鼠标悬停节点，高亮其一跳邻居
- **点击聚焦**：点击节点，显示详情卡片（内容 + 关联条目列表）
- **缩放/平移**：滚轮缩放，拖拽画布
- **阈值滑块**：调节相似度阈值，控制边的稀疏程度

### 3.3 功能

| 功能 | 说明 |
|------|------|
| **标签分类** | 按 category 分组展示，支持 Tab/按钮切换 |
| **知识卡片** | 带标签、时间的卡片展示，固定认知置顶带星标 |
| **搜索过滤** | 关键词搜索知识条目 |
| **知识图谱** | 基于向量相似度的力导向图（所有可嵌入表 + `long_term_memory`） |
| **相似度阈值** | 滑动条控制图谱边的密度 |
| **导出 Logseq** | 一键导出为 Logseq 兼容的 markdown 格式 |
| **导出 Obsidian** | 一键导出为 Obsidian 兼容的 markdown 格式 |
| **刷新** | 手动/自动刷新数据 |
| **删除（可选）** | 右键删除知识条目（仅影响 DB，AI 无法恢复） |

### 3.4 情绪可视化（可选增强）

从 `feelings` 表取出最近 N 条心情记录，展示情感趋势：

```
开心 ████████████████████░░ 80%
好奇 ██████████░░░░░░░░░░ 40%
平静 ██████████████████░░ 70%
难过 ░░░░░░░░░░░░░░░░░░░░ 5%
```

---

## 四、图谱引擎设计

### 4.1 数据流

```
AAA 侧:
  写入知识条目（user_facts / fixed_cognition 等）
    └─ memos.py 增量生成向量 → 存入 memos_index.npz

GUI 侧:
  打开知识库面板 → 读取 DB + 读取 memos_index.npz
    └─ KnowledgeGraphWidget
         ├─ 加载所有条目文本 + 对应向量
         ├─ 两两计算余弦相似度（内积）
         ├─ 过滤 > 阈值的边
         └─ 渲染力导向图
```

### 4.2 向量关联计算

```python
# gui/widgets/knowledge_graph.py（示意）
import numpy as np

def build_graph(entries: list[dict], embeddings: np.ndarray, threshold: float = 0.6):
    """构建图谱节点和边"""
    nodes = [{"id": e["id"], "label": e["content"][:20], "category": e["category"]}
             for e in entries]
    sims = embeddings @ embeddings.T  # 余弦相似度矩阵（已归一化）
    edges = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            s = float(sims[i][j])
            if s >= threshold:
                edges.append({"source": i, "target": j, "weight": s})
    return nodes, edges
```

### 4.3 可视化方案

使用 **PySide6 原生 QGraphicsView** 实现力导向图，避免引入额外依赖：

| 组件 | 职责 |
|------|------|
| `QGraphicsScene` | 管理节点和边图形项 |
| `QGraphicsEllipseItem` | 知识节点（圆形，颜色按 category 区分） |
| `QGraphicsLineItem` | 关联边（宽度随相似度变化） |
| 力导向布局 | 简单弹簧算法（每次刷新迭代 50 步） |
| 滑块控件 | 调节相似度阈值，实时过滤边 |

---

## 五、导出格式

### Logseq 导出

```
- 冰美式
  tags:: 饮食, 偏好
  source:: AI 认知 (2026-07-26)

- 武侠小说
  tags:: 阅读, 偏好
  source:: AI 认知 (2026-07-26)
```

### Obsidian 导出

```markdown
---
tags: [饮食, 偏好]
source: AI 认知 (2026-07-26)
---

冰美式
```

---

## 六、文件变动清单

| 文件 | 改动 | 工作量 |
|------|------|:----:|
| `nodes/node_python_aaa_cognition/memos.py` | 扩展向量索引：增加 `user_facts` / `fixed_cognition` / `feelings` 等表的向量生成和检索 | 1h |
| `gui/widgets/knowledge_panel.py` | **新建**，知识库面板主组件（卡片列表 + 图谱双视图） | 2h |
| `gui/widgets/knowledge_graph.py` | **新建**，力导向图可视化组件 | 1.5h |
| `gui/widgets/__init__.py` | 注册新组件 | — |
| `gui/widgets/sidebar.py` | 新增"知识库"按钮入口 | 0.2h |
| `gui/main_window.py`（可选） | 快捷键绑定（如 Ctrl+K 打开知识库） | 0.3h |

**总工作量**: 约 5-6h

---

## 七、与其他组件的关系

```
AAA chatbot.db                    ← 知识唯一来源
  ├─ memos_index.npz              ← 语义向量索引（memos.py 维护）
  ↓
GUI KnowledgePanel                ← 可视化展示
  ├─ 卡片列表视图                  ← 按分类浏览
  ├─ 知识图谱视图                  ← 语义关联探索（基于向量相似度）
  └─ 导出
       ├─ Logseq .md              ← 用户手动导出
       └─ Obsidian .md            ← 用户手动导出
```

与 `turn_taking`、`live2d` 等无数据依赖，是纯展示组件。
