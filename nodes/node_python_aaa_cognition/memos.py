"""
MemOS 语义记忆检索模块 — 替换 memory.py

用 SentenceTransformer 真语义向量替换 MD5 hash 伪向量，
内嵌 numpy 暴力检索引擎（小规模场景无需 FAISS）。
"""
import os
import json
import re
import sqlite3
import threading
import numpy as np
from pathlib import Path

_model = None
_model_lock = threading.Lock()
_embeddings = None   # np.ndarray: (N, dim)
_entry_ids = []      # list[int]: 对应各表的 id
_entry_tables = []   # list[str]: 条目来源表名
_entry_identity_keys = []  # list[str]: 每条记忆所属 identity_key
_index_path = ""     # 持久化路径

# v4.0: 索引全局变量写锁 —— 后台 rebuild（sync_turn/diary 通道）与
# 主线程 rebuild 并发会重复 append 条目，必须串行化。
# 用 RLock：rebuild_index 持锁期间调用 save_index 需可重入。
_index_lock = threading.RLock()

# v6.6 数据采集 P0-1：检索命中埋点（线程本地，后台 review 线程的检索
# 不会覆盖主流程决策的命中记录）
_retrieve_hits = threading.local()


def get_last_hits() -> list[dict]:
    """返回当前线程最近一次检索的命中条目（供 decisions.jsonl 埋点）。

    Returns:
        [{id, table, score, adopted}]：adopted=True 表示该条已被采纳
        （注入 prompt 上下文）；被相似度/身份过滤掉的条目不在此列。
    """
    return list(getattr(_retrieve_hits, "hits", []))


def _record_hits(hits: list[dict]):
    _retrieve_hits.hits = hits


def _get_model(timeout: float = -1) -> object | None:
    """获取 SentenceTransformer 模型。

    Args:
        timeout: 等待模型加载的超时秒数。-1 表示阻塞直到加载完成；0 表示即查即返。

    Returns:
        模型实例，超时或未就绪时返回 None。
    """
    global _model
    if _model is not None:
        return _model

    if timeout == 0:
        # 非阻塞快查：锁被占用 → 模型正在加载 → 返回 None
        if not _model_lock.acquire(blocking=False):
            return None
        try:
            return _model if _model is not None else None
        finally:
            _model_lock.release()

    # 阻塞等待（timeout < 0）或有限等待（timeout > 0）
    if timeout < 0:
        acquired = _model_lock.acquire(blocking=True)
    else:
        acquired = _model_lock.acquire(blocking=True, timeout=timeout)
    if not acquired:
        return None
    try:
        if _model is None:
            if "HF_ENDPOINT" not in os.environ:
                os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer("all-MiniLM-L6-v2")
        return _model
    finally:
        _model_lock.release()


def preload():
    """异步预加载模型到内存，不阻塞 AAA 启动。"""
    threading.Thread(target=_get_model, kwargs={"timeout": -1}, daemon=True).start()


def _encode(text: str) -> np.ndarray | None:
    """返回归一化后的嵌入向量，模型未就绪时返回 None"""
    model = _get_model(timeout=0)
    if model is None:
        return None
    v = model.encode(text, normalize_embeddings=True)
    return np.asarray(v, dtype=np.float32)


def _core(text: str) -> str:
    """去空白/标点后的文本核心（供逐字命中检测）"""
    return re.sub(r"[\s。！？，、；：,.!?;:（）()【】\[\]「」\"'“”]", "",
                  text or "")


def _query_echo_penalty(query: str, content: str) -> float:
    """query 逐字命中惩罚：query 原文出现在记忆内容里（历史 exchange 回放）
    说明该条是「重复提问的历史」而非「答案记忆」，降权让位给真正知识记忆。

    E4 idx44 实证：问「你还记得我喜欢什么电影吗？」时，历史里逐字相同的
    exchange 条目相似度 0.65+ 霸榜 top5，种子「星际穿越」仅 0.405 被挤出。
    """
    q_core = _core(query)
    c_core = _core(content[:120])
    if len(q_core) >= 4 and q_core in c_core:
        return 0.2
    return 0.0


# v7.3 停用字/词（gram 提权噪声过滤）：意图词与通用高频词无内容判别力
_GRAM_STOP_CHARS = frozenset(
    "什么怎么一个这个那个没有不是就是但是所以因为如果可以还是现在知道记得喜欢"
    "我们你们他们这些那些时候地方东西事情觉得感觉我的你有什么在我不你有他她它"
    "和与及就都也很还又再才只最着过吧吗呢啊了")
_GRAM_NOISE = frozenset(
    {"今天", "现在", "什么", "这个", "那个", "我们", "你们", "他们", "自己",
     "时候", "真的", "还是", "没有", "觉得", "感觉", "地方", "东西", "知道",
     "这样", "那样", "怎么", "因为", "所以", "但是", "如果", "就是", "不是",
     "可以", "有些", "其实", "可能", "比较", "应该", "最近", "之前", "以后"})


def _grams(chars: list[str], noise: bool) -> set:
    """连续双字 gram 集（噪声 gram 可剔除）"""
    out = set()
    for i in range(len(chars) - 1):
        g = chars[i] + chars[i + 1]
        if len(g) == 2 and (not noise or g not in _GRAM_NOISE):
            out.add(g)
    return out


def _gram_boost(query: str, content: str) -> float:
    """query 词元提权：query 去停用字后的双字 gram 与记忆内容重叠时提权。

    中文语义模型（all-MiniLM-L6-v2）相似度饱和 + 语义坍塌下，纯余弦排序
    对唯一性记忆失效（E4 idx44 种子星际穿越 0.405 vs 无关 exchange 0.65+），
    词元重叠是更可靠的相关性信号。上限 +0.4 防单条记忆过度拔高。
    """
    qc = _core(query)
    cc = _core(content[:120])
    qchars = [c for c in qc if c not in _GRAM_STOP_CHARS]
    cchars = [c for c in cc if c not in _GRAM_STOP_CHARS]
    if len(qchars) < 2 or len(cchars) < 2:
        return 0.0
    q_grams = _grams(qchars, noise=False)
    c_grams = _grams(cchars, noise=True)
    overlap = q_grams & c_grams
    if not overlap:
        return 0.0
    return min(0.2 * len(overlap), 0.4)


# ════════════════════════════════════════════════════════════════
#  索引管理
# ════════════════════════════════════════════════════════════════

def _index_path_for(db_path: str) -> str:
    """MemOS 索引文件路径（和 db 同级）"""
    d = os.path.dirname(db_path)
    return os.path.join(d, "memos_index.npz")


def load_index(db_path: str):
    """从磁盘加载 MemOS 索引"""
    global _embeddings, _entry_ids, _entry_tables, _entry_identity_keys, _index_path
    with _index_lock:
        _index_path = _index_path_for(db_path)
        p = Path(_index_path)
        if p.exists():
            data = np.load(_index_path, allow_pickle=True)
            _embeddings = data["embeddings"]
            _entry_ids = data["entry_ids"].tolist()
            if "entry_tables" in data:
                _entry_tables = data["entry_tables"].tolist()
            else:
                _entry_tables = ["long_term_memory"] * len(_entry_ids)
            if "identity_keys" in data:
                _entry_identity_keys = data["identity_keys"].tolist()
            else:
                _entry_identity_keys = ["gui:default"] * len(_entry_ids)
        else:
            _embeddings = np.empty((0, 384), dtype=np.float32)
            _entry_ids = []
            _entry_tables = []
            _entry_identity_keys = []


def save_index():
    """持久化 MemOS 索引到磁盘"""
    with _index_lock:
        if _embeddings is None or _entry_ids is None:
            return
        os.makedirs(os.path.dirname(_index_path) or ".", exist_ok=True)
        np.savez_compressed(
            _index_path,
            embeddings=_embeddings,
            entry_ids=np.array(_entry_ids, dtype=np.int64),
            entry_tables=np.array(_entry_tables, dtype=object),
            identity_keys=np.array(_entry_identity_keys, dtype=object),
        )


def rebuild_index(db_path: str):
    """增量重建索引：扫描 long_term_memory + diaries，去重后只编码新条目。

    注意：user_messages（原始对话）不再建索引——对话已以合并 QA 形式写入
    long_term_memory（source='exchange'），双源会导致同一内容被索引两次。

    线程安全：整个函数持 _index_lock —— 后台 rebuild（sync_turn/diary 通道）
    与主线程 rebuild 并发时串行执行，防止基于同一旧状态重复 append 条目。
    """
    global _embeddings, _entry_ids, _entry_tables, _entry_identity_keys
    with _index_lock:
        conn = sqlite3.connect(db_path)
        try:
            # 已有索引条目集合（用于去重）——注意元组顺序为 (id, table)，
            # 与下方检查 (eid, "long_term_memory") 保持一致（zip 顺序反了会导致
            # 去重永久失效，每次 rebuild 重复索引全部条目）。
            existing = set(zip(_entry_ids, _entry_tables)) if _entry_tables else set()
            all_new = []  # (id, table, content, identity_key)

            rows = conn.execute(
                "SELECT id, content, identity_key FROM long_term_memory WHERE content IS NOT NULL AND content != '' ORDER BY id"
            ).fetchall()
            for row in rows:
                eid, content, key = row
                if (eid, "long_term_memory") not in existing:
                    all_new.append((eid, "long_term_memory", content[:500], key or "gui:default"))

            rows = conn.execute(
                "SELECT id, content, mood, identity_key FROM diaries WHERE content IS NOT NULL AND content != '' ORDER BY id"
            ).fetchall()
            for row in rows:
                eid, content, mood, key = row
                text = f"[diary] {content}"[:500]
                if mood:
                    text += f" (心情: {mood})"
                if (eid, "diaries") not in existing:
                    all_new.append((eid, "diaries", text, key or "gui:default"))
        finally:
            conn.close()

        if not all_new:
            if _embeddings is None:
                _embeddings = np.empty((0, 384), dtype=np.float32)
                _entry_ids = []
                _entry_tables = []
                _entry_identity_keys = []
                save_index()
            return

        model = _get_model()
        texts = [r[2] for r in all_new]
        new_vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        new_vecs = np.asarray(new_vecs, dtype=np.float32)
        new_ids = [r[0] for r in all_new]
        new_tables = [r[1] for r in all_new]
        new_keys = [r[3] for r in all_new]

        if _embeddings is None or len(_entry_ids) == 0:
            _embeddings = new_vecs
            _entry_ids = new_ids
            _entry_tables = new_tables
            _entry_identity_keys = new_keys
        else:
            _embeddings = np.vstack([_embeddings, new_vecs])
            _entry_ids.extend(new_ids)
            _entry_tables.extend(new_tables)
            _entry_identity_keys.extend(new_keys)

        save_index()


# ════════════════════════════════════════════════════════════════
#  检索接口
# ════════════════════════════════════════════════════════════════

def retrieve(query: str, top_k: int = 5, db_path: str = "", identity_key: str = "gui:default") -> str:
    """语义检索相关记忆，返回格式化文本（供 prompt 注入）。

    检索来源：
      - long_term_memory（记忆归档 + 合并对话 QA）
      - diaries（日记）

    Args:
        query: 检索关键词/问题
        top_k: 返回 top N
        db_path: 用于回查原文
        identity_key: 身份键，只返回该用户的记忆

    Returns:
        格式化记忆文本，空串表示无结果
    """
    if _embeddings is None or len(_entry_ids) == 0:
        _record_hits([])
        return ""

    qv = _encode(query)
    if qv is None:
        _record_hits([])
        return ""  # 模型未就绪，跳过检索
    sims = _embeddings @ qv  # 余弦相似度
    # v7.1 阶段0-bug3：候选池 top_k*3 → top_k*20。中文语义模型相似度饱和
    # （E4 idx44：种子星际穿越 0.405 在 85 条库里排 70 名外），候选池过小
    # 会让高 importance 种子记忆永远进不了排序，加权无从生效。
    top_idx = set(np.argsort(-sims)[:top_k * 20].tolist())

    cands = []  # (weighted_score, line, hit)  v7.1 收集后按加权分排序
    hits = []  # v6.6 数据采集 P0-1：实际返回（采纳）的命中条目
    conn = sqlite3.connect(db_path) if db_path else None
    try:
        # v7.3 高重要记忆保底：importance>=5 的记忆无条件进候选
        # （相似度饱和下靠 top_idx 永远捞不到它们，加权无从生效）
        if conn:
            id_to_idx = {eid: i for i, eid in enumerate(_entry_ids)}
            for (eid,) in conn.execute(
                "SELECT id FROM long_term_memory WHERE identity_key=? "
                "AND importance>=5 AND (status IS NULL OR status='active')",
                (identity_key,)):
                i = id_to_idx.get(int(eid))
                if i is not None:
                    top_idx.add(i)
        for idx in sorted(top_idx):
            eid = _entry_ids[idx]
            table = _entry_tables[idx] if idx < len(_entry_tables) else "long_term_memory"
            score = float(sims[idx])
            if score < 0.3:
                continue
            if idx < len(_entry_identity_keys) and _entry_identity_keys[idx] != identity_key:
                continue
            if not conn:
                cands.append((score, f"[{score:.3f}] (匹配条目)",
                              {"id": int(eid), "table": table,
                               "score": round(score, 3), "adopted": True}))
                continue

            if table == "diaries":
                row = conn.execute(
                    "SELECT content, date, mood FROM diaries WHERE id=?", (eid,)
                ).fetchone()
                if not row:
                    continue
                content, date_str, mood = row
                ts = date_str[:10] if date_str else ""
                line = f"[{ts} | {score:.2f}] [日记] {content[:200]}"
                if mood:
                    line += f" (心情: {mood})"
                cands.append((score, line,
                              {"id": int(eid), "table": table,
                               "score": round(score, 3), "adopted": True}))
            else:
                # long_term_memory
                row = conn.execute(
                    "SELECT content, created_at, status, importance, source FROM long_term_memory WHERE id=?", (eid,)
                ).fetchone()
                if not row:
                    continue
                content, created_at, status, importance, source = row
                # v4.0: 过滤掉 superseded 的记录
                if status and status != "active":
                    continue
                content = content[:200] if content else ""
                created_at = created_at[:10] if created_at else ""
                line = f"[{created_at} | {score:.2f}] {content}"
                # v7.1 阶段0-bug3：importance 弱加权（0.02/级，仅同分决胜，
                # 防止高重要种子反超真正答案记忆——见 dbg_side 实测）；
                # v7.2 对话回放降权 + 逐字命中降权；
                # v7.3 query 词元提权（中文语义坍塌下词元重叠才是可靠相关性）。
                imp = int(importance or 3)
                w = score + 0.02 * (imp - 3)
                if source == "exchange":
                    w -= 0.10
                w -= _query_echo_penalty(query, content)
                w += _gram_boost(query, content)
                cands.append((w, line,
                              {"id": int(eid), "table": table,
                               "score": round(score, 3), "adopted": True}))

    finally:
        if conn:
            conn.close()

    # v7.1 按加权分降序取 top_k（diaries 无 importance，加权分 = 原始分）
    cands.sort(key=lambda c: c[0], reverse=True)
    selected = cands[:top_k]
    results = [c[1] for c in selected]
    hits = [c[2] for c in selected]

    _record_hits(hits)
    return "\n".join(results) if results else ""


def retrieve_raw(query: str, top_k: int = 5, identity_key: str = "gui:default", db_path: str = "") -> list[dict]:
    """语义检索，返回结构化结果（供程序内部使用）。

    v7.1 阶段0-bug3：与 retrieve 对齐——候选池 top_k*5 + importance 加权
    （db_path 提供时可读 importance，否则退化为纯相似度排序）。
    """
    if _embeddings is None or len(_entry_ids) == 0:
        _record_hits([])
        return []

    qv = _encode(query)
    if qv is None:
        _record_hits([])
        return []  # 模型未就绪，跳过检索
    sims = _embeddings @ qv
    # v7.1 阶段0-bug3：候选池 top_k*12 + v7.3 高重要保底（与 retrieve 对齐）
    top_idx = set(np.argsort(-sims)[:top_k * 12].tolist())

    conn = sqlite3.connect(db_path) if db_path else None
    cands = []  # (weighted_score, hit_dict)
    try:
        # v7.3 高重要记忆保底（importance>=5 无条件进候选）
        if conn:
            id_to_idx = {eid: i for i, eid in enumerate(_entry_ids)}
            for (eid,) in conn.execute(
                "SELECT id FROM long_term_memory WHERE identity_key=? "
                "AND importance>=5 AND (status IS NULL OR status='active')",
                (identity_key,)):
                i = id_to_idx.get(int(eid))
                if i is not None:
                    top_idx.add(i)
        for idx in sorted(top_idx):
            score = float(sims[idx])
            if score < 0.3:
                continue
            if idx < len(_entry_identity_keys) and _entry_identity_keys[idx] != identity_key:
                continue
            table = _entry_tables[idx] if idx < len(_entry_tables) else "long_term_memory"
            hit = {"entry_id": _entry_ids[idx], "table": table, "score": score}
            w = score
            if conn and table == "long_term_memory":
                row = conn.execute(
                    "SELECT importance, content, source FROM long_term_memory WHERE id=?", (hit["entry_id"],)
                ).fetchone()
                if row:
                    imp = int(row[0] or 3)
                    # v7.3 与 retrieve 对齐：importance 弱加权 + 回放降权 +
                    # 逐字命中降权 + query 词元提权
                    w = score + 0.02 * (imp - 3)
                    if row[2] == "exchange":
                        w -= 0.10
                    w -= _query_echo_penalty(query, str(row[1] or ""))
                    w += _gram_boost(query, str(row[1] or ""))
            cands.append((w, hit))
    finally:
        if conn:
            conn.close()

    cands.sort(key=lambda c: c[0], reverse=True)
    results = [c[1] for c in cands[:top_k]]
    # v6.6 数据采集 P0-1：同步埋点命中条目（与 retrieve 一致，供决策埋点）
    _record_hits([{"id": int(r["entry_id"]), "table": r["table"],
                   "score": round(r["score"], 3), "adopted": True}
                  for r in results])
    return results


# ════════════════════════════════════════════════════════════════
#  记忆图谱表向量索引（供 GUI 记忆图谱面板使用）
#  支持增量构建 + 缓存检测 + 可配置 max_edges_per_node
# ════════════════════════════════════════════════════════════════

# 记忆图谱数据源：多表聚合（v4.0，语义记忆过滤）
# 每项: (表名, SQL) — SQL 返回 (id, content[, category, created_at])
#
# 图谱只呈现"AI 对用户和自己的长期语义记忆"，剔除三类噪音：
#   - 原始对话 (user_messages) — 噪音大，对话已合并为 QA 进 long_term_memory
#   - 瞬时/元数据 (location_history, fixed_cognition, self_info,
#     personality_seed, mood_trend, mood_value) — 非语义内容，另有独立可视化
#   - 低区分度记录 — feelings 空 thought 的纯情绪词、long_term_memory 的
#     tool 工具返回 / diary 整篇日记（日记由 diaries 表统一承载，避免双源）
MEMORY_QUERIES = {
    "event_summary": ("event_summary",
        "SELECT id, summary AS content, 'event_summary' AS category, "
        "created_at FROM event_summary "
        "WHERE summary IS NOT NULL AND summary != '' "
        "AND summary NOT LIKE '%打招呼%' "
        "AND LENGTH(summary) > 15 ORDER BY id DESC LIMIT 200"),
    "self_cognition": ("self_cognition",
        "SELECT id, content, 'self_cognition' AS category, created_at "
        "FROM self_cognition "
        "WHERE content IS NOT NULL AND content != '' "
        "ORDER BY id DESC LIMIT 200"),
    "other_cognition": ("other_cognition",
        "SELECT id, content, 'other_cognition' AS category, created_at "
        "FROM other_cognition "
        "WHERE content IS NOT NULL AND content != '' "
        "ORDER BY id DESC LIMIT 200"),
    "user_facts": ("user_facts",
        "SELECT id, content, category, created_at FROM user_facts "
        "WHERE content IS NOT NULL AND content != '' "
        "ORDER BY id DESC LIMIT 200"),
    "feelings": ("feelings",
        # 只保留 mood + thought 都有内容的记录；纯情绪词（如只有"开心"）
        # 无语义区分度，进图谱只会产生互相重叠的噪声节点
        # category 统一为 'feelings'（GUI 显示"想法"），不再用情绪词作分类
        "SELECT id, thought AS content, 'feelings' AS category, created_at "
        "FROM feelings "
        "WHERE thought IS NOT NULL AND thought != '' "
        "ORDER BY id DESC LIMIT 200"),
    "long_term_memory": ("long_term_memory",
        # 剔除 tool 工具返回（如"结果"）和 diary 整篇日记（由 diaries 表
        # 统一承载），保留 exchange 合并 QA / seed 种子背景等真实语义记忆
        "SELECT id, content, 'long_term_memory' AS category, created_at "
        "FROM long_term_memory "
        "WHERE content IS NOT NULL AND content != '' AND status='active' "
        "AND role != 'tool' AND source != 'diary' AND LENGTH(content) > 10 "
        "ORDER BY id DESC LIMIT 200"),
    "diaries": ("diaries",
        "SELECT id, content, 'diary' AS category, "
        "COALESCE(date, created_at) AS created_at "
        "FROM diaries "
        "WHERE content IS NOT NULL AND content != '' AND LENGTH(content) > 10 "
        "ORDER BY id DESC LIMIT 200"),
}

# 图谱配置常量
GRAPH_DEFAULT_MAX_EDGES = 5
GRAPH_DEFAULT_THRESHOLD = 0.6
GRAPH_INDEX_VERSION = 5  # 格式版本号，变更时触发全量重建（v5: feelings 分类统一为"想法"）


def _knowledge_index_path_for(db_path: str) -> str:
    d = os.path.dirname(db_path)
    return os.path.join(d, "knowledge_index.npz")


def _load_knowledge_index(index_path: str) -> dict | None:
    """加载已有图谱索引，供增量构建使用。"""
    p = Path(index_path)
    if not p.exists():
        return None
    try:
        data = np.load(index_path, allow_pickle=True)
        # 检查版本号
        version = data.get("version", np.array([1]))
        if version[0] != GRAPH_INDEX_VERSION:
            return None  # 版本不匹配，触发全量重建
        return {
            "embeddings": data["embeddings"],
            "entry_ids": data["entry_ids"].tolist(),
            "tables": data["tables"].tolist(),
            "categories": data["categories"].tolist(),
            "contents": data["contents"].tolist(),
            "created_ats": data["created_ats"].tolist() if "created_ats" in data else [],
            "max_edges_per_node": int(data["max_edges_per_node"][0]) if "max_edges_per_node" in data else GRAPH_DEFAULT_MAX_EDGES,
        }
    except Exception:
        return None


def rebuild_knowledge_index(
    db_path: str,
    max_edges_per_node: int = GRAPH_DEFAULT_MAX_EDGES,
    threshold: float = GRAPH_DEFAULT_THRESHOLD,
    force_full: bool = False,
):
    """增量构建图谱索引。

    Args:
        db_path: 数据库路径
        max_edges_per_node: 每节点最大连边数 (1-20)
        threshold: 相似度阈值 (0-1)
        force_full: 强制全量重建（忽略缓存）
    """
    model = _get_model()
    index_path = _knowledge_index_path_for(db_path)
    data_dir = Path(db_path).parent

    # ── Step 1: 加载已有索引 ──
    existing = None if force_full else _load_knowledge_index(index_path)

    # ── Step 2: 查询数据库获取所有条目 ──
    conn = sqlite3.connect(db_path)
    all_entries = []
    try:
        for table_name, (_, query) in MEMORY_QUERIES.items():
            rows = conn.execute(query).fetchall()
            for row in rows:
                entry_id = row[0]
                content = (row[1] or "").strip()
                category = row[2] if len(row) > 2 else table_name
                created_at = row[3] if len(row) > 3 else ""
                if not content:
                    continue
                all_entries.append({
                    "id": entry_id,
                    "table": table_name,
                    "category": category,
                    "content": content,
                    "created_at": created_at,
                })
    finally:
        conn.close()

    if not all_entries:
        return

    # ── Step 3: 确定需要编码的新条目 ──
    all_entries_data = all_entries
    if existing is not None and not force_full:
        # 增量模式：只编码新条目
        existing_ids = set(zip(existing["tables"], existing["entry_ids"]))
        new_entries = [
            e for e in all_entries
            if (e["table"], e["id"]) not in existing_ids
        ]

        if not new_entries:
            # 无新数据，跳过
            print(f"[MemOS] 图谱缓存命中，无新条目")
            return

        # 编码新条目
        new_texts = [e["content"][:500] for e in new_entries]
        new_vecs = model.encode(new_texts, normalize_embeddings=True, show_progress_bar=False)
        new_embeddings = np.asarray(new_vecs, dtype=np.float32)

        # 追加到已有索引
        embeddings = np.vstack([existing["embeddings"], new_embeddings])
        entry_ids = existing["entry_ids"] + [e["id"] for e in new_entries]
        tables = existing["tables"] + [e["table"] for e in new_entries]
        categories = existing["categories"] + [e["category"] for e in new_entries]
        contents = existing["contents"] + [e["content"] for e in new_entries]
        created_ats = existing.get("created_ats", []) + \
            [e.get("created_at", "") for e in new_entries]

        print(f"[MemOS] 图谱增量更新: {len(new_entries)} 条新数据, 总计 {len(embeddings)} 条")
    else:
        # 全量模式：编码所有条目
        texts = [e["content"][:500] for e in all_entries]
        vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        embeddings = np.asarray(vecs, dtype=np.float32)
        entry_ids = [e["id"] for e in all_entries]
        tables = [e["table"] for e in all_entries]
        categories = [e["category"] for e in all_entries]
        contents = [e["content"] for e in all_entries]
        created_ats = [e.get("created_at", "") for e in all_entries]

        print(f"[MemOS] 图谱全量重建: {len(embeddings)} 条")

    # ── Step 4: 保存索引 ──
    path = index_path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    np.savez_compressed(
        path,
        embeddings=embeddings,
        entry_ids=np.array(entry_ids, dtype=np.int64),
        tables=np.array(tables, dtype=object),
        categories=np.array(categories, dtype=object),
        contents=np.array(contents, dtype=object),
        created_ats=np.array(created_ats, dtype=object),
        max_edges_per_node=np.array([max_edges_per_node]),
        version=np.array([GRAPH_INDEX_VERSION]),
    )

    # ── Step 5: 导出图谱 JSON ──
    _export_knowledge_graph(
        all_entries_data, embeddings, data_dir,
        threshold=threshold,
        max_edges_per_node=max_edges_per_node,
    )


def _compute_2d_coordinates(embeddings: np.ndarray, width: int = 1500, height: int = 1200) -> tuple[np.ndarray, np.ndarray]:
    """用 PCA 将高维向量降到 2D，归一化到画布坐标范围。

    Args:
        embeddings: (N, D) 归一化向量矩阵
        width: 画布宽度
        height: 画布高度

    Returns:
        (coords_2d, explained_variance_ratio)
        coords_2d: (N, 2) 数组，每行 [x, y]
    """
    n = len(embeddings)
    if n < 2:
        return np.zeros((n, 2)), np.array([0.0, 0.0])

    # 中心化
    mean = embeddings.mean(axis=0)
    centered = embeddings - mean

    # SVD 取前两个主成分
    # U: (N, K), S: (K,), Vt: (K, D)
    U, S, Vt = np.linalg.svd(centered, full_matrices=False)

    # 投影到 2D
    coords = U[:, :2] * S[:2]  # (N, 2)

    # 归一化到 [margin, width-margin] × [margin, height-margin]
    margin = 80
    x_min, x_max = coords[:, 0].min(), coords[:, 0].max()
    y_min, y_max = coords[:, 1].min(), coords[:, 1].max()

    x_range = max(x_max - x_min, 1e-6)
    y_range = max(y_max - y_min, 1e-6)

    coords[:, 0] = margin + (coords[:, 0] - x_min) / x_range * (width - 2 * margin)
    coords[:, 1] = margin + (coords[:, 1] - y_min) / y_range * (height - 2 * margin)

    return coords.astype(np.float32)


def _export_knowledge_graph(
    entries: list[dict],
    embeddings: np.ndarray,
    data_dir: Path,
    threshold: float = GRAPH_DEFAULT_THRESHOLD,
    max_edges_per_node: int = GRAPH_DEFAULT_MAX_EDGES,
):
    """预计算记忆图谱边 + PCA 2D 坐标，输出 JSON 供 GUI 直接使用。

    Args:
        entries: 节点列表 [{id, table, category, content}]
        embeddings: 向量矩阵 (N, 384)
        data_dir: 输出目录
        threshold: 相似度阈值
        max_edges_per_node: 每节点最大连边数
    """
    n = len(embeddings)
    sims = embeddings @ embeddings.T

    # ── PCA 降维到 2D 坐标 ──
    coords_2d = _compute_2d_coordinates(embeddings)

    # 导出全部相似度对 (无阈值过滤, 供 GUI 力引擎使用)
    all_pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            all_pairs.append({
                "source": i,
                "target": j,
                "weight": round(float(sims[i][j]), 4),
            })

    # 传统边列表 (保留用于显示, 仅高相似度)
    edges = []
    for i in range(n):
        row = [(j, float(sims[i][j])) for j in range(n) if j != i and sims[i][j] >= threshold]
        row.sort(key=lambda x: -x[1])
        for j, s in row[:max_edges_per_node]:
            if i < j:
                edges.append({"source": i, "target": j, "weight": round(s, 4)})

    from datetime import datetime
    graph = {
        "entries": [
            {
                "id": e["id"],
                "table": e["table"],
                "category": e["category"],
                "content": e["content"],
                "created_at": e.get("created_at", ""),
                "x": float(coords_2d[i][0]),
                "y": float(coords_2d[i][1]),
            }
            for i, e in enumerate(entries)
        ],
        "edges": edges,
        "all_pairs": all_pairs,
        "sim_matrix": [round(float(sims[i][j]), 4) for i in range(n) for j in range(n)],
        "meta": {
            "total_nodes": n,
            "total_edges": len(edges),
            "total_pairs": len(all_pairs),
            "max_edges_per_node": max_edges_per_node,
            "threshold": threshold,
            "layout": "pca",
            "canvas_size": {"width": 1500, "height": 1200},
            "updated_at": datetime.now().isoformat(),
        }
    }

    path = data_dir / "knowledge_graph.json"
    path.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
    print(f"[MemOS] 记忆图谱已导出: {n} 节点, {len(edges)} 边, {len(all_pairs)} 对, {path}")


def read_knowledge_index(index_path: str) -> dict | None:
    """读取记忆图谱向量索引文件，返回 {entries, embeddings}。"""
    p = Path(index_path)
    if not p.exists():
        return None
    data = np.load(index_path, allow_pickle=True)
    created_ats = data["created_ats"].tolist() if "created_ats" in data else []
    return {
        "embeddings": data["embeddings"],
        "entries": [
            {
                "id": int(eid),
                "table": str(tbl),
                "category": str(cat),
                "content": str(cont),
                "created_at": str(ca) if ca is not None else "",
            }
            for eid, tbl, cat, cont, ca in zip(
                data["entry_ids"], data["tables"], data["categories"],
                data["contents"],
                created_ats + [""] * max(0, len(data["entry_ids"]) - len(created_ats)),
            )
        ],
        "max_edges_per_node": int(data["max_edges_per_node"][0]) if "max_edges_per_node" in data else GRAPH_DEFAULT_MAX_EDGES,
    }


def recompute_graph_edges(
    index_path: str,
    output_path: str,
    max_edges_per_node: int,
    threshold: float = GRAPH_DEFAULT_THRESHOLD,
):
    """重新计算图谱边 + PCA 2D 坐标（不重新编码，仅按新 max_edges 过滤）。

    用于 GUI 调整 top-N 时快速更新，无需重新编码向量。
    """
    data = np.load(index_path, allow_pickle=True)
    embeddings = data["embeddings"]
    entries = [
        {
            "id": int(eid),
            "table": str(tbl),
            "category": str(cat),
            "content": str(cont),
            "created_at": str(ca) if ca is not None else "",
        }
        for eid, tbl, cat, cont, ca in zip(
            data["entry_ids"], data["tables"], data["categories"],
            data["contents"],
            data["created_ats"] if "created_ats" in data else [""] * len(data["entry_ids"]),
        )
    ]

    n = len(embeddings)
    sims = embeddings @ embeddings.T

    # ── PCA 降维到 2D 坐标 ──
    coords_2d = _compute_2d_coordinates(embeddings)

    # 全部相似度对
    all_pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            all_pairs.append({
                "source": i,
                "target": j,
                "weight": round(float(sims[i][j]), 4),
            })

    edges = []
    for i in range(n):
        row = [(j, float(sims[i][j])) for j in range(n) if j != i and sims[i][j] >= threshold]
        row.sort(key=lambda x: -x[1])
        for j, s in row[:max_edges_per_node]:
            if i < j:
                edges.append({"source": i, "target": j, "weight": round(s, 4)})

    from datetime import datetime
    graph = {
        "entries": [
            {
                "id": e["id"],
                "table": e["table"],
                "category": e["category"],
                "content": e["content"],
                "created_at": e.get("created_at", ""),
                "x": float(coords_2d[i][0]),
                "y": float(coords_2d[i][1]),
            }
            for i, e in enumerate(entries)
        ],
        "edges": edges,
        "all_pairs": all_pairs,
        "sim_matrix": [round(float(sims[i][j]), 4) for i in range(n) for j in range(n)],
        "meta": {
            "total_nodes": n,
            "total_edges": len(edges),
            "total_pairs": len(all_pairs),
            "max_edges_per_node": max_edges_per_node,
            "threshold": threshold,
            "layout": "pca",
            "canvas_size": {"width": 1500, "height": 1200},
            "updated_at": datetime.now().isoformat(),
        }
    }

    path = Path(output_path)
    path.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
    print(f"[MemOS] 图谱边已重算: {n} 节点, {len(edges)} 边, {len(all_pairs)} 对, max_edges={max_edges_per_node}")
