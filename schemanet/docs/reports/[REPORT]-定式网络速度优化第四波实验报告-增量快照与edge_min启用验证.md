# [REPORT] 定式网络速度优化第四波实验报告（增量快照与 edge_min 启用验证）

> 日期：2026-08-10 | 状态：[OK] | 版本：接第三波（3.2×）之后；增量事件日志落地（日志增量 2.3ms/句 vs 全量 save 4.5s）、快照 f64 存储修复、edge_min 启用验证（检索质量持平 → 可启用）

## 一、背景与需求

用户拍板"收完 CPU 尾巴"：① 增量快照（实验循环最后大头：save 4.5s 全量序列化）；② edge_min 启用验证（唤起 2.5× 杠杆，但需确认是否伤检索）。按 `docs/[PLAN]-定式网络记忆持久化方案（Checkpoint+增量事件日志）` 实施 Phase 0 核心。

## 二、增量快照（`_net_log.py`，新增）

### 2.1 设计（按方案文档 + 两处增强）

| 组件 | 实现 |
|---|---|
| E 事件（教学经历） | `{"t":"E","words":[...],"slot":0,"rng":{...}}`，**附 rng 状态**（增强①：教学步有噪声 noise_p=0.06，重放必须恢复原始噪声序列才能位级一致；方案对拍容差 1e-9 即此妥协，本实现做到严格 0 差异） |
| O 事件（RL 差分） | strengthen/decay/delete 预留（Phase 2 接入） |
| checkpoint | 复用 `save_snapshot` 版本机制 + active 归档（**空日志也落空归档文件 = checkpoint 锚点**，增强②：recover 靠 archive 文件定位 checkpoint） |
| recover_latest | load_version(最近 checkpoint) + 重放 active 日志 |
| 写盘 | 文件句复用（Windows 每次 open/write/close 有安全扫描开销 ~40ms/次 → 句柄复用后日志增量仅 2.3ms/句） |

### 2.2 实测（100 句，机器负载期）

```
纯学习 100 句: 5.82s（58ms/句）| 学习+日志: 6.06s | 日志增量: 2.3ms/句（4%）
日志: 267B/句（含 rng 状态）| 恢复: 8.5s（checkpoint 加载 ~3s + 重放 ~5.5s）
```

### 2.3 对拍（真实崩溃恢复场景：checkpoint 学习前 → 100 句 → recover = checkpoint+重放）

```
[对拍] 重放恢复 vs 直接学习: 差异边数 = 0  ✅ 位级一致
[对拍] 重放恢复 vs 崩溃时状态: 差异边数 = 0  ✅ 位级一致
```

**严格 0 差异**（方案测试计划 #1 的门槛是容差 1e-9，本实现靠 rng 状态重放做到 0）。

### 2.4 踩坑

| 坑 | 现象 | 修复 |
|---|---|---|
| rng 状态 128 位 | `np.uint64` 转 int 溢出（PCG64 状态是 128 位，numpy 2.x） | 保持 Python int 直传 setter（内部转换） |
| 空日志无 checkpoint 锚点 | 学习前 checkpoint → archive 空 → recover 找不到版本 | 空日志也 touch 归档文件 |
| 句柄未关 | 测试清理 PermissionError（WinError 32） | close() 方法 + recover 前 flush |

## 三、快照 f64 存储修复（snapshot.py）

`_pack_net` sparse 路径 vals **float32 → float64**：

- 实证：v13.0 旧边全是 f32 派生值（此前测"无损"是假象）；**会话内新学边是 f64 增量（如 0.30000001+0.1）→ 存 f32 截断 → 恢复后与原始差 8,895 条边**（增量对拍 v1 实证）
- 修复后：checkpoint→load 往返无损，日志重放 0 差异成立
- 代价：npz 边数组 ~2 倍（56→112MB raw），旧快照（f32）载入向后兼容
- dense 后端（SchemaNet，遗留）仍 f32，未动（n 小、非主路径；如需对齐另立）

## 四、edge_min 启用验证（唤起 2.5× 杠杆的代价核查）

之前"发放集不变（~50 神经元）"只比了**数量**；集合级对比（200 词唤起）：

```
fired 集合完全相同 49 / 不同 151  —— edge_min 确实改变检索动力学
```

但**强边命中率评估**（515 条 w≥8 定式边，唤起源词看目标是否激活）：

| edge_min | 强边命中率 |
|---|---|
| 0.0（现状） | 0.101（52/515） |
| 0.5 | 0.103（53/515） |
| 1.0 | 0.101（52/515） |
| 2.0 | 0.117（60/515，+15%） |

**结论：修剪弱边不伤强定式检索（持平），2.0 甚至略升**——fired 集合差异来自弱噪声边的下游传播（去噪而非失忆）。edge_min=0.5–2.0 可启用；建议新版本从 0.5 起（保守）或 1.0（平衡），2.0 激进但实测最好。

## 五、收益更新（四波总账）

| 路径 | 波1 | 波2 | 波3 | 波4 |
|---|---|---|---|---|
| 训练对拍 | 2.0× | 2.6× | 3.2× | 3.2×（不变） |
| 唤起 | ~1× | ~持平 | ~持平 | **edge_min 0.5+ → 2.5×**（验证可启用） |
| 保存 | 4.5s 全量 | — | — | **2.3ms/句 日志**（会话级 checkpoint 4.5s） |
| 恢复 | 3.1s 全量 | — | — | checkpoint 加载 + 重放（位级一致） |

## 六、工程接入（Phase 1/2，2026-08-10 收尾）

| 文件 | 接入 | 验证 |
|---|---|---|
| `_grow_v16.py` | 主教学（108 条×轮）与 cal 修正 → `ExpLog.learn`（E）；结尾 `save_snapshot` → `log.checkpoint`（metrics 透传）；`ng.edge_min = 0.5` 配置块（带回退说明注释）；smoke 模式不落盘 | `--smoke` 全验收通过（28s，19/19 命中） |
| `_speak.py` | 对话教学 `reward_apply`/`_pain_event`/`_relief_event` → `_LOG.learn`（E）；`decay_path`/`penalize` → 操作级 O 事件 + `register_op` 注册重放（**重放执行原函数，不复制实现防漂移**；decay_path 加 `record` 开关防重放再记录） | E+O 混合对拍：9E+3O 事件重放 0 差异 ✅ |

### 6.1 操作级 O 事件设计

- `_net_log.append_op(op, **fields)`：字段随操作而定（`penalize{src,dst}` / `decay_path{path,factor}`），重放时查 `register_op` 注册表执行**原函数**（`_speak` 在 import 时注册 handler）——语义精确，`_net_log` 不复制实现
- 三原语（strengthen/decay/delete）内置保留，供独立差分场景

## 七、下一步建议

1. `_speak.py` 会话结束后周期 checkpoint（防日志无限累积；当前 active 由下次 `_grow` checkpoint 自然归档）；
2. 异步刷盘 + `--replay vX` 履历工具（Phase 3）；
3. 新版本（v17+）训练将自动带 edge_min=0.5 与日志——首跑前先确认 `_exp_logs/active.jsonl` 无历史残留（恢复锚点口径）。

## 八、数据留档索引

| 项目 | 位置 |
|------|------|
| 日志模块 | `_net_log.py`（ExpLog：learn/checkpoint/recover_latest/append_edge） |
| 恢复对拍 | `_tmp_verify_netlog.py`（真实崩溃场景：双 0 差异门槛） |
| 存储修复 | `snapshot.py` `_pack_net`（vals f64） |
| 方案文档 | `docs/[PLAN]-定式网络记忆持久化方案（Checkpoint+增量事件日志）.md` |
| 前级报告 | `docs/reports/[REPORT]-定式网络速度优化第三波实验报告-线性归并重写与LTD截断修复.md` |
