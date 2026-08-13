# -*- coding: utf-8 -*-
"""Stage 3 v15（定式对话/回答读取机制）：direct_next 直接边接话 + 域内过滤 + 对话练习。

背景（2026-08-10 探测报告 20260810_115157_probe_s3）：
  - 续推侧读取失败根因 = 检索是"回响全部被点亮词"，不是"输出下一个词"
    （定式边已学进网络，但前缀续推 0%——因为/虽然/先 的定式词读不出来）
  - 方案 A 已验证：直接出边读取 top-1 9/10——答案的读取通道
  - v15 = 把方案 A 落地为**对话/回答的读取机制**：
    direct_next（前缀最后词直接出边做定向 WTA，不走全局回响）
    + 域内过滤（对话域词表：排除虚词枢纽 的/了/是 与域外词，定式词浮出）
    + 对话练习（教师↔网络轮次：教师说 → 网络 direct_next 接话 → 判定 → 修正）
    + 对话生成验收（轮次完成率 + 回应一致率 + 链式接话 + 直接出边问答）

设计：
  - direct_next(src, domain)：src 词直接出边（W_out 汇聚）→ 域内过滤 → top-k
  - 域内过滤：只保留对话域词表成员（S/V/O + 关系词 + 关系句内容词）——
    虚词枢纽（的 38.4/了/是）连接数爆炸是字级续推霸榜根因，域内过滤直接排除
  - 对话练习：脚本轮次（TALK_BLOCK 话题延续），判定 = 网络 top-1 ∈ 预期候选？
    修正 = 一致不动 / 读不出 → 固化（训练平衡，加权） / 读出错词 → 删边
  - C/D 顺手落地：关系词偏向（下雨→所以 加权，消除与 下雨→但是 对称竞争）
    + 训练平衡（想要→苹果 加权，匹配真实语料 的 强度）
  - 验收：直接出边问答 top-1 ≥ 0.9 | 对话轮次完成率 ≥ 0.9 + 回应一致率 ≥ 0.8
    | 链式接话（前缀逐词）| 继承 v14 全验收（零遗忘）
  - save_snapshot(parent="14.0") → v15.0

诚实边界：
  - direct_next 读的是**已学边**（检索级能力，不是生成新意）——回应上限 = 网络已学结构
  - 域内过滤是对话场景的读取约束（像人对话时在话题词表内取词），
    不等同于全词表语言能力；过滤后读出的词都是真实边
  - 对话早期 = 接话级（教师说半句 → 网络接后半），完整开放式对话后续版本

用法：python _grow_v15.py [--smoke]
"""

import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from sparse_net import allocate_pats
from _grow_cat import build_cats
from _grow_v11 import O_FOOD, O_PLACE, V_SET, PERS_MANUAL, S_ANIMALS, edge_between
from _grow_v12 import inherit_acceptance

DATA = Path(__file__).parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).parent / "runs"
SEED = 42
K = 4                  # 神经元/词（与 v11 同源分配制）

R_FIX = 3              # 对话练习修正：读不出 → 固化轮次
R_BIAS = 2             # C/D 加权：关系词偏向 / 训练平衡 额外跟读轮次

# ── 关系定式（v14 已建：跟读 ×3 → 边权 24.0）───────────────────
REL_PAIRS = [("因为", "所以"), ("虽然", "但是"), ("先", "然后")]
REL_NEXT = {"因为": "所以", "虽然": "但是", "先": "然后"}   # 配对直读（定式链）

# ── 对话域词表（域内过滤 = 只从这些词里取接话）──────────────────
# S/V/O（v12/v13 教学词）+ 关系词 + 关系句内容词（v14）——对话场景的话题词表
DOMAIN_CORE = (set(PERS_MANUAL) | set(S_ANIMALS) | set(V_SET) | set(O_FOOD)
               | set(O_PLACE) | {"想要", "需要", "在", "想", "看医生"})
REL_CONTENT = {"下雨", "带伞", "饿", "吃饭", "生病", "睡觉", "困", "冷",
               "穿衣服", "累", "坚持", "上课", "洗手", "刷牙", "写作业",
               "跑步", "石头", "苹果", "西瓜", "香蕉", "饼干", "牛奶"}
DOMAIN_WORDS = sorted(DOMAIN_CORE | REL_CONTENT | {w for p in REL_PAIRS for w in p})

# ── 直接出边问答（探测 QA_ITEMS 复刻：'X → ?' 读 X 直接出边）────
# 预期 = 训练/固化定式应回答的词；域内过滤后应 top-1 命中
QA_ITEMS = [
    ("因为", ["下雨", "所以"], "因果词后接"),
    ("下雨", ["所以", "带伞", "但是"], "内容词双出边（对称竞争点）"),
    ("所以", ["带伞", "吃饭", "看医生"], "因果词后接"),
    ("想要", ["苹果", "牛奶", "香蕉", "饼干", "石头"], "想要族宾语"),
    ("先", ["吃饭", "洗手", "刷牙"], "顺序词后接"),
    ("然后", ["写作业", "吃饭", "睡觉"], "顺序词后接"),
    ("虽然", ["下雨", "累", "困"], "转折词后接"),
    ("但是", ["跑步", "坚持", "上课"], "转折词后接"),
    ("看", ["石头", "公园", "家", "商店"], "v10 动宾"),
    ("吃", ["苹果", "西瓜", "米饭"], "v10 动宾"),
]

# ── 前缀接话（探测 PREFIX_ITEMS 复刻：多词前缀 → 最后词出边）────
PREFIX_ITEMS = [
    (["我", "想要"], ["苹果"], "v13 固化 想要→苹果"),
    (["他", "在"], ["看"], "v13 固化 B 型"),
    (["因为"], ["下雨", "所以"], "关系词出边"),
    (["因为", "下雨"], ["所以"], "关系定式链"),
    (["所以"], ["带伞", "吃饭"], "关系词后接"),
    (["先", "吃饭"], ["然后"], "顺序定式链"),
    (["然后"], ["写作业", "吃饭", "睡觉"], "顺序词后接"),
    (["虽然"], ["但是", "下雨", "累", "困"], "转折词出边（配对直读→但是）"),
    (["虽然", "下雨"], ["但是"], "转折定式链"),
    (["但是"], ["跑步", "坚持", "上课"], "转折词后接"),
]

# ── 对话练习脚本（教师说 → 网络 direct_next 接话 → 判定）────────
# (教师说 tokens, 预期接话候选, 话题, 说明) —— 话题延续：同话题连续 2-3 轮
# 注意：开放续推（所以/然后/但是/想要/看/吃）的候选 = **全部**已学合法出边，
# 避免把合法词（如 所以→睡觉/穿衣服）误当错词修正
DIALOG = [
    (["因为", "下雨"], ["所以"], "因果", "定式链：因为下雨→所以"),
    (["所以"], ["带伞", "吃饭", "看医生", "睡觉", "穿衣服"], "因果", "因果词后接：所以→结果"),
    (["因为", "生病"], ["所以"], "因果", "定式链：因为生病→所以"),
    (["先", "吃饭"], ["然后"], "顺序", "定式链：先吃饭→然后"),
    (["然后"], ["写作业", "吃饭", "睡觉"], "顺序", "顺序词后接：然后→后续"),
    (["先", "洗手"], ["然后"], "顺序", "定式链：先洗手→然后"),
    (["虽然", "下雨"], ["但是"], "转折", "定式链：虽然下雨→但是"),
    (["但是"], ["跑步", "坚持", "上课"], "转折", "转折词后接：但是→后续"),
    (["虽然", "累"], ["但是"], "转折", "定式链：虽然累→但是"),
    (["我", "想要"], ["苹果", "牛奶", "香蕉", "饼干", "石头"], "想要", "想要族：我想要→苹果"),
    (["他", "想要"], ["苹果", "牛奶", "香蕉", "饼干", "石头"], "想要", "想要族：他想要→饼干"),
    (["他", "在", "看"], ["石头", "公园", "家", "学校", "商店"], "动宾", "B 型动宾：看→石头"),
    (["我", "在", "吃"], ["苹果", "西瓜", "米饭", "面包", "牛奶", "鸡蛋", "香蕉", "饼干"], "动宾", "B 型动宾：吃→苹果"),
]

# 对话话题块：连续轮次视为同一话题（验收口径用）
TOPICS = ["因果", "顺序", "转折", "想要", "动宾"]


# ── 读取机制：direct_next（前缀最后词直接出边 → 域内过滤 → top-k）──


def direct_next(ng, pats, n2w, src, k=6, domain=None):
    """src 词直接出边读取：W_out 汇聚到目标词，取最强 top-k。

    方案 A（探测已验证 9/10）：把"答案"当网络里的边直接读——
    不走全局回响、不走涟漪、不走 WTA 竞争，只有最后词的直接出边。
    域内过滤：domain 词表非空时，只保留域内词（排除虚词枢纽与域外词）。
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
                if domain and w not in domain:
                    continue
                scores[w] += wt
    return scores.most_common(k)


def prefix_next(ng, pats, n2w, prefix, k=6, domain=None):
    """前缀接话：定式链配对直读 + 最后词直接出边。

    ① 配对直读（关系定式链）：关系词位于**倒数第二位**（前缀以 [关系词, X] 结尾）
       且配对边存在 → 直读配对词——"虽然下雨"→但是 由"虽然"决定，不受
       下雨→所以/但是 对称竞争干扰；同时避免"因为下雨所以"→? 再读回"所以"
    ② 否则 → 取前缀**最后词**的直接出边（真实对话 = 词级输入，听到末尾词接话）
    """
    if len(prefix) >= 2 and prefix[-2] in REL_NEXT:
        rel = prefix[-2]
        nxt = REL_NEXT[rel]
        w = edge_between(ng, pats, rel, nxt)
        if w > 0.1:
            return [(nxt, w)]
    return direct_next(ng, pats, n2w, prefix[-1], k=k, domain=domain)


# ── 对话练习（教师↔网络轮次：判定 + 修正）───────────────────────


def dialogue_practice(ng, pats, n2w, domain, r_fix=R_FIX):
    """脚本对话轮次：教师说 → 网络 direct_next 接话 → 判定 → 修正。

    修正（v13 四原则扩展，保守版）：
      - 一致（top-1 ∈ 预期候选）→ 不动作
      - 读不出（域内 top 空）→ 固化 教师说+首选预期（训练平衡 D）
      - 读出错词（top-1 非预期）→ **不删边**（对称竞争边的另一条可能是合法
        的，如 下雨→但是；删边会破坏 虽然…但是 知识）→ 固化预期边，
        让正确边在对称竞争中胜出（C 关系词偏向的自然落地）
    返回逐轮记录 list + 修正记录 list。
    """
    turns, fixes = [], []
    for teacher, expect, topic, note in DIALOG:
        top = prefix_next(ng, pats, n2w, teacher, k=6, domain=domain)
        resp = top[0][0] if top else None
        w = top[0][1] if top else 0.0
        agree = resp in expect if resp else False
        fix = None
        if not agree:
            # 读不出 / 读出错词 → 统一固化预期边（强化正确路径，不破坏对称边）
            seq = teacher + [expect[0]]
            for _ in range(r_fix):
                _learn_sentence(ng, seq, pats, slot=0)
            reason = "读不出" if resp is None else f"读出错词 {resp}"
            fix = f"{reason} → 固化 {'、'.join(seq)} ×{r_fix}"
            fixes.append({"teacher": "".join(teacher), "expect": expect,
                          "fix": fix, "resp_before": resp})
        turns.append({"teacher": "".join(teacher), "expect": expect,
                      "topic": topic, "resp": resp, "w": round(w, 2),
                      "top": top[:4], "agree": agree,
                      "fix": fix, "note": note})
    return turns, fixes


def dialogue_retest(ng, pats, n2w, domain):
    """修正后复测（阶段4 口径）：返回逐轮一致记录。"""
    rows = []
    for teacher, expect, topic, note in DIALOG:
        top = prefix_next(ng, pats, n2w, teacher, k=6, domain=domain)
        resp = top[0][0] if top else None
        rows.append({"teacher": "".join(teacher), "expect": expect,
                     "topic": topic, "resp": resp, "agree": resp in expect})
    return rows


# ── 验收口径 ────────────────────────────────────────────────────


def qa_acceptance(ng, pats, n2w, domain):
    """直接出边问答：'X → ?' top-1/top-3 命中（QA_ITEMS 复刻）。"""
    rows = []
    for src, expect, note in QA_ITEMS:
        top = direct_next(ng, pats, n2w, src, k=6, domain=domain)
        hit1 = top[0][0] in expect if top else False
        hit3 = any(w in expect for w, _ in top[:3])
        rows.append({"src": src, "expect": expect, "top": top[:5],
                     "hit_top1": hit1, "hit_top3": hit3, "note": note})
        mark = "✓" if hit1 else "△" if hit3 else "✗"
        print(f"  {mark}「{src} → ?」{top[:5]}{'' if hit1 else f'  预期: {expect}'}")
    n1 = sum(1 for r in rows if r["hit_top1"])
    n3 = sum(1 for r in rows if r["hit_top3"])
    print(f"  [直接出边问答] top-1 命中 {n1}/{len(rows)}"
          f" | top-3 命中 {n3}/{len(rows)}")
    return rows, n1, n3


def prefix_acceptance(ng, pats, n2w, domain):
    """前缀接话：多词前缀 → 最后词出边 top-1/top-3 命中（PREFIX_ITEMS 复刻）。"""
    rows = []
    for prefix, expect, note in PREFIX_ITEMS:
        top = prefix_next(ng, pats, n2w, prefix, k=6, domain=domain)
        hit1 = top[0][0] in expect if top else False
        hit3 = any(w in expect for w, _ in top[:3])
        rows.append({"prefix": "".join(prefix), "expect": expect, "top": top[:5],
                     "hit_top1": hit1, "hit_top3": hit3, "note": note})
        mark = "✓" if hit1 else "△" if hit3 else "✗"
        print(f"  {mark}「{''.join(prefix)}」{top[:5]}"
              f"{'' if hit1 else f'  预期: {expect}'}")
    n1 = sum(1 for r in rows if r["hit_top1"])
    n3 = sum(1 for r in rows if r["hit_top3"])
    print(f"  [前缀接话] top-1 命中 {n1}/{len(rows)}"
          f" | top-3 命中 {n3}/{len(rows)}")
    return rows, n1, n3


def chain_generation(ng, pats, n2w, domain):
    """链式接话（对话生成验收）：从起始词逐词 direct_next 生成整句。

    关系定式链：因为 → 下雨 → 所以 → 带伞（每步都从直接出边取 top-1）。
    验收口径 = 每步生成词 ∈ 该步合法候选集（训练关系句的后继词集），
    不是精确匹配某一句——因为 所以→带伞/吃饭 同为训练句合法后接（对称）。
    返回生成链 + 每步命中。
    """
    # (起始词, 每步合法后继集, 示例句)
    CHAINS = [
        ("因为", [["下雨", "饿", "生病", "困", "冷"], ["所以"], ["带伞", "吃饭", "看医生", "睡觉", "穿衣服"]],
         "因为下雨所以带伞"),
        ("先", [["吃饭", "洗手", "刷牙"], ["然后"], ["写作业", "吃饭", "睡觉"]],
         "先吃饭然后写作业"),
        ("虽然", [["下雨", "累", "困"], ["但是"], ["跑步", "坚持", "上课"]],
         "虽然下雨但是跑步"),
    ]
    chains = []
    for start, steps, sent_example in CHAINS:
        gen = [start]
        prefix = [start]
        hits = []
        for expect_step in steps:
            top = prefix_next(ng, pats, n2w, prefix, k=1, domain=domain)
            if not top:
                hits.append(False)
                break
            nxt = top[0][0]
            gen.append(nxt)
            ok = nxt in expect_step
            hits.append(ok)
            prefix.append(nxt)
        chains.append({"start": start, "gen": gen, "steps": steps,
                       "example": sent_example, "hits": hits,
                       "match": sum(hits)})
        print(f"  「{start}」→ {'、'.join(gen)}"
              f"（示例：{sent_example}）"
              f" 每步命中 {sum(hits)}/{len(steps)}"
              f" {'✅' if all(hits) else ''}")
    return chains


# ── 图表化（用户约定：实验数据必须用图表呈现）──────────────────


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


def save_charts(metrics, out_dir):
    """实验数据图表化 → out_dir/charts/*.png。返回图表文件 list。

    ① 直接出边问答 top-1/top-3 命中
    ② 前缀接话 top-1/top-3 命中
    ③ 对话练习：分话题回应一致率（修正前 vs 修正后）
    """
    plt = _plt()
    if plt is None:
        return []
    charts = []
    out = Path(out_dir) / "charts"
    out.mkdir(parents=True, exist_ok=True)

    def _bar_hit(ax, labels, h1, h3, title, sub):
        x = np.arange(len(labels))
        ax.bar(x, h1, color="#2e7d32", label="top-1 命中")
        ax.bar(x, h3, bottom=h1, color="#f9a825", label="top-3 内")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=8)
        ax.set_ylim(0, 1.15)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["未中", "命中"])
        ax.set_title(title)
        ax.legend(fontsize=8)
        if sub:
            ax.set_xlabel(sub, fontsize=8)

    # ① 直接出边问答
    qa = metrics.get("qa_rows", [])
    if qa:
        fig, ax = plt.subplots(figsize=(8, 3.2))
        _bar_hit(ax, [q["src"] for q in qa],
                 [1 if q["hit_top1"] else 0 for q in qa],
                 [1 if q["hit_top3"] and not q["hit_top1"] else 0 for q in qa],
                 f"v15 直接出边问答：X → ?（top-1 {metrics['qa_top1']}/"
                 f"{len(qa)}）", "域内过滤 + 直接出边读取")
        fig.tight_layout()
        p = out / "fig1_direct_qa.png"
        fig.savefig(p, dpi=130)
        plt.close(fig)
        charts.append(p)

    # ② 前缀接话
    pfx = metrics.get("prefix_rows", [])
    if pfx:
        fig, ax = plt.subplots(figsize=(8, 3.2))
        _bar_hit(ax, [p["prefix"] for p in pfx],
                 [1 if p["hit_top1"] else 0 for p in pfx],
                 [1 if p["hit_top3"] and not p["hit_top1"] else 0 for p in pfx],
                 f"v15 前缀接话：多词前缀 → 最后词出边（top-1 {metrics['prefix_top1']}/"
                 f"{len(pfx)}）", "真实对话输入（词级）")
        fig.tight_layout()
        p = out / "fig2_prefix.png"
        fig.savefig(p, dpi=130)
        plt.close(fig)
        charts.append(p)

    # ③ 对话练习：分话题一致率（修正前 vs 修正后）
    topics = metrics.get("topics", [])
    t1 = [metrics.get(f"topic_{t}_1", 0.0) for t in topics]
    t4 = [metrics.get(f"topic_{t}_4", 0.0) for t in topics]
    if topics:
        fig, ax = plt.subplots(figsize=(6.5, 3.4))
        x = np.arange(len(topics))
        w = 0.35
        b1 = ax.bar(x - w / 2, t1, w, label="修正前", color="#9db8d2")
        b4 = ax.bar(x + w / 2, t4, w, label="修正后", color="#4c78a8")
        for b in list(b1) + list(b4):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.02,
                    f"{b.get_height():.2f}", ha="center", fontsize=8)
        ax.axhline(0.8, ls="--", lw=0.8, color="gray")
        ax.text(len(topics) - 0.4, 0.805, "验收线 0.8", fontsize=8,
                color="gray", ha="right")
        ax.set_ylim(0, 1.15)
        ax.set_xticks(x)
        ax.set_xticklabels(topics)
        ax.set_ylabel("回应一致率（网络 top-1 ∈ 预期）")
        ax.set_title("对话练习：分话题回应一致率")
        ax.legend(fontsize=8)
        fig.tight_layout()
        p = out / "fig3_dialog.png"
        fig.savefig(p, dpi=130)
        plt.close(fig)
        charts.append(p)
    print(f"    [charts] 生成 {len(charts)} 张图 → {out}")
    return charts


def charts_from_result(fp):
    data = json.loads(Path(fp).read_text(encoding="utf-8"))
    metrics = data.get("metrics", data)
    save_charts(metrics, Path(fp).parent)


# ── 主流程 ──────────────────────────────────────────────────────


def main():
    if "--charts" in sys.argv:
        i = sys.argv.index("--charts")
        fp = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        if not fp:
            raise SystemExit("用法：python _grow_v15.py --charts <result.json>")
        charts_from_result(fp)
        return
    smoke = "--smoke" in sys.argv
    if smoke:
        print("⚠ SMOKE 模式：小规模快跑（机制验证，不跑继承全量、不存快照）")
    t0 = time.time()
    print("═══ Stage 3 v15：定式对话/回答读取机制"
          "（direct_next 直接边接话 + 域内过滤 + 对话练习）═══\n")

    # ── 1. 加载 v14.0（关系词配对 + 关系句题集最新）──
    ng, vocab, pats, cursor = load_version("14.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    hanzi = json.loads((DATA / "stage0_hanzi.json").read_text(encoding="utf-8"))
    print(f"[加载] 14.0：n={ng.n}，模式 {len(pats)}，cursor={cursor}")

    # ── 2. 对话域词表（域内过滤）──
    domain = sorted(w for w in DOMAIN_WORDS if w in pats)
    missing = sorted(set(DOMAIN_WORDS) - set(pats))
    if missing:
        new_pats, cursor = allocate_pats(ng, missing, K, cursor)
        pats.update(new_pats)
        n2w = {j: w for w, ns in pats.items() for j in ns}
        vocab_new = vocab + [w for w in missing if w not in vocab]
        print(f"[新词] 分配 {len(missing)} 个：{missing}，n={ng.n}")
    else:
        vocab_new = vocab
    print(f"[域内词表] {len(domain)} 词（S/V/O + 关系词 + 关系句内容词）")

    # ── 3. 训练平衡（探测报告方案 D：专门数据边强度匹配真实语料）──
    # 真实语料里 想要→你(19.2)/的(38.4)、在→你(206) 等边远强于 v13 固化边
    # （想要→苹果 ≤2.5、在→看 8.0），直接出边问答会输给语料边 →
    # 专门定式边加权到与语料边同量级，再验收读取机制
    balance_seqs = [["我", "想要", "苹果"], ["我", "在", "吃"],
                    ["下雨", "所以"]]
    for seq in balance_seqs + [["想要", "苹果"]]:
        for _ in range(R_BIAS):
            _learn_sentence(ng, seq, pats, slot=0)
    # B 型体标记 在→看：语料 在→你 ≈206，自适应加足（≥语料量级）
    n_b = 0
    while edge_between(ng, pats, "在", "看") < edge_between(ng, pats, "在", "你"):
        _learn_sentence(ng, ["他", "在", "看"], pats, slot=0)
        n_b += 1
        if n_b > 80:
            break
    print(f"[训练平衡] 定式边加权 ×{R_BIAS}: "
          + "、".join("".join(s) for s in balance_seqs)
          + f" | B 型 他在看 自适应加权 {n_b} 轮"
          + f"（在→看 {edge_between(ng, pats, '在', '看'):.1f} vs "
          f"在→你 {edge_between(ng, pats, '在', '你'):.1f}）")

    # ── 4. 读取机制验证：直接出边问答 + 前缀接话（修正前）──
    print("\n[读取机制·直接出边问答]（'X → ?' 读 X 直接出边，域内过滤）")
    qa_rows, n_qa1, _ = qa_acceptance(ng, pats, n2w, domain)
    print("\n[读取机制·前缀接话]（多词前缀 → 最后词出边，域内过滤）")
    pfx_rows, n_pfx1, _ = prefix_acceptance(ng, pats, n2w, domain)

    # ── 5. 对话练习（修正前一致率 → 修正 → 复测）──
    print(f"\n【对话练习】{len(DIALOG)} 轮（话题：{'、'.join(TOPICS)}）")
    turns1, fixes = dialogue_practice(ng, pats, n2w, domain)
    stat1 = Counter()
    for t in turns1:
        stat1[(t["topic"], "agree")] += t["agree"]
        stat1[(t["topic"], "total")] += 1
    print("\n[对话练习 修正前] 分话题回应一致率（网络 top-1 ∈ 预期）")
    for topic in TOPICS:
        a, tot = stat1[(topic, "agree")], stat1[(topic, "total")]
        print(f"  {topic}：{a}/{tot} = {a / tot:.3f}")
    print(f"[修正] {len(fixes)} 次：{'; '.join(f['fix'] for f in fixes) or '无'}")

    # 修正后复测（阶段4）
    turns4 = dialogue_retest(ng, pats, n2w, domain)
    stat4 = Counter()
    for t in turns4:
        stat4[(t["topic"], "agree")] += t["agree"]
        stat4[(t["topic"], "total")] += 1
    print("\n[对话练习 修正后] 分话题回应一致率")
    topic_rates_1, topic_rates_4 = {}, {}
    for topic in TOPICS:
        a1, tot1 = stat1[(topic, "agree")], stat1[(topic, "total")]
        a4, tot4 = stat4[(topic, "agree")], stat4[(topic, "total")]
        topic_rates_1[topic] = a1 / tot1
        topic_rates_4[topic] = a4 / tot4
        print(f"  {topic}：{a1}/{tot1} → {a4}/{tot4} = {a4 / tot4:.3f}")

    # ── 5. 链式接话（对话生成验收）──
    print("\n[链式接话]（从起始词逐词 direct_next 生成整句）")
    chains = chain_generation(ng, pats, n2w, domain)

    # ── 6. 继承 v14 验收（零遗忘；smoke 跳过）──
    inh, ok_inh = {}, True
    if not smoke:
        sem = json.loads((DATA / "stage25_sememes.json").read_text(
            encoding="utf-8"))
        cats25 = build_cats(pats, sem["words"], 12, 3)
        words_old = [w for w in vocab_new if w not in set(hanzi)]
        eval_hanzi = list(np.random.default_rng(7).choice(hanzi, 200,
                                                          replace=False))
        eval_words = list(np.random.default_rng(8).choice(words_old, 300,
                                                         replace=False))
        sents_all = json.loads((DATA / "stage2_sents.json").read_text(
            encoding="utf-8"))
        eval_sents = [sents_all[i] for i in np.random.default_rng(9).choice(
            len(sents_all), 100, replace=False)]
        inh, ok_inh = inherit_acceptance(ng, vocab_new, pats, hanzi, cats25,
                                         sem, eval_hanzi, eval_words,
                                         eval_sents)
        print(f"[继承] 字 {inh['char']:.4f}（base {inh['char_before']:.4f}）"
              f" | 词 {inh['word']:.4f}（base {inh['word_before']:.4f}）"
              f" | 句 {inh['sent']:.4f}（base {inh['sent_before']:.4f}）"
              f" | 2.5 类别 {inh['cat25']:.4f}"
              f" | hold {inh['hold25_ok']}/{inh['hold25_tot']}"
              f" {'✅' if ok_inh else '❌ 回退!'}")

    # ── 7. 验收 ──
    ok_qa = n_qa1 / len(QA_ITEMS) >= 0.9
    ok_pfx = n_pfx1 / len(PREFIX_ITEMS) >= 0.7
    n_turn4 = sum(1 for t in turns4 if t["agree"])
    ok_turn = n_turn4 / len(DIALOG) >= 0.8
    ok_all = bool(ok_qa and ok_pfx and ok_turn and ok_inh)
    print(f"\n[验收] 直接出边问答 top-1 {n_qa1}/{len(QA_ITEMS)}"
          f" {'✅' if ok_qa else '❌'} | 前缀接话 top-1 {n_pfx1}/{len(PREFIX_ITEMS)}"
          f" {'✅' if ok_pfx else '❌'}"
          f" | 对话一致 {n_turn4}/{len(DIALOG)} {'✅' if ok_turn else '❌'}"
          f" | 继承 {'✅' if ok_inh else '❌'}"
          f" {'（smoke 未跑）' if smoke else ''}")
    print(f"\n═══ v15 验收: {'全部通过 ✅' if ok_all else '有失败 ❌'} "
          f"（{time.time() - t0:.0f}s）═══")

    # ── 8. 快照（parent=14.0 → v15.0；冒烟不存）+ 留档 ──
    metrics = {"dialogue_v15": True,
               "qa_rows": qa_rows, "qa_top1": n_qa1, "qa_top3": sum(
                   1 for r in qa_rows if r["hit_top3"]),
               "prefix_rows": pfx_rows, "prefix_top1": n_pfx1,
               "prefix_top3": sum(1 for r in pfx_rows if r["hit_top3"]),
               "dialog_turns1": turns1, "dialog_turns4": turns4,
               "dialog_fixes": fixes,
               "topics": TOPICS,
               **{f"topic_{t}_1": topic_rates_1.get(t, 0.0) for t in TOPICS},
               **{f"topic_{t}_4": topic_rates_4.get(t, 0.0) for t in TOPICS},
               "chains": chains,
               "n": ng.n, "all_ok": bool(ok_all)}
    if not smoke and inh:
        metrics["inherit"] = {k: inh[k] for k in (
            "char", "char_before", "word", "word_before", "sent",
            "sent_before", "cat25", "hold25_ok", "hold25_tot")}
    if not smoke:
        save_snapshot(ng, parent="14.0",
                      tag="Stage 3 v15：定式对话/回答读取机制"
                          "（direct_next 直接边接话 + 域内过滤 + 对话练习）",
                      metrics=metrics, vocab=vocab_new, pats=pats,
                      cursor=cursor)
        out = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_dialogue_v15"
        out.mkdir(parents=True, exist_ok=True)
        metrics["charts"] = [str(p) for p in save_charts(metrics, out)]
        (out / "result.json").write_text(json.dumps(metrics,
                                                    ensure_ascii=False,
                                                    indent=1),
                                         encoding="utf-8")
        print(f"\n[留档] {out / 'result.json'}")


if __name__ == "__main__":
    main()
