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
    """读取 other_cognition 表，按 user_id 分组的认知内容列表。"""
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
            uid = r["user_id"] or "unknown"
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

## 五、结论

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
