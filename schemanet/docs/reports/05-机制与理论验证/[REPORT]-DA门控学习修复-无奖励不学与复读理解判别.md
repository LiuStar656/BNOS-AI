# [REPORT] DA 门控学习修复——无奖励不学（Δw = STDP × DA）与复读-理解判别

> 日期：2026-08-11 ｜ 状态：[OK] 已实证、已修复、已验证 ｜ 定位：机制与理论验证
> 关联：[REPORT]-底噪过度设计诊断（学习门控）｜[REPORT]-定式网络睡眠机制全景（组块化/奖励）｜[REPORT]-定式网络注意力机制 v2.0

---

## 一、发现经过（复读期污染预警）

教学「拿 苹果」后出现异常联想：输入「拿」→ 输出「拿 苹果」。

**判别实验（复读 vs 理解）**：

| 输入 | 输出 | 判读 |
|---|---|---|
| 完整「拿 苹果」 | 拿 / 苹果 | 复读表象（输入词全被唤起） |
| 部分线索「拿」 | 拿 / **苹果** | 表面像"理解"——**实为共现联想** |
| 新组合「拿 水」 | 拿 / 水 / **苹果** | **✗ 过度泛化——污染铁证** |

**用户判定（2026-08-11）**："输出拿应该出来拿——出苹果就是污染的开始"。

**定位**：这不是"指令理解"，是**无奖励共现联想**——复读期（v51 白纸）不应有联想；联想应由"教学 + 奖励"显式建立，不是"老师说话"自动建立。

## 二、根因：学习无 DA 门控（违背三因子原式）

### 2.1 引擎原实现（sparse_net.py）

```python
mod = 1.0 + self.da_gain * (self.da - self.da_expected)
```

**问题**：da=0（无奖励）时 mod = 1.0 —— **照样学**。老师只要说话（注入词序列）→ STDP 无条件建边 → 共现统计污染。

实测：无零食教学「拿 苹果」5 次 → 拿→苹果 边 **46.8**（污染）。

### 2.2 文献对照：三因子规则的原式是乘法门

Izhikevich (2007) 三因子规则（奖励调制 STDP / R-STDP 原始论文）：

> **Izhikevich, E. M. (2007). Solving the Distal Reward Problem through Linkage of STDP and Dopamine Signaling. *Cerebral Cortex*, 17(10), 2443–2452. doi:10.1093/cercor/bhl152**

标准数学形式（sc-neurocore DopamineStdpSynapse 实现）：

```
Δw = lr · DA(t) · e(t)
      ↑     ↑     ↑
   学习率 多巴胺  资格迹
```

**关键事实：DA 是乘法因子，DA=0 → Δw=0 → 不学。**

- 无 "1+" 加成项——多巴胺是**门**（gate），不是调制器（modulator）
- 资格迹 e(t)（τ_e≈1s）：STDP 先打标，延迟奖励到达时凭标记兑现（解决 distal reward problem——奖励延迟几秒也能归因）
- 相关文献：Florian (2007) 独立推导同式；Pfister & Gerstner (2006) triplet STDP 提供基础

## 三、修复：DA 门控学习（Δw = STDP × DA）

### 3.1 引擎修改（sparse_net.py）

```python
rpe = self.da - self.da_expected
mod = self.da_gain * rpe
if mod < 0.0:
    mod = 0.0        # 负 RPE（落空/惩罚）也不建边
```

- **da=0（无零食）→ mod=0 → 学习块零增量 → 不建边**
- da>0（零食）→ mod>0 → 正常学习（RPE 内化保留：稳定奖励 RPE→0 不强化、意外奖励正强化）
- 负 RPE（惩罚/落空）→ 归零（不因失望反向建边——保守）

### 3.2 修复后判别验证（实测）

| 场景 | 教学方式 | 拿→苹果 边 | 输入「拿」输出 |
|---|---|---|---|
| 无零食教学 5 次 | 只说「拿 苹果」（da=0） | **0.0**（不学）| **拿**（纯复读——零联想 ✓）|
| 有零食教学 5 次 | 每次 release_da(+2) | **40.6**（学到）| 苹果/拿（指令唤起 ✓）|

**训狗语义精确落地**：零食（release_da）是学习的**开关**——无奖励纯复读（零改动），教学伴随奖励才建边。复读期不会因"老师说话"产生任何污染联想。

## 四、意义：复读期 → 指令期 的分界清晰化

```
复读期（v51 白纸）:
  老师说话（无零食）→ 网络纯复读——零改动、零联想
  "猫是动物"听一万遍 → 边 0——不污染

指令期（教学开启）:
  老师说「拿苹果」+ 零食 → 拿→苹果 边建立——指令理解
  正确行为 → 继续零食（强化）→ RPE 内化
```

**污染防线完整了**（三层）：
1. **底噪门控**（2026-08-11 上午）：无信号来源的发放不学——堵噪声
2. **DA 门控**（本次）：无奖励的教学不学——堵共现
3. **sleep 组块化**（2026-08-11 下午）：高频主干固化 + 低频遗忘——用进废退

## 五、遗留差距：资格迹（elig）未兑现

Izhikevich (2007) 的核心贡献是**延迟奖励归因**（distal reward problem）：资格迹 e(t) 在 STDP 事件时打标（τ_e≈1s），奖励延迟数秒到达后凭标记兑现 Δw = DA × e。

引擎现状：
- `elig[top] = 1.0` 置位 ✓
- `elig *= elig_decay`（0.9/拍）衰减 ✓
- **无读取点——资格迹从未兑现** ✗（底噪报告中已记录）

**当前同步教学（说话+零食同拍）不受影响**；但"先听指令→行为→后给零食"的**延迟奖励**场景需要资格迹兑现（Δw = DA × elig——奖励到达时对"刚才活动过"的突触兑现）。**待办**：完成资格迹兑现，补全三因子。

## 六、结论

| 项 | 内容 |
|---|---|
| 现象 | 教学后输入「拿」带出「苹果」（共现联想——污染预警） |
| 根因 | mod = 1+da_gain×RPE 在 da=0 时照样学——违背三因子原式 Δw = STDP×DA |
| 文献 | Izhikevich 2007（Cerebral Cortex）——DA 是乘法门，DA=0 不学 |
| 修复 | mod = da_gain×RPE（da=0 → 0 不建边；负 RPE 归零） |
| 验证 | 无零食 → 边 0.0、输入拿→只出拿 ✓；有零食 → 边 40.6、指令唤起 ✓ |
| 意义 | 复读期零污染——"老师说话"不再自动建边；训狗语义（零食=学习开关）落地 |
| 待办 | 资格迹兑现（Δw = DA×elig——延迟奖励归因） |

---

## 参考文献

1. Izhikevich, E. M. (2007). Solving the Distal Reward Problem through Linkage of STDP and Dopamine Signaling. *Cerebral Cortex*, 17(10), 2443–2452. doi:10.1093/cercor/bhl152
2. Florian, R. V. (2007). Reinforcement learning through modulation of spike-timing-dependent synaptic plasticity. *Neural Computation*, 19(6), 1468–1502.
3. Pfister, J.-P., & Gerstner, W. (2006). Triplets of spikes: a proposal for spike-timing-dependent plasticity with ternary synaptic efficacy. *Journal of Neuroscience*, 26(38), 9673–9682.
4. Yusoffa, N., & Grüning, A. (2012). A study of STDP-based reward-modulated synaptic plasticity. *(R-STDP 形式——Yusoffa & Grüning 2012)*
