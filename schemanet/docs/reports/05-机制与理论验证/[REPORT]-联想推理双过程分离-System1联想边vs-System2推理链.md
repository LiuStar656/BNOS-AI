# [REPORT] 联想-推理双过程分离——System 1 联想边 vs System 2 推理链（生成链与惩罚压制）

> 日期：2026-08-11 ｜ 状态：[OK] 架构确立 + 机制实现 + 文献对照 ｜ 定位：机制与理论验证
> 关联：[REPORT]-DA门控学习修复（无奖励不学）｜[REPORT]-底噪过度设计诊断（学习门控）｜[REPORT]-定式网络睡眠机制全景（组块化）

---

## 一、架构洞察（用户 2026-08-11）

用户提出定式网络的两条通路分离：

```
推理链（回答/表达）: 走主干——k-(k-1) 逐拍推进（槽位轨道）
  · 槽0→槽1→槽2 主干边（w=64 固定强度——结构）
  · 回答"叫爸爸" = 槽位推进 → 爸爸（结构化，不依赖统计）

联想链（思考/联想）: 走突触联想边
  · 词→词 共现边（权重 = 与这个词出现次数最多——统计）
  · 听到"猫"→ 联想到"鱼"（思考过程——不是回答！）
```

**核心命题（用户）**："就算突触权重有多高，推理链的时候不符合都不应该出现在 k 里"——推理时联想边被硬排除；"叫和爸爸可以连在一起，这样思考的时候看到叫就会出现爸爸"——联想边保留供思考。

## 二、文献对照（双过程理论——System 1 / System 2）

### 2.1 双过程理论（Dual Process Theory）

| 你的设计 | 文献对应 | 来源 |
|---|---|---|
| 联想边（思考用）| **System 1**：快速、自动、联想 | Kahneman（思考快与慢）；Evans 2003 |
| 推理链（回答）| **System 2**：慢速、序列、工作记忆受限 | Evans 2003 (TiCS) |
| 联想 = 共现频率 | 自由联想/共现强度（associative strength）| Nelson et al. 2005 |

- **Morewedge et al. (2010, TiCS)**：System 1 = 联想记忆的自动操作——"看到叫出现爸爸"正是联想记忆的自动激活。
- **Goel & Dolan fMRI**：逻辑（System 2）反应 = 右前额叶；信念/联想（System 1）= 腹内侧前额叶——两条通路有独立神经基础。
- **Nelson et al. (2005, PBR)**：自由联想概率与共现统计是联想强度的度量——联想边权重 = 共现强度有实证基础。

### 2.2 推理时联想被压制（前额叶抑制）

| 你的设计 | 文献对应 | 来源 |
|---|---|---|
| 推理链时联想不进 k（硬过滤）| **左外侧 PFC 抑制预势联想**（proactive inhibition）| Marko & Riecansky 2021 (Cortex) |
| 被剔联想 + 惩罚压边 | **检索抑制 / 抑制诱发遗忘 SIF** | Anderson & Floresco 2022 (Neuropsychopharmacology) |
| 思考时联想自由 | 小脑自动自由联想；PFC 控制侵入 | Kubinec et al. (Neurobiology of Language) |

- **Marko & Riecansky (2021)**：左外侧前额叶在语义检索中主动抑制预势联想（prepotent associations）——推理时联想被排除有直接神经证据。
- **Anderson & Floresco (2022)**：右 DLPFC/VLPFC 抑制海马/皮层再激活——**抑制诱发遗忘（SIF）：被压的联想真的变弱**——用户的"惩罚压边"（LTD）正是 SIF 的模型实现。

### 2.3 互补学习系统（CLS）

McClelland, McNaughton & O'Reilly：海马（快速、情景、模式分离）vs 新皮层（慢速、分布式、泛化）——定式网络的**框架/主干（结构化推理）**与**联想边（统计联想）**的分工可类比 CLS 的双系统架构。

## 三、机制实现（引擎落地）

### 3.1 联想边保留（思考用）

教学「叫 爸爸」（奖励）→ 叫→爸爸 联想边建立（w=43.8，可到 999）——**保留**（思考时"看到叫出现爸爸"）。

### 3.2 推理链硬过滤（联想不进 k）

轨道上（senders 含定式词/槽位）→ k 只收：
```
① 槽位（主干推进——k-(k-1) 逐拍）
② 注入词（论元回声——X 来自输入）
③ 轨道绑定词（当前槽位读出）
联想边（词→词共现）权重再高也被硬剔（keep_track 排除）
```

### 3.3 惩罚压制联想（SIF 模型）

- **DA 门控**（无奖励不学）：da≈0 → mod=0 → 不建边
- **惩罚 LTD**（负 RPE 压边）：da<0 → mod<0 → 学习增量变负 → 边权重下降
- **压被剔候选**（`_punish_cands`）：推理时被硬过滤剔除的联想候选（爸爸）→ 惩罚到达时压其入边（叫→爸爸）

### 3.4 实测验证

| 测试 | 结果 |
|---|---|
| 教学后 叫→爸爸 联想边 | 43.8（保留——思考用）|
| 惩罚 5 次后 叫→爸爸 | **43.8 → 0.0**（LTD 压制——SIF）|
| 论元边 叫→爷爷 | 0.0（框架槽位——不走联想边，惩罚不伤）|

## 四、生成链问题（用户："带出绑定词很明显就是生成链出现问题"）

### 4.1 现象

开放槽框架（叫X 教爸爸/妈妈/爷爷）输入「叫 爷爷」→ 输出带出 妈妈/爸爸（历史绑定词）。

### 4.2 根因

```
槽1 多绑定（readout={爸爸,妈妈,爷爷}）→ 槽1 发放 → 槽1→各绑定词边（w=64）
全部驱动 → 妈妈/爸爸过阈成候选 → 硬过滤剔除（track_words∩ctx 只留爷爷）
→ 但被剔候选 v 残留 → 下一拍学习路径（全局 WTA 无轨道过滤）→ 泄漏放出
```

**生成链泄漏**：硬过滤剔除了联想词（keep 置 False）但**未清零膜电位**——词层消歧（keep2）剔时清了 v（`v[drop]=0`），硬过滤（keep）剔时没清。

### 4.3 修复方向

硬过滤剔除时同步清零膜电位（与 keep2 一致）——被剔联想不出现在生成链，也不残留到下一拍泄漏。

## 五、结论

| 项 | 内容 |
|---|---|
| 架构 | 联想链（System 1——思考）vs 推理链（System 2——回答）分离 |
| 联想边 | 保留（思考用），权重 = 共现频率（associative strength）|
| 推理链 | 主干（槽位轨道 k-(k-1)），联想硬过滤不进 k |
| 惩罚 | LTD 压边（负 RPE）——SIF 模型——被压联想真的变弱 |
| 文献 | 双过程理论（Kahneman/Evans）、前额叶抑制（Marko 2021）、检索抑制 SIF（Anderson 2022）、CLS（McClelland）|
| 待修 | 生成链泄漏（硬过滤剔 v 残留 → 下一拍放出）|

---

## 参考文献

1. Evans, J. St. B. T. (2003). In Two Minds: Dual-Process Accounts of Reasoning. *Trends in Cognitive Sciences*, 7(10).
2. Morewedge, C. K., & Kahneman, D. (2010). Associative Processes in Intuitive Judgment. *Trends in Cognitive Sciences*, 14(10).
3. Nelson, D. L., et al. (2005). What is preexisting strength? Predicting free association probabilities... *Psychonomic Bulletin & Review*, 12(6).
4. Marko, M., & Riecansky, I. (2021). The left prefrontal cortex supports inhibitory processing during semantic memory retrieval. *Cortex*.
5. Anderson, M. C., & Floresco, S. B. (2022). Retrieval stopping and its neural mechanisms. *Neuropsychopharmacology*.
6. Kubinec, K., et al. Prefrontal and Cerebellar Contributions to Semantic Memory Retrieval. *Neurobiology of Language*.
7. McClelland, J. L., McNaughton, B. L., & O'Reilly, R. C. Why there are complementary learning systems in the hippocampus and neocortex. *Psychological Review*.
