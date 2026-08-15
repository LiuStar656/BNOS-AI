# 论文复现包：外部反馈极性经增量记忆装置塑造大模型行为

> 对应论文：《外部反馈极性是否经增量记忆装置塑造大模型行为？——基于行为风格向量演化环的实证》
> 本文件夹集中存放论文全部实验数据、核心实现与图表脚本，供审阅与复现。

## 目录结构

```
paper_repro/
├── README.md                 # 本说明
├── src/
│   ├── personality.py        # 增量记忆装置核心实现（状态/观测/演化/注入，纯标准库）
│   ├── make_figures.py       # 论文图 1、图 2 生成脚本（需 matplotlib）
│   ├── external_validation.py          # 外部效标裁判脚本（独立 LLM 打分，§6.6/附录 E）
│   └── analyze_external_validation.py  # 外部效标结果分析（Spearman/分组对比）
├── data/
│   ├── condB_deepseek/       # DeepSeek-v4-flash 条件 B 轮次数据（B1×100 / B2×100 / B2NEG×60 / 复跑×30）
│   ├── condB_glm/            # GLM-5.2 条件 B 轮次数据（B2×60 / B2NEG×60）
│   ├── condB_qwen/           # Qwen3.7-max 条件 B 轮次数据（B2×55 / B2NEG×60）
│   ├── formatAB/             # 注入格式 2×2 对照统计结果 + 原始样本
│   ├── extval/               # 外部效标验证逐样本裁判数据（23 条，附录 E）
│   └── reports/              # 三份实验报告（轮次表/文本抽样/机制分析的完整来源）
└── figs/                     # 论文图 1（装置环数据流）、图 2（三模型×双极性轨迹）
```

## 数据说明

- `*_rounds.json`：每条轨迹的完整轮次记录，含注入段文本、原始输出、观测与演化向量；`final_vector` 字段为终态（论文表 4 与附录 A 末行以此为准）。
- `formatAB_results.json`：注入格式 2×2 对照（directness 0.1 vs 0.9，n=100/组）的均值±SD、Cohen's d 与 p 值；`probe_samples.jsonl` 为原始样本。
- `extval/extval_results.json`：外部效标验证 23 条样本（三模型 × B2/B2NEG 代表轮次），含自然回复、观测值与独立裁判四维打分。
- 报告见 `data/reports/`：条件 B 反馈极性对照、指令缺失假设验证、expB 行为锚点验证。

## 复现方法

**1. 生成论文两张图**（只需 matplotlib）：

```bash
pip install matplotlib
python src/make_figures.py
```

**2. 观测与演化函数**：`src/personality.py` 中 `estimate_style_from_reply`（观测投影）、`compute_new_mood`（演化公式）与 `build_personality_section`（注入构建）为论文 §4 的对应实现，纯标准库可直接调用。

**3. 完整轨迹实验**：需 DeepSeek / GLM / Qwen 三家 API（temperature=0.7，种子向量 v0=(0.8, 0.5, 0.3, 0.6)），参数与输入池见论文 §5。因依赖 API 额度，未随包发布运行脚本；核心装置与全部结果数据已包含，可直接核验论文附录 A–D 的每个数值。

**4. 外部效标验证**（§6.6/附录 E）：`src/external_validation.py` 调用独立裁判模型（deepseek-v4-flash，temperature=0）对样本【自然回复】打分，需 DeepSeek API key（环境变量 `DEEPSEEK_API_KEY`）；`src/analyze_external_validation.py` 复现 Spearman 相关与条件间方向性统计（纯标准库，无需 API）。

## 与论文的对应关系

| 论文章节 | 数据/代码 |
|---|---|
| §4 装置设计 | `src/personality.py` |
| §5 实验设计 | `data/condB_*`、`data/formatAB` |
| §6 结果 | `data/condB_*`（表 3/4、图 2）、`data/formatAB`（附录 D） |
| 附录 A 轮次表 | `data/condB_*/*_rounds.json` |
| 附录 B 文本抽样 | `data/reports/条件B报告 §四.2` |
| 附录 C 关键词表/公式 | `src/personality.py` |
| §6.6/附录 E 外部效标验证 | `data/extval/`、`src/external_validation.py`、`src/analyze_external_validation.py` |
| 图 1/图 2 | `figs/`、`src/make_figures.py` |
