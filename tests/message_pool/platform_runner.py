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
import json
import os
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
                 bus=None, pool=None, arbiter=None, topic_rounds=10,
                 gate=None):
        self.agents = {a.agent_id: a for a in agents}
        self.agent_ids = [a.agent_id for a in agents]
        self.max_batch = max_batch
        self.arbiter_policy = arbiter_policy
        self._round_no = 0
        # v7.0 兴趣门控（InterestGate 实例，None=关闭，行为退回 v6.6 全过门）
        self.gate = gate
        # v6.5 冷板凳计数：每个 agent 被其他人回应的次数（reply_to 命中 +1）。
        # _batch_for 据此把"被回应最少"的 agent 发言移到批次末位，让末位偏置
        # 服务"被忽视者"，打破 agent:0 式首位发言者认知黑洞。
        self._responded = {a: 0 for a in self.agent_ids}
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
        # v7.2 接话窗口：消息池历史（所有入池消息按序）+ 每个 agent 最近
        # 发言的 seq——过门 agent 的决策上下文 = (自己最近发言, 切入消息] 区间
        self._msg_history: list[dict] = []
        self._last_speech_seq: dict[str, int] = {}
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
        # v7.0 兴趣门控：自我介绍作为初始兴趣锚点
        if self.gate is not None:
            self.gate.set_anchor(agent_id, content)

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
            self._track_history(msg, user_id, content, "")
        self._chat(role=role, user_id=user_id, content=content, source=source)
        return True

    def _track_history(self, msg, user_id, content, reply_to=""):
        """v7.2：把入池消息追加到消息池历史（接话窗口的数据源）。"""
        self._msg_history.append({
            "seq": int(getattr(msg, "seq", 0) or 0),
            "user_id": user_id or "",
            "content": content or "",
            "reply_to": reply_to or "",
        })

    def _window_for(self, aid, target_seq):
        """v7.2 接话窗口：`(该 agent 最近一次发言, 切入消息]` 的所有消息。

        不含该 agent 自己的发言；agent 未发言过 → 下界 = 消息池起点；
        无截断（用户确认）。窗口按历史顺序（时间正序）返回。
        """
        lower = self._last_speech_seq.get(aid, 0)
        return [m for m in self._msg_history
                if lower < m["seq"] <= int(target_seq)
                and m.get("user_id", "") != aid]

    # ── Agent 发言回投与话题轮数（多轮对话） ──────────────────
    def _batch_for(self, aid, batch):
        """为单个 Agent 定制批次顺序。

        v6.3 P1-3：把 @ 该 Agent 的消息移到批次末尾（末位偏置为"@ 优先"
        服务）；v6.5 冷板凳轮转：无 @ 时把"被回应次数最少"的 Agent 发言
        移到末位，让末位偏置服务被忽视者——打破首位发言者（如 agent:0）
        发言最多却长期无人回应的认知黑洞（5a40r / 5a30r 均复现）。
        """
        mentioned = []
        rest = []
        for m in batch:
            text = m.text if hasattr(m, "text") else m.get("text", m.get("content", ""))
            if aid in find_mentions(text, [aid]):
                mentioned.append(m)
            else:
                rest.append(m)
        if mentioned:
            return rest + mentioned
        if len(batch) >= 2:
            def _author(m):
                return (m.user_id if hasattr(m, "user_id") else m.get("user_id", "")).strip()
            # 仅对 agent 发言做冷板凳（platform/用户消息不动）
            cands = [m for m in batch if _author(m) in self._responded]
            if len(cands) >= 2:
                cold = min(cands, key=lambda m: self._responded[_author(m)])
                if cold is not batch[-1]:
                    return [m for m in batch if m is not cold] + [cold]
        return batch

    def _feed_agent_speech(self, agent_id, content, reply_to=""):
        """把 Agent 广播发言回投消息池（构成 agent 间多轮对话）并按轮计数。

        轮数只统计「成功入池的 agent 消息」；被去重丢弃、静默、以及
        agent 后台的思考/总结（不经消息池）都不计入。

        reply_to: v6.4 引用链——本条发言回应谁（决策的【回应对象】），
                  随消息入池，下一轮批次合并时标注给 LLM 决策上下文。
        """
        if not self.topic_active:
            return
        # v6.5 冷板凳计数：被回应对象是某 agent → 该 agent 被回应次数 +1
        # （供 _batch_for 末位轮转选择"被忽视者"）
        if reply_to in self._responded:
            self._responded[reply_to] += 1
        # dedup=False：agent 每次发言都是对话的实际一轮，不被同人同文去重误伤
        msg = self.pool.enqueue_input(text=content, source="agent",
                                      user_id=agent_id, priority=0,
                                      dedup=False, reply_to=reply_to)
        if msg:
            self.agent_speech_count += 1
            # v7.2 接话窗口：记录本 agent 最近一次发言的 seq（窗口下界）
            self._last_speech_seq[agent_id] = int(getattr(msg, "seq", 0) or 0)
            self._track_history(msg, agent_id, content, reply_to)
            # v7.0 兴趣门控：广播发言更新兴趣锚点（兴趣随参与漂移）
            if self.gate is not None:
                self.gate.set_anchor(agent_id, content)
            if self.topic_rounds and self.agent_speech_count >= self.topic_rounds:
                self._end_topic()

    def _end_topic(self):
        """平台主动宣告当前话题结束（轮数可配置：topic_rounds）。"""
        if self.topic_ended:
            return
        self.topic_active = False
        self.topic_ended = True
        # v6.5 口径标注：话题结束后的残余批次决策（幽灵发言）在 decisions.jsonl
        # 中以 topic_ended=True 标记，避免与话题进行中的决策混淆
        if self.collector:
            self.collector.topic_ended = True
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
                    self._track_history(msg, m.user_id, m.text, "")
                    self._chat(role="user", user_id=m.user_id, content=m.text,
                               source=m.source)
            else:
                msg = self.pool.enqueue_input(
                    text=m.get("content", ""),
                    source=m.get("source", "sim"),
                    user_id=m.get("user_id", ""),
                    priority=m.get("priority", 0))
                if msg:
                    self._track_history(msg, m.get("user_id", ""),
                                        m.get("content", ""), "")
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
        # v6.6 P1-3 熔断：话题已结束后残余批次不再产生新决策/发言。
        # 消息被消费（防止主循环空转）但不派发——从源头消除
        # "topic_ended 后幽灵发言"（5a30r_v2 中 decisions 35 条 reply
        # vs events 入池 30 条的口径分歧，根源就是结束后的残余批次）。
        if not self.topic_active:
            return None
        self._round_no += 1
        target_agents, mentioned = pick_speaker(batch, self.agent_ids)
        # v7.0/v7.2 兴趣门控：平台显式判定"谁对当前对话感兴趣"（编码一次、比对
        # 多次，共享多语模型）。v7.2 起按时间从旧到新逐条发言判定（judge_sequence），
        # 每条判定（检测文本 + 兴趣值）写入 interest_judgment 表；
        # 第一个过门的发言 = 接话切入点（决定从谁说完话后开始接话）。
        # @ 点名 / reply_to 直接过门（reason=direct）；无任何过门时兴趣最高者
        # 兜底过门（interest_floor），防对话停滞。
        gate_judgments: dict[str, dict] = {}
        gate_windows: dict[str, list] = {}
        if self.gate is not None:
            for aid in target_agents:
                direct = [m for m in batch
                          if (getattr(m, "reply_to", "") or "").strip() == aid
                          or aid in find_mentions(
                              m.text if hasattr(m, "text")
                              else m.get("content", ""), [aid])]
                res = self.gate.judge_sequence(aid, batch, direct_hits=direct)
                # 全部候选判定落库（每个候选发言者各一条：检测文本 + 兴趣值）
                for rec in res["records"]:
                    self.gate.write_judgment(self.agents[aid].db_path, aid,
                                             self._round_no, rec)
                gate_judgments[aid] = res
            if not any(res["target"] is not None
                       for res in gate_judgments.values()):
                best_aid = max(target_agents, key=lambda a: max(
                    r["interest_value"] for r in gate_judgments[a]["records"]))
                best_rec = max(gate_judgments[best_aid]["records"],
                               key=lambda r: r["interest_value"])
                best_rec["passed"] = True
                best_rec["reason"] = "interest_floor"
                gate_judgments[best_aid]["target"] = best_rec
            target_agents = [a for a in target_agents
                             if gate_judgments[a]["target"] is not None]
            # v7.2 接话窗口：过门 agent 的决策上下文 = (自己最近发言, 切入消息]
            for aid in target_agents:
                gate_windows[aid] = self._window_for(
                    aid, gate_judgments[aid]["target"]["seq"])
        # v6.6 P0-1 批次顺序事实源统一：每个 Agent 的定制顺序只计算一次，
        # 同时用于派发决策与记录——decisions.batch_context（Agent 实际所见
        # 顺序）与 events.batch_dispatched（原始到达顺序）不再互相矛盾；
        # Message.seq 为两者提供全局唯一关联键（见 message_pool.Message.to_dict）。
        ordered = {a: self._batch_for(a, batch) for a in target_agents}
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
                    ordered[aid], round_no=self._round_no,
                    mention_targets=[aid] if aid in mentioned else [],
                    window=gate_windows.get(aid))
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
                        ordered[aid], round_no=self._round_no,
                        mention_targets=[aid] if aid in mentioned else [],
                        window=gate_windows.get(aid))
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

        # ── F9 优先级仲裁：@ 点名 > 兴趣值高 > 冷板凳（被回应少者优先）> 原顺序
        # （决策完成后排序，非先到先得；gate 关闭时兴趣维度恒 0，退回 v6.6）
        def _arb_order_key(a):
            if self.gate is None:
                iv = 0.0
            else:
                t = gate_judgments.get(a, {}).get("target")
                iv = t.get("interest_value", 0.0) if t else 0.0
            return (0 if a in mentioned else 1, -iv,
                    self._responded.get(a, 0), target_agents.index(a))

        order = sorted(target_agents, key=_arb_order_key)
        speech = None
        for aid in order:
            decision = decisions.get(aid) or {}
            priority = self.MENTION_PRIORITY if aid in mentioned else 0
            if (decision.get("action") == "reply"
                    and decision.get("content")):
                ok = self.arbiter.request_speech(
                    aid, decision["content"], priority=priority,
                    policy=self.arbiter_policy,
                    reply_to=decision.get("回应对象", ""))
                if ok and speech is None:
                    speech = (aid, decision["content"])
        # 本轮发言权在步末释放（QUEUE 下排队者经 _serve_next 获得发言权，
        # 由 drain_queue() 逐步广播；保证每步至多广播一条发言）。
        self.arbiter.release()
        if speech:
            self._chat(role="agent", agent_id=speech[0], content=speech[1],
                       round_no=self._round_no)
            # 广播发言回投消息池 → 其他 Agent 下一轮感知，构成多轮对话；
            # reply_to 带出决策的【回应对象】→ 引用链随消息入池
            self._feed_agent_speech(speech[0], speech[1],
                                    reply_to=(decisions.get(speech[0]) or {})
                                    .get("回应对象", ""))
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
        if not self.topic_active:
            # v6.6 P1-3 熔断：话题结束后不再广播排队发言（残余队列留在
            # 仲裁器，实验收尾即释放）——避免结束公告之后再冒出幽灵发言
            return None
        released = self.arbiter.release()
        if released:
            self._chat(role="agent", agent_id=released["agent_id"],
                       content=released["content"], round_no=self._round_no)
            self._feed_agent_speech(released["agent_id"], released["content"],
                                    reply_to=released.get("reply_to", ""))
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
            # v6.5 口径标注：evolution.rounds=处理批次数（含话题结束后的
            # 幽灵批次），与 agent_speech_count（成功入池发言轮数）是两个
            # 独立口径，一并落盘避免混淆
            self.collector.write_evolution(
                agents_meta,
                extra={"agent_speech_count": self.agent_speech_count,
                       "topic_ended": self.topic_ended,
                       "rounds_metric": "processed_batches",
                       "trajectory": self._trajectory()})
        return agents_meta

    def _trajectory(self) -> dict:
        """人格漂移过程轨迹（数据采集方案 P0-3）：decisions.jsonl → {agent: [{round, vector}]}。

        每个决策都带 personality 快照（agent_bridge._snapshot 读 DB），按轮次
        升序整理——回答"演化是渐进还是突变、从第几轮开始动、与哪类交互相关"。
        """
        if not self.collector:
            return {}
        path = os.path.join(self.collector.run_dir, "decisions.jsonl")
        if not os.path.exists(path):
            return {}
        out: dict[str, list[dict]] = {}
        try:
            with open(path, encoding="utf-8") as f:
                for raw in f:
                    if not raw.strip():
                        continue
                    d = json.loads(raw)
                    aid = d.get("agent")
                    p = d.get("personality")
                    r = d.get("round")
                    if not aid or not p or r is None:
                        continue
                    out.setdefault(aid, []).append(
                        {"round": r, "vector": p})
            for aid in out:
                # 同一轮多个决策（如排队补位）取该轮最后一条；按轮升序
                by_round = {}
                for item in out[aid]:
                    by_round[item["round"]] = item["vector"]
                out[aid] = [{"round": r, "vector": by_round[r]}
                            for r in sorted(by_round)]
        except Exception:
            return {}
        return out
