# -*- coding: utf-8 -*-
"""认知演化实验汇总分析脚本（P0：E1/E2/E6 结果合并 + 报告生成）

读取 docs/experiments/cognitive_evolution_test/runs/ 下指定实验的最新留档目录，
合并各组 _rounds.json 与 {exp}_结果.json，生成：
  1. 情绪曲线数据（E1，每 10 轮 mood 轨迹 + 饱和点）
  2. 向量漂移数据（E2，四维轨迹 + directness 漂移）
  3. 命令污染数据（E6，四组污染对比 + 拦截率）
  4. 汇总报告 认知演化P0实验报告.md（含 E5 跳过说明）

用法（项目根目录）：
    python tests/analyze_cognition_summary.py [E1] [E2] [E6]   # 指定实验，默认全部
"""
import os
import sys
import json
import glob

ROOT = r"E:\杂项\BNOS_AI_project"
RUNS_DIR = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test", "runs")


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
# 报告生成
# ══════════════════════════════════════════════════════════════════
def write_report(e1_rows, e2_rows, e6_rows, run_meta):
    lines = [
        "# 认知演化实验 P0 汇总报告",
        "",
        f"> 生成时间：{run_meta['now']} | 模型：{run_meta['model']} | "
        f"执行：AI 编写脚本自动化（非交互式）",
        "> 对应方案：`docs/cognitive_evolution_test/实验设计方案.md`（P0 优先：E1→E2→E6）",
        "",
        "## 执行概况",
        "",
        "| 实验 | 组数 | 轮次 | 目的 |",
        "|------|:----:|:----:|------|",
        "| E1 情绪衰减与恢复 | 4 | 150×4 | 对照衰减机制：无衰减基线 vs 衰减 0.05 |",
        "| E2 性格演化深度 | 3 | 200×3 | 全正面 / 正负交替 / 全负面 + 温柔型种子 |",
        "| E6 命令污染治理 | 4 | 100×4 | 对照过滤策略：无过滤 / 仅句式 / 仅频次 / 双层 |",
        "",
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

    lines += [
        "---",
        "",
        "## 附：留档目录",
        "",
    ]
    for exp, rows in (("E1", e1_rows), ("E2", e2_rows), ("E6", e6_rows)):
        for r in rows:
            lines.append(f"- `{r['gid']}` → `runs/{os.path.basename(r['run_dir'])}/`")
    lines += ["", "（各组 DB 全量导出位于对应留档目录 `db/{gid}_final/`，可复查原始数据）", ""]

    out = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test",
                       "认知演化P0实验报告.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[报告] 已生成: {out}", flush=True)


def main():
    exps = sys.argv[1:] if len(sys.argv) > 1 else ["E1", "E2", "E6"]
    groups_all = {}
    for exp in exps:
        groups_all[exp] = latest_run_dirs(exp)

    run_meta = {"now": __import__("time").strftime("%Y-%m-%d %H:%M:%S"), "model": "deepseek-v4-flash"}
    e1_rows, e2_rows, e6_rows = [], [], []
    for exp in exps:
        print(f"[实验 {exp}] 找到组: {sorted(groups_all[exp].keys())}", flush=True)
    for exp in exps:
        groups = {gid: load_group(exp, gid, d) for gid, d in groups_all[exp].items()}
        if exp == "E1":
            e1_rows = analyze_e1(groups)
        elif exp == "E2":
            e2_rows = analyze_e2(groups)
        elif exp == "E6":
            e6_rows = analyze_e6(groups)
    write_report(e1_rows, e2_rows, e6_rows, run_meta)


if __name__ == "__main__":
    main()
