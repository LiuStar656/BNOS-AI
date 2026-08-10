# [REPORT] 定式网络速度优化实验报告（numba 融合内核：训练固定开销定型 + 推理瓶颈定位）

> 日期：2026-08-10 | 状态：[OK] | 版本：内存优化（EdgeRow 数组化）落地后，针对 step() 热路径的提速改造；用户拍板"直接用最快的"（numba prange 并行方案）

## 一、背景与需求

内存优化（EdgeRow 数组化，RSS 2138→343MB）落地后，用户提出：**训练速度和推理速度怎么优化？** 并指定"用快照试试，变量用训练的语句量做对照"（`_probe_speed.py`），最后拍板"直接用最快的"。

## 二、诊断：瓶颈不在 Python 循环，在 step 内 20+ 次全数组 numpy 操作

第一直觉（"瓶颈在 Python 循环"）被实测推翻：Hebbian/STDP 已 numba 化后，cProfile 显示 step() 每步 96 次调用占 2.16s 的绝对大头，热点是 **step 内 20+ 次 O(148776) 全数组 numpy 分配/遍历**：

| 热点 | 单点实测 |
|---|---|
| `v.argmax(axis=1)` | ~4ms/步 |
| `v*decay + noise[:,None]`（分配两次） | ~6.8ms |
| `np.maximum(ref_left-1, 0)` | 全数组 |
| `np.nonzero` / `vmax[np.arange(n), k]` / `argsort` / 清零 | 各 1-4ms |

微基准（n=148776，slots=4）确认 prange 并行内核的收益：

| 内核 | numpy | prange（parallel） | 串行 njit |
|---|---|---|---|
| WTA argmax+候选 | 5.84ms | **1.05ms**（5.5×） | 3.39ms |
| v 衰减+噪声+注入 | 6.78ms | **2.63ms**（2.6×） | 2.10ms |

## 三、改造清单（sparse_net.py，2026-08-10）

| # | 位置 | 改造 | 语义 |
|---|---|---|---|
| 1 | 传播段 | sender 循环逐行 `drive[e[0]] += w` → 收集传出突触一次 `np.add.at(drive, all_dst, all_w)` | 逐位一致（行内顺序+sender 顺序拼接后 add.at 与逐行累加顺序相同） |
| 2 | Hebbian/STDP/LTD | Python 双循环 + 每对 `row.get()` → `_apply_edge_updates`（扁平化 → `_merge_rows` numba 并行） | = 逐行 batch_update（存在键+w_max 截断，新键插入保持有序） |
| 3 | step 开头 | `v*decay + noise[:,None]` + 注入 + STD 恢复 → `_update_v` prange 融合内核 | 逐位一致 |
| 4 | step 中段 | `argmax` + `vmax[arange,k]` + `np.where` → `_wta_cand` prange 融合内核（argmax + 候选收集 + 不应期基础 -1） | 候选按神经元号升序（= np.where 顺序），vmax 直接取自候选值（省全数组 fancy 索引） |
| 5 | step 尾部 | `pre_trace = pre_trace*decay + new_spikes`（新数组）→ 就地 `*=` + `+=`（零分配）；不应期 -1 已并入内核，尾部只落 top | 终态逐位一致 |

预分配 `_is_cand/_cand_idx/_cand_val` 工作区（reset + expand pad），消除每步临时分配。

## 四、踩坑记录（三条铁律级教训）

### 4.1 argpartition 破坏语义，回退 argsort（105 万边差异）
第一版 WTA 用 `argpartition` 提速，对拍发现差异突触数 **1,056,580**——并列 key 时 argpartition 与 argsort 的 top-k **集合**可能不同 → 发放分叉 → 网络演化连锁分叉。**语义铁律优先，回退 argsort**（源码留注释）。教训：WTA 的 top-k 语义 = argsort 的确定性选择，任何"更快但集合可能不同"的算法都不可用。

### 4.2 prange 内 pre_trace 衰减会先于 STDP 读取（语义分叉）
初版把 pre_trace 衰减也融进 `_wta_cand`——但 STDP 在 WTA 之后仍要读**未衰减**的痕迹值；若内核先衰减，STDP 看到的 pre_trace 值变了（`p` vs `decay*p`），阈值过滤 `> trace_thres` 的集合可能不同 → 语义分叉。**衰减保留在 step 尾部**（就地 `*=`，零分配），内核只做 ref_left 的 -1（候选判定用未递减值，与旧时序一致）。

### 4.3 numba 细节
- `np.argsort(kind="stable")` 在 numba 0.66 报 UnboundLocalError → 键唯一（存在键已排除、新键不重复）时稳定排序无意义，改无 kind。
- `prange` 需显式 `from numba import prange`。
- **numba 首次编译延迟可混入计时段**：改签名后 `@njit(cache=True)` 缓存失效，warm 只学 1 对不足以确认全部内核编译完毕，曾出现 numba 版 37.86s vs 参考 6.90s 的假象；重跑（缓存已建）稳定 3.55s。对拍脚本的计时应"跑两遍取第二遍"。

## 五、对拍验证（语义铁律）

`_check_speed_opt.py`：v13.0 两份同种子副本，20 词对 × 3 轮同序列，参考实现（原逻辑复刻）vs numba 版：

```
[耗时] 参考实现：6.90s | numba 版：3.55s | 提速 1.9×
[对拍] ✅ 全表逐边一致（差异突触数 = 0）——语义无损
[唤起] 新=44 参考=44 一致=True
```

逐边对拍（dst/w 完全一致，容差 0）+ 唤起对拍（44=44）双门槛通过。

## 六、速度基准：训练语句量 N → 训练/推理速度（`_probe_speed.py 13.0`）

v13.0 干净快照，N ∈ [10,20,50,100,200]，每 N 重载隔离，N_ROUNDS=10：

| N句 | 每教学秒 | 唤起毫秒/次 | 新增边 |
|---|---|---|---|
| 10 | 0.1428 | 122.74 | 354,878 |
| 20 | 0.1962 | 162.68 | 714,589 |
| 50 | 0.1850 | 127.60 | 1,793,922 |
| 100 | 0.1352 | 115.59 | 3,593,332 |
| 200 | 0.0800 | 105.88 | 7,190,043 |

![速度基准](file:///e:/杂项/BNOS_AI_project/schemanet/runs/fig_speed_bench.png)

### 6.1 训练：固定开销主导（边增长不拖慢训练）
每教学秒随 N **不升反降**（0.1428→0.0800，-44%）——新增边 35 万→719 万（20 倍）没有拖慢训练。判读：训练耗时由 **O(n) 全数组固定开销**（v 遍历/WTA 遍历/清零）主导，传播只碰发放神经元的非零行（O(非零)），与突触数弱相关。这验证了稀疏化的结构性收益：**训练速度 ≈ 神经元数决定，不随知识量增长**。

### 6.2 推理（唤起）：新瓶颈，比训练慢 2-4 倍
唤起 105-163ms/次（3 步 → 35-54ms/步）vs 训练步 ~10-20ms/步。根因：唤起是**连续 step 不重置**场景——静息态 v 衰减累积 → 大量过阈 → 传播扇出宽 + WTA 候选多。这是优化前的原逻辑遗留，numba 融合未触及（传播/WTA 本身已并行，瓶颈在"过阈神经元数量"）。**推理优化的正确方向 = 压过阈数量/传播扇出**（见 §七）。

## 七、下一步建议（推理瓶颈）

唤起慢的根因是静息态自发大规模发放 → 传播 Python 循环宽。候选方向（按收益/成本）：

1. **噪声/阈值侧**：降低静息过阈（θ 调优 / noise_p 调低 / inh_loose 清扫强化）——抑制"无输入也炸"；
2. **传播侧向量化**：把传播段的 sender 循环改成目标侧全量累加（CSC 传入突触索引，GPU 方案已规划）——消除 Python 级 sender 循环；
3. **唤醒计数**：唤起时如果连续 N 步发放规模超限，提前截断（有界回响）。

## 八、数据留档索引

| 项目 | 位置 |
|------|------|
| 基准数据 | `runs/_speed_bench.json`（5 档全量明细 + 判读） |
| 图表 | `runs/fig_speed_bench.png`（每教学秒/唤起毫秒/突触数 3 子图） |
| 对拍脚本 | `_check_speed_opt.py`（语义对拍 + 测速，门槛=差异 0） |
| 基准脚本 | `_probe_speed.py`（训练语句量对照） / `_plot_speed.py`（画图） |
| 优化代码 | `sparse_net.py`：`_update_v`/`_wta_cand`/`_merge_rows`/`_merge_row`/`_apply_edge_updates` |
| 前级报告 | `docs/reports/[REPORT]-定式网络内存优化探针实验报告-三种存储结构RSS实测.md` |
