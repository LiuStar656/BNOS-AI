# archive — 历史实验脚本归档

> 归档时间：2026-08-09 | 原因：schemanet 根目录 .py 堆积 45 个，其中 37 个为 v1.1 时代的历史实验脚本，已被 v2.0 方案废弃/吸收结论，统一移入本目录。
> 关联：[PLAN]-定式网络成长路线设计方案 v2.0（§一 证据链 / §十一 影响范围）
>
> 追加归档（2026-08-10）：`_debug_avalanche.py` — v13.2 超临界雪崩（神经元过度放电）复现脚本，诊断结论见 [REPORT]-定式网络说话教学v3实验报告 §六。

**归档脚本 = 冻结**：不再运行、不参与维护；结论已沉淀到 reports/ 与方案文档，原始结果留档在 runs/。需要复现历史实验时回到本目录执行（依赖 schema_net / sparse_net / grad_readout / generator，这些仍保留在根目录）。

## 归档清单（37 个，按类别）

| 类别 | 文件 | 归档理由 |
|---|---|---|
| accept 定案系列（8） | `_accept_open.py` `_accept_scale20w.py` `_accept_clean_cmp.py` `_accept_prune.py` `_accept_hybrid.py` `_accept_gen.py` `_accept_grad.py` `_accept_grad_diag.py` | v1.1 词接词定案实验（20 万直训/w_max 饱和/grad 定案），v2.0 数据专门化路线废弃 |
| grad 引擎（2） | `_grad_engine.py` `grad_learn.py` | 引擎之争无意义（都是词级），grad 降级为可选项（模块保留在根目录 grad_readout.py） |
| 引擎对比测试（6） | `_test_candidates.py` `_test_ta.py` `_test_same_tail.py` `_cand_readout.py` `_norm_cmp.py` `_gen_cmp.py` | 六引擎对照/归一化/同末词/生成对比，结论已定（wsum 最强、区分≠理解） |
| trace 系列（6） | `_check_trace_fast.py` `_diag_trace.py` `_debug_trace.py` `_debug_trace_inc.py` `_check_trace_inc.py` `_trace_beta_scan.py` | trace 引擎归档（v2.0 §七 引擎定位） |
| 句记忆/涟漪（2） | `_sent_mem.py` `_sent_ripple.py` | 稀碎版失败实锤（证据⑥）+ 整句涟漪外挂验证（证据⑦）。v2.0 涟漪须网络内长出（见 _sanzi_jing.py） |
| 调试/基准（12） | `_diag2.py` `_debug_lang.py` `_debug_lang2.py` `_debug_lang3.py` `_bench_step.py` `_bench_step2.py` `_bench_perf.py` `_par_train_check.py` `_verify_mb.py` `_check_smat.py` `_check_sparse.py` `_check_open_collide.py` | 一次性调试/性能/对拍验证脚本，结论已吸收 |
| 早期槽位扫描（1） | `combo_slots_sweep.py` | 多槽容量实验，架构已定（slots=4） |
| v13.2 雪崩复现（1） | `_debug_avalanche.py` | 超临界雪崩（神经元过度放电）诊断复现：v 指数放大、候选数爆炸、σ>>1，根因=纯兴奋网络无抑制（2026-08-10 追加） |

## 根目录保留（8 个，当前有效）

| 文件 | 用途 |
|---|---|
| `schema_net.py` | 核心网络（SchemaNet + 26 字母复述实验） |
| `sparse_net.py` | 稀疏网络（SparseSchemaNet，规模扩展核心） |
| `snapshot.py` | 模型版本链快照（增量成长硬前提，2026-08-09 落地） |
| `grad_readout.py` | grad 可微读出模块（v2.0 §七 可选项） |
| `generator.py` | 语料生成器 |
| `_data_curriculum.py` | Phase A 分级数据抽取（当前工作） |
| `_sanzi_jing.py` | 三字经第二层验证：人之初→性本善（当前工作） |
| `_version_demo.py` | 模型版本链演示（当前工作） |
