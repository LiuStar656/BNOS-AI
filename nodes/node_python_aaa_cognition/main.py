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
import shutil
import sqlite3
import threading
from datetime import datetime

from config import load_config, resolve
import db
import prompt as pt
import prompt_retrieval as ptr
import prompt_tool as ptoo
import parser as psr
import memos
import diary


# ════════════════════════════════════════════════════════════════
#  ★ 开发者在此类中编写所有业务逻辑 — 其他代码不要修改 ★
# ════════════════════════════════════════════════════════════════

_IDENTITY_KEY_DEFAULT = "gui:default"

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
        # 启动时预加载 MemOS 语义模型到内存
        memos.preload()

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

        # LLM 响应（data_type: "text"/"parsed", source: "llm"）
        if data_type in ("text", "parsed") and source == "llm":
            return self._on_parsed(data, dbp, cfg)

        # GUI 文本输入（data_type: "text", source: "gui"）
        if data_type == "text":
            return self._on_text(data, dbp)

        # 工具执行结果
        if data_type == "tool_result":
            return self._on_tool_result(data, dbp)

        # DB 管理命令
        if data_type == "db_command":
            return self._on_db_command(data, dbp)

        return {"_port": "default", "status": "noop"}

    # ── 用户文本 / ASR / 视觉 / 环境输入 ──────────────────────
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

        # Diary 检测：次日首条对话触发写前一天日记
        today = datetime.now().strftime("%Y-%m-%d")
        diary.check_and_write_diary(today, dbp)

        attachments = data.get("attachments", [])

        # 第一轮：薄 prompt（skip_retrieval=True）
        ctx = self._gather_context(
            data.get("content", ""), dbp, attachments, conv_id,
            skip_retrieval=True, identity_key=identity_key,
        )

        # 缓存当前上下文，供第二轮检索使用
        rid = data.get("request_id", "")
        self._pending_contexts[rid] = {
            "user_text": data.get("content", ""),
            "attachments": attachments,
            "conv_id": conv_id,
            "identity_key": identity_key,
        }

        return {
            "_port": "prompt", "data_type": "prompt", "content": pt.build(ctx),
            "request_id": rid,
        }

    # ── LLM 节标记回执 ─────────────────────────────────────────
    def _on_parsed(self, data, dbp, cfg):
        db.ensure(dbp)
        conv_id = data.get("conversation_id") or data.get("_session_id", "default")
        content = data.get("content", "")
        parsed = psr.parse_llm_output(content)
        rid = data.get("request_id", "")

        # ── 三选一决策 ─────────────────────────────────
        tool_call = parsed.get("工具调用", [])
        retrieval_keywords = (parsed.get("语意检索") or "").strip()
        pending = self._pending_contexts.pop(rid, None)
        user_text = pending.get("user_text", "") if pending else ""
        identity_key = pending.get("identity_key", _IDENTITY_KEY_DEFAULT) if pending else _IDENTITY_KEY_DEFAULT

        # ③ 工具调用（当前功能尚未开放）
        if tool_call:
            return {
                "_port": "reply", "data_type": "reply",
                "content": "抱歉，工具调用功能目前尚未开放。",
                "request_id": rid,
            }

        # ② 检索记忆 — 跑 MemOS 语义检索 → 第二轮 prompt → 再次发给 LLM
        if retrieval_keywords and pending:
            memos_results = memos.retrieve(
                retrieval_keywords, top_k=5, db_path=dbp, identity_key=identity_key,
            )
            if memos_results:
                ctx2 = self._gather_context(
                    pending["user_text"], dbp, pending["attachments"],
                    pending["conv_id"], retrieval_override=memos_results,
                    identity_key=identity_key,
                )
                new_rid = f"{rid}_r2"
                self._pending_contexts[new_rid] = pending
                return {
                    "_port": "prompt", "data_type": "prompt",
                    "content": ptr.build_second(ctx2),
                    "request_id": new_rid,
                }
            # 检索无结果 → fall through 到直接回复

        # ① 直接回复 — 正常写库 + 输出
        db.write_parsed_async(parsed, dbp, conversation_id=conv_id, user_input=user_text, identity_key=identity_key)

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
                identity_key=identity_key,
            )
            return {
                "_port": "prompt", "data_type": "prompt",
                "content": pt.build(ctx3),
                "request_id": f"{rid}_reflection",
            }

        # ── 异步重建 MemOS 索引 + 知识图谱 + 情感趋势 ────
        threading.Thread(target=memos.rebuild_index, args=(dbp,), daemon=True).start()
        threading.Thread(target=memos.rebuild_knowledge_index, args=(dbp,), daemon=True).start()
        threading.Thread(
            target=db._aggregate_mood, args=(dbp, conv_id), daemon=True,
            kwargs={"identity_key": identity_key},
        ).start()

        # ── 输出 reply + knowledge + logseq ─────────────
        outputs = []
        if parsed.get("自然回复"):
            outputs.append({
                "_port": "reply", "data_type": "reply",
                "content": psr.inject_mood_tag(parsed["自然回复"], parsed.get("心情", "")),
                "request_id": rid,
            })
        if parsed.get("记忆归档"):
            outputs.append({
                "_port": "default", "data_type": "knowledge",
                "content": parsed["记忆归档"],
                "tags": parsed.get("归档标签", ""),
                "request_id": rid,
            })
            # ── Logseq 输出：记忆归档 + 向量关联 ────────────
            logseq_related = []
            try:
                raw_results = memos.retrieve_raw(parsed["记忆归档"], top_k=5, identity_key=identity_key)
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
                "content": parsed["记忆归档"],
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

    # ── 上下文收集（v3.0 重写：加入 identity_key 隔离） ─────────
    def _gather_context(self, user_text, dbp, attachments=None, conv_id="default",
                         skip_retrieval=False, retrieval_override=None,
                         reflection_override=None, identity_key=_IDENTITY_KEY_DEFAULT):
        """收集上下文（v3.0：MemOS + 反思 + 情感趋势 + identity_key 隔离）。

        Args:
            skip_retrieval: 第一轮「薄 prompt」时不检索
            retrieval_override: 第二轮「带检索结果」时直接注入
            reflection_override: 自我反思时注入历史认知
            identity_key: 身份键，隔离不同用户的记忆/认知/画像
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
            oc = db.g_where_identity(conn, "other_cognition", "content", conv_id, identity_key)

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

            ui = "\n".join(x[0] for x in conn.execute(
                "SELECT content FROM user_facts WHERE category='background' AND conversation_id=? AND identity_key=? ORDER BY id DESC LIMIT 5",
                (conv_id, identity_key)
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

        # 4. MemOS 检索
        memos_top5 = ""
        if retrieval_override is not None:
            memos_top5 = retrieval_override    # 第二轮：注入精确检索结果
        elif not skip_retrieval:
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
        return {
            "identity_key": identity_key,
            "fixed_cognition": fixed_context,
            "self_cognition": sc, "other_cognition": oc, "recent_feelings": feel,
            "user_text": user_text, "current_date": now.strftime("%Y-%m-%d"),
            "current_time": now.strftime("%H:%M:%S"), "current_state": "清醒",
            "history_summary": hs, "user_info": ui, "self_info": si,
            "mood_trend": mood_trend,
            "memos_top5": memos_top5,
            "attachment_context": attachment_context,
            "reflection_prompt": reflection_override or "",
        }

    # ── 对话切换 ────────────────────────────────────────────
    def _on_switch_conversation(self, data):
        conv_id = data.get("conversation_id", "default")
        self._current_conversation_id = conv_id
        self._pending_contexts.clear()
        return {
            "_port": "default", "data_type": "switch_conversation_ack",
            "status": "ok", "conversation_id": conv_id,
        }

    # ── DB 管理命令（clear / backup / restore）───────────
    def _on_db_command(self, data, dbp):
        cmd = data.get("cmd", "")
        db_dir = os.path.dirname(dbp)
        db_name = os.path.basename(dbp)

        if not os.path.isfile(dbp):
            return {"data_type": "db_result", "cmd": cmd, "status": "error", "message": "数据库文件不存在"}

        if cmd == "clear":
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
                return {
                    "data_type": "db_result", "cmd": cmd, "status": "ok",
                    "message": f"已清空 {len(tables)} 张用户表，影响 {total} 行",
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
