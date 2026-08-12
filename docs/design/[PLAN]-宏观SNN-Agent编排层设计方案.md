# [PLAN] 宏观 SNN Agent 编排层设计方案

> 日期：2026-08-12 | 版本：v1.1 | 状态：[PLAN]
> 归属：BNOS-AI 项目（文档位置：docs/design/）

## 目录

- [一、背景与现状评估](#一背景与现状评估)
- [二、目标](#二目标)
- [三、理论来源](#三理论来源)
- [四、方案设计](#四方案设计)
- [五、实现层次（bnos_runtime 落地）](#五实现层次bnos_runtime-落地)
- [六、分阶段实施计划](#六分阶段实施计划)
- [七、风险评估](#七风险评估)
- [八、测试计划](#八测试计划)
- [九、影响范围](#九影响范围)

---

## 一、背景与现状评估

### 1.1 问题：微观涌现路径已被实验证伪

schemanet 在实验中的结论（已写入综合技术报告）：

- **机制层可行**：Hebbian / STDP / R-STDP（奖惩门控）/ 睡眠巩固（用进废退）全部实现了"定式沉淀"——权重从交互中产生；
- **语言层未涌现**：在三机制全部激活下，语言效果（top-1、PPL）仍显著低于最朴素的统计基线（bigram / KN / LSTM）；
- **能力外置**：预测能力来自代码层读出（S 矩阵直读 / 梯度读出层），不来自动力学本身；
- **混沌路径不可行**：随机初始 + 噪声探索 + 让网络自组织涌现规律的路径，在无生物物理结构支撑时只会退化为混沌（超临界放电、自振、无静息态），不产生可用的结构。

**结论**：不再追求"微观结构自主涌现功能"。

### 1.2 转向：SNN 作为 agent 工作流的架构范式

SNN 的已知优势恰好是 agent 编排所需，已知劣势恰好由 LLM 组件补上：

| SNN 特性 | agent 工作流需求 |
|---|---|
| 事件驱动、按需发放 | 组件按需唤醒，不空转 |
| 动态路由（WTA 竞争） | 工具/组件选择自适应，不写死 |
| 连接强度可学习 | 组件协作关系可演化 |
| 发放轨迹可回放 | 一次任务 = 一条脉冲路径 = 完全可审计 |
| 稀疏激活、低功耗 | 只激活必要组件，省算力 |

SNN 不学语言（交给 LLM 组件），只负责**编排**——动态路由、自组织连接、奖惩调节、可解释路径。

### 1.3 BNOS 已提供的基础设施

进程隔离（细胞膜）、文件协议（突触接口）、多端口+类型过滤（受体特异性）、生命周期/兴奋-休眠（代谢）、状态机（状态合法性）。

**缺口**：可学习连接强度 + 奖惩调制 + 用进废退衰减。本方案补这一层。

---

## 二、目标

1. 用 SNN 架构重构 agent 工作流：任务不再由硬编码 DAG / if-else 路由，而是由**脉冲网络动力学**编排；
2. 组件间的协作关系可学习：成功路径强化、失败路径压制、长期不用衰减；
3. 工作流完全可观测、可回放、可人工干预（脉冲轨迹即工作流）；
4. 不依赖混沌涌现：初始拓扑由人设计（骨架 DAG），学习只调制连接强度。

---

## 三、理论来源

本方案的每个机制都有明确的神经科学/计算神经科学理论依据。机制与文献的对应如下。

### 3.1 学习机制的神经科学基础

| 本方案机制 | 理论来源 | 依据要点 |
|---|---|---|
| 连接强度可学习（Hebbian 强化） | **Hebb (1949)**《The Organization of Behavior》 | "同时激活的神经元连接增强"（fire together, wire together）——组件协作成功多次 → 连接增强的生物学原型 |
| 用进废退 / 低频衰减 | **Kandel 系列实验（海兔 Aplysia）**；**Tononi & Cirelli (2014)** 突触稳态假说（SHY） | 反复经历形成记忆、不用的连接逐渐削弱；SHY：觉醒期突触净增强，睡眠期全局下调恢复稳态 |
| 睡眠巩固（低频槽衰减、强边豁免） | **de Vivo et al. (2017)**《Evidence for sleep-dependent synaptic down-selection in mice》 | 睡眠中大多数突触变小、最强的豁免（"spared the largest ones"）——与既有 sleep_consolidate 实现一致 |
| 活动依赖突触修剪 | **Hua & Smith (2004)**《Neural activity and the dynamics of central nervous system development》 | 不活跃的突触被修剪，活跃的连接保留——w≤eps 修剪的生物学原型 |
| 强化学习（R-STDP 三因子） | **Izhikevich (2007)**《Solving the distal reward problem through linkage of STDP and dopamine signaling》 | 多巴胺作为全局奖励信号门控 STDP，解决"远端奖励"的时间信用分配——资格迹的核心依据 |
| 三因子学习规则（neuromodulated learning） | **Gerstner, Lehmann, Vasilaki & Kiani (2018)**《Eligibility traces and plasticity on behavioral time scales: experimental support of neoHebbian three-factor learning》 | 突触 × 神经元 × 神经调节器三因子：`Δw = 资格迹 × 神经调节信号`——宏观 R-STDP 的规范数学形式 |
| 奖励预测误差 | **Schultz, Dayan & Montague (1997)**《A neural substrate of prediction and reward》 | 多巴胺编码预测误差；任务成败作为奖惩信号的神经编码依据 |

### 3.2 路由与表示的理论基础

| 本方案机制 | 理论来源 | 依据要点 |
|---|---|---|
| WTA 竞争路由 | **Rumelhart & Zipser (1985)**《Feature discovery by competitive learning》 | 竞争学习：多个候选竞争，胜者全取——组件选择自适应的原型 |
| 侧抑制 / 胜者全取稀疏发放 | **Grossberg (1987)**《Competitive learning: From interactive activation to adaptive resonance》 | 侧抑制实现稀疏激活与稳定编码（ART 框架） |
| 稀疏激活、低功耗 | **Olshausen & Field (1996)**《Emergence of simple-cell receptive field properties by learning a sparse code for natural images》 | 稀疏编码是自然神经系统的普遍策略——只激活必要组件 |

### 3.3 架构范式依据

| 本方案主张 | 理论来源 | 依据要点 |
|---|---|---|
| 事件驱动（异步、按需发放）而非全局时钟同步 | **Merolla et al. (2014)**（TrueNorth 百万神经元芯片）等神经形态计算工作 | 事件驱动（AER）是神经形态硬件的一致选择；BNOS 文件事件通信与其同构 |
| 用 SNN 做"编排"而非"内容生成" | 本项目 schemanet 实证结论 | 微观动力学在语言层无涌现、能力外置到代码层读出——架构层承载能力 |

### 3.4 文献清单

1. Hebb, D. O. (1949). *The Organization of Behavior*. New York: Wiley.
2. Rumelhart, D. E., & Zipser, D. (1985). Feature discovery by competitive learning. *Cognitive Science*, 9(1), 75–112.
3. Grossberg, S. (1987). Competitive learning: From interactive activation to adaptive resonance. *Cognitive Science*, 11(1), 23–63.
4. Olshausen, B. A., & Field, D. J. (1996). Emergence of simple-cell receptive field properties by learning a sparse code for natural images. *Nature*, 381(6583), 607–609.
5. Schultz, W., Dayan, P., & Montague, P. R. (1997). A neural substrate of prediction and reward. *Science*, 275(5306), 1593–1599.
6. Hua, J. Y., & Smith, S. J. (2004). Neural activity and the dynamics of central nervous system development. *Nature Neuroscience*, 7(4), 327–332.
7. Izhikevich, E. M. (2007). Solving the distal reward problem through linkage of STDP and dopamine signaling. *Cerebral Cortex*, 17(10), 2443–2452.
8. Tononi, G., & Cirelli, C. (2014). Sleep and the price of plasticity: from synaptic and cellular homeostasis to memory consolidation and integration. *Neuron*, 81(1), 12–34.
9. Merolla, P. A., et al. (2014). A million spiking-neuron integrated circuit with a scalable communication network and interface. *Science*, 345(6197), 668–673.
10. de Vivo, L., et al. (2017). Evidence for sleep-dependent synaptic down-selection in mice. *Science*, 355(6324), 507–510.
11. Gerstner, W., Lehmann, M., Vasilaki, V., & Kiani, R. (2018). Eligibility traces and plasticity on behavioral time scales: experimental support of neoHebbian three-factor learning. *Frontiers in Neural Circuits*, 12, 53.

---

## 四、方案设计

### 4.1 核心映射

| 微观定式网络 | 宏观 agent 工作流 |
|---|---|
| 神经元 | 工作单元：LLM 调用、工具、记忆读写、检索器、决策器 |
| 发放 | 该单元被激活、执行一次、产出结果 |
| 突触权重 W | 组件 A 输出 → 组件 B 的信任度/转移概率（可学习） |
| Hebbian 强化 | A、B 协作成功多次 → A→B 连接增强 |
| 用进废退 / sleep 巩固 | 长期未用的连接渐进衰减（可复活）；≤eps 修剪 |
| R-STDP 奖惩 | 任务成功/用户反馈 → 强化本次路径（资格迹）；失败 → 压制 |
| WTA | 多个候选组件竞争当前任务，最强（最匹配）的被选中 |
| 不应期 / 疲劳 | 组件处理中不重入；高频组件节流 |
| 学习门 | 运行态冻结连接（纯执行），学习态更新连接（训练） |
| 生命周期 / 兴奋-休眠 | 组件进程按需启动/休眠（BNOS 已有） |

### 4.2 节点突触协议（新增 BNOS 层）

在 BNOS 现有 `output.json` 文件协议之上，为每个节点新增**连接状态表**（由编排层维护）：

```jsonc
// node_state.json（每节点一份，与 output.json 同级）
{
  "node_id": "llm_infer",
  "synapses": [
    {
      "to": "tts",
      "w": 0.72,            // 连接强度（信任度/转移概率），[0,1]
      "last_used": 1786484808,   // 上次成功协作时间戳
      "uses": 412,               // 累计成功协作次数
      "fails": 13                // 累计失败次数
    }
  ],
  "refractory_left": 0,      // 不应期剩余（处理中不重入）
  "learn_gate": true         // 学习态/冻结态
}
```

读写走现有文件协议（不引入 SDK、不侵入节点逻辑）。**初始骨架**由 `pipeline.json`（人设计的 DAG）生成：有边 w=0.5（中性），无边 w=0。

### 4.3 学习信号（R-STDP 宏观化）

奖惩的来源（三选一可叠加，优先级递减）：

1. **任务成败**（硬信号）：LLM 调用报错、工具超时、结果校验失败 → 失败；流程完整走通 → 成功；
2. **用户反馈**（软信号）：用户点赞/采纳 → 成功；用户纠错/撤销 → 失败；
3. **LLM 自评**（弱信号）：结果被下游判定"相关/可用" → 成功。

奖惩沿**本次任务路径**回溯（资格迹，Gerstner 2018 三因子形式）：

```text
W[a→b] += da_gain * da * eligibility(a→b)
da = +1.0（成功） / -0.5（失败）
eligibility = trace_decay ^ (路径步差)
```

参数（初值）：`da_gain=0.05`、`trace_decay=0.8`、`w_max=1.0`、`w_min=0.05`（防死连接，可复活）。

### 4.4 用进废退（睡眠巩固宏观化）

低频连接渐进衰减、可复活；长期死连接修剪：

```text
每 N 次任务后（sleep）：
  所有 synapse: w *= (1 - decay) 若 last_used 距今 > T_idle
  w ≤ eps 的连接：从状态表删除（但保留在 pipeline.json 骨架里，可复活）
```

参数（初值）：`decay=0.1`、`T_idle=7 天`、`eps=0.02`。

### 4.5 WTA 路由

当节点产出多个候选后继（多端口 + 类型匹配均可用）时：

```text
对每个候选 b：score = w[a→b] * (1 - fat[b]) * recency_bonus
选 score 最高者；被选者不应期 refractory 步内不再被选中
```

- 多个候选 = 竞争；`score` 由连接强度主导 → 动态路由；
- 无候选（score 全 0）= 不发放 → 任务终止（可配置回退到 LLM 兜底）。

### 4.6 与 BNOS 现状的关系

| BNOS 现有 | 本方案新增 |
|---|---|
| `out_connections` 静态拓扑 | `node_state.json` 动态连接状态 |
| 多端口 + 类型过滤（确定性路由） | WTA 竞争路由（确定性 + 强度调制） |
| 生命周期（启动/监听/处理/休眠） | 不应期 / 疲劳 / 学习门 |
| 无奖惩通道 | R-STDP 宏观化（任务成败/用户反馈/LLM 自评） |
| 无衰减机制 | 用进废退（睡眠巩固宏观化） |

---

## 五、实现层次（bnos_runtime 落地）

### 5.1 为什么必须在 bnos_runtime 层（依据代码现状）

1. **连接是跨节点的全局状态**：拓扑由编排层持有（`pipeline_loader.py` 解析 `pipeline.json`）；节点 `node_config.json` 只存自身配置。连接强度表若放节点内部，两端副本必然不一致，违反"节点自治"边界 → 连接状态由编排层持有；
2. **用进废退是全局周期调度**：单节点看不到"别人的使用频率"。bnos_runtime 已有周期任务先例（`node_monitor.py` 的 `should_check()/mark_checked()`，每 5 秒一轮）→ sleep 调度器照此模式添加；
3. **WTA 路由是运行时决策**：现状路由是 GUI 写死的 `listen_upper_file / port_mappings`（`standalone_runner.py` 注释明示），节点是被动 listener，无法"选择把消息给谁" → 只有编排层读连接强度表才能做竞争路由；
4. **奖惩注入复用现有命令文件机制**：`engine.py` 已有 `bnos_cmd.json` → 重启节点的文件命令模式 → 奖惩做成同类文件协议（`bnos_reward.json`）零成本接入。

### 5.2 模块划分

```
bnos_runtime/
├── synapse_store.py      # 连接状态表（node_state.json）读写/演进   ← 新增
├── synapse_engine.py     # 动力学：Hebbian / R-STDP 资格迹 / sleep  ← 新增
├── wta_router.py         # WTA 竞争路由                            ← 新增
├── reward_inject.py      # 奖惩注入接口（文件协议）                  ← 新增
├── engine.py             # PipelineRunner 集成 sleep 周期任务       ← 修改
├── node_monitor.py       # 硬信号源：进程崩溃/退出码非0 → 惩罚        ← 复用
└── pipeline_loader.py    # 初始化：pipeline.json 骨架 → 连接表      ← 修改
```

### 5.3 待决策：任务路径追踪（影响 R-STDP 精度）

现引擎是**并行启动 + 文件通信**（`engine.py` 一次性启动全部节点），**没有"任务路径"概念**——而资格迹必须知道"本次任务经过哪些连接"：

- **方案 A（消息带 `task_id` + 上游标记）**：节点在 output.json 带 `task_id` 与上游节点 id。精确、可回放；代价是节点做最小协议扩展（改 packet 封装，不动业务逻辑）；
- **方案 B（编排层观察推断）**：runtime 监听文件消费关系推断路径。节点零改动；长链/并行分支下路径推断粗糙，资格迹可能错配奖惩。

> **当前倾向：方案 A**。理由：协议级最小改动、RL 质量高一个档次；且与"脉冲轨迹回放"（可观测性目标）共用同一数据。

---

## 六、分阶段实施计划

### Phase 0：协议与仿真骨架（纯离线，不接真实节点）

- 定义 `node_state.json` 协议 + 校验；
- 用 Python 仿真一个 8-12 节点的宏观 SNN（纯矩阵 W + 事件队列），在合成任务流上验证动力学收敛；
- 产出：协议文档 + `synapse_engine.py` 仿真库。

### Phase 1：学习信号接入

- 实现任务成败检测（结果校验）、用户反馈通道、LLM 自评钩子；
- 实现资格迹回溯奖惩；在仿真任务流上对比"有奖惩 vs 无奖惩"的路由命中率。

### Phase 2：真实节点接入 BNOS

- 决策任务路径方案（A/B，见 5.3）；
- 在 BNOS 现有节点（llm_infer、tts、asr_input、env_input、aaa_cognition 等）接入连接状态表；
- WTA 路由器替换现有确定性分发（保留回退开关）；
- 用 `pipeline.json` 骨架初始化连接。

### Phase 3：用进废退与观测面板

- 睡眠巩固调度器（按任务数/时间触发）；
- 观测面板：脉冲轨迹回放（本次任务经过哪些组件、哪些连接被强化/衰减）、连接强度热力图。

### Phase 4：长程验证

- 3 组任务流 × 多轮（如 200 轮）对比：固定 DAG vs 宏观 SNN；
- 指标：任务成功率、平均路径长度、连接演化熵、用户满意度。

---

## 七、风险评估

| 风险 | 等级 | 对策 |
|---|---|---|
| 学习信号不可靠（LLM 自评噪声大） | 高 | 以任务成败为硬信号，反馈/自评为辅助；信号冲突时硬信号优先 |
| 宏观层收敛慢/震荡（奖惩来回翻转） | 中 | 小 da_gain；连接初始中性（0.5）；引入动量/EMA |
| 动态路由引入不确定执行（任务路径漂移） | 中 | 保留"冻结态"回退：`learn_gate=false` 时退化为骨架 DAG 确定性执行 |
| 复用混沌涌现的错误直觉 | 高 | 明确铁律：**结构由人设计，学习只调强度**；不随机初始化拓扑 |
| 与现有 BNOS 节点不侵入原则冲突 | 中 | 连接状态表由编排层维护，节点零改动（或最小协议扩展，见 5.3） |

---

## 八、测试计划

1. **协议测试**：`node_state.json` 读写、越界（w>w_max、负 da）、缺字段容错；
2. **动力学仿真测试**：固定合成任务流，验证 WTA 命中率、奖惩收敛（成功路径 w↑、失败路径 w↓）、衰减复活；
3. **路由回退测试**：`learn_gate=false` 时执行轨迹与骨架 DAG 完全一致（对拍）；
4. **集成测试**：真实节点任务流 20 轮冒烟（含 llm 调用、tts、记忆读写）。

---

## 九、影响范围

- **新增文件**（bnos_runtime/）：`synapse_store.py`、`synapse_engine.py`、`wta_router.py`、`reward_inject.py`；
- **修改文件**：`pipeline.json` 初始化器（骨架 → 连接表）；`engine.py`（sleep 周期任务）；`node_monitor.py`（硬信号上报）；
- **不改动**：节点 main.py 业务逻辑、文件协议、进程隔离模型（BNOS 设计哲学全部保持）。

---

> 与 schemanet 的关系：本方案是**架构层**设计（BNOS 项目根），schemanet 提供**动力学语义与参数经验**（R-STDP、sleep、不应期等参数初值均来自微观实验）——两者是"语义复用"而非"代码复用"。
>
> 铁律：不依赖混沌涌现；结构人设计、强度 AI 学。
