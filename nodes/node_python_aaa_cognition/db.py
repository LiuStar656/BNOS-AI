"""
数据库模块 - 存储/读取业务
"""
import sqlite3
import json
import re
import threading
import os
from datetime import datetime, timedelta

# v7.1 阶段0-bug2：实体-属性一致性校验器（用户原话抽取 + LLM 摘要冲突修正）
import entity_attr_checker

# 所有需要加 conversation_id 的表
_TABLES_NEED_CONV_ID = [
    "user_messages", "feelings", "event_summary",
    "self_cognition", "other_cognition", "user_facts",
    "self_info", "long_term_memory",
]

# v6.0 消息池实验（多用户交互）：需要 user_id 归属列的表。
# 空字符串 '' = AI 自己 / 匿名 / 全局认知兜底。
_TABLES_NEED_USER_ID = [
    "user_messages", "event_summary", "other_cognition", "user_facts",
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

# v7.1 阶段0-bug2：LLM 摘要类节（写入前过实体-属性一致性校验，
# 冲突类型词用已知绑定修正——防事件摘要互相污染导致实体属性漂移）
_LLM_SUMMARY_SECTIONS = {
    "事件摘要", "自我认知", "他人认知", "用户记忆", "环境记忆", "记忆归档",
}

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
    user_id: str = "",
) -> str | None:
    """去重合并。返回 None=不写, str=写入的实际内容

    v6.0：增加 user_id 维度 —— 同一用户（user_id）内最近一条才参与去重，
    避免多用户同会话时把不同用户的相似消息误合并。
    """
    if user_id:
        old = conn.execute(
            f"SELECT [{column}] FROM [{table}] WHERE conversation_id=? AND identity_key=? AND user_id=? ORDER BY id DESC LIMIT 1",
            (conv_id, identity_key, user_id),
        ).fetchone()
    else:
        old = conn.execute(
            f"SELECT [{column}] FROM [{table}] WHERE conversation_id=? AND identity_key=? AND user_id='' ORDER BY id DESC LIMIT 1",
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


# 名字提取模式（v8.4 自然起名）：只认显式自我介绍句式，避免把
# "我是一个温柔的人"这类性格描述误提取为名字
_NAME_PATTERNS = (
    r"(?:我叫|我的名字(?:是|叫)?|我名字是|你可以叫我|请叫我)"
    r"\s*[「『\"'“]?\s*([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9]{0,9})",
)


def _maybe_capture_name(conn: sqlite3.Connection, identity_key: str, val: str) -> None:
    """名字自然生成：自我认知含显式自我介绍句式且当前名字为空时，提取并固化。

    一旦有名字（用户设置或自我起名）不再覆盖；名字写入 personality_seed.name，
    此后由 prompt 顶部固定注入（酒馆 Character Card name 式，永不丢失）。
    """
    try:
        for pat in _NAME_PATTERNS:
            m = re.search(pat, val)
            if not m:
                continue
            name = m.group(1).strip()
            if not name:
                return
            row = conn.execute(
                "SELECT name FROM personality_seed WHERE identity_key=?",
                (identity_key,),
            ).fetchone()
            if row and (row[0] or "").strip():
                return  # 已有名字，不覆盖
            conn.execute(
                """INSERT INTO personality_seed(identity_key, name, updated_at)
                   VALUES(?,?, datetime('now','localtime'))
                   ON CONFLICT(identity_key) DO UPDATE SET
                       name=excluded.name, updated_at=datetime('now','localtime')""",
                (identity_key, name),
            )
            return
    except Exception:
        pass


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
    """初始化数据库（幂等）— 建表 + 迁移 conversation_id 列 + v2.0 增强"""
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
            -- v8.x 人格注入双开关：anchor_enabled（五档动作级锚点）/ instruction_enabled（通用激活指令）
            -- v8.4 AI 名字：name 列（酒馆 Character Card name 式，固定字段永不丢）
            CREATE TABLE IF NOT EXISTS personality_seed(
                identity_key TEXT PRIMARY KEY,
                name TEXT DEFAULT '',
                warmth REAL DEFAULT 0.6,
                playfulness REAL DEFAULT 0.4,
                directness REAL DEFAULT 0.5,
                curiosity REAL DEFAULT 0.5,
                style_description TEXT DEFAULT '',
                preset_name TEXT DEFAULT 'default',
                anchor_enabled INTEGER DEFAULT 1,
                instruction_enabled INTEGER DEFAULT 0,
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
            CREATE INDEX IF NOT EXISTS idx_mv_time ON mood_value(created_at);
            -- v6.6 数据采集 P0-1：记忆检索命中日志表（决策 id → 命中记忆条目）
            CREATE TABLE IF NOT EXISTS memory_usage(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identity_key TEXT NOT NULL DEFAULT 'gui:default',
                decision_id TEXT,
                entry_id INTEGER,
                table_name TEXT,
                score REAL,
                adopted INTEGER DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT(datetime('now','localtime')));
            CREATE INDEX IF NOT EXISTS idx_mu_decision ON memory_usage(decision_id);
            -- v6.6 数据采集 P0-2：静默期间的认知更新日志表（静默≠无认知）
            CREATE TABLE IF NOT EXISTS silent_cognition(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identity_key TEXT NOT NULL DEFAULT 'gui:default',
                decision_id TEXT,
                thought TEXT,
                cognition_written INTEGER DEFAULT 0,
                sections TEXT,
                created_at TEXT NOT NULL DEFAULT(datetime('now','localtime')));
            -- v7.0 兴趣门控：向量判定日志表（检测文本 + 兴趣值，平台进程写入）
            CREATE TABLE IF NOT EXISTS interest_judgment(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identity_key TEXT NOT NULL DEFAULT 'gui:default',
                round_no INTEGER,
                message_seq INTEGER,
                detected_text TEXT,
                anchor_text TEXT,
                interest_value REAL,
                passed INTEGER DEFAULT 0,
                reason TEXT,
                created_at TEXT NOT NULL DEFAULT(datetime('now','localtime')));
            CREATE INDEX IF NOT EXISTS idx_ij_identity ON interest_judgment(identity_key);
            -- v4.0 会话边界管理：会话摘要表（SessionManager 写入，供跨会话结构化记忆）
            CREATE TABLE IF NOT EXISTS session_summaries(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                identity_key TEXT NOT NULL DEFAULT 'gui:default',
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT(datetime('now', 'localtime')));
            CREATE INDEX IF NOT EXISTS idx_ss_identity ON session_summaries(identity_key);
            CREATE INDEX IF NOT EXISTS idx_ss_session ON session_summaries(session_id);""")
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

        # v6.0: 迁移 user_id 列（消息池多用户实验，幂等）。
        # ''  = AI 自己 / 匿名 / 全局认知兜底；具体值 = 该条数据由哪个用户触发。
        for tbl in _TABLES_NEED_USER_ID:
            try:
                conn.execute(
                    f"ALTER TABLE [{tbl}] ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
                conn.commit()
            except sqlite3.OperationalError:
                pass

        # v7.1 阶段0-bug2：实体-属性绑定表（一致性校验数据源）
        entity_attr_checker.ensure_table(conn)
        conn.commit()

        # v8.x 人格注入双开关：老库 personality_seed 补列（幂等）。
        # 默认 anchor_enabled=1 / instruction_enabled=0 = 生产现有形态（只锚点）。
        for col_sql in [
            "ALTER TABLE personality_seed ADD COLUMN anchor_enabled INTEGER DEFAULT 1",
            "ALTER TABLE personality_seed ADD COLUMN instruction_enabled INTEGER DEFAULT 0",
            # v8.4 AI 名字：酒馆 Character Card name 式固定字段
            "ALTER TABLE personality_seed ADD COLUMN name TEXT DEFAULT ''",
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
    """内部同步写（v3.0：去重 + 重要性/decay + identity_key；v6.0：+ user_id）"""
    try:
        conv_id = data.get("conversation_id") or data.get("_session_id", "default")
        identity_key = data.get("identity_key", _IDENTITY_KEY_DEFAULT)
        user_id = str(data.get("user_id", "") or "")
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
            # 去重（v6.0：按 user_id 区分归属，避免多用户消息互相误合并）
            deduped = _dedup_and_merge(
                "user_messages", conv_id, identity_key, c, conn, importance, user_id=user_id)
            if deduped is None:
                conn.close()
                return
            conn.execute(
                "INSERT INTO user_messages(conversation_id,identity_key,role,content,user_id,created_at) VALUES(?,?,?,?,?,?)",
                (conv_id, identity_key, "user", deduped, user_id, now))
            # v7.1 阶段0-bug2：用户原话是实体-属性绑定的可靠事实源，
            # 抽取「实体→动物类型」强绑定写入 entity_attrs（防 LLM 摘要漂移）
            entity_attr_checker.record_statement(deduped, conn, identity_key)
        elif role == "assistant":
            conn.execute(
                "INSERT INTO user_messages(conversation_id,identity_key,role,content,user_id,created_at) VALUES(?,?,?,?,?,?)",
                (conv_id, identity_key, "assistant", c, user_id, now))
        elif role == "tool":
            conn.execute(
                "INSERT INTO long_term_memory(conversation_id,identity_key,source,role,content,importance,decay_date,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (conv_id, identity_key, "grok", "tool", c, importance, _calc_decay_date(importance), now))
        conn.commit()
        conn.close()
    except Exception:
        pass


def write_parsed_async(parsed, db_path, conversation_id="default", user_input="", identity_key=None, user_id="", skip_empty_other=False):
    """并行写解析结果到各表

    Args:
        skip_empty_other: v6.6 P0-2——消息池批量模式下 user_id 为空（回应对象
            为群聊/多条/无对象/自认知）时跳过 other_cognition 写入，杜绝空键
            污染认知矩阵；GUI 1对1 路径保持 False（空 user_id 是"全局认知兜底"）。
    """
    kwargs = {"user_input": user_input, "identity_key": identity_key or _IDENTITY_KEY_DEFAULT,
              "user_id": user_id, "skip_empty_other": skip_empty_other}
    threading.Thread(target=_write_parsed, args=(parsed, db_path, conversation_id), kwargs=kwargs, daemon=True).start()


def _write_parsed(parsed, db_path, conversation_id, user_input="", identity_key=None, user_id="", skip_empty_other=False):
    """将节标记结果分别写入对应表（v3.0：去重 + importance 解析 + MemOS 增量 + identity_key；v6.0：+ user_id）"""
    identity_key = identity_key or _IDENTITY_KEY_DEFAULT
    user_id = str(user_id or "")
    try:
        conn = sqlite3.connect(db_path)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # v7.1 阶段0-bug2：懒回填历史可靠源（旧库 user_messages/种子记忆）
        entity_attr_checker.backfill(conn, identity_key)
        for k, v in [("自然回复", "assistant"), ("心情", None), ("想法", None), ("事件摘要", None),
                      ("自我认知", None), ("他人认知", None), ("用户信息", None), ("自我信息", None),
                      ("知识条目", None), ("记忆归档", None), ("用户记忆", None), ("环境记忆", None)]:
            val = parsed.get(k, "")
            if not val:
                continue
            # v7.1 阶段0-bug2：LLM 摘要类节过实体-属性一致性校验，
            # 冲突时用已知绑定修正类型词（二饼=猫 不会被摘要写成狗）
            if k in _LLM_SUMMARY_SECTIONS:
                _fixed, n_conflict = entity_attr_checker.validate_llm(
                    val, conn, identity_key)
                if n_conflict:
                    print(f"[WARN] 实体-属性冲突修正 {k}: "
                          f"「{val[:60]}」→「{_fixed[:60]}」({n_conflict}处)", flush=True)
                val = _fixed
                if not val.strip():
                    continue

            # 提取 importance（从解析结果中取，如 "事件摘要_importance"）
            importance = parsed.get(f"{k}_importance", 3)

            if k == "自然回复":
                conn.execute(
                    "INSERT INTO user_messages(conversation_id,identity_key,role,content,user_id,created_at) VALUES(?,?,?,?,?,?)",
                    (conversation_id, identity_key, "assistant", val, user_id, now))
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
                deduped = _dedup_and_merge("event_summary", conversation_id, identity_key, val, conn, importance, column="summary", user_id=user_id)
                if deduped is None:
                    continue
                conn.execute(
                    "INSERT INTO event_summary(conversation_id,identity_key,summary,user_id,created_at) VALUES(?,?,?,?,?)",
                    (conversation_id, identity_key, deduped, user_id, now))
            elif k == "自我认知":
                # v8.4 名字自然生成：显式自我介绍且无名字 → 提取固化
                _maybe_capture_name(conn, identity_key, val)
                # 直接 INSERT，不去重合并（像 adaptive-agent-architecture 那样）
                conn.execute(
                    "INSERT INTO self_cognition(conversation_id,identity_key,content,created_at) VALUES(?,?,?,?)",
                    (conversation_id, identity_key, val, now))
            elif k == "他人认知":
                # v6.6 P0-2：批量模式空 user_id（无明确认知对象）跳过写入，
                # 杜绝 "" 空键进入 other_cognition 污染认知矩阵统计
                if skip_empty_other and not user_id:
                    continue
                # 直接 INSERT，不去重合并（像 adaptive-agent-architecture 那样）
                conn.execute(
                    "INSERT INTO other_cognition(conversation_id,identity_key,content,user_id,created_at) VALUES(?,?,?,?,?)",
                    (conversation_id, identity_key, val, user_id, now))
            elif k == "用户信息":
                for pair in val.split(","):
                    pair = pair.strip()
                    if pair:
                        conn.execute(
                            "INSERT INTO user_facts(conversation_id,identity_key,category,content,user_id,created_at) VALUES(?,?,?,?,?,?)",
                            (conversation_id, identity_key, "background", pair, user_id, now))
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
                    "INSERT INTO user_facts(conversation_id,identity_key,category,content,user_id,created_at) VALUES(?,?,?,?,?,?)",
                    (conversation_id, identity_key, "preference", entry, user_id, now))
            elif k == "用户记忆":
                # v4.0: 用户记忆写入 user_facts
                tags = parsed.get("归档标签", "")
                entry = f"[{tags}] {val}" if tags else val
                conn.execute(
                    "INSERT INTO user_facts(conversation_id,identity_key,category,content,user_id,created_at) VALUES(?,?,?,?,?,?)",
                    (conversation_id, identity_key, "preference", entry, user_id, now))
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


# ── v6.6 数据采集：记忆检索命中 / 静默认知更新 ──────────────────
def record_memory_usage(db_path, identity_key, decision_id, hits):
    """记录一次决策的记忆检索命中（数据采集 P0-1）：每条命中一行。

    Args:
        hits: memos.get_last_hits() 的结构化结果 [{id, table, score, adopted}]
    """
    if not hits:
        return
    threading.Thread(
        target=_write_memory_usage,
        args=(db_path, identity_key, decision_id, list(hits)), daemon=True).start()


def _write_memory_usage(db_path, identity_key, decision_id, hits):
    try:
        conn = sqlite3.connect(db_path)
        try:
            for h in hits:
                conn.execute(
                    "INSERT INTO memory_usage(identity_key, decision_id, entry_id, table_name, score, adopted) VALUES(?,?,?,?,?,?)",
                    (identity_key, decision_id, h.get("id"), h.get("table"),
                     h.get("score", 0.0), 1 if h.get("adopted") else 0))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def record_silent_cognition(db_path, identity_key, decision_id, thought,
                            cognition_written, sections=""):
    """记录静默决策的认知更新（数据采集 P0-2）：静默≠无认知。

    Args:
        thought: 静默时的真实想法（模型输出）
        cognition_written: 本次静默是否仍写入了认知类内容（他人认知/用户记忆等）
        sections: 写入的认知节名（逗号分隔）
    """
    threading.Thread(
        target=_write_silent_cognition,
        args=(db_path, identity_key, decision_id, thought or "",
              bool(cognition_written), sections or ""), daemon=True).start()


def _write_silent_cognition(db_path, identity_key, decision_id, thought,
                            cognition_written, sections):
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO silent_cognition(identity_key, decision_id, thought, cognition_written, sections) VALUES(?,?,?,?,?)",
                (identity_key, decision_id, thought, 1 if cognition_written else 0, sections))
            conn.commit()
        finally:
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


def g_where_identity_user(conn, table, column, conv_id, identity_key, user_id):
    """按 conversation_id + identity_key + user_id 获取最新一条记录的指定列（v6.0 多用户检索）。

    优先返回对指定 user_id 的认知（user_id 精确匹配）；
    无该用户专属记录时回退到全局认知（user_id=''，兜底保留），保证多用户认知隔离。
    """
    user_id = str(user_id or "")
    r = conn.execute(
        f"SELECT {column} FROM {table} "
        f"WHERE conversation_id=? AND identity_key=? AND user_id IN ('', ?) "
        f"ORDER BY CASE WHEN user_id=? THEN 0 ELSE 1 END, id DESC LIMIT 1",
        (conv_id, identity_key, user_id, user_id)
    ).fetchone()
    return r[0] if r else ""


def read_recent_observations(conn, identity_key, limit=5):
    """读取该 agent 最近"看过但未回应"的消息（v7.1 近期观察记录注入）。

    interest_judgment 由平台进程写入（检测文本 + 兴趣值），过门（passed=1）的
    消息已在当批决策上下文，不重复注入；只取 passed=0 的检测文本，按 id 倒序
    去重收集 limit 条，返回注入段文本（含标题行）。无记录 / 表不存在 → 返回 ""。
    """
    try:
        rows = conn.execute(
            "SELECT round_no, detected_text FROM interest_judgment "
            "WHERE identity_key=? AND passed=0 ORDER BY id DESC LIMIT 200",
            (identity_key,)).fetchall()
    except Exception:
        return ""
    seen, kept = set(), []
    for rno, txt in rows:
        txt = (txt or "").strip()
        if not txt or txt in seen:
            continue
        seen.add(txt)
        kept.append((rno, txt))
        if len(kept) >= max(int(limit), 1):
            break
    if not kept:
        return ""
    lines = "\n".join(f"- [r{rno}] {txt}" for rno, txt in kept)
    return "【近期观察记录】（你最近看过但未回应的消息，可参考）\n" + lines


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
# v8.4 不再硬编码名字（"我的名字是阿镜"），名字由交互自然生成（_maybe_capture_name）
_SEED_BACKGROUND_MEMORIES = [
    "我刚来到这台电脑上，对用户还不了解",
    "我住在用户的桌面上，能看到屏幕、听到声音",
]


def get_personality(db_path: str, identity_key: str = _IDENTITY_KEY_DEFAULT) -> dict:
    """读取性格向量 + 风格描述 + 注入双开关 + AI 名字；无记录时返回默认种子（fallback）

    v8.4 名字自然生成：name 默认空串（不硬编码），由交互中 AI 自我起名
    （_maybe_capture_name 从【自我认知】提取）或用户显式设置（set_ai_name）。
    """
    default = {
        **_DEFAULT_PERSONALITY,
        "name": "",
        "style_description": PERSONALITY_PRESETS["默认"]["style_description"],
        "preset_name": "默认",
        "anchor_enabled": True,
        "instruction_enabled": False,
        "exists": False,
    }
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT name, warmth, playfulness, directness, curiosity, style_description, preset_name, "
                "anchor_enabled, instruction_enabled "
                "FROM personality_seed WHERE identity_key=?",
                (identity_key,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return default
        return {
            "name": row[0] or "",
            "warmth": row[1], "playfulness": row[2],
            "directness": row[3], "curiosity": row[4],
            "style_description": row[5] or "",
            "preset_name": row[6] or "默认",
            "anchor_enabled": bool(row[7]),
            "instruction_enabled": bool(row[8]),
            "exists": True,
        }
    except Exception:
        return default


def save_personality(db_path: str, vector: dict, style_description: str = "",
                     preset_name: str = "默认",
                     identity_key: str = _IDENTITY_KEY_DEFAULT,
                     anchor_enabled: bool = True, instruction_enabled: bool = False) -> bool:
    """写入/更新性格种子（INSERT OR REPLACE，幂等）"""
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """INSERT INTO personality_seed(
                       identity_key, warmth, playfulness, directness, curiosity,
                       style_description, preset_name, anchor_enabled, instruction_enabled,
                       updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?, datetime('now','localtime'))
                   ON CONFLICT(identity_key) DO UPDATE SET
                       warmth=excluded.warmth, playfulness=excluded.playfulness,
                       directness=excluded.directness, curiosity=excluded.curiosity,
                       style_description=excluded.style_description,
                       preset_name=excluded.preset_name,
                       anchor_enabled=excluded.anchor_enabled,
                       instruction_enabled=excluded.instruction_enabled,
                       updated_at=datetime('now','localtime')""",
                (identity_key,
                 float(vector.get("warmth", 0.6)), float(vector.get("playfulness", 0.4)),
                 float(vector.get("directness", 0.5)), float(vector.get("curiosity", 0.5)),
                 style_description, preset_name,
                 1 if anchor_enabled else 0, 1 if instruction_enabled else 0),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        return False


def set_ai_name(db_path: str, name: str,
                identity_key: str = _IDENTITY_KEY_DEFAULT) -> bool:
    """更新 AI 名字（v8.4，酒馆 Character Card name 式固定字段）。

    GUI 设置面板调用；空名不入库（name.strip() 为空则忽略）。
    """
    name = (name or "").strip()
    if not name:
        return False
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """INSERT INTO personality_seed(identity_key, name, updated_at)
                   VALUES(?,?, datetime('now','localtime'))
                   ON CONFLICT(identity_key) DO UPDATE SET
                       name=excluded.name, updated_at=datetime('now','localtime')""",
                (identity_key, name),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        return False


def set_personality_mode(db_path: str, anchor_enabled: bool = True,
                         instruction_enabled: bool = False,
                         identity_key: str = _IDENTITY_KEY_DEFAULT) -> dict:
    """人格注入双开关热切换（写库即时生效，落盘持久化）。

    只更新两个开关，不动性格向量；无记录时先落默认种子再写开关。
    返回切换后的完整配置（供调用方确认/回显）。
    """
    try:
        conn = sqlite3.connect(db_path)
        try:
            has = conn.execute(
                "SELECT 1 FROM personality_seed WHERE identity_key=?",
                (identity_key,),
            ).fetchone()
            if not has:
                conn.execute(
                    """INSERT INTO personality_seed(
                           identity_key, warmth, playfulness, directness, curiosity,
                           style_description, preset_name, anchor_enabled, instruction_enabled)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (identity_key,
                     _DEFAULT_PERSONALITY["warmth"], _DEFAULT_PERSONALITY["playfulness"],
                     _DEFAULT_PERSONALITY["directness"], _DEFAULT_PERSONALITY["curiosity"],
                     PERSONALITY_PRESETS["默认"]["style_description"], "默认",
                     1 if anchor_enabled else 0, 1 if instruction_enabled else 0),
                )
            else:
                conn.execute(
                    """UPDATE personality_seed
                       SET anchor_enabled=?, instruction_enabled=?, updated_at=datetime('now','localtime')
                       WHERE identity_key=?""",
                    (1 if anchor_enabled else 0, 1 if instruction_enabled else 0, identity_key),
                )
            conn.commit()
            row = conn.execute(
                "SELECT warmth, playfulness, directness, curiosity, style_description, preset_name, "
                "anchor_enabled, instruction_enabled FROM personality_seed WHERE identity_key=?",
                (identity_key,),
            ).fetchone()
        finally:
            conn.close()
        return {
            "warmth": row[0], "playfulness": row[1],
            "directness": row[2], "curiosity": row[3],
            "style_description": row[4] or "",
            "preset_name": row[5] or "默认",
            "anchor_enabled": bool(row[6]),
            "instruction_enabled": bool(row[7]),
        }
    except Exception:
        return {}


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
