# -*- coding: utf-8 -*-
"""Agent 桥接：把平台消息池派发接入 AAA 认知节点（黑盒）。

两种运行模式（F9）：
    1. inline（默认，保留作对照）：单进程内 import main + MyNode()，
       桥接循环在本进程内调用 llm_fn。
    2. subprocess：每个 Agent 一个独立 AAA 子进程（aaa_serve.py 常驻），
       通过 stdin/stdout JSON 协议通信，LLM 在子进程内部完成整轮决策，
       父进程一次往返拿回 {action: reply|silent}（进程隔离 + 并行决策）。

链路（对齐方案 §四 数据流）：
    平台批量派发 → AAA _on_pool_batch（写库 + 合并上下文 + prompt）
              → LLM（llm_fn）→ AAA _on_parsed(batch_mode=True) → {action: reply|silent}

决策落采集器（F8 decisions.jsonl）并附带性格向量/心情快照。
"""
import os
import sys
import json
import subprocess


class AgentBridge:
    """单个 Agent 的桥接器（platform 的组成单元）。"""

    def __init__(self, agent_id, identity_key, db_path, llm_fn=None,
                 collector=None, node_dir=None, conv_id="default",
                 max_llm_rounds=4, mode="inline",
                 aaa_env=None, serve_script=None, log_dir=None):
        self.agent_id = agent_id
        self.identity_key = identity_key
        self.db_path = db_path
        self.llm_fn = llm_fn
        self.collector = collector
        self.conv_id = conv_id
        self.max_llm_rounds = max_llm_rounds
        self.mode = mode
        self._node = None
        # subprocess 模式状态
        self._proc = None
        self._aaa_env = aaa_env or {}
        self._log_dir = log_dir
        self._serve_script = serve_script or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "aaa_serve.py")
        self._node_dir = node_dir or os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "nodes", "node_python_aaa_cognition"))
        # inline 模式 LLM 调用计数（subprocess 模式在子进程内计数，见 llm_stats）
        self._inline_llm_calls = 0
        if mode == "inline" and llm_fn is not None:
            _orig = llm_fn

            def _counted(prompt):
                self._inline_llm_calls += 1
                return _orig(prompt)

            self.llm_fn = _counted

    # ── AAA 节点懒加载（inline 模式） ─────────────────────
    def _get_node(self):
        """inline 模式：首次调用导入 AAA 节点并实例化 MyNode；
        subprocess 模式：确保子进程存活后返回 None（节点在子进程内）。"""
        if self.mode == "subprocess":
            self._ensure_proc()
            return None
        if self._node is not None:
            return self._node
        node_dir = os.path.abspath(self._node_dir)
        if node_dir not in sys.path:
            sys.path.insert(0, node_dir)
        import main as aaa_main
        self._node = aaa_main.MyNode()
        return self._node

    # ── subprocess 生命周期 ────────────────────────────────
    def _ensure_proc(self):
        """确保 AAA 子进程存活（异常退出自动重启）。"""
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        # 旧进程已死 → 重启（丢弃该轮 pending 状态）
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None
        env = dict(os.environ)
        env.update(self._aaa_env)
        # stderr 重定向到日志文件（log_dir 提供时），否则 DEVNULL
        if self._log_dir:
            os.makedirs(self._log_dir, exist_ok=True)
            err = open(os.path.join(
                self._log_dir, f"aaa_{self.agent_id.replace(':', '_')}.log"),
                "a", encoding="utf-8")
        else:
            err = subprocess.DEVNULL
        self._proc = subprocess.Popen(
            [sys.executable, self._serve_script,
             "--identity", self.identity_key, "--db", self.db_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=err, env=env, cwd=os.path.dirname(self._serve_script),
            text=True, encoding="utf-8", bufsize=1)
        return self._proc

    def _send(self, req: dict, retries=1) -> dict:
        """向子进程发送一行 JSON 请求并阻塞读响应。

        通信失败（进程死亡/EOF）→ 自动重启并重试一次；仍失败抛异常。
        """
        proc = self._ensure_proc()
        last_err = None
        try:
            proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
        except (BrokenPipeError, OSError, ValueError) as e:
            line = ""
            last_err = e
        if not line:
            # 子进程异常退出 → 重启重试
            if retries > 0:
                try:
                    self._proc.kill()
                except Exception:
                    pass
                self._proc = None
                return self._send(req, retries=retries - 1)
            raise ConnectionError(
                f"aaa_serve 子进程无响应: {last_err or 'EOF'}")
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            if retries > 0:
                try:
                    self._proc.kill()
                except Exception:
                    pass
                self._proc = None
                return self._send(req, retries=retries - 1)
            raise ConnectionError(f"aaa_serve 响应解析失败: {line[:120]}")

    def ping(self) -> bool:
        """探活（subprocess 模式）。"""
        if self.mode != "subprocess":
            return True
        try:
            resp = self._send({"type": "ping"})
            return resp.get("code") == 0
        except Exception:
            return False

    def flush_review(self):
        """等待子进程内后台 review 线程落库（实验收尾用）。"""
        if self.mode != "subprocess":
            node = self._get_node()
            for t in getattr(node, "_review_threads", [])[:]:
                try:
                    t.join(timeout=60)
                except Exception:
                    pass
                node._review_threads = [
                    x for x in node._review_threads if x is not t]
            return
        try:
            self._send({"type": "flush_review"})
        except Exception:
            pass

    def llm_stats(self) -> dict:
        """返回本 Agent 的 LLM 调用量统计（API 调用量实验指标）。

        subprocess：子进程内计数（决策 + 后台 review 全经过 llm_fn）；
        inline：本进程决策路径计数（对照模式，后台 review 线程调用不计）。

        Returns:
            {"calls": int, "mode": str}
        """
        if self.mode == "subprocess":
            try:
                resp = self._send({"type": "llm_stats"})
                if resp.get("code") == 0:
                    return {"calls": int((resp.get("data") or {}).get("calls", 0)),
                            "mode": self.mode}
            except Exception:
                pass
            return {"calls": 0, "mode": self.mode}
        return {"calls": self._inline_llm_calls, "mode": self.mode}

    def close(self):
        """优雅关闭子进程（发 shutdown → wait 回收，防孤儿进程）。"""
        if self.mode != "subprocess" or self._proc is None:
            return
        try:
            self._send({"type": "shutdown"})
        except Exception:
            pass
        try:
            self._proc.wait(timeout=10)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None

    def _snapshot(self) -> dict:
        """性格向量 + 心情快照（写入决策日志，读子进程写出的 DB 文件）。"""
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
    def process_batch(self, messages, round_no=None, mention_targets=None,
                      window=None) -> dict:
        """处理一批聊天室消息，返回显式决策。

        Args:
            messages: 平台派发的本批消息（含 user_id/content/reply_to/seq）
            round_no: 当前批次数
            mention_targets: v6.6 采集——本批中被 @ 点名的 Agent 列表
                （平台按批计算，供 @提及响应率指标统计）
            window: v7.2 接话窗口（平台计算的决策上下文 = 该 agent 最近发言
                之后到切入消息的区间消息）；None 时退回完整批次

        Returns:
            {action: "reply"|"silent", content, user_id, 想法, 心情,
             agent, round, batch_size, personality, mood, ...}
        """
        def _norm(m):
            if hasattr(m, "text"):
                return {"user_id": m.user_id, "content": m.text,
                        "reply_to": getattr(m, "reply_to", ""),
                        "seq": getattr(m, "seq", 0)}
            return {"user_id": m.get("user_id", ""), "content": m.get("content", ""),
                    "reply_to": m.get("reply_to", ""),
                    "seq": m.get("seq", 0)}

        msgs = [_norm(m) for m in messages]
        if not msgs:
            return {"action": "silent", "content": "", "user_id": "",
                    "想法": "", "心情": "", "agent": self.agent_id,
                    "round": round_no, "batch_size": 0}
        # v7.2 接话窗口：决策上下文 = 窗口（LLM 输入）；完整批另存 batch_full
        window_items = ([_norm(m) for m in window]
                        if window is not None else None)
        decision_msgs = window_items if window is not None else msgs

        rid = f"round_{round_no or 0}_" + self.agent_id.replace(":", "_")
        if self.mode == "subprocess":
            resp = self._send({
                "type": "pool_batch",
                "conversation_id": self.conv_id,
                "identity_key": self.identity_key,
                "request_id": rid,
                "messages": decision_msgs,
            })
            if resp.get("code") != 0:
                # v6.3 P0-1：LLM/AAA 调用失败必须独立标记 action="error"，
                # 绝不能落入 silent（否则失败被当成"主动沉默"，静默率被污染）。
                # user_id 不归因（失败时无实际回应对象）。
                decision = {"action": "error", "content": "",
                            "user_id": "",
                            "想法": "", "心情": "",
                            "error": resp.get("error", "")}
            else:
                decision = dict(resp.get("data") or {})
            decision.setdefault("request_id", rid)
        else:
            node = self._get_node()
            out = node._on_pool_batch({
                "data_type": "pool_batch",
                "conversation_id": self.conv_id,
                "identity_key": self.identity_key,
                "request_id": rid,
                "messages": decision_msgs,
            }, self.db_path)

            decision = None
            _trunc_retried = False
            try:
                for _ in range(self.max_llm_rounds):
                    if not out or out.get("data_type") != "prompt":
                        decision = out
                        break
                    content = self.llm_fn(out.get("content", ""))
                    # v6.6 P1-4 输出完整性校验：截断（未闭合节标记 / 有回复
                    # 缺情绪调整）→ 追加提示重试一次，避免半句回复落盘
                    if not _trunc_retried:
                        from parser import is_truncated
                        if is_truncated(content or ""):
                            _trunc_retried = True
                            content = self.llm_fn(
                                (out.get("content", "") or "")
                                + "\n\n（注意：你上次的输出被截断了，"
                                "请完整输出全部小节，并在结尾正常结束，不要中断。）")
                    out = node._on_parsed({
                        "data_type": "parsed", "source": "llm",
                        "request_id": out.get("request_id", rid),
                        "content": content or "",
                    }, self.db_path, {}, user_id="", batch_mode=True)
            except Exception as e:
                # v6.3 P0-1：inline 模式 LLM 调用失败 → error（不落 silent）
                decision = {"action": "error", "content": "",
                            "user_id": "", "想法": "", "心情": "",
                            "error": f"{type(e).__name__}: {e}",
                            "request_id": rid}

            if decision is None:
                # 超过多轮上限仍未收敛 → 兜底静默（不对外广播）
                decision = {"action": "silent", "content": "",
                            "user_id": "", "想法": "", "心情": "",
                            "request_id": rid}

            if not isinstance(decision, dict):
                decision = {"action": "silent", "content": "",
                            "user_id": "", "想法": "", "心情": "",
                            "raw": decision}
            # v6.3 P0-2：user_id 归因由 AAA 内部按【回应对象】决定，
            # 平台不再用批次末尾兜底（否则静默/回复都错误归因到最后发言者）。
            decision.setdefault("user_id", "")
            decision.setdefault("action", "silent")
        decision["agent"] = self.agent_id
        decision["round"] = round_no
        decision["batch_size"] = len(msgs)
        decision["window_size"] = len(decision_msgs)
        # v6.6 P0-1 批次顺序事实源统一：batch_context 带 seq（消息池全局
        # 唯一序号，与 events.batch_dispatched 关联）与 pos（本 Agent 实际
        # 所见顺序中的位置）——末位偏置分析以本顺序为准，两种顺序互证不互斥
        # v7.2 口径：batch_context = 接话窗口（决策实际所见，指标统计依据）；
        # batch_full = 完整批次（与 v6.6 口径对照复核用）
        decision["batch_context"] = [
            {"user_id": m.get("user_id", ""),
             "content": (m.get("content", "") or "")[:60],
             "seq": m.get("seq", 0), "pos": i}
            for i, m in enumerate(decision_msgs)
        ]
        decision["batch_full"] = [
            {"user_id": m.get("user_id", ""),
             "content": (m.get("content", "") or "")[:60],
             "seq": m.get("seq", 0), "pos": i}
            for i, m in enumerate(msgs)
        ]
        # v6.6 P1-5 末位偏置量化（数据采集方案 P2）：reply 时记录回应对象
        # 在批次中的位置（LLM 实际所见顺序）与末位作者——topic_report 据此
        # 计算"回复是否总指向批次最后一条"的量化证据
        _target = str(decision.get("回应对象", "") or "").strip()
        if decision.get("action") == "reply" and _target:
            _pos = next((i for i, m in enumerate(decision_msgs)
                         if m.get("user_id", "").strip() == _target), -1)
            decision["reply_target_pos"] = _pos
            decision["batch_last_author"] = (decision_msgs[-1].get("user_id", "")
                                             if decision_msgs else "")
        # v6.6 采集 @ 提及指标（数据采集方案 P1-5）：本批是否被 @ 点名、
        # 点名者是谁、是否回应了点名者、user_id 归因是否正确
        # （决策 user_id == LLM 回应对象）
        decision["mention_targets"] = list(mention_targets or [])
        _was_mentioned = bool(decision["mention_targets"])
        # mentioner：本批中点名本 agent 的消息作者（@agent:3 / @3 语法）
        _mentioner = ""
        if _was_mentioned:
            _alias = self.agent_id.split(":")[-1]
            for _m in msgs:
                _t = _m.get("content", "") or ""
                if f"@{self.agent_id}" in _t or f"@{_alias}" in _t:
                    _mentioner = _m.get("user_id", "")
                    break
        if decision.get("action") == "reply":
            decision["mention_responded"] = bool(
                _was_mentioned and _mentioner
                and _target and _target == _mentioner)
        decision["attribution_ok"] = bool(
            decision.get("user_id")
            and decision.get("user_id") == _target
            and _target not in ("群聊", "多条", "所有人"))
        decision.update(self._snapshot())
        if self.collector:
            self.collector.decision(**decision)
        return decision
