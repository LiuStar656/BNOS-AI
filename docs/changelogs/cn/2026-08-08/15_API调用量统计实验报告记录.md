# 15 API 调用量统计：实验报告记录总量与各 Agent 调用量

## 问题描述

用户进行 5 Agent 40 轮真实实验前提出：**实验完成后要在报告里记录本次实验 API 调用量，以及各 Agent 的 API 调用量**。此前实验数据（decisions.jsonl / evolution.json / topic_report.md）均不含 LLM/API 调用量指标，无法核算实验成本与调用分布。

## 根因分析

F9 子进程架构下 LLM 调用发生在 AAA 子进程内（`aaa_serve.py` 的 llm_fn，决策 + 后台 review 都经过它），平台（父进程）看不到子进程内的调用次数——stdin/stdout 协议只有 ping / pool_batch / flush_review / shutdown 四种请求，无统计查询通道。同时平台侧自我介绍等直连调用也不在统计内。

## 修改方案

### 1. `aaa_serve.py`：LLM 调用计数 + `llm_stats` 协议请求

`_make_llm()` 返回带计数包装的函数（决策与后台 review 都经过 llm_fn，计数全覆盖）：

```python
def _make_llm():
    _base = _llm_real if ...real... else _llm_fake
    stats = {"calls": 0}

    def _counted(prompt):
        stats["calls"] += 1
        return _base(prompt)

    _counted.stats = stats
    return _counted
```

新增协议请求 `{"type": "llm_stats"}` → 响应 `{"code": 0, "data": {"calls": N}}`。

### 2. `agent_bridge.py`：`llm_stats()` 方法

- subprocess 模式：发 `llm_stats` 请求取子进程内计数；
- inline 模式：`__init__` 对 `llm_fn` 做计数包装（`self._inline_llm_calls`），返回本进程决策路径计数（对照模式，后台 review 线程调用不计，已注释说明）。

### 3. `run_pool_experiment.py`：主进程计数 + 收尾落盘

- 主进程直连 LLM 包装计数（自我介绍等平台侧调用，`_platform_llm_calls`）；
- 收尾（flush_review 后、close 前）收集各 Agent `llm_stats()`，写入 `run_dir/llm_stats.json`：

```json
{"mode": "subprocess", "fake_llm": false,
 "platform_direct": 5, "total": 356,
 "per_agent": {"agent:0": 71, "agent:1": 70, ...}}
```

- 打印汇总 `[API 调用量] total=N (AAA 子进程 X + 平台直连 Y)`。

### 4. `topic_report.py`：报告渲染「四、API 调用量统计」节

- `_load_llm_stats` / `_render_llm_stats`：总量（含 fake 标注）+ 平台直连/子进程内拆分 + 各 Agent 明细表（调用量 + 占比）；
- 缺失 `llm_stats.json` 时优雅降级显示"未记录"（旧 run 报告不受影响）；
- 原「四、结论」顺延为「五、结论」。

## 影响范围

- 实验基础设施：`aaa_serve.py`（协议新增 llm_stats）、`agent_bridge.py`（llm_stats 方法 + inline 计数）、`run_pool_experiment.py`（计数 + 落盘）、`topic_report.py`（报告节）；
- AAA 节点代码零改动；平台基础设施（消息池/路由/仲裁/采集）零改动；
- 旧 run 无 `llm_stats.json` → 报告降级显示，不报错。

## 验证方法

1. `infra_acceptance_test.py`：U7 新增 2 项（llm_stats 合法计数 + 50 条请求后每子进程 ≥1 次调用）、U6 新增 2 项（报告含 API 统计节 + 各 Agent 明细表）→ **68/68** 全过。
2. 冒烟（`--fake-llm --agents 3 --rounds 3`）：`total=35`（AAA 子进程 32 + 平台直连 3），报告渲染正确。
3. 5 Agent 40 轮真实实验：llm_stats.json 落盘 + 报告「四、API 调用量统计」节展示总量与各 Agent 明细。
