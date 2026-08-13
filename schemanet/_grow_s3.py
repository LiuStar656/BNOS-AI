# -*- coding: utf-8 -*-
"""Stage 3 复杂句级（关系）：因果/转折/顺序关系词配对 + 关系句题集。

背景（2026-08-10 用户）：
  - 数字章节挪到推理单元后，Stage 3 = 复杂句级（关系）开发
  - 题集模式（v13 四阶段复刻）+ 小规模（3 组关系词 × 4-6 内容变体，题集 15 道）
  - 拓展档含语义因果题（LLM 裁决——内容合理性代码规则完全无力，价值放大点）

设计（题集模式，判定全代码化 + 语义因果 LLM 裁决）：
  - 数据专门化（铁律 1）：旧 stage3_sents.json 是真实语料（15000 句），
    本阶段**新构造专门关系句**（3 组关系词 × 11 条合理训练句），落档 stage3_rel.json
  - 训练：关系词对跟读建直连（因为→所以 / 虽然→但是 / 先→然后，R 轮）
    + 11 条关系句 _learn_sentence（整句定式，学相邻 bigram 转移）
    + 错配负例拒绝（防御性删边：因为→但是 等不在白名单的对不建边）
  - 网络自判 relation_self_judge：关系词对直连 + 前后内容链（结构检查，纯代码）
  - 教师判定 relation_teacher：白名单配对（代码规则，不用 LLM）；
    语义因果题（judge=llm）→ LLM 裁决合理性（合理=可造 / 不合理=不可造），
    无 key / 失败 → 回退人工语义标注（GT，模板占位标注）
  - 修正：v13 四原则（一致不动 / 误放行删边 / 误拒绝固化 / 保守诚实不动）；
    语义题不一致 = 结构合法但语义被否定 → 保守诚实不动 + LLM 讲评
  - LLM 讲评：只对答错/答不出（自判 ≠ 教师）生成「正确答案 + 解析」

验收：
  - 阶段1 修正前 / 阶段4 修正后 分档一致率 + 错误收敛（错题复测）
  - 关系词对直连专项（因为→所以 等 6 边 > 0.1）+ 错配拒绝
  - 继承 v13 全验收（字/词/句 + 2.5 类别 + hold-out 零遗忘）
  - save_snapshot(parent="13.0") → v14.0；练习数据独立留档

诚实边界：
  - 网络只判结构（配对直连 + 内容链记忆），内容语义合理性由 LLM/人工标注给出
  - 语义因果题的不一致 = 网络盲区（结构合法 ≠ 语义合理），如实报告不掩盖
  - 无 key 时语义题用人工标注 GT（可复现基准），LLM 裁决仅作能力对照

用法：python _grow_s3.py [--smoke]
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
from _grow_v11 import edge_between, penalize_edge, _load_key, _llm_chat
from _grow_v12 import inherit_acceptance

DATA = Path(__file__).parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).parent / "runs"
SEED = 42
K = 4                  # 神经元/词（与 v11 同源分配制）
R_REL = 3              # 关系词对跟读轮数
R_S = 3                # 关系句跟读轮数
REL_TH = 0.1           # 有边阈值（跟读后边权远大于此，防御性判断）

# ── 关系词对（白名单；前词 → 后词 直连 = 关系定式）──────────────
REL_WORDS = ["因为", "所以", "虽然", "但是", "先", "然后"]
REL_PAIRS = {("因为", "所以"), ("虽然", "但是"), ("先", "然后")}

# ── 训练关系句（数据专门化：新构造专门关系句，非真实语料）──────
# 结构统一 [关系词1, X, 关系词2, Y]（4 词）
TRAIN_SENTS = [
    # 因果组（因为…所以…）
    ["因为", "下雨", "所以", "带伞"],
    ["因为", "饿", "所以", "吃饭"],
    ["因为", "生病", "所以", "看医生"],
    ["因为", "困", "所以", "睡觉"],
    ["因为", "冷", "所以", "穿衣服"],
    # 转折组（虽然…但是…）
    ["虽然", "下雨", "但是", "跑步"],
    ["虽然", "累", "但是", "坚持"],
    ["虽然", "困", "但是", "上课"],
    # 顺序组（先…然后…）
    ["先", "吃饭", "然后", "写作业"],
    ["先", "洗手", "然后", "吃饭"],
    ["先", "刷牙", "然后", "睡觉"],
]

# ── 题集（15 道 = 基础 5 + 巩固 4 + 拓展 6；人工语义标注 GT）────
# (tokens, 档位, judge, 教师 GT, GT 依据)
#   judge="rule" → 白名单配对代码判定（不用 LLM）
#   judge="llm"  → 语义因果题：配对合法但内容合理性代码盲区 → LLM 裁决（无 key 回退 GT）
ITEMS = [
    # 基础档（训练句复测，期望网络全对）
    (["因为", "下雨", "所以", "带伞"], "基础", "rule", "可造", "下雨→带伞（训练句复测）"),
    (["因为", "饿", "所以", "吃饭"], "基础", "rule", "可造", "饿→吃饭（训练句复测）"),
    (["虽然", "下雨", "但是", "跑步"], "基础", "rule", "可造", "下雨→跑步（训练句复测）"),
    (["先", "吃饭", "然后", "写作业"], "基础", "rule", "可造", "吃饭→写作业（训练句复测）"),
    (["因为", "生病", "所以", "看医生"], "基础", "rule", "可造", "生病→看医生（训练句复测）"),
    # 巩固档（新内容组合新对：bigram 链全部训练过 → 网络可判）
    (["因为", "生病", "所以", "睡觉"], "巩固", "rule", "可造", "生病→睡觉（新组合）"),
    (["虽然", "下雨", "但是", "坚持"], "巩固", "rule", "可造", "下雨→坚持（新组合）"),
    (["虽然", "累", "但是", "上课"], "巩固", "rule", "可造", "累→上课（新组合）"),
    (["先", "洗手", "然后", "睡觉"], "巩固", "rule", "可造", "洗手→睡觉（新组合）"),
    # 拓展档：错配（配对不在白名单，代码判不可造）
    (["因为", "下雨", "但是", "带伞"], "拓展", "rule", "不可造", "错配（因为+但是）"),
    (["虽然", "下雨", "所以", "跑步"], "拓展", "rule", "不可造", "错配（虽然+所以）"),
    (["先", "吃饭", "所以", "写作业"], "拓展", "rule", "不可造", "错配（先+所以）"),
    # 拓展档：语义因果（配对合法，内容合理性代码盲区 → LLM 裁决）
    (["先", "吃饭", "然后", "睡觉"], "拓展", "llm", "可造", "语义因果（顺序合理：先吃饭后睡觉）"),
    (["因为", "下雨", "所以", "吃饭"], "拓展", "llm", "不可造", "语义因果（下雨与吃饭无因果）"),
    (["因为", "饿", "所以", "看医生"], "拓展", "llm", "不可造", "语义因果（饿与看医生无因果）"),
]


# ── 网络自判（结构检查：关系词对直连 + 前后内容链，纯代码）──────


def relation_self_judge(ng, pats, n2w, tokens):
    """网络自判关系句 [关系词1, X, 关系词2, Y] → (可造/不可造/不知道, 置信, 依据)。

    ① 配对直连：关系词1→关系词2 边（跟读建立的关系定式）
    ② 内容链：关系词1→X、X→关系词2、关系词2→Y（整句记忆的 bigram 转移）
    全通 → 可造（高）；配对通但内容链缺 → 不知道（诚实：内容合理性无证据）；
    配对直连无 → 不可造（错配结构，网络凭定式拒绝）。
    """
    w1, x, w2, y = tokens
    p1 = edge_between(ng, pats, w1, w2) > REL_TH     # 配对直连
    p2 = edge_between(ng, pats, w1, x) > REL_TH      # 前内容链
    p3 = edge_between(ng, pats, x, w2) > REL_TH
    p4 = edge_between(ng, pats, w2, y) > REL_TH      # 后内容链
    if p1 and p2 and p3 and p4:
        return "可造", "高", f"{w1}→{x}→{w2}→{y} 全链通（配对 {w1}→{w2} 直连有）"
    if p1:
        missing = "、".join(e for e, ok in [
            (f"{w1}→{x}", p2), (f"{x}→{w2}", p3), (f"{w2}→{y}", p4)] if not ok)
        return "不知道", "中", f"配对 {w1}→{w2} 直连有，内容链缺 {missing}"
    return "不可造", "中", f"配对 {w1}→{w2} 无直连（未学过该关系词对）"


# ── 教师判定（白名单代码规则；语义因果 = LLM 裁决，无 key 回退 GT）


def llm_semantic_judge(tokens):
    """LLM 裁决关系句内容合理性 → '合理'/'不合理'，失败 → None。"""
    sent = "".join(tokens)
    q = (f"你是中文教师。判断关系句「{sent}」的因果/转折/顺序关系是否合理自然："
         f"如'因为下雨所以带伞'合理、'因为带伞所以下雨'不合理（因果倒置）。"
         f"只输出一个字符：合理输出'对'，不合理输出'错'。")
    txt = _llm_chat([{"role": "user", "content": q}])
    if not txt or not txt.strip():
        return None
    return "合理" if txt.strip()[0] == "对" else "不合理"


def relation_teacher(tokens, judge, gt, gt_basis, has_llm, llm_res=None):
    """教师判定 → (verdict, basis)。判定依据 = 代码规则 / LLM 语义裁决。"""
    w1, x, w2, y = tokens
    if judge == "llm":
        if llm_res is not None:
            return ("可造" if llm_res == "合理" else "不可造"), f"LLM 语义裁决：{llm_res}"
        if has_llm:
            return gt, f"[模板占位] LLM 裁决失败回退人工标注：{gt_basis}"
        return gt, f"[模板占位] 语义因果未启用 LLM，用人工标注：{gt_basis}"
    if (w1, w2) in REL_PAIRS:
        return "可造", f"配对 ({w1},{w2}) 在白名单"
    return "不可造", f"配对 ({w1},{w2}) 错配（不在白名单）"


# ── LLM 讲评（只对答错/答不出：正确答案 + 解析）─────────────────
# 判定 = 代码规则；LLM 只负责"告诉正确答案和解析"（2026-08-10 用户定）


def llm_explain(tokens, vd, tv, has_llm):
    """LLM 生成「正确答案 + 解析」两行。无 key / 失败 → 模板占位。"""
    sent = "".join(tokens)
    ans_txt = f"能说「{sent}」" if tv == "可造" else f"不能说「{sent}」"
    if not has_llm:
        return (f"[模板占位] 正确答案：{ans_txt}。\n"
                f"[模板占位] 解析：教师规则判定（白名单配对 / 语义因果人工标注），非 LLM。")
    q = (f"你是中文教师。判断题：能否说「{sent}」？学生自判为「{vd}」，"
         f"正确答案是「{'能说' if tv == '可造' else '不能说'}」。"
         f"请只输出两行：第一行「正确答案：{ans_txt}。」；第二行「解析："
         f"不超过 40 字的语法/语义解释（如：'因为…所以…'表因果关系，"
         f"'虽然…但是…'表转折，'先…然后…'表先后顺序；前后内容要有合理联系）。」")
    txt = _llm_chat([{"role": "user", "content": q}])
    if txt is None:
        return f"[模板占位] 正确答案：{ans_txt}。\n[模板占位] 解析：LLM 调用失败回退。"
    return txt.strip()[:160]


# ── 修正（v13 四原则；语义题 = 保守诚实不动）────────────────────


def relation_apply_fix(ng, pats, n2w, tokens, vd, tv):
    """按不一致类型修正。返回修正描述（None = 无动作）。

    语义题（配对合法但内容被教师否定）= 保守诚实：不动网络——
    结构合法 ≠ 语义合理，网络无语义知识，删边会破坏合法结构。
    """
    w1, x, w2, y = tokens
    if vd == tv:
        return None
    if vd == "可造" and tv == "不可造":
        if (w1, w2) in REL_PAIRS:
            return None                       # 保守诚实（语义盲区，待 LLM 讲评）
        penalize_edge(ng, pats, w1, w2)
        return f"误放行 → 删除错配对 {w1}→{w2} 边（连接级处罚）"
    if tv == "可造":
        _learn_sentence(ng, tokens, pats, slot=0)
        return f"误拒绝 → 固化关系句（学 {'、'.join(tokens)} 1 次）"
    return None                               # 保守诚实：不建立错误边


# ── 练习主循环（四阶段，同 v13 口径）────────────────────────────


def relation_homework(ng, pats, n2w, items, has_llm):
    """阶段1 全题自判+批改 → 阶段2 统一修正 → 阶段3 错题复测 → 阶段4 全题复测。"""
    stat1 = Counter()
    detail = []
    for tokens, level, judge, gt, gt_basis in items:
        vd, conf, path = relation_self_judge(ng, pats, n2w, tokens)
        llm_res = llm_semantic_judge(tokens) if (judge == "llm" and has_llm) else None
        tv, basis = relation_teacher(tokens, judge, gt, gt_basis, has_llm, llm_res)
        agree = (vd == tv)
        stat1[(level, "agree")] += agree
        stat1[(level, "total")] += 1
        detail.append({"sent": "".join(tokens), "tokens": tokens, "level": level,
                       "judge": judge, "self": vd, "conf": conf, "path": path,
                       "teacher": tv, "teacher_basis": basis,
                       "gt": gt, "gt_basis": gt_basis,
                       "llm_verdict": llm_res, "agree": agree})
    # 阶段2：LLM 讲评（答错/答不出 → 正确答案+解析）+ 统一修正
    for d in detail:
        if not d["agree"]:
            d["explain"] = llm_explain(d["tokens"], d["self"], d["teacher"], has_llm)
    fixes = []
    for d in detail:
        fix = relation_apply_fix(ng, pats, n2w, d["tokens"], d["self"], d["teacher"])
        if fix:
            d["fix"] = fix
            fixes.append(d)
    # 阶段3：错题复测（收敛）
    n_fix_ok = 0
    for f in fixes:
        vd, conf, path = relation_self_judge(ng, pats, n2w, f["tokens"])
        ok = (vd == f["teacher"])
        n_fix_ok += ok
        f["retest"] = vd
        f["fixed"] = ok
        print(f"  错题复测「{f['sent']}」({f['level']}档)："
              f"修正前自判 {f['self']}({f['conf']}) vs 教师 {f['teacher']}"
              f" → 修正后自判 {vd} {'✓ 收敛' if ok else '✗ 未收敛'}")
    # 阶段3b：保守诚实的不一致题（不动网络，LLM 讲评）
    for d in detail:
        if not d["agree"] and "fix" not in d:
            if d["judge"] == "llm":
                print(f"  语义盲区「{d['sent']}」({d['level']}档)："
                      f"自判 {d['self']} vs 教师 {d['teacher']}"
                      f" → 不修正（结构合法 ≠ 语义合理，网络无语义知识，"
                      f"诚实留白，LLM 讲评）")
            else:
                print(f"  保守诚实「{d['sent']}」({d['level']}档)："
                      f"自判 {d['self']} vs 教师 {d['teacher']}"
                      f" → 不修正（无结构证据，诚实留白）")
        if d.get("explain"):
            print(f"    LLM 讲评：{d['explain'].replace(chr(10), ' ')}")
    # 阶段4：全题复测（教师判定复用阶段1 缓存，验收口径 = 修正后网络）
    stat4 = Counter()
    for d in detail:
        vd, _, _ = relation_self_judge(ng, pats, n2w, d["tokens"])
        agree4 = (vd == d["teacher"])
        stat4[(d["level"], "agree")] += agree4
        stat4[(d["level"], "total")] += 1
        d["agree4"] = agree4
        d["self4"] = vd
    return stat1, fixes, stat4, detail


def grade_report(stat, fixes, stage="阶段1（修正前）"):
    print(f"\n【关系句题集 {stage}】分档一致率（网络自判 vs 教师判定）")
    rates = {}
    for level in ["基础", "巩固", "拓展"]:
        a, t = stat[(level, "agree")], stat[(level, "total")]
        rate = a / t if t else 1.0
        rates[level] = rate
        tag = ("≈1.0 ✅" if level == "基础" and rate >= 0.9 else
               "≥0.9 ✅" if level == "巩固" and rate >= 0.9 else
               "泛化边界（含语义 LLM 裁决盲区）" if level == "拓展" else "")
        print(f"  {level}档：{a}/{t} = {rate:.3f} {tag}")
    if stage.startswith("阶段1"):
        print(f"  修正：{len(fixes)} 次（误放行删边 / 误拒绝固化解；语义盲区不动）")
    return rates


# ── 图表化（用户约定 2026-08-10：实验数据必须用图表呈现，提升可读性）


def _plt():
    """初始化 matplotlib（无则返回 None，跳过出图；中文字体 Windows 优先）。"""
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

    ① 分档一致率（阶段1 vs 阶段4）柱状对比
    ② 关系定式边权（关系词对直连，含阈值线）
    ③ 语义因果题：LLM 裁决 vs 人工标注 GT 对比
    """
    plt = _plt()
    if plt is None:
        return []
    charts = []
    out = Path(out_dir) / "charts"
    out.mkdir(parents=True, exist_ok=True)

    # ① 分档一致率（阶段1 修正前 vs 阶段4 修正后）
    levels = ["基础", "巩固", "拓展"]
    s1 = [metrics.get(f"{k}_agree_1", 0.0) for k in ("base", "firm", "extend")]
    s4 = [metrics.get(f"{k}_agree_4", 0.0) for k in ("base", "firm", "extend")]
    fig, ax = plt.subplots(figsize=(6, 3.6))
    x = np.arange(len(levels))
    w = 0.35
    b1 = ax.bar(x - w / 2, s1, w, label="阶段1（修正前）", color="#9db8d2")
    b4 = ax.bar(x + w / 2, s4, w, label="阶段4（修正后）", color="#4c78a8")
    for b in list(b1) + list(b4):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.02,
                f"{b.get_height():.2f}", ha="center", fontsize=8)
    ax.axhline(0.9, ls="--", lw=0.8, color="gray")
    ax.text(2.35, 0.905, "验收线 0.9", fontsize=8, color="gray", ha="right")
    ax.set_ylim(0, 1.15)
    ax.set_xticks(x)
    ax.set_xticklabels(levels)
    ax.set_ylabel("一致率（网络自判 vs 教师）")
    ax.set_title("Stage 3 关系句题集：分档一致率")
    ax.legend(fontsize=8)
    fig.tight_layout()
    p = out / "fig1_agree.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    charts.append(p)

    # ② 关系定式边权（关系词对直连）
    rel = metrics.get("rel_edges", {})
    if rel:
        fig, ax = plt.subplots(figsize=(6, 3.2))
        names, vals = list(rel), list(rel.values())
        ax.bar(names, vals, color="#82b366")
        for i, v in enumerate(vals):
            ax.text(i, v + 0.5, f"{v:.1f}", ha="center", fontsize=8)
        ax.axhline(0.1, ls="--", lw=0.8, color="red")
        ax.text(len(names) - 0.4, 0.35, "有边阈值 0.1", fontsize=8,
                color="red", ha="right")
        ax.set_ylabel("关系词对直连边权")
        ax.set_title("关系定式：关系词对直连（跟读 ×3）")
        fig.tight_layout()
        p = out / "fig2_rel_edges.png"
        fig.savefig(p, dpi=130)
        plt.close(fig)
        charts.append(p)

    # ③ 语义因果题：LLM 裁决 vs 人工标注 GT
    sem = metrics.get("llm_semantic", {})
    gt, vd = sem.get("gt", []), sem.get("verdicts", [])
    if gt:
        n = len(gt)
        fig, ax = plt.subplots(figsize=(6, 2.8))
        y = np.arange(n)
        ax.scatter([1] * n, y, marker="o", s=130, color="#4c78a8",
                   label="人工标注 GT")
        ax.scatter([2] * n, y, marker="^", s=130,
                   color=["#4c78a8" if (a == "合理") == (b == "可造") else "#e45756"
                          for a, b in zip(vd or [None] * n, gt)],
                   label="LLM 裁决")
        ax.set_yticks(y)
        ax.set_yticklabels([f"语义题 {i + 1}" for i in range(n)])
        ax.set_xlim(0.5, 2.5)
        ax.set_xticks([1, 2])
        ax.set_xticklabels(["GT", "LLM"])
        n_ok = len([v for v in (vd or []) if v is not None])
        ax.set_title(f"语义因果题：LLM 裁决 vs 人工标注"
                     f"（一致 {sem.get('match', '-')}/{n_ok}）")
        ax.legend(fontsize=8, loc="lower right")
        fig.tight_layout()
        p = out / "fig3_semantic.png"
        fig.savefig(p, dpi=130)
        plt.close(fig)
        charts.append(p)
    print(f"    [charts] 生成 {len(charts)} 张图 → {out}")
    return charts


def charts_from_result(fp):
    """历史数据出图：python _grow_s3.py --charts <result.json>。
    兼容 _speak_logs（metrics 本体）与快照 result.json（metrics 子字段）。"""
    data = json.loads(Path(fp).read_text(encoding="utf-8"))
    metrics = data.get("metrics", data)
    save_charts(metrics, Path(fp).parent)


def main():
    if "--charts" in sys.argv:                    # 历史数据出图模式
        i = sys.argv.index("--charts")
        fp = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        if not fp:
            raise SystemExit("用法：python _grow_s3.py --charts <result.json>")
        charts_from_result(fp)
        return
    smoke = "--smoke" in sys.argv
    if smoke:
        print("⚠ SMOKE 模式：小规模快跑（机制验证，不存快照、不跑继承全量）")
    has_llm = bool(_load_key())
    t0 = time.time()
    print("═══ Stage 3 复杂句级（关系）：关系词配对 + 关系句题集 ═══\n")
    print(f"[判定] 教师 = 白名单配对代码规则（语义因果题 = LLM 裁决）"
          f"| 网络自判 = 配对直连 + 内容链结构检查"
          f"\n[LLM] {'DEEPSEEK_API_KEY 已配置 → 语义因果 LLM 裁决 + LLM 讲评'
                if has_llm else '无 API key → 语义因果回退人工标注（模板占位）'}")

    # ── 1. 加载 v13.0（复杂句式练习最新）──
    ng, vocab, pats, cursor = load_version("13.0")
    hanzi = json.loads((DATA / "stage0_hanzi.json").read_text(encoding="utf-8"))
    print(f"[加载] 13.0：n={ng.n}，模式 {len(pats)}，cursor={cursor}")

    # ── 2. 集合构造（继承验收用：2.5 类别体系）──
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats25 = build_cats(pats, sem["words"], 12, 3)

    # ── 3. 新词分配（关系词 + 内容词；数据专门化：仅 Stage 3 关系句词表）──
    rel_words = sorted({w for s in TRAIN_SENTS for w in s})
    item_words = sorted({w for tks, *_ in ITEMS for w in tks})
    new_words = sorted(set(rel_words) | set(item_words))
    new_pats, cursor = allocate_pats(ng, new_words, K, cursor)
    pats.update(new_pats)
    n2w = {j: w for w, ns in pats.items() for j in ns}
    vocab_new = vocab + [w for w in new_words if w not in vocab]
    print(f"[新词] 分配 {len(new_words)} 个（关系词 6 + 内容词 {len(new_words) - 6}），"
          f"n={ng.n}，cursor={cursor}")

    # ── 4. 训练：关系词对跟读 → 错配负例拒绝 → 关系句跟读 ──
    for w1, w2 in sorted(REL_PAIRS):
        for _ in range(R_REL):
            _learn_sentence(ng, [w1, w2], pats, slot=0)
    n_reject = 0
    for a in ["因为", "虽然", "先"]:
        for b in ["所以", "但是", "然后"]:
            if (a, b) not in REL_PAIRS:
                penalize_edge(ng, pats, a, b)     # 防御性：错配对不建边
                n_reject += 1
    for s in TRAIN_SENTS:
        for _ in range(R_S):
            _learn_sentence(ng, s, pats, slot=0)
    rel_edges = {f"{w1}→{w2}": round(edge_between(ng, pats, w1, w2), 3)
                 for w1, w2 in sorted(REL_PAIRS)}
    ok_rel = all(v > REL_TH for v in rel_edges.values())
    print(f"[训练] 关系词对跟读 ×{R_REL} | 错配负例拒绝 {n_reject} 对 | "
          f"关系句跟读 ×{R_S}（{len(TRAIN_SENTS)} 句）")
    print(f"[关系定式] {rel_edges} {'✅ 全部建边' if ok_rel else '❌ 有缺'}")

    # ── 5. 题集（阶段1 → 修正 → 复测 → 阶段4）──
    print(f"\n【关系句题集】题集 {len(ITEMS)} 道（基础 5 + 巩固 4 + 拓展 6，含错配 3 + 语义因果 3）")
    stat1, fixes, stat4, detail = relation_homework(ng, pats, n2w, ITEMS, has_llm)
    rates1 = grade_report(stat1, fixes, stage="阶段1（修正前）")
    rates4 = grade_report(stat4, fixes, stage="阶段4（修正后复测）")
    r_fix = (sum(1 for f in fixes if f["fixed"]) / len(fixes)
             if fixes else 1.0)
    print(f"[错误收敛] 错题复测 {sum(1 for f in fixes if f['fixed'])}/{len(fixes)}"
          f" = {r_fix:.3f} {'✅' if r_fix >= 0.8 or not fixes else '❌'}")

    # 语义因果题专项：LLM 裁决 vs 人工标注 GT（合理=可造，单位对齐）
    llm_sel = [d for d in detail if d["judge"] == "llm"]
    n_llm = sum(1 for d in llm_sel if d.get("llm_verdict") is not None)
    n_match = sum(1 for d in llm_sel
                  if d.get("llm_verdict") is not None
                  and (d["llm_verdict"] == "合理") == (d["gt"] == "可造"))
    print(f"[语义因果] {len(llm_sel)} 道：LLM 裁决 {n_llm} 道，"
          f"与人工标注一致 {n_match}/{n_llm}"
          f"（{'已启用 LLM' if has_llm else '未启用 LLM → 回退人工标注'}）")

    # ── 6. 逐题对照（含 LLM 讲评全文）──
    print("\n[逐题对照]（网络自判 vs 教师判定，阶段4 后）")
    for d in detail:
        m = "✓" if d["agree4"] else "✗"
        print(f"  {m}「{d['sent']}」({d['level']}档) "
              f"自判={d['self4']}({d['path']}) vs 教师={d['teacher']}"
              f"{' | ' + d['fix'] if d.get('fix') else ''}")

    # ── 7. 继承 v13 验收（零遗忘；smoke 跳过）──
    inh, ok_inh = {}, True
    if not smoke:
        words_old = [w for w in vocab if w not in set(hanzi)]
        eval_hanzi = list(np.random.default_rng(7).choice(hanzi, 200, replace=False))
        eval_words = list(np.random.default_rng(8).choice(words_old, 300,
                                                         replace=False))
        sents_all = json.loads((DATA / "stage2_sents.json").read_text(
            encoding="utf-8"))
        eval_sents = [sents_all[i] for i in np.random.default_rng(9).choice(
            len(sents_all), 100, replace=False)]
        from _grow_zh import recall_words
        from _grow_v11 import sent_recall
        inh, ok_inh = inherit_acceptance(
            ng, vocab, pats, hanzi, cats25, sem, eval_hanzi, eval_words,
            eval_sents)
        print(f"[继承] 字 {inh['char']:.4f}（base {inh['char_before']:.4f}）"
              f" | 词 {inh['word']:.4f}（base {inh['word_before']:.4f}）"
              f" | 句 {inh['sent']:.4f}（base {inh['sent_before']:.4f}）"
              f" | 2.5 类别 {inh['cat25']:.4f}"
              f" | hold {inh['hold25_ok']}/{inh['hold25_tot']}"
              f" {'✅' if ok_inh else '❌ 回退!'}")

    # ── 8. 验收 ──
    ok_base = rates4["基础"] >= 0.9
    ok_firm = rates4["巩固"] >= 0.9
    ok_fix = r_fix >= 0.8 or not fixes
    ok_all = bool(ok_base and ok_firm and ok_fix and ok_inh and ok_rel)
    print(f"\n[验收] 基础 {rates4['基础']:.3f} {'✅' if ok_base else '❌'}"
          f" | 巩固 {rates4['巩固']:.3f} {'✅' if ok_firm else '❌'}"
          f" | 拓展 {rates4['拓展']:.3f}（泛化边界，含语义 LLM 裁决盲区）"
          f" | 错误收敛 {r_fix:.3f} {'✅' if ok_fix else '❌'}"
          f" | 关系定式 {'✅' if ok_rel else '❌'}"
          f" | 继承 {'✅' if ok_inh else '❌'}"
          f" {'（smoke 未跑）' if smoke else ''}")
    print(f"\n═══ v14 验收: {'全部通过 ✅' if ok_all else '有失败 ❌'} "
          f"（{time.time() - t0:.0f}s）═══")

    # ── 9. 快照（parent=13.0 → v14.0；冒烟不存）+ 数据留档 ──
    metrics = {"stage3_rel": True,
               "base_agree_1": round(rates1["基础"], 4),
               "firm_agree_1": round(rates1["巩固"], 4),
               "extend_agree_1": round(rates1["拓展"], 4),
               "base_agree_4": round(rates4["基础"], 4),
               "firm_agree_4": round(rates4["巩固"], 4),
               "extend_agree_4": round(rates4["拓展"], 4),
               "fix_actions": len(fixes),
               "fix_reconverge": round(r_fix, 4),
               "rel_edges": rel_edges, "ok_rel": bool(ok_rel),
               "llm_enabled": has_llm,
               "llm_semantic": {"total": len(llm_sel),
                                "verdicts": [d.get("llm_verdict")
                                             for d in llm_sel],
                                "gt": [d["gt"] for d in llm_sel],
                                "match": n_match},
               "items": detail,
               "n": ng.n, "all_ok": bool(ok_all)}
    if not smoke and inh:
        metrics["inherit"] = {k: inh[k] for k in (
            "char", "char_before", "word", "word_before", "sent",
            "sent_before", "cat25", "hold25_ok", "hold25_tot")}
    if not smoke:
        save_snapshot(ng, parent="13.0",
                      tag="Stage 3 复杂句级（关系）：关系词配对 + 关系句题集（代码判定 + LLM 语义裁决讲评）",
                      metrics=metrics, vocab=vocab_new, pats=pats, cursor=cursor)
        # 练习数据独立留档（每次实验必须保存）+ 实验数据图表化
        out = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_s3_rel"
        out.mkdir(parents=True, exist_ok=True)
        metrics["charts"] = [str(p) for p in save_charts(metrics, out)]
        (out / "result.json").write_text(json.dumps(metrics, ensure_ascii=False,
                                                    indent=1), encoding="utf-8")
        # 数据专门化留档：新构造的关系句训练数据（替代旧真实语料用途）
        stage3_data = {"stage": 3, "purpose": "复杂句级（关系）：数据专门化——新构造专门关系句（非真实语料）",
                       "rel_pairs": sorted(REL_PAIRS),
                       "train_sents": TRAIN_SENTS,
                       "items": [{"tokens": t, "level": l, "judge": j,
                                  "gt": g, "gt_basis": b}
                                 for t, l, j, g, b in ITEMS]}
        (DATA / "stage3_rel.json").write_text(
            json.dumps(stage3_data, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"\n[留档] {out / 'result.json'} | {DATA / 'stage3_rel.json'}")


if __name__ == "__main__":
    main()
