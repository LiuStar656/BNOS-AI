# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""Stage 3 探测：复杂句式对话能力现状（v14.0）。

复刻 v13 probe_complex 口径（整句复述 + 前缀续推），在 v14.0 上验证：
  - 记住性：复杂句/关系句整句复述率
  - 接话性：前缀续推 top 词（我想要→? / 因为下雨→? / 先吃饭→?）
  - 链式接话：关系词定式链（因为→…→带伞）每步能否按边接出来

对比基线：v13 探测（12.0）「我想要」→ 的/了/是 霸榜（推不出苹果，转移定式缺位）。

用法：python _probe_s3.py
输出：runs/_speak_logs/{ts}_probe_s3/result.json + charts/ 图表
"""

import json
import time
from collections import Counter
from pathlib import Path

import numpy as np

from schema_net import build_pulse
from snapshot import load_version
from _grow_zh import run_recall, fire_ratio
from _grow_v11 import sent_recall, edge_between
from _grow_s3 import relation_self_judge, ITEMS

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"

# ── 复述样本（按类型分组）──────────────────────────────────────
RECALL_ITEMS = [
    ("简单句基线", ["我要苹果", "他看石头", "我吃西瓜", "我们看公园"]),
    ("A型 S想要O", ["我想要苹果", "我想要牛奶", "我想吃西瓜", "他想要石头"]),
    ("B型 S在VO", ["他在看石头", "他在看公园", "我在吃西瓜", "猫在看石头"]),
    ("关系句·训练", ["因为下雨所以带伞", "先吃饭然后写作业",
                    "虽然下雨但是跑步", "因为饿所以吃饭"]),
    ("关系句·未训练", ["因为下雨所以吃饭", "虽然下雨但是坚持"]),
]

# ── 前缀续推（词级 token 注入；预期词 = 定式/固化应推出的词）───
PREFIX_ITEMS = [
    (["我", "想要"], ["苹果"], "v13 固化 想要→苹果"),
    (["他", "在"], ["看"], "v13 固化 B 型"),
    (["因为"], ["下雨", "所以"], "关系词出边（内容词 + 跟读直连）"),
    (["因为", "下雨"], ["所以"], "关系定式链"),
    (["所以"], ["带伞", "吃饭"], "关系词后接"),
    (["先", "吃饭"], ["然后"], "顺序定式链"),
    (["然后"], ["写作业", "吃饭", "睡觉"], "顺序词后接"),
    (["虽然"], ["下雨", "累", "困"], "转折词出边"),
    (["虽然", "下雨"], ["但是"], "转折定式链"),
    (["但是"], ["跑步", "坚持", "上课"], "转折词后接"),
]

# 高频虚词枢纽（注意力=连接数量：多源汇聚的枢纽始终霸榜续推）
# 滤噪后若定式词出现 → 信号存在但被枢纽压过（读取失败，非学习失败）
NOISE = {"的", "了", "是", "有", "什么", "为什么", "世界", "好", "一",
         "在", "不", "很", "都", "把", "被", "就", "又", "也", "上",
         "下", "大", "小", "说", "去", "来", "到", "个", "这", "那",
         "还", "才", "再", "能", "会", "要", "想", "看", "里", "和",
         "与", "或", "之", "中", "为", "向", "从", "而", "对", "同"}

# ── 直接出边问答（开放式补全："X → ?" 读 X 的直接出边，不走涟漪）──
# 预期 = 训练/固化定式应回答的词。验证"答案是否就在边里"。
QA_ITEMS = [
    ("因为", ["下雨", "所以"], "因果词后接"),
    ("下雨", ["所以", "但是"], "内容词双出边（对称竞争点）"),
    ("所以", ["带伞", "吃饭"], "因果词后接"),
    ("想要", ["苹果", "牛奶", "香蕉", "饼干", "石头"], "想要族宾语"),
    ("先", ["吃饭", "洗手", "刷牙"], "顺序词后接"),
    ("然后", ["写作业", "吃饭", "睡觉"], "顺序词后接"),
    ("虽然", ["下雨", "累", "困"], "转折词后接"),
    ("但是", ["跑步", "坚持", "上课"], "转折词后接"),
    ("看", ["石头", "公园", "家", "商店"], "v10 动宾"),
    ("吃", ["苹果", "西瓜", "米饭"], "v10 动宾"),
]


def top_words(ng, pats, n2w, prefix, k=6, exclude=()):
    """前缀续推：注入前缀 → 冻结检索 → 按词统计被唤起神经元数。"""
    neurons = [j for w in prefix for j in pats.get(w, [])]
    if not neurons:
        return []
    fired = run_recall(ng, build_pulse(ng.n, neurons))
    cnt = Counter()
    for j in fired:
        w = n2w.get(j)
        if not w or w in exclude or w in set(prefix):
            continue
        cnt[w] += 1
    return cnt.most_common(k)


def next_words_direct(ng, pats, n2w, src, k=6):
    """直接出边读取：src 词神经元的 W_out 汇聚到目标词，取最强 top。

    不走涟漪/不走 WTA——把"答案"当网络里的边直接读（方案 A：直接边接话）。
    返回 [(词, 边权汇聚), ...]。
    """
    scores = Counter()
    for i in pats.get(src, []):
        row = ng.W_out[i][0]
        if row:
            for j, wt in row.items():
                w = n2w.get(j)
                if not w or w == src:
                    continue
                scores[w] += wt
    return scores.most_common(k)


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
    ng, vocab, pats, cursor = load_version("14.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    print(f"[加载] 14.0：n={ng.n}，模式 {len(pats)}，cursor={cursor}\n")

    rows = []

    # ── 1. 整句复述（记住性）──
    print("[整句复述]（输入整句 → 各词回响比例；1.000 只证明记住词）")
    recall_stats = {}
    for tag, sents in RECALL_ITEMS:
        vals = [round(sent_recall(ng, pats, list(s)), 3) for s in sents]
        recall_stats[tag] = vals
        print(f"  {tag}: " + ", ".join(f"{s}={v}" for s, v in zip(sents, vals)))
        for s, v in zip(sents, vals):
            rows.append({"type": "复述", "tag": tag, "sent": s, "recall": v})

    # ── 2. 前缀续推（接话性；原始 + 滤噪两口径）──
    print("\n[前缀续推]（注入前缀 → 冻结检索 top-6；排除前缀词）")
    print("  原始 top 与滤噪（排除高频虚词枢纽）对照，判断定式信号是否存在")
    prefix_stats = []
    for prefix, expect, note in PREFIX_ITEMS:
        top_raw = top_words(ng, pats, n2w, prefix, k=6)
        top = top_words(ng, pats, n2w, prefix, k=6, exclude=NOISE)
        hit1 = top[0][0] if top else None
        hit3 = any(w in expect for w, _ in top[:3])
        hit6 = any(w in expect for w, _ in top)
        prefix_stats.append({"prefix": "".join(prefix), "expect": expect,
                             "top_raw": top_raw[:4], "top": top[:6],
                             "hit_top1": hit1 in expect,
                             "hit_top3": hit3, "hit_top6": hit6,
                             "note": note})
        mark = ("✓" if hit1 else "△" if hit3 else "✗")
        print(f"  {mark}「{''.join(prefix)}」"
              f"滤噪 top {top[:4]}"
              f"{'（原始 ' + '、'.join(w for w, _ in top_raw[:3]) + '）' if top_raw else ''}"
              f"{'  预期: ' + '、'.join(expect) if not hit1 else ''}")
        rows.append({"type": "前缀续推", "prefix": "".join(prefix),
                     "expect": expect, "top_raw": top_raw[:6], "top": top[:6],
                     "hit_top1": hit1 in expect, "hit_top3": hit3,
                     "hit_top6": hit6, "note": note})

    # ── 2.5 回答能力：判断问答（能说/不能说）+ 直接出边补全问答 ──
    print("\n[判断问答]（给关系句 → 网络回答 可造/不可造/不知道；与教师判定对照）")
    qa_judge = []
    for tokens, level, judge, gt, gt_basis in ITEMS:
        vd, conf, path = relation_self_judge(ng, pats, n2w, tokens)
        ok = (vd == gt)
        qa_judge.append({"sent": "".join(tokens), "level": level,
                         "self": vd, "gt": gt, "ok": ok})
        print(f"  {'✓' if ok else '✗'}「{''.join(tokens)}」({level}) "
              f"网络={vd} vs 答案={gt}")
    n_jok = sum(1 for q in qa_judge if q["ok"])
    print(f"  [判断问答] 回答正确 {n_jok}/{len(qa_judge)}"
          f"（基础/巩固 1.000，拓展语义盲区除外）")

    print("\n[直接出边问答]（'X → ?' 读 X 直接出边 top，不走涟漪）")
    qa_direct = []
    for src, expect, note in QA_ITEMS:
        top = next_words_direct(ng, pats, n2w, src, k=6)
        hit1 = top[0][0] in expect if top else False
        hit3 = any(w in expect for w, _ in top[:3])
        qa_direct.append({"src": src, "expect": expect, "top": top,
                          "hit_top1": hit1, "hit_top3": hit3, "note": note})
        mark = "✓" if hit1 else "△" if hit3 else "✗"
        print(f"  {mark}「{src} → ?」top {top[:5]}"
              f"{'  预期: ' + '、'.join(expect) if not hit1 else ''}")
    n_d1 = sum(1 for q in qa_direct if q["hit_top1"])
    n_d3 = sum(1 for q in qa_direct if q["hit_top3"])
    print(f"  [直接出边问答] top-1 命中 {n_d1}/{len(qa_direct)}"
          f" | top-3 命中 {n_d3}/{len(qa_direct)}")

    # ── 3. 汇总 ──
    n_pfx = len(prefix_stats)
    n_hit1 = sum(1 for p in prefix_stats if p["hit_top1"])
    n_hit3 = sum(1 for p in prefix_stats if p["hit_top3"])
    print(f"\n[接话命中] {n_pfx} 个前缀：top-1 命中 {n_hit1}（{n_hit1 / n_pfx:.3f}）"
          f" | top-3 命中 {n_hit3}（{n_hit3 / n_pfx:.3f}）")

    out = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_probe_s3"
    out.mkdir(parents=True, exist_ok=True)
    result = {"tag": "复杂句式对话能力探测（v14.0）", "base": "14.0",
              "n": ng.n, "rows": rows,
              "recall_stats": recall_stats,
              "prefix_stats": prefix_stats,
              "hit_top1": n_hit1, "hit_top3": n_hit3, "n_prefix": n_pfx,
              "qa_judge": qa_judge, "n_judge_ok": n_jok,
              "qa_direct": qa_direct, "n_direct1": n_d1, "n_direct3": n_d3,
              "time_s": round(time.time() - t0, 1)}
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False,
                                                indent=1), encoding="utf-8")

    # ── 图表化（用户约定：实验数据必须用图表呈现）──
    plt = _plt()
    if plt:
        charts = out / "charts"
        charts.mkdir(parents=True, exist_ok=True)
        # 图1：复述率分组
        fig, ax = plt.subplots(figsize=(7, 3.4))
        tags, means = [], []
        for tag, vals in recall_stats.items():
            tags.append(tag)
            means.append(sum(vals) / len(vals))
        bars = ax.bar(tags, means, color="#4c78a8")
        for b, m in zip(bars, means):
            ax.text(b.get_x() + b.get_width() / 2, m + 0.01,
                    f"{m:.3f}", ha="center", fontsize=9)
        ax.set_ylim(0, 1.1)
        ax.axhline(0.9, ls="--", lw=0.8, color="gray")
        ax.set_ylabel("整句复述率（均值）")
        ax.set_title("v14.0 复杂句式整句复述（记住性）")
        fig.autofmt_xdate(rotation=0)
        fig.tight_layout()
        fig.savefig(charts / "fig1_recall.png", dpi=130)
        plt.close(fig)
        # 图2：前缀续推命中
        fig, ax = plt.subplots(figsize=(7, 3.4))
        labels = [p["prefix"] for p in prefix_stats]
        h1 = [1 if p["hit_top1"] else 0 for p in prefix_stats]
        h3 = [1 if p["hit_top3"] and not p["hit_top1"] else 0 for p in prefix_stats]
        x = np.arange(len(labels))
        ax.bar(x, h1, color="#2e7d32", label="top-1 命中")
        ax.bar(x, h3, bottom=h1, color="#f9a825", label="top-3 内")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
        ax.set_ylim(0, 1.15)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["未命中", "命中"])
        ax.set_title(f"v14.0 前缀续推接话（top-1 {n_hit1}/{n_pfx}，top-3 {n_hit3}/{n_pfx}）")
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(charts / "fig2_prefix.png", dpi=130)
        plt.close(fig)
        # 图3：回答能力——判断问答正确率 + 直接出边补全命中
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 3.4))
        lv_ok = {}
        for q in qa_judge:
            lv_ok.setdefault(q["level"], [0, 0])
            lv_ok[q["level"]][1] += 1
            lv_ok[q["level"]][0] += q["ok"]
        names = ["基础", "巩固", "拓展"]
        vals = [lv_ok.get(l, [0, 1])[0] / max(1, lv_ok.get(l, [0, 1])[1])
                for l in names]
        b = ax1.bar(names, vals, color="#4c78a8")
        for bb, v in zip(b, vals):
            ax1.text(bb.get_x() + bb.get_width() / 2, v + 0.02,
                     f"{v:.2f}", ha="center", fontsize=8)
        ax1.set_ylim(0, 1.1)
        ax1.set_ylabel("回答正确率（网络 vs 教师判定）")
        ax1.set_title(f"判断问答：能说/不能说（{n_jok}/{len(qa_judge)} 正确）")
        labels = [q["src"] for q in qa_direct]
        h1 = [1 if q["hit_top1"] else 0 for q in qa_direct]
        h3 = [1 if q["hit_top3"] and not q["hit_top1"] else 0 for q in qa_direct]
        x = np.arange(len(labels))
        ax2.bar(x, h1, color="#2e7d32", label="top-1 命中")
        ax2.bar(x, h3, bottom=h1, color="#f9a825", label="top-3 内")
        ax2.set_xticks(x)
        ax2.set_xticklabels(labels, rotation=25, ha="right", fontsize=8)
        ax2.set_ylim(0, 1.15)
        ax2.set_yticks([0, 1])
        ax2.set_yticklabels(["未中", "命中"])
        ax2.set_title(f"直接出边问答：X → ?（top-1 {n_d1}/{len(qa_direct)}）")
        ax2.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(charts / "fig3_qa.png", dpi=130)
        plt.close(fig)
        print(f"\n[图表] {charts}")
    print(f"\n[留档] {out / 'result.json'}（{time.time() - t0:.0f}s）")


if __name__ == "__main__":
    main()
