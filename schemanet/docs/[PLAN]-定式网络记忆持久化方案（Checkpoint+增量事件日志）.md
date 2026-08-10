# 定式网络记忆持久化方案（Checkpoint + 增量事件日志）

> 日期：2026-08-10 | 版本：v1.0 | 状态：[PLAN]

## 目录

## 一、背景与现状评估

**问题**：持续学习（v15 教学、`_speak.py` 对话教学）是在内存里完成的，保存粒度是**会话级**——会话结束才写 `net_after.npz` / 快照。会话中途断电、崩溃、误关，**上次保存到崩溃之间的所有经历全部丢失**。

**现状盘点**（已有底座，可直接复用）：

| 组件 | 现状 | 缺口 |
|------|------|------|
| 全量快照 | `snapshot.save_snapshot()`：npz + meta + 版本链 + 追溯索引 | 粒度粗（手动/会话末触发） |
| 版本恢复 | `load_snapshot` / `load_version`：回退任意版本 | 只能回到版本点，不能回到崩溃前 |
| 经历记录 | 无 | **丢失窗口 = 整个会话** |

**关键有利性质**（128 并发实验已实证）：教学式学习 = 干净注入——每句经历清空 `v/spikes/pre_trace`，逐句独立。因此**经历事件可以重放**：恢复 = 最近 checkpoint + 重放增量经历，Hebbian/STDP 确定性重建出同样的边更新。

## 二、目标

1. **丢失窗口从"会话级"降到"毫秒~秒级"**：每句经历即落日志，崩溃后恢复到崩溃前最近状态
2. **日志即履历**：经历日志本身就是完整训练档案（呼应"实验数据都要留档"铁律），可回溯网络学过什么
3. **不侵入学习热路径**：日志写盘异步化，不进 `_learn_sentence` 内层
4. **与版本链/快照体系融合**：checkpoint 复用现有快照版本机制，不回造轮子
5. **两类操作都可恢复**：教学经历（可重放）与 RL 操作差分（不可重放，记边更新）都能恢复

## 三、方案设计

### 3.1 总体架构

```
持续学习（内存中，每秒 ~6 句经历）
   │  每经历 append → 事件日志 experiences.jsonl（append-only）
   │  （异步批量刷盘，不进热路径）
   │  定期（按日志大小阈值）→ checkpoint（复用 save_snapshot 版本化）+ 归档日志
   ▼
崩溃 → 重启 → recover_latest()
        = load_version(最近 checkpoint) → 重放归档后剩余日志 → 恢复到崩溃前状态
```

### 3.2 两类日志事件

| 类型 | 适用 | 内容 | 重放方式 |
|------|------|------|----------|
| **E（经历事件）** | 教学式学习 `_learn_sentence`（干净注入） | `{"t":"E","words":["我","吃","苹果"],"slot":0}` | `_learn_sentence(ng, words, pats, slot)` |
| **O（操作差分）** | RL 奖励/惩罚等状态依赖操作 | `{"t":"O","op":"strengthen","src":123,"slot":0,"dst":456,"dw":0.5}` | 直接应用差分 |

- E 只记"经历了什么"（~几十字节/句），重放靠 Hebbian/STDP 确定性重建——加法系统的红利
- O 记"边更新差分"（精确值），因为 RL 操作依赖网络当时状态，只记句子无法复现
- 教学链路如果内部混合 RL（如 v13 痛觉衰减），教学外操作一律走 O 通道

### 3.3 文件布局

```
runs/
├── index.jsonl                       # 既有版本追溯索引（不动）
├── v{M}_{N}_{ts}/                    # 既有快照目录（checkpoint = 一次 save_snapshot）
│   └── net.npz
└── _exp_logs/
    ├── active.jsonl                  # 当前活跃日志（append-only，从上次 checkpoint 起）
    └── archive/                      # 归档日志（checkpoint 时把 active 移入）
        └── v{M}_{N}_{ts}.jsonl       # 文件名 = 对应的 checkpoint 版本
```

恢复规则：`最近 checkpoint + 归档后剩余 active.jsonl 全量重放`。checkpoint 把 active 归档成不可变文件，active 清空重开。

### 3.4 核心接口（`_net_log.py`，新增）

```python
class ExpLog:
    """经历日志：append 只写事件，checkpoint 触发快照+归档，recover 重建状态。"""

    def __init__(self, base=None):
        self.log = Path(base or RUNS) / "_exp_logs" / "active.jsonl"
        self.arch = self.log.parent / "archive"

    # ── 写 ──
    def append_learn(self, words, slot=0):
        """教学经历事件（E）。异步批量刷盘，不进热路径。"""
        self._write({"t": "E", "words": list(words), "slot": int(slot),
                     "ts": time.time()})

    def append_edge(self, op, src, slot, dst, dw):
        """RL 操作差分（O）。op ∈ {strengthen, decay, delete}。"""
        self._write({"t": "O", "op": op, "src": int(src), "slot": int(slot),
                     "dst": int(dst), "dw": round(float(dw), 6), "ts": time.time()})

    def checkpoint(self, ng, vocab, pats, cursor, tag="checkpoint",
                   parent=None, base=None):
        """全量快照（复用 save_snapshot）+ 归档 active 日志。返回版本号。"""
        out = save_snapshot(ng, parent=parent, tag=tag,
                            vocab=vocab, pats=pats, cursor=cursor)
        self._archive(version=out.name)

    # ── 读（恢复入口）──
    def recover_latest(self, base=None):
        """最近 checkpoint + 重放归档后剩余日志 → (ng, vocab, pats, cursor)。
        崩溃后一键恢复：比 load_version 多走一段日志重放。"""
        ng, vocab, pats, cursor = load_version(最近版本号)
        for ev in self._iter_after(最近版本):      # 归档后剩余 active 全量重放
            if ev["t"] == "E":
                _learn_sentence(ng, ev["words"], pats, slot=ev["slot"])
            elif ev["t"] == "O":
                _apply_diff(ng, ev)               # 边差分直接应用
        return ng, vocab, pats, cursor
```

### 3.5 关键设计决策

| 决策 | 理由 |
|------|------|
| 日志记事件不记权重差分（教学类） | 教学式干净注入可重放；日志省 10-100 倍空间；履历可读 |
| RL 操作走差分通道 | 状态依赖操作无法用句子复现，差分保证确定性恢复 |
| checkpoint 复用 `save_snapshot` 版本机制 | 版本链/回退/追溯全部免费继承，不回造轮子 |
| 日志按版本归档 | 恢复点与版本一一对应，"版本=记忆线"清晰可回溯 |
| 异步批量刷盘（默认每 10 句或 200ms fsync） | 丢失窗口可配置（0 句~10 句），学习吞吐不受影响 |
| 快照触发按日志大小（默认 8MB） | 恢复耗时 = 快照加载 + 短日志重放，稳定有界 |

## 四、分阶段实施计划

### Phase 0：日志模块 + 教学接入
- `_net_log.py`：ExpLog 类（append/checkpoint/recover）
- `_learn_sentence` 调用处接入 `append_learn`（先同步写，验证正确性）
- 对拍：记录日志重放 vs 原始训练，逐边对比 `edge_by_slot` 一致性

### Phase 1：崩溃恢复闭环
- `recover_latest()` 完成 + 模拟崩溃测试（kill -9 / 断电模拟：学习 100 句后强杀，恢复比对）
- 阈值自动 checkpoint（日志超 8MB 自动快照+归档）

### Phase 2：RL 差分通道
- `_speak.py` 的 reward/penalty/pain 衰减接入 `append_edge`
- 对话教学全流程对拍：日志恢复后的网络 == 原始会话结束网络

### Phase 3：异步化 + 履历工具
- 日志写盘异步化（后台线程批量刷）
- `_net_log.py --replay vX` 命令行入口：任意版本 + 日志 → 重建到任意时刻
- 履历分析：`--summary` 输出网络学过什么（词对/频次/时间线）

## 五、风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| 重放结果与原始不完全一致（教学链非纯干净注入时） | 中 | 对拍门槛：恢复前后逐边比对；不一致 → 该操作降级为 O 差分通道 |
| 日志体积膨胀 | 低 | 8MB 自动 checkpoint 归档；E 事件仅几十字节/句，1 亿句才 ~10GB |
| 异步刷盘丢最后几句 | 低 | 可配置 fsync 粒度；教学/推理切换时强制 flush |
| 快照本身损坏 | 低 | 版本链多版本留存；`save_snapshot` 写临时文件 + rename 原子落盘（Phase 0 补） |
| 与既有版本链冲突（日志/快照交错） | 中 | 日志只挂靠 checkpoint 版本；普通版本训练不清日志（下一 checkpoint 自然覆盖语义） |

## 六、测试计划

1. **重放一致性对拍**（核心门槛）：v13 快照 + 教学 100 句 → 记日志 → 从 checkpoint 重放 → `edge_by_slot` 逐边比对 == 原网络（容差 1e-9）
2. **断电模拟**：学习中途 `taskkill /f` → `recover_latest()` → 比对恢复后网络与崩溃前快照时刻网络
3. **RL 差分对拍**：`_speak.py` 会话（含奖励/惩罚/痛觉）→ 日志恢复 → 与原始会话结束网络逐边一致
4. **性能影响**：接入日志前后 `_probe_boundary.py` 学习耗时差 < 5%（同步模式）/< 1%（异步模式）
5. **版本链融合**：checkpoint 产生的版本在 `index.jsonl` 可追溯、可回退、链完整

## 七、影响范围

| 文件 | 改动 |
|------|------|
| `_net_log.py`（新增） | ExpLog 类：append_learn / append_edge / checkpoint / recover_latest |
| `_probe_boundary.py` / `_speak.py` | 学习入口接入日志（薄封装，不入侵规则） |
| `snapshot.py` | 仅补 `save_snapshot` 原子写（临时文件+rename），其余不动 |
| `docs/[OK]-定式网络核心框架.md` | §九 路线补"记忆持久化"条目；§五 验证汇总补对拍结论 |

**不做**：不改 `_learn_sentence`/Hebbian 内核；不引入数据库/第三方库；不影响快照版本机制本身。
