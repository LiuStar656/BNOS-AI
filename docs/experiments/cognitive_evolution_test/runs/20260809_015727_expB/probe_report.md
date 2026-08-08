# 实验 B 报告：人格漂移 → prompt → 输出 因果验证

- run_dir：`E:\杂项\BNOS_AI_project\docs\experiments\cognitive_evolution_test\runs\20260809_015727_expB`
- 模型：deepseek-v4-flash  temperature=0.7
- 输入：20 条（POOL_NEUTRAL） × 5 采样 × 2 组

## 一、组设计

| 组 | 含义 | 向量 |
|---|---|---|
| A_seed | 基线 | {"warmth": 0.41, "playfulness": 0.52, "directness": 0.14, "curiosity": 0.1} |
| B_drift | 真实漂移 | {"warmth": 0.4339, "playfulness": 0.5225, "directness": 0.2342, "curiosity": 0.2} |
| C_low / C_high | 极值对照 | warmth 0.1 vs 0.9 |
| D_low / D_high | 极值对照 | directness 0.1 vs 0.9 |
| E_low / E_high | 极值对照 | curiosity 0.1 vs 0.9 |

## 二、显示层（.1f 精度）

A: `### 你的性格（会随使用自然演化，不需主动提及） | 各维度均为 0-100% 范围，当前值如下（0%=完全不是，100%=极致，50%=中等）： | 温暖度: 41% | 活泼度: 52% | 直接度: 14% | 好奇心: 10%`
B: `### 你的性格（会随使用自然演化，不需主动提及） | 各维度均为 0-100% 范围，当前值如下（0%=完全不是，100%=极致，50%=中等）： | 温暖度: 43% | 活泼度: 52% | 直接度: 23% | 好奇心: 20%`

跨显示阈值维度：directness: 0.140→0.234（显示 0.1→0.2）, curiosity: 0.100→0.200（显示 0.1→0.2）

## 三、输出层（estimate_style_from_reply 关键词观测）

### A vs B（真实漂移）

| 维度 | A均值 | B均值 | Δ | Cohen's d | p |
|---|---|---|---|---|---|

### 维度敏感性（极值对照 0.1 vs 0.9）

| 对照维度 | 输出维度 | low均值 | high均值 | Δ | Cohen's d | p |
|---|---|---|---|---|---|---|---|
| directness | warmth | 0.5345 | 0.5345 | +0.000 | +0.000 | 1.0 |
| directness | playfulness | 0.5145 | 0.5075 | -0.007 | -0.098 | 0.7592 |
| directness | directness | 0.4685 | 0.4767 | +0.008 | +0.066 | 0.7147 |
| directness | curiosity | 0.5525 | 0.6155 | +0.063 | +0.429 | 0.0132 |

## 四、同向性

| 维度 | 向量Δ | 输出Δ | 同向 |
|---|---|---|---|

## 五、判定

仅极值对照 run（A/B 用历史数据）：维度敏感性：极值对照显著维度 = ['directness']（未显著维度需修 prompt 措辞或观测）