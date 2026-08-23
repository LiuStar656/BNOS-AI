# -*- coding: utf-8 -*-
"""Cohen's kappa 一致性分析：观测函数（规则打分）vs 人工标注。

用法（项目根目录，标注表需已填写）：
    python tests/kappa_analysis.py [标注表路径]

流程：
1. 解析标注表（warmth/directness 0-4 分）
2. 对每条回复从源轨迹 JSON 重取全文（自然回复正文，与标注表生成一致），
   用观测函数 estimate_style_from_reply 计算规则分（0-1）
3. 规则分离散化为 0-4 档
4. 计算线性加权 Cohen's kappa（0-4 有序类别）
"""
import json
import math
import os
import re
import sys

ROOT = r"E:\杂项\BNOS_AI_project"
sys.path.insert(0, os.path.join(ROOT, "docs", "cogevo", "paper_repro", "src"))
from personality import estimate_style_from_reply  # 观测函数（v2.0，关键词统计投影）

RUNS = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test", "runs")
# (model, cond) -> (run 目录, 轨迹文件)  与标注表生成脚本一致
SOURCES = {
    ("DeepSeek", "B2"): ("20260812_condB_194649", "condB_B2_rounds.json"),
    ("DeepSeek", "B2NEG"): ("20260812_condB_195954", "condB_B2NEG_rounds.json"),
    ("GLM-5.2", "B2"): ("20260812_multimodel_201814", "glm5.2_B2_rounds.json"),
    ("GLM-5.2", "B2NEG"): ("20260812_multimodel_201814", "glm5.2_B2NEG_rounds.json"),
    ("Qwen3.7-max", "B2"): ("20260812_multimodel_201814", "qwen3.7max_B2_rounds.json"),
    ("Qwen3.7-max", "B2NEG"): ("20260812_multimodel_201814", "qwen3.7max_B2NEG_rounds.json"),
}

_REPLY_CACHE = {}


def get_reply(model, cond, rnd):
    """从源轨迹取该轮的自然回复正文（与标注表同一清洗逻辑）。"""
    key = (model, cond)
    if key not in _REPLY_CACHE:
        run, fname = SOURCES[key]
        _REPLY_CACHE[key] = json.load(open(os.path.join(RUNS, run, fname), encoding="utf-8"))
    data = _REPLY_CACHE[key]
    for r in data["log"]:
        if r.get("round") == rnd:
            text = r.get("reply", "") or ""
            for marker in ("【风格自评】", "[风格自评]"):
                i = text.find(marker)
                if i != -1:
                    text = text[:i]
            for marker in ("【自然回复】", "[自然回复]"):
                text = text.replace(marker, "")
            return text.strip()
    return None


def parse_sheet(path):
    """解析标注表，返回 [{model, cond, round, human_w, human_d}]，跳过未填写的行。"""
    rows = []
    for line in open(path, encoding="utf-8"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        # cells: [id, model, cond, round, reply, warmth, directness]
        m = re.fullmatch(r"r(\d+)", cells[3])
        if not m:
            continue
        hw, hd = cells[5], cells[6]
        if hw == "" or hd == "":
            continue  # 未标注的行跳过
        rows.append({
            "model": cells[1], "cond": cells[2], "round": int(m.group(1)),
            "human_w": int(hw), "human_d": int(hd),
        })
    return rows


def rule_score(reply, dim):
    """观测函数规则分（0-1）→ 0-4 档（0=完全不符 … 4=完全符合）。"""
    obs = estimate_style_from_reply({"自然回复": reply})
    v = obs[dim]
    # 0.5 中心线性映射到 0-4：0.0→0, 0.5→2, 1.0→4
    return int(round(v * 4))


def _ranks(values):
    """并列均值秩。返回 (秩列表, 是否含并列)。"""
    order = sorted(range(len(values)), key=lambda k: values[k])
    ranks = [0.0] * len(values)
    i, n = 0, len(values)
    tied = False
    while i < n:
        j = i
        while j < n and values[order[j]] == values[order[i]]:
            j += 1
        r = (i + 1 + j) / 2.0
        if j - i > 1:
            tied = True
        for k in range(i, j):
            ranks[order[k]] = r
        i = j
    return ranks, tied


def mann_whitney_u(a, b):
    """双尾正态近似 U 检验，返回 p 值（含并列秩修正）。"""
    combined = list(a) + list(b)
    na, nb = len(a), len(b)
    ranks, tied = _ranks(combined)
    ua = sum(ranks[:na]) - na * (na + 1) / 2.0
    mu = na * nb / 2.0
    if tied:
        freqs = {}
        vals = sorted(combined)
        i, n = 0, len(vals)
        while i < n:
            j = i
            while j < n and vals[j] == vals[i]:
                j += 1
            if j - i > 1:
                freqs[j - i] = freqs.get(j - i, 0) + 1
            i = j
        tie_corr = sum(k * (k - 1) * (k + 1) for k in freqs) / 2.0
        sigma2 = na * nb / 12.0 * ((na + nb + 1) - tie_corr / ((na + nb) * (na + nb - 1)))
    else:
        sigma2 = na * nb * (na + nb + 1) / 12.0
    sigma = math.sqrt(max(sigma2, 1e-9))
    z = abs(ua - mu) / sigma
    p = 2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2))))
    return min(p, 1.0)


def weighted_kappa(a, b, k=5):
    """线性加权 Cohen's kappa（0 到 k-1 有序类别）。"""
    n = len(a)
    o = [[0] * k for _ in range(k)]
    for x, y in zip(a, b):
        o[x][y] += 1
    row_sum = [sum(o[i]) for i in range(k)]
    col_sum = [sum(o[j][i] for j in range(k)) for i in range(k)]
    w = [[1.0 - abs(i - j) / (k - 1) for j in range(k)] for i in range(k)]
    po = sum(o[i][j] * w[i][j] for i in range(k) for j in range(k)) / n
    pe = sum(row_sum[i] * col_sum[j] / (n * n) * w[i][j]
             for i in range(k) for j in range(k))
    if pe == 1.0:
        return float("nan")
    return (po - pe) / (1.0 - pe)


def main():
    sheet = sys.argv[1] if len(sys.argv) > 1 else None
    if sheet is None:
        import glob
        cands = sorted(glob.glob(os.path.join(
            ROOT, "docs", "experiments", "cognitive_evolution_test",
            "annotation_sheet_*.md")))
        sheet = cands[-1] if cands else None
    if not sheet or not os.path.exists(sheet):
        print("未找到标注表，请先填写 annotation_sheet_*.md")
        return
    rows = parse_sheet(sheet)
    if not rows:
        print("标注表为空或未填写（warmth/directness 列为空）。")
        return

    print(f"标注表：{sheet}")
    print(f"已标注 {len(rows)} 条（warmth 与 directness 均已填写）\n")

    for dim in ("warmth", "directness"):
        human, rule = [], []
        for r in rows:
            reply = get_reply(r["model"], r["cond"], r["round"])
            if reply is None:
                continue
            human.append(r["human_" + dim[0]])
            rule.append(rule_score(reply, dim))
        k = weighted_kappa(human, rule)
        print("=" * 66)
        print(f"{dim}: 线性加权 Cohen's kappa = {k:.3f}  (n={len(human)})")
        print("=" * 66)
        # 分布
        dist_h = {i: human.count(i) for i in range(5)}
        dist_r = {i: rule.count(i) for i in range(5)}
        print(f"  人工标注分布 (0-4): {dist_h}")
        print(f"  规则打分分布 (0-4): {dist_r}")
        # 条件分组 kappa
        for cond in ("B2", "B2NEG"):
            hh = [h for r, h in zip(rows, human) if r["cond"] == cond]
            rr = [h for r, h in zip(rows, rule) if r["cond"] == cond]
            kc = weighted_kappa(hh, rr)
            print(f"  条件 {cond:5s} kappa = {kc:+.3f} (n={len(hh)})")
        print()

    # 汇总：规则分中回退 0.5（→2 档）的比例
    fb = 0
    for r in rows:
        reply = get_reply(r["model"], r["cond"], r["round"])
        obs = estimate_style_from_reply({"自然回复": reply})
        if obs["warmth"] == 0.5 and obs["directness"] == 0.5:
            fb += 1
    print(f"规则分双维均回退 0.5（未命中关键词）的样本：{fb}/{len(rows)}")

    # 人工标注的条件区分度：人类能否仅凭文本区分 B2/B2NEG
    print("\n=== 人工标注条件间对比（人类文本感知 vs 装置预期方向）===")
    for dim in ("warmth", "directness"):
        print(f"--- {dim}（人工标注 0-4 档）---")
        groups = {}
        for cond in ("B2", "B2NEG"):
            hh = [r["human_" + dim[0]] for r in rows if r["cond"] == cond]
            groups[cond] = hh
            print(f"  {cond:5s}: mean={sum(hh)/len(hh):.2f}  分布={ {i: hh.count(i) for i in range(5)} }")
        p = mann_whitney_u(groups["B2"], groups["B2NEG"])
        print(f"  Mann-Whitney U 检验 p={p:.2e}")
    # 人工标注与规则分方向一致性（按条件均值）
    print("\n规则分条件均值（0-4 档）:")
    for dim in ("warmth", "directness"):
        for cond in ("B2", "B2NEG"):
            rr = [rule_score(get_reply(r["model"], r["cond"], r["round"]), dim)
                  for r in rows if r["cond"] == cond]
            print(f"  {dim} {cond:5s}: mean={sum(rr)/len(rr):.2f}")

    # 长度启发式检验：人工标注是否由回复长度（用心程度代理）驱动
    print("\n=== 长度启发式检验（长回复=用心=温暖？）===")
    lens = []
    for r in rows:
        reply = get_reply(r["model"], r["cond"], r["round"])
        lens.append((len(reply), r["cond"], r["human_w"], r["human_d"]))
    for cond in ("B2", "B2NEG"):
        ls = [l for l, c, _, _ in lens if c == cond]
        print(f"  {cond:5s}: 平均长度 {sum(ls)/len(ls):.0f} 字符  中位 {sorted(ls)[len(ls)//2]}  min={min(ls)} max={max(ls)}")
    p_len = mann_whitney_u([l for l, c, _, _ in lens if c == "B2"],
                           [l for l, c, _, _ in lens if c == "B2NEG"])
    print(f"  B2 vs B2NEG 长度差异 Mann-Whitney U p={p_len:.2e}")
    # 人工分 vs 长度 Spearman
    def spearman(xs, ys):
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
    L = [l for l, _, _, _ in lens]
    print(f"  人工 warmth vs 长度  Spearman ρ={spearman([w for _, _, w, _ in lens], L):+.3f}")
    print(f"  人工 directness vs 长度 Spearman ρ={spearman([d for _, _, _, d in lens], L):+.3f}")


if __name__ == "__main__":
    main()
