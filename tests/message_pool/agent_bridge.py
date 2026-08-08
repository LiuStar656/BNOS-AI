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
    def process_batch(self, messages, round_no=None) -> dict:
        """处理一批聊天室消息，返回显式决策。

        Returns:
            {action: "reply"|"silent", content, user_id, 想法, 心情,
             agent, round, batch_size, personality, mood, ...}
        """
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
        if self.mode == "subprocess":
            resp = self._send({
                "type": "pool_batch",
                "conversation_id": self.conv_id,
                "identity_key": self.identity_key,
                "request_id": rid,
                "messages": msgs,
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
                "messages": msgs,
            }, self.db_path)

            decision = None
            try:
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
        # v6.2 回应上下文：本批消息作者/内容摘录（渲染聊天历史时标注"回应了谁"；
        # 注意 user_id 只是批次最后一条消息的作者，不等于真正的回应对象）
        decision["batch_context"] = [
            {"user_id": m.get("user_id", ""),
             "content": (m.get("content", "") or "")[:60]}
            for m in msgs
        ]
        decision.update(self._snapshot())
        if self.collector:
            self.collector.decision(**decision)
        return decision
