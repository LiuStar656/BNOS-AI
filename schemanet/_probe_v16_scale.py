# -*- coding: utf-8 -*-
"""Stage 3 v16 训练量缩放探测：并发训练 × 轮次缩放（108 条高质量对话/短文）。

背景（2026-08-10 用户）：
  - v16 用 108 条高质量对话/短文训练，分句接话修正后 19/19 = 1.000（校准 1 处）
  - 用户问："要不要提升高质量对话和短文的训练量？"
    + "可以试试并发训练看看实际训练效果"
  - 前置：并发训练边界探针已证 128 组并发 100% 无崩溃、槽位代价线性（~0.69MB/组）

本探测回答两个问题：
  1. 训练量提升（同一批 108 条 × 更多轮次）能否提升网络真实掌握度？
     ——测"修正前"分句接话命中率（v16 修正后 1.000 靠校准，修正前 0.895 才是
        真实掌握度）：R_S ∈ {1,2,4,8}
  2. 并发训练的实际效果？——4 进程并行 4 个轮次点（各自独立 v15.0 副本），
     对比并发墙钟 vs 串行总和，确认并发调度下训练效果与串行一致（无崩溃无串扰）
  3. 数据量维度：toutiao 精筛标准放宽后的候选量（短文·真实还能扩多少）

输出：runs/_speak_logs/{ts}_probe_v16_scale/result.json + charts/

用法：python _probe_v16_scale.py
      python _probe_v16_scale.py --nostats   # 跳过 toutiao 数据量统计（省时）
"""

import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

DATA = Path(__file__).parent / "data" / "curriculum"
RAW = DATA / "raw" / "toutiao_cat_data.txt_unzip" / "toutiao_cat_data.txt"
RUNS_DIR = Path(__file__).parent / "runs"
RS_POINTS = [1, 2, 4, 8]     # 轮次缩放点（训练量 108×rs 次学习）
MAX_WORKERS = 4


def run_point(rs):
    """独立进程：加载 v15.0 → 108 条 ×rs 轮训练 → 分句接话（修正前/校准/修正后）。"""
    import json
    import time
    from pathlib import Path

    from schema_net import _learn_sentence
    from snapshot import load_version
    from sparse_net import allocate_pats
    from _grow_v15 import DOMAIN_WORDS
    import _grow_v16 as G16

    DATA = Path(__file__).parent / "data" / "curriculum"
    t0 = time.time()
    ng, vocab, pats, cursor = load_version("15.0")
    rows = json.loads((DATA / "stage3_rel_v2.json").read_text(encoding="utf-8"))
    n2w = {j: w for w, ns in pats.items() for j in ns}
    all_toks = [w for r in rows for w in r["tokens"]]
    missing = sorted(set(all_toks) - set(pats))
    if missing:
        new_pats, cursor = allocate_pats(ng, missing, G16.K, cursor)
        pats.update(new_pats)
        n2w = {j: w for w, ns in pats.items() for j in ns}
    domain = sorted(w for w in DOMAIN_WORDS if w in pats)

    t1 = time.time()
    for r in rows:
        for _ in range(rs):
            _learn_sentence(ng, r["tokens"], pats, slot=0)
    learn_sec = time.time() - t1

    rows1, n1, tot1 = G16.chain_generate(ng, pats, n2w, domain)
    fixes = G16.calibrate(ng, pats, n2w, domain)
    rows4, n4, tot4 = G16.chain_generate(ng, pats, n2w, domain)

    out = {"rs": rs, "n": ng.n,
           "pre": round(n1 / tot1, 3), "pre_hits": n1, "pre_tot": tot1,
           "post": round(n4 / tot4, 3), "post_hits": n4, "post_tot": tot4,
           "cal_fixes": len(fixes),
           "chain1": rows1, "chain4": rows4, "fixes": fixes,
           "learn_sec": round(learn_sec, 1),
           "total_sec": round(time.time() - t0, 1)}
    print(f"\n[点 {rs}轮] 训练 {len(rows) * rs} 次 | 修正前 {n1}/{tot1}"
          f"={n1 / tot1:.3f} | 校准 {len(fixes)} 处 | 修正后 {n4}/{tot4}"
          f"={n4 / tot4:.3f} | 学习 {learn_sec:.0f}s 总 {out['total_sec']:.0f}s")
    return out


def toutiao_stats(keys):
    """toutiao 精筛标准放宽后的候选量统计（只读，不改数据文件）。"""
    import jieba
    import re

    def clean_title(t):
        return re.sub(r"[，。？！、；：“”\"'\u2018\u2019\u201c\u201d（）()…—\-—\s,.;:!?\u3000]", "", t)

    lines = RAW.read_text(encoding="utf-8", errors="ignore").splitlines()
    toks_list = []
    for l in lines:
        parts = l.split("_!_")
        if len(parts) < 4:
            continue
        t = parts[3].strip()
        if not (("虽然" in t and "但是" in t) or ("因为" in t and "所以" in t)
                or ("先" in t and "然后" in t)):
            continue
        c = clean_title(t)
        toks = list(jieba.cut(c))
        if any(ch.isascii() and ch.isalnum() for w in toks for ch in w):
            continue
        toks_list.append(toks)
    print(f"[toutiao 配对候选] 去标点/去 ASCII 后共 {len(toks_list)} 条")

    def count(miss_max, lo, hi):
        n = 0
        for toks in toks_list:
            if not (lo <= len(toks) <= hi):
                continue
            miss = sum(1 for w in toks if w not in keys)
            if miss <= miss_max:
                n += 1
        return n

    table = {}
    for miss_max in (2, 4, 8, 99):
        for (lo, hi), lab in (((5, 22), "5-22词"), ((3, 30), "3-30词")):
            c = count(miss_max, lo, hi)
            table[f"miss<={miss_max}·{lab}"] = c
            print(f"  miss<={miss_max} · {lab}：{c} 条")
    return table


def _plt():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
        plt.rcParams["axes.unicode_minus"] = False
        return plt
    except Exception as e:
        print(f"  [charts] matplotlib 不可用，跳过出图：{e}")
        return None


def main():
    nostats = "--nostats" in sys.argv
    t0 = time.time()
    print("═══ v16 训练量缩放探测（并发训练 × 轮次缩放）═══\n")

    # ── 1. 并发训练：4 点并行（各点独立 v15.0 副本）──────────
    t_wall = time.time()
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as ex:
        results = list(ex.map(run_point, RS_POINTS))
    wall_sec = time.time() - t_wall
    serial_sec = sum(r["total_sec"] for r in results)
    speedup = serial_sec / wall_sec if wall_sec else 0
    print(f"\n[并发调度] 墙钟 {wall_sec:.0f}s vs 串行总和 {serial_sec:.0f}s"
          f" → 加速比 {speedup:.2f}x（{MAX_WORKERS} 进程，无崩溃）")

    # ── 2. 数据量评估（toutiao 放宽标准；主进程，并发后跑）────
    stats = {}
    if not nostats:
        print("\n[数据量评估] toutiao 精筛标准放宽（v16 现标准 = miss≤4·5-22词 → 47 条）")
        from snapshot import load_version
        ng, _, pats, _ = load_version("15.0")
        stats = toutiao_stats(set(pats.keys()))

    # ── 3. 图表 ───────────────────────────────────────────────
    out_dir = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_probe_v16_scale"
    out_dir.mkdir(parents=True, exist_ok=True)
    ch_dir = out_dir / "charts"
    ch_dir.mkdir(exist_ok=True)
    plt = _plt()
    if plt:
        rs = [r["rs"] for r in results]
        pre = [r["pre"] for r in results]
        post = [r["post"] for r in results]
        cal = [r["cal_fixes"] for r in results]
        fig, ax = plt.subplots(figsize=(7, 3.6))
        ax.plot(rs, pre, "o-", label="修正前（真实掌握度）", color="#c62828")
        ax.plot(rs, post, "s--", label="修正后（含校准）", color="#2e7d32")
        ax.axhline(0.8, ls=":", lw=1, color="gray")
        ax.text(rs[-1], 0.81, "验收线 0.8", fontsize=8, color="gray")
        ax.set_xlabel("训练轮次 R_S（108 条 × R_S）")
        ax.set_ylabel("分句接话命中率")
        ax.set_title("训练量 vs 句式掌握度（v16 108 条高质量对话/短文）")
        ax.legend(fontsize=8)
        ax.set_xticks(rs)
        fig.tight_layout()
        fig.savefig(ch_dir / "fig1_scale_hit.png", dpi=130)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(7, 3.2))
        ax.bar([str(r) for r in rs], cal, color="#4c78a8")
        ax.set_xlabel("训练轮次 R_S")
        ax.set_ylabel("校准处数（教师批改负担）")
        ax.set_title("训练量 vs 校准负担（越少 = 网络自己会得越多）")
        fig.tight_layout()
        fig.savefig(ch_dir / "fig2_cal_fixes.png", dpi=130)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(6, 3.2))
        ax.bar(["串行总和", "并发墙钟"], [serial_sec, wall_sec],
               color=["#9e9e9e", "#2e7d32"])
        ax.set_ylabel("秒")
        ax.set_title(f"并发训练加速（{MAX_WORKERS} 进程，{speedup:.2f}x）")
        for i, v in enumerate([serial_sec, wall_sec]):
            ax.text(i, v + 5, f"{v:.0f}s", ha="center", fontsize=9)
        fig.tight_layout()
        fig.savefig(ch_dir / "fig3_concurrent.png", dpi=130)
        plt.close(fig)

    # ── 4. 留档 ───────────────────────────────────────────────
    result = {
        "tag": "v16 训练量缩放探测（并发训练 × 轮次缩放）",
        "base": "15.0", "data": "stage3_rel_v2.json（108 条）",
        "points": results,
        "concurrent": {"wall_sec": round(wall_sec, 1),
                       "serial_sec": round(serial_sec, 1),
                       "speedup": round(speedup, 2),
                       "workers": MAX_WORKERS,
                       "crash": False},
        "toutiao_stats": stats,
        "wall_total_sec": round(time.time() - t0, 1),
    }
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False,
                                                    indent=1), encoding="utf-8")
    print(f"\n[留档] {out_dir / 'result.json'}")
    print(f"════ 总耗时 {time.time() - t0:.0f}s ════")


if __name__ == "__main__":
    main()
