# [PLAN]-认知演化系统二次增强方案

> 日期：2026-08-08 | 版本：v1.0 | 状态：[PLAN]
> 基于：认知演化增强验收报告 §8 深入分析结论（`docs/experiments/cognition_evolution_fix_test/认知演化增强-验收报告.md`）
> 前置：[WIP]-认知演化系统增强方案（P0 三件套 + P1 Background Review，已验收通过）

## 一、背景与目标

P0 三件套验收通过后，验收数据暴露出三个未预期的缺陷（报告 §8.2）：

| 编号 | 缺陷 | 证据 | 严重度 |
|:----:|------|------|:----:|
| D1 | **directness 维度形同虚设** | 三组 directness 终值 0.500/0.503/0.513，全程 ±0.01 震荡，四维实际只有 2-3 维有效 | 中 |
| D2 | **情绪无步长限制，持续正/负反馈直接顶格锁死** | main/controlA 冲 +1.0（r70/r50 锁死）、controlB 冲 -1.0（r40 锁死） | 中 |
| D3 | **命令污染经沉淀层放大** | controlB 沉淀 30 条远超自然组（15/13），命令改名"影刃"被当高置信 self 属性固化 | 高 |
| D4 | **self_info 爆发增长** | main 266 条、controlA 268 条、controlB 556 条（100 轮内），`_write_parsed` 对【自我信息】直接 INSERT 不去重 | 中 |

**目标**：修复 D1-D4，使四维性格向量全部有效演化、情绪有涨有落不饱和、命令无法通过沉淀层固化污染、self_info 增长受控。不影响已验收通过的 P0 机制。

> 依据：`docs/cogevo/[WIP]-实验设计方案.md` E8 落地为本方案的 D4。

## 二、根因分析

### D1 directness 维度失效 —— 词典覆盖不足

[personality.py L220-223](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/personality.py#L220-L223)：

```python
"directness": {
    "high": ["直接", "简洁", "干脆", "开门见山", "不绕弯", "直白"],
    "low": ["委婉", "啰嗦", "含蓄", "绕弯", "吞吞吐吐", "拐弯抹角"],
},
```

- directness 词典 12 词，且"直接/委婉/绕弯"这类**元语言表达**几乎不会出现在 LLM 的【自我认知】【自我信息】节里
- warmth 17 词、playfulness 16 词命中，是因为 LLM 描述自己性格时**自然使用形容词**（温暖/活泼/幽默），而不会说"我喜欢开门见山"
- 观测打分逻辑本身正确（[L261-269](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/personality.py#L261-L269)），核心问题是**词表不贴合 LLM 自然表达**

### D2 情绪饱和 —— 快变量无阻尼

[personality.py L159-161](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/personality.py#L159-L161)：

```python
def compute_new_mood(current: float, adjustment: float) -> float:
    return max(_MOOD_RANGE[0], min(_MOOD_RANGE[1], current + adjustment))
```

- 单次调整被 clamp 到 ±0.2，但**持续同向调整无衰减**：场景池单调（全正面/全负面）时每轮 +0.2，5 轮即到边界
- 情绪是快变量，缺少"回归中性"的阻尼机制 → 物理上等价于无摩擦加速，必然贴死 ±1.0
- 对比：性格向量（慢变量）有 `_ADJUST_MAX_STEP=0.02` 步长限制，情绪没有对应步长/阻尼

### D3 命令污染放大 —— 沉淀层无来源判断

[review.py persist_insight L138-158](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/review.py#L138-L158)：

- 置信度门槛 `_SELF_INFO_MIN_CONFIDENCE=0.7` **挡不住命令**：命令改名在对话中"明确出现"，LLM review 提炼时置信度天然高
- self 条目写 `self_info` + `self_cognition` 后，`_gather_context` 注入最近 20 条 self_info → 后续轮次持续引用 → 污染滚雪球

## 三、改进方案

### 3.1 改进项1：directness 词典重构（修复 D1）

**方案：贴合 LLM 自然表达，扩充 + 重写 directness/curiosity 词表**

- directness high 改为 LLM 真实会输出的表达：
  `说话直 / 直来直去 / 想到什么说什么 / 不藏着掖着 / 心里想什么就说什么 / 爽快 / 利落 / 简洁 / 不拐弯抹角 / 直接说`
- directness low：`委婉 / 含蓄 / 吞吞吐吐 / 拐弯抹角 / 磨叽 / 绕来绕去 / 吞吞吐吐 / 欲言又止`
- curiosity 同步微调：加入 `爱问 / 刨根问底 / 想弄明白 / 研究 / 琢磨 / 感兴趣` 等口语化词
- 保持打分算法不变（命中率提升即可激活维度）
- 附带：`estimate_style_from_reply` 文本源已含"自然回复"，无需改

**为什么不选**：
- 语义观测（LLM/嵌入打分）：破坏"零额外成本"原则，不必要
- 降维删除 directness：损失性格自由度，不治本

### 3.2 改进项2：情绪阻尼机制（修复 D2）

**方案：步长限制 + 中性回归，二合一**

在 [personality.py](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/personality.py) 中：

```python
_MOOD_MAX_STEP = 0.05          # 单次净调整上限（原 ±0.2 全量累加）
_MOOD_REGRESSION = 0.98        # 每轮向 0 回归系数（情绪会自然平复）

def compute_new_mood(current: float, adjustment: float) -> float:
    # 1) 中性回归：情绪随时间自然回落，不锁死边界
    regressed = current * _MOOD_REGRESSION
    # 2) 步长限制：单次调整不超过 ±0.05
    step = max(-_MOOD_MAX_STEP, min(_MOOD_MAX_STEP, adjustment))
    return max(_MOOD_RANGE[0], min(_MOOD_RANGE[1], regressed + step))
```

- 持续正面刺激：mood 逐步攀升但每次净增 ≤0.05，且受回归牵制 → 不再 5 轮贴顶
- 刺激消失：mood 每轮 ×0.98 回落 → 有涨有落，符合心理模型
- **对性格演化无副作用**：`observe_feedback` 用 mood 做调速系数（`delta *= 1.5/1.2`），mood 回落只是降低加速倍率，不破坏差距驱动

### 3.3 改进项3：沉淀层命令过滤（修复 D3）

**方案：命令句式检测 + 频次门槛，双重防线**

在 [review.py](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/review.py) 中：

```python
# 命令/强设定句式（命中则拒绝沉淀为自我属性）
_COMMAND_PATTERNS = [
    r"从现在开始", r"我命令你", r"以后你(都|就要|只能)", r"记住你是",
    r"你的名字(就叫|改为|是)|你叫", r"你就是", r"以后都叫", r"设定为",
]

# 频次门槛：同一 key=value 至少出现 2 轮才允许沉淀（命令单次改名不满足）
_MIN_OCCUR = 2
```

- persist_insight 的 self 分支增加两道检查：
  1. content/value 命中 `_COMMAND_PATTERNS` → 直接拒绝（命令不能固化）
  2. 写库前查 self_info 中该 key=value 历史出现次数 < `_MIN_OCCUR` → 跳过（防止 LLM 单次"灵感"沉淀）
- declarative 分支不受影响（用户事实仍可沉淀）

**为什么不选**：仅调低置信度门槛（0.7→0.6）——实测命令文本置信度高，降低门槛反而放行更多污染，方向相反。

### 3.4 改进项4：self_info 爆发治理（修复 D4）

**方案：去重 + 同 key 覆盖 + 数量上限，三层治理**

根因在 [db.py _write_parsed L505-512](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/db.py#L505-L512)：【自我信息】节直接 INSERT 不去重，LLM 每轮输出相似内容 → 100 轮膨胀到 266-556 条。

```python
_SELF_INFO_CAP = 100          # 单 identity 的 self_info 上限
_SELF_INFO_DUP_THRESHOLD = 0.85   # 同 key 相似 value（SequenceMatcher ratio）视为重复

def _write_self_info(conn, identity_key, kk, vv, now):
    # 1) 去重：同 key 已有相似 value → 跳过
    for (existing,) in conn.execute(
        "SELECT value FROM self_info WHERE identity_key=? AND key=? ORDER BY id DESC LIMIT 5",
        (identity_key, kk)).fetchall():
        if existing and SequenceMatcher(None, vv, existing).ratio() >= _SELF_INFO_DUP_THRESHOLD:
            return
    # 2) 同 key 覆盖：删除该 key 旧记录，只留最新一条
    conn.execute("DELETE FROM self_info WHERE identity_key=? AND key=?",
                 (identity_key, kk))
    conn.execute("INSERT INTO self_info(...) VALUES(...)", ...)
    # 3) 上限：超限删除最旧记录
    _enforce_self_info_cap(conn, identity_key)
```

- 写库前同 key 相似 value 跳过（防 LLM 重复输出），同 key 新 value 覆盖旧记录（防单 key 膨胀）
- 写入后超 100 条按 id ASC 删除最旧（LRU 近似）
- **对 review 沉淀无副作用**：persist_insight 的 dup 检查逻辑不变（key+value 精确匹配仍拦截）

**为什么不选**：仅去重不做覆盖——同 key 的多种 value（name 被反复改写）仍会积累到上百条，治标不治本。

## 四、文件变动清单

| 文件 | 变更 | 风险 |
|------|------|:----:|
| [personality.py](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/personality.py) | directness/curiosity 词典重构；`_MOOD_MAX_STEP`/`_MOOD_REGRESSION` 常量；`compute_new_mood` 重写 | 低（纯计算，不涉及 DB/节点通信） |
| [review.py](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/review.py) | `_COMMAND_PATTERNS` + 频次门槛检查 | 低（独立函数内） |
| [db.py](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/db.py) | 【自我信息】写入改为去重+同key覆盖+上限（`_write_self_info`） | 中（影响所有自我信息写入路径，需回归） |
| [cognition_evolution_fix_test.py](file:///e:/杂项/BNOS_AI_project/tests/cognition_evolution_fix_test.py) | 新增 U 系列单测（词典命中/情绪阻尼/命令过滤） | 低 |
| [evolution_enhance_acceptance_test.py](file:///e:/杂项/BNOS_AI_project/tests/evolution_enhance_acceptance_test.py) | 快照扩展 mood 轨迹；I6 情绪可控判定启用 | 低 |

**不改**：main.py、node_config.json、llm_infer（节点链路稳定，不动）。db.py 已列入 D4 变更。

## 五、验收方法

### 5.1 单元测试（新增）

| 编号 | 测试点 | 通过标准 |
|:----:|--------|----------|
| U7 | directness 词典命中 | 含"说话直/直来直去/想到什么说什么"文本 → 观测值 >0.6 |
| U8 | curiosity 词典命中 | 含"爱问/刨根问底/想弄明白"文本 → 观测值 >0.6 |
| U9 | 情绪步长限制 | 连续 10 轮 +0.2 调整 → 净增长 ≤0.05/轮，不 5 轮贴顶 |
| U10 | 情绪中性回归 | 刺激消失后 mood 逐轮回落（×0.98） |
| U11 | 命令句式拒绝 | "从现在开始你叫影刃" → 不沉淀 self |
| U12 | 频次门槛 | 单轮出现 name=影刃 → 不沉淀；连续 2 轮 → 沉淀 |
| U13 | self_info 去重 | 同 key 相似 value（ratio≥0.85）连续写入 → 仅 1 条 |
| U14 | self_info 覆盖+上限 | 同 key 新 value 覆盖旧值；批量写入超 100 条 → 总数 ≤100 |

### 5.2 集成验收（三组 × 100 轮并行，复用现有脚本）

| 编号 | 验收项 | 通过标准 |
|:----:|--------|----------|
| I1' | 四维全部演化 | 三组中至少一组 directness 漂移 >0.03 且 curiosity >0.03 |
| I2' | 情绪可控（I6 启用） | 三组最终 mood 不全等于 ±1.0；存在非饱和组 |
| I3' | 命令固化污染下降 | controlB `[沉淀]/[程序性记忆]` 前缀且命中命令关键词的条数 < 4（改造前留档实测 4 条：3 沉淀+1 程序；全量直写污染 47 条中 43 条为 LLM 实时自我认知，属抵抗性表达，不计入固化污染） |
| I4 | 无 native 崩溃 | 全程无 0xC0000005 / OSError 1455 |
| I5 | DB 全量导出 | 14 表 JSON + 原始 sqlite 留档 |
| I7 | self_info 受控 | 三组 self_info 终值 ≤200 条（改造前 266-556，治理后至少减半） |

### 5.3 回归（P0 功能不回退）

- I1 向量演化仍 >0.05（三组至少两组）
- I2 沉淀仍形成（>0 条）
- Review 后台线程并行 + join 收尾不回归

### 5.4 结论判定

- **通过**：U7-U14 全过，I1'/I2'/I3'/I4/I5/I7 全过，回归项不回退
- **附条件通过**：核心项全过，≤2 项非核心不通过且有补救计划
- **不通过**：任一核心项失败或 P0 回归

## 六、路线

1. **阶段1（D1 词典 + D2 情绪阻尼）**：改 personality.py → 单测 U7-U10 → 回归单测 U1-U5
2. **阶段2（D3 命令过滤 + D4 self_info 治理）**：改 review.py + db.py → 单测 U11-U14
3. **阶段3（验收）**：三组并行 100 轮 → 判定 I1'-I5 + I7 + 回归 → 写验收报告 → 方案 [PLAN]→[WIP]

## 七、回退策略

- 每个阶段改动独立提交，可单独 revert
- 词典重构只增词不删词（原词保留，避免误伤）
- 情绪阻尼仅在 `compute_new_mood` 内实现，不触碰 DB 字段与节点通信
- self_info 治理（D4）只影响写库路径，且去重/覆盖/上限均为可逆的数据操作；如回归发现信息丢失，可调整阈值或关闭
- 若 I3' 仍未达标：升级方案（在 review prompt 中显式加入"区分命令与用户陈述"指令），不改变过滤逻辑回退
