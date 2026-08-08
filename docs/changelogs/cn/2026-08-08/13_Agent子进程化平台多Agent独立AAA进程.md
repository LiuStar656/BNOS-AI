# 13 Agent 子进程化：平台维护多个独立 AAA 子进程（F9）

## 问题描述

消息池实验平台原本是「单进程多 AAA 实例」架构：主进程 `import main` 后创建 N 个 `MyNode()` 实例，共享同一进程内的 memos 语义索引。用户希望**让 Agent 成为平台的子进程**——每个 Agent 由独立的 AAA 认知进程处理，平台（父进程）只负责编排。

单进程架构的 3 处硬伤：

1. **memos 共享竞态**：多实例共用同一 memos 全局索引，后台重建线程并发写同一 numpy 状态，存在 native 崩溃风险（此前演化长跑已验证）。
2. **崩溃连坐**：任一实例的 LLM 调用异常 / 后台线程崩溃会拖垮整个实验进程。
3. **无法真正并行**：单进程内 GIL 约束下多 Agent 决策只能串行（线程并行仅对 I/O 有意义）。

## 根因分析

- 消息池实验需要「平台编排 + 多 Agent 各自独立认知」两个正交维度，原实现把二者揉在一个进程里。
- `MyNode` 的 `__init__` 在模块级即实例化并调用 `memos.preload()`，单进程内多个实例天然共享索引，无法隔离。
- LLM 调用为 HTTP 直连（`urllib`），天然支持并发，瓶颈只在 AAA 认知状态与索引的进程内共享。

## 修改方案

### 架构决策

采用 **stdin/stdout 每行一个 JSON** 的进程间协议（与 BNOS 节点文件协议同源的进程隔离思想，但面向高频实验通信）：

```
平台（父进程）                      AAA 子进程 × N（每 Agent 一个）
─────────────────────             ─────────────────────────────
MessagePoolPlatform          ┌──► aaa_serve.py 常驻循环
  step() 并行决策 ──────────┼──► aaa_serve.py
  @ 优先级仲裁               └──► aaa_serve.py
  AgentBridge._send(ping/pool_batch/flush_review/shutdown)
```

- 每个 AAA 子进程独立加载 memos 语义模型与索引（~80MB，Agent ≤ 5 内存预算内）。
- 后台 review 线程在子进程内自行调 LLM，与真实架构一致；进程退出前 `flush_review` 等待落库。
- 崩溃自动重启：`_send` 捕获 EOF/解析失败 → kill 旧进程 → 重新拉起 → 重试一次。

### 1. 新增 `tests/message_pool/aaa_serve.py`（AAA 常驻子进程服务）

- 协议：`ping` / `pool_batch` / `flush_review` / `shutdown`，响应 `{"code": 0|-1, "type", "data"/"error"}`，stdout 只输出协议 JSON，日志走 stderr。
- LLM 由环境变量注入（`AAA_LLM_MODE=real|fake`、`AAA_API_URL/KEY/MODEL`），不写死节点代码。
- `AAA_SKIP_HEAVY=1`（验收/fake 模式）：在 `import main` **之前** patch `memos.preload` / `rebuild_index` / `rebuild_knowledge_index` / `db._aggregate_mood`——main 模块级会实例化 `MyNode()`，其 `__init__` 内调用 `memos.preload()`。
- `_handle_pool_batch` 与 AgentBridge inline 逻辑逐行一致（`_on_pool_batch` → LLM → `_on_parsed(batch_mode=True)` 直到收敛 action），保证两种模式行为等价。
- 备注：方案文档落点为「main.py 加 --serve 循环」，实际实施改为**独立 aaa_serve.py 服务**——保持 AAA 节点黑盒不侵入，实验基础设施与节点代码解耦。

### 2. `tests/message_pool/agent_bridge.py` — subprocess 桥接

- `__init__` 新增 `mode="inline"|"subprocess"`、`aaa_env`、`serve_script`、`log_dir`。
- `_ensure_proc`：`subprocess.Popen([sys.executable, aaa_serve.py, --identity, --db], ...)`，stderr 重定向到日志文件（`log_dir` 提供时）。
- `_send`：写一行 JSON + 阻塞读一行；EOF/解析失败 → kill 重启重试一次，仍失败抛 `ConnectionError`。
- `ping` / `flush_review` / `close`（shutdown → wait 回收，防孤儿进程）。
- inline 模式原有逻辑完整保留（对照/回归）。

### 3. `tests/message_pool/platform_runner.py` — 并行决策 + 优先级仲裁

- `step()`：多目标 Agent 时开线程并行 `process_batch`，收集全部决策。
- 仲裁改为**决策完成后按 @ 优先级排序**（点名者优先），不再先到先得——被点名 Agent 即使决策完成较晚，发言仍优先生效。
- 单目标 Agent 保持串行（无并发开销）。

### 4. `tests/message_pool/run_pool_experiment.py` — 参数透传与回收

- 新增 `--inline`（单进程对照模式，F9 前架构保留作回归）；默认每 Agent 独立 AAA 子进程。
- LLM 配置经 `aaa_env` 环境变量注入子进程；`--fake-llm` 时附带 `AAA_SKIP_HEAVY=1`（冒烟不耗资源）。
- 收尾：`flush_review` 等待落库 → `close` 关闭全部子进程并打印回收。

## 影响范围

- 新增：`tests/message_pool/aaa_serve.py`。
- 修改：`tests/message_pool/agent_bridge.py`（subprocess 桥接，inline 保留）、`platform_runner.py`（并行决策 + 优先级仲裁）、`run_pool_experiment.py`（--inline + aaa_env + 回收）、`infra_acceptance_test.py`（U7 专项验收）。
- 不涉及 AAA 节点代码（`nodes/node_python_aaa_cognition/`）与平台基础设施（消息池/路由/仲裁/采集）——进程协议在桥接层实现。
- 内存预算：每子进程 ~80MB（模型 + 索引），Agent ≤ 5。

## 验证方法

1. U7 专项验收（`infra_acceptance_test.py` 追加）：
   - 进程隔离：3 个独立 AAA 子进程 PID 各不相同；
   - 常驻通信：预热后 ping 往返 < 1s；50 条 `pool_batch` 请求全部返回合法决策；
   - @ 点名优先：并行决策下被点名 `agent:s2` 获得发言权；
   - 崩溃恢复：kill 子进程后自动重启并返回决策；
   - 资源回收：close 后全部子进程退出，无孤儿进程。
2. 回归：U1–U6 + I1–I4（57 项）全部通过，`infra_acceptance_test.py` **64/64**。
3. 冒烟全链路：`run_pool_experiment.py --fake-llm --agents 3 --rounds 3 --gid smoke` → 3 个子进程模式 Agent 完成自我介绍 → 话题发放 → 10 轮 agent 发言（达上限平台宣告话题结束）→ 每 Agent 14 张表导出 + 聊天历史 + 话题报告 → `[回收] 已关闭 3 个 AAA 子进程`。
