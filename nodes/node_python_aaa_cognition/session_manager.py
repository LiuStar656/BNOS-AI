"""
SessionManager 会话边界管理（v4.0）

切换会话时对旧会话生成结构化摘要（复用 review 文件通道），
新会话启动时加载最近会话摘要，注入 Prefetch 上下文。

通道说明：
- 摘要求求写 output_review_prompt.json（复用 Background Review 的节点间通道，
  LLM 节点无需改动），request_id 带 "session_summary_" 前缀；
- 回执在 main._on_review_response 中按前缀分流到 _on_session_summary_response。

约束：后台线程只做 sqlite 读 + 写文件，不碰 MemOS 语义模型。
"""
import json
import sqlite3
import threading
import time

# 建表语句（幂等；与 db.ensure() 保持一致，SessionManager 查询前兜底建表）
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS session_summaries(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    identity_key TEXT NOT NULL DEFAULT 'gui:default',
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT(datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_ss_identity ON session_summaries(identity_key);
CREATE INDEX IF NOT EXISTS idx_ss_session ON session_summaries(session_id);
"""


class SessionManager:
    """会话边界管理：切换时生成旧会话摘要，新会话加载历史摘要"""

    def __init__(self):
        self._current_session_id = None

    def start_session(self, session_id: str, identity_key: str, db_path: str):
        """开始/切换会话：若来自其他会话则先触发旧会话摘要（异步）"""
        if self._current_session_id and self._current_session_id != session_id:
            self._request_summary(self._current_session_id, identity_key, db_path)
        self._current_session_id = session_id

    # ── 摘要请求（异步，复用 review 通道）──────────────────────
    def _request_summary(self, session_id, identity_key, db_path):
        """异步请求会话摘要"""
        def _run():
            try:
                conv = self._load_messages(session_id, identity_key, db_path)
                if not conv:
                    return
                prompt = self._build_summary_prompt(conv)
                self._write_summary_prompt_file(prompt, identity_key, session_id)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def _build_summary_prompt(self, conv):
        lines = [f"[{'用户' if m['role'] == 'user' else 'AI'}]: "
                 f"{(m.get('content') or '')[:100]}".replace("\n", " ")
                 for m in conv[-20:]]
        return ("你是记忆管理员。为以下会话生成一段结构化摘要，"
                "输出纯文本，不要 JSON，不超过 200 字，"
                "涵盖：对话主题、用户表现出的偏好/身份信息、双方结论。\n\n"
                + "\n".join(lines))

    def _write_summary_prompt_file(self, prompt, identity_key, session_id):
        """写 output_review_prompt.json（复用 review 通道）。
        session_id 编码进 request_id（LLM 节点回执时透传 request_id），
        保证回执能定位到被摘要的旧会话。"""
        try:
            from config import resolve
            path = resolve("./output_review_prompt.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "data_type": "prompt",
                    "content": prompt,
                    "source": "review",
                    "request_id": f"session_summary_{session_id}_{int(time.time() * 1000)}",
                    "identity_key": identity_key,
                    "user_id": "",
                    "session_id": session_id,
                }, f, ensure_ascii=False)
        except Exception:
            pass

    @staticmethod
    def parse_summary_rid(rid: str) -> str:
        """从 session_summary_{session_id}_{ts} 解析 session_id（session_id 可含下划线）"""
        parts = rid.split("_")
        if len(parts) >= 4 and parts[0] == "session" and parts[1] == "summary":
            return "_".join(parts[2:-1])
        return ""

    def _load_messages(self, session_id, identity_key, db_path):
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT role, content FROM user_messages WHERE conversation_id=? "
                "AND identity_key=? AND role IN ('user','assistant') "
                "ORDER BY id DESC LIMIT 20", (session_id, identity_key)).fetchall()
            return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
        finally:
            conn.close()

    # ── 历史摘要读取（供 Prefetch 上下文注入）──────────────────
    def get_session_history(self, identity_key, db_path, limit=3):
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("BEGIN")
            conn.executescript(_CREATE_TABLE_SQL)
            conn.commit()
            rows = conn.execute(
                "SELECT session_id, summary, created_at FROM session_summaries "
                "WHERE identity_key=? ORDER BY created_at DESC LIMIT ?",
                (identity_key, limit)).fetchall()
            return [{"session_id": r[0], "summary": r[1], "created_at": r[2]}
                    for r in rows]
        except Exception:
            return []
        finally:
            conn.close()
