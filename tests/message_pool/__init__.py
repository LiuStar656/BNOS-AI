# -*- coding: utf-8 -*-
"""消息池实验平台包（多用户交互实验基础设施）。

对齐 Lumi_Nox（EventBus / SpeakerScheduler / SpeechOutputArbiter）与
[PLAN] 消息池与聊天室式消息处理方案 v1.0 的 F1/F4/F6/F8。

模块划分：
    event_bus.py      事件发布/订阅（仲裁/消息池/采集器解耦）
    message_pool.py   聊天室消息池（入队不打断 / 批量取出 / 去重 / 洪流配额）
    router.py         @ 点名路由（谁被点名谁先回）
    arbiter.py        发言仲裁器（同一时刻单一发言权；QUEUE/DROP/INTERRUPT）
    collector.py      实验数据采集（events.jsonl / decisions.jsonl / evolution.json）
    agent_bridge.py   Agent 桥接（调 AAA _on_pool_batch + _on_parsed(batch_mode=True)）
    platform_runner.py 平台主入口（消息池 + 路由 + 仲裁 + 采集 + Agent 编排）
                   （文件名避让 stdlib `platform`，防 numpy 等 import 遮蔽）
    topic_report.py  话题报告生成器（相互认知记忆 + 人格漂移 + 采集指标，对齐实验设计方案）

本包是实验基础设施，不包含具体实验场景（实验脚本单独编写）。
"""
