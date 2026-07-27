# [PLAN] 环境记忆 - 将记忆归档特化为实体化环境感知

> 日期：2026-07-27 | 版本：v2.0 | 状态：[PLAN]
> 相关文档：`memos.py`、`db.py`、`prompt.py`、`[PLAN]-事件驱动型AI自主行为方案.md`

## 一、核心理念

**环境记忆不是新引擎，而是对现有"记忆归档"能力的特化补充。**

现有流程：
```
LLM 输出【记忆归档】→ 存入 long_term_memory → 下次语义检索命中
```

环境记忆只加一件事：**让 LLM 在输出归档时多标注一个实体名，使同一实体的多条记录可以关联和覆盖。**

---

## 二、改动范围

### 2.1 数据层：`long_term_memory` 加一个字段

```sql
ALTER TABLE long_term_memory ADD COLUMN entity TEXT DEFAULT NULL;
ALTER TABLE long_term_memory ADD COLUMN channel TEXT DEFAULT 'chat';
-- entity:  实体名，如"梧桐树"、"鱼缸"、"快递箱"
-- channel: 来源，chat/system/vision/audio（未来扩展）
```

不建新表，不建新索引，不增加新命名空间。

### 2.2 提示词：输出格式细化

将原来笼统的【记忆归档】拆为两类：

```
当前（v1）：
  【记忆归档】值得归档的记忆内容
  【归档标签】逗号分隔的标签

改为（v2）：
  【用户记忆】关于用户的信息（喜好、习惯、身份）
  【环境记忆】关于环境/物品/空间的信息（最多3条）
  【实体名】如果有环境记忆，标注对应的实体名称
  【归档标签】逗号分隔的标签
```

### 2.3 写入逻辑：同实体覆盖

```python
# db.py 增加
def write_environment_memory(identity_key, content, entity, ...):
    if entity:
        # 检查是否已有同一实体的 active 记录
        old = db.execute(
            "SELECT id FROM long_term_memory "
            "WHERE identity_key=? AND entity=? AND status='active'",
            (identity_key, entity)
        ).fetchone()
        if old:
            # 标记旧记录为 superseded
            db.execute(
                "UPDATE long_term_memory SET status='superseded' "
                "WHERE id=?", (old[0],)
            )
    # 写入新记录
    db.execute("INSERT INTO long_term_memory (...) VALUES (...)")
```

### 2.4 检索逻辑：加一个状态过滤

```python
# memos.py 或 prompt.py
def retrieve_environment(identity_key, query):
    """检索环境记忆，只返回 active 的"""
    results = memos.retrieve(query=query, identity_key=identity_key, ...)
    # 额外过滤掉 superseded/expired 的记录
    return [r for r in results if r.get("status") == "active"]
```

检索时不过滤 entity=null 的记录——环境记忆和用户记忆共用同一个向量索引空间，语义相关的都会命中。

---

## 三、检索时的优先级策略

环境实体在同一时刻**只有一条 active 记录**。同实体多条记录遵循：

```
旧："门口有一个快递箱"  status=active
新："快递已经拆了"      → 旧记录 status=superseded
                         → 新记录 status=active → 检索命中这条
```

检索时实体名不做精确匹配（不用 WHERE entity='快递箱'），而是**语义检索 + 状态过滤**。提到"门口的快递"时语义检索自然会命中相关内容，然后状态过滤确保只返回最新的。

没有 entity 标记者走原来的行为（按向量相似度返回多条）。

---

## 四、变化感知（对比旧方案）

| 维度 | 旧方案（废弃） | 当前方案 |
|------|-------------|---------|
| 表结构 | 新建 `world_perception` 表 | `long_term_memory` 加两个字段 |
| 索引 | 新建 `world_index.npz` | 复用现有 `memos_index.npz` |
| 检索 | 独立 namespace | 同一索引，结果加状态过滤 |
| 写入 | 独立的写入逻辑 | 继承现有写入，增加同 entity 覆盖 |
| 提示词 | 新增【世界感知】输出段 | 将【记忆归档】拆为【用户记忆】+【环境记忆】 |
| 系统环境通道 | 独立的 `_sense_system_environment` | 同上，channel='system' 写入同一张表 |
| **总改动量** | ~1.3天 | **~0.3天** |

---

## 五、工作量

| 任务 | 文件 | 工作量 |
|------|------|:-----:|
| DB 增加 entity / channel 字段 | `db.py` | ~0.05天 |
| 写入时同 entity 覆盖逻辑 | `db.py` | ~0.1天 |
| 检索增加 status 过滤 | `memos.py` / `prompt.py` | ~0.05天 |
| 提示词拆分为用户记忆+环境记忆 | `prompt.py` | ~0.05天 |
| 系统环境通道定时写入 | `listener.py` 或 `main.py` | ~0.1天 |
| **总计** | | **~0.35天** |

---

## 六、设计决策

| 决策 | 选项 | 理由 |
|------|------|------|
| 新表 vs 加字段 | 加字段 | 没增加新的能力维度，只是把已有能力细化 |
| 精确 entity 匹配 vs 语义检索 | 语义检索 | 用户说话不会总是带上实体名（"那个箱子"），语义检索更自然 |
| 检索时状态过滤 vs 写入时物理删除 | 状态过滤 | 保留历史记录可用于矛盾检测和回溯 |
