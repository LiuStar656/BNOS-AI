"""
AAA 认知拼接站 - 核心处理逻辑（合并版 v2.0 — 记忆增强）

v2.0 新特性：
- MemOS 语义检索替换 FAISS hash 检索
- 按需检索：薄 prompt → LLM 决定是否需回忆 → 第二轮带检索结果
- 自我反思：self_cognition 每达 10 条触发回顾迭代
- Diary 日记：次日首条对话触发写前一天日记，联动 MemOS
- 去重合并 + 重要性/decay 机制
"""
import sys
import json
import os
import re
import shutil
import sqlite3
import threading
from datetime import datetime

from config import load_config, resolve
import db
import prompt as pt
import parser as psr
import memos
import diary
import personality as prs
import retrieval_gate
from perception_capabilities import PerceptionCapabilities
from memory_provider import MemOSProvider, sanitize_memory_context
from context_engine import ContextEngine
from session_manager import SessionManager


# ════════════════════════════════════════════════════════════════
#  ★ 开发者在此类中编写所有业务逻辑 — 其他代码不要修改 ★
# ════════════════════════════════════════════════════════════════

_IDENTITY_KEY_DEFAULT = "gui:default"

# v4.0 Prefetch：无意义输入（短输入/礼貌语/命令）跳过记忆预取
_TRIVIAL_PATTERNS = [
    r'^\s*(嗯|好|对|是|ok|yes|继续|在吗|hello|hi|谢谢|了解了|知道了)\s*[.!?！？。]*$',
    r'^\s*[.!?！？。\s]{1,3}\s*$',
    r'^\s*(/learn|/help|/clear|/status)\s*',
]

class MyNode:
    """
    AAA 认知拼接处理器（数据中枢管理器）。

    v2.0 业务能力扩展：
    - MemOS 语义检索（替换旧 FAISS hash）
    - 按需检索两轮交互（LLM 决定是否需回忆）
    - 自我反思（每 10 条 self_cognition 触发）
    - Diary 日记联动（次日首条对话写前一天日记）
    """

    def __init__(self):
        self._current_conversation_id = "default"
        # 缓存第一轮的用户输入上下文（供第二轮检索/反思使用）
        self._pending_contexts: dict[str, dict] = {}
        # v5.1 角色种子：按 identity_key 缓存的性格演化实例
        self._evolutions: dict[str, prs.PersonalityEvolution] = {}
        # v2.0 认知演化增强：最近一次观测风格缓存（供 _on_text 反馈使用）
        self._last_observed_style: dict | None = None
        # v2.0 认知演化增强：打断事件标志（用户打断 TTS → negative 反馈）
        self._interrupt_flag = False
        # v3.1 认知反思：review 触发计数器 + 后台线程引用
        self._review_counter = 0
        self._review_threads: list = []
        # v6.0 消息池实验：静默观察计数器（每消费一批 +1，定期触发后台反思，独立于发言计数）
        self._observe_counter = 0
        # 启动时预加载 MemOS 语义模型到内存
        memos.preload()
        # v4.0: 感知能力声明系统
        self._perception = PerceptionCapabilities()
        # v4.0 Prefetch：最近一次预取命中（v6.6 数据采集，随 pending 传递到 _on_parsed）
        self._last_prefetch_hits: list = []
        # v4.0 MemoryProvider：MemOS 包装（main 不再直连 memos.py 检索细节）
        self.memory_provider = MemOSProvider()
        # v4.0 ContextEngine：按会话跟踪 Token + 超阈值压缩保护
        self.context_engine = ContextEngine()
        self._conversation_history: dict[str, list] = {}
        # v4.0 SessionManager：会话边界管理（切换摘要 + 跨会话结构化记忆）
        self.session_manager = SessionManager()
        # v4.0 Review 回执重试：已重试的 request_id（防无限重发）
        self._review_retried_ids: set = set()

    # ── 框架入口 ──────────────────────────────────────────────
    def process(self, data):
        data_type = data.get("data_type", "")
        source = data.get("source", "")
        cfg = load_config()
        dbp = resolve(cfg.get("db_path", "../shared/chatbot.db"))

        # 对话切换 — 在任何其他处理之前
        if data_type == "switch_conversation":
            return self._on_switch_conversation(data)

        # 日记 LLM 响应（data_type: "parsed", source: "diary"）
        if data_type in ("text", "parsed") and source == "diary":
            return self._on_diary_response(data, dbp)

        # 认知反思 LLM 响应（data_type: "parsed", source: "review"，v3.1 Background Review）
        if data_type in ("text", "parsed") and source == "review":
            return self._on_review_response(data, dbp)

        # 打断事件信号（用户打断 TTS → 下一轮 negative 反馈，v2.0 真实反馈接入）
        if data_type == "interrupt":
            return self._on_interrupt(data)

        # LLM 响应（data_type: "text"/"parsed", source: "llm"）
        if data_type in ("text", "parsed") and source == "llm":
            return self._on_parsed(data, dbp, cfg)

        # GUI 文本输入（data_type: "text", source: "gui"）
        if data_type == "text":
            return self._on_text(data, dbp)

        # v6.0 消息池批量输入（data_type: "pool_batch"，平台打包一批消息）
        if data_type == "pool_batch":
            return self._on_pool_batch(data, dbp)

        # 工具执行结果
        if data_type == "tool_result":
            return self._on_tool_result(data, dbp)

        # DB 管理命令
        if data_type == "db_command":
            return self._on_db_command(data, dbp)

        return {"_port": "default", "status": "noop"}

    # ── 用户文本 / ASR / 视觉 / 环境输入 ──────────────────────

    # ── v4.0 Prefetch 辅助 ─────────────────────────────────────
    def _is_trivial_prompt(self, text: str) -> bool:
        """跳过无意义输入（短输入/礼貌语/命令），节省记忆预取延迟"""
        text = text.strip().lower()
        if len(text) < 3:
            return True
        return any(re.match(p, text, re.IGNORECASE) for p in _TRIVIAL_PATTERNS)

    def _sanitize_memory(self, text: str) -> str:
        """记忆注入前脱敏 + 截断（实现统一在 memory_provider.sanitize_memory_context）"""
        return sanitize_memory_context(text)

    def _prefetch_memory(self, query, dbp, identity_key):
        """同步预取记忆（经 MemoryProvider，含安全协议）；
        无结果返回空串，异常不阻塞对话。"""
        self._last_prefetch_hits = []
        try:
            result = self.memory_provider.prefetch(query, dbp, identity_key)
            if not result:
                return ""
            hits = self.memory_provider.get_last_hits()
            if hits:
                self._last_prefetch_hits = hits
            return result
        except Exception:
            return ""

    def _on_text(self, data, dbp):
        db.ensure(dbp)
        # 首次连接 DB 时加载 MemOS 索引
        if memos._embeddings is None:
            memos.load_index(dbp)
        conv_id = data.get("conversation_id") or data.get("_session_id", "default")
        identity_key = data.get("identity_key", _IDENTITY_KEY_DEFAULT)
        self._current_conversation_id = conv_id

        # 写用户输入到 DB（去重 + importance）
        db.write_async(data, dbp, role="user")

        # ── v2.0 认知演化增强：真实反馈信号 ─────────────
        # 打断（用户打断 TTS）或显式否定句 → negative；普通继续对话 → positive
        if self._interrupt_flag:
            reaction = "negative"
            self._interrupt_flag = False
        else:
            reaction = ("negative" if prs.detect_negative_reaction(data.get("content", ""))
                        else "positive")
        self._observe_user_reaction(dbp, identity_key, reaction=reaction)

        # Diary 检测：次日首条对话触发写前一天日记
        today = datetime.now().strftime("%Y-%m-%d")
        diary.check_and_write_diary(today, dbp)

        attachments = data.get("attachments", [])
        rid = data.get("request_id", "")

        # ── v4.0 Prefetch：单轮交互，同步预取记忆并注入安全协议 ──
        # v7.0 检索门控（retrieval_gate.should_prefetch）：判断这轮需不需要
        # 预取记忆（config.retrieval_gate.mode，默认 off = 每轮强制预取）
        query = data.get("content", "")
        memory_context = ""
        if not self._is_trivial_prompt(query):
            should, _gate_info = retrieval_gate.should_prefetch(query)
            if should:
                memory_context = self._prefetch_memory(query, dbp, identity_key)

        # 一轮成型：直接组装完整上下文（不再需要 LLM 决策检索）
        ctx = self._gather_context(
            query, dbp, attachments, conv_id,
            skip_retrieval=True,
            prefetch_override=memory_context,
            identity_key=identity_key,
        )

        # 缓存当前上下文，供写库/反思/Review 使用
        # （v6.6 采集：预取命中随 pending 传递到 _on_parsed，替代原第二轮 get_last_hits）
        self._pending_contexts[rid] = {
            "user_text": query,
            "attachments": attachments,
            "conv_id": conv_id,
            "identity_key": identity_key,
            "user_id": str(data.get("user_id", "") or ""),
            "memory_hits": self._last_prefetch_hits,
        }

        return {
            "_port": "prompt", "data_type": "prompt", "content": pt.build(ctx),
            "request_id": rid,
        }

    # ── v6.0 F1 消息池批量入口 ─────────────────────────────────
    def _on_pool_batch(self, data, dbp):
        """处理平台打包的一批弹幕消息（每条带 user_id/speaker_id）。

        - 与 `_on_text` 并存：GUI 直连仍走单条路径，消息池走批量路径。
        - 批量写库（user_id 归属）+ 合并上下文（F5）+ 静默观察计数（F7）。
        - 返回 prompt 交给 LLM；回执由 `_on_parsed(..., batch_mode=True)` 处理，
          最终返回 {action: reply|silent} 显式决策（F4）。
        """
        db.ensure(dbp)
        # 首次连接 DB 时加载 MemOS 索引
        if memos._embeddings is None:
            memos.load_index(dbp)
        messages = data.get("messages") or []
        if not messages:
            return {"_port": "default", "data_type": "pool_ack", "action": "silent",
                    "content": "", "user_id": "", "status": "empty"}

        conv_id = data.get("conversation_id") or data.get("_session_id", "default")
        identity_key = data.get("identity_key", _IDENTITY_KEY_DEFAULT)
        rid = data.get("request_id", "")
        self._current_conversation_id = conv_id

        # 1. 批量写库：每条消息归属到具体 user_id（去重按 user_id 隔离）
        for m in messages:
            db.write_async({
                "conversation_id": conv_id,
                "identity_key": identity_key,
                "user_id": m.get("user_id") or m.get("speaker_id", ""),
                "content": m.get("content", ""),
            }, dbp, role="user")

        # 2. F5 合并批量上下文：按时间正序拼接；最后发言用户为检索注入对象
        last_user_id = str(
            messages[-1].get("user_id") or messages[-1].get("speaker_id", "") or "")
        merged = "\n".join(
            f"[{m.get('user_id') or m.get('speaker_id') or '匿名'}] {m.get('content', '')}"
            for m in messages)

        # v4.0 Prefetch：批量场景对合并文本同步预取（单轮交互，注入安全协议）
        # v7.0 检索门控：判断这轮需不需要预取记忆
        memory_context = ""
        if not self._is_trivial_prompt(merged):
            should, _gate_info = retrieval_gate.should_prefetch(merged)
            if should:
                memory_context = self._prefetch_memory(merged, dbp, identity_key)

        ctx = self._gather_context(
            merged, dbp, conv_id=conv_id, skip_retrieval=True,
            prefetch_override=memory_context,
            identity_key=identity_key, user_id=last_user_id, batch_items=messages,
        )

        # 3. 缓存当前上下文（供写库 / 反思 / Review 使用；v6.6 采集：预取命中随 pending 传递）
        if rid:
            self._pending_contexts[rid] = {
                "user_text": merged,
                "attachments": data.get("attachments", []),
                "conv_id": conv_id,
                "identity_key": identity_key,
                "user_id": last_user_id,
                "batch_items": messages,
                "memory_hits": self._last_prefetch_hits,
            }

        # 4. F7 后台监听计数：静默观察也计数，每 N 批触发一次后台反思
        #    （独立于发言计数 _review_counter，保证"只听不说"也能沉淀认知）
        # v4.0 阈值配置化：review_interval（0 = 关闭）
        self._observe_counter += 1
        _ri = int(load_config().get("review_interval", 5) or 0)
        if _ri and self._observe_counter % _ri == 0:
            self._trigger_background_review(dbp, conv_id, identity_key, last_user_id)

        return {
            "_port": "prompt", "data_type": "prompt", "content": pt.build(ctx),
            "request_id": rid,
        }

    # ── LLM 节标记回执 ─────────────────────────────────────────
    def _on_parsed(self, data, dbp, cfg, user_id="", batch_mode=False):
        db.ensure(dbp)
        conv_id = data.get("conversation_id") or data.get("_session_id", "default")
        content = data.get("content", "")
        parsed = psr.parse_llm_output(content)
        rid = data.get("request_id", "")

        # ── 三选一决策 ─────────────────────────────────
        tool_call = parsed.get("工具调用", [])
        pending = self._pending_contexts.pop(rid, None)
        user_text = pending.get("user_text", "") if pending else ""
        identity_key = pending.get("identity_key", _IDENTITY_KEY_DEFAULT) if pending else _IDENTITY_KEY_DEFAULT
        # v6.0 多用户：user_id 取值优先级 参数 > data > pending
        if not user_id:
            user_id = str(data.get("user_id", "") or "")
        if not user_id and pending:
            user_id = pending.get("user_id", "")

        # v6.3 P0-2：批量模式 user_id 归因改为 LLM 显式【回应对象】——
        # 原实现把批次最后一条消息的作者当作 user_id（_on_pool_batch 的
        # last_user_id），导致静默/回复的认知都错误归因到"最后发言者"，
        # 且与模型实际回应对象（若 LLM 输出 agent:3 但末位是 agent:5）不符。
        # reply → 归因到回应对象；静默/群聊/无回应对象 → 不归因（""）。
        if batch_mode:
            _target = (parsed.get("回应对象") or "").strip()
            if _target and _target not in ("群聊", "多条", "所有人"):
                # v6.5 防自认知污染：agent 回应对象是自己（如话题结束后
                # 批次含自身发言，LLM 回应了自己的话）时不得把认知归因到
                # 自己 → 清空归因（otherwise other_cognition 混入自认知）
                user_id = "" if _target == identity_key else _target
            else:
                user_id = ""

        # ③ 工具调用（当前功能尚未开放）
        if tool_call:
            if batch_mode:
                return {
                    "action": "reply",
                    "content": "抱歉，工具调用功能目前尚未开放。",
                    "user_id": user_id, "request_id": rid,
                }
            return {
                "_port": "reply", "data_type": "reply",
                "content": "抱歉，工具调用功能目前尚未开放。",
                "request_id": rid,
            }

        # v4.0 Prefetch 单轮交互：删除「② 检索记忆 → 第二轮」分支。
        # 记忆检索已在 _on_text/_on_pool_batch 预取完成并随 Prompt 注入；
        # 命中采集随 pending["memory_hits"] 传递（见 _on_text）。

        # ① 直接回复 — 正常写库 + 输出
        # v6.6 P0-2：批量模式下 user_id 空（群聊/无对象/自认知）→ 跳过
        # other_cognition 写入（空键污染认知矩阵的根因）；GUI 路径保持兜底。
        db.write_parsed_async(parsed, dbp, conversation_id=conv_id, user_input=user_text,
                              identity_key=identity_key, user_id=user_id,
                              skip_empty_other=batch_mode)

        # ── v2.0 认知演化增强：观测本次回复风格 → 触发性格演化 ──
        # 演化输入源改为"本次回复实际表现的风格"（修复 v1.0 自己看自己）
        self._last_observed_style = prs.estimate_style_from_reply(parsed)
        self._process_mood_and_evolution(parsed, dbp, conv_id, identity_key,
                                         reaction="neutral",
                                         style=self._last_observed_style)

        # ── v3.1 认知反思：每 N 轮后台 Review 沉淀持久认知 ──
        # v4.0 阈值配置化：cfg.review_interval（0 = 关闭）
        self._review_counter += 1
        _ri = int(cfg.get("review_interval", 5) or 0)
        if _ri and self._review_counter % _ri == 0:
            self._trigger_background_review(dbp, conv_id, identity_key, user_id)

        # ── 自我反思触发器 ──────────────────────────────────
        conn = sqlite3.connect(dbp)
        try:
            sc_count = conn.execute(
                "SELECT COUNT(*) FROM self_cognition WHERE conversation_id=? AND identity_key=?",
                (conv_id, identity_key),
            ).fetchone()[0]
            has_reflection = sc_count > 0 and sc_count % 10 == 0
            if has_reflection:
                sc_rows = conn.execute(
                    "SELECT content FROM self_cognition WHERE conversation_id=? AND identity_key=? ORDER BY id DESC LIMIT 5",
                    (conv_id, identity_key),
                ).fetchall()
                ev_rows = conn.execute(
                    "SELECT summary FROM event_summary WHERE conversation_id=? AND identity_key=? ORDER BY id DESC LIMIT 5",
                    (conv_id, identity_key),
                ).fetchall()
                parts = []
                if sc_rows:
                    parts.append("你之前的自我认识：\n" + "\n".join(
                        f"{i+1}. {r[0]}" for i, r in enumerate(reversed(sc_rows))))
                if ev_rows:
                    parts.append("最近的事件：\n" + "\n".join(
                        f"- {r[0]}" for r in reversed(ev_rows)))
                reflection_prompt = "\n\n".join(parts)
        finally:
            conn.close()

        if has_reflection:
            ctx3 = self._gather_context(
                "", dbp, conv_id=conv_id, reflection_override=reflection_prompt,
                identity_key=identity_key, user_id=user_id,
            )
            new_rid = f"{rid}_reflection"
            # v6.0 修复：为反思轮续接 pending（原实现丢 identity_key/user_id，
            # 多 Agent 场景下反思回执会退回默认身份，必须保留上下文）
            self._pending_contexts[new_rid] = {
                "user_text": user_text,
                "attachments": pending["attachments"] if pending else [],
                "conv_id": conv_id,
                "identity_key": identity_key,
                "user_id": user_id,
            }
            return {
                "_port": "prompt", "data_type": "prompt",
                "content": pt.build(ctx3),
                "request_id": new_rid,
            }

        # ── 异步重建 MemOS 索引（经 MemoryProvider）+ 知识图谱 + 情感趋势 ──
        self.memory_provider.sync_turn(
            user_text, parsed.get("自然回复", ""), dbp, identity_key, conv_id)
        threading.Thread(target=memos.rebuild_knowledge_index, args=(dbp,), daemon=True).start()
        threading.Thread(
            target=db._aggregate_mood, args=(dbp, conv_id), daemon=True,
            kwargs={"identity_key": identity_key},
        ).start()

        # ── v4.0 ContextEngine：会话历史 Token 跟踪 + 超阈值压缩保护 ──
        # 压缩前抢救含持久化价值的消息（on_pre_compress → long_term_memory）
        self._conversation_history.setdefault(conv_id, []).extend([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": parsed.get("自然回复", "")},
        ])
        hist = self._conversation_history[conv_id]
        if self.context_engine.should_compress(
                self.context_engine.estimate_tokens(hist)):
            self._conversation_history[conv_id] = self.context_engine.compress(
                hist, dbp, identity_key)

        # v6.0 F4 静默处理通道：回复文本（自然回复为空 → 静默）
        reply_text = (psr.inject_mood_tag(parsed["自然回复"], parsed.get("心情", ""))
                      if parsed.get("自然回复") else "")

        # v7.0 空回复兜底（阶段0-bug1）：GUI 单条路径 LLM 输出被截断/格式损坏
        # 导致【自然回复】缺失时，不应让用户收到空响应——输出兜底回复并告警。
        # 批量路径保留原语义（reply/silent 由平台按有无文本决策，不算异常）。
        if not reply_text and not batch_mode:
            print(f"[WARN] 空回复（rid={rid} raw_len={len(content)}），输出兜底", flush=True)
            reply_text = "嗯，我在听。刚才那句我可能没接好，你能再说具体一点吗？"

        # ── v6.0 F4 批量模式：返回显式决策 {action: reply|silent} ──
        # 平台据此决定广播（reply）或标记已消费（silent）；认知演化已在上方照常执行。
        # v6.1 意识流同步：想法是内心活动，无论回复与否都必须更新——LLM 未输出
        # 【想法】/【心情】时给默认值兜底，保证静默决策也带状态（回复与否只看
        # 【自然回复】有无文本，与想法无关）。
        if batch_mode:
            _is_reply = bool(reply_text)
            # v6.6 数据采集 P0-1：记忆检索命中（第二轮决策时 pending 携带）
            _hits = list((pending or {}).get("memory_hits", []))
            # v6.6 数据采集 P0-2：静默≠无认知——统计本次是否仍写入了认知类内容
            _cog_sections = [k for k in ("自我认知", "他人认知", "用户记忆",
                                         "环境记忆", "事件摘要")
                             if (parsed.get(k) or "").strip()]
            _thought = parsed.get("想法", "").strip()
            if _hits:
                db.record_memory_usage(dbp, identity_key, rid, _hits)
            if not _is_reply:
                db.record_silent_cognition(
                    dbp, identity_key, rid, thought=_thought,
                    cognition_written=bool(_cog_sections),
                    sections=",".join(_cog_sections))
            return {
                "action": "reply" if _is_reply else "silent",
                "content": reply_text,
                "user_id": user_id,
                # v6.5 静默模板分 action：想法缺失时只有静默才用
                # "保持观察"兜底；reply 不得复用静默文案（曾出现
                # action=reply 但想法="收到消息，保持观察"的数据污染）
                "想法": _thought
                       or ("" if _is_reply else "收到消息，保持观察，暂不回应"),
                "心情": parsed.get("心情", "").strip() or "平静",
                # v6.2 回应对象：LLM 显式声明的回应对象（agent:3 / 用户A / 群聊），
                # 渲染聊天历史时优先用它标注"在回答谁"（无 batch_context 的旧数据回退）
                "回应对象": parsed.get("回应对象", "").strip(),
                "request_id": rid,
                # v6.6 采集：记忆命中日志 + 静默认知写入标记
                "memory_hits": _hits,
                "silent_cognition_written": bool(_cog_sections) if not _is_reply else False,
                "cognition_sections": ",".join(_cog_sections),
            }

        # ── 输出 reply + knowledge + logseq ─────────────
        outputs = []
        if reply_text:
            outputs.append({
                "_port": "reply", "data_type": "reply",
                "content": reply_text,
                "request_id": rid, "action": "reply",
            })
        # v4.0: 支持【记忆归档】（旧）和【用户记忆】+【环境记忆】（新）
        archive_content = parsed.get("记忆归档") or parsed.get("用户记忆") or parsed.get("环境记忆")
        if archive_content:
            outputs.append({
                "_port": "default", "data_type": "knowledge",
                "content": archive_content,
                "tags": parsed.get("归档标签", ""),
                "request_id": rid,
            })
            # ── Logseq 输出：记忆归档 + 向量关联 ────────────
            logseq_related = []
            try:
                raw_results = memos.retrieve_raw(
                    archive_content, top_k=5, identity_key=identity_key, db_path=dbp)
                if raw_results:
                    conn = sqlite3.connect(dbp)
                    try:
                        for r in raw_results:
                            eid = r.get("entry_id", 0)
                            tbl = r.get("table", "long_term_memory")
                            row = conn.execute(
                                f"SELECT content FROM [{tbl}] WHERE id=?", (eid,)
                            ).fetchone()
                            if row:
                                logseq_related.append({
                                    "content": row[0][:100],
                                    "score": r["score"],
                                })
                    finally:
                        conn.close()
            except Exception:
                pass
            outputs.append({
                "_port": "logseq", "data_type": "knowledge_logseq",
                "content": archive_content,
                "tags": parsed.get("归档标签", ""),
                "related": logseq_related,
                "request_id": rid,
            })
        return outputs

    # ── 日记 LLM 回执 ──────────────────────────────────────────
    def _on_diary_response(self, data, dbp):
        """处理日记 LLM 响应：写 event_summary + self_cognition + 重建 MemOS"""
        content = data.get("content", "")
        rid = data.get("request_id", "")  # "diary_2026-07-25"
        date_str = rid.replace("diary_", "") if rid.startswith("diary_") else ""

        if not content or not date_str:
            return {"_port": "default", "status": "noop"}

        conn = sqlite3.connect(dbp)
        try:
            # 1. 写 diaries 表
            conn.execute(
                "INSERT INTO diaries(conversation_id, date, content, mood, identity_key) VALUES(?, ?, ?, ?, ?)",
                ("default", date_str, content[:2000], data.get("mood", ""), _IDENTITY_KEY_DEFAULT))

            conn.commit()
        finally:
            conn.close()

        # 3. 重建 MemOS 索引，将日记条目纳入语义检索
        threading.Thread(target=memos.rebuild_index, args=(dbp,), daemon=True).start()

        # 4. 重建记忆图谱索引
        threading.Thread(target=memos.rebuild_knowledge_index, args=(dbp,), daemon=True).start()

        return {"_port": "default", "status": "ok", "message": f"diary processed for {date_str}"}

    # ── 工具执行结果 ──────────────────────────────────────────
    def _on_tool_result(self, data, dbp):
        db.ensure(dbp)
        conv_id = data.get("conversation_id") or data.get("_session_id", "default")
        self._current_conversation_id = conv_id
        db.write_async(data, dbp, role="tool")
        ctx = self._gather_context(
            data.get("content", ""), dbp, conv_id=conv_id,
            skip_retrieval=True, identity_key=_IDENTITY_KEY_DEFAULT,
        )
        return {"_port": "prompt", "data_type": "prompt", "content": pt.build(ctx)}

    # ── 上下文收集（v3.0 重写：加入 identity_key 隔离；v6.0：加入 user_id 多用户过滤 + 批量合并） ─────────
    @staticmethod
    def _fmt_pool_msg(m: dict) -> str:
        """v6.4 引用链：批次消息格式化，标注"回应谁"（reply_to）——
        让 LLM 决策时可见对话引用结构（谁在回应谁），而非扁平消息列表。"""
        user = m.get("user_id") or m.get("speaker_id") or "匿名"
        content = m.get("content", "")
        rt = str(m.get("reply_to") or "").strip()
        if rt:
            if rt in ("群聊", "多条", "所有人"):
                return f"[{user}] {content}（回应群聊）"
            return f"[{user}] {content}（回应 {rt[:20]}）"
        return f"[{user}] {content}"

    def _gather_context(self, user_text, dbp, attachments=None, conv_id="default",
                         skip_retrieval=False, retrieval_override=None,
                         prefetch_override=None,
                         reflection_override=None, identity_key=_IDENTITY_KEY_DEFAULT,
                         user_id="", batch_items=None):
        """收集上下文。

        Args:
            skip_retrieval: 第一轮「薄 prompt」时不检索
            retrieval_override: 第二轮「带检索结果」时直接注入（兼容保留）
            prefetch_override: v4.0 Prefetch 模式注入预取结果（优先级最高，含安全标签）
            reflection_override: 自我反思时注入历史认知
            identity_key: 身份键，隔离不同用户的记忆/认知/画像
            user_id: v6.0 当前对话用户；other_cognition / user_facts 按该用户过滤
            batch_items: v6.0 消息池批量消息列表（含 user_id/content），合并注入
        """
        cfg = load_config()
        conn = sqlite3.connect(dbp)
        try:
            limit = cfg.get("max_history_summary", 3)

            # 1. 固定认知层（全局共享，不按 identity 隔离）
            fixed_rows = conn.execute(
                "SELECT key, value FROM fixed_cognition ORDER BY updated_at DESC"
            ).fetchall()
            fixed_context = "\n".join(f"{k}: {v}" for k, v in fixed_rows) if fixed_rows else ""

            # 2. 对话层 — 按 identity_key + conversation_id 隔离
            sc = db.g_where_identity(conn, "self_cognition", "content", conv_id, identity_key)
            # v6.0 多用户：他人认知按 user_id 检索（user_id='' 全局认知兜底）
            oc = db.g_where_identity_user(conn, "other_cognition", "content", conv_id, identity_key, user_id)

            # v7.1 近期观察记录：interest_judgment 未过门（passed=0）的检测文本
            # 回流上下文，让"看过但没回应"的消息后续想得起（零额外 LLM 调用）
            recent_observations = db.read_recent_observations(
                conn, identity_key, cfg.get("recent_observations_limit", 5))

            r = conn.execute(
                "SELECT mood,thought FROM feelings WHERE conversation_id=? AND identity_key=? ORDER BY id DESC LIMIT 1",
                (conv_id, identity_key)
            ).fetchone()
            feel = (f"心情：{r[0]}" + (f" | 想法：{r[1]}" if r[1] else "")) if r else ""

            hs = "\n".join(
                f"[{x[1][:10]}] {x[0]}" for x in conn.execute(
                "SELECT summary, created_at FROM event_summary WHERE conversation_id=? AND identity_key=? ORDER BY id DESC LIMIT ?",
                (conv_id, identity_key, limit)
            ).fetchall())

            # v6.0 多用户：用户事实按 user_id 过滤（用户专属优先，全局兜底）
            ui = "\n".join(x[0] for x in conn.execute(
                "SELECT content FROM user_facts WHERE category='background' AND conversation_id=? AND identity_key=? "
                "AND (user_id=? OR user_id='') "
                "ORDER BY CASE WHEN user_id=? THEN 0 ELSE 1 END, id DESC LIMIT 5",
                (conv_id, identity_key, user_id, user_id)
            ).fetchall())

            si = ", ".join(f"{k}={v}" for k, v in conn.execute(
                "SELECT key,value FROM self_info WHERE conversation_id=? AND identity_key=? ORDER BY id DESC LIMIT 20",
                (conv_id, identity_key)
            ).fetchall())

            # 3. 本周情感基调
            mood_trend_row = conn.execute(
                """SELECT dominant_mood, avg_mood_value FROM mood_trend
                   WHERE conversation_id=? AND identity_key=? ORDER BY id DESC LIMIT 1""",
                (conv_id, identity_key),
            ).fetchone()
            mood_trend = ""
            if mood_trend_row:
                mood_trend = f"{mood_trend_row[0]}（{mood_trend_row[1]:.1f}/5）"

        finally:
            conn.close()

        # 4. MemOS 检索（v4.0 优先级：prefetch_override > retrieval_override > 按需）
        # v7.0 检索门控：兴趣门控（平台 passed=1）之后、提示词拼接之前，判定
        # 这轮对话需不需要预取记忆（config.retrieval_gate.mode，默认 off=每轮强制）。
        # 三条路径统一过门控：on_text/on_pool_batch 的 prefetch（前置判定已拦，
        # 传 prefetch_override），反思等 fallback 检索在此判定（含空文本拦截）。
        memos_top5 = ""
        if prefetch_override is not None:
            memos_top5 = prefetch_override    # v4.0 Prefetch：直接使用预取结果（含安全标签）
        elif retrieval_override is not None:
            memos_top5 = retrieval_override    # 第二轮：注入精确检索结果（LLM 明确请求，绕过门控）
        elif not skip_retrieval:
            should, _info = retrieval_gate.should_prefetch(user_text)
            if should:
                memos_top5 = memos.retrieve(
                    user_text, top_k=5, db_path=dbp, identity_key=identity_key,
                )

        # 6. 附件上下文
        attachment_context = ""
        if attachments:
            lines = []
            for i, att in enumerate(attachments, 1):
                atype = att.get("type", "file")
                aname = att.get("name", "unknown")
                apath = att.get("path", "")
                lines.append(f"  {i}. 类型: {atype} | 名称: {aname} | 路径: {apath}")
            attachment_context = (
                "用户附带了以下附件（你可通过 file_read(\"路径\") 读取内容）：\n"
                + "\n".join(lines)
                + "\n\n如需查看附件内容，请调用 file_read(\"路径\")。"
                "若你无法处理（如不支持该文件类型），请在回复中告知用户。"
            )

        now = datetime.now()

        # v5.1 角色种子系统：读取性格向量 + 情绪值并构建注入段
        seed = db.get_personality(dbp, identity_key)
        personality_section = prs.build_personality_section(
            {"warmth": seed["warmth"], "playfulness": seed["playfulness"],
             "directness": seed["directness"], "curiosity": seed["curiosity"]},
            seed.get("style_description", ""),
        )
        mood_value = db.get_current_mood(dbp, identity_key)
        mood_section = prs.build_mood_section(mood_value)

        # v4.0 SessionManager：跨会话摘要注入（会话级结构化记忆，与全局扁平记忆互补）
        try:
            session_hist = self.session_manager.get_session_history(identity_key, dbp)
            if session_hist:
                ss_text = "\n".join(
                    f"[{s['created_at'][:10]}] {s['summary']}" for s in session_hist)
                hs = (ss_text + "\n" + hs) if hs else ss_text
        except Exception:
            pass

        return {
            "identity_key": identity_key,
            "fixed_cognition": fixed_context,
            "self_cognition": sc, "other_cognition": oc, "recent_feelings": feel,
            "recent_observations": recent_observations,
            "user_text": user_text, "current_date": now.strftime("%Y-%m-%d"),
            "current_time": now.strftime("%H:%M:%S"), "current_state": "清醒",
            "history_summary": hs, "user_info": ui, "self_info": si,
            "mood_trend": mood_trend,
            "memos_top5": memos_top5,
            "attachment_context": attachment_context,
            "reflection_prompt": reflection_override or "",
            "perception": self._perception.get_perception_text(),
            # v1.3 定位信息：传 db_path 让 prompt.py 自动查询并注入位置段
            "db_path": dbp,
            # v5.1 角色种子：性格段 + 情绪段
            "personality": personality_section,
            "mood": mood_section,
            # v6.0 消息池实验：
            "user_id": user_id,
            "pool_batch_section": (
                "本轮消息池消息（按时间正序）：\n" + "\n".join(
                    self._fmt_pool_msg(m) for m in batch_items)
                if batch_items else ""
            ),
        }

    # ── 对话切换 ────────────────────────────────────────────
    def _on_switch_conversation(self, data):
        conv_id = data.get("conversation_id", "default")
        identity_key = data.get("identity_key", _IDENTITY_KEY_DEFAULT)
        self._current_conversation_id = conv_id
        self._pending_contexts.clear()
        # v4.0 ContextEngine：会话切换时清空旧会话历史（Token 统计归零）
        self._conversation_history.pop(conv_id, None)
        # v4.0 SessionManager：切换会话 → 旧会话异步生成摘要 + 新会话加载历史摘要
        cfg = load_config()
        dbp = resolve(cfg.get("db_path", "../shared/chatbot.db"))
        self.session_manager.start_session(conv_id, identity_key, dbp)
        return {
            "_port": "default", "data_type": "switch_conversation_ack",
            "status": "ok", "conversation_id": conv_id,
        }

    # ── v5.1 角色种子：情绪处理 + 性格演化 ────────────────────
    def _get_evolution(self, dbp, identity_key):
        """按 identity_key 懒加载 PersonalityEvolution 实例"""
        evo = self._evolutions.get(identity_key)
        if evo is None:
            seed = db.get_personality(dbp, identity_key)
            evo = prs.PersonalityEvolution({
                "warmth": seed["warmth"], "playfulness": seed["playfulness"],
                "directness": seed["directness"], "curiosity": seed["curiosity"],
            })
            self._evolutions[identity_key] = evo
        return evo

    def _persist_evolution(self, dbp, identity_key, evo):
        """演化发生微调后写回 DB（保留原风格描述与预设名）"""
        if not evo.vector_changed:
            return
        seed = db.get_personality(dbp, identity_key)
        db.save_personality(
            dbp, evo.vector,
            style_description=seed.get("style_description", ""),
            preset_name=seed.get("preset_name", "默认"),
            identity_key=identity_key,
        )

    def _process_mood_and_evolution(self, parsed, dbp, conv_id, identity_key,
                                    reaction: str = "neutral", style: dict | None = None):
        """处理【情绪调整】标签 → 累加写 mood_value → 触发性格演化

        v2.0：style 为本次回复的观测风格（演化输入源），不传时回退到观测函数推导。
        """
        try:
            raw = parsed.get("情绪调整", "0.0")
            adjustment = prs.parse_mood_adjustment(raw)
            current_mood = db.get_current_mood(dbp, identity_key)
            new_mood = prs.compute_new_mood(current_mood, adjustment)
            db.save_mood_value(dbp, new_mood, adjustment,
                               source_mood=parsed.get("心情", ""),
                               conversation_id=conv_id, identity_key=identity_key)

            evo = self._get_evolution(dbp, identity_key)
            if style is None:
                style = prs.estimate_style_from_reply(parsed)
            evo.observe_feedback(style, reaction, mood=new_mood)
            self._persist_evolution(dbp, identity_key, evo)
        except Exception:
            pass

    def _observe_user_reaction(self, dbp, identity_key, reaction: str):
        """采集用户自然行为作为反馈信号（positive/negative）

        v2.0：风格取最近一次观测（_on_parsed 缓存），未观测到用默认值（不引发演化）。
        """
        try:
            mood_value = db.get_current_mood(dbp, identity_key)
            evo = self._get_evolution(dbp, identity_key)
            style = self._last_observed_style or prs.get_default_style()
            evo.observe_feedback(style, reaction, mood=mood_value)
            self._persist_evolution(dbp, identity_key, evo)
        except Exception:
            pass

    # ── v2.0 打断事件（用户打断 TTS → negative 反馈信号源）──────
    def _on_interrupt(self, data):
        """接收打断信号并记录标志，下一轮用户输入合并为 negative 反馈"""
        self._interrupt_flag = True
        return {"_port": "default", "status": "ok", "message": "interrupt recorded"}

    # ── v3.1 认知反思（Background Review）────────────────────────
    def _get_recent_conversation(self, dbp, conv_id, identity_key, limit=10):
        """取最近 N 条 user/assistant 消息（升序），供 review 提炼（含 user_id 标注）"""
        conn = sqlite3.connect(dbp)
        try:
            rows = conn.execute(
                "SELECT role, content, user_id FROM user_messages "
                "WHERE conversation_id=? AND identity_key=? AND role IN ('user','assistant') "
                "ORDER BY id DESC LIMIT ?", (conv_id, identity_key, limit)).fetchall()
            return [{"role": r[0], "content": r[1], "user_id": r[2] or ""} for r in reversed(rows)]
        finally:
            conn.close()

    def _trigger_background_review(self, dbp, conv_id, identity_key, user_id=""):
        """每 5 轮触发一次后台 Review（线程内完成，不阻塞主流程）。

        Args:
            user_id: v6.1 多用户 — review 沉淀 declarative 用户事实时归属的说话对象
        """
        try:
            conversation = self._get_recent_conversation(dbp, conv_id, identity_key)
            if not conversation:
                return
            thr = threading.Thread(
                target=self._run_background_review,
                args=(conversation, dbp, identity_key, user_id), daemon=True)
            self._review_threads.append(thr)
            thr.start()
        except Exception:
            pass

    def _run_background_review(self, conversation, dbp, identity_key, user_id=""):
        """后台线程：构建 review prompt → LLM 调用 → 解析 → 持久化。

        线程内严禁调用 memos / 语义模型（并发 native 崩溃 0xC0000005）。
        LLM 调用走 review.llm_call：有注入钩子则同步；否则写文件走节点间通道，
        回执由 _on_review_response 处理。
        """
        try:
            import review
            review.run_review(conversation, dbp, identity_key, user_id)
        except Exception:
            pass

    def _on_review_response(self, data, dbp):
        """处理 review 回执（data_type=parsed, source=review）→ 解析 + 持久化"""
        # v4.0 Session 摘要回执分流（复用 review 通道，request_id 前缀区分）
        rid = data.get("request_id", "")
        if rid.startswith("session_summary_"):
            return self._on_session_summary_response(data, dbp)
        try:
            import review
            content = data.get("content", "")
            identity_key = data.get("identity_key", _IDENTITY_KEY_DEFAULT)
            user_id = str(data.get("user_id", "") or "")
            if not content:
                return {"_port": "default", "status": "noop"}
            insights = review.parse_review_result(content)
            # v4.0 回执重试：LLM 偶发输出脏文本导致解析为空 → 重发一次 review 请求
            # （防静默丢记忆；_review_retried_ids 防无限重发）
            if not insights and content.strip() and rid not in self._review_retried_ids:
                self._review_retried_ids.add(rid)
                self._trigger_background_review(
                    dbp, self._current_conversation_id, identity_key, user_id)
                return {"_port": "default", "status": "retry"}
            for ins in insights:
                review.persist_insight(ins, dbp, identity_key, user_id)
            return {"_port": "default", "status": "ok",
                    "message": f"review processed {len(insights)} insights"}
        except Exception:
            return {"_port": "default", "status": "error"}

    def _on_session_summary_response(self, data, dbp):
        """处理会话摘要回执（request_id 前缀 session_summary_）→ 写 session_summaries 表"""
        content = (data.get("content") or "").strip()
        identity_key = data.get("identity_key", _IDENTITY_KEY_DEFAULT)
        rid = data.get("request_id", "")
        # 回执定位旧会话：session_id 字段 > request_id 编码 > 当前会话兜底
        session_id = (data.get("session_id") or ""
                      or SessionManager.parse_summary_rid(rid)
                      or self._current_conversation_id)
        if not content:
            return {"_port": "default", "status": "noop"}
        conn = sqlite3.connect(dbp)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS session_summaries("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "session_id TEXT NOT NULL,"
                "identity_key TEXT NOT NULL DEFAULT 'gui:default',"
                "summary TEXT NOT NULL,"
                "created_at TEXT NOT NULL DEFAULT(datetime('now', 'localtime')))")
            conn.execute(
                "INSERT INTO session_summaries(session_id, identity_key, summary, created_at) "
                "VALUES(?, ?, ?, datetime('now','localtime'))",
                (session_id, identity_key, content[:2000]))
            conn.commit()
        finally:
            conn.close()
        return {"_port": "default", "status": "ok",
                "message": f"session summary saved: {session_id}"}

    # ── DB 管理命令（clear / format / backup / restore）───
    def _clear_conversation_history(self):
        """清空 GUI 对话历史 JSON（人格格式化用，见方案 §10.5）"""
        try:
            # main.py 位于 nodes/node_python_aaa_cognition/，项目根向上两级
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            path = os.path.join(root, "gui", "pages", "conversation_history.json")
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass

    def _on_db_command(self, data, dbp):
        cmd = data.get("cmd", "")
        db_dir = os.path.dirname(dbp)
        db_name = os.path.basename(dbp)

        if not os.path.isfile(dbp):
            return {"data_type": "db_result", "cmd": cmd, "status": "error", "message": "数据库文件不存在"}

        if cmd == "format":
            # 人格格式化 = 彻底清空数据库（含固定认知）+ 重置性格（清空数据库与格式化合并为一个功能）
            try:
                conn = sqlite3.connect(dbp)
                # 查询所有用户表（排除系统表，以 sqlite_ 开头的是系统表）
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                total = 0
                for (tname,) in tables:
                    conn.execute(f"DELETE FROM [{tname}]")
                    total += conn.total_changes
                conn.commit()
                conn.close()
                # personality_seed 重置为默认种子（mood_value 已被上面清空）
                db.reset_personality_seed(dbp)
                # 清空 GUI 对话历史 JSON，避免 UI 残留旧对话
                self._clear_conversation_history()
                return {
                    "data_type": "db_result", "cmd": cmd, "status": "ok",
                    "message": (
                        f"人格格式化完成：已清空全部 {len(tables)} 张表，"
                        f"影响 {total} 行，性格已重置为默认"
                    ),
                }
            except Exception as e:
                return {"data_type": "db_result", "cmd": cmd, "status": "error", "message": str(e)}

        elif cmd == "backup":
            try:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_name = f"{os.path.splitext(db_name)[0]}_{ts}.db"
                backup_path = os.path.join(db_dir, backup_name)
                shutil.copy2(dbp, backup_path)
                return {
                    "data_type": "db_result", "cmd": cmd, "status": "ok",
                    "message": f"备份成功: {backup_name}",
                }
            except Exception as e:
                return {"data_type": "db_result", "cmd": cmd, "status": "error", "message": str(e)}

        elif cmd == "restore":
            backup_file = (data.get("params") or {}).get("backup_file", "")
            if not backup_file:
                return {"data_type": "db_result", "cmd": cmd, "status": "error", "message": "未指定备份文件"}
            backup_path = os.path.join(db_dir, backup_file)
            if not os.path.isfile(backup_path):
                return {"data_type": "db_result", "cmd": cmd, "status": "error", "message": f"备份文件不存在: {backup_file}"}
            try:
                shutil.copy2(backup_path, dbp)
                return {
                    "data_type": "db_result", "cmd": cmd, "status": "ok",
                    "message": f"已从 {backup_file} 恢复",
                }
            except Exception as e:
                return {"data_type": "db_result", "cmd": cmd, "status": "error", "message": str(e)}
        else:
            return {"data_type": "db_result", "cmd": cmd, "status": "error", "message": f"未知命令: {cmd}"}


# ════════════════════════════════════════════════════════════════
#  框架桥接（开发者不要修改）
# ════════════════════════════════════════════════════════════════

_node = MyNode()


def process(data):
    """框架入口，由 listener.py 或 __main__ 调用。"""
    return _node.process(data)


# ════════════════════════════════════════════════════════════════
#  __main__ 入口（仅直接运行 python main.py 时执行）
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    input_data = {}
    if len(sys.argv) >= 2:
        try:
            input_data = json.loads(sys.argv[1])
        except Exception:
            pass
    if not input_data:
        try:
            s = sys.stdin.read().strip()
            if s:
                input_data = json.loads(s)
        except Exception:
            pass
    if not input_data:
        print(json.dumps({"code": -1, "error": "no input"}, ensure_ascii=False))
        sys.exit(1)

    result = process(input_data)
    cfg = load_config()

    if isinstance(result, list):
        print(json.dumps({
            "code": 0, "type": cfg.get("output_type", "default"), "data": result,
        }, ensure_ascii=False))
    else:
        # 提取 _port 作为 type（listener 路由用），其余作为 data
        port = result.pop("_port") if "_port" in result else cfg.get("output_type", "default")
        print(json.dumps({
            "code": 0, "type": port, "data": result,
        }, ensure_ascii=False))
