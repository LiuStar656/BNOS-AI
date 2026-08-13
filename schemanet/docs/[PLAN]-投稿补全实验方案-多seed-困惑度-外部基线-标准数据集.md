# [PLAN] 投稿补全实验方案：多 seed · 困惑度 · 外部基线 · 标准数据集

> 日期：2026-08-11 | 版本：v1.0 | 状态：[PLAN]
> 关联：[REPORT]-定式网络综合技术报告（投稿底稿）| `archive/_accept_open.py`（现有验收模板）

## 目录

## 一、背景与现状评估

投稿底稿（综合技术报告）经审稿人视角评估后，存在四类硬伤：

| 缺口 | 现状 | 审稿人视角 |
|---|---|---|
| 统计严谨性 | 几乎所有实验单 seed | "换 seed 结论还成立吗？" |
| 标准指标 | 自建留出 top-1 | "困惑度（perplexity）是多少？" |
| 外部基线 | 仅与自实现 bigram 对比 | "与 n-gram/LSTM 同语料公平对比过吗？" |
| 标准数据集 | 仅自建语料 | "在公开基准上跑过吗？" |

本文案设计 5 个补全实验（E1-E5），目标是把上述四类缺口全部闭合，使技术报告达到"可投稿"的证据等级。全部基于现有引擎（`sparse_net.py` / `grad_readout.py` / `generator.py`），不修改核心机制，只新增评估层。

## 二、目标

1. **E1**：corpus_open 上 5 seed 三路（wsum/trace/grad）top-1 稳定性，报 mean±std + 配对检验 → 闭合统计严谨性
2. **E2**：三路 + 基线在留出集上的**困惑度**（全位置 / 非 UNK 位置双口径）→ 闭合标准指标
3. **E3**：外部基线（bigram / trigram / Kneser-Ney trigram / LSTM 小模型），同词表同划分公平对比 → 闭合基线
4. **E4**：标准数据集 WikiText-2（英文公开基准）上全方法同口径对比 → 闭合标准数据集
5. **E5**：能力外置对照（剥离代码层：纯动力学回响 vs 代码层直读）→ 支撑讨论章节核心论点

约束：**不改核心引擎**（`schema_net.py` / `sparse_net.py` / `grad_readout.py` 只读引用）；新增代码为独立评估脚本；每次运行留档 `runs/时间戳/`。

## 三、方案设计

### 3.0 公共配置（E1-E4 统一）

| 项 | 值 |
|---|---|
| 网络 | SparseSchemaNet(n=8192, slots=4, theta=1.0, decay=0.9, eta=0.1, w_max=16.0, wta_k=16, noise_p=0.06, noise_amp=0.5, refractory=1) |
| 词表 | 高频 3000 + `<unk>`（与 corpus_open 契约一致 KV=3000） |
| 训练 | Hebbian（逐句 `_learn_sentence`）→ sleep（min_wake=P10, decay=0.3, eps=1e-4）→ delta_off 扫描（{0.005,0.01,0.02}，留出 150 句子集）→ train_w（lr=0.02/5ep/subsample=2000，跳过 train_ctx 变体，训后 clip+归一化） |
| 评估 | 训练子集 1000 句 / 留出子集 600 句（每 seed 独立采样） |
| 公平性 | 全部方法共用同一划分、同一词表、同一 UNK 处理 |

### 3.1 E1：多 seed 稳定性

- seed ∈ {42, 43, 44, 45, 46}（语料划分 rng = SEED+9000，训练 RNG = SEED+5000）
- 每 seed 独立完成全流程（训练→sleep→扫描→train_w→三路评估）
- 输出：三路 train/test top-1 × 5 seed → mean±std；三路两两配对检验（z 统计量，二项近似）

### 3.2 E2：困惑度

在 E1 每 seed 的留出集上计算三路困惑度：

- **wsum**：`P(w|src) = outsum 归一化 + δ 平滑`（δ=1e-6，保证无零概率）
- **trace**：插值后同口径归一化 + 平滑
- **grad**：`softmax(logits / T=1.0)` + 平滑
- 口径 1：全位置 PPL；口径 2：跳过 `<unk>` 作为目标的非 UNK 位置 PPL
- 输出：三路 × 5 seed → mean±std（双口径）

### 3.3 E3：外部基线（同语料公平对比）

| 基线 | 实现 | 指标 |
|---|---|---|
| bigram MLE | 复用 `_BigramModel` | top-1 + PPL（+δ 平滑） |
| trigram MLE | 复用 `_TrigramModel` | 同上 |
| **Kneser-Ney trigram** | `nltk.lm.KneserNeyInterpolated`（`pip install nltk`）；若 Python 3.14 不兼容则自实现插值 KN（约 60 行） | top-1 + PPL |
| **LSTM 小模型** | torch（已装 2.13 CPU）：embed=128 / hidden=128 / 1 层 / dropout=0.2，Adam lr=1e-3，batch=64，≤10 epochs（训练 80% 内再分 10% 作验证选最优 epoch） | top-1 + PPL |

公平性：LSTM 与 KN 使用与 SchemaNet **完全相同**的词表、划分、UNK 处理（均从同一 tokenized 语料构建）。

### 3.4 E4：标准数据集 WikiText-2

- 数据源：`wikitext-2-raw-v1.zip`（公开，约 4.5MB，2M tokens，33k 词）
- 预处理：正则分词（保留英文单词/数字/标点）→ 高频 3000 + `<unk>` 截断（与 KV=3000 契约一致）
- 全方法同口径：SchemaNet 三路 + bigram/trigram/KN + LSTM（80/20 划分，seed=42）
- **诚实预期**：绝对 PPL 会很高（词表截断 + crc32 无语义编码），论文重点报**相对差距**（SchemaNet vs 基线）
- 备选：若下载失败 → PTB（nltk 内置）或 `corpus_open20w`（20 万句公开源合成），并在报告中注明替代原因

### 3.5 E5：能力外置对照（支撑讨论章节）

- 剥离代码层：注入前缀后**纯动力学回响** top-1（`_evoke_prefix`） vs **代码层直读**（wsum）→ 留出集命中率对比
- 输出：表（动力学 vs 代码层 × top-1），量化"能力外置"程度
- 复用现有历史证据（回响 0.247 / 续推 0%）做同口径正式对照

## 四、分阶段实施计划

| Phase | 内容 | 产出 |
|---|---|---|
| 0 | 环境准备：`pip install nltk`；下载 WikiText-2（失败走备选） | 依赖就绪 |
| 1 | 编写 `_paper_eval.py`（公共函数 + E1/E2/E3 一体化；E4 独立 `_paper_wikitext.py`；E5 独立 `_paper_outsourcing.py`） | 脚本 |
| 2 | 跑 E1-E3（corpus_open，5 seed，每 seed 即时留档） | `runs/` 数据 |
| 3 | 跑 E4（WikiText-2 全方法） | 同上 |
| 4 | 跑 E5（能力外置对照） | 同上 |
| 5 | 汇总表 + 图（matplotlib：多 seed 柱状图、PPL 对比、WikiText 对比）→ 更新技术报告 §5.2/§7 | 图表 + 报告修订 |

## 五、风险评估

| 风险 | 概率 | 缓解 |
|---|---|---|
| nltk 与 Python 3.14 不兼容 | 中 | 自实现插值 Kneser-Ney（兜底，附正确性自检） |
| WikiText-2 下载失败 | 中 | 备选 PTB / corpus_open20w，报告注明原因 |
| LSTM CPU 训练慢 | 中 | hidden=128 已小；先跑 1 epoch 测速；epochs≤10 + early stop |
| 5 seed 总时长 | 中 | 每 seed 独立脚本循环 + 即时留档，可中断续跑（已有 run 目录跳过） |
| PPL 极高导致数值溢出 | 低 | δ 平滑 + 对数域累加 |

## 六、测试计划

1. **正确性自检**：n-gram 基线 PPL 与手动小样例比对；LSTM 过拟合冒烟（1 epoch 后 train PPL 应显著下降）
2. **公平性检查**：确认各方法词表/划分/UNK 处理逐字段一致
3. **对拍回归**：E1 的 seed=42 结果与历史 `_accept_open` 结果对齐（误差 <1%），证明脚本未破坏评估口径
4. **留档检查**：每次运行生成独立 `runs/时间戳/result.json`（含 config/结果/seed）

## 七、影响范围

- **新增文件**：`_paper_eval.py`、`_paper_wikitext.py`、`_paper_outsourcing.py`（独立评估脚本，不改核心引擎）
- **修改文件**：技术报告 `[REPORT]-定式网络综合技术报告...md`（补实验结果表与图表）
- **数据**：新增 `runs/` 留档目录（不触碰既有 v1-v55 版本链与归档）
- **不修改**：`schema_net.py` / `sparse_net.py` / `grad_readout.py` / `generator.py`
