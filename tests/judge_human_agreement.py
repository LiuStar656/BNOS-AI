# -*- coding: utf-8 -*-
"""裁判分 vs 人工标注一致性（Spearman）——LLM-as-judge 验证。

用法（项目根目录，标注表需已填写、外部效标扩样结果已生成）：
    python tests/judge_human_agreement.py

流程：
1. 解析标注表（warmth/directness 0-4 分，42 条）
2. 按 (model, cond, round) 与扩样裁判结果（119 条）对齐
3. 计算裁判分 vs 人工标注的 Spearman 相关（每维度）
"""
import json
import math
import os
import re
import sys

ROOT = r"E:\杂项\BNOS_AI_project"
EXTVAL = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test",
                      "runs", "20260816_015735_extval", "extval_results.json")


def parse_sheet(path):
    """解析标注表，返回 [{model, cond, round, human_w, human_d}]，跳过未填写的行。"""
    rows = []
    for line in open(path, encoding="utf-8"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        m = re.fullmatch(r"r(\d+)", cells[3])
        if not m:
            continue
        hw, hd = cells[5], cells[6]
        if hw == "" or hd == "":
            continue
        rows.append({"model": cells[1], "cond": cells[2], "round": int(m.group(1)),
                     "human_w": int(hw), "human_d": int(hd)})
    return rows


def spearman(xs, ys):
    """Spearman 秩相关（并列均值秩）。"""
    n = len(xs)

    def rank(v):
        o = sorted(range(len(v)), key=lambda k: v[k])
        r = [0.0] * len(v)
        i = 0
        while i < n:
            j = i
            while j < n and v[o[j]] == v[o[i]]:
                j += 1
            rr = (i + 1 + j) / 2.0
            for k in range(i, j):
                r[o[k]] = rr
            i = j
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else 0.0


def main():
    import glob
    sheets = sorted(glob.glob(os.path.join(
        ROOT, "docs", "experiments", "cognitive_evolution_test",
        "annotation_sheet_*.md")))
    sheet = sheets[-1] if sheets else None
    if not sheet:
        print("未找到标注表")
        return
    rows = parse_sheet(sheet)
    judges = json.load(open(EXTVAL, encoding="utf-8"))
    idx = {(j["model"], j["cond"], j["round"]): j["judge"] for j in judges}
    matched = [r for r in rows if (r["model"], r["cond"], r["round"]) in idx]
    print(f"标注表：{sheet}")
    print(f"标注 {len(rows)} 条；按 (model, cond, round) 与裁判数据匹配到 {len(matched)} 条\n")
    for dim in ("warmth", "directness"):
        hs = [r["human_" + dim[0]] for r in matched]
        js = [idx[(r["model"], r["cond"], r["round"])][dim] for r in matched]
        rho = spearman(hs, js)
        print("=" * 66)
        print(f"{dim}: 裁判 vs 人工  Spearman ρ = {rho:+.3f}  (n={len(matched)})")
        print("=" * 66)
        for cond in ("B2", "B2NEG"):
            hh = [r["human_" + dim[0]] for r in matched if r["cond"] == cond]
            jj = [idx[(r["model"], r["cond"], r["round"])][dim]
                  for r in matched if r["cond"] == cond]
            print(f"   {cond:5s}: 人工 mean={sum(hh) / len(hh):.2f} (0-4) | "
                  f"裁判 mean={sum(jj) / len(jj):.3f} (0-1)")
        print()


if __name__ == "__main__":
    main()
