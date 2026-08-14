# 03 Workflow 流程接入 DSH 执行器

## 问题描述

workflow_store 已有流程 schema + 双引擎分数（多巴胺/用进废退），但流程步骤此前
没有真实执行能力，无法把任务交给外部执行器。

## 根因分析

- DSH（DeepSeek Harness）已作为执行器官接入 GUI（dsh.run_task 工具），
  流程步骤应复用该执行链路而非自建执行逻辑
- 需要支持"流程步骤提交 DSH 任务并等待最终回答"的同步语义

## 修改方案

- `gui/core/tool_registry.py` 新增 `dsh.run_task`（异步提交）/ `dsh.run_task_sync`
  （同步等待最终回答，流程步骤用）/ `dsh.check_task`（补查结果）
- `dsh.run_task_sync` 支持 `session_id` 续接同一会话多轮对话、`timeout` 上限
  （默认 600s 与 node_dsh 超时一致）；超时后任务继续后台执行，可 check_task 补查
- AAA 侧 `gui_tools.py::workflows_text()` 注入流程清单（含实时双引擎分数），
  main.py 解析【流程选择】节接入 `ui.run_workflow`

## 影响范围

- 流程执行从空转变为真实执行，DSH 任务结果回流
- 用户通过 AAA 对话即可让流程选择并执行 DSH 任务

## 验证方法

- tool_registry.execute("dsh.run_task") 提交 + check_task 查询冒烟
- 流程选择链路：LLM 输出【流程选择】→ main.py 流程分支 → ui.run_workflow
