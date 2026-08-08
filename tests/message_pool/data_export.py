# -*- coding: utf-8 -*-
"""实验数据导出（原始数据库按表分类 + 聊天历史渲染）。

- export_agent_db：单个 Agent 的原始 SQLite 数据库按表分类导出到
  `runs/.../db/{agent_id}_final/`（每表一个 JSON + 原始 sqlite 副本 +
  _manifest.json），格式与认知演化实验 `export_db` 对齐。
- export_all_agent_dbs：遍历所有 Agent 导出。
- render_chat_history_md：把 `chat_history.jsonl` 渲染为人类可读 Markdown。
"""
import json
import os
import shutil
import sqlite3
import time


def export_agent_db(db_path: str, out_dir: str, agent_id: str) -> dict:
    """按表分类导出单个 Agent 的原始数据库。

    Returns:
        {"tables": {表名: 行数}, "export_dir": 导出目录}
    """
    export_dir = os.path.join(out_dir, f"{agent_id.replace(':', '_')}_final")
    os.makedirs(export_dir, exist_ok=True)
    # 原始 sqlite 一并留档，保证可复查
    try:
        shutil.copy2(db_path, os.path.join(export_dir, "data.sqlite"))
    except Exception:
        pass
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    meta = {"agent": agent_id,
            "export_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tables": {}}
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (tname,) in tables:
            rows = conn.execute(f'SELECT * FROM "{tname}"').fetchall()
            cols = [d["name"] for d in conn.execute(
                f'PRAGMA table_info("{tname}")').fetchall()]
            records = [dict(zip(cols, r)) for r in rows]
            with open(os.path.join(export_dir, f"{tname}.json"), "w",
                      encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=1, default=str)
            meta["tables"][tname] = {"rows": len(records), "file": f"{tname}.json"}
        with open(os.path.join(export_dir, "_manifest.json"), "w",
                  encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
    finally:
        conn.close()
    return meta


def export_all_agent_dbs(agents, run_dir: str, db_sub: str = "db") -> dict:
    """遍历导出所有 Agent 的原始数据库（按表分类）。

    Returns:
        {agent_id: export_meta}
    """
    db_dir = os.path.join(run_dir, db_sub)
    os.makedirs(db_dir, exist_ok=True)
    result = {}
    for agent in agents:
        result[agent.agent_id] = export_agent_db(
            agent.db_path, db_dir, agent.agent_id)
    return result


def render_chat_history_md(run_dir: str, out_name: str = "chat_history.md") -> str:
    """把 chat_history.jsonl 渲染为人类可读 Markdown（返回输出文件路径）。

    会话视角：用户发言（左）与 Agent 广播（右）按时间顺序交错展示。
    """
    src = os.path.join(run_dir, "chat_history.jsonl")
    dst = os.path.join(run_dir, out_name)
    if not os.path.exists(src):
        return ""
    lines = []
    with open(src, encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            e = json.loads(raw)
            role = e.get("role")
            if role == "user":
                lines.append(f"**[{e.get('user_id')}]** {e.get('content', '')}")
            elif role == "agent":
                stage = e.get("stage")
                prefix = f"（{stage}）" if stage else ""
                lines.append(f"> **[{e.get('agent_id')}]{prefix}** {e.get('content', '')}")
            elif role == "topic":
                lines.append(f"> ## 📢 平台话题：{e.get('content', '')}")
            elif role == "system":
                lines.append(f"> ## ⏹ 平台：{e.get('content', '')}")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("# 消息池聊天历史\n\n" + "\n\n".join(lines) + "\n")
    return dst
