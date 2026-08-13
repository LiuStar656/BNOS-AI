# -*- coding: utf-8 -*-
"""话题报告生成器：话题结束后收集 Agent 记忆，生成量化分析报告。

对齐 [WIP]-实验设计方案.md 的采集方法（E3/E4 记忆与人格相关指标）：
    - 相互认知记忆：other_cognition 表按 user_id 分组，判断 Agent 之间是否
      形成对彼此的认知（双向认知矩阵 + 内容摘录）
    - 人格漂移倾向：初始种子（_run_meta.json 的 seeds，缺失时回退 decisions.jsonl
      首条 personality 快照）→ 最终向量（personality_seed 表）的欧氏距离与各维变化
    - 自我认知 / 情绪轨迹 / 沉淀 / self_info（E3 采集指标表）

输入：run_dir（runs/...，须含 db/agent_{i}.sqlite 与可选 _run_meta.json / decisions.jsonl）
输出：run_dir/topic_report.md

用法：
    python tests/message_pool/topic_report.py <run_dir>          # 独立运行
    from message_pool.topic_report import generate_topic_report  # 平台收尾调用

依赖：仅标准库（sqlite3 / json / glob），不加载 AAA 节点模型。
"""
import glob
import json
import math
import os
import sqlite3
import time

# ── 人格四维顺序 ────────────────────────────────────────────────
PERSONA_DIMS = ("warmth", "playfulness", "directness", "curiosity")
# 漂移倾向阈值（欧氏距离 ≥ 0.05 记为"有漂移倾向"，对齐方案 E5 一致性判定）
DRIFT_THRESHOLD = 0.05

# ── 自我认知关键词维度（对齐方案 E3 关键词频率指标） ─────────────
COGNITION_KEYWORDS = {
    "孤独/内向": ["孤独", "内向", "一个人", "安静", "寂寞", "独处", "不善"],
    "社交/外向": ["社交", "朋友", "聊天", "交流", "热闹", "喜欢和人", "开朗"],
    "温暖/关怀": ["温暖", "关心", "温和", "温柔", "关怀", "体贴", "倾听"],
    "直接/克制": ["直接", "克制", "冷静", "沉稳", "理性", "一针见血"],
    "好奇/学习": ["好奇", "学习", "探索", "新鲜", "兴趣", "求知"],
}


# ── 数据读取 ─────────────────────────────────────────────────────
def _load_meta(run_dir: str) -> dict:
    """读取 _run_meta.json；缺失时返回空 dict。"""
    path = os.path.join(run_dir, "_run_meta.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _agent_dbs(run_dir: str) -> list[tuple[str, str]]:
    """从 run_dir/db/agent_*.sqlite 推断 Agent 列表。

    Returns:
        [(identity_key, db_path)]，按编号排序（agent:0 → agent:9）。
    """
    dbs = glob.glob(os.path.join(run_dir, "db", "agent_*.sqlite"))
    # 排除导出目录副本（basename 判断，避免 run_dir 目录名含 "_final" 时误伤）
    dbs = [d for d in dbs if "_final" not in os.path.basename(d)]

    def _num(p: str) -> int:
        base = os.path.basename(p)[len("agent_"):-len(".sqlite")]
        try:
            return int(base)
        except ValueError:
            return 10 ** 9

    dbs.sort(key=_num)
    return [(f"agent:{_num(p)}", p) for p in dbs]


def _db_conn(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _read_personality(db_path: str, identity: str) -> dict | None:
    """读取 personality_seed 表最新向量；无记录返回 None。"""
    try:
        conn = _db_conn(db_path)
        try:
            row = conn.execute(
                "SELECT warmth, playfulness, directness, curiosity "
                "FROM personality_seed WHERE identity_key=? ORDER BY rowid DESC LIMIT 1",
                (identity,)).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {d: round(float(row[d]), 4) for d in PERSONA_DIMS}
    except Exception:
        return None


def _read_other_cognition(db_path: str, identity: str) -> dict[str, list[str]]:
    """读取 other_cognition 表，按 user_id 分组的认知内容列表。

    v6.6 P0-2：user_id 为空（""，消息池批量模式的归因污染 / 无明确对象）
    的条目过滤掉——空键会污染相互认知矩阵与网络演化统计。GUI 全局兜底
    认知也一并排除：实验报告只关心"对明确对象"的认知。
    """
    out: dict[str, list[str]] = {}
    try:
        conn = _db_conn(db_path)
        try:
            rows = conn.execute(
                "SELECT user_id, content FROM other_cognition "
                "WHERE identity_key=? ORDER BY rowid",
                (identity,)).fetchall()
        finally:
            conn.close()
        for r in rows:
            uid = (r["user_id"] or "").strip()
            if not uid:
                continue
            out.setdefault(uid, []).append(r["content"])
    except Exception:
        pass
    return out


def _read_counts(db_path: str, identity: str) -> dict:
    """E3 采集指标：self_cognition / event_summary / self_info / feelings 条数 + 情绪轨迹。"""
    out = {"self_cognition": 0, "event_summary": 0, "self_info": 0,
           "feelings": 0, "mood_first": None, "mood_last": None,
           "mood_avg": None, "mood_n": 0}
    try:
        conn = _db_conn(db_path)
        try:
            out["self_cognition"] = conn.execute(
                "SELECT COUNT(*) FROM self_cognition WHERE identity_key=?", (identity,)).fetchone()[0]
            out["event_summary"] = conn.execute(
                "SELECT COUNT(*) FROM event_summary WHERE identity_key=?", (identity,)).fetchone()[0]
            out["self_info"] = conn.execute(
                "SELECT COUNT(*) FROM self_info WHERE identity_key=?", (identity,)).fetchone()[0]
            out["feelings"] = conn.execute(
                "SELECT COUNT(*) FROM feelings WHERE identity_key=?", (identity,)).fetchone()[0]
            rows = conn.execute(
                "SELECT mood_value FROM mood_value WHERE identity_key=? "
                "ORDER BY rowid", (identity,)).fetchall()
            if rows:
                vals = [float(r["mood_value"]) for r in rows]
                out["mood_first"] = round(vals[0], 4)
                out["mood_last"] = round(vals[-1], 4)
                out["mood_avg"] = round(sum(vals) / len(vals), 4)
                out["mood_n"] = len(vals)
        finally:
            conn.close()
    except Exception:
        pass
    return out


def _read_self_cognition_texts(db_path: str, identity: str) -> list[str]:
    """读取 self_cognition 全部内容（关键词分布用）。"""
    try:
        conn = _db_conn(db_path)
        try:
            rows = conn.execute(
                "SELECT content FROM self_cognition WHERE identity_key=?", (identity,)).fetchall()
        finally:
            conn.close()
        return [r["content"] for r in rows]
    except Exception:
        return []


def _initial_seed(meta: dict, identity: str) -> dict | None:
    """初始种子：_run_meta.json 的 seeds[identity]；缺失返回 None。"""
    seeds = meta.get("seeds") or {}
    entry = seeds.get(identity) or {}
    vec = entry.get("vector") if isinstance(entry, dict) else None
    if isinstance(vec, dict) and all(d in vec for d in PERSONA_DIMS):
        return {d: round(float(vec[d]), 4) for d in PERSONA_DIMS}
    return None


def _decisions_first_personality(run_dir: str, identity: str) -> dict | None:
    """回退：decisions.jsonl 首条 personality 快照作为初始种子。"""
    path = os.path.join(run_dir, "decisions.jsonl")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                if not raw.strip():
                    continue
                d = json.loads(raw)
                if d.get("agent") == identity and d.get("personality"):
                    p = d["personality"]
                    return {dim: round(float(p.get(dim, 0)), 4) for dim in PERSONA_DIMS}
    except Exception:
        pass
    return None


def _euclidean(a: dict, b: dict) -> float:
    return math.sqrt(sum((a[d] - b[d]) ** 2 for d in PERSONA_DIMS))


def _drift_detail(start: dict, end: dict) -> dict:
    """返回各维变化量 {dim: delta}（仅显示非零）。"""
    return {d: round(end[d] - start[d], 4)
            for d in PERSONA_DIMS
            if abs(end[d] - start[d]) >= 1e-6}


def _speech_stats(run_dir: str, identity: str) -> dict:
    """从 decisions.jsonl 统计 reply / silent / error 次数。

    v6.3 P0-1：error（LLM/AAA 调用失败）独立统计，不进 silent——
    否则 402 等失败会被当成"主动沉默"，静默率指标被污染。
    """
    stats = {"reply": 0, "silent": 0, "error": 0}
    path = os.path.join(run_dir, "decisions.jsonl")
    if not os.path.exists(path):
        return stats
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                if not raw.strip():
                    continue
                d = json.loads(raw)
                if d.get("agent") == identity:
                    act = d.get("action")
                    if act == "reply":
                        stats["reply"] += 1
                    elif act == "silent":
                        stats["silent"] += 1
                    elif act == "error":
                        stats["error"] += 1
    except Exception:
        pass
    return stats


def _load_llm_stats(run_dir: str) -> dict:
    """读取 llm_stats.json（API 调用量统计）；缺失/异常返回空 dict。"""
    path = os.path.join(run_dir, "llm_stats.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _render_llm_stats(stats: dict, identities: list[str]) -> str:
    """渲染 API 调用量统计节：总量 + 各 Agent 明细。"""
    if not stats:
        return "- 本次运行未记录 API 调用量（缺少 llm_stats.json）。"
    per = stats.get("per_agent") or {}
    total = int(stats.get("total", 0))
    direct = int(stats.get("platform_direct", 0))
    sub_total = total - direct
    rows = []
    for i in identities:
        calls = int(per.get(i, 0))
        ratio = f"{calls / total * 100:.1f}%" if total else "-"
        rows.append(f"| {i} | {calls} | {ratio} |")
    table = ("| Agent | API 调用量 | 占比 |\n"
             "|---|---|---|\n" + "\n".join(rows))
    mode_note = "（假 LLM 模拟调用，未调真实 API）" if stats.get("fake_llm") else ""
    return (f"- 本次实验 API 调用总量：**{total}** 次{mode_note}"
            f"（模式：{stats.get('mode', '?')}）\n"
            f"- AAA 子进程内（决策 + 后台 review）：{sub_total} 次；"
            f"平台直连（自我介绍等）：{direct} 次\n\n{table}")


def _keyword_stats(texts: list[str]) -> dict[str, int]:
    """统计自我认知文本中各维度关键词命中次数。"""
    joined = " ".join(texts)
    return {dim: sum(joined.count(kw) for kw in kws)
            for dim, kws in COGNITION_KEYWORDS.items()}


# ── 报告渲染 ─────────────────────────────────────────────────────
def _render_mutual_matrix(others: dict[str, dict[str, list[str]]],
                          identities: list[str]) -> tuple[str, str]:
    """渲染相互认知矩阵表 + 双向判定说明。

    Returns:
        (matrix_md, verdict_md)
    """
    ids = [i for i in identities]
    header = "| 认知方 \\ 对象 |" + "".join(f" {i} |" for i in ids) + " 其他 |"
    sep = "|" + "---|" * (len(ids) + 2)
    rows = []
    for src in ids:
        cells = [str(len((others.get(src) or {}).get(dst, []))) for dst in ids]
        other_cnt = sum(len(v) for k, v in (others.get(src) or {}).items()
                        if k not in ids)
        rows.append(f"| {src} | " + " | ".join(cells) + f" | {other_cnt} |")
    matrix = header + "\n" + sep + "\n" + "\n".join(rows)

    verdict = []
    pairs = [(ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))]
    if not pairs:
        verdict.append("- Agent 数量不足 2，无法判定相互认知。")
    for a, b in pairs:
        a2b = len((others.get(a) or {}).get(b, []))
        b2a = len((others.get(b) or {}).get(a, []))
        if a2b > 0 and b2a > 0:
            verdict.append(f"- {a} → {b}：{a2b} 条 ✅ | {b} → {a}：{b2a} 条 ✅ "
                           f"→ **相互认知已形成**")
        elif a2b > 0:
            verdict.append(f"- {a} → {b}：{a2b} 条 ✅ | {b} → {a}：{b2a} 条 ❌ "
                           f"→ 单向认知（{b} 未形成对 {a} 的认知）")
        elif b2a > 0:
            verdict.append(f"- {a} → {b}：{a2b} 条 ❌ | {b} → {a}：{b2a} 条 ✅ "
                           f"→ 单向认知（{a} 未形成对 {b} 的认知）")
        else:
            verdict.append(f"- {a} → {b}：0 条 | {b} → {a}：0 条 → **未形成相互认知**")
    return matrix, "\n".join(verdict)


def _render_other_detail(others: dict[str, dict[str, list[str]]],
                         identities: list[str]) -> str:
    """渲染相互认知内容摘录（Agent 对 Agent 的条目全文，其他对象仅计数）。"""
    lines = []
    for src in identities:
        src_map = others.get(src) or {}
        agent_targets = {dst: src_map[dst] for dst in identities if dst in src_map}
        if not agent_targets:
            lines.append(f"#### {src}\n\n- 未形成对其他 Agent 的认知记录。")
            continue
        lines.append(f"#### {src}")
        for dst, contents in agent_targets.items():
            lines.append(f"\n**对 {dst}（{len(contents)} 条）**")
            for i, c in enumerate(contents, 1):
                lines.append(f"{i}. {c}")
        others_cnt = {k: len(v) for k, v in src_map.items() if k not in identities}
        if others_cnt:
            lines.append("\n_其他对象（仅计数）："
                         + "、".join(f"{k}×{v}" for k, v in others_cnt.items())
                         + "_")
    return "\n\n".join(lines)


def _render_personality_table(starts: dict, ends: dict) -> tuple[str, str]:
    """渲染人格漂移表 + 判定说明。"""
    ids = list(starts.keys())
    rows = []
    drift_rows = []
    for i in ids:
        s, e = starts.get(i), ends.get(i)
        if not s or not e:
            rows.append(f"| {i} | 初始未记录 | {e or '未记录'} | - | - |")
            continue
        dist = _euclidean(s, e)
        detail = _drift_detail(s, e)
        delta = "、".join(f"{d}{v:+.2f}" for d, v in detail.items()) if detail else "无变化"
        mark = "⚠️ 有漂移倾向" if dist >= DRIFT_THRESHOLD else "—"
        rows.append(f"| {i} | {list(s.values())} | {list(e.values())} | "
                    f"{dist:.4f} | {delta} {mark} |")
    table = ("| Agent | 初始向量 | 最终向量 | 欧氏距离 | 各维变化 |\n"
             "|---|---|---|---|---|\n" + "\n".join(rows))

    verdict = []
    drifted = [i for i in ids
               if starts.get(i) and ends.get(i)
               and _euclidean(starts[i], ends[i]) >= DRIFT_THRESHOLD]
    if not ids:
        verdict.append("- 未发现可用的 Agent 向量数据。")
    elif drifted:
        verdict.append(f"- 有漂移倾向的 Agent：{', '.join(drifted)} "
                       f"（欧氏距离 ≥ {DRIFT_THRESHOLD}）→ 人格正在演化")
    else:
        verdict.append(f"- 所有 Agent 漂移量 < {DRIFT_THRESHOLD} → 本轮未观测到显著人格漂移"
                       "（短话题通常不足以触发演化门槛，需多轮话题累积观察）")
    return table, "\n".join(verdict)


def _render_e3_table(identities: list[str], counts: dict, keywords: dict,
                     speeches: dict) -> str:
    """E3 采集指标汇总表。"""
    rows = []
    for i in identities:
        c = counts.get(i) or {}
        kw = keywords.get(i) or {}
        kw_hit = [(d, v) for d, v in sorted(kw.items(), key=lambda x: -x[1]) if v > 0]
        kw_top = "、".join(f"{d}×{v}" for d, v in kw_hit[:3]) if kw_hit else "—"
        sp = speeches.get(i) or {}
        rows.append(
            f"| {i} | {c.get('self_cognition', 0)} | {c.get('event_summary', 0)} | "
            f"{c.get('self_info', 0)} | {c.get('feelings', 0)} | "
            f"{c.get('mood_first', '-')} → {c.get('mood_last', '-')} "
            f"(均值 {c.get('mood_avg', '-')}) | {kw_top or '—'} | "
            f"{sp.get('reply', 0)} / {sp.get('silent', 0)} |")
    return ("| Agent | 自我认知 | 沉淀(event) | self_info | 情感记录 | "
            "情绪轨迹(首→末) | 自我认知关键词 Top3 | 发言 reply/silent |\n"
            "|---|---|---|---|---|---|---|---|\n" + "\n".join(rows))


# ── v6.6 数据采集统计节（数据采集价值清单与方案.md 对齐）────────────
def _load_decisions(run_dir: str) -> list[dict]:
    """读取 decisions.jsonl 全部决策（按写入顺序）。"""
    path = os.path.join(run_dir, "decisions.jsonl")
    if not os.path.exists(path):
        return []
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                if raw.strip():
                    out.append(json.loads(raw))
    except Exception:
        pass
    return out


def _load_evolution(run_dir: str) -> dict:
    """读取 evolution.json；缺失返回空 dict。"""
    path = os.path.join(run_dir, "evolution.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _render_position_bias(decisions: list[dict]) -> str:
    """批次位置-回应对象对照（数据采集 P2-6，末位偏置量化）。

    对每条 reply：回应对象在 batch_context 中的位置 vs 批次末位。
    reply_target_pos==-1 表示回应对象不在本批（如回应平台话题/历史消息）。
    """
    rows = []
    n_reply = n_valid = n_last = 0
    for d in decisions:
        if d.get("action") != "reply" or not d.get("回应对象"):
            continue
        n_reply += 1
        bc = d.get("batch_context") or []
        pos = d.get("reply_target_pos")
        last_author = d.get("batch_last_author", "")
        target = str(d.get("回应对象", "")).strip()
        if target in ("群聊", "多条", "所有人"):
            rows.append(f"| r{d.get('round')} | {d.get('agent')} | {target} | 群聊/多条 | {last_author} | — |")
            continue
        if pos is not None and pos >= 0:
            n_valid += 1
            is_last = (pos == len(bc) - 1)
            if is_last:
                n_last += 1
            rows.append(f"| r{d.get('round')} | {d.get('agent')} | {target} | {pos} | "
                        f"{last_author} | {'✅ 末位' if is_last else '—'} |")
        else:
            rows.append(f"| r{d.get('round')} | {d.get('agent')} | {target} | 不在本批 | "
                        f"{last_author} | — |")
    if not rows:
        return "- 无有效 reply 决策（缺少 回应对象 / batch_context 数据）。"
    table = ("| 轮次 | Agent | 回应对象 | 对象在批次位置 | 末位作者 | 是否末位 |\n"
             "|---|---|---|---|---|---|\n" + "\n".join(rows))
    rate = f"{n_last / n_valid * 100:.1f}%" if n_valid else "-"
    return (f"- **末位偏置量化**：reply {n_reply} 条，其中可定位批次位置的 {n_valid} 条，"
            f"回应末位 {n_last} 条 → **末位回应率 {rate}**\n"
            f"- `reply_target_pos` = 回应对象在 LLM 实际所见批次（batch_context.seq 唯一"
            f"事实源）中的位置；P0-1 修复后 decisions/events 顺序同源，本统计可信\n\n{table}")


def _render_mention_attribution(decisions: list[dict], identities: list[str]) -> str:
    """@提及响应率 + user_id 归因正确率（数据采集 P1-5）。"""
    mentioned = [d for d in decisions if d.get("mention_targets")]
    m_reply = [d for d in mentioned if d.get("action") == "reply"]
    m_responded = [d for d in m_reply if d.get("mention_responded")]
    replies = [d for d in decisions if d.get("action") == "reply"]
    attr_valid = [d for d in replies
                  if str(d.get("回应对象", "")).strip() not in ("群聊", "多条", "所有人", "")]
    attr_ok = [d for d in attr_valid if d.get("attribution_ok")]
    rows = []
    for aid in identities:
        md = [d for d in mentioned if aid in (d.get("mention_targets") or [])]
        mdr = [d for d in md if d.get("action") == "reply"]
        mdrp = [d for d in mdr if d.get("mention_responded")]
        av = [d for d in attr_valid if d.get("agent") == aid]
        ao = [d for d in av if d.get("attribution_ok")]
        rate = f"{len(mdrp) / len(md) * 100:.0f}%" if md else "-"
        arate = f"{len(ao) / len(av) * 100:.0f}%" if av else "-"
        rows.append(f"| {aid} | {len(md)} | {len(mdr)} | {len(mdrp)} ({rate}) | "
                    f"{len(av)} | {len(ao)} ({arate}) |")
    if not mentioned and not attr_valid:
        return "- 本轮无 @提及 与可判归因的 reply（可能未注入 sim 消息或全部回应群聊）。"
    table = ("| Agent | 被@批次 | @后回复 | @点名回应(率) | 可判归因 | 归因正确(率) |\n"
             "|---|---|---|---|---|---|\n" + "\n".join(rows))
    total_rate = (f"{len(m_responded) / len(mentioned) * 100:.0f}%" if mentioned else "-")
    attr_rate = (f"{len(attr_ok) / len(attr_valid) * 100:.0f}%" if attr_valid else "-")
    return (f"- 全局：被 @ {len(mentioned)} 批，@后回复 {len(m_reply)}，点名者被回应 "
            f"{len(m_responded)}（响应率 {total_rate}）；可判归因 reply {len(attr_valid)} 条，"
            f"归因正确 {len(attr_ok)} 条（**{attr_rate}**）\n"
            f"- `attribution_ok` = 决策 user_id == LLM 声明的回应对象（排除群聊/多条）；"
            f"P0-2 修复后空归因不再写入 other_cognition\n\n{table}")


def _render_mood_behavior(decisions: list[dict], identities: list[str]) -> str:
    """情绪-行为关联（数据采集 P2-7）：mood 值与当次 reply/silent 的交叉统计。"""
    rows = []
    notes = []
    for aid in identities:
        ds = [d for d in decisions if d.get("agent") == aid]
        rep = [d for d in ds if d.get("action") == "reply"]
        sil = [d for d in ds if d.get("action") == "silent"]

        def _avg(lst):
            vals = [float(d.get("mood", 0)) for d in lst if d.get("mood") is not None]
            return f"{sum(vals) / len(vals):.3f}" if vals else "-"

        rows.append(f"| {aid} | {len(rep)} | {_avg(rep)} | {len(sil)} | {_avg(sil)} |")
        # 静默全 0 的 agent 提示情绪更新链路异常（5a30r 中 agent:3 现象）
        if sil and not any(d.get("mood") not in (None, 0) for d in sil):
            notes.append(f"- {aid}：静默决策 mood 恒为 0——情绪更新链路可能未对该 "
                         "agent 生效（需核查心情标签映射）")
    if not rows:
        return "- 无决策数据。"
    table = ("| Agent | reply 次数 | reply 平均 mood | silent 次数 | silent 平均 mood |\n"
             "|---|---|---|---|---|\n" + "\n".join(rows))
    note = "\n".join(notes) if notes else "- 无 mood 恒 0 的静默 agent，情绪链路正常。"
    return table + "\n\n" + note


def _render_memory_hits(decisions: list[dict], identities: list[str]) -> str:
    """记忆检索命中日志统计（数据采集 P0-1）。"""
    rows = []
    n_hit_decisions = 0
    n_hits = 0
    for aid in identities:
        ds = [d for d in decisions if d.get("agent") == aid]
        hd = [d for d in ds if d.get("memory_hits")]
        hits = [h for d in hd for h in (d.get("memory_hits") or [])]
        n_hit_decisions += len(hd)
        n_hits += len(hits)
        avg = (f"{sum(h.get('score', 0) for h in hits) / len(hits):.3f}" if hits else "-")
        rows.append(f"| {aid} | {len(hd)} | {len(hits)} | {avg} |")
    if not rows or n_hits == 0:
        return "- 本轮无记忆检索命中（LLM 未触发【语意检索】，或 MemOS 无匹配条目）。"
    table = ("| Agent | 检索决策数 | 命中条目 | 平均相似度 |\n"
             "|---|---|---|---|\n" + "\n".join(rows))
    return (f"- 共 {n_hit_decisions} 个决策触发记忆检索，命中 {n_hits} 条记忆"
            f"（认知写入 → 检索 → 被采纳的证据链）\n{table}")


def _render_silent_cognition(decisions: list[dict], identities: list[str]) -> str:
    """静默期间的认知更新统计（数据采集 P0-2）：静默≠无认知。"""
    rows = []
    for aid in identities:
        sil = [d for d in decisions if d.get("agent") == aid and d.get("action") == "silent"]
        if not sil:
            continue
        with_thought = [d for d in sil if (d.get("想法") or "").strip()]
        with_cog = [d for d in sil if d.get("silent_cognition_written")]
        sections = {}
        for d in sil:
            for s in (d.get("cognition_sections") or "").split(","):
                if s.strip():
                    sections[s.strip()] = sections.get(s.strip(), 0) + 1
        sec_str = "、".join(f"{k}×{v}" for k, v in sections.items()) if sections else "—"
        rows.append(f"| {aid} | {len(sil)} | {len(with_thought)} | {len(with_cog)} | {sec_str} |")
    if not rows:
        return "- 本轮无静默决策。"
    table = ("| Agent | silent 次数 | 有想法 | 仍写认知 | 认知节分布 |\n"
             "|---|---|---|---|---|\n" + "\n".join(rows))
    return (f"- 静默轮仍在沉淀认知（想法/他人认知/用户记忆）→ 平台差异化理念"
            f"『听而不说 ≠ 无认知』的可量化证据\n{table}")


def _render_trajectory(evo: dict) -> str:
    """人格漂移过程轨迹（数据采集 P0-3）：evolution.json 的 trajectory。"""
    traj = evo.get("trajectory") or {}
    if not traj:
        return "- 本轮无轨迹数据（人格演化未触发或 decisions 无 personality 快照）。"
    blocks = []
    for aid in sorted(traj):
        pts = traj[aid]
        first = pts[0]["vector"] if pts else {}
        moved = next((p["round"] for p in pts
                      if any(abs(p["vector"].get(d, 0) - first.get(d, 0)) > 1e-6
                             for d in PERSONA_DIMS)), None)
        n_points = len(pts)
        last_round = pts[-1]["round"] if pts else "-"
        rows = [f"| {p['round']} | {p['vector'].get('warmth', 0):.4f} | "
                f"{p['vector'].get('playfulness', 0):.4f} | "
                f"{p['vector'].get('directness', 0):.4f} | "
                f"{p['vector'].get('curiosity', 0):.4f} |" for p in pts]
        table = ("| 轮次 | warmth | playfulness | directness | curiosity |\n"
                 "|---|---|---|---|---|\n" + "\n".join(rows))
        move_note = (f"首动轮次：**r{moved}**（第 {pts.index(next(p for p in pts if p['round'] == moved)) + 1} 个采样点）"
                     if moved else "全程未变化")
        blocks.append(f"#### {aid}（{n_points} 个采样点，末轮 r{last_round}；{move_note}）\n\n{table}")
    return "- 每轮决策附带人格向量快照（decisions.personality → trajectory），" \
           "回答『演化是渐进还是突变、从第几轮开始动』\n\n" + "\n\n".join(blocks)


def _render_cognition_timeline(decisions: list[dict], identities: list[str]) -> str:
    """认知网络演化时序（数据采集 P1-4）：逐轮累计互认矩阵（谁认知了谁、何时成对）。"""
    # 边 (a → b, 首见轮次)：决策写了「他人认知」且归因到另一 agent
    first_seen: dict[tuple[str, str], int] = {}
    by_round: dict[int, list[str]] = {}
    for d in decisions:
        if not d.get("user_id"):
            continue
        if d.get("user_id") not in identities:
            continue
        if "他人认知" not in (d.get("cognition_sections") or ""):
            continue
        a, b = d.get("agent"), d.get("user_id")
        r = d.get("round")
        if a == b:
            continue
        if (a, b) not in first_seen:
            first_seen[(a, b)] = r
        by_round.setdefault(r, []).append(f"{a}→{b}")
    if not first_seen:
        return "- 本轮未从决策中解析出 agent 间认知边（需 cognition_sections + 有效归因）。"
    ids = identities
    rows = []
    total_mutual = 0
    for r in sorted(by_round):
        # 累计到本轮：含本轮及之前所有边
        edges = {(a, b) for (a, b), rr in first_seen.items() if rr <= r}
        mutual = 0
        pair_list = []
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                if (a, b) in edges and (b, a) in edges:
                    mutual += 1
                    pair_list.append(f"{a}↔{b}")
        total_mutual = mutual
        new_cnt = len(by_round[r])
        rows.append(f"| r{r} | {new_cnt} | {len(edges)} | {mutual} | "
                    f"{', '.join(pair_list) if pair_list else '—'} |")
    table = ("| 轮次 | 新增认知边 | 累计边数 | 双向认知组数 | 双向组明细 |\n"
             "|---|---|---|---|---|\n" + "\n".join(rows))
    return (f"- 认知网络从稀疏到稠密的时序证据：末轮双向认知组数 **{total_mutual}**\n"
            f"- 边 = 决策写「他人认知」且归因到对方 agent（P0-2 修复后空归因不产生边）\n\n{table}")


# ── 主入口 ───────────────────────────────────────────────────────
def _median(vals: list[float]) -> float:
    """列表（可空）中位数。"""
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _percentile(vals: list[float], q: float) -> float:
    """列表（可空）线性插值百分位。"""
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * q / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _read_interest_judgments(run_dir: str,
                             identities: list[str]) -> dict[str, list[dict]]:
    """读取 interest_judgment 表（v7.0 兴趣门控判定）。

    优先读 data_export 导出的 {agent}_final/interest_judgment.json；
    缺失（旧实验/未导出）时回退直接读原始 sqlite。
    """
    out: dict[str, list[dict]] = {}
    for identity in identities:
        out[identity] = []
        num = identity.split(":")[-1]
        exp = os.path.join(run_dir, "db",
                           f"{identity.replace(':', '_')}_final",
                           "interest_judgment.json")
        if os.path.exists(exp):
            try:
                with open(exp, encoding="utf-8") as f:
                    out[identity] = json.load(f)
                continue
            except Exception:
                pass
        dbp = os.path.join(run_dir, "db", f"agent_{num}.sqlite")
        try:
            conn = _db_conn(dbp)
            try:
                rows = conn.execute(
                    "SELECT * FROM interest_judgment ORDER BY rowid").fetchall()
                out[identity] = [dict(r) for r in rows]
            finally:
                conn.close()
        except Exception:
            pass
    return out


def _render_interest_gate(judgments: dict[str, list[dict]],
                          identities: list[str], meta: dict) -> str:
    """渲染兴趣门控判定采集章节（v7.0）：兴趣值分布 + 过门率 + 判定原因。"""
    gate_cfg = meta.get("interest_gate") or {}
    enabled = gate_cfg.get("enabled")
    threshold = gate_cfg.get("threshold", "?")
    total = sum(len(v) for v in judgments.values())
    if total == 0:
        if enabled is False:
            return "- 兴趣门控已关闭（--no-gate，本实验为 v6.6 全候选决策基线）。"
        return "- 未采集到兴趣判定（interest_judgment 表为空）。"

    rows = []
    all_vals: list[float] = []
    total_pass = total_fail = 0
    reasons: dict[str, int] = {}
    for identity in identities:
        js = judgments.get(identity) or []
        n_pass = sum(1 for j in js if j.get("passed"))
        n_fail = len(js) - n_pass
        vals = [float(j.get("interest_value", 0.0)) for j in js]
        all_vals.extend(vals)
        rows.append(f"| {identity} | {len(js)} | {n_pass} | {n_fail} | "
                    f"{_median(vals):.3f} |")
        total_pass += n_pass
        total_fail += n_fail
        for j in js:
            r = j.get("reason", "?")
            reasons[r] = reasons.get(r, 0) + 1
    table = ("| Agent | 判定数 | 过门 | 未过门(省调用) | 兴趣值中位 |\n"
             "|---|---|---|---|---|\n" + "\n".join(rows))
    pass_rate = total_pass / total * 100 if total else 0.0
    reason_txt = "、".join(f"{k}×{v}" for k, v in sorted(reasons.items()))
    return (f"- 门控配置：{'开启' if enabled else '关闭'} | 阈值 {threshold} | "
            f"模型 {gate_cfg.get('model', '?')}\n"
            f"- 判定总数 {total}，过门 {total_pass}（{pass_rate:.1f}%），"
            f"未过门 {total_fail} 条 → LLM 调用节约 {total_fail} 次\n"
            f"- 兴趣值分布：min {min(all_vals):.3f} / 中位 {_median(all_vals):.3f} / "
            f"p90 {_percentile(all_vals, 90):.3f} / max {max(all_vals):.3f}\n"
            f"- 判定原因分布：{reason_txt}\n"
            f"- 检测文本与兴趣值逐条存于各 agent 数据库 interest_judgment 表\n\n"
            f"{table}")


# ── 主入口 ───────────────────────────────────────────────────────
def generate_topic_report(run_dir: str, out_name: str = "topic_report.md") -> str:
    """从留档目录收集数据并生成话题报告。

    Returns:
        生成的报告文件绝对路径。
    """
    meta = _load_meta(run_dir)
    agent_dbs = _agent_dbs(run_dir)
    if not agent_dbs:
        raise ValueError(f"run_dir 中未找到 db/agent_*.sqlite：{run_dir}")
    identities = [i for i, _ in agent_dbs]

    starts, ends, counts, keywords, speeches, others = {}, {}, {}, {}, {}, {}
    for identity, dbp in agent_dbs:
        starts[identity] = _initial_seed(meta, identity) \
            or _decisions_first_personality(run_dir, identity)
        ends[identity] = _read_personality(dbp, identity)
        counts[identity] = _read_counts(dbp, identity)
        keywords[identity] = _keyword_stats(
            _read_self_cognition_texts(dbp, identity))
        speeches[identity] = _speech_stats(run_dir, identity)
        others[identity] = _read_other_cognition(dbp, identity)

    matrix_md, mutual_verdict = _render_mutual_matrix(others, identities)
    pt_table, pt_verdict = _render_personality_table(starts, ends)
    e3_table = _render_e3_table(identities, counts, keywords, speeches)
    llm_stats = _load_llm_stats(run_dir)
    # v6.6 数据采集统计节（decisions.jsonl / evolution.json 驱动）
    decisions = _load_decisions(run_dir)
    evo = _load_evolution(run_dir)
    position_bias = _render_position_bias(decisions)
    mention_attr = _render_mention_attribution(decisions, identities)
    mood_behavior = _render_mood_behavior(decisions, identities)
    memory_hits = _render_memory_hits(decisions, identities)
    silent_cog = _render_silent_cognition(decisions, identities)
    trajectory = _render_trajectory(evo)
    timeline = _render_cognition_timeline(decisions, identities)
    interest_gate = _render_interest_gate(
        _read_interest_judgments(run_dir, identities), identities, meta)

    topic = meta.get("topic", "（未记录）")
    topic_rounds = meta.get("topic_rounds", "?")
    model = meta.get("model", "?")
    gid = meta.get("gid") or meta.get("start_time", "?")
    report = f"""# 消息池话题报告（gid: {gid}）

> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')} | 话题：{topic}
> Agent 数：{len(identities)} | 话题轮次上限：{topic_rounds} | 模型：{model}
> 数据来源：db/agent_*.sqlite + decisions.jsonl（对齐 [WIP]-实验设计方案.md 采集方法）

## 一、相互认知记忆

**相互认知矩阵**（行=认知方，列=认知对象；数值=other_cognition 条目数）：

{matrix_md}

**双向认知判定**：

{mutual_verdict}

### 相互认知内容摘录

{_render_other_detail(others, identities)}

## 二、人格漂移倾向

{pt_table}

**判定**：

{pt_verdict}

## 三、认知记忆采集指标（E3 对齐）

{e3_table}

## 四、API 调用量统计

{_render_llm_stats(llm_stats, identities)}

## 五、批次位置-回应对象对照（末位偏置量化，P2）

{position_bias}

## 六、@提及响应率 与 user_id 归因正确率（P1-5）

{mention_attr}

## 七、情绪-行为关联（P2-7）

{mood_behavior}

## 八、记忆检索命中日志（P0-1）

{memory_hits}

## 九、静默期间的认知更新（P0-2）

{silent_cog}

## 十、人格漂移过程轨迹（P0-3）

{trajectory}

## 十一、认知网络演化时序（P1-4）

{timeline}

## 十二、兴趣门控判定采集（v7.0）

{interest_gate}

## 十三、结论

- **相互认知**：本报告检查了 Agent 之间是否在聊天室中形成对彼此的认知记忆
  （other_cognition 表，user_id=对方 Agent）。双向认知的形成是"多 Agent 相互
  认识"的直接证据；单向或缺失则说明对方尚未成为其认知对象。
- **人格漂移**：对比初始种子与话题结束时的性格向量（欧氏距离），判定本轮
  是否有可观测的演化倾向。短话题通常不触发演化，需跨话题长期观察累积漂移。
"""
    out_path = os.path.join(run_dir, out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    return out_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法：python topic_report.py <run_dir>")
        sys.exit(1)
    target = sys.argv[1]
    out = generate_topic_report(target)
    print(f"[报告] {out}")
