"""
实体-属性一致性校验器（v7.1 阶段0-bug2）

问题：LLM 生成的【事件摘要】/【自我认知】会把多实体属性混写
（E4 idx30「你养的两只狗叫二饼和豆豆」——二饼是猫、豆豆是仓鼠，
被旺财的"狗"属性污染），直写 event_summary 后经 history_summary +
MemOS 检索反复注入，形成自我强化的污染漂移（idx22 系统已不认识豆豆）。

方案：沉淀侧加「实体-属性一致性校验」——
  A. ground truth 抽取：用户原话（user_messages role='user'）与种子记忆
     （long_term_memory 非 exchange）是可靠事实源，从中抽取「实体→动物类型」
     强绑定，累加 confidence 存入 entity_attrs 表。
  B. LLM 摘要校验：事件摘要/自我认知/他人认知/用户记忆/环境记忆/记忆归档
     等节写入前过校验，与已知强绑定冲突的类型词用已知值修正。

只覆盖规则可抽取的动物类型绑定（高价值、易漂移、可规则化），
不做通用知识抽取，避免过度设计。
"""
import re
import sqlite3

# ── 动物类型词表（规则可抽取的高价值绑定属性）──
ANIMAL_TYPES = ("猫", "狗", "仓鼠", "兔子", "乌龟", "鸟", "鱼",
                "龙猫", "荷兰猪", "豚鼠", "花枝鼠")
_ANIMAL_ALT = "|".join(ANIMAL_TYPES)

# 类型在前、名字在后：养了(的)?(两只)?(猫)...(名字叫)(豆豆)
_RE_TYPE_FIRST = re.compile(
    r"(?:养了|养|有只|有|还有|添了|新养|又养|养着|养的)"
    r"(?:的)?(?:两只|三只|一只|只|条|一)?(?P<type>" + _ANIMAL_ALT + r")"
    r"(?P<mid>[^。！？\n]{0,24}?)(?:叫|名字叫|名字是|取名叫|命名为)"
    r"(?P<names>[\u4e00-\u9fa5A-Za-z0-9]{1,12})")

# 名字在前、类型在后：二饼(是)(只)?(猫)
_RE_NAME_FIRST = re.compile(
    r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{1,6})(?:是|叫)"
    r"(?:一只|只|条)?(?:可爱的|小|橘|黑|白|黄)?(?P<type>" + _ANIMAL_ALT + r")")

# 名字拆分连接词
_RE_SPLIT = re.compile(r"[和、与及，,\s]+")

# 懒回填标记（模块级，防每次校验重复全表扫描）
_BACKFILLED: set = set()


# ════════════════════════════════════════════════════════════════
#  绑定抽取
# ════════════════════════════════════════════════════════════════

def _split_names(names: str) -> list[str]:
    """拆分多实体名：'二饼和豆豆' → ['二饼', '豆豆']；过滤单字/空"""
    out = []
    for n in _RE_SPLIT.split(names.strip()):
        n = n.strip()
        if len(n) >= 2:
            out.append(n)
    return out


def extract_bindings(text: str) -> list[tuple[str, str, int, int]]:
    """从文本抽取「实体→动物类型」绑定对。

    Returns:
        [(name, atype, start, end)] —— start/end 为绑定对在文本中的位置
        （供精确修正；无位置需求的调用方可忽略后两位）
    """
    binds: list[tuple[str, str, int, int]] = []
    for m in _RE_TYPE_FIRST.finditer(text):
        atype, names = m.group("type"), m.group("names")
        for name in _split_names(names):
            binds.append((name, atype, m.start(), m.end()))
    for m in _RE_NAME_FIRST.finditer(text):
        name, atype = m.group("name"), m.group("type")
        binds.append((name, atype, m.start(), m.end()))
    return binds


# ════════════════════════════════════════════════════════════════
#  DB 读写（entity_attrs 表）
# ════════════════════════════════════════════════════════════════

def ensure_table(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entity_attrs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            identity_key TEXT NOT NULL DEFAULT 'gui:default',
            entity TEXT NOT NULL,
            attribute TEXT NOT NULL DEFAULT 'type',
            value TEXT NOT NULL,
            confidence INTEGER NOT NULL DEFAULT 1,
            source TEXT DEFAULT 'user_statement',
            updated_at TEXT NOT NULL DEFAULT(datetime('now','localtime')),
            UNIQUE(identity_key, entity, attribute))
    """)


def _load_bindings(conn, identity_key: str) -> dict[str, str]:
    """加载已知「实体→类型」绑定（entity_attrs 中 attribute='type'）"""
    try:
        rows = conn.execute(
            "SELECT entity, value FROM entity_attrs "
            "WHERE identity_key=? AND attribute='type'",
            (identity_key,)).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {r[0]: r[1] for r in rows}


def record_statement(text: str, conn, identity_key: str) -> int:
    """从用户原话/种子记忆抽取绑定并 upsert（confidence 累加）。

    返回新抽取的绑定数。仅当文本是可靠事实源时调用
    （user_messages role='user'、long_term_memory 非 exchange）。
    """
    if not text:
        return 0
    ensure_table(conn)
    n = 0
    for name, atype, _s, _e in extract_bindings(text):
        row = conn.execute(
            "SELECT confidence FROM entity_attrs WHERE identity_key=? AND entity=? AND attribute='type'",
            (identity_key, name)).fetchone()
        if row:
            conn.execute(
                "UPDATE entity_attrs SET value=?, confidence=confidence+1, "
                "updated_at=datetime('now','localtime') "
                "WHERE identity_key=? AND entity=? AND attribute='type'",
                (atype, identity_key, name))
        else:
            conn.execute(
                "INSERT INTO entity_attrs(identity_key,entity,attribute,value,confidence,source)"
                " VALUES(?,?, 'type',?,1,'user_statement')",
                (identity_key, name, atype))
        n += 1
    return n


def backfill(conn, identity_key: str) -> int:
    """懒回填：首次使用时从历史可靠源抽取绑定（幂等，防全量重复扫描）。

    可靠源：user_messages role='user'（用户原话）+
    long_term_memory 非 exchange（种子/归档等直写事实）。
    """
    if identity_key in _BACKFILLED:
        return 0
    ensure_table(conn)
    n = 0
    for (content,) in conn.execute(
            "SELECT content FROM user_messages WHERE role='user' "
            "AND content IS NOT NULL AND content != ''").fetchall():
        n += record_statement(str(content), conn, identity_key)
    for (content,) in conn.execute(
            "SELECT content FROM long_term_memory WHERE source != 'exchange' "
            "AND role='user' AND content IS NOT NULL AND content != ''").fetchall():
        n += record_statement(str(content), conn, identity_key)
    conn.commit()
    _BACKFILLED.add(identity_key)
    return n


# ════════════════════════════════════════════════════════════════
#  LLM 摘要校验（冲突修正）
# ════════════════════════════════════════════════════════════════

def validate_llm(text: str, conn, identity_key: str) -> tuple[str, int]:
    """校验 LLM 摘要中的实体-属性绑定，冲突时用已知值修正类型词。

    修正策略：
      - 单实体绑定段冲突：类型词精确替换为已知值（二饼被写狗→修正为猫）。
      - 多实体共享一个类型词的绑定段（如「两只狗叫二饼和豆豆」）：
        无法分别精确修正，类型词替换为中性词「宠物」，避免错误归因
        （二饼=猫、豆豆=仓鼠 都不会被写成狗）。

    Returns:
        (new_text, n_conflict)——n_conflict 为被修正的冲突绑定数；
        无冲突时原样返回（new_text == text, n_conflict == 0）。
    """
    if not text:
        return text, 0
    known = _load_bindings(conn, identity_key)
    if not known:
        return text, 0
    # 按绑定段分组：(start, end) 相同的多个实体共享一个类型词
    segments: dict[tuple[int, int], list[tuple[str, str]]] = {}
    for name, atype, start, end in extract_bindings(text):
        segments.setdefault((start, end), []).append((name, atype))

    fixes: list[tuple[int, int, str, str]] = []  # (start, end, old_type, new_type)
    n_conflict = 0
    for (start, end), binds in segments.items():
        conflicts = [b for b in binds
                     if known.get(b[0]) and known[b[0]] != b[1]]
        if not conflicts:
            continue
        old_type = binds[0][1]  # 同段实体共享同一类型词
        if len(binds) == 1:
            new_type = known[binds[0][0]]
        else:
            new_type = "宠物"  # 多实体无法分别精确修正 → 中性词防错误归因
        fixes.append((start, end, old_type, new_type))
        n_conflict += len(conflicts)
    if not fixes:
        return text, 0
    new_text = text
    for start, end, old_type, new_type in sorted(fixes, reverse=True):
        seg = new_text[start:end].replace(old_type, new_type)
        new_text = new_text[:start] + seg + new_text[end:]
    return new_text, n_conflict
