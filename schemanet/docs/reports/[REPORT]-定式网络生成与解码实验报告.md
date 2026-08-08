# [REPORT] 定式网络生成与解码实验报告（Phase 3："会学也会说"）

> 日期：2026-08-09 | 版本：v1.0 | 状态：[OK]（验收通过）
> 关联：[PLAN]-定式网络向大模型方向发展方案.md（上级目录，v1.1 Phase 3）| [OK]-定式网络技术档案.md
> 代码：`schemanet/generator.py`（生成器）| `schemanet/_accept_gen.py`（验收编排）| `schemanet/sparse_net.py`（save_net/load_net 序列化）
> 语料：`schemanet/data/corpus_large.json`（1814 句，训练 1451/留出 363）
> 留档：`schemanet/runs/20260809_055328`（最终版，train_w 镜像向量化 11.8s）| `runs/20260809_051913`（初版，train_w 373s）
> 上一阶段：[REPORT]-定式网络梯度可行性实验报告.md（Phase 4a，同目录）

## 目录

- [一、实验背景与目标](#一实验背景与目标)
- [二、设计](#二设计)
- [三、结果](#三结果)
- [四、发现与分析](#四发现与分析)
- [五、结论](#五结论)
- [六、复现与留档](#六复现与留档)
- [七、后续方向](#七后续方向)

---

## 一、实验背景与目标

**方向**：定式网络（SchemaNet）自主进化路线。Phase 4 已让网络获得**梯度在线学习**能力（参数级、W 结构不动），下一步是让网络把学到的转移"说出来"——**Phase 3 生成与解码**，目标"会学也会说"闭环：给定前缀，逐词采样生成完整句，流畅度达标。

**Phase 3 目标（方案 v1.1 §六 验收项）**：
1. 20 条生成样例人工评估报告（5 分制，≥3/5 达标）
2. 与前缀一致性：生成句开头与条件前缀一致（20/20）
3. BLEU 基线对照（诚实定位，不追求超越 LLM）

**核心问题**：上一阶段（Phase 0-2）网络只能"读"（next-token 预测 top-1），不能"说"（多步生成完整句）。且训练链里 train_w 全量 373s 是工程瓶颈，Phase 3 生成调参场景需要反复重训——提速与生成器同步解决。

## 二、设计

### 2.1 生成引擎（generator.py，Generator 类）

给定前缀 → 逐词采样 → 完整句。**主引擎 = 梯度读出**（Phase 4 GradReadout.train_w 精调后的 `_logits_w`），对照 Hebbian 静态读出（wsum/trace）。

```
logits[w_t] = Σ_pos ctx_wgt[pos] × score(w_t, prefix[last-pos])   # 梯度读出
score(w, src) = Σ_{j∈pats[w]} W[j,0,src] / k
```

**解码策略（纯 numpy，零外部依赖）**：
- **top-k 采样**：只保留 logits 前 k 大 → 温度 softmax → 采样（贪心 argmax 作对照）
- **温度 T**：分布锐度
- **重复惩罚 penalty**：对生成历史已出现词的 logits ÷ penalty（防"很很很很"式退化）
- **停止**：达 max_len 或无可转移信号候选

**最终调优参数（2026-08-09）**：`top_k=12, T=1.1, penalty=2.5`。初版 0.8/1.2 下高频词重复退化（"很很很很"），penalty 提至 2.5 修好。

### 2.2 序列化（sparse_net.py save_net/load_net）

生成