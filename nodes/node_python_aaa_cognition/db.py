"""
数据库模块 - 存储/读取业务
"""
import sqlite3
import json
import threading
import os
from datetime import datetime, timedelta

# 所有需要加 conversation_id 的表
_TABLES_NEED_CONV_ID = [
    "user_messages", "feelings", "event_summary",
    "self_cognition", "other_cognition", "user_facts",
    "self_info", "long_term_memory",
]

# 重要性 → 过期天数
_IMPORTANCE_DAYS = {1: 1, 2: 7, 3: 30, 4: 90, 5: 365}

# 情感数值映射
_MOOD_VALUES = {
    "开心": 5, "兴奋": 5, "喜悦": 5,
    "好奇": 4, "期待": 4, "平静": 3,
    "疲惫": 2, "无聊": 2, "难过": 1,
    "悲伤": 1, "愤怒": 1, "焦虑": 1,
    "恐惧": 1,
}

# 去重相似度阈值
_SIMILARITY_THRESHOLD = 0.80

# 默认身份键（单用户模式）
_IDENTITY_KEY_DEFAULT = "gui:default"


def _calc_decay_date(importance: int) -> str:
    """根据重要性计算过期日期"""
    days = _IMPORTANCE_DAYS.get(importance, 30)
    return (datetime.now() + timedelta(days=days)).isoformat()


def _text_similarity(a: str, b: str) -> float:
    """字符级 Jaccard 相似度，轻量无依赖"""
    if not a or not b:
        return 0.0
    set_a, set_b = set(a), set(b)
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


def _dedup_and_merge(
    table: str,
    conv_id: str,
    identity_key: str,
    new_content: str,
    conn: sqlite3.Connection,
    importance: int = 3,
    column: str = "content",
) -> str | None:
    """去重合并。返回 None=不写, str=写入的实际内容"""
    old = conn.execute(
        f"SELECT [{column}] FROM [{table}] WHERE conversation_id=? AND identity_key=? ORDER BY id DESC LIMIT 1",
        (conv_id, identity_key),
    ).fetchone()
    if not old:
        return new_content

    old_content = old[0]
    if not old_content:
        return new_content

    sim = _text_similarity(new_content, old_content)
    if sim > _SIMILARITY_THRESHOLD:
        return None

    if importance >= 4 and sim > 0.5:
        return f"{old_content}；补充：{new_content}"

    return new_content


def _increment_certainty(key: str, conn: sqlite3.Connection) -> int:
    """增加确认次数；返回当前次数"""
    conn.execute(
        """INSERT INTO fixed_cognition(key, value) VALUES(?, '1')
           ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
           updated_at = datetime('now','localtime')""",
        (f"certainty_{key}",),
    )
    row = conn.execute(
        "SELECT value FROM fixed_cognition WHERE key = ?",
        (f"certainty_{key}",),
    ).fetchone()
    return int(row[0]) if row else 0


def _aggregate_mood(db_path: str, conv_id: str, period: str = "daily", identity_key: str = None):
    """聚合指定周期的情感数据到 mood_trend 表"""
    identity_key = identity_key or _IDENTITY_KEY_DEFAULT
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """SELECT mood, COUNT(*) as cnt FROM feelings
               WHERE conversation_id=? AND identity_key=? AND mood IS NOT NULL AND mood != ''
               AND date(created_at) = date('now')
               GROUP BY mood ORDER BY cnt DESC""",
            (conv_id, identity_key),
        ).fetchall()
        if not rows:
            return

        total = sum(r[1] for r in rows)
        dominant = rows[0][0]
        avg_value = sum(_MOOD_VALUES.get(r[0], 3) * r[1] for r in rows) / total

        conn.execute(
            """INSERT INTO mood_trend(conversation_id, identity_key, period, period_start,
               avg_mood_value, dominant_mood, sample_count)
               VALUES(?, ?, ?, date('now'), ?, ?, ?)""",
            (conv_id, identity_key, period, avg_value, dominant, total),
        )
        conn.commit()
    finally:
        conn.close()


def ensure(db_path):
    """初始化数据库（幂等）— 建表 + 迁移 conversation_id 列 + fixed_cognition + v2.0 增强"""
    d = os.path.dirname(db_path)
    if d:
        os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        # 新表直接带 conversation_id 列
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS user_messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT(datetime('now')));
            CREATE TABLE IF NOT EXISTS feelings(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                mood TEXT,
                thought TEXT,
                created_at TEXT NOT NULL DEFAULT(datetime('now')));
            CREATE TABLE IF NOT EXISTS event_summary(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT(datetime('now')));
            CREATE TABLE IF NOT EXISTS self_cognition(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT(datetime('now')));
            CREATE TABLE IF NOT EXISTS other_cognition(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT(datetime('now')));
            CREATE TABLE IF NOT EXISTS user_facts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT(datetime('now')));
            CREATE TABLE IF NOT EXISTS self_info(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT(datetime('now')));
            CREATE TABLE IF NOT EXISTS long_term_memory(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                source TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT(datetime('now')));
            CREATE TABLE IF NOT EXISTS fixed_cognition(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now','localtime')));
            CREATE TABLE IF NOT EXISTS mood_trend(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                period TEXT NOT NULL,
                period_start TEXT NOT NULL,
                avg_mood_value REAL DEFAULT 3.0,
                dominant_mood TEXT,
                sample_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime')));
            CREATE TABLE IF NOT EXISTS retrieval_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                keywords TEXT NOT NULL,
                result_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime')));
            CREATE TABLE IF NOT EXISTS diaries(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                date TEXT NOT NULL,
                content TEXT NOT NULL,
                mood TEXT,
                created_at TEXT NOT NULL DEFAULT(datetime('now','localtime')),
                identity_key TEXT NOT NULL DEFAULT 'gui:default');
            CREATE INDEX IF NOT EXISTS idx_ltm_s ON long_term_memory(source);
            CREATE INDEX IF NOT EXISTS idx_um_c ON user_messages(created_at);
            CREATE INDEX IF NOT EXISTS idx_uf_c ON user_facts(category);""")
        conn.commit()

        # v1: 迁移 conversation_id 列（幂等）
        for tbl in _TABLES_NEED_CONV_ID:
            try:
                conn.execute(f"ALTER TABLE [{tbl}] ADD COLUMN conversation_id TEXT NOT NULL DEFAULT 'default'")
                conn.commit()
            except sqlite3.OperationalError:
                pass

        # v2.0: 迁移 importance / decay_date / source_confidence 列（幂等）
        for col_sql in [
            "ALTER TABLE long_term_memory ADD COLUMN importance INTEGER DEFAULT 3",
            "ALTER TABLE long_term_memory ADD COLUMN decay_date TEXT DEFAULT NULL",
            "ALTER TABLE long_term_memory ADD COLUMN source_confidence INTEGER DEFAULT 3",
        ]:
            try:
                conn.execute(col_sql)
                conn.commit()
            except sqlite3.OperationalError:
                pass

        # v3.0: 迁移 identity_key 列（幂等），默认 "gui:default"
        for tbl in _TABLES_NEED_CONV_ID + ["mood_trend", "retrieval_log"]:
            try:
                conn.execute(
                    f"ALTER TABLE [{tbl}] ADD COLUMN identity_key TEXT NOT NULL DEFAULT '{_IDENTITY_KEY_DEFAULT}'")
                conn.commit()
            except sqlite3.OperationalError:
                pass
    finally:
        conn.close()


def write_async(data, db_path, role):
    """并行写 DB（不阻塞调用方）"""
    threading.Thread(target=_write, args=(data, db_path, role), daemon=True).start()


def _write(data, db_path, role):
    """内部同步写（v3.0：去重 + 重要性/decay + identity_key）"""
    try:
        conv_id = data.get("conversation_id") or data.get("_session_id", "default")
        identity_key = data.get("identity_key", _IDENTITY_KEY_DEFAULT)
        conn = sqlite3.connect(db_path)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c = data.get("content", "") or json.dumps(data, ensure_ascii=False)
        importance = data.get("importance", 3)
        if role == "user":
            # 去重
            deduped = _dedup_and_merge("user_messages", conv_id, identity_key, c, conn, importance)
            if deduped is None:
                conn.close()
                return
            conn.execute(
                "INSERT INTO user_messages(conversation_id,identity_key,role,content,created_at) VALUES(?,?,?,?,?)",
                (conv_id, identity_key, "user", deduped, now))
        elif role == "assistant":
            conn.execute(
                "INSERT INTO user_messages(conversation_id,identity_key,role,content,created_at) VALUES(?,?,?,?,?)",
                (conv_id, identity_key, "assistant", c, now))
        elif role == "tool":
            conn.execute(
                "INSERT INTO long_term_memory(conversation_id,identity_key,source,role,content,importance,decay_date,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (conv_id, identity_key, "grok", "tool", c, importance, _calc_decay_date(importance), now))
        conn.commit()
        conn.close()
    except Exception:
        pass


def write_parsed_async(parsed, db_path, conversation_id="default", user_input="", identity_key=None):
    """并行写解析结果到各表"""
    kwargs = {"user_input": user_input, "identity_key": identity_key or _IDENTITY_KEY_DEFAULT}
    threading.Thread(target=_write_parsed, args=(parsed, db_path, conversation_id), kwargs=kwargs, daemon=True).start()


def _write_parsed(parsed, db_path, conversation_id, user_input="", identity_key=None):
    """将节标记结果分别写入对应表（v3.0：去重 + importance 解析 + MemOS 增量 + identity_key）"""
    identity_key = identity_key or _IDENTITY_KEY_DEFAULT
    try:
        conn = sqlite3.connect(db_path)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for k, v in [("自然回复", "assistant"), ("心情", None), ("想法", None), ("事件摘要", None),
                      ("自我认知", None), ("他人认知", None), ("用户信息", None), ("自我信息", None),
                      ("知识条目", None)]:
            val = parsed.get(k, "")
            if not val:
                continue

            # 提取 importance（从解析结果中取，如 "事件摘要_importance"）
            importance = parsed.get(f"{k}_importance", 3)

            if k == "自然回复":
                conn.execute(
                    "INSERT INTO user_messages(conversation_id,identity_key,role,content,created_at) VALUES(?,?,?,?,?)",
                    (conversation_id, identity_key, "assistant", val, now))
                # 合并用户输入 + AI 回复写入 long_term_memory（供 MemOS 检索）
                if user_input:
                    combined = f"user: {user_input}\nassistant: {val}"
                    conn.execute(
                        "INSERT INTO long_term_memory(conversation_id,identity_key,source,role,content,importance,decay_date,created_at) VALUES(?,?,?,?,?,?,?,?)",
                        (conversation_id, identity_key, "exchange", "combined", combined, 3, _calc_decay_date(3), now))
            elif k == "心情":
                conn.execute(
                    "INSERT INTO feelings(conversation_id,identity_key,mood,thought,created_at) VALUES(?,?,?,?,?)",
                    (conversation_id, identity_key, val, parsed.get("想法", ""), now))
            elif k == "事件摘要":
                deduped = _dedup_and_merge("event_summary", conversation_id, identity_key, val, conn, importance, column="summary")
                if deduped is None:
                    continue
                conn.execute(
                    "INSERT INTO event_summary(conversation_id,identity_key,summary,created_at) VALUES(?,?,?,?)",
                    (conversation_id, identity_key, deduped, now))
            elif k == "自我认知":
                # 检查是否带 [固定] 标记 → 写入 fixed_cognition 表
                if val.startswith("[固定]") or val.startswith("[fixed]"):
                    clean = val.split("]", 1)[1].strip() if "]" in val else val
                    conn.execute(
                        "INSERT INTO fixed_cognition(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now','localtime')",
                        ("self_cognition", clean))
                # 直接 INSERT，不去重合并（像 adaptive-agent-architecture 那样）
                conn.execute(
                    "INSERT INTO self_cognition(conversation_id,identity_key,content,created_at) VALUES(?,?,?,?)",
                    (conversation_id, identity_key, val, now))
                _increment_certainty("self_cognition", conn)
            elif k == "他人认知":
                # 直接 INSERT，不去重合并（像 adaptive-agent-architecture 那样）
                conn.execute(
                    "INSERT INTO other_cognition(conversation_id,identity_key,content,created_at) VALUES(?,?,?,?)",
                    (conversation_id, identity_key, val, now))
                _increment_certainty("other_cognition", conn)
            elif k == "用户信息":
                for pair in val.split(","):
                    pair = pair.strip()
                    if pair:
                        conn.execute(
                            "INSERT INTO user_facts(conversation_id,identity_key,category,content,created_at) VALUES(?,?,?,?,?)",
                            (conversation_id, identity_key, "background", pair, now))
            elif k == "自我信息":
                for item in val.split(","):
                    item = item.strip()
                    if "=" in item:
                        kk, vv = item.split("=", 1)
                        conn.execute(
                            "INSERT INTO self_info(conversation_id,identity_key,key,value,created_at) VALUES(?,?,?,?,?)",
                            (conversation_id, identity_key, kk.strip(), vv.strip(), now))
            elif k == "记忆归档":
                tags = parsed.get("归档标签", "")
                entry = f"[{tags}] {val}" if tags else val
                conn.execute(
                    "INSERT INTO user_facts(conversation_id,identity_key,category,content,created_at) VALUES(?,?,?,?,?)",
                    (conversation_id, identity_key, "preference", entry, now))
        conn.commit()
        conn.close()
    except Exception:
        pass


def g(conn, table, column):
    """获取表中最新一条记录的指定列"""
    r = conn.execute(f"SELECT {column} FROM {table} ORDER BY id DESC LIMIT 1").fetchone()
    return r[0] if r else ""


def g_where(conn, table, column, conv_id):
    """按 conversation_id 获取表中最新一条记录的指定列"""
    r = conn.execute(
        f"SELECT {column} FROM {table} WHERE conversation_id=? ORDER BY id DESC LIMIT 1",
        (conv_id,)
    ).fetchone()
    return r[0] if r else ""


def g_where_identity(conn, table, column, conv_id, identity_key):
    """按 conversation_id + identity_key 获取表中最新一条记录的指定列"""
    r = conn.execute(
        f"SELECT {column} FROM {table} WHERE conversation_id=? AND identity_key=? ORDER BY id DESC LIMIT 1",
        (conv_id, identity_key)
    ).fetchone()
    return r[0] if r else ""
