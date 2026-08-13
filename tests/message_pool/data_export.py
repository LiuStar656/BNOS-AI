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


def _load_decision_map(run_dir: str) -> dict:
    """decisions.jsonl → {(round, agent): decision}。

    供聊天历史渲染标注"回应上下文/回应对象"使用。
    """
    path = os.path.join(run_dir, "decisions.jsonl")
    if not os.path.exists(path):
        return {}
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                if not raw.strip():
                    continue
                d = json.loads(raw)
                if d.get("round") is not None and d.get("agent"):
                    out[(d["round"], d["agent"])] = d
    except Exception:
        pass
    return out


def _reconstruct_round_batches(run_dir: str, decisions: dict) -> dict:
    """旧数据回退：重建每轮批次的消息作者（新数据用 decision.batch_context，不走到这里）。

    原理：消息池按（优先级降序，时间正序）弹批，同轮全部 Agent 共享同一批
    （batch_size 相同）；每轮弹批边界取该轮最早决策时间戳（弹批发生在决策之前）。
    仅用于展示"回应上下文"，属于近似重建，不作为精确数据依据。
    """
    src = os.path.join(run_dir, "chat_history.jsonl")
    if not os.path.exists(src):
        return {}
    # 每轮 batch_size + 最早决策 ts（弹批边界）
    rounds: dict[int, dict] = {}
    for (r, _agent), d in decisions.items():
        entry = rounds.setdefault(r, {"batch_size": 0, "ts": ""})
        entry["batch_size"] = max(int(d.get("batch_size") or 0), entry["batch_size"])
        dts = d.get("ts", "") or ""
        if dts and (not entry["ts"] or dts < entry["ts"]):
            entry["ts"] = dts
    if not rounds:
        return {}
    # 入池消息流（chat_history 按时间顺序）：用户发言 / 平台话题 / agent 广播回投
    events = []  # (ts, priority, user_id, content)
    with open(src, encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            e = json.loads(raw)
            role = e.get("role")
            if role == "user":
                c = e.get("content", "")
                events.append((e.get("ts", ""), 10 if "@agent" in c else 0,
                               e.get("user_id", ""), c))
            elif role == "topic":
                events.append((e.get("ts", ""), 5, e.get("user_id", "platform"),
                               e.get("content", "")))
            elif role == "agent" and e.get("round_no") is not None:
                events.append((e.get("ts", ""), 0, e.get("agent_id", ""),
                               e.get("content", "")))
            # role=system（话题结束公告）/ 自我介绍（round_no=None）不进入消息池
    events.sort(key=lambda ev: ev[0])
    pool = []
    added = 0
    batches: dict[int, list] = {}
    for r in sorted(rounds):
        bs = rounds[r]["batch_size"]
        bound = rounds[r]["ts"]
        while added < len(events) and events[added][0] < bound:
            pool.append(events[added])
            added += 1
        pool.sort(key=lambda ev: (-ev[1], ev[0]))
        picked = pool[:bs]
        del pool[:bs]
        if picked:
            batches[r] = [{"user_id": ev[2], "content": ev[3][:60]} for ev in picked]
    return batches


def _reply_context_annotation(decision: dict | None, batch: list | None) -> str:
    """生成回应上下文标注：优先 LLM 显式【回应对象】，其次批次消息作者。"""
    if not decision and not batch:
        return ""
    # ① LLM 显式回应对象（v6.2，仅批量模式输出）
    target = (decision or {}).get("回应对象", "") if decision else ""
    if target and str(target).strip():
        t = str(target).strip()
        if "群" in t or "多条" in t or "所有人" in t:
            return "（回应群聊）"
        return f"（回应 {t[:20]}）"
    # ② 批次上下文（新数据 exact / 旧数据重建近似）
    ctx = (decision or {}).get("batch_context") if decision else None
    if not ctx:
        ctx = batch or []
    authors, seen, cnt = [], set(), len(ctx)
    for m in ctx:
        uid = m.get("user_id", "") or "匿名"
        if uid not in seen:
            seen.add(uid)
            authors.append(uid)
        if len(authors) >= 4:
            break
    if not authors:
        return ""
    if cnt == 1:
        return f"（回应上下文：{authors[0]}）"
    tail = f" 等 {cnt} 条" if cnt > len(authors) else f"（{cnt} 条）"
    return f"（回应上下文：{', '.join(authors)}{tail}）"


def render_chat_history_md(run_dir: str, out_name: str = "chat_history.md") -> str:
    """把 chat_history.jsonl 渲染为人类可读 Markdown（返回输出文件路径）。

    会话视角：用户发言（左）与 Agent 广播（右）按时间顺序交错展示。
    v6.2 增强：Agent 发言标注回应上下文（本批消息作者 / LLM 显式回应对象），
    解决"看不出在回答谁"的问题；旧数据（无 batch_context）自动重建近似。
    """
    src = os.path.join(run_dir, "chat_history.jsonl")
    dst = os.path.join(run_dir, out_name)
    if not os.path.exists(src):
        return ""
    decisions = _load_decision_map(run_dir)
    # 仅当存在无 batch_context 的旧决策时才重建批次（新数据直接读决策字段）
    need_rebuild = decisions and any(not d.get("batch_context") for d in decisions.values())
    batches = _reconstruct_round_batches(run_dir, decisions) if need_rebuild else {}
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
                anno = ""
                rn = e.get("round_no")
                if rn is not None and not stage:
                    decision = decisions.get((rn, e.get("agent_id")))
                    batch = batches.get(rn)
                    anno = _reply_context_annotation(decision, batch)
                lines.append(
                    f"> **[{e.get('agent_id')}]{prefix}{anno}** {e.get('content', '')}")
            elif role == "topic":
                lines.append(f"> ## 📢 平台话题：{e.get('content', '')}")
            elif role == "system":
                lines.append(f"> ## ⏹ 平台：{e.get('content', '')}")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("# 消息池聊天历史\n\n" + "\n\n".join(lines) + "\n")
    return dst
