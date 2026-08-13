# -*- coding: utf-8 -*-
"""实验数据采集器（F8）。

输出（runs/ 目录约定，与认知演化实验一致）：
    events.jsonl     平台消息池事件（入池、去重、派发、仲裁、广播）
    decisions.jsonl  Agent 每批响应决策（reply/silent、user_id、想法、性格向量、心情）
    evolution.json   实验起止性格向量、情感、他人认知条目数（按 user_id 分组）
"""
import json
import os
from datetime import datetime


class ExperimentCollector:
    """JSON Lines 实验数据采集器。"""

    def __init__(self, run_dir, gid="exp"):
        self.run_dir = run_dir
        self.gid = gid
        os.makedirs(run_dir, exist_ok=True)
        self._events = open(os.path.join(run_dir, "events.jsonl"),
                            "a", encoding="utf-8")
        self._decisions = open(os.path.join(run_dir, "decisions.jsonl"),
                               "a", encoding="utf-8")
        self._chat = open(os.path.join(run_dir, "chat_history.jsonl"),
                          "a", encoding="utf-8")
        self._evolution_path = os.path.join(run_dir, "evolution.json")
        self._rounds = 0
        self._reply_count: dict[str, int] = {}
        self._silent_count: dict[str, int] = {}
        # v6.3 P0-1：调用失败独立计数（error），与"主动沉默"区分
        self._error_count: dict[str, int] = {}
        # v6.5 幽灵发言口径：平台话题结束后置 True，之后的决策记录
        # 附带 topic_ended=True（残余批次决策未入池，与话题中决策区分）
        self.topic_ended = False

    # ── 事件日志（订阅 EventBus 写入） ─────────────────────
    def event(self, **payload):
        """写一条平台事件（自动带时间戳）。"""
        self._events.write(json.dumps(
            {"ts": datetime.now().isoformat(), **payload},
            ensure_ascii=False) + "\n")
        self._events.flush()

    # ── 决策日志（Agent 每批响应） ─────────────────────────
    def decision(self, **payload):
        """写一条 Agent 决策并累计 reply/silent 计数。

        v6.5 幽灵发言口径：平台话题结束后产生的残余批次决策
        （未入池）附加 topic_ended=True 标记。
        """
        if self.topic_ended:
            payload["topic_ended"] = True
        self._decisions.write(json.dumps(
            {"ts": datetime.now().isoformat(), **payload},
            ensure_ascii=False) + "\n")
        self._decisions.flush()
        action = payload.get("action")
        agent = payload.get("agent", "?")
        if action == "reply":
            self._reply_count[agent] = self._reply_count.get(agent, 0) + 1
        elif action == "silent":
            self._silent_count[agent] = self._silent_count.get(agent, 0) + 1
        elif action == "error":
            # v6.3 P0-1：失败独立计数，不进 silent（静默率是"主动沉默"的指标）
            self._error_count[agent] = self._error_count.get(agent, 0) + 1

    # ── 聊天历史（平台消息池：用户发言 + Agent 广播，按时间顺序） ──
    def chat(self, **payload):
        """写一条聊天历史（role=user|agent，含 user_id/agent_id/content）。"""
        self._chat.write(json.dumps(
            {"ts": datetime.now().isoformat(), **payload},
            ensure_ascii=False) + "\n")
        self._chat.flush()

    # ── 演化汇总 ───────────────────────────────────────────
    def write_evolution(self, agents_meta, extra=None):
        """写 evolution.json。

        Args:
            agents_meta: {agent_id: {"start": {...}, "end": {...},
                                     "other_cognition": {user_id: 条目数}}}
            extra: 附加统计字段
        """
        data = {
            "gid": self.gid,
            "created_at": datetime.now().isoformat(),
            "rounds": self._rounds,
            "reply_count": self._reply_count,
            "silent_count": self._silent_count,
            # v6.3 P0-1：失败独立计数（静默率统计必须排除 error 记录）
            "error_count": self._error_count,
            "agents": agents_meta,
        }
        if extra:
            data.update(extra)
        with open(self._evolution_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def set_rounds(self, n: int):
        """记录已处理批次数（供 evolution.json 汇总）。"""
        self._rounds = n

    def close(self):
        self._events.close()
        self._decisions.close()
        self._chat.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
