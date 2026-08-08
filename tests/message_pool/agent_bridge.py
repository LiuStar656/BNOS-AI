# -*- coding: utf-8 -*-
"""Agent 桥接：把平台消息池派发接入 AAA 认知节点（黑盒）。

链路（对齐方案 §四 数据流）：
    平台批量派发 → AAA _on_pool_batch（写库 + 合并上下文 + prompt）
              → LLM（llm_fn）→ AAA _on_parsed(batch_mode=True) → {action: reply|silent}

多轮回执：AAA 可能返回第二轮 prompt（【语意检索】或自我反思），
桥接循环继续调 LLM 直到拿到显式 action 决策（max_llm_rounds 防死循环）。

决策落采集器（F8 decisions.jsonl）并附带性格向量/心情快照。
"""
import os
import sys


class AgentBridge:
    """单个 Agent 的桥接器（platform 的组成单元）。"""

    def __init__(self, agent_id, identity_key, db_path, llm_fn,
                 collector=None, node_dir=None, conv_id="default",
                 max_llm_rounds=4):
        self.agent_id = agent_id
        self.identity_key = identity_key
        self.db_path = db_path
        self.llm_fn = llm_fn
        self.collector = collector
        self.conv_id = conv_id
        self.max_llm_rounds = max_llm_rounds
        self._node = None
        self._node_dir = node_dir or os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "nodes", "node_python_aaa_cognition"))

    # ── AAA 节点懒加载 ─────────────────────────────────────
    def _get_node(self):
        """首次调用时导入 AAA 节点 main.py 并实例化 MyNode。"""
        if self._node is not None:
            return self._node
        node_dir = os.path.abspath(self._node_dir)
        if node_dir not in sys.path:
            sys.path.insert(0, node_dir)
        import main as aaa_main
        self._node = aaa_main.MyNode()
        return self._node

    def _snapshot(self) -> dict:
        """性格向量 + 心情快照（写入决策日志）。"""
        import db
        try:
            seed = db.get_personality(self.db_path, self.identity_key)
            mood = db.get_current_mood(self.db_path, self.identity_key)
            return {
                "personality": {k: round(seed[k], 4) for k in
                                ("warmth", "playfulness", "directness", "curiosity")},
                "mood": round(float(mood), 4),
            }
        except Exception:
            return {"personality": {}, "mood": 0.0}

    # ── 批量处理 ───────────────────────────────────────────
    def process_batch(self, messages, round_no=None) -> dict:
        """处理一批聊天室消息，返回显式决策。

        Returns:
            {action: "reply"|"silent", content, user_id, 想法, 心情,
             agent, round, batch_size, personality, mood, ...}
        """
        node = self._get_node()
        msgs = [
            {"user_id": m.user_id, "content": m.text}
            if hasattr(m, "text") else
            {"user_id": m.get("user_id", ""), "content": m.get("content", "")}
            for m in messages
        ]
        if not msgs:
            return {"action": "silent", "content": "", "user_id": "",
                    "想法": "", "心情": "", "agent": self.agent_id,
                    "round": round_no, "batch_size": 0}

        rid = f"round_{round_no or 0}_" + self.agent_id.replace(":", "_")
        out = node._on_pool_batch({
            "data_type": "pool_batch",
            "conversation_id": self.conv_id,
            "identity_key": self.identity_key,
            "request_id": rid,
            "messages": msgs,
        }, self.db_path)

        last_user_id = msgs[-1].get("user_id", "")
        decision = None
        for _ in range(self.max_llm_rounds):
            if not out or out.get("data_type") != "prompt":
                decision = out
                break
            content = self.llm_fn(out.get("content", ""))
            out = node._on_parsed({
                "data_type": "parsed", "source": "llm",
                "request_id": out.get("request_id", rid),
                "content": content or "",
            }, self.db_path, {}, user_id="", batch_mode=True)

        if decision is None:
            # 超过多轮上限仍未收敛 → 兜底静默（不对外广播）
            decision = {"action": "silent", "content": "", "user_id": last_user_id,
                        "想法": "", "心情": "", "request_id": rid}

        if not isinstance(decision, dict):
            decision = {"action": "silent", "content": "", "user_id": last_user_id,
                        "想法": "", "心情": "", "raw": decision}
        decision.setdefault("user_id", last_user_id)
        decision.setdefault("action", "silent")
        decision["agent"] = self.agent_id
        decision["round"] = round_no
        decision["batch_size"] = len(msgs)
        decision.update(self._snapshot())
        if self.collector:
            self.collector.decision(**decision)
        return decision
