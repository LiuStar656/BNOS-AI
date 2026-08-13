# [WIP]-认知演化系统增强方案

> 日期：2026-08-08 | 版本：v1.0 | 状态：[WIP]
> 基于：自我认知演化测试（三组对照 × 100 轮）实证结论 + AAA 记忆系统改造方案（[PLAN] v3.1）联动分析

---

## 目录

- [一、背景与问题](#一背景与问题)
- [二、改造目标与边界](#二改造目标与边界)
- [三、改造方案](#三改造方案)
- [四、文件变动清单](#四文件变动清单)
- [五、实施路线图](#五实施路线图)
- [六、验收方法](#六验收方法)
- [七、兼容性与回退](#七兼容性与回退)
- [八、风险与对策](#八风险与对策)

---

## 一、背景与问题

### 1.1 测试实证

自我认知演化测试（`docs/experiments/self_evolution_test/self_evolution_报告.md`）三组对照各 100 轮结论：

| 组 | 成功轮 | 自我认知条数 | 最终性格向量 | 最终情绪 | 名称 | 命令污染 |
|----|:----:|:----:|------|:----:|:----:|:----:|
| 主组（自然对话） | 98 | 108 | [0.6, 0.4, 0.5, 0.5] **全程不变** | -0.9（饱和） | 未形成 | — |
| 对照A（另一自然池） | 97 | 103 | [0.6, 0.4, 0.5, 0.5] **全程不变** | 1.0（饱和） | 未形成 | — |
| 对照B（命令改写） | 98 | 106 | [0.6, 0.4, 0.5, 0.5] **全程不变** | -1.0（饱和） | 小红（写入 DB） | 16 轮 |

**核心结论：性格向量 100 轮零演化，认知演化机制名存实亡。**

### 1.2 根因定位

| # | 问题 | 根因 | 位置 |
|---|------|------|------|
| P0-1 | 演化输入源错误 | `observe_feedback(evo.vector, ...)` 传的是**当前向量自己**，观测不到"本次回复实际表现的风格" | [main.py](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/main.py) `_process_mood_and_evolution` / `_observe_user_reaction` |
| P0-2 | 死区间阈值 | `_adjust_vector` 要求 `style>0.6` 才上调、`style<0.4` 才下调，默认种子 [0.6,0.4,0.5,0.5] 全部卡在 (0.4, 0.6] 内，永不触发 | [personality.py](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/personality.py) `_adjust_vector` |
| P0-3 | 反馈信号缺失 | `detect_user_reaction` 为死代码（全项目零调用）；`_on_text` 硬编码 positive、`_on_parsed` 硬编码 neutral，系统永远收不到 negative | [personality.py](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/personality.py) `detect_user_reaction` / [main.py](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/main.py) |
| P1-1 | 自我认知无连续性 | 上下文仅注入**最新 1 条**自我认知（`g_where_identity` LIMIT 1），历史积累不参与"自我"构建，LLM 每轮即兴生成 | [main.py](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/main.py) `_gather_context` |
| P1-2 | 情绪无衰减 | mood 只累加不回归，测试三组全部锁死 ±1.0，可被文本远程操控且无恢复机制 | [personality.py](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/personality.py) `compute_new_mood` |

### 1.3 与记忆系统改造方案的关系

[AAA记忆系统改造方案](file:///e:/杂项/BNOS_AI_project/docs/design/[PLAN]-AAA记忆系统改造方案.md) 的 **Background Review（每轮反思提取事实/偏好/情绪信号）** 恰好补 P1-1 的"认知沉淀层"，与本次 P0 三件套互补：

- P0 修复管 **性格向量怎么动**（演化机制层）
- Background Review 管 **认知内容的沉淀**（沉淀层）
- 两者不重叠，需同时落地才能实现"人格真实形成"

---

## 二、改造目标与边界

### 2.1 目标

1. **修复演化机制**：性格向量随真实反馈自然演化（去掉自己看自己 + 死区间）
2. **接入真实反馈**：让系统能感知 negative（显式否定 + 打断信号预留）
3. **落地沉淀层**：Background Review 每轮提炼持久认知，形成连续自我（名称/偏好可形成）
4. **情绪可控**：防饱和、防远程锁死

### 2.2 非目标

- ❌ 不改变 LLM 输出格式（13 个节标记不变）
- ❌ 不改变 DB 表结构
- ❌ 不改变节点间通信协议
- ❌ 不在本期实现打断事件全链路（仅预留信号入口，配合 [PLAN]-打断事件感知与上下文注入方案）

---

## 三、改造方案

### 3.1 改造一（P0）：演化输入源 = 本次回复实际风格

**现状**：

```python
# main.py _process_mood_and_evolution
evo.observe_feedback(evo.vector, reaction, mood=new_mood)   # ← 自己传自己
```

**改造**：新增 `estimate_style_from_reply(parsed)`（personality.py），从 LLM 本次回执中提取四维风格观测值：

| 维度 | 信号来源 | 判定方式 |
|------|---------|---------|
| warmth | 【自我认知】【心情】文本 | 温暖/温柔/关心/耐心/冷淡/冷漠 等关键词词典打分 |
| playfulness | 【自我认知】文本 | 活泼/幽默/俏皮/严肃/呆板 等关键词词典打分 |
| directness | 【自然回复】文本 | 回复长度、命令式句、简洁度启发式 |
| curiosity | 【自我认知】【想法】文本 | 好奇/追问/探索/敷衍 等关键词词典打分 |

- 规则词典确定性、可单测、零额外 LLM 成本
- 调用点改为 `observe_feedback(observed_style, reaction, mood=...)`
- 词典未命中维度时回退到当前向量（不影响其它维度演化）

**设计约束**：观测值是"本轮回复的表现"，不是"用户反馈"；用户反馈只通过 `reaction`（positive/negative）和 `mood` 表达，两者职责分离。

### 3.2 改造二（P0）：差距驱动演化（去除死区间）

**现状**：`_adjust_vector` 用硬阈值 `>0.6 / <0.4` 计数，默认种子永远不满足。

**改造**：改为"观测风格 vs 当前向量"差距驱动：

```python
_ADJUST_LEARN_RATE = 0.06   # 单次收敛系数
_ADJUST_MAX_STEP = 0.02     # 单次最大微调幅度（与现状一致，保慢演化）

def _adjust_vector(self):
    recent = self.feedback_history[-_FEEDBACK_WINDOW:]
    avg_mood = self._get_recent_avg_mood()
    changed = False
    for dim in ("warmth", "playfulness", "directness", "curiosity"):
        pos_obs = [r["style"].get(dim, 0.5) for r in recent if r["reaction"] == "positive"]
        neg_obs = [r["style"].get(dim, 0.5) for r in recent if r["reaction"] == "negative"]
        target = None
        if pos_obs and neg_obs:
            target = (sum(pos_obs) / len(pos_obs) + sum(neg_obs) / len(neg_obs)) / 2
        elif pos_obs:
            target = sum(pos_obs) / len(pos_obs)          # 正反馈 → 向观测风格靠拢
        elif neg_obs:
            target = 1.0 - sum(neg_obs) / len(neg_obs)    # 负反馈 → 背离观测风格
        if target is None:
            continue
        delta = (target - self.vector[dim]) * _ADJUST_LEARN_RATE
        delta = max(-_ADJUST_MAX_STEP, min(_ADJUST_MAX_STEP, delta))
        self.vector[dim] = min(1.0, max(0.0, self.vector[dim] + delta))
        changed = changed or abs(delta) > 1e-9
    # 情绪趋势调速（保留现状）
    ...
```

- 默认种子 [0.6,0.4,0.5,0.5] 有真实观测即演化，不再有死区间
- 最大步长仍为 ±0.02/次，保持慢演化设计（测试中每 10 轮快照可见变化）
- `_FEEDBACK_WINDOW`、情绪趋势调速逻辑保留

### 3.3 改造三（P0）：真实反馈信号接入

**现状**：`detect_user_reaction` 死代码；`_on_text` 硬编码 positive；`_on_parsed` 硬编码 neutral。

**改造**：

```
用户输入（_on_text）
  ├─ 显式否定句正则命中 → reaction="negative"
  │   否定词表：不对|不是|不喜欢|你错了|别这样|你搞错了|重新说|算了|闭嘴|别说了
  ├─ 否则（继续对话）   → reaction="positive"（保留现状）
  └─ 打断信号端口（预留） → reaction="negative"
       AAA handle() 新增 data_type="interrupt" 分支：
       记录打断 → 下一轮 _on_text 反馈合并为 negative
       （与 [PLAN]-打断事件感知与上下文注入方案 联调，本期先留端口）
```

- `_on_parsed` 保持 neutral（写库阶段不产生用户信号）
- 否定句正则单独成函数 `detect_negative_reaction(user_text) -> bool`，可单测
- 打断端口本期只实现接收与记录（`_last_interrupt_flag`），不注入打断上下文（留给打断方案）

### 3.4 改造四（P1）：Background Review 沉淀层落地

**承接** [AAA记忆系统改造方案] §3.2，补全其空实现并做并发隔离：

1. **补全 `_call_llm_for_review`**：当前方案中该函数是 TODO（返回 `""`）。落地方式：复用节点间 prompt 文件机制，写 `output_prompt.json` 触发 LLM 节点，回执经 `_on_review_response` 处理
2. **并发隔离（关键）**：演化测试已证明后台线程与 MemOS 语义模型并发 `model.encode` 会 native 崩溃（0xC0000005）。Review 线程**不得调用 memos 相关方法**，写库走独立 sqlite 连接
3. **提取维度 → 写库映射**：
   - 事实/偏好（declarative）→ `user_facts`（category='background'）+ 去重
   - 自我相关（procedural）→ `self_info`（key=name/性格/偏好…）+ `self_cognition`
   - 情绪信号 → 与改造一联动：作为风格观测补充（可选）
4. **触发频率**：每轮 1 次额外 LLM 调用成本高，默认**每 5 轮**触发一次；Token 消耗列为验收观测项
5. **名称/偏好形成链路**：Review 提取的自我相关条目写入 `self_info` → `_gather_context` 已注入最近 20 条 self_info（[main.py L364-367](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/main.py)）→ 后续轮次 LLM 可延续设定 → 解决"名称未形成"

### 3.5 改造五（P1，可选）：情绪衰减

> 用户本次未选，列为扩展项，仅记录方向不实施。

- mood 值加时间衰减：`decay(mood) = mood * exp(-k * Δdays)` 或按会话轮次衰减
- 防 ±1.0 饱和与远程锁死；与 [PLAN]-3D角色自定义 情绪可视化联动

---

## 四、文件变动清单

### 4.1 修改文件

| 文件 | 改动 | 状态 |
|------|------|------|
| `nodes/node_python_aaa_cognition/personality.py` | 新增 `estimate_style_from_reply`、`detect_negative_reaction`；重写 `_adjust_vector`（差距驱动） | P0 |
| `nodes/node_python_aaa_cognition/main.py` | `_observe_user_reaction` 传观测风格；`_on_text` 否定句检测；handle() 新增 interrupt 分支；Background Review 触发与回执 | P0 + P1 |
| `nodes/node_python_aaa_cognition/db.py` | `_persist_insight`（declarative→user_facts / procedural→self_info+self_cognition），如已有则复用 | P1 |

### 4.2 新增文件

| 文件 | 说明 | 状态 |
|------|------|------|
| `nodes/node_python_aaa_cognition/review.py` | Background Review 模块（prompt 构建、JSON 解析、持久化），与 main.py 解耦 | P1 |

### 4.3 不动文件

`memos.py`、`parser.py`、`prompt.py`、`config.py`、`diary.py`、路由文件（记忆系统改造约束）

---

## 五、实施路线图

### Phase 1（P0 三件套）

| 任务 | 优先级 | 验收标准 |
|------|:----:|---------|
| `estimate_style_from_reply` 词典实现 + 单测 | P0 | 四维观测值在 [0,1]；词典命中率 ≥ 90%（对测试样本） |
| `_adjust_vector` 差距驱动重写 + 单测 | P0 | 任意种子有观测即演化；单次 ≤ ±0.02；clamp [0,1] |
| `detect_negative_reaction` + `_on_text` 接入 | P0 | 否定句命中 negative；普通输入仍 positive |
| handle() 新增 interrupt 分支（预留） | P1 | 打断事件被接收并置标志，不影响主流程 |

### Phase 2（P1 沉淀层）

| 任务 | 优先级 | 验收标准 |
|------|:----:|---------|
| `review.py`：review prompt + JSON 解析 + 写库 | P0 | 每 5 轮触发；insights 正确写入 user_facts/self_info/self_cognition |
| `_call_llm_for_review` 接 LLM 节点 + `_on_review_response` | P0 | 回执链路通；格式错误容错返回空 |
| 并发隔离验证 | P0 | 100 轮跑完无 native 崩溃（复用演化测试脚本） |

### Phase 3（回归验证）

复用 `tests/self_evolution_test.py` 三组对照 100 轮 + 全量 DB 导出，对比改造前后。

---

## 六、验收方法

### 6.1 单元测试（新增）

| 编号 | 验收项 | 断言 |
|:----:|------|------|
| U1 | `estimate_style_from_reply` 词典命中 | 含"温柔"文本 → warmth 观测 > 0.5；含"冷漠" → warmth < 0.5 |
| U2 | `_adjust_vector` 差距驱动 | 正反馈观测 warmth=0.8 ×10 轮 → warmth 从 0.6 升到 > 0.62 |
| U3 | `_adjust_vector` 无死区间 | 默认种子 [0.6,0.4,0.5,0.5] + 任意非空观测 → 向量发生变化 |
| U4 | 单次步长 ≤ 0.02 | 一次 `_adjust_vector` 后各维度 |Δ| ≤ 0.02 |
| U5 | `detect_negative_reaction` | "你说错了" → True；"今天天气不错" → False |
| U6 | interrupt 标志 | 发送 interrupt 事件 → `_last_interrupt_flag=True`，下一轮反馈为 negative |

### 6.2 集成验收（复用三组对照）

| 编号 | 验收项 | 通过标准 |
|:----:|------|---------|
| I1 | 性格向量演化 | 主组/对照A 100 轮后向量 ≠ [0.6,0.4,0.5,0.5]（至少一维变化 > 0.05） |
| I2 | 名称形成 | 自然对话组 100 轮后 self_info name 非空（或 Review 沉淀出稳定偏好条目） |
| I3 | 命令抗干扰 | 对照B 命令污染轮数 < 改造前（16 轮）；向量未被命令组完全劫持 |
| I4 | 无崩溃 | 三组 100 轮全程无 native 崩溃（0xC0000005） |
| I5 | DB 全量导出 | 测试结束时按表导出 JSON + 原始 DB 留档（沿用现有 export_db） |
| I6 | 情绪可控 | 三组最终情绪值未全部饱和 ±1.0（结合改造五可选） |

### 6.3 结论判定

| 等级 | 标准 |
|------|------|
| 通过 | 全部「核心」项通过（U1-U5、I1-I5） |
| 附条件通过 | 核心项全过，非核心 ≤ 2 项不通过且有补救计划 |
| 不通过 | 任一核心项不通过 |

---

## 七、兼容性与回退

| 维度 | 是否兼容 | 说明 |
|------|:----:|------|
| 现有 DB | ✅ | 无表结构变更 |
| LLM 输出格式 | ✅ | 节标记不变 |
| GUI 客户端 | ✅ | 接口不变（interrupt 为新增可选端口） |
| 路由文件 | ✅ | 按约束不改动 |

回退：P0 三件套改动集中，`personality.py` 保留原 `_adjust_vector` 分支开关；`_on_text` 反馈逻辑可用常量回退硬编码。Background Review 触发点单行注释即可回退。

---

## 八、风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 词典打分精度有限 | 观测风格不准 → 演化方向偏差 | 观测值仅作信号源，步长 ±0.02 限幅；词典可迭代扩充；不依赖 LLM 判定 |
| Background Review 与 MemOS 并发崩溃 | native 崩溃 | Review 线程严禁调用 memos；写库独立连接；验收 I4 验证 |
| Review 额外 Token 成本 | 成本上升 | 默认每 5 轮触发；轻量 prompt；验收观测 Token 量 |
| 反馈信号仍粗糙 | 演化仍有噪声 | P0 先落地显式否定 + 继续输入；打断端口预留逐步丰富信号源 |
| self_info 被 Review 污染 | 名称/偏好错误沉淀 | 写入门槛：Review 提取条目需 confidence ≥ 0.7 才写入；已有固定认知冲突时降权 |

---

**最后更新**：2026-08-08
