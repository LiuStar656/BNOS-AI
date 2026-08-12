# 混沌脉冲网络中奖惩学习的动力学现象与归因判别

## 作者信息（提交前填写）

- 作者：____________（第一作者）
- 单位：____________（如：××职业技术学院 / 独立研究者）
- 通信邮箱：____________
- 基金项目：____________（无则写"无"）

---

## 摘要

针对无梯度脉冲神经网络（SNN）奖惩学习缺乏系统实证的问题，本文在间歇混沌背景下开展受控实验，检验奖惩能否经 R-STDP 三因子规则定向调节行为频率，并对其效应进行归因判别。方法上采用奖励/惩罚/中性三组对照（5 个随机种子，另补充 16 倍规模不变性扫描与 50 种子坍缩发生率统计），以资格迹兑现（Δw=DA×e）为干预接口并保持学习门关闭，以隔离 Hebbian 使用增强；随后设计随机奖励（D1）、错误边（D2）、阈值扫描（D3）、自发率（D4）四组判别实验。结果显示：奖励组测试期行为频率升至 100.0%（中性 28.0%），惩罚组压至 0.0%，效应量 Cohen's d=+6.68/−2.60，该调节跨 16 倍规模（n=1024–16384）稳定；权重复核证实调节的物质载体为突触权重；D2–D4 排除全局注入、机械阈值与兴奋性抬升等代码诱导出口，D1 则将机制诚实降级为"奖赏驱动的权重增强"而非操作性条件反射。此外，调试中意外发现"马太坍缩"失效模式：奖励兑现与 Hebbian 使用增强叠加形成双重自增强正反馈，少数神经元垄断权重，行为组发放维度跌破检测阈值并永久死锁——50 个随机种子中发生率 34.0%、权重垄断率 100.0%，学习门消融证明该自增强回路仅在奖励方向致病，与深度学习的 neural collapse 形成无梯度对照。结论：混沌背景下奖惩可定向调节突触权重并随之调节行为唤起频率；能力归因判别是自研系统结论可信度的必要步骤。

**关键词**：脉冲神经网络；奖励学习；R-STDP；混沌动力学；神经坍缩；能力归因；胜者全取

**中图分类号**：TP183  **文献标识码**：A

**Title**: Dynamical Phenomena and Attribution in Reward-Punishment Learning of Chaotic Spiking Neural Networks

**Abstract (EN)**: 见文末英文摘要。

---

## 0 引言

脉冲神经网络（SNN）的学习信号（Hebbian、STDP）是局部的、无反向传播的，与生物突触可塑性同构[1-2]。但在下游任务性能上，SNN 与 Transformer 存在数量级差距，这一差距使 SNN 研究长期聚焦"追赶性能"或"神经形态硬件适配"。

本工作不追求性能追赶，而是将 SNN 定位为可学习 Agent 系统的微观动力学层：在宏观编排层（连接拓扑、奖惩注入、用进废退调度）与微观突触动力学层之间建立实证桥梁。在此定位下，一个基础问题浮现：**奖惩信号能否在混沌背景下对局部突触权重实施定向调节，并因此改变宏观行为频率？**

本文以受控实验回答三个问题：

- **Q1（定向调节）**：混沌背景下，奖惩能否经 R-STDP 资格迹定向改写被标记突触的权重，并使行为频率同向变化？
- **Q2（归因判别）**：观测到的调节效应，是网络动力学的真实涌现，还是探针/脚本代码诱导的假象？
- **Q3（意外发现）**：实验过程中是否撞出设计预期之外、且具有科学价值的动力学现象？

## 1 相关工作

**1.1 R-STDP 三因子规则。** Izhikevich[5] 提出多巴胺门控的 STDP 三因子规则 Δw = DA × e：突触可塑性由局部 STDP 资格迹 e 与全局奖赏信号 DA 的乘积决定，实现延迟归因。其神经科学对应为奖赏预测误差[4]与操作性条件反射。近年来神经调质 STDP 的学习理论得到系统整理[7]，代理梯度法[8]则为 SNN 提供梯度近似路线，但本文关注规则层（无梯度）奖惩学习。

**1.2 Neural collapse。** Papyan 等[11] 发现深度分类网络在训练终期出现四重几何收敛：类内表示坍缩至类均值、类均值收敛至 simplex 等角紧框架、分类器与类均值对齐、分类退化为最近类中心规则。NC 被视为梯度下降的隐式偏置，通常表现为"健康的"结构化收敛。本文发现的"马太坍缩"与其形成无梯度对照（见 4 节）。

**1.3 能力归因方法族。** LLM/Agent 域近年建立了一套能力归因方法：CapaBench[16] 用 Shapley 值对模型模块做组合归因；Harness-vs-Models[17] 分离评测脚手架与模型本体的能力；Backtrace 框架[18] 用 no-skill 反事实与六种干预对照判断技能是否真实被使用；Schaeffer 等[12] 证明"能力涌现"可能是度量假象。本文的 D1–D4 判别实验是该方法族向无梯度 SNN 机制域的迁移。

**1.4 混沌临界与 SNN 稳态。** Beggs 与 Plenz[9] 发现神经元雪崩呈幂律（临界分支参数 σ≈1）；Shew 等[10] 证明 E/I 平衡建立临界态并最大化动态范围。本文的混沌环境（σ 超临界、间歇混沌）以此为背景。突触稳态方面，de Vivo 等[15] 提供睡眠期突触缩放的超微结构证据，与本系统的频率门控慢衰减对应。

## 2 实验设置与方法

**2.1 网络与混沌环境。** 引擎为 SparseSchemaNet（n=1024，膜电位衰减 λ=0.9，发放阈值 θ=1.0，学习率 η=0.1，权重上限 w_max=16.0，WTA 全局竞争 K=8）。混沌参数构成间歇混沌（无静息态背景，自发发放率 chaos≈0.5–0.78，实测确认）。三组独立样本：rng = seed×100 + {reward:0, punish:1, neutral:2}，互不共享噪声序列。

**2.2 行为与三组对照。** 输入模式 X 与行为模式 B 各 16 神经元；预学习 X→B 单向边（w_pre≈66）。行为 = 注入 X 后响应窗口内 B 组 ≥8 个神经元同时发放。干预在 learn_gate=False 下进行（release_da 直接写边、无 Hebbian 使用增强混杂——该设计源自 4 节马太坍缩的教训）：

| 组 | Phase 2 干预 |
|---|---|
| 奖励 | 行为发生 → 标记活跃 X→B 资格迹 + release_da(+0.3) |
| 惩罚 | 行为发生 → 标记活跃 X→B 资格迹 + release_da(−0.3)（×3 系数） |
| 中性 | 行为发生 → 零改动 |

**2.3 流程。** Phase 1 基线（40 周期）→ Phase 2 干预（100 周期）→ Phase 3 测试（freeze，清残留 DA/资格迹，注入 X 及相似输入 X₁₂/X₈/X₄ 各 20 周期，记 f16/f12/f8/f4）。

**2.4 指标与统计。** 行为频率 = 行为事件/注入周期×100；干预效应 = f_inter − f_base；效应量 Cohen's d = (组 − 中性)/合并标准差。主结果 5 seeds × 3 组 → mean±std；规模不变性扫描 5 档 × 3 seeds（3.2 节）；马太坍缩发生率 50 seeds（4.3 节）；学习门消融 4 seeds × 3 组 × 2 门态（4.3 节）。

**2.5 判别实验（D1–D4）。** 分别攻击四个"代码诱导"出口：D1 随机奖励（奖励时点与行为解耦，50% 概率注入）检验行为-奖赏关联；D2 错误边（预学习 X→B 与 X→C 双路径、只奖励标记 X→C）检验全局 DA 泛滥；D3 阈值扫描（BM∈{5,8,10}）检验机械阈值切分；D4 空拍自发率（B 组无输入时自发率）检验全局兴奋性抬升。

## 3 结果：混沌中奖惩定向调节行为频率

**3.1 主结果（5 seeds：42–46）。**

| 组 | f_base | f_inter | f16 | f12 | f8 | f4 | Cohen's d (vs neutral f16) |
|---|---|---|---|---|---|---|---|
| 奖励 | 42.5±17.5 | 97.4±3.0 | **100.0±0.0** | 100.0 | 100.0 | 100.0 | **+6.68** |
| 中性 | 33.0±18.9 | 33.6±18.3 | **28.0±15.2** | 14.0 | 1.0 | 1.0 | — |
| 惩罚 | 47.0±18.1 | 2.0±0.0 | **0.0±0.0** | 0.0 | 0.0 | 0.0 | **−2.60** |

双向调节 5/5 seeds 全成立：奖励组测试期 f16 升至 100%（中性 28%），惩罚组压至 0%，效应量巨大。

**3.2 规模不变性。** 为回应"小规模仿真、说服力有限"的质疑，补充扫描 n ∈ {2048, 4096, 8192, 16384} × 3 seeds × 三组（其余参数与正式协议一致）：

| n | reward f16 | punish f16 | neutral f16 | d_reward | d_punish |
|---|---|---|---|---|---|
| 1024（正式，5 seeds）| 100.0±0.0 | 0.0±0.0 | 28.0±15.2 | +6.68 | −2.60 |
| 2048（3 seeds）| 100.0±0.0 | 1.7±2.9 | 26.7±16.1 | +6.45 | −2.17 |
| 4096（3 seeds）| 100.0±0.0 | 0.0±0.0 | 30.0±18.0 | +5.49 | −2.35 |
| 8192（3 seeds）| 100.0±0.0 | 0.0±0.0 | 30.0±18.0 | +5.49 | −2.35 |
| 16384（3 seeds）| 100.0±0.0 | 1.7±2.9 | 36.7±12.6 | +7.12 | −3.83 |

16 倍规模跨度下调节完全稳定（reward 饱和 100%、punish 压至 ~0–2%、neutral 26.7–36.7% 噪声内，效应量 d∈+5.5~+7.1/−2.2~−3.8 全为大效应）——调节机制与规模无关，是结构性效应而非小网络特例。

**3.3 权重复核。** 奖励组 w_pre 65.98 → w_post 1764–1916（5 seeds）；惩罚组 → 22.09（≈1/3，×3 惩罚系数叠加）；中性组 65.98（零改动）。奖惩确实定向改写了突触权重，行为频率与权重同向变化——调节的物质载体是突触本身。

**3.4 泛化梯度与混沌确认。** 中性组 f16→f4：28→14→1→1——相似输入按共享神经元数分级唤起（吸引域梯度），奖励组因饱和、惩罚组因压制而双向饱和。三组 chaos≈0.5–0.78，确认调节发生在间歇混沌背景下。

## 4 意外发现：马太坍缩

**4.1 现象。** 早期协议（干预期 learn_gate=True）下奖励组出现反直觉现象：X→B 权重和 w 66→1514（暴涨 23 倍），但测试期行为频率 f16 反而 0%（seed 43/44）——强化与行为表现呈反向关系。

**4.2 插桩证据链。** 逐周期插桩四指标（w_sum 权重和、marks 资格迹标记次数、fatB 疲劳均值、nb_si 行为组实际发放神经元数）显示三个阶段：（1）**强化集中**——WTA 竞争下同一批高膜电位赢家重复赢得竞争，资格迹每次标记同一批神经元；（2）**权重垄断与发放维度坍缩**——赢家权重冲向 w_max 饱和，learn_gate=True 使 Hebbian 使用增强叠加于资格迹兑现，构成双重自增强正反馈，B 组从 16 神经元协同发放坍缩为少数赢家垄断（每次仅 4–6 个）；（3）**阈值失配与永久死锁**——发放数恒低于行为阈值 8，行为永不达标，奖励停发，无恢复信号，永久死锁。

**4.3 发生率与消融。** ① 发生率定量（50 seeds，n=1024）：learn_gate=True + reward，seeds 1–50——完全坍缩（f16=0%）17/50 = 34.0%；权重垄断（w_post > 3×w_pre）100.0%（50/50）；reward f16 均值 38.3±39.2（vs 正式协议 100.0±0.0）。即开门奖励下必然发生权重垄断、34% 种子完全死锁、其余 66% 行为频率也严重受损。② 学习门消融矩阵（learn_gate ∈ {False, True} × 三组 × 4 seeds）：reward f16 由 100.0±0.0 降至 40.0±46.9（坍缩 2/4），punish 0.0±0.0 → 0.0±0.0（无影响），neutral 28.0±15.2 → 30.0±16.8（无影响，噪声内），reward w_post 1764–1916 → 528–2252（100% 暴涨）——学习门（无监督 Hebbian 使用增强通道）只在奖励方向致病，且权重暴涨并不带来行为增强。③ 反证：learn_gate=False（仅资格迹兑现）下 3 seeds 探针稳定、5 seeds 正式全过——坍缩不是奖励本身的必然结果，而是"使用增强 × 奖励兑现"叠加的产物。

**4.4 与 neural collapse 的对比。** 对照如表：

| 维度 | Neural Collapse[11] | 马太坍缩（本文） |
|---|---|---|
| 驱动信号 | 全局梯度下降 | **无梯度**：局部 Hebbian × 奖励资格迹 |
| 坍缩对象 | 类内表示方差 | 行为组发放维度（16→4–6） |
| 坍缩几何 | simplex ETF（保序分离） | 少数赢家垄断（聚集失序） |
| 后果 | 结构化、利于泛化 | 病态死锁、功能丧失 |
| 可分离性 | 训练过程难以关闭 | 可由 learn_gate 独立开关 |

对照要点：（1）**坍缩不是梯度方法的专利**——仅靠局部可塑性 + 奖励即可自发产生多样性坍缩；（2）**坍缩方向由驱动信号的信息结构决定**——梯度携带全局类别结构（→ETF 保序），局部奖励只携带"这行为好"（→垄断失序）；（3）**自增强回路可分离**——为 SNN 奖惩学习提供具体的防坍缩干预原则（奖励兑现与无监督可塑性解耦、行为阈值留安全边际、监控行为组发放维度作为多样性哨兵）。

## 5 归因判别实验：结果 vs 代码诱导

**5.1 D1 非操作性对照（随机奖励）。** 奖励时点与行为完全解耦（每周期独立 50% 概率注入 +0.3），行为检测不参与发放。结果：f16=100%（wB 66→771/768），与操作性奖励一致。判定：频率上升的主机制是权重增强（Δw=DA×e 资格迹兑现），而非"行为-奖赏"关联的时点选择性。**诚实披露**：本实验验证的是"奖赏→路径权重增强"的动力学，不足以支撑"操作性条件反射/行为选择学习"的强断言。

**5.2 D2 错误边对照。** 奖励只标记 X→C 时（seed42）：reward→B 时 f16=100%、wB 187→1658、wC 48.2→48.2（C 不受益）；reward→C 时 f16=0%、wB 187→187、wC 48.2→173（仅 C 受益）；seed43 同构。判定：强化严格作用于被标记的边——排除全局 DA 注入假象。

**5.3 D3 阈值扫描。** BM=5：reward 100% vs neutral 80–87%；BM=8：reward 100% vs neutral 20–45%；BM=10：两组均 0%。判定：reward 组跨阈值全饱和、neutral 组随阈值显著衰减——差异来自权重状态而非阈值设定（对照"度量假象"教训[12]）。

**5.4 D4 特异性。** reward 空拍自发率 50.6–54.7% vs neutral 52.2–61.9%（无显著差异）。判定：奖励未改变整体兴奋性，频率上升是 X→B 路径的特异性增强。

**5.5 判别结论。** 全局 DA 泛滥（D2）、机械阈值切分（D3）、全局兴奋性抬升（D4）均被排除；D1 表明机制为"奖赏驱动的权重增强"而非操作性条件反射涌现。论文口径：可支撑"混沌背景下奖惩定向调节突触权重并随之调节行为唤起频率"，不宣称实现行为-奖赏关联的涌现（后者需奖赏预测误差与行为选择逻辑，属后续工作）。

## 6 讨论

**6.1 三层发现的组合逻辑。** 正结果（3 节）给出效应，马太坍缩（4 节）给出意外机制，判别实验（5 节）给出归因边界。三者互相咬合：马太坍缩的定位过程直接决定了正式协议的 learn_gate=False 设计，而该设计又是判别实验中"排除 Hebbian 混杂"的前提。意外发现不是主结果的干扰，而是主结果可信度的一部分。

**6.2 归因方法族向 SNN 域的迁移。** 与 LLM/Agent 域方法[16-18]相比，D1–D4 的增量体现为：干预对照的**机制级**对象（突触权重、资格迹、WTA 发放维度）而非模块级；判别出口从"能力归属"扩展到"代码诱导 vs 动力学涌现"——对自研系统研究而言，"效果是否只是探针代码造成的"是比"能力归谁"更基础的质疑。

**6.3 对 Agent 编排层的意义。** ① 混沌背景下奖励/惩罚即可定向改写突触并调节行为频率——编排层无需稳定背景即可实施奖惩；② learn_gate 是编排层接口：自增强回路（Hebbian 使用增强）与定向奖励（资格迹兑现）的解耦是可操作的编排旋钮；③ 行为组发放维度/权重基尼系数可作为行为多样性监控的微观指标。

## 7 结论

本文以受控实验回答三个问题：混沌背景下奖惩定向调节行为频率成立（5/5 seeds，d=+6.68/−2.60，跨 16 倍规模稳定，物质载体为突触权重）；该效应经四组判别排除代码诱导、诚实地定位于"奖赏驱动的权重增强"；过程中撞出"马太坍缩"这一意外失效模式——50 seeds 定量发生率 34.0%、权重垄断率 100.0%，学习门消融证明双通道自增强仅在奖励方向致病，其与 neural collapse 的对照表明"多样性坍缩"是学习动力学的一般特征而方向由驱动信号决定。本文不宣称实现智能，而是提供一个证据链完整、归因诚实、意外发现可复现的现象学样本，为"无梯度 SNN 作为可学习 Agent 微观动力学层"提供机制级背书。

## 参考文献（GB/T 7714）

[1] BI G Q, POO M M. Synaptic modifications in cultured hippocampal neurons: dependence on spike timing, synaptic strength, and postsynaptic cell type[J]. Journal of Neuroscience, 1998, 18(24): 10464-10472.
[2] MARKRAM H, LÜBKE J, FROTSCHER M, et al. Regulation of synaptic efficacy by coincidence of postsynaptic APs and EPSPs[J]. Science, 1997, 275(5297): 213-215.
[3] IZHIKEVICH E M. Simple model of spiking neurons[J]. IEEE Transactions on Neural Networks, 2003, 14(6): 1569-1572.
[4] SCHULTZ W, DAYAN P, MONTAGUE P R. A neural substrate of prediction and reward[J]. Science, 1997, 275(5306): 1593-1599.
[5] IZHIKEVICH E M. Solving the distal reward problem through linkage of STDP and dopamine signaling[J]. Cerebral Cortex, 2007, 17(10): 2443-2452.
[6] PFISTER J P, GERSTNER W. Triplets of spikes: a proposal for spike-based plasticity[J]. Journal of Neuroscience, 2006, 26(38): 9673-9682.
[7] FRÉMAUX N, GERSTNER W. Neuromodulated learning, reinforcement learning, and neuro-inspired learning[J]. Current Opinion in Neurobiology, 2016, 35: 25-34.
[8] BELLEC G, SCHERBER T, SUBRAMONEY A, et al. A solution to the learning dilemma for recurrent networks of spiking neurons[J]. Nature Communications, 2020, 11: 3625.
[9] BEGGS J M, PLENZ D. Neuronal avalanches in neocortical circuits[J]. Journal of Neuroscience, 2003, 23(35): 11167-11177.
[10] SHEW W L, YANG H, PETERMAN T, et al. Neuronal avalanches imply maximum dynamic range in cortical networks at criticality[J]. Journal of Neuroscience, 2009, 29(49): 15595-15600.
[11] PAPYAN V, HAN X Y, DONOHO D L. Prevalence of neural collapse during the terminal phase of deep learning training[J]. Proceedings of the National Academy of Sciences, 2021, 117(40): 24652-24663.
[12] SCHAEFFER R, MIRANDA B, KOYEJO S. Are emergent abilities of large language models a mirage?[C]//Advances in Neural Information Processing Systems 36. 2023.
[13] KIRKPATRICK J, PASCANU R, RABINOWITZ N, et al. Overcoming catastrophic forgetting in neural networks[J]. Proceedings of the National Academy of Sciences, 2017, 114(13): 3521-3526.
[14] McCLELLAND J L, McNAUGHTON B L, O'REILLY R C. Why there are complementary learning systems in the hippocampus and neocortex[J]. Psychological Review, 1995, 102(3): 419-457.
[15] DE VIVO L, BELLESI M, MARSHALL W, et al. Ultrastructural evidence for synaptic scaling across the wake/sleep cycle[J]. Science, 2017, 355(6324): 507-510.
[16] CapaBench: A benchmark for modular capability attribution[EB/OL]. arXiv:2502.00510, 2025.
[17] Harness vs Models: separating scaffolding and model capabilities[EB/OL]. 2026.
[18] Skill Use or Skill Theater? Backtrace framework[EB/OL]. arXiv:2607.27484, 2026.
[19] 中文相关文献（脉冲神经网络/类脑计算综述）：提交前请按目标期刊要求补充 1–3 篇国内期刊近 5 年论文。

---

## 附：英文摘要（Abstract）

**Dynamical Phenomena and Attribution in Reward-Punishment Learning of Chaotic Spiking Neural Networks**

We conduct a controlled study of reward-punishment learning in a gradient-free spiking neural network (SNN) under intermittent chaos, addressing three questions: (1) Can reward/punishment directionally modulate behavioral frequency via the R-STDP three-factor rule (Δw = DA × e)? (2) Is the observed effect genuine network dynamics or code-induced artifact? (3) Does the process reveal unexpected dynamical phenomena? Using reward/punishment/neutral contrasts across 5 random seeds, reward raised test-phase behavioral frequency to 100.0% (neutral: 28.0%) and punishment suppressed it to 0.0% (Cohen's d = +6.68/−2.60), a modulation that remained stable across a 16× scale sweep (n = 1024–16384); weight auditing confirmed synaptic weights as the substrate. Four attribution experiments (random-reward D1, wrong-edge D2, threshold-scan D3, spontaneous-rate D4) ruled out global dopamine flooding, mechanical threshold effects, and excitability elevation, while honestly downgrading the mechanism to "reward-driven weight enhancement" rather than operant conditioning. During debugging we discovered an unexpected failure mode, "Matthew Collapse": reward delivery combined with Hebbian use-dependent potentiation forms a dual self-reinforcing loop, collapsing behavioral diversity into a winner-monopoly deadlock — quantified across 50 seeds (collapse rate 34.0%, weight monopolization 100.0%), with an ablation showing the self-reinforcing loop only damages the reward direction; this is a gradient-free counterpart to neural collapse (Papyan et al., 2021). We conclude that reward/punishment can directionally modify synaptic weights and thereby behavior frequency under chaos, and that capability attribution is a necessary step for trustworthy conclusions in self-built systems.

**Keywords**: spiking neural network; reward learning; R-STDP; chaotic dynamics; neural collapse; capability attribution; winner-take-all
