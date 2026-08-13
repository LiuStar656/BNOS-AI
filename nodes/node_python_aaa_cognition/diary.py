"""
Diary 日记联动 MemOS 模块

触发：次日首条对话（由 main.py _on_text 调用）
行为：写前一天日记 → MemOS 向量索引 → self_cognition 更新
LLM 调用：每天 +1
"""
import sqlite3
import threading
from datetime import datetime

import memos

_last_diary_date = None  # 最后写日记的日期，用于次日检测


def check_and_write_diary(today: str, db_path: str) -> bool:
    """次日首条对话时调用。由 main.py _on_text 在写用户输入后调用。

    触发状态（最后日记日期）持久化到 self_info 表，
    节点重启后仍能正确补写漏掉的日记。

    Args:
        today: 当前日期 "%Y-%m-%d"
        db_path: 数据库路径

    Returns:
        True=触发了日记写入（无内容日期会被跳过）, False=跳过
    """
    global _last_diary_date

    # 内存无状态（首次调用/节点重启）：先从 DB 恢复持久化的最后日记日期
    if _last_diary_date is None:
        _last_diary_date = _load_last_diary_date(db_path)
        if _last_diary_date is None:
            # 从未写过日记：补写昨天（_write_diary 内部会跳过无内容日期）
            yesterday = _calc_yesterday(today)
            if not _diary_exists(db_path, yesterday):
                threading.Thread(
                    target=_write_diary, args=(db_path, yesterday), daemon=True
                ).start()
            _last_diary_date = today
            _save_last_diary_date(db_path, today)
            return True

    if today == _last_diary_date:
        return False  # 同一天，跳过

    yesterday = _calc_yesterday(today)

    # 前一天日记已存在 → 仅推进指针
    if _diary_exists(db_path, yesterday):
        _last_diary_date = today
        _save_last_diary_date(db_path, today)
        return False

    # 写前一天日记（后台线程），并推进持久化指针
    threading.Thread(
        target=_write_diary, args=(db_path, yesterday), daemon=True
    ).start()
    _last_diary_date = today
    _save_last_diary_date(db_path, today)
    return True


def _load_last_diary_date(db_path: str):
    """从 self_info 表读取持久化的最后日记日期，无则返回 None"""
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT value FROM self_info WHERE key='last_diary_date' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def _save_last_diary_date(db_path: str, date_str: str):
    """将最后日记日期持久化到 self_info 表，防止节点重启丢失触发状态"""
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE self_info SET value=?, created_at=datetime('now','localtime') "
            "WHERE key='last_diary_date'",
            (date_str,),
        )
        if conn.total_changes == 0:
            conn.execute(
                "INSERT INTO self_info(conversation_id, identity_key, key, value, created_at) "
                "VALUES('default', 'gui:default', 'last_diary_date', ?, datetime('now','localtime'))",
                (date_str,),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _write_diary(db_path: str, yesterday: str):
    """生成前一天日记（后台线程执行，不阻塞对话）"""
    try:
        conn = sqlite3.connect(db_path)

        # 1. 收集前一天的内容
        events = _get_day_events(conn, yesterday)
        conversations = _get_day_conversations(conn, yesterday)
        mood = _get_day_mood(conn, yesterday)

        if not events and not conversations and not mood:
            conn.close()
            return  # 没有内容，不写

        diary_prompt = (
            f"日期：{yesterday}\n\n"
            f"今天的事件：\n{events}\n\n"
            f"今天的对话记录：\n{conversations}\n\n"
            f"今天的心情：{mood}\n\n"
            f"请根据以上信息，以第一人称写一段日记总结今天的经历和感受。"
        )

        # 2. 写 output_diary_prompt.json — 由 LLM 节点通过 diary_prompt 端口消费
        import json, os
        from config import resolve
        diary_prompt_path = resolve("./output_diary_prompt.json")
        with open(diary_prompt_path, "w", encoding="utf-8") as f:
            json.dump({
                "data_type": "prompt",
                "content": diary_prompt,
                "source": "diary",
                "request_id": f"diary_{yesterday}",
            }, f, ensure_ascii=False)

        # 注意：此处无法同步等待 LLM 返回，
        # diary 文本会在 MemOS 下次 rebuild 时被索引
        # self_cognition 更新需要等 LLM 返回后由 _on_parsed 处理

        conn.close()
    except Exception:
        pass


def _diary_exists(db_path: str, date_str: str) -> bool:
    """检查指定日期是否已有日记"""
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT id FROM diaries WHERE date=? LIMIT 1",
            (date_str,),
        ).fetchall()
        conn.close()
        return len(rows) > 0
    except Exception:
        return False


def _calc_yesterday(today: str) -> str:
    """计算昨天日期"""
    dt = datetime.strptime(today, "%Y-%m-%d")
    return datetime(dt.year, dt.month, dt.day - 1).strftime("%Y-%m-%d")


def _get_day_events(conn, date_str: str) -> str:
    """从 event_summary 表取指定日期的事件"""
    rows = conn.execute(
        "SELECT summary FROM event_summary WHERE date(created_at) = ? ORDER BY id",
        (date_str,),
    ).fetchall()
    return "\n".join(f"- {r[0]}" for r in rows) if rows else "（无）"


def _get_day_conversations(conn, date_str: str) -> str:
    """从 long_term_memory 取指定日期的对话"""
    rows = conn.execute(
        "SELECT role, content FROM long_term_memory WHERE date(created_at) = ? ORDER BY id LIMIT 50",
        (date_str,),
    ).fetchall()
    if not rows:
        return "（无）"
    lines = []
    for role, content in rows:
        label = "用户" if role == "user" else "AI" if role == "assistant" else "工具"
        lines.append(f"  {label}: {content[:200]}")
    return "\n".join(lines)


def _get_day_mood(conn, date_str: str) -> str:
    """从 feelings 表聚合指定日期的心情"""
    rows = conn.execute(
        "SELECT mood FROM feelings WHERE date(created_at) = ? AND mood IS NOT NULL AND mood != ''",
        (date_str,),
    ).fetchall()
    if not rows:
        return "（无）"
    # 统计心情词频
    counts = {}
    for (mood,) in rows:
        counts[mood] = counts.get(mood, 0) + 1
    sorted_moods = sorted(counts.items(), key=lambda x: -x[1])
    return ", ".join(f"{m}({c}次)" for m, c in sorted_moods[:3])
