# [REPORT] 定式网络速度优化第二波实验报告（噪声内化与传播单 pass 融合内核定型）

> 日期：2026-08-10 | 状态：[OK] | 版本：接第一波（numba 融合内核，2.0×）落地之后；用户追问"最后能提速多少"——本轮先精确定位训练/唤起/快照三段成本，产出三个位级一致的融合内核原型并落地

## 一、背景与需求

第一波 numba 提速已定型（参考实现 6.90s → numba 版 3.55s = 1.9–2.0×，逐边对拍 0 差异）。用户继续问**还能提速多少**。本轮目标：

1. 精确定位训练步（~7ms/步）、唤起传播步（~25ms/步）、快照 IO（save 4.5s / load 3.1s）三段的真实成本构成；
2. 验证三个融合内核原型（噪声内化 / 训练三段合一 / 传播单 pass）的位级一致性与收益；
3. 落地并过 `_check_speed_opt.py` 对拍铁律。

## 二、诊断：训练步三段构成（本轮实测，n=148776 slots=4）

cProfile（480 步）确认 numba 内核本身快（`_update_v`/`_wta_cand` 合计 <1ms/步），**step 的 Python 级代码占 13.3s/18.5s**。逐段计时精确定位：

| 段 | 实测 ms/步 | 占比 | 性质 |
|---|---|---|---|
| noise 生成（rng.random + 比较 + 乘） | 1.2–1.8 | 25–30% | 3 次全数组 pass + 1.2MB 临时 |
| `_update_v`（prange） | 0.05–0.5 | ~8% | 已并行 |
| `_wta_cand`（prange） | 0.4–0.6 | ~10% | 已并行 |
| Hebbian/STDP `_apply_edge_updates` | 0.9（发放步） | ~13% | Python 侧组装 |
| 其余（topk/痕迹/清零等） | ~1 | ~15% | 已近最小 |

**训练步结论：noise 生成是当前最大可压缩项**——它完全可以内化进 `_update_v` 内核（比较/乘法是 IEEE 确定性运算，位级一致）。

### 2.1 唤起传播步：瓶颈 = 传播宽度，不是 add.at

| 段 | 实测 ms/步 | 占比 |
|---|---|---|
| 传播各部件（where/collect/concat/filter/add.at） | ~4 | 8–16% |
| **step 其余（含 WTA 候选多、静息累积过阈）** | ~20 | 84–92% |

高频词"的"单神经元传出突触 **41,603 条**（"我" 4,351×4 神经元）→ 一次唤起传播扇出 31–42 万边。这与第一波报告 §七 的判读一致：**推理优化 = 压过阈数量/传播扇出**（edge_min 弱突触修剪，v13.2 机制，代码已实现但 v13.0 快照未启用）。

### 2.2 快照：训练循环的隐性固定开销

| 项 | 实测 | 占比（N=10 场景） |
|---|---|---|
| load_snapshot（1,400 万边） | 3.06s | ~35%（学习仅 14s） |
| save_snapshot（Python 三层循环 + savez_compressed） | 4.47s | |

随突触数线性增长（N=200 时 2,000 万+边）。增量事件日志方案已规划（`docs/[PLAN]-定式网络记忆持久化方案`），本轮先报告不实施。

### 2.3 两个新发现（非提速，但影响正确性）

1. **`snapshot.py` `_PARAMS_FIELDS` 缺 7 个 v13.2 新机制字段**（`inh_loose/std_dep/std_rec/edge_min/inh_norm/refract_clear/gain`）→ 新机制训练的网络存/载后**静默回退默认关闭**，语义不可恢复。
2. **不应期双递减潜伏 bug**：`_wta_cand` 内核内已做 ref_left 基础 -1（`sparse_net.py:294`），但 step 尾部仍保留 `np.maximum(refractory_left-1, 0)`（`sparse_net.py:652`）→ refractory=1 时饱和到 0 无感（对拍因此通过），**refractory≥2 时每步递减两次，语义分叉**。

### 2.4 测量伪影修正：`_bench_kernel.py` 的"prange 比串行慢 6.7×"是错的

第一波遗留的微基准显示 WTA prange 22ms vs 串行 3.3ms——本轮控制变量复测（预热 8 轮 + 交替计时）推翻该结论：

| 内核 | numpy | prange（现用） | 串行 njit |
|---|---|---|---|
| update_v | 4.2ms | **0.054ms**（77×） | 0.23ms |
| WTA | 3.86ms | **0.57ms**（6.8×） | 2.46ms |

此前 22ms 是 numba 缓存加载/线程池首启混入计时（与第一波 §4.3 的教训同源：**计时应跑两遍取第二遍**）。**prange 并行内核有效，无需回退**。

## 三、融合内核原型验证（位级一致 ✓）

三个原型在 `_tmp_fused_kernels.py` 中实现并验证（对拍铁律：语义逐位一致，容差 0）：

| 原型 | 语义 | 位级一致 | 速度 |
|---|---|---|---|
| A. **噪声内化**：`rng.random` 原始值传入内核，内部 `<p` / `×amp` | = `(raw<p)*amp` | ✓ | 1.805 → **1.109ms**（-39%） |
| B'. **训练三段合一**（prange）：衰减+噪声 → 注入 → 疲劳恢复 → refract_clear → argmax+候选+ref-1 单内核 | = `_update_v`+refract_clear+`_wta_cand` | ✓（v/ref/lastk/n_c 全等） | 1.826 → **1.253ms**（-31%） |
| C. **传播单 pass**：numba 逐边累加（含 edge_min 过滤，免 concat 临时与 add.at） | = concat+过滤+`add.at`（42 万边） | ✓ | 1.114 → **0.833ms**（-25%） |

踩坑：B' 若用**串行** njit 反而慢（2.49ms > 2.16ms）——三段合一必须 prange；C 原型首测位级不一致是传参 bug（fat=1 意为全疲劳→全跳过），修正后 0 差异。

## 四、落地改造（sparse_net.py，2026-08-10）

| # | 位置 | 改造 | 语义 |
|---|---|---|---|
| 1 | step 开头 | spikes 为空（学习路径必然）→ 走新内核 `_train_core`（噪声内化 + 三段合一，prange）；有 spikes（唤起）→ 保持 `_update_v`+传播+`_wta_cand` 原路径 | 两路径均与参考实现逐位一致 |
| 2 | 传播段 | `concat + edge_min 过滤 + np.add.at` → 收集拼接后单 numba pass `_prop_accum`（edge_min 过滤内嵌） | 逐位一致（原型 C 已验证） |
| 3 | step 尾部 | 删除 `np.maximum(refractory_left-1, 0)`（内核已做基础 -1，修复 refractory≥2 双递减 bug） | 与参考实现单次递减一致 |
| 4 | 内核 | `_train_core` 保留 fat 疲劳恢复（std_dep>0 时） | 与 `_update_v` 一致 |

预分配工作区复用第一波 `_is_cand/_cand_idx/_cand_val`，无需新增。

## 五、对拍验证（语义铁律）

`_check_speed_opt.py`：v13.0 两份同种子副本，20 词对 × 3 轮同序列，参考实现（原逻辑复刻）vs 新内核版：

```
[耗时] 参考实现：7.01s | 新版：2.74s | 提速 2.6×
[对拍] ✅ 全表逐边一致（差异突触数 = 0）——语义无损
[唤起] 新=44 参考=44 一致=True
```

（第一波基线 2.0× → 本轮 2.6×；缓存冷态首跑 2.80s，热态 2.74s，无编译污染）

### 5.1 新内核全分支对拍（v13.0 参数不覆盖的分支专项验证）

v13.0（refractory=1 / std_dep=0 / refract_clear=False / 学习无传播）不覆盖新内核的 else 分支与激活机制组合，另构造三组**学习+唤起混合序列**（唤起步保留 spikes → 走传播路径）逐边对拍：

| 组合 | 参数 | 差异突触数 |
|---|---|---|
| 1 | refractory=1, std_dep=0.6, std_rec=0.85, inh_loose=0.3, edge_min=0.3, inh_norm=4.0 | 0 ✅ |
| 2 | refractory=2, refract_clear=True（双递减曾分叉的组合） | 0 ✅ |
| 3 | refractory=3, std_dep=0.5, refract_clear=True, inh_loose=0.5, edge_min=0.2 | 0 ✅ |

### 5.2 快照参数往返验证

`edge_min=0.4 / std_dep=0.7 / inh_loose=0.2 / refract_clear=True` 存载后全部保持（此前静默回退默认关闭）✅

### 5.3 唤起路径实测

冻结态唤起（learn_gate=False，3 步）稳态 79–115ms/次，与改造前 116ms 持平——传播融合省的是内核层（每传播步 ~0.3ms），端到端被传播宽度瓶颈淹没；**唤起提速的正确杠杆是 edge_min 弱突触修剪**（见 §七）。

## 六、收益测算（实测口径，相对原始参考实现）

| 路径 | 第一波后 | 本轮实测 | 依据 |
|---|---|---|---|
| 训练（20对×3轮对拍） | 2.0× | **2.6×** | §五 实测 |
| 唤起传播步 | ~1× | ~持平（内核省 ~0.3ms/步） | §5.3；瓶颈=传播宽度，需 edge_min |
| 快照 | ~1× | 参数持久化修复 ✅（IO 未动） | 增量方案另立 |

## 七、下一步建议

1. **修 `_PARAMS_FIELDS`** ✅ 已修复（本轮 §五.5.2 验证往返）；`gain` 数组仍未入快照（需 `_pack_net` 另存，另立）；
2. **v13.2 机制启用基准**：edge_min>0 的唤起吞吐对照（弱突触修剪后的传播宽度实测）——唤起提速的主杠杆；
3. Hebbian/STDP 的 `row_to_a` dict 构建（O(k²) Python）与 `_apply_edge_updates` 组装整体移入 numba（约省 0.5–1ms/发放步）；
4. 快照增量事件日志落地（`[PLAN]-定式网络记忆持久化方案`）。

## 八、数据留档索引

| 项目 | 位置 |
|------|------|
| 对拍脚本 | `_check_speed_opt.py`（语义对拍 + 测速，门槛=差异 0） |
| 分支对拍 | `_tmp_verify_branches.py`（新内核全分支回归对拍：机制组合 + refractory≥2 + 唤起传播路径） |
| 优化代码 | `sparse_net.py`：`_train_core` / `_prop_accum` / step 分支改造 / 双递减修复 |
| 参数修复 | `snapshot.py`：`_PARAMS_FIELDS` 补 6 个机制字段 |
| 内核基准 | `_bench_kernel.py`（注意 §2.4 的测量伪影，计时需预热 8 轮以上） |
| 前级报告 | `docs/reports/01-速度与性能/[REPORT]-定式网络速度优化实验报告-numba融合内核与训练固定开销定型.md` |
