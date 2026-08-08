# 实验 B 报告：人格漂移 → prompt → 输出 因果验证

- run_dir：`E:\杂项\BNOS_AI_project\docs\experiments\cognitive_evolution_test\runs\20260809_011232_expB`
- 模型：deepseek-v4-flash  temperature=0.7
- 输入：20 条（POOL_NEUTRAL） × 5 采样 × 6 组

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

### 维度敏感性（极值对照 0.1 vs 0.9）

| 对照维度 | 输出维度 | low均值 | high均值 | Δ | Cohen's d | p |
|---|---|---|---|---|---|---|---|
| warmth | warmth | 0.5185 | 0.5955 | +0.077 | +0.499 | 0.0033 |
| warmth | playfulness | 0.52 | 0.527 | +0.007 | +0.077 | 0.7569 |
| warmth | directness | 0.5245 | 0.5 | -0.025 | -0.304 | 0.2607 |
| warmth | curiosity | 0.5595 | 0.5817 | +0.022 | +0.141 | 0.4184 |
| directness | warmth | 0.5335 | 0.5185 | -0.015 | -0.131 | 0.4655 |
| directness | playfulness | 0.512 | 0.5095 | -0.003 | -0.033 | 0.9962 |
| directness | directness | 0.4685 | 0.507 | +0.038 | +0.315 | 0.1268 |
| directness | curiosity | 0.563 | 0.577 | +0.014 | +0.091 | 0.6829 |
| curiosity | warmth | 0.502 | 0.532 | +0.030 | +0.272 | 0.1699 |
| curiosity | playfulness | 0.5155 | 0.538 | +0.022 | +0.225 | 0.4534 |
| curiosity | directness | 0.5 | 0.5 | +0.000 | +0.000 | 1.0 |
| curiosity | curiosity | 0.605 | 0.7905 | +0.185 | +1.224 | 0.0 |

## 四、同向性

| 维度 | 向量Δ | 输出Δ | 同向 |
|---|---|---|---|

## 五、判定

仅极值对照 run（A/B 用历史数据）：维度敏感性：极值对照显著维度 = ['warmth', 'curiosity']（未显著维度需修 prompt 措辞或观测）