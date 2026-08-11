# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""Stage 3 探测（v2）：句式颗粒度升级现状（v15.0）。

背景（2026-08-10 用户）：
  - "s3 在句式上的颗粒度不够，句式的复杂度没有这么低"——当前 s3 训练数据
    是 [关系词1, X, 关系词2, Y] 四词定式（11 条），真实关系句 8-20 词、
    内容小句化、关系词位置多样、可嵌套
  - 用户决策：四维全升（内容小句化 / 关系词位置多样 / 嵌套复合 /
    句内修饰加长）+ 先探测再定方案
  - 用户质疑："目前是不是句子太少了？需不需要找一些开源语料来注入？"

本探测三模块（全部只读：不改网络、不训练、不存快照）：
  1. 真实语料复杂度统计（stage3_sents.json 15000 句）
     ——长度分布 / 关系词位置 / 配对 vs 单用 → 量化"真实复杂度长什么样"
  2. 升级句式读取现状
     ——用 v15.0 词表内词构造 6-8 词小句化句式，逐词前缀测 prefix_next
        → 定位读取机制缺口（配对直读过度触发 / 后半关系词上下文缺失 /
           主语结尾断读）
  3. 小句化转移边现状
     ——关键 bigram 边（今天→下雨、他→生病、我们→去 等）是否存在：
        真实语料共现已建边 vs s3 专门定式缺边

结论：回答 ① 复杂度差距多大 ② 读取机制断在哪 ③ 要不要注入开源语料、
     以及 v16 数据/机制改造方向。

用法：python _probe_s3adv.py
输出：runs/_speak_logs/{ts}_probe_s3adv/result.json + charts/
"""

import json
import time
from collections import Counter
from pathlib import Path

import numpy as np

from snapshot import load_version
from _grow_v11 import edge_between
from _grow_v15 import direct_next, prefix_next, REL_NEXT, DOMAIN_WORDS as DOMAIN

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"

REL_WORDS = ["因为", "所以", "虽然", "但是", "先", "然后"]

# ── 模块 2：升级句式样本（全部词已验证在 v15.0 词表内）──────────
# (句子 tokens, 标签, 每步合法候选 dict: 前缀长度 → 合法候选集)
# 合法候选 = 该位置真实读法应输出的词（人工标注，覆盖 4 维升级）
SENT_ITEMS = [
    (["因为", "今天", "下雨", "所以", "我", "带伞"],
     "因果·小句化",
     {1: ["今天", "下雨", "他", "饿"],      # 因为→原因内容（小句）
      2: ["下雨"],                          # 今天→下雨（修饰）
      3: ["所以"],                          # 下雨→所以（因果链）
      4: ["我", "他", "我们"],              # 所以→结果主语
      5: ["带伞", "睡觉", "吃饭", "看医生"]}),  # 我→结果谓语
    (["虽然", "他", "生病", "了", "但是", "他", "上课"],
     "转折·小句化·助词了",
     {1: ["他", "下雨", "累", "困"],
      2: ["生病", "累"],
      3: ["了", "但是"],
      4: ["但是"],
      5: ["他", "我", "我们"],
      6: ["上课", "坚持", "跑步"]}),
    (["先", "吃饭", "然后", "我", "写作业"],
     "顺序·主语后置",
     {1: ["吃饭", "洗手", "刷牙"],
      2: ["然后"],
      3: ["我", "他", "我们"],
      4: ["写作业", "睡觉", "吃饭"]}),
    (["因为", "他", "累", "所以", "他", "睡觉"],
     "因果·主语重复",
     {1: ["他", "今天", "下雨", "饿"],
      2: ["累", "生病"],
      3: ["所以"],
      4: ["他", "我"],
      5: ["睡觉", "带伞", "看医生"]}),
    (["虽然", "下雨", "但是", "我们", "去", "公园"],
     "转折·去公园",
     {1: ["下雨", "累", "困"],
      2: ["但是"],
      3: ["我们", "他", "我"],
      4: ["去", "看"],
      5: ["公园", "家", "学校", "商店"]}),
    (["因为", "饿", "所以", "我", "吃饭"],
     "因果·4词+主语",
     {1: ["饿", "下雨", "生病", "困"],
      2: ["所以"],
      3: ["我", "他"],
      4: ["吃饭", "睡觉"]}),
]

# ── 模块 3：小句化关键转移边（真实语料共现 vs 专门定式）──────────
# (src, dst, 说明)——升级句式的内容小句转移，是否已有边
EDGE_ITEMS = [
    ("因为", "今天", "因果词→时间（真实语料共现？）"),
    ("因为", "他", "因果词→主语"),
    ("今天", "下雨", "时间修饰（今天下雨）"),
    ("他", "生病", "主谓小句（他生病）"),
    ("他", "累", "主谓小句（他累）"),
    ("我们", "去", "主谓小句（我们去）"),
    ("去", "公园", "动宾（去公园）"),
    ("所以", "我", "结果→主语（所以我）"),
    ("但是", "他", "转折→主语（但是他）"),
    ("然后", "我", "顺序→主语（然后我）"),
    ("所以", "带伞", "结果内容（定式边）"),
    ("但是", "上课", "转折内容（定式边）"),
]


def _plt():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
        plt.rcParams["axes.unicode_minus"] = False
        return plt
    except Exception as e:
        print(f"    [charts] matplotlib 不可用，跳过出图：{e}")
        return None


def main():
    t0 = time.time()
    ng, vocab, pats, cursor = load_version("15.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    print(f"[加载] 15.0：n={ng.n}，词表 {len(keys)} 词，cursor={cursor}\n")

    result = {"tag": "Stage 3 句式颗粒度升级探测（v15.0）", "base": "15.0"}

    # ── 模块 1：真实语料复杂度统计 ──────────────────────────────
    print("[模块1] 真实语料复杂度统计（stage3_sents.json 15000 句）")
    raw = json.loads((DATA / "stage3_sents.json").read_text(encoding="utf-8"))
    # 语料结构 = token 列表（jieba 分词词序列），非字符串
    sents = [list(s) if isinstance(s, list) else list(str(s)) for s in raw]
    rel_sents = [s for s in sents if any(r in s for r in REL_WORDS)]
    print(f"  总句 {len(sents)}，含关系词句 {len(rel_sents)}"
          f"（{len(rel_sents) / len(sents):.1%}）")

    # 长度分布（含关系词的句子，按 token 数）
    lens = Counter(len(s) for s in rel_sents)
    len_hist = {str(k): v for k, v in sorted(lens.items())}
    len_mean = sum(len(s) for s in rel_sents) / len(rel_sents)
    print(f"  关系句 token 长度：均值 {len_mean:.1f}，"
          f"分布（≤8 词 {sum(v for k, v in lens.items() if int(k) <= 8)} 句，"
          f"9-16 词 {sum(v for k, v in lens.items() if 9 <= int(k) <= 16)} 句，"
          f">16 词 {sum(v for k, v in lens.items() if int(k) > 16)} 句）")

    # 关系词位置 + 配对/单用
    pos2 = {r: [0, 0, 0] for r in REL_WORDS}      # [句首, 句中, 句尾]
    pair_stats = Counter()
    for s in rel_sents:
        n = len(s)
        for i, tok in enumerate(s):
            if tok in REL_WORDS:
                frac = i / max(1, n)
                pos2[tok][0 if frac < 0.33 else 1 if frac < 0.66 else 2] += 1
        set_s = set(s)
        if "因为" in set_s or "所以" in set_s:
            pair_stats["因果配对"] += ("因为" in set_s and "所以" in set_s)
            pair_stats["因果单用"] += (("因为" in set_s) != ("所以" in set_s))
        if "虽然" in set_s or "但是" in set_s:
            pair_stats["转折配对"] += ("虽然" in set_s and "但是" in set_s)
            pair_stats["转折单用"] += (("虽然" in set_s) != ("但是" in set_s))
        if "先" in set_s or "然后" in set_s:
            pair_stats["顺序配对"] += ("先" in set_s and "然后" in set_s)
            pair_stats["顺序单用"] += (("先" in set_s) != ("然后" in set_s))
    pos_lab = ["句首", "句中", "句尾"]
    print("  关系词出现位置（句首/句中/句尾）：")
    for i, r in enumerate(REL_WORDS):
        print(f"    {r}：{' | '.join(f'{pos_lab[j]} {pos2[r][j]}' for j in range(3))}")
    print(f"  配对 vs 单用：{dict(pair_stats)}")

    # 短关系句筛选可行性（v16 数据候选：token 数 ≤14）
    short_pair = [s for s in rel_sents if len(s) <= 14 and (
        ("因为" in s and "所以" in s) or ("虽然" in s and "但是" in s)
        or ("先" in s and "然后" in s))]
    short_single = [s for s in rel_sents if len(s) <= 14 and s not in short_pair]
    print(f"  短关系句候选（≤14 词）：配对 {len(short_pair)} 条，"
          f"单用 {len(short_single)} 条")
    for s in short_pair[:8]:
        print(f"    配对: {' '.join(s)}")
    for s in short_single[:8]:
        print(f"    单用: {' '.join(s)}")

    # 模块1 图表
    plt = _plt()
    charts = []
    if plt:
        out_dir = RUNS_DIR / "_speak_logs" / (
            f"{time.strftime('%Y%m%d_%H%M%S')}_probe_s3adv")
        ch = out_dir / "charts"
        ch.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(8, 3.4))
        ks = sorted(int(k) for k in len_hist)
        vs = [len_hist[str(k)] for k in ks]
        ax.bar([str(k) for k in ks], vs, color="#4c78a8", width=0.8)
        ax.axvline(4.5, ls="--", lw=1, color="red")
        ax.text(4.5, max(vs) * 0.95, "s3 现句式\n(4 词定式)",
                fontsize=8, color="red", ha="right")
        ax.set_xlabel("关系句 token 长度")
        ax.set_ylabel("句数")
        ax.set_title(f"真实语料关系句长度分布（{len(rel_sents)} 句，"
                     f"均值 {len_mean:.1f} 词）")
        fig.tight_layout()
        fig.savefig(ch / "fig1_len_dist.png", dpi=130)
        plt.close(fig)
        charts.append("fig1_len_dist.png")

        # 位置分布（堆叠条）
        fig, ax = plt.subplots(figsize=(7, 3.4))
        labels = REL_WORDS
        arr = np.array([pos2[r] for r in labels])
        bottom = np.zeros(len(labels))
        for i, (lab, col) in enumerate(zip(["句首", "句中", "句尾"],
                                           ["#2e7d32", "#f9a825", "#c62828"])):
            ax.bar(labels, arr[:, i], bottom=bottom, label=lab, color=col)
            bottom += arr[:, i]
        ax.set_ylabel("出现次数")
        ax.set_title("关系词出现位置分布（真实语料）")
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(ch / "fig2_rel_pos.png", dpi=130)
        plt.close(fig)
        charts.append("fig2_rel_pos.png")

    # ── 模块 2：升级句式读取现状（v15.0 prefix_next 纯读）──────
    print("\n[模块2] 升级句式读取现状（v15.0 prefix_next 逐词前缀）")
    print("  ✓ = top-1 ∈ 合法候选 | △ = 候选在 top 内 | ✗ = 断读")
    sent_rows = []
    n_ok = n_tot = 0
    for tokens, tag, cands in SENT_ITEMS:
        print(f"\n  【{''.join(tokens)}】（{tag}）")
        rows = []
        # 校验样本词全在词表（探测前置）
        miss = [w for w in tokens if w not in keys]
        if miss:
            print(f"    样本词缺失: {miss}（跳过）")
            continue
        for ln in range(1, len(tokens)):
            prefix = tokens[:ln]
            expect = cands.get(ln, [])
            top = prefix_next(ng, pats, n2w, prefix, k=6, domain=DOMAIN)
            hit1 = top[0][0] in expect if top else False
            hit3 = any(w in expect for w, _ in top[:3])
            n_tot += 1
            n_ok += hit1
            mark = "✓" if hit1 else "△" if hit3 else "✗"
            gap = ("配对直读" if (len(prefix) >= 2 and
                                  prefix[-2] in REL_NEXT and not hit1) else
                   "读最后词" if not hit1 else "")
            print(f"    {mark}「{''.join(prefix)}」→ {top[:4]}"
                  f"{'（期待: ' + '、'.join(expect) + '）' if not hit1 else ''}"
                  f"{f'  [缺口:{gap}]' if gap else ''}")
            rows.append({"prefix": "".join(prefix), "expect": expect,
                         "top": top[:6], "hit_top1": hit1,
                         "hit_top3": hit3, "gap": gap})
        sent_rows.append({"sent": "".join(tokens), "tag": tag, "rows": rows})
    print(f"\n  [升级句式读取] {n_ok}/{n_tot} 步 top-1 命中"
          f"（{n_ok / max(1, n_tot):.3f}）")

    # 模块2 图表：每句前缀命中热力（✓/△/✗）
    if plt:
        fig, ax = plt.subplots(figsize=(9, 3.6))
        all_prefix = []
        for sr in sent_rows:
            for r in sr["rows"]:
                all_prefix.append(r["prefix"])
        h1 = [1 if r["hit_top1"] else 0 for sr in sent_rows for r in sr["rows"]]
        h3 = [1 if r["hit_top3"] and not r["hit_top1"] else 0
              for sr in sent_rows for r in sr["rows"]]
        x = np.arange(len(all_prefix))
        ax.bar(x, h1, color="#2e7d32", label="top-1 命中")
        ax.bar(x, h3, bottom=np.array(h1, dtype=float),
               color="#f9a825", label="候选在 top-3")
        ax.set_xticks(x)
        ax.set_xticklabels(all_prefix, rotation=45, ha="right", fontsize=7)
        ax.set_ylim(0, 1.15)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["断读", "命中"])
        ax.set_title(f"升级句式前缀读取（top-1 {n_ok}/{n_tot}）——"
                     f"配对直读/读最后词 断点定位")
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(ch / "fig3_prefix_read.png", dpi=130)
        plt.close(fig)
        charts.append("fig3_prefix_read.png")

    # ── 模块 3：小句化关键转移边现状 ────────────────────────────
    print("\n[模块3] 小句化关键转移边（edge_between 实查）")
    edge_rows = []
    for src, dst, note in EDGE_ITEMS:
        w = edge_between(ng, pats, src, dst)
        ok = w > 0.1
        edge_rows.append({"src": src, "dst": dst, "w": round(w, 3),
                          "has": bool(ok), "note": note})
        print(f"  {'✓' if ok else '✗'} {src}→{dst} = {w:.3f}（{note}）")
    n_edge_ok = sum(1 for e in edge_rows if e["has"])
    print(f"  [小句化边] {n_edge_ok}/{len(edge_rows)} 已有边"
          f"（缺边 = 需要 v16 专门训练或注入）")

    # ── 汇总结论 ────────────────────────────────────────────────
    print("\n[汇总]")
    print(f"  真实复杂度：关系句均值 {len_mean:.1f} 字（s3 现句式 8 字=4 词）"
          f"，位置/配对多样（见模块1）")
    print(f"  读取断点：{n_tot - n_ok}/{n_tot} 步断读——"
          f"配对直读过度触发 + 后半关系词上下文缺失 + 主语结尾断读")
    print(f"  小句化边：{n_edge_ok}/{len(edge_rows)} 已有（缺边集中在"
          f" 关系词→主语、主谓小句 → 需专门训练）")

    result.update({
        "corpus_total": len(sents),
        "corpus_rel": len(rel_sents),
        "len_mean": round(len_mean, 1),
        "len_hist": len_hist,
        "rel_pos": {r: pos2[r] for r in REL_WORDS},
        "pair_stats": dict(pair_stats),
        "sent_read": sent_rows, "read_ok": n_ok, "read_tot": n_tot,
        "edges": edge_rows, "edge_ok": n_edge_ok, "edge_tot": len(edge_rows),
        "charts": charts, "time_s": round(time.time() - t0, 1)})

    out = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_probe_s3adv"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False,
                                                indent=1), encoding="utf-8")
    print(f"\n[留档] {out / 'result.json'} + charts/（{time.time() - t0:.0f}s）")


if __name__ == "__main__":
    main()
