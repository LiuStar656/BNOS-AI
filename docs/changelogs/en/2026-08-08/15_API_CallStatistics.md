# 15 API Call Statistics: Experiment Report Records Total and Per-Agent Call Counts

## Problem Description

Before the 5-Agent, 40-round real experiment, the user required: **after the experiment, the report must record the total API call count and each Agent's API call count**. Previously none of the experiment artifacts (decisions.jsonl / evolution.json / topic_report.md) carried LLM/API call metrics, so the experiment cost and call distribution could not be audited.

## Root Cause Analysis

Under the F9 subprocess architecture, LLM calls happen inside the AAA subprocess (the `llm_fn` in `aaa_serve.py`; both decisions and background reviews pass through it), and the platform (parent process) cannot see subprocess call counts — the stdin/stdout protocol only had ping / pool_batch / flush_review / shutdown. Platform-side direct calls (self-intro) were also uncounted.

## Solution

### 1. `aaa_serve.py`: LLM call counting + `llm_stats` protocol request

`_make_llm()` now returns a counting wrapper (both decision and review calls go through `llm_fn`, so counting is complete):

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

New protocol request `{"type": "llm_stats"}` → response `{"code": 0, "data": {"calls": N}}`.

### 2. `agent_bridge.py`: `llm_stats()` method

- subprocess mode: sends `llm_stats` and reads the subprocess count;
- inline mode: `__init__` wraps `llm_fn` with a counter (`self._inline_llm_calls`) and returns the decision-path count (control mode; background review-thread calls are not counted, documented in the docstring).

### 3. `run_pool_experiment.py`: platform-side counting + teardown persistence

- Platform-side direct LLM calls wrapped with a counter (`_platform_llm_calls`, e.g. self-intro);
- At teardown (after flush_review, before close), collects each Agent's `llm_stats()` and writes `run_dir/llm_stats.json`:

```json
{"mode": "subprocess", "fake_llm": false,
 "platform_direct": 5, "total": 356,
 "per_agent": {"agent:0": 71, "agent:1": 70, ...}}
```

- Prints summary `[API 调用量] total=N (AAA 子进程 X + 平台直连 Y)`.

### 4. `topic_report.py`: report renders the "四、API 调用量统计" section

- `_load_llm_stats` / `_render_llm_stats`: total (with fake-LLM annotation) + subprocess/direct split + per-Agent detail table (calls + share);
- Graceful degradation when `llm_stats.json` is missing (old runs unaffected);
- Original "四、结论" becomes "五、结论".

## Impact Scope

- Experiment infrastructure: `aaa_serve.py` (new llm_stats request), `agent_bridge.py` (llm_stats method + inline counting), `run_pool_experiment.py` (counting + persistence), `topic_report.py` (report section);
- Zero AAA node code changes; zero platform infrastructure changes (pool/router/arbiter/collector);
- Old runs without `llm_stats.json` degrade gracefully in the report.

## Verification

1. `infra_acceptance_test.py`: U7 gains 2 checks (valid llm_stats counts + every subprocess ≥1 call after 50 requests), U6 gains 2 checks (report has the API stats section + per-Agent detail table) → **68/68**.
2. Smoke (`--fake-llm --agents 3 --rounds 3`): `total=35` (subprocess 32 + direct 3), report renders correctly.
3. 5-Agent 40-round real experiment: llm_stats.json persisted + report "四、API 调用量统计" section shows total and per-Agent detail.
