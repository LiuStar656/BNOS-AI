# 实验 B 报告：人格漂移 → prompt → 输出 因果验证

- run_dir：`E:\杂项\BNOS_AI_project\docs\experiments\cognitive_evolution_test\runs\20260809_011130_expB`
- 模型：deepseek-v4-flash  temperature=0.7
- 输入：20 条（POOL_NEUTRAL） × 5 采样 × 8 组

## 一、组设计

| 组 | 含义 | 向量 |
|---|---|---|
| A_seed | 基线 | {"warmth": 0.41, "playfulness": 0.52, "directness": 0.14, "curiosity": 0.1} |
| B_drift | 真实漂移 | {"warmth": 0.4339, "playfulness": 0.5225, "directness": 0.2342, "curiosity": 0.2} |
| C_low / C_high | 极值对照 | warmth 0.1 vs 0.9 |
| D_low / D_high | 极值对照 | directness 0.1 vs 0.9 |
| E_low / E_high | 极值对照 | curiosity 0.1 vs 0.9 |

## 二、显示层（.1f 精度）

A: `### 你的性格（会随使用自然演化，不需主动提及） | 各维度均为 0-1 范围，当前值如下（0=完全不是，1=极致，0.5=中等）： | 温暖度: 0.4 | 活泼度: 0.5 | 直接度: 0.1 | 好奇心: 0.1`
B: `### 你的性格（会随使用自然演化，不需主动提及） | 各维度均为 0-1 范围，当前值如下（0=完全不是，1=极致，0.5=中等）： | 温暖度: 0.4 | 活泼度: 0.5 | 直接度: 0.2 | 好奇心: 0.2`

跨显示阈值维度：directness: 0.140→0.234（显示 0.1→0.2）, curiosity: 0.100→0.200（显示 0.1→0.2）

## 三、输出层（estimate_style_from_reply 关键词观测）

### A vs B（真实漂移）

| 维度 | A均值 | B均值 | Δ | Cohen's d | p |
|---|---|---|---|---|---|
| warmth | 0.533 | 0.538 | +0.005 | +0.047 | 0.9481 |
| playfulness | 0.5055 | 0.518 | +0.013 | +0.164 | 0.4562 |
| directness | 0.472 | 0.507 | +0.035 | +0.386 | 0.1238 |
| curiosity | 0.542 | 0.5735 | +0.032 | +0.243 | 0.1909 |

### 维度敏感性（极值对照 0.1 vs 0.9）

| 对照维度 | 输出维度 | low均值 | high均值 | Δ | Cohen's d | p |
|---|---|---|---|---|---|---|---|
| warmth | warmth | 0.5485 | 0.627 | +0.079 | +0.539 | 0.0026 |
| warmth | playfulness | 0.5215 | 0.541 | +0.019 | +0.177 | 0.3219 |
| warmth | directness | 0.5315 | 0.5 | -0.032 | -0.443 | 0.1433 |
| warmth | curiosity | 0.577 | 0.5875 | +0.011 | +0.070 | 0.6761 |
| directness | warmth | 0.5415 | 0.5048 | -0.037 | -0.364 | 0.1807 |
| directness | playfulness | 0.518 | 0.5115 | -0.006 | -0.077 | 0.5613 |
| directness | directness | 0.465 | 0.4825 | +0.018 | +0.158 | 0.4733 |
| directness | curiosity | 0.598 | 0.57 | -0.028 | -0.182 | 0.2995 |
| curiosity | warmth | 0.5265 | 0.53 | +0.004 | +0.031 | 0.9212 |
| curiosity | playfulness | 0.5155 | 0.5295 | +0.014 | +0.154 | 0.544 |
| curiosity | directness | 0.5035 | 0.5 | -0.004 | -0.081 | 0.8657 |
| curiosity | curiosity | 0.605 | 0.815 | +0.210 | +1.541 | 0.0 |

## 四、同向性

| 维度 | 向量Δ | 输出Δ | 同向 |
|---|---|---|---|
| warmth | +0.024 | +0.005 | True |
| playfulness | +0.003 | +0.013 | True |
| directness | +0.094 | +0.035 | True |
| curiosity | +0.100 | +0.032 | True |

## 五、判定

显示层有变化但输出层无显著差异：注入存在但权重低 → 需增强 prompt 约束或调整措辞。维度敏感性：极值对照显著维度 = ['warmth', 'curiosity']（未显著维度需修 prompt 措辞或观测）