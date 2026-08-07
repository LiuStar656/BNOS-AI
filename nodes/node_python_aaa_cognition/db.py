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

# v3.1(D4) self_info 治理：单 identity 条数上限 + 同 key 相似 value 去重阈值
_SELF_INFO_CAP = 100
_SELF_INFO_DUP_THRESHOLD = 0.85

# 默认身份键（单用户模式）
_IDENTITY_KEY_DEFAULT = "gui:default"


def _calc_decay_date(importance: int) -> str:
    """根据重要性计算过期日期"""
    days = _IMPORTANCE_DAYS.get(importance, 30)
    return (datetime.now() + timedelta(days=days)).isoformat()


# LLM 输出的无意义占位值（表示"无内容可归档"）
_MEANINGLESS_VALUES = {"无", "none", "null", "暂无", "没有", "无内容",
                       "无新内容", "无信息", "nan", "n/a", "-", "—", "无实体"}

# 定位状态描述噪音（LLM 常把"当前定位精度为街区级别，时效在5分钟内"
# 这类系统状态描述误当环境记忆归档，应过滤）
_LOCATION_NOISE_KEYWORDS = (
    "定位精度", "精度为", "时效在", "时效", "街区级别", "城市级别",
    "定位到", "定位", "坐标", "经纬度", "GPS", "基站", "米范围", "米内",
)


def _is_meaningful(text: str) -> bool:
    """判断 LLM 输出的内容是否有实际意义（过滤"无"/"None"/空白等占位值）"""
    if not text:
        return False
    stripped = text.strip().strip("[]")
    if not stripped:
        return False
    return stripped.lower() not in _MEANINGLESS_VALUES


def _is_location_noise(text: str) -> bool:
    """判断是否为定位状态描述噪音（系统状态，非环境记忆）"""
    return any(kw in text for kw in _LOCATION_NOISE_KEYWORDS)


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


def _write_self_info(conn: sqlite3.Connection, identity_key: str, kk: str, vv: str, now: str):
    """self_info 写入治理（v3.1 D4，防 self_info 爆发增长）。

    三层治理：
    1) 去重：同 key 最近 value 相似度 ≥ 阈值 → 跳过（防 LLM 重复输出）
    2) 覆盖：同 key 旧记录删除，只保留最新一条（防单 key 多 value 膨胀）
    3) 上限：写入后超 _SELF_INFO_CAP → 按 id 删除最旧记录
    """
    try:
        # 1) 去重：同 key 已有相似 value → 跳过
        for (existing,) in conn.execute(
            "SELECT value FROM self_info WHERE identity_key=? AND key=? ORDER BY id DESC LIMIT 5",
            (identity_key, kk)).fetchall():
            if existing and _text_similarity(vv, existing) >= _SELF_INFO_DUP_THRESHOLD:
                return
        # 2) 同 key 覆盖：删除该 key 旧记录，只留最新一条
        conn.execute("DELETE FROM self_info WHERE identity_key=? AND key=?",
                     (identity_key, kk))
        conn.execute(
            "INSERT INTO self_info(conversation_id,identity_key,key,value,created_at) "
            "VALUES('default',?,?,?,?)",
            (identity_key, kk, vv, now))
        # 3) 上限：超限删除最旧记录
        over = conn.execute(
            "SELECT COUNT(*)-? FROM self_info WHERE identity_key=?",
            (_SELF_INFO_CAP, identity_key)).fetchone()[0]
        if over > 0:
            conn.execute(
                "DELETE FROM self_info WHERE id IN ("
                " SELECT id FROM self_info WHERE identity_key=? ORDER BY id ASC LIMIT ?)",
                (identity_key, over))
    except Exception:
        pass  # 治理失败不阻塞主流程，回到普通写入兜底


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
                source TEXT DEFAULT NULL,
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
            CREATE TABLE IF NOT EXISTS diaries(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                date TEXT NOT NULL,
                content TEXT NOT NULL,
                mood TEXT,
                created_at TEXT NOT NULL DEFAULT(datetime('now','localtime')),
                identity_key TEXT NOT NULL DEFAULT 'gui:default');
            CREATE TABLE IF NOT EXISTS location_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identity_key TEXT NOT NULL DEFAULT 'gui:default',
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                accuracy REAL DEFAULT 5000,
                city TEXT DEFAULT NULL,
                region TEXT DEFAULT NULL,
                country TEXT DEFAULT NULL,
                street TEXT DEFAULT NULL,
                district TEXT DEFAULT NULL,
                source TEXT NOT NULL DEFAULT 'ip',
                status TEXT DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT(datetime('now','localtime')));
            -- v5.1 角色种子系统：性格向量表（多用户隔离，identity_key 为主键）
            CREATE TABLE IF NOT EXISTS personality_seed(
                identity_key TEXT PRIMARY KEY,
                warmth REAL DEFAULT 0.6,
                playfulness REAL DEFAULT 0.4,
                directness REAL DEFAULT 0.5,
                curiosity REAL DEFAULT 0.5,
                style_description TEXT DEFAULT '',
                preset_name TEXT DEFAULT 'default',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT DEFAULT (datetime('now','localtime')));
            -- v5.1 角色种子系统：动态情绪值表（逐次记录，供 prompt 注入 + GUI 曲线）
            CREATE TABLE IF NOT EXISTS mood_value(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identity_key TEXT NOT NULL DEFAULT 'gui:default',
                mood_value REAL DEFAULT 0.0,
                adjustment REAL DEFAULT 0.0,
                source_mood TEXT,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                created_at TEXT DEFAULT (datetime('now','localtime')));
            CREATE INDEX IF NOT EXISTS idx_ltm_s ON long_term_memory(source);
            CREATE INDEX IF NOT EXISTS idx_um_c ON user_messages(created_at);
            CREATE INDEX IF NOT EXISTS idx_uf_c ON user_facts(category);
            CREATE INDEX IF NOT EXISTS idx_lh_key ON location_history(identity_key, status);
            CREATE INDEX IF NOT EXISTS idx_mv_identity ON mood_value(identity_key);
            CREATE INDEX IF NOT EXISTS idx_mv_time ON mood_value(created_at);""")
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
        for tbl in _TABLES_NEED_CONV_ID + ["mood_trend"]:
            try:
                conn.execute(
                    f"ALTER TABLE [{tbl}] ADD COLUMN identity_key TEXT NOT NULL DEFAULT '{_IDENTITY_KEY_DEFAULT}'")
                conn.commit()
            except sqlite3.OperationalError:
                pass

        # v4.0: 迁移 entity / channel / status 列（环境记忆系统，幂等）
        for col_sql in [
            "ALTER TABLE long_term_memory ADD COLUMN entity TEXT DEFAULT NULL",
            "ALTER TABLE long_term_memory ADD COLUMN channel TEXT DEFAULT 'chat'",
            "ALTER TABLE long_term_memory ADD COLUMN status TEXT DEFAULT 'active'",
        ]:
            try:
                conn.execute(col_sql)
                conn.commit()
            except sqlite3.OperationalError:
                pass

        # v5.0: 迁移旧定位数据到独立的 location_history 表（幂等）
        # 旧数据在 long_term_memory 中 entity='current_location' 且 content 为 JSON
        _migrate_location_history(conn)

        # v5.2: event_summary 增加 source 列（角色种子背景标记，幂等）
        try:
            conn.execute("ALTER TABLE event_summary ADD COLUMN source TEXT DEFAULT NULL")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        # v5.4: 清理冗余表 retrieval_log（从未写入数据，旧库残留直接删除）
        conn.execute("DROP TABLE IF EXISTS retrieval_log")
        conn.commit()

        # v5.3: location_history 增加 street/district 列（街道级逆地理编码，幂等）
        for col_sql in [
            "ALTER TABLE location_history ADD COLUMN street TEXT DEFAULT NULL",
            "ALTER TABLE location_history ADD COLUMN district TEXT DEFAULT NULL",
        ]:
            try:
                conn.execute(col_sql)
                conn.commit()
            except sqlite3.OperationalError:
                pass
    finally:
        conn.close()


def _migrate_location_history(conn: sqlite3.Connection):
    """将 long_term_memory 中旧版定位数据迁移到 location_history 表（幂等）。

    旧版定位数据: entity='current_location' AND channel='location'，
    content 为 JSON（含 latitude/longitude 字段）。迁移完成后删除旧记录，
    避免污染长期记忆与记忆图谱。
    """
    try:
        rows = conn.execute(
            "SELECT id, identity_key, content, created_at, status FROM long_term_memory "
            "WHERE entity='current_location' AND channel='location'"
        ).fetchall()
        migrated = 0
        for row in rows:
            rid, identity_key, content, created_at, status = row
            try:
                data = json.loads(content)
                lat = float(data.get("latitude"))
                lng = float(data.get("longitude"))
            except Exception:
                continue  # 无法解析的内容跳过
            conn.execute(
                "INSERT INTO location_history("
                "identity_key, latitude, longitude, accuracy, city, region, "
                "country, source, status, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    identity_key,
                    lat,
                    lng,
                    float(data.get("accuracy", 5000)),
                    data.get("city"),
                    data.get("region"),
                    data.get("country"),
                    data.get("source", "ip"),
                    status or "active",
                    created_at,
                ),
            )
            conn.execute("DELETE FROM long_term_memory WHERE id=?", (rid,))
            migrated += 1
        if migrated:
            conn.commit()
            print(f"[DB] 已迁移 {migrated} 条旧定位记录到 location_history 表")
    except Exception as e:
        print(f"[DB] 迁移定位数据失败: {e}")


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
        c = data.get("content", "")
        # v5.5: 空 user 消息不入库（避免把 {"data_type":"text","content":"",...}
        # 整段 JSON 序列化后写入 user_messages，产生"仅冒号"占位垃圾）
        if role == "user" and (c is None or str(c).strip() == ""):
            conn.close()
            return
        if not c:
            c = json.dumps(data, ensure_ascii=False)
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
                      ("知识条目", None), ("记忆归档", None), ("用户记忆", None), ("环境记忆", None)]:
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
                        # v3.1(D4) self_info 治理：去重 + 同key覆盖 + 上限
                        _write_self_info(conn, identity_key, kk.strip(), vv.strip(), now)
            elif k == "记忆归档":
                # 向后兼容：旧格式仍写入 user_facts
                tags = parsed.get("归档标签", "")
                entry = f"[{tags}] {val}" if tags else val
                conn.execute(
                    "INSERT INTO user_facts(conversation_id,identity_key,category,content,created_at) VALUES(?,?,?,?,?)",
                    (conversation_id, identity_key, "preference", entry, now))
            elif k == "用户记忆":
                # v4.0: 用户记忆写入 user_facts
                tags = parsed.get("归档标签", "")
                entry = f"[{tags}] {val}" if tags else val
                conn.execute(
                    "INSERT INTO user_facts(conversation_id,identity_key,category,content,created_at) VALUES(?,?,?,?,?)",
                    (conversation_id, identity_key, "preference", entry, now))
            elif k == "环境记忆":
                # v4.0: 环境记忆写入 long_term_memory，支持同实体覆盖
                entity = parsed.get("实体名", "").strip()
                tags = parsed.get("归档标签", "")
                # 过滤无意义值（LLM 可能输出"无"/"None"/空表示无内容）
                if not _is_meaningful(val):
                    continue
                # v5.1: 过滤定位状态描述噪音
                # （LLM 常把"定位精度为街区级别/时效在5分钟内"当环境记忆归档）
                if _is_location_noise(val):
                    continue
                entry = f"[{tags}] {val}" if tags else val
                # 同实体覆盖：标记旧记录为 superseded
                if entity:
                    old = conn.execute(
                        "SELECT id FROM long_term_memory "
                        "WHERE identity_key=? AND entity=? AND status='active'",
                        (identity_key, entity)
                    ).fetchone()
                    if old:
                        conn.execute(
                            "UPDATE long_term_memory SET status='superseded' WHERE id=?",
                            (old[0],))
                # 写入新记录
                conn.execute(
                    "INSERT INTO long_term_memory(conversation_id,identity_key,source,role,content,importance,decay_date,created_at,entity,channel,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (conversation_id, identity_key, "exchange", "memory", entry, 3, _calc_decay_date(3), now, entity or None, "chat", "active"))
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


# ══════════════════════════════════════════════════════════════════
# v5.1 角色种子系统 — 性格种子 / 动态情绪 读写方法
# ══════════════════════════════════════════════════════════════════

# 默认种子值（无记录时的 fallback，与方案 §3.5/§6 Phase 1 一致）
_DEFAULT_PERSONALITY = {
    "warmth": 0.6, "playfulness": 0.4,
    "directness": 0.5, "curiosity": 0.5,
}

# 预设种子表（与方案 §3.1.2 一致）
PERSONALITY_PRESETS = {
    "默认": {
        "warmth": 0.6, "playfulness": 0.4, "directness": 0.5, "curiosity": 0.5,
        "style_description": "你说话自然平衡，像熟悉的朋友。不用敬语，不啰嗦。",
    },
    "温柔型": {
        "warmth": 0.8, "playfulness": 0.5, "directness": 0.3, "curiosity": 0.6,
        "style_description": "你说话关心柔和，不强迫，语气温和，像可靠的亲人。",
    },
    "理性型": {
        "warmth": 0.3, "playfulness": 0.2, "directness": 0.8, "curiosity": 0.5,
        "style_description": "你说话精确简洁，不废话，直接给结论，像冷静的分析师。",
    },
    "毒舌型": {
        "warmth": 0.4, "playfulness": 0.7, "directness": 0.9, "curiosity": 0.6,
        "style_description": "你说话直接调侃，不客套，带点毒舌但分寸到位。",
    },
    "活泼型": {
        "warmth": 0.7, "playfulness": 0.9, "directness": 0.5, "curiosity": 0.8,
        "style_description": "你说话热情好奇，多用感叹号，像元气满满的伙伴。",
    },
}

# 初始背景记忆（写入 event_summary，source='seed'，随真实记忆积累自然淡化）
_SEED_BACKGROUND_MEMORIES = [
    "我刚来到这台电脑上，对用户还不了解",
    "我的名字是阿镜（可由用户修改）",
    "我住在用户的桌面上，能看到屏幕、听到声音",
]


def get_personality(db_path: str, identity_key: str = _IDENTITY_KEY_DEFAULT) -> dict:
    """读取性格向量 + 风格描述；无记录时返回默认种子（fallback）"""
    default = {
        **_DEFAULT_PERSONALITY,
        "style_description": PERSONALITY_PRESETS["默认"]["style_description"],
        "preset_name": "默认",
        "exists": False,
    }
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT warmth, playfulness, directness, curiosity, style_description, preset_name "
                "FROM personality_seed WHERE identity_key=?",
                (identity_key,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return default
        return {
            "warmth": row[0], "playfulness": row[1],
            "directness": row[2], "curiosity": row[3],
            "style_description": row[4] or "",
            "preset_name": row[5] or "默认",
            "exists": True,
        }
    except Exception:
        return default


def save_personality(db_path: str, vector: dict, style_description: str = "",
                     preset_name: str = "默认",
                     identity_key: str = _IDENTITY_KEY_DEFAULT) -> bool:
    """写入/更新性格种子（INSERT OR REPLACE，幂等）"""
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """INSERT INTO personality_seed(
                       identity_key, warmth, playfulness, directness, curiosity,
                       style_description, preset_name, updated_at)
                   VALUES(?,?,?,?,?,?,?, datetime('now','localtime'))
                   ON CONFLICT(identity_key) DO UPDATE SET
                       warmth=excluded.warmth, playfulness=excluded.playfulness,
                       directness=excluded.directness, curiosity=excluded.curiosity,
                       style_description=excluded.style_description,
                       preset_name=excluded.preset_name,
                       updated_at=datetime('now','localtime')""",
                (identity_key,
                 float(vector.get("warmth", 0.6)), float(vector.get("playfulness", 0.4)),
                 float(vector.get("directness", 0.5)), float(vector.get("curiosity", 0.5)),
                 style_description, preset_name),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        return False


def write_seed_background(db_path: str, identity_key: str = _IDENTITY_KEY_DEFAULT) -> int:
    """写入初始背景记忆（source='seed'）到 event_summary 表，幂等。

    背景记忆属于"事件摘要"而非对话 QA，故写入 event_summary 而非 long_term_memory。
    若该用户已存在 source='seed' 记录则跳过（防止格式化后重复累积）。
    Returns: 实际写入条数
    """
    try:
        conn = sqlite3.connect(db_path)
        try:
            existing = conn.execute(
                "SELECT COUNT(*) FROM event_summary WHERE source='seed' AND identity_key=?",
                (identity_key,),
            ).fetchone()[0]
            if existing > 0:
                return 0
            count = 0
            for mem in _SEED_BACKGROUND_MEMORIES:
                conn.execute(
                    """INSERT INTO event_summary(
                           conversation_id, identity_key, summary, source, created_at)
                       VALUES('default', ?, ?, 'seed', datetime('now','localtime'))""",
                    (identity_key, mem),
                )
                count += 1
            conn.commit()
            return count
        finally:
            conn.close()
    except Exception:
        return 0


def get_current_mood(db_path: str, identity_key: str = _IDENTITY_KEY_DEFAULT,
                     conversation_id: str = "default") -> float:
    """读取最新情绪值；无记录时返回 0.0（fallback）"""
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT mood_value FROM mood_value WHERE identity_key=? ORDER BY id DESC LIMIT 1",
                (identity_key,),
            ).fetchone()
        finally:
            conn.close()
        return float(row[0]) if row else 0.0
    except Exception:
        return 0.0


def save_mood_value(db_path: str, new_mood: float, adjustment: float,
                    source_mood: str = "", conversation_id: str = "default",
                    identity_key: str = _IDENTITY_KEY_DEFAULT) -> bool:
    """追加一条情绪值记录（逐次记录，供曲线可视化）"""
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """INSERT INTO mood_value(
                       identity_key, mood_value, adjustment, source_mood, conversation_id)
                   VALUES(?,?,?,?,?)""",
                (identity_key, float(new_mood), float(adjustment), source_mood, conversation_id),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        return False


def reset_personality_seed(db_path: str, identity_key: str = _IDENTITY_KEY_DEFAULT) -> bool:
    """格式化：重置 personality_seed 为默认种子（DELETE + INSERT 默认值）"""
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("DELETE FROM personality_seed WHERE identity_key=?", (identity_key,))
            conn.execute(
                """INSERT INTO personality_seed(
                       identity_key, warmth, playfulness, directness, curiosity,
                       style_description, preset_name)
                   VALUES(?,?,?,?,?,?,?)""",
                (identity_key, 0.6, 0.4, 0.5, 0.5,
                 PERSONALITY_PRESETS["默认"]["style_description"], "默认"),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        return False
