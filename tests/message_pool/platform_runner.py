# -*- coding: utf-8 -*-
"""消息池实验平台：消息池 + 路由 + 仲裁 + 采集 + Agent 编排（F1/F6/F8）。

注意：本文件名刻意避开 `platform`（与 Python 标准库同名会导致
numpy 等库 import platform 时被本文件遮蔽，引发 ImportError）。

典型用法（实验脚本）：
    agents = [AgentBridge("agent:alpha", "agent:alpha", dbp_a, llm_fn), ...]
    platform = MessagePoolPlatform(agents, run_dir="runs/...", gid="exp")
    platform.inject([{"content": "大家好", "user_id": "userA"}, ...])
    speech = platform.step()          # 本步发言 (agent_id, content) 或 None
    platform.drain_queue()            # 依次广播排队发言
    platform.write_evolution()        # 采集终态 evolution.json

发言收敛规则（step 内）：
    - 同一批消息按路由顺序派发，各 Agent 独立决策。
    - 第一个 reply 获得发言权并广播；其余 reply 按平台策略排队/丢弃。
    - 每步至多广播一条发言（仲裁器保证「同一时刻至多一个 Agent 发言」）。
"""
import sqlite3

from .event_bus import EventBus
from .message_pool import MessagePool
from .router import pick_speaker, find_mentions
from .arbiter import SpeechOutputArbiter, ArbiterPolicy
from .collector import ExperimentCollector


class MessagePoolPlatform:
    """多用户消息池实验平台。"""

    # @ 点名 → 被点名 Agent 的发言优先级（供 INTERRUPT 打断策略使用）
    MENTION_PRIORITY = 20

    def __init__(self, agents, run_dir=None, gid="exp", max_batch=10,
                 per_user_quota=3, arbiter_policy=ArbiterPolicy.QUEUE,
                 bus=None, pool=None, arbiter=None, topic_rounds=10):
        self.agents = {a.agent_id: a for a in agents}
        self.agent_ids = [a.agent_id for a in agents]
        self.max_batch = max_batch
        self.arbiter_policy = arbiter_policy
        self._round_no = 0
        # 避让机制：上一条「agent 广播发言」若是本 Agent，则本轮跳过决策
        # （不接自己的话，防自言自语），让其他 Agent 有机会接话。
        # 用户消息/话题等外部输入不重置 last_speaker（仍避让一轮，优先让
        # 其他 Agent 回应）；当一批因避让而无任何广播时解除避让，防对话停滞。
        self._last_speaker = None
        self._yield_pending = False
        # 话题会话状态：agent 广播发言回投消息池构成 agent 间多轮对话，
        # 达到 topic_rounds（0=不限）后平台主动宣告话题结束。
        # 轮数只统计「成功入池的 agent 发言」；agent 后台思考/总结不经消息池，不计。
        self.topic_rounds = topic_rounds
        self.topic_active = True
        self.topic_ended = False
        self.agent_speech_count = 0

        self.bus = bus or EventBus()
        self.collector = None
        if run_dir:
            self.collector = ExperimentCollector(run_dir, gid=gid)
            for evt in ("message_enqueued", "message_duplicate_dropped",
                        "batch_dispatched", "speech_requested",
                        "speech_output_started", "speech_queued",
                        "speech_dropped", "speech_cancelled", "speech_finished",
                        "topic_ended"):
                self.bus.subscribe(evt, self._on_event)
            for a in agents:
                a.collector = self.collector

        self.pool = pool or MessagePool(self.bus, per_user_quota=per_user_quota)
        self.arbiter = arbiter or SpeechOutputArbiter(
            self.bus, default_policy=arbiter_policy)

    # ── 事件 → 采集器 ──────────────────────────────────────
    def _on_event(self, event_type, **payload):
        self.collector.event(event=event_type, **payload)

    def _chat(self, **fields):
        """记录一条聊天历史（collector 未启用时跳过）。"""
        if self.collector:
            self.collector.chat(**fields)

    # ── 初始化阶段（自我介绍 / 话题发放） ─────────────────────
    def record_speech(self, agent_id, content, stage="", round_no=None):
        """记录一条 Agent 发言到聊天历史（不入消息池，用于自我介绍等）。"""
        self._chat(role="agent", agent_id=agent_id, content=content,
                   stage=stage, round_no=round_no)

    def announce(self, content, role="topic", user_id="platform",
                 source="topic", priority=5, enqueue=True):
        """平台广播消息（话题/公告）。

        默认注入消息池（让 Agent 在下一轮 step() 中感知并围绕展开）
        并记录聊天历史（role=topic）；`enqueue=False` 时只记录不注入。
        """
        if enqueue:
            msg = self.pool.enqueue_input(text=content, source=source,
                                          user_id=user_id, priority=priority)
            if not msg:  # 被去重丢弃（窗口内重复话题）→ 不记录
                return None
        self._chat(role=role, user_id=user_id, content=content, source=source)
        return True

    # ── Agent 发言回投与话题轮数（多轮对话） ──────────────────
    def _batch_for(self, aid, batch):
        """v6.3 P1-3：为单个 Agent 定制批次顺序——把 @ 该 Agent 的消息移到
        批次末尾。AAA 合并上下文把末位作者作为"最后发言者"，LLM 存在末位偏置
        （几乎总回应批次最后一条消息），导致发言排在批次前端的 Agent（如
        agent:0/1）永远不被回应 → 认知黑洞。把 @ 消息置末位，让末位偏置
        反过来为"@ 优先"服务；无 @ 时保持原序（最后发言者仍是自然的回应焦点）。
        """
        mentioned = []
        rest = []
        for m in batch:
            text = m.text if hasattr(m, "text") else m.get("text", m.get("content", ""))
            if aid in find_mentions(text, [aid]):
                mentioned.append(m)
            else:
                rest.append(m)
        return rest + mentioned if mentioned else batch

    def _feed_agent_speech(self, agent_id, content):
        """把 Agent 广播发言回投消息池（构成 agent 间多轮对话）并按轮计数。

        轮数只统计「成功入池的 agent 消息」；被去重丢弃、静默、以及
        agent 后台的思考/总结（不经消息池）都不计入。
        """
        if not self.topic_active:
            return
        # dedup=False：agent 每次发言都是对话的实际一轮，不被同人同文去重误伤
        msg = self.pool.enqueue_input(text=content, source="agent",
                                      user_id=agent_id, priority=0,
                                      dedup=False)
        if msg:
            self.agent_speech_count += 1
            if self.topic_rounds and self.agent_speech_count >= self.topic_rounds:
                self._end_topic()

    def _end_topic(self):
        """平台主动宣告当前话题结束（轮数可配置：topic_rounds）。"""
        if self.topic_ended:
            return
        self.topic_active = False
        self.topic_ended = True
        text = (f"【平台】当前话题已结束（共 {self.agent_speech_count} 轮 agent 发言）。"
                "本次讨论到此为止，谢谢大家参与！")
        msg = self.pool.enqueue_input(text=text, source="topic_end",
                                      user_id="platform", priority=10)
        if msg:
            self._chat(role="system", user_id="platform", content=text,
                       source="topic_end")
        self.bus.publish("topic_ended", agent_speech_count=self.agent_speech_count)

    # ── 对外接口 ───────────────────────────────────────────
    def inject(self, messages):
        """注入聊天室消息：list[dict]（content/user_id/priority/source）或 Message。

        入池成功的消息写入聊天历史（role=user）。
        """
        for m in messages:
            if hasattr(m, "text"):
                msg = self.pool.enqueue_input(text=m.text, source=m.source,
                                              user_id=m.user_id, priority=m.priority)
                if msg:
                    self._chat(role="user", user_id=m.user_id, content=m.text,
                               source=m.source)
            else:
                msg = self.pool.enqueue_input(
                    text=m.get("content", ""),
                    source=m.get("source", "sim"),
                    user_id=m.get("user_id", ""),
                    priority=m.get("priority", 0))
                if msg:
                    self._chat(role="user", user_id=m.get("user_id", ""),
                               content=m.get("content", ""), source=m.get("source", "sim"))

    def step(self):
        """消费一批消息并让相关 Agent 决策。

        F9 并行派发：同一批消息并行投给全部目标 Agent（各 Agent 独立
        子进程/实例），决策完成后按 @ 优先级排序仲裁——被点名 Agent
        即使决策完成较晚，其发言仍优先生效。

        Returns:
            (agent_id, content) 本步广播的发言；无消息或无人发言则 None。
        """
        batch = self.pool.pop_all_inputs(self.max_batch)
        if not batch:
            return None
        self._round_no += 1
        target_agents, mentioned = pick_speaker(batch, self.agent_ids)
        # 避让：上一条 agent 广播发言者本轮跳过（除非被 @ 点名），
        # 防止单 Agent 连续接自己的话形成自言自语
        if (self._yield_pending and self._last_speaker
                and self._last_speaker in target_agents
                and self._last_speaker not in mentioned):
            target_agents = [a for a in target_agents
                             if a != self._last_speaker]

        # ── F9 并行决策：并发调用全部目标 Agent，收集决策 ──
        decisions: dict[str, dict] = {}
        if len(target_agents) == 1:
            aid = target_agents[0]
            try:
                decisions[aid] = self.agents[aid].process_batch(
                    self._batch_for(aid, batch), round_no=self._round_no)
            except Exception as e:
                # v6.3 P0-1：单 Agent 路径调用失败 → error（不落 silent）
                decisions[aid] = {"action": "error", "content": "",
                                  "user_id": "", "想法": "", "心情": "",
                                  "error": f"{type(e).__name__}: {e}"}
        else:
            import threading
            results: dict[str, dict] = {}
            errors: list[str] = []

            def _run(aid):
                try:
                    results[aid] = self.agents[aid].process_batch(
                        self._batch_for(aid, batch), round_no=self._round_no)
                except Exception as e:
                    errors.append(f"{aid}: {type(e).__name__}: {e}")
                    # v6.3 P0-1：调用失败独立标记 error，不落 silent
                    # （否则 402 等错误被当成"主动沉默"，静默率被污染）
                    results[aid] = {"action": "error", "content": "",
                                    "user_id": "", "想法": "", "心情": "",
                                    "error": f"{type(e).__name__}: {e}"}

            threads = [threading.Thread(target=_run, args=(a,), daemon=True)
                       for a in target_agents]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            decisions = results

        # ── F9 优先级仲裁：@ 点名 > 普通（决策完成后排序，非先到先得） ──
        order = sorted(target_agents,
                       key=lambda a: (0 if a in mentioned else 1,
                                      target_agents.index(a)))
        speech = None
        for aid in order:
            decision = decisions.get(aid) or {}
            priority = self.MENTION_PRIORITY if aid in mentioned else 0
            if (decision.get("action") == "reply"
                    and decision.get("content")):
                ok = self.arbiter.request_speech(
                    aid, decision["content"], priority=priority,
                    policy=self.arbiter_policy)
                if ok and speech is None:
                    speech = (aid, decision["content"])
        # 本轮发言权在步末释放（QUEUE 下排队者经 _serve_next 获得发言权，
        # 由 drain_queue() 逐步广播；保证每步至多广播一条发言）。
        self.arbiter.release()
        if speech:
            self._chat(role="agent", agent_id=speech[0], content=speech[1],
                       round_no=self._round_no)
            # 广播发言回投消息池 → 其他 Agent 下一轮感知，构成多轮对话
            self._feed_agent_speech(speech[0], speech[1])
            # 下一批避让本发言者（若被点名则已在前面豁免）
            self._last_speaker = speech[0]
            self._yield_pending = True
        else:
            # 本批无人发言（其他 Agent 沉默）→ 解除避让，避免对话停滞
            self._yield_pending = False
        return speech

    def drain_queue(self):
        """释放当前发言并广播排队补位者（每调用一次广播一条）。

        Returns:
            (agent_id, content) 或 None（无排队）。
        """
        released = self.arbiter.release()
        if released:
            self._chat(role="agent", agent_id=released["agent_id"],
                       content=released["content"], round_no=self._round_no)
            self._feed_agent_speech(released["agent_id"], released["content"])
            # 排队补位者是聊天历史最新的 agent 发言 → 下批避让它
            self._last_speaker = released["agent_id"]
            self._yield_pending = True
            return (released["agent_id"], released["content"])
        return None

    def write_evolution(self, extra=None):
        """采集实验终态：性格向量 / 心情 / 他人认知条目数（按 user_id 分组）。"""
        agents_meta = {}
        for aid, agent in self.agents.items():
            meta = {"end": agent._snapshot(), "other_cognition": {}}
            try:
                conn = sqlite3.connect(agent.db_path)
                rows = conn.execute(
                    "SELECT user_id, COUNT(*) FROM other_cognition "
                    "WHERE conversation_id=? AND identity_key=? GROUP BY user_id",
                    (agent.conv_id, agent.identity_key)).fetchall()
                meta["other_cognition"] = {r[0]: r[1] for r in rows}
                conn.close()
            except Exception:
                pass
            agents_meta[aid] = meta
        if self.collector:
            self.collector.set_rounds(self._round_no)
            self.collector.write_evolution(agents_meta, extra=extra)
        return agents_meta
