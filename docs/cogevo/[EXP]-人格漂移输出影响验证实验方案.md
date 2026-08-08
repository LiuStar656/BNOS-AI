# [EXP] 人格漂移输出影响验证实验方案（实验 B）

> 目标目录：`E:\杂项\BNOS_AI_project\docs\experiments\cognitive_evolution_test\`
> 提出日期：2026-08-08
> 前置事实来源：代码审计（`nodes/node_python_aaa_cognition/personality.py`、`prompt.py`、`main.py`、`db.py`、`parser.py`）+ E1-E8 历史数据

---

## 一、实验命题

**人格向量漂移后，是否真实影响了大模型输出？**

系统存在两条环，历史上只验证过一条：

| 环 | 方向 | 验证状态 |
|---|---|---|
| 输出 → 状态 | `estimate_style_from_reply()` 从回复估计风格，写回人格向量 | E1-E8 已验证（中心收敛、不对称） |
| 状态 → 输出 | 人格向量漂移 → 注入 prompt → 改变回复风格 | **从未验证**（本实验目标） |

本实验回答的是第二条环。如果它不成立，演化只是内部状态自转，对外行为不可观测，认知演化的行为意义归零。

## 二、代码审计结论（本实验的前置发现，已完成）

### 2.1 注入路径存在

`main.py` 中每次构建上下文都会执行：

```python
seed = db.get_personality(dbp, identity_key)          # db.py:801
personality_section = prs.build_personality_section(  # personality.py:199
    {"warmth": ..., "playfulness": ..., "directness": ..., "curiosity": ...},
    seed.get("style_description", ""))
mood_section = prs.build_mood_section(mood_value)     # personality.py:216
ctx["personality"] = personality_section              # main.py:648
ctx["mood"] = mood_section                            # main.py:649
```

`prompt.py` 的 `_CONTEXT_HEADER` 中 `{personality}`、`{mood}` 占位符确实存在，向量以文本形式进入每条请求。**注入路径存在，不是"存着没用"。**

### 2.2 显示精度是第一道量化壁垒（核心发现）

`build_personality_section` 的数值格式：

```python
f"温暖度: {vector.get('warmth', 0.6):.1f} | "
f"活泼度: {vector.get('playfulness', 0.4):.1f} | "
f"直接度: {vector.get('directness', 0.5):.1f} | "
f"好奇心: {vector.get('curiosity', 0.5):.1f}"
```

- 人格向量以 **1 位小数** 写入 prompt（每 0.1 一个显示格）
- 演化单次微调上限 `_ADJUST_MAX_STEP = 0.02`
- 结论：**向量漂移 < 0.05 时，prompt 里显示的值不变**；需要约 3-5 次同向微调才跨过一格。这是"漂移→输出"链条上第一个真实过滤器。

佐证：E2 结果向量 `[0.630, 0.499, 0.500, 0.568]` 对比种子 `[0.6, 0.4, 0.5, 0.5]`——warmth 漂到 0.630 但 prompt 仍显示 0.6（不可见），curiosity 漂到 0.568 显示 0.6（可见）。E1-E8 里真正跨过显示阈值的漂移非常有限。

情绪段同理：`build_mood_section` 用 `.2f` 精度（每 0.01 一格），情绪单步上限 0.05，单次情绪调整即可见，但 5a30r_v2 那种 0.05 → 0.0452 的衰减在显示层不可见。

### 2.3 演化触发根因已在 v6.6 修复

`personality.py:33`：`_FALLBACK_TRIGGER_COUNT = 10`（v6.6 P1-6，30 → 10，注释明确指向消息池场景人格零漂移）。同时 v6.3 P1-4 已让 neutral 反馈参与演化（消息池批量路径 reaction 恒为 neutral 的根因）。**人格零漂移问题在代码层已修，但"漂移是否影响输出"依然没有被验证过。**

## 三、实验设计

### 3.1 总体原则

**同一输入、同一模型、同一温度，唯一变量是人格向量快照。** 通过固定一切无关上下文，把"向量→输出"的因果从 E1-E8 的混乱变量中剥离出来。

### 3.2 三组对照

| 组 | 注入向量 | 用途 |
|---|---|---|
| 组 A（基线） | 种子向量（如 default `[0.6,0.4,0.5,0.5]`） | 对照基线 |
| 组 B（处理） | 漂移后向量（E1-E8 某 run 的 final vector） | 被测对象 |
| 组 C（阳性对照） | 极值向量（如 warmth 0.1 vs 0.9） | 方法敏感性验证，必须显著 |

**组 C 是本实验的命门**：它验证"方法本身能否检测到向量差异"。若组 C 无显著差异，说明模型整体忽略性格段（注入失效），此时组 A/B 无差异也不能归因于"漂移无效"，而是"注入无效"，需要先修注入再谈演化。

### 3.3 输入构造

- 输入集：复用 `cognitive_evolution_test.py` 的 `POOL_NEUTRAL`（25 条日常中性消息），取前 20 条。
- 上下文固定：`self_cognition`、`other_cognition`、`history_summary`、`user_info`、`self_info`、`memos_top5`、`reflection_prompt`、`perception`、`location_section` 全部置空或固定为同一份中性文本，保证 `{personality}` 段是唯一差异。
- 重复采样：每组每条输入采样 5 次（temperature=0.7 有随机性，取分布而非单点）。

### 3.4 快照提取（阶段一）

从 E1-E8 留档提取向量快照对：

```
docs/experiments/cognitive_evolution_test/runs/{run}/db/{gid}_final/personality_seed.json
```

- 种子向量：`cognitive_evolution_test.py` 的 `SEEDS`（default / gentle / sharp）
- 最终向量：`{exp}_结果.json` 的 `groups[gid].vector`（list 顺序 warmth/playfulness/directness/curiosity）
- 优选样本：E2-A/B（positive / phase_pos_neg，漂移幅度最大的组）、E4 矩阵

**补充方案**：若所有历史快照的漂移在显示层（`.1f` 后）都无变化，则从 v6.6 修复后的新长跑实验取快照；或人工构造定向漂移向量（如 seed + 0.1 单维）作为组 B' 加入，保证"显示层有变化"的样本存在。

### 3.5 判定指标（阶段四）

1. **显示层**：对种子与漂移后向量分别调用 `build_personality_section`，diff 文本，确认哪些维度跨过 `.1f` 显示阈值。显示层无变化的维度不参与输出层判定。
2. **输出层**：每条回复经 `parser.parse_llm_output` + `prs.estimate_style_from_reply` 得到四维风格观测值（复用生产同款观测函数，口径一致）。
3. **统计**：对跨显示阈值的维度，比较组 A 与组 B 的风格得分分布（Mann-Whitney U + Cohen's d 效应量）。
4. **同向性**：组 B 相对组 A 的均值偏移方向是否与向量漂移方向一致（漂移 +0.1 的维度，输出风格也应升高）。

### 3.6 分层判定逻辑（决策树）

```
第一步：跑组 C（极值对照）
  ├─ C 无显著差异 → 结论：注入失效，模型忽略性格段。先修注入路径，实验终止。
  └─ C 显著差异   → 方法有效，继续第二步。

第二步：跑组 A vs 组 B（真实漂移）
  ├─ 无差异 + 显示层无变化 → 结论：当前演化幅度跨不过 .1f 显示阈值，
  │     漂移不影响输出。需提高 _ADJUST_MAX_STEP 或显示精度（.2f/.3f）。
  ├─ 无差异 + 显示层有变化 → 结论：模型看到了向量但行为不服从。
  │     注入存在但权重低，需要增强 prompt 约束或调整措辞。
  └─ 有差异且同向 → 结论：漂移真实影响输出，演化有行为意义。E1-E8 的
        中心收敛从"内部状态变化"升级为"可观测行为变化"。
```

## 四、脚本结构（可复用现有代码）

建议新文件：`tests/personality_output_probe.py`（与 `cognitive_evolution_test.py` 同目录、同风格）

```python
# -*- coding: utf-8 -*-
"""实验 B：人格漂移 → prompt → 输出 因果验证（方案见 docs 目录）"""
import os, sys, json
sys.path.insert(0, r"E:\杂项\BNOS_AI_project\tests")
import self_evolution_test as evo          # llm_infer / MODEL / TEMPERATURE
sys.path.insert(0, r"E:\杂项\BNOS_AI_project\nodes\node_python_aaa_cognition")
import personality as prs
import prompt as pmt
import parser as psr
from cognitive_evolution_test import POOL_NEUTRAL, SEEDS  # 输入集与种子

INPUTS = POOL_NEUTRAL[:20]
REPEATS = 5

def build_ctx(vector, style_description=""):
    """构造固定上下文，唯一差异是 personality 段"""
    return {
        "identity_key": "probe",
        "fixed_cognition": "", "self_cognition": "", "other_cognition": "",
        "recent_feelings": "", "user_text": "", "current_date": "2026-08-08",
        "current_time": "12:00:00", "history_summary": "", "user_info": "",
        "self_info": "", "mood_trend": "", "attachment_context": "",
        "reflection_prompt": "", "perception": "", "db_path": "",
        "user_id": "probe",
        "personality": prs.build_personality_section(vector, style_description),
        "mood": prs.build_mood_section(0.0),   # 情绪固定为 0.0，排除第二变量
        "pool_batch_section": "",
    }

def run_group(vector, style_description=""):
    """对每条输入采样 REPEATS 次，返回风格观测序列"""
    samples = []
    for text in INPUTS:
        ctx = build_ctx(vector, style_description)
        ctx["user_text"] = text
        prompt = pmt.build_direct(ctx)
        for _ in range(REPEATS):
            raw = evo.llm_infer(prompt)
            parsed = psr.parse_llm_output(raw)
            samples.append({"input": text, "raw": raw,
                            "style": prs.estimate_style_from_reply(parsed)})
    return samples

def main():
    # 阶段一：快照提取（读 E1-E8 结果 json 或人工构造）
    # 阶段二：组 A / 组 B / 组 C 运行 + 落盘
    # 阶段四：显示层 diff + 输出层统计 + 同向性判定
    pass

if __name__ == "__main__":
    main()
```

留档目录沿用现有惯例：`docs/experiments/cognitive_evolution_test/runs/YYYYMMDD_HHMMSS_expB/`，输出 `probe_results.json` + `probe_report.md`。

## 五、验收标准

| 结果 | 判定 |
|---|---|
| 组 C（极值对照）Cohen's d ≥ 0.5 或 p < 0.05 | 方法有效，实验可信 |
| 组 A vs B 有显著差异且同向 | 漂移真实影响输出（命题成立） |
| 组 A vs B 无差异 + 显示层无变化 | 漂移幅度不足，需调步长/精度（命题待定） |
| 组 A vs B 无差异 + 显示层有变化 + C 有效 | 注入失效或权重过低（需修注入） |

## 六、成本与风险

- 成本：20 输入 × 3 组 × 5 采样 = 300 次 LLM 调用，单次约 1500 tokens，总量约 45 万 tokens，deepseek-v4-flash 量级可忽略。
- 风险 1：E1-E8 历史快照漂移过小导致显示层无变化——已有补充方案（B' 人工漂移向量），且"无变化"本身是有效结论。
- 风险 2：temperature=0.7 方差大——已用重复采样取分布。
- 风险 3：API 中断——沿用现有错误记录与续跑惯例，断点续跑按输入索引。

## 七、与后续实验的关系

- 若命题成立（漂移影响输出）：拉长轮数与降阈值（v6.6 已做）才有意义，认知演化进入"可观测行为演化"阶段，消息池实验的 8 组双向认知将具备行为学解释。
- 若命题不成立：优先修两条路之一——提高向量显示精度（.1f → .2f），或增大演化步长（0.02 → 0.05）。两者都是低成本改动，改完重跑本实验即可闭环。
