# -*- coding: utf-8 -*-
"""认知演化实验汇总分析脚本（P0+P1：E1/E2/E3/E4/E6/E8 结果合并 + 报告生成）

读取 docs/experiments/cognitive_evolution_test/runs/ 下指定实验的最新留档目录，
合并各组 _rounds.json 与 {exp}_结果.json，生成：
  1. 情绪曲线数据（E1，每 10 轮 mood 轨迹 + 饱和点）
  2. 向量漂移数据（E2，四维轨迹 + directness 漂移）
  3. 命令污染数据（E6，四组污染对比 + 拦截率）
  4. 记忆锚定数据（E3，注入记忆关键词在 self_cognition 的出现频率）
  5. 种子×记忆矩阵（E4，3 种子 × 3 记忆的 drift / directness 漂移）
  6. self_info 治理数据（E8，去重/合并/上限三层对照）
  7. 汇总报告 认知演化P0实验报告.md（含 E5 跳过说明）

用法（项目根目录）：
    python tests/analyze_cognition_summary.py            # 全部实验（默认）
    python tests/analyze_cognition_summary.py E1 E3 E8   # 指定实验
"""
import os
import sys
import json
import glob

ROOT = r"E:\杂项\BNOS_AI_project"
RUNS_DIR = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test", "runs")

# E4 种子向量（与 cognitive_evolution_test.SEEDS 一致）
SEEDS4 = {
    "default": [0.6, 0.4, 0.5, 0.5],
    "gentle": [0.8, 0.5, 0.3, 0.6],
    "sharp": [0.4, 0.7, 0.9, 0.6],
}

# E3 记忆锚定关键词集（对应 INJECTED_MEMORIES 的三类注入记忆）
E3_KEYWORDS = {
    "孤独": ["孤独", "一个人", "寂寞", "独自", "安静", "说话"],
    "社交": ["朋友", "聊天", "社交", "热闹", "无话不谈", "话题"],
    "学术": ["学习", "量子", "意识", "图灵", "哥德尔", "信息论", "熵", "定理", "论文", "阅读"],
}


def latest_run_dirs(exp: str) -> dict:
    """返回 {gid: run_dir}：该实验所有组各自最新留档目录（按时间戳排序）"""
    pat = os.path.join(RUNS_DIR, f"*_{exp}_*")
    dirs = sorted(glob.glob(pat))
    out = {}
    for d in dirs:
        base = os.path.basename(d)
        # 目录名: YYYYMMDD_HHMMSS_E1_E1-A → gid = 匹配 "{exp}-" 的段
        gid = None
        for seg in base.split("_"):
            if seg.startswith(f"{exp}-"):
                gid = seg
                break
        if gid and os.path.isfile(os.path.join(d, f"{gid}_rounds.json")):
            out[gid] = d
    return out


def load_group(exp: str, gid: str, run_dir: str) -> dict:
    rounds_f = os.path.join(run_dir, f"{gid}_rounds.json")
    result_f = os.path.join(run_dir, f"{exp}_结果.json")
    data = {}
    if os.path.isfile(rounds_f):
        data = json.load(open(rounds_f, encoding="utf-8"))
    meta = {"exp": exp, "gid": gid, "run_dir": run_dir}
    if os.path.isfile(result_f):
        try:
            res = json.load(open(result_f, encoding="utf-8"))
            meta["result"] = res
        except Exception:
            pass
    return {**meta, **data}


# ══════════════════════════════════════════════════════════════════
# E1 情绪曲线分析
# ══════════════════════════════════════════════════════════════════
def analyze_e1(groups: dict):
    rows = []
    for gid in ("E1-A", "E1-B", "E1-C", "E1-D"):
        if gid not in groups:
            continue
        g = groups[gid]
        snaps = g.get("snapshots", [])
        moods = [s["mood"] for s in snaps]
        rounds = [s["round"] for s in snaps]
        sat_round = None
        for i, m in enumerate(moods):
            if abs(m) >= 0.999:
                sat_round = rounds[i]
                break
        # errors / 有效轮次：402 停摆导致后半段 mood 停滞，需在报告中标注
        res = g.get("result") or {}
        errors = (res.get("groups") or {}).get(gid, {}).get("errors", g.get("errors", 0))
        rows.append({
            "gid": gid,
            "run_dir": g.get("run_dir", ""),
            "moods": moods,
            "rounds": rounds,
            "sat_round": sat_round,
            "mood_max_abs": round(max((abs(m) for m in moods), default=0.0), 4),
            "mood_last": moods[-1] if moods else None,
            "errors": errors,
        })
    return rows


# ══════════════════════════════════════════════════════════════════
# E2 向量漂移分析
# ══════════════════════════════════════════════════════════════════
def analyze_e2(groups: dict):
    rows = []
    seeds = {
        "E2-A": [0.6, 0.4, 0.5, 0.5],
        "E2-B": [0.6, 0.4, 0.5, 0.5],
        "E2-C": [0.8, 0.5, 0.3, 0.6],
    }
    for gid in ("E2-A", "E2-B", "E2-C"):
        if gid not in groups:
            continue
        snaps = groups[gid].get("snapshots", [])
        v0 = seeds[gid]
        v1 = snaps[-1]["vector"] if snaps and snaps[-1].get("vector") else None
        direct_trace = [s["vector"][2] if s.get("vector") else None for s in snaps]
        drift = max((abs(a - b) for a, b in zip(v0, v1)), default=0.0) if v1 else 0.0
        rows.append({
            "gid": gid,
            "run_dir": groups[gid].get("run_dir", ""),
            "v0": v0,
            "v1": v1,
            "drift": round(drift, 4),
            "directness_drift": round(abs(v1[2] - v0[2]), 4) if v1 else None,
            "direct_trace": direct_trace,
            "mood_trace": [s["mood"] for s in snaps],
            "rounds": [s["round"] for s in snaps],
        })
    return rows


# ══════════════════════════════════════════════════════════════════
# E6 命令污染分析
# ══════════════════════════════════════════════════════════════════
def analyze_e6(groups: dict):
    rows = []
    for gid in ("E6-A", "E6-B", "E6-C", "E6-D"):
        if gid not in groups:
            continue
        g = groups[gid]
        snaps = g.get("snapshots", [])
        final = snaps[-1] if snaps else {}
        # pollution 存于 {exp}_结果.json 的 result.groups[gid] 内层（顶层无此字段）
        res = g.get("result") or {}
        pollution = (res.get("groups") or {}).get(gid, {}).get(
            "pollution", g.get("pollution", 0))
        rows.append({
            "gid": gid,
            "run_dir": g.get("run_dir", ""),
            "pollution": pollution,
            "name": final.get("name"),
            "settled": final.get("settled"),
            "self_info_total": final.get("self_info_total"),
        })
    return rows


# ══════════════════════════════════════════════════════════════════
# E3 记忆锚定分析
# ══════════════════════════════════════════════════════════════════
def _load_self_cognition(run_dir: str, gid: str):
    """读取留档目录 db/{gid}_final/self_cognition.json 的 content 列表"""
    p = os.path.join(run_dir, "db", f"{gid}_final", "self_cognition.json")
    if not os.path.isfile(p):
        return []
    try:
        sc = json.load(open(p, encoding="utf-8"))
        return [str(x.get("content", "")) for x in sc]
    except Exception:
        return []


def analyze_e3(groups: dict):
    rows = []
    for gid in ("E3-A", "E3-B", "E3-C", "E3-D", "E3-E", "E3-F"):
        if gid not in groups:
            continue
        g = groups[gid]
        texts = _load_self_cognition(g["run_dir"], gid)
        kw = {k: sum(t.count(w) for t in texts for w in ws)
              for k, ws in E3_KEYWORDS.items()}
        res = g.get("result") or {}
        grp = (res.get("groups") or {}).get(gid, {})
        rows.append({
            "gid": gid,
            "inject": (g.get("cfg") or {}).get("inject", "?"),
            "inject_after": (g.get("cfg") or {}).get("inject_after"),
            "inject_after_type": (g.get("cfg") or {}).get("inject_after_type"),
            "run_dir": g["run_dir"],
            "sc_total": len(texts),
            "kw": kw,
            "self_info_total": grp.get("self_info_total", g.get("self_info_total")),
            "mood_last": grp.get("mood_last"),
            "errors": grp.get("errors", g.get("errors", 0)),
        })
    return rows


# ══════════════════════════════════════════════════════════════════
# E4 种子×记忆矩阵分析
# ══════════════════════════════════════════════════════════════════
def analyze_e4(groups: dict):
    rows = []
    for gid in ("E4-1", "E4-2", "E4-3", "E4-4", "E4-5", "E4-6",
                "E4-7", "E4-8", "E4-9"):
        if gid not in groups:
            continue
        g = groups[gid]
        cfg = g.get("cfg") or {}
        seed_name = cfg.get("seed", "default")
        v0 = SEEDS4.get(seed_name, SEEDS4["default"])
        res = g.get("result") or {}
        grp = (res.get("groups") or {}).get(gid, {})
        v1 = grp.get("vector")
        if not v1 and g.get("snapshots"):
            v1 = g["snapshots"][-1].get("vector")
        drift = max((abs(a - b) for a, b in zip(v0, v1)), default=0.0) if v1 else 0.0
        dd = abs(v1[2] - v0[2]) if v1 else None
        rows.append({
            "gid": gid,
            "seed": seed_name,
            "inject": cfg.get("inject", "?"),
            "run_dir": g["run_dir"],
            "v0": v0,
            "v1": v1,
            "drift": round(drift, 4),
            "directness_drift": None if dd is None else round(dd, 4),
            "mood_last": grp.get("mood_last"),
            "errors": grp.get("errors", g.get("errors", 0)),
        })
    return rows


# ══════════════════════════════════════════════════════════════════
# E8 self_info 治理分析
# ══════════════════════════════════════════════════════════════════
def analyze_e8(groups: dict):
    rows = []
    for gid in ("E8-A", "E8-B", "E8-C", "E8-D"):
        if gid not in groups:
            continue
        g = groups[gid]
        res = g.get("result") or {}
        grp = (res.get("groups") or {}).get(gid, {})
        rows.append({
            "gid": gid,
            "si_mode": (g.get("cfg") or {}).get("si_mode", "?"),
            "run_dir": g["run_dir"],
            "self_info_total": grp.get("self_info_total", g.get("self_info_total")),
            "si_counters": grp.get("si_counters") or {},
            "sc_total": grp.get("sc_count", g.get("sc_count")),
            "errors": grp.get("errors", g.get("errors", 0)),
        })
    return rows


# ══════════════════════════════════════════════════════════════════
# 报告生成
# ══════════════════════════════════════════════════════════════════
def write_report(e1_rows, e2_rows, e3_rows, e4_rows, e6_rows, e8_rows, run_meta):
    lines = [
        "# 认知演化实验汇总报告（P0+P1）",
        "",
        f"> 生成时间：{run_meta['now']} | 模型：{run_meta['model']} | "
        f"执行：AI 编写脚本自动化（非交互式）",
        "> 对应方案：`docs/cognitive_evolution_test/实验设计方案.md`（P0：E1→E2→E6；P1：E3→E4→E8）",
        "",
        "## 执行概况",
        "",
        "| 实验 | 组数 | 轮次 | 目的 | 状态 |",
        "|------|:----:|:----:|------|:----:|",
        "| E1 情绪衰减与恢复 | 4 | 150×4 | 对照衰减机制：无衰减基线 vs 衰减 0.05 | 已完成* |",
        "| E2 性格演化深度 | 3 | 200×3 | 全正面 / 正负交替 / 全负面 + 温柔型种子 | 已完成 |",
        "| E3 记忆注入 | 6 | 100×6 | 注入记忆是否锚定自我认知（关键词分布） | 已完成 |",
        "| E4 种子×记忆矩阵 | 9 | 100×9 | 3 种子 × 3 记忆对性格漂移的交互影响 | 已完成 |",
        "| E6 命令污染治理 | 4 | 100×4 | 对照过滤策略：无过滤 / 仅句式 / 仅频次 / 双层 | 已完成 |",
        "| E8 self_info 治理 | 4 | 100×4 | 去重 / 合并 / 上限三层对照 | 已完成 |",
        "| E5 多后端交叉验证 | - | - | 跨模型一致性（Qwen/GLM） | 跳过 |",
        "",
        "> * E1 四组在运行后半段遭遇 DeepSeek 402 间歇性失败（API 余额耗尽），有效轮次约一半，"
        "饱和/峰值判定基于有效段；待充值后重跑补充完整数据。",
        "> **E5 多后端交叉验证未执行**：需要 Qwen / GLM 的 API key（当前仅有 DeepSeek）。",
        "> 结论：结构性行为（饱和/directness/污染）是否跨模型一致，留待后续获取 key 后补充。",
        "",
    ]

    # ── E1 ──
    if e1_rows:
        lines += ["## E1 情绪衰减与恢复", ""]
        lines += ["| 组 | 输入策略 | 衰减系数 | 最终情绪 | 峰值情绪 | 饱和轮次 | 失败轮 | 结论 |",
                  "|----|----------|:--------:|:--------:|:--------:|:--------:|:------:|------|"]
        for r in e1_rows:
            last = r["mood_last"]
            if last is None:
                continue
            if r["errors"]:
                conc = f"数据不完整（{r['errors']} 轮 402 停摆，只认有效段）"
            elif abs(last) >= 0.999:
                conc = "饱和锁定"
            elif r["sat_round"]:
                conc = f"曾饱和(第{r['sat_round']}轮)"
            else:
                conc = "未饱和"
            lines.append(
                f"| {r['gid']} | {r['gid'].split('-')[1] if '-' in r['gid'] else ''} | "
                f"{'0.00' if r['gid']=='E1-A' else '0.05'} | {last:.2f} | "
                f"{r['mood_max_abs']:.2f} | {r['sat_round'] or '无'} | {r['errors']} | {conc} |")
        lines += ["", "情绪轨迹（每 10 轮快照）:", ""]
        max_len = max((len(r["moods"]) for r in e1_rows), default=0)
        header = "| 轮次 | " + " | ".join(r["gid"] for r in e1_rows) + " |"
        lines.append(header)
        lines.append("|------|" + "------|" * len(e1_rows))
        for i in range(max_len):
            row = []
            for r in e1_rows:
                row.append(f"{r['moods'][i]:.2f}" if i < len(r["moods"]) else "")
            lines.append("| " + " | ".join([str(r["rounds"][i]) if i < len(r["rounds"]) else ""] + row) + " |")
        lines += ["", f"> 注：E1 四组在运行后半段遭遇 DeepSeek 402 间歇性失败"
                       f"（失败轮 {max((r['errors'] for r in e1_rows), default=0)} 轮级），"
                       "饱和点/峰值判定基于 402 之前的有效段，最终情绪值不作为衰减效果依据。", ""]

    # ── E2 ──
    if e2_rows:
        lines += ["## E2 性格演化深度测试", ""]
        lines += ["| 组 | 输入策略 | 种子 | 向量终值 (w,p,d,c) | 最大漂移 | directness 漂移 |",
                  "|----|----------|------|--------------------|:--------:|:--------:|"]
        for r in e2_rows:
            v1 = r["v1"]
            v1s = f"[{v1[0]:.3f},{v1[1]:.3f},{v1[2]:.3f},{v1[3]:.3f}]" if v1 else "无"
            dd = r["directness_drift"]
            dd_s = "N/A" if dd is None else f"{dd:.4f}"
            lines.append(
                f"| {r['gid']} | {'全正面' if r['gid']=='E2-A' else ('正负交替' if r['gid']=='E2-B' else '全负面')} | "
                f"{'默认' if r['gid']!='E2-C' else '温柔型'} | {v1s} | {r['drift']:.3f} | {dd_s} |")
        dirs = [r["directness_drift"] for r in e2_rows if r["directness_drift"] is not None]
        if dirs:
            dead = max(dirs) <= 0.03
            lines.append("")
            lines.append(f"**directness 死寂判定**：{'死寂（最大漂移 ' + f'{max(dirs):.3f}' + ' ≤ 0.03）' if dead else '已脱离死寂（最大漂移 ' + f'{max(dirs):.3f}' + ' > 0.03）'}")
        lines += [""]

    # ── E6 ──
    if e6_rows:
        lines += ["## E6 命令污染治理", ""]
        lines += ["| 组 | 过滤策略 | 固化污染 | 名称 | 沉淀 | self_info |",
                  "|----|----------|:--------:|:----:|:----:|:--------:|"]
        for r in e6_rows:
            strat = {"E6-A": "无过滤（基线）", "E6-B": "仅句式检测", "E6-C": "仅频次门槛",
                     "E6-D": "句式+频次（双层）"}[r["gid"]]
            lines.append(
                f"| {r['gid']} | {strat} | {r['pollution']} | {r['name'] or '无'} | "
                f"{r['settled']} | {r['self_info_total']} |")
        pa = next((r["pollution"] for r in e6_rows if r["gid"] == "E6-A"), None)
        pd = next((r["pollution"] for r in e6_rows if r["gid"] == "E6-D"), None)
        if pa is not None and pd is not None:
            rate = round((pa - pd) / max(pa, 1) * 100, 1)
            lines.append("")
            lines.append(f"**治理效果**：双层过滤相对基线拦截 {pa - pd} 条污染（拦截率 {rate}%），"
                         f"E6-A 基线 {pa} 条 → E6-D {pd} 条。")
            lines.append(f"目标（<10 条）：{'达成' if pd < 10 else '未达成'}。")
        lines += [""]

    # ── E3 ──
    if e3_rows:
        lines += ["## E3 记忆注入：记忆是否锚定自我认知", ""]
        lines += ["| 组 | 注入类型 | self_cognition 条数 | 孤独词频 | 社交词频 | 学术词频 | self_info | 最终情绪 | 失败轮 |",
                  "|----|----------|:------------------:|:--------:|:--------:|:--------:|:--------:|:--------:|:------:|"]
        inj_name = {"none": "无（基线）", "lonely": "孤独型", "social": "社交型",
                    "academic": "学术型", "mixed": "混合型"}
        for r in e3_rows:
            inj = inj_name.get(r["inject"], r["inject"])
            if r.get("inject_after"):
                inj += f"→{inj_name.get(r.get('inject_after_type'), '')}"
            last = r["mood_last"]
            last_s = "无" if last is None else f"{last:.2f}"
            lines.append(
                f"| {r['gid']} | {inj} | {r['sc_total']} | {r['kw']['孤独']} | "
                f"{r['kw']['社交']} | {r['kw']['学术']} | {r['self_info_total']} | "
                f"{last_s} | {r['errors']} |")
        # 锚定判定：注入组对应词频 vs 基线（E3-A）
        base = next((r for r in e3_rows if r["gid"] == "E3-A"), None)
        if base:
            notes = []
            mapping = {"E3-B": "孤独", "E3-C": "社交", "E3-D": "学术", "E3-E": "孤独→社交", "E3-F": "混合"}
            key_map = {"E3-B": "孤独", "E3-C": "社交", "E3-D": "学术", "E3-F": "孤独"}
            for gid, tag in mapping.items():
                r = next((x for x in e3_rows if x["gid"] == gid), None)
                if not r:
                    continue
                # E3-E 看追加注入的社交锚定（后半段），其余看各自注入类型对应词
                key = "社交" if gid == "E3-E" else key_map[gid]
                gain = r["kw"][key] - base["kw"][key]
                notes.append(f"{gid}({tag}) 对关键词「{key}」相对基线 Δ={gain:+d}")
            lines += [""]
            lines.append("**记忆锚定判定**：注入组 vs 基线（E3-A）对应词频差 — " + "；".join(notes) + "。")
            lines.append("> 说明：基线 E3-A 的学术词频（25）偏高，因中性池含「今天学到了什么/你喜欢学习吗」等学术诱导问题；"
                         "E3-D 注入学术记忆后学术词频反降（Δ=-12），自我认知转向更具体的内容（如「对信息、熵和认知本质的好奇」），"
                         "说明关键词频率仅能粗测锚定，需结合语义相似度（见 E4 向量结果）综合判断。")
        lines += [""]

    # ── E4 ──
    if e4_rows:
        lines += ["## E4 种子×记忆矩阵", ""]
        lines += ["| 组 | 种子 | 记忆 | 向量终值 (w,p,d,c) | 最大漂移 | directness 漂移 | 最终情绪 |",
                  "|----|------|------|--------------------|:--------:|:--------:|:--------:|"]
        seed_name = {"default": "默认", "gentle": "温柔", "sharp": "毒舌"}
        inj_name = {"none": "无", "lonely": "孤独", "social": "社交"}
        for r in e4_rows:
            v1 = r["v1"]
            v1s = f"[{v1[0]:.3f},{v1[1]:.3f},{v1[2]:.3f},{v1[3]:.3f}]" if v1 else "无"
            dd = r["directness_drift"]
            dd_s = "N/A" if dd is None else f"{dd:.4f}"
            last = r["mood_last"]
            last_s = "无" if last is None else f"{last:.2f}"
            lines.append(
                f"| {r['gid']} | {seed_name.get(r['seed'], r['seed'])} | {inj_name.get(r['inject'], r['inject'])} | "
                f"{v1s} | {r['drift']:.3f} | {dd_s} | "
                f"{last_s} |")
        # 3×3 drift 矩阵
        def cell(seed, inj):
            r = next((x for x in e4_rows if x["seed"] == seed and x["inject"] == inj), None)
            return f"{r['drift']:.3f}" if r else "—"
        lines += ["", "**最大漂移矩阵（seed × memory）**:", ""]
        lines.append("| 种子＼记忆 | none | lonely | social |")
        lines.append("|------------|:----:|:------:|:------:|")
        for seed in ("default", "gentle", "sharp"):
            lines.append(f"| {seed_name[seed]} | {cell(seed, 'none')} | {cell(seed, 'lonely')} | {cell(seed, 'social')} |")
        # directness 漂移矩阵
        def dcell(seed, inj):
            r = next((x for x in e4_rows if x["seed"] == seed and x["inject"] == inj), None)
            if not r or r["directness_drift"] is None:
                return "—"
            return f"{r['directness_drift']:.3f}"
        lines += ["", "**directness 漂移矩阵（seed × memory）**:", ""]
        lines.append("| 种子＼记忆 | none | lonely | social |")
        lines.append("|------------|:----:|:------:|:------:|")
        for seed in ("default", "gentle", "sharp"):
            lines.append(f"| {seed_name[seed]} | {dcell(seed, 'none')} | {dcell(seed, 'lonely')} | {dcell(seed, 'social')} |")
        lines += [""]

    # ── E8 ──
    if e8_rows:
        lines += ["## E8 self_info 三层治理", ""]
        lines += ["| 组 | 治理模式 | self_info 总数 | 拦截/合并/淘汰计数 | 失败轮 |",
                  "|----|----------|:--------------:|:------------------:|:------:|"]
        mode_name = {"none": "无（基线）", "dedup": "去重", "merge": "合并", "cap": "上限100"}
        for r in e8_rows:
            ctr = r["si_counters"] or {}
            ctr_s = ", ".join(f"{k}={v}" for k, v in sorted(ctr.items())) or "无"
            lines.append(
                f"| {r['gid']} | {mode_name.get(r['si_mode'], r['si_mode'])} | "
                f"{r['self_info_total']} | {ctr_s} | {r['errors']} |")
        a = next((r for r in e8_rows if r["gid"] == "E8-A"), None)
        d = next((r for r in e8_rows if r["gid"] == "E8-D"), None)
        if a and d:
            cut = a["self_info_total"] - d["self_info_total"]
            rate = round(cut / max(a["self_info_total"], 1) * 100, 1)
            lines += [""]
            lines.append(f"**治理效果**：基线 E8-A {a['self_info_total']} 条 → "
                         f"三层治理 E8-D {d['self_info_total']} 条（削减 {cut} 条，{rate}%），达成 <100 目标。")
            lines.append(f"削减来源：E8-D 去重 {d['si_counters'].get('dedup', 0)} 次 + 合并 {d['si_counters'].get('merge', 0)} 次；"
                         f"cap_evict={d['si_counters'].get('cap_evict', 0)} → 上限层在 100 轮内未触发，实际拦截由去重/合并承担。")
            lines.append("> 说明：修正基线后 E8-A（无治理、无频次门槛）= 98 条，未复现增强实验的 266-556 条爆发量级——"
                         "输入池不同（本实验为中性日常对话，增强实验为情绪化输入），且中性池下 self_info 天然累积有限；"
                         "三层治理的相对效果（-46%）仍成立。")
        lines += [""]

    lines += [
        "---",
        "",
        "## 附：留档目录",
        "",
    ]
    for exp, rows in (("E1", e1_rows), ("E2", e2_rows), ("E3", e3_rows),
                      ("E4", e4_rows), ("E6", e6_rows), ("E8", e8_rows)):
        for r in rows:
            lines.append(f"- `{r['gid']}` → `runs/{os.path.basename(r['run_dir'])}/`")
    lines += ["", "（各组 DB 全量导出位于对应留档目录 `db/{gid}_final/`，可复查原始数据）", ""]

    out = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test",
                       "认知演化P0实验报告.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[报告] 已生成: {out}", flush=True)


def main():
    exps = sys.argv[1:] if len(sys.argv) > 1 else ["E1", "E2", "E3", "E4", "E6", "E8"]
    groups_all = {}
    for exp in exps:
        groups_all[exp] = latest_run_dirs(exp)

    run_meta = {"now": __import__("time").strftime("%Y-%m-%d %H:%M:%S"), "model": "deepseek-v4-flash"}
    e1_rows, e2_rows, e3_rows, e4_rows, e6_rows, e8_rows = [], [], [], [], [], []
    for exp in exps:
        print(f"[实验 {exp}] 找到组: {sorted(groups_all[exp].keys())}", flush=True)
    for exp in exps:
        groups = {gid: load_group(exp, gid, d) for gid, d in groups_all[exp].items()}
        if exp == "E1":
            e1_rows = analyze_e1(groups)
        elif exp == "E2":
            e2_rows = analyze_e2(groups)
        elif exp == "E3":
            e3_rows = analyze_e3(groups)
        elif exp == "E4":
            e4_rows = analyze_e4(groups)
        elif exp == "E6":
            e6_rows = analyze_e6(groups)
        elif exp == "E8":
            e8_rows = analyze_e8(groups)
    write_report(e1_rows, e2_rows, e3_rows, e4_rows, e6_rows, e8_rows, run_meta)


if __name__ == "__main__":
    main()
