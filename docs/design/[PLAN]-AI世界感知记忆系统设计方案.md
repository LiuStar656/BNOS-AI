# [PLAN] 环境记忆 - 将记忆归档特化为实体化环境感知

> 日期：2026-07-27 | 版本：v3.0 | 状态：[PLAN]
> 相关文档：`memos.py`、`db.py`、`prompt.py`、`[PLAN]-事件驱动型AI自主行为方案.md`

## 目录

- [一、核心理念](#一核心理念)
- [二、分层架构设计（v3.0 新增）](#二分层架构设计v30-新增)
  - [2.1 实体记忆层（立即实施）](#21-实体记忆层立即实施)
  - [2.2 多模态感知层（推迟实施）](#22-多模态感知层推迟实施)
  - [2.3 能力声明系统（v3.0 新增）](#23-能力声明系统v30-新增)
- [三、改动范围](#三改动范围)
  - [3.1 数据层：`long_term_memory` 加字段](#31-数据层long_term_memory-加字段)
  - [3.2 提示词：输出格式细化](#32-提示词输出格式细化)
  - [3.3 写入逻辑：同实体覆盖](#33-写入逻辑同实体覆盖)
  - [3.4 检索逻辑：加状态过滤](#34-检索逻辑加状态过滤)
- [四、检索优先级策略](#四检索优先级策略)
- [五、感官能力声明设计（v3.0 新增）](#五感官能力声明设计v30-新增)
  - [5.1 设计目标](#51-设计目标)
  - [5.2 Prompt 集成](#52-prompt-集成)
  - [5.3 代码实现](#53-代码实现)
  - [5.4 动态更新机制](#54-动态更新机制)
- [六、变化感知（对比旧方案）](#六变化感知对比旧方案)
- [七、实施计划](#七实施计划)
  - [7.1 Phase 1 — 实体记忆层（立即）](#71-phase-1--实体记忆层立即)
  - [7.2 Phase 2 — 多模态感知层（推迟）](#72-phase-2--多模态感知层推迟)
- [八、设计决策](#八设计决策)
- [九、风险与缓解](#九风险与缓解)

---

## 一、核心理念

**环境记忆不是新引擎，而是对现有"记忆归档"能力的特化补充。**

现有流程：
```
LLM 输出【记忆归档】→ 存入 long_term_memory → 下次语义检索命中
```

环境记忆只加一件事：**让 LLM 在输出归档时多标注一个实体名，使同一实体的多条记录可以关联和覆盖。**

v3.0 新增核心理念：**采用分层架构 + 能力声明系统，支持渐进式功能上线。**

---

## 二、分层架构设计（v3.0 新增）

### 2.1 实体记忆层（立即实施）

**定义**：在纯文本对话中，让 AI 能够识别和记忆"实体"（物品、人物、地点等），同实体的信息自动更新覆盖。

**当前状态**：✅ 可立即实施，无需 ASR/Vision 节点支持

**能力范围**：
- 用户在文字对话中提到的实体（如"我的红杯子"、"阳台上的花"）
- AI 可以给实体标注唯一名称
- 同一实体的新信息自动覆盖旧信息

**用户价值**：
- "AI 怎么突然变聪明了？"
- "它居然记住了我的红杯子放在哪里！"

### 2.2 多模态感知层（推迟实施）

**定义**：当 ASR/Vision 节点上线后，AI 能够从听觉/视觉通道获取环境信息，触发实体记忆。

**当前状态**：❌ 需等待 ASR/Vision 节点就绪

**能力范围**：
- ASR 捕获的环境语音（如"这个杯子好漂亮"）
- Vision 捕获的屏幕画面（如识别到桌面上的杯子图片）
- OCR 识别的文字信息

**实施条件**：
- ASR 节点开发完成并能正常工作
- Vision 节点开发完成并能正常工作
- 相关 BNOS 连线配置就绪

### 2.3 能力声明系统（v3.0 新增）

**定义**：在 Prompt 中明确告知 LLM 当前可用的感知通道，防止幻觉，支持渐进增强。

**设计目标**：
1. **防幻觉**：防止 LLM 假装能"听到"或"看到"环境
2. **渐进增强**：当 ASR/Vision 上线时，无需修改 Prompt 逻辑
3. **可扩展**：支持未来添加新的感知通道

---

## 三、改动范围

### 3.1 数据层：`long_term_memory` 加字段

```sql
ALTER TABLE long_term_memory ADD COLUMN entity TEXT DEFAULT NULL;
ALTER TABLE long_term_memory ADD COLUMN channel TEXT DEFAULT 'chat';
-- entity:  实体名，如"梧桐树"、"鱼缸"、"快递箱"
-- channel: 来源，chat/system/vision/audio（未来扩展）
```

不建新表，不建新索引，不增加新命名空间。

### 3.2 提示词：输出格式细化

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

### 3.3 写入逻辑：同实体覆盖

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

### 3.4 检索逻辑：加状态过滤

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

## 四、检索优先级策略

环境实体在同一时刻**只有一条 active 记录**。同实体多条记录遵循：

```
旧："门口有一个快递箱"  status=active
新："快递已经拆了"      → 旧记录 status=superseded
                         → 新记录 status=active → 检索命中这条
```

检索时实体名不做精确匹配（不用 WHERE entity='快递箱'），而是**语义检索 + 状态过滤**。提到"门口的快递"时语义检索自然会命中相关内容，然后状态过滤确保只返回最新的。

没有 entity 标记者走原来的行为（按向量相似度返回多条）。

---

## 五、感官能力声明设计（v3.0 新增）

### 5.1 设计目标

| 目标 | 说明 |
|------|------|
| **防幻觉** | 明确告知 LLM 哪些通道可用，防止它假装能"看到"或"听到"环境 |
| **渐进增强** | 当 ASR/Vision 上线时，只需修改配置，无需修改 Prompt 逻辑 |
| **可扩展** | 支持未来添加新的感知通道（camera、microphone_array 等） |
| **用户信任** | AI 不会说出"我看到你桌上有个杯子"这种当前能力不支持的话 |

### 5.2 Prompt 集成

在 Prompt 模板中新增 `{perception}` 段：

```markdown
### 你的感知能力（重要）
当前可用的感知通道：
- 文本输入 (text): ✅ 可用
- 语音环境 (auditory): ❌ 不可用（ASR 未连接）
- 视觉环境 (visual): ❌ 不可用（Vision 未连接）
- 屏幕截图 (screen): ❌ 不可用
- 系统事件 (system): ❌ 不可用

**注意**：只能基于"文本输入"进行对话，不要假装能听到或看到东西。
当感知通道启用时，你将能够：
- 听觉：听到环境中的对话声
- 视觉：看到屏幕上的变化
- 但目前这些能力尚未启用。
```

### 5.3 代码实现

```python
# perception_capabilities.py (新增文件)

class PerceptionCapabilities:
    """AI 感知能力状态管理（v3.0 新增）"""
    
    # 默认配置：只有文本输入可用
    DEFAULT_CAPABILITIES = {
        "text": {
            "enabled": True,
            "description": "用户的文字输入"
        },
        "auditory": {
            "enabled": False,
            "description": "环境语音（ASR 捕获）"
        },
        "visual": {
            "enabled": False,
            "description": "屏幕画面（Vision 捕获）"
        },
        "screen": {
            "enabled": False,
            "description": "屏幕截图"
        },
        "system": {
            "enabled": False,
            "description": "系统事件（时间、通知等）"
        }
    }
    
    def __init__(self, config_path: str = None):
        self._config = self.DEFAULT_CAPABILITIES.copy()
        if config_path:
            self._load_from_file(config_path)
    
    def enable(self, channel: str):
        """启用指定感知通道"""
        if channel in self._config:
            self._config[channel]["enabled"] = True
    
    def disable(self, channel: str):
        """禁用指定感知通道"""
        if channel in self._config:
            self._config[channel]["enabled"] = False
    
    def get_perception_text(self) -> str:
        """生成 Prompt 中的感知能力描述"""
        lines = [
            "### 你的感知能力（重要）",
            "当前可用的感知通道："
        ]
        for channel, info in self._config.items():
            status = "✅ 可用" if info["enabled"] else "❌ 不可用"
            cn_name = self._channel_cn(channel)
            lines.append(f"- {cn_name} ({channel}): {status}（{info['description']}）")
        
        disabled = [
            self._channel_cn(k) for k, v in self._config.items() if not v["enabled"]
        ]
        if disabled:
            lines.append(
                f"\n**注意**：以下通道不可用，不要假装能感知到这些信息：{', '.join(disabled)}"
            )
        
        return "\n".join(lines)
    
    def _channel_cn(self, en: str) -> str:
        """通道名的中文映射"""
        return {
            "text": "文本输入",
            "auditory": "语音环境",
            "visual": "视觉环境",
            "screen": "屏幕截图",
            "system": "系统事件"
        }.get(en, en)
    
    def is_available(self, channel: str) -> bool:
        """检查指定通道是否可用"""
        return self._config.get(channel, {}).get("enabled", False)
    
    def _load_from_file(self, config_path: str):
        """从配置文件加载"""
        import json
        with open(config_path, 'r', encoding='utf-8') as f:
            custom = json.load(f)
        for key, value in custom.items():
            if key in self._config and isinstance(value, dict):
                self._config[key].update(value)
```

### 5.4 动态更新机制

#### 方式一：配置文件（静态）

```json
// perception_config.json
{
    "auditory": {"enabled": true, "description": "环境语音（ASR 已连接）"},
    "visual": {"enabled": true, "description": "屏幕画面（Vision 已连接）"}
}
```

#### 方式二：代码动态更新（节点启动时）

```python
# main.py 或节点启动逻辑中

# ASR 节点启动后自动启用
asr_node = ASRNode()
asr_node.start()
perception.enable("auditory")

# Vision 节点启动后自动启用
vision_node = VisionNode()
vision_node.start()
perception.enable("visual")
```

#### 方式三：BNOS 连线配置自动检测

```python
# plugins_discovery.py 或 engine.py

def detect_available_capabilities():
    """根据已连接的节点自动更新感知能力"""
    capabilities = PerceptionCapabilities()
    
    # 检查 ASR 节点是否已连接
    if asr_connector.is_connected():
        capabilities.enable("auditory")
    
    # 检查 Vision 节点是否已连接
    if vision_connector.is_connected():
        capabilities.enable("visual")
    
    # 检查系统事件源是否可用
    if system_events.is_listening():
        capabilities.enable("system")
    
    return capabilities
```

---

## 六、变化感知（对比旧方案）

| 维度 | 旧方案（v1.0 废弃） | 当前方案（v2.0） | v3.0 新增 |
|------|-------------|---------|---------|
| 表结构 | 新建 `world_perception` 表 | `long_term_memory` 加两个字段 | — |
| 索引 | 新建 `world_index.npz` | 复用现有 `memos_index.npz` | — |
| 检索 | 独立 namespace | 同一索引，结果加状态过滤 | — |
| 写入 | 独立的写入逻辑 | 继承现有写入，增加同 entity 覆盖 | — |
| 提示词 | 新增【世界感知】输出段 | 将【记忆归档】拆为【用户记忆】+【环境记忆】 | 新增 `{perception}` 段 |
| 系统环境通道 | 独立的 `_sense_system_environment` | 同上，channel='system' 写入同一张表 | — |
| 能力声明 | 无 | 无 | ✅ `PerceptionCapabilities` 系统 |
| 防幻觉 | 无 | 无 | ✅ 明确告知 LLM 可用通道 |
| 渐进增强 | 无 | 无 | ✅ 节点上线即自动启用 |
| **总改动量** | ~1.3天 | **~0.3天** | +0.15天 |

---

## 七、实施计划

### 7.1 Phase 1 — 实体记忆层（立即）

**目标**：让 AI 在纯文本对话中具备实体记忆能力

| 顺序 | 任务 | 文件 | 工作量 | 交付标准 |
|:----:|------|------|:------:|---------|
| 1 | DB 增加 entity / channel 字段 | `db.py` | 0.05天 | SQL 迁移脚本执行成功 |
| 2 | 写入时同 entity 覆盖逻辑 | `db.py` | 0.1天 | 旧记录自动标记 superseded |
| 3 | 检索增加 status 过滤 | `memos.py` | 0.05天 | 只返回 active 状态的记录 |
| 4 | 提示词拆分为用户记忆+环境记忆 | `prompt.py` | 0.05天 | LLM 输出包含【实体名】标签 |
| 5 | 能力声明系统实现 | `perception_capabilities.py`（新增） | 0.1天 | Prompt 包含 `{perception}` 段 |
| 6 | Prompt 集成 `{perception}` | `prompt.py` | 0.05天 | LLM 知道当前只有文本输入可用 |
| **合计** | | | **~0.4天** | |

**测试场景**：
```
用户：我买了一个新的红杯子
AI：（归档：实体="红杯子"，内容="用户买了新的红杯子"）

用户：我的红杯子漏水了
AI：（归档：实体="红杯子"，内容="红杯子漏水了"，旧记录自动 superseded）

用户：我的红杯子在哪里？
AI：（检索：语义命中"红杯子"，返回最新的 active 记录："红杯子漏水了"）
```

### 7.2 Phase 2 — 多模态感知层（推迟）

**目标**：当 ASR/Vision 节点就绪后，AI 能从听觉/视觉通道获取环境信息

| 顺序 | 任务 | 文件 | 工作量 | 前置条件 |
|:----:|------|------|:------:|---------|
| 1 | ASR 节点数据接入（auditory 通道） | `main.py` | 1天 | ASR 节点开发完成 |
| 2 | Vision 节点数据接入（visual 通道） | `main.py` | 1天 | Vision 节点开发完成 |
| 3 | 系统事件通道（system 通道） | `main.py` | 0.5天 | Env 节点开发完成 |
| 4 | 动态检测已连接节点 | `engine.py` | 0.5天 | Phase 1 完成 |
| 5 | 端到端测试 | — | 0.5天 | 所有节点就绪 |
| **合计** | | | **~3.5天** | |

**触发机制**：
```python
# 当 ASR 节点启动时
perception = PerceptionCapabilities("perception_config.json")
perception.enable("auditory")  # 自动启用听觉通道

# 当 Vision 节点启动时
perception.enable("visual")  # 自动启用视觉通道

# Prompt 自动更新
# "语音环境 (auditory): ✅ 可用（ASR 已连接）"
# "视觉环境 (visual): ✅ 可用（Vision 已连接）"
```

---

## 八、设计决策

| 决策 | 选项 | 理由 |
|------|------|------|
| 新表 vs 加字段 | 加字段 | 没增加新的能力维度，只是把已有能力细化 |
| 精确 entity 匹配 vs 语义检索 | 语义检索 | 用户说话不会总是带上实体名（"那个箱子"），语义检索更自然 |
| 检索时状态过滤 vs 写入时物理删除 | 状态过滤 | 保留历史记录可用于矛盾检测和回溯 |
| 能力声明 vs 无声明 | 能力声明 | 防止 LLM 幻觉，支持渐进增强 |
| 硬编码 vs 配置文件 | 配置文件 | 方便动态更新，无需修改代码 |

---

## 九、风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|:----:|:----:|---------|
| LLM 不遵循【实体名】标签格式 | 中 | 中 | 在 Prompt 中强化格式要求，代码层做容错处理 |
| entity 字段为空导致实体覆盖失效 | 低 | 低 | 代码层做非空检查，空值走普通归档逻辑 |
| 能力声明过于复杂干扰 LLM | 低 | 中 | 保持简洁，只声明可用性，不描述具体能力 |
| ASR/Vision 节点延迟上线 | 中 | 高 | Phase 1 独立实施，实体记忆层可立即生效 |
| 多模态感知后 LLM 行为异常 | 高 | 低 | 分阶段上线，每次只启用一个通道，逐步验证 |
