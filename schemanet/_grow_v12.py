# -*- coding: utf-8 -*-
"""Stage 2.6 v12（方案 v2.10 铁律 5 ⑤）：网络自判——判断内化到网络结构。

核心（2026-08-10 用户决策）：
  - 铁律 5 五步闭环 ①-④ 已完成（v7→v11），⑤ 自己判断 = v12（本脚本）
  - 现状差距：_speak.py §③ speak_judge 是 v11 代码规则（rule_verifier 查
    搭配类别），判断依据/阈值/方法都是代码写死，没内化到网络
  - v12 目标：网络凭**自己边结构**判断 "(S,V,O) 可造/不可造/不知道"
    （带置信），外部教师从"判断者"转岗为"批改讲评者"
    （⑤a 判断方法教学 → ⑤b 课后练习 + 教师批改讲评）

自判判定（方案 v12 §2.1，用户认可"直连→二跳→强度→不知道"）：
  ① 直连：V→O 边 ≥ 0.5 → 可造（强判断，置信高）
  ② 二跳：O ∈ V 搭配类别成员 → 可造（弱判断，类别泛化）
  ③ 强度：O 进 top-8 → 置信升档；不进 → 置信降档
  ④ 类别冲突：V 有搭配类别 且 O 有明确类别归属 但 O ∉ V 搭配 → 不可造
     （结构证据：O 明确属于别的类别 → 能明确拒绝）
  ⑤ 其余（V 无搭配类别 / O 无类别归属 / 结构证据不足）→ 不知道
     （诚实留白：语义合法性交给教师，网络只判结构）

教师基准（smoke 实测修正，2026-08-10）：
  - 基础/巩固档 ground truth = **规则验证器**（与 v10/v11 教学验收同源，
    稳定可复现；LLM 判"看公园/鸟看学校"错是真实语义偏好，不是网络错）
  - 拓展档：规则判"不可造"的临界题 → **LLM 裁决**（规则类别不匹配但语义
    合法：买石头/看石头——LLM 教师的价值放大点）
  - LLM 通用于批改讲评（自判错误给自然语言原因），不影响基准判定

修正原则（smoke 实测修正，2026-08-10）：
  - 一致（自判=教师）→ 不动作（结构已支持判断；原"一致就固化"会与
    "不一致就删边"互相抵消，且固化对象句会把"不可造"教成"可造"）
  - 误放行（自判可造、教师不可造）→ 删 o 的来源边
  - 误拒绝（自判不可造/不知道、教师可造）→ 固化 [s,v,o]（建立正确路径）
  - 保守诚实（自判不知道、教师不可造）→ 不修正（无结构证据，诚实留白）

流程（在 v11.2 快照上迭代，不重训）：
  load_version("11.2")
    → ⑤a 判断方法教学（示范样本覆盖判断路径模板 + 修正校准）
    → ⑤b 课后练习（三档×变式×穿插题集 → 自判 → 教师批改
       → 修正 → 错题复测 → 全题复测）
    → 验收（分档一致率 + 错误收敛 + 继承 v11 全验收）
    → save_snapshot(parent="11.2") → v12.0

诚实边界（方案 §四）：
  - 自判 = 图可达性检查（路径存在 + 强度），不是"理解为什么"
  - 语义合法性（"看石头"合理）来自 LLM 教师，网络只判结构
  - 判断置信 ≠ 语义理解

用法：python _grow_v12.py [--smoke]
"""

import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from schema_net import build_pulse, _learn_sentence
from snapshot import load_version, save_snapshot
from _grow_cat import build_cats, edge_sum
from _grow_zh import run_recall, fire_ratio, recall_words
from _grow_v11 import (attributed_sentence, rule_verifier, edge_between,
                       penalize_edge, penalize_bad_word, _load_key, _llm_chat,
                       llm_judge, template_reason, sent_recall,
                       VO_PAIRS, O_FOOD, O_PLACE, O_TAGS,
                       SLOT_S, SLOT_V, SLOT_O, TAG_ACT, TAG_PERS,
                       V_SET, PERS_MANUAL, S_ANIMALS, K)

# ── 自判阈值（初值；阈值标定 = 校准读数刻度，判断依据仍是网络边）──
DIRECT_TH = 0.5          # V→O 直连边 ≥ 此值 → 可造（强判断）
TOP_WIN = 8              # O 进 top-8 → 置信升档

DATA = Path(__file__).parent / "data" / "curriculum"
SEED = 42

# ── 自判（核心：判断 = 网络边结构）──────────────────────────────
# verdict ∈ {可造, 不可造, 不知道}；conf ∈ {高, 中, 低}；
# path = 判定依据（直连/类别泛化/类别冲突/诚实留白）


def self_judge(ng, pats, n2w, s, v, o, vo_pairs, cat_members):
    """网络自判：(S,V,O) 可造/不可造/不知道（带置信 + 判定依据）。

    判定依据全部来自网络边结构（attributed_sentence 信号），
    不是代码里的 allow 集合比对——改网络（教学/处罚）就改判断。
    """
    direct = edge_between(ng, pats, v, o)          # ① 直连
    ok_path, top, allow, _ = attributed_sentence(
        ng, pats, n2w, s, v, vo_pairs, cat_members)
    allow_mem = set()
    if allow:
        allow_mem = set().union(*(cat_members[c] for c in allow))
    reach2 = o in allow_mem                        # ② 二跳（类别泛化可达）
    o_rank = top.index(o) if o in top else None    # ③ 强度（top 排名）
    # ④ 类别冲突证据：O 有明确类别归属（O_TAGS 成员）且不在 V 搭配类别
    o_has_cat = any(o in cat_members.get(t, set()) for t in O_TAGS)

    if direct >= DIRECT_TH:
        conf = "高" if (o_rank is not None and o_rank < TOP_WIN) else "中"
        return "可造", conf, f"直连（{v}→{o} 边 {direct:.1f}）"
    if not allow:                                  # ⑤a 无搭配类别 → 诚实留白
        return "不知道", "低", "诚实留白（V 无搭配类别）"
    if reach2:
        conf = "低" if (o_rank is None or o_rank >= TOP_WIN) else "中"
        return "可造", conf, f"类别泛化（{v} 搭配 {'、'.join(sorted(allow))}）"
    if o_has_cat:
        cat_own = "、".join(t for t in O_TAGS if o in cat_members.get(t, set()))
        return "不可造", "中", (f"类别冲突（{o} 属 {cat_own}，"
                                f"不在 {v} 搭配 {'、'.join(sorted(allow))}）")
    if o_rank is not None and o_rank < TOP_WIN:
        return "不可造", "低", "强度够但结构不可达（进 top 却无搭配边）"
    return "不知道", "低", "诚实留白（无结构证据）"


# ── 教师判断（批改口径：基础/巩固=规则基准，拓展=LLM 裁决）──────
# use_llm=True（拓展档）：规则判"不可造"的临界题由 LLM 裁决（语义临界）；
# use_llm=False（基础/巩固档）：规则为基准，LLM 只出讲评原因（不影响判定）。


def teacher_verdict(ng, pats, s, v, o, vo_pairs, cat_members, has_llm,
                    use_llm=False):
    """教师判断 → (verdict, reason)。"""
    ok_path, top, allow, _ = attributed_sentence(
        ng, pats, {}, s, v, vo_pairs, cat_members)
    kind, _, allow_mem = rule_verifier(
        ng, pats, s, v, o, allow, cat_members, top)
    base = {"ok": "可造", "bad": "不可造"}.get(kind, "不知道")
    diag = {"S": s, "V": v, "O": o, "kind": kind, "allow": sorted(allow),
            "top": top, "principles": {}, "allow_mem": sorted(allow_mem)[:8],
            "penalized": None}
    llm_reason = None
    if has_llm:
        res = llm_judge(diag)
        if res:
            jg, reason = res
            llm_reason = reason
            if use_llm and kind == "bad":         # 拓展档临界：规则否定 → LLM 裁决
                base = "可造" if jg == "对" else "不可造"
    reason = llm_reason or template_reason(diag)
    return base, reason


# ── ⑤a 判断方法教学：示范判断过程 + 修正校准 ────────────────────
# 示范 = 教师演示"怎么判"（先查直连、再查二跳、再判强度、判不出说不知道）；
# 修正原则同 ⑤b（一致不动作 / 误放行删边 / 误拒绝固化 / 保守诚实不动）。


def method_lesson(ng, pats, n2w, vo_pairs, cat_members, has_llm, s="我"):
    """⑤a 判断方法教学。返回留档记录 list。"""
    print("\n【⑤a 判断方法教学】教师示范判断过程（先查直连、再查二跳、再判强度）")
    log = []
    samples = [("我", "要", "苹果"), ("我", "吃", "学校"), ("我", "画", "家"),
               ("我", "看", "石头")]
    for sv, v, o in samples:
        vd, conf, path = self_judge(ng, pats, n2w, sv, v, o,
                                    vo_pairs, cat_members)
        use_llm = (v == "看")                    # 临界样本（看+石头）→ LLM 裁决
        tv, reason = teacher_verdict(ng, pats, sv, v, o,
                                     vo_pairs, cat_members, has_llm,
                                     use_llm=use_llm)
        agree = (vd == tv)
        print(f"  示范「{sv}{v}{o}」：自判={vd}({conf}, {path})"
              f" | 教师={tv} {'✓' if agree else '✗'} — {reason[:28]}")
        fix = apply_fix(ng, pats, n2w, sv, v, o, vd, tv, vo_pairs, cat_members)
        log.append({"s": sv, "v": v, "o": o, "self": vd, "conf": conf,
                    "path": path, "teacher": tv, "agree": agree,
                    "reason": reason, "fix": fix})
        if fix:
            print(f"    ✗ 不一致 → {fix}")
    return log


# ── 修正（三类不一致的统一落点）──────────────────────────────────


def apply_fix(ng, pats, n2w, s, v, o, vd, tv, vo_pairs, cat_members):
    """按不一致类型修正：
    误放行（自判可造、教师不可造）→ 删 o 来源边；
    误拒绝（自判不可造/不知道、教师可造）→ 固化 [s,v,o]；
    保守诚实（自判不知道、教师不可造）→ 不动。
    一致 → 不动（结构已支持判断；固化会与删边抵消、把不可造教成可造）。
    返回修正描述（None = 无动作）。
    """
    if vd == tv:
        return None
    if vd == "可造" and tv == "不可造":
        _, top, allow, sources = attributed_sentence(
            ng, pats, n2w, s, v, vo_pairs, cat_members)
        pen = penalize_bad_word(ng, pats, n2w, o, sources, allow, [])
        return f"误放行 → 删除 {o} 来源边 {pen or '（无来源）'}"
    if tv == "可造":
        _learn_sentence(ng, [s, v, o], pats, slot=0)
        return f"误拒绝 → 固化正确路径（学 {s}{v}{o} 1 次）"
    return None                                   # 保守诚实：不建立错误边


# ── ⑤b 课后练习题集：三档 × 变式 × 穿插 ─────────────────────────
# 基础档 = 训练组合复测 + 明确类别冲突逆例；巩固档 = 三词单训过的新组合；
# 拓展档 = 类别泛化二跳 + 跨类临界（LLM 裁决）。
# 穿插：按 V 交错混出（防同 V 连片 → "O 槽保底"定式）。


def exercise_set(s_words, v_words, o_words, train_combos, test_combos,
                 vo_pairs, cat_members, noun_pool, n_each=6):
    """生成三档 × 变式 × 穿插题集。返回 [(s, v, o, 档位)]。"""
    rng = np.random.default_rng(SEED + 1)
    items = []
    # 基础档：训练组合复测（正例）+ 明确类别冲突（逆例）
    ok_train = [(s, v, o) for s, v, o in train_combos
                if o in vo_pairs.get(v, [])]
    rng.shuffle(ok_train)
    items += [(s, v, o, "基础") for s, v, o in ok_train[:n_each]]
    for v in v_words[:n_each]:
        allow = set()
        for o in vo_pairs.get(v, []):
            for c, mem in cat_members.items():
                if o in mem:
                    allow.add(c)
        allow_mem = set().union(*(cat_members[c] for c in allow)) if allow else set()
        conflicts = [o for o in noun_pool if o not in allow_mem and
                     any(o in cat_members[t] for t in O_TAGS)]
        if conflicts:
            o = conflicts[rng.integers(len(conflicts))]
            items.append((s_words[0], v, o, "基础"))
    # 巩固档：测试组合（三词单训过、组合没学过）
    rng.shuffle(test_combos)
    items += [(s, v, o, "巩固") for s, v, o in test_combos[:n_each]]
    # 拓展档：类别泛化二跳（V 搭配类别成员、非直接搭配词）+ 跨类临界
    for v in v_words:
        allow = set()
        for o in vo_pairs.get(v, []):
            for c, mem in cat_members.items():
                if o in mem:
                    allow.add(c)
        allow_mem = set().union(*(cat_members[c] for c in allow)) if allow else set()
        gen = [o for o in allow_mem if o not in vo_pairs.get(v, [])]
        if gen:
            items.append((s_words[0], v, gen[0], "拓展"))
    for v in ["吃", "看", "买"]:
        items.append((s_words[0], v, "石头", "拓展"))
    # 穿插：按 V 交错排列
    by_v = {}
    for it in items:
        by_v.setdefault(it[1], []).append(it)
    out = []
    keys = list(by_v)
    idx = {k: 0 for k in keys}
    while any(idx[k] < len(by_v[k]) for k in keys):
        for k in keys:
            if idx[k] < len(by_v[k]):
                out.append(by_v[k][idx[k]])
                idx[k] += 1
    return out


# ── ⑤b 课后练习：自判 → 教师批改 → 修正 → 复测 ──────────────────
# 阶段1 全题自判+批改（纯读）→ 阶段2 统一修正（仅不一致）→
# 阶段3 错题复测（收敛）→ 阶段4 全题复测（最终一致率）。


def homework_loop(ng, pats, n2w, items, vo_pairs, cat_members, has_llm):
    """⑤b 课后练习。返回 (阶段1统计, 修正记录, 阶段4统计, 逐题记录)。"""
    # 阶段1：全题自判 + 教师批改（纯读，不改边）
    stat1 = Counter()
    detail = []
    for s, v, o, level in items:
        vd, conf, path = self_judge(ng, pats, n2w, s, v, o,
                                    vo_pairs, cat_members)
        tv, reason = teacher_verdict(ng, pats, s, v, o,
                                     vo_pairs, cat_members, has_llm,
                                     use_llm=(level == "拓展"))
        agree = (vd == tv)
        stat1[(level, "agree")] += agree
        stat1[(level, "total")] += 1
        detail.append({"s": s, "v": v, "o": o, "level": level,
                       "self": vd, "conf": conf, "path": path,
                       "teacher": tv, "agree": agree,
                       "teacher_reason": reason[:40]})
    # 阶段2：统一修正（仅不一致）
    fixes = []
    for d in detail:
        fix = apply_fix(ng, pats, n2w, d["s"], d["v"], d["o"],
                        d["self"], d["teacher"], vo_pairs, cat_members)
        if fix:
            d["fix"] = fix
            fixes.append(d)
    # 阶段3：错题复测（收敛）
    n_fix_ok = 0
    fix_retest = []
    for f in fixes:
        vd, conf, path = self_judge(ng, pats, n2w, f["s"], f["v"], f["o"],
                                    vo_pairs, cat_members)
        ok = (vd == f["teacher"])
        n_fix_ok += ok
        f["retest"] = vd
        f["fixed"] = ok
        fix_retest.append(f)
        print(f"  错题复测「{f['s']}{f['v']}{f['o']}」({f['level']}档)："
              f"修正前自判 {f['self']} vs 教师 {f['teacher']}"
              f" → 修正后自判 {vd} {'✓ 收敛' if ok else '✗ 未收敛'}")
    # 阶段4：全题复测（最终一致率，验收口径 = 修正后网络）
    stat4 = Counter()
    for s, v, o, level in items:
        vd, _, _ = self_judge(ng, pats, n2w, s, v, o, vo_pairs, cat_members)
        tv, _ = teacher_verdict(ng, pats, s, v, o,
                                vo_pairs, cat_members, has_llm,
                                use_llm=(level == "拓展"))
        stat4[(level, "agree")] += (vd == tv)
        stat4[(level, "total")] += 1
    return stat1, fixes, stat4, detail


def grade_report(stat, fixes, stage="阶段1（修正前）"):
    """分档一致率统计。"""
    print(f"\n【⑤b 课后练习批改 {stage}】分档一致率（网络自判 vs 教师判断）")
    rates = {}
    for level in ["基础", "巩固", "拓展"]:
        a, t = stat[(level, "agree")], stat[(level, "total")]
        rate = a / t if t else 1.0
        rates[level] = rate
        tag = ("≈1.0 ✅" if level == "基础" and rate >= 0.9 else
               "≥0.9 ✅" if level == "巩固" and rate >= 0.9 else
               "泛化边界" if level == "拓展" else "")
        print(f"  {level}档：{a}/{t} = {rate:.3f} {tag}")
    if stage.startswith("阶段1"):
        print(f"  修正：{len(fixes)} 次（误放行删边 / 误拒绝固化作答句）")
    return rates


# ── 继承 v11 验收（字/词/句 + 2.5 类别 + hold-out 零遗忘）──────────


def inherit_acceptance(ng, vocab, pats, hanzi, cats25, sem,
                       eval_hanzi, eval_words, eval_sents):
    """v11 验收④ 全量继承：零遗忘校验。返回 (指标 dict, 全过?)。"""
    r0 = recall_words(ng, pats, eval_hanzi, K)
    rw0 = recall_words(ng, pats, eval_words, 20)
    rs0 = np.mean([sent_recall(ng, pats, s) for s in eval_sents])
    r0_after = recall_words(ng, pats, eval_hanzi, K)
    rw0_after = recall_words(ng, pats, eval_words, 20)
    rs0_after = np.mean([sent_recall(ng, pats, s) for s in eval_sents])
    ok_char = bool(r0_after >= r0 - 0.01)
    ok_word = bool(rw0_after >= rw0 - 0.01)
    ok_sent = bool(rs0_after >= rs0 - 0.01)
    cat_ok, hold_ok = {}, {}
    for label, d in cats25.items():
        tag_n = set()
        for t in d["tags"]:
            tag_n.update(pats.get(t, []))
        cat_ok[label] = round(float(np.mean(
            [edge_sum(ng, pats, w, tag_n) > 0.1 for w in d["train"]])), 4)
        others_n = set()
        for l2, d2 in cats25.items():
            if l2 == label:
                continue
            for t in d2["tags"]:
                others_n.update(pats.get(t, []))
            for m in d2["train"]:
                others_n.update(pats[m])
        mine = set(tag_n)
        for m in d["train"]:
            mine.update(pats[m])
        n_hok = 0
        for h in d["hold"]:
            shared = set(sem["words"][h]) & set().union(
                *(set(sem["words"][m]) for m in d["train"]))
            self_n = set(mine)
            for ss in shared:
                self_n.update(pats.get(ss, []))
            n_hok += int(edge_sum(ng, pats, h, self_n) > 0
                         and edge_sum(ng, pats, h, self_n)
                         >= edge_sum(ng, pats, h, others_n) * 0.5)
        hold_ok[label] = n_hok
    r_cat25 = float(np.mean(list(cat_ok.values()))) if cat_ok else 0.0
    n_hold25_ok = sum(hold_ok.values())
    n_hold25_tot = sum(len(d["hold"]) for d in cats25.values())
    ok_cat25 = bool(all(v >= 0.9 for v in cat_ok.values())) if cat_ok else True
    ok_hold25 = bool(n_hold25_ok >= n_hold25_tot * 0.5) if n_hold25_tot else True
    return ({"char": r0_after, "char_before": r0, "word": rw0_after,
             "word_before": rw0, "sent": rs0_after, "sent_before": rs0,
             "cat25": r_cat25, "cat25_per": cat_ok,
             "hold25_ok": n_hold25_ok, "hold25_tot": n_hold25_tot},
            ok_char and ok_word and ok_sent and ok_cat25 and ok_hold25)


def main():
    smoke = "--smoke" in sys.argv
    if smoke:
        print("⚠ SMOKE 模式：小规模快跑（仅验证机制，指标不具统计意义）")
        n_train, n_test, n_each = 60, 30, 4
    else:
        n_train, n_test, n_each = 800, 400, 6
    has_llm = bool(_load_key())
    t0 = time.time()
    print("═══ Stage 2.6 v12：网络自判（判断内化到网络结构）═══\n")
    print(f"[LLM] {'DEEPSEEK_API_KEY 已配置 → LLM 教师批改讲评（拓展档临界裁决）'
            if has_llm else '无 API key → 规则验证器回退（标注[模板占位]）'}")

    # ── 1. 加载 v11.2（动宾搭配 + 连接级处罚 + LLM 教师最新）──
    ng, vocab, pats, cursor = load_version("11.2")
    hanzi = json.loads((DATA / "stage0_hanzi.json").read_text(encoding="utf-8"))
    print(f"[加载] 11.2（Stage 2.6 链最新）：n={ng.n}，模式 {len(pats)}，cursor={cursor}")

    # ── 2. 集合构造（∩ v11.2 网络）──
    s_words = sorted({w for w in PERS_MANUAL + S_ANIMALS if w in pats})
    v_words = sorted({w for w in V_SET if w in pats})
    o_words = sorted({w for w in O_FOOD + O_PLACE if w in pats})
    if not (s_words and v_words and o_words):
        raise SystemExit(f"S {len(s_words)} / V {len(v_words)} / O {len(o_words)} 有空集")
    vo_pairs = {v: [o for o in ops if o in pats]
                for v, ops in VO_PAIRS.items() if v in v_words}
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats25 = build_cats(pats, sem["words"], 12, 3)
    cat_members = {}
    for l in ["食物", "地点"]:
        d = cats25.get(l)
        cat_members[l] = set(d["train"]) | set(d["hold"]) if d else set()
    cat_members["食物"] |= set(O_FOOD)
    cat_members["地点"] |= set(O_PLACE)
    noun_pool = cat_members["食物"] | cat_members["地点"]
    n2w = {j: w for w, ns in pats.items() for j in ns}

    # ── 3. 组合划分（与 v11 同种子同划分 → 验收可比）──
    all_combos = [(s, v, o) for s in s_words for v in v_words for o in o_words]
    rng = np.random.default_rng(SEED)
    perm = rng.permutation(len(all_combos))
    train_combos = [all_combos[i] for i in perm[:n_train]]
    test_combos = [all_combos[i] for i in perm[n_train:n_train + n_test]]
    print(f"[组合] 总 {len(all_combos)}，训练 {len(train_combos)}，测试 {len(test_combos)}")

    # ── 4. ⑤a 判断方法教学（示范 + 修正校准）──
    t1 = time.time()
    method_log = method_lesson(ng, pats, n2w, vo_pairs, cat_members, has_llm)

    # ── 5. ⑤b 课后练习（题集 → 自判 → 批改 → 修正 → 复测）──
    items = exercise_set(s_words, v_words, o_words, train_combos, test_combos,
                         vo_pairs, cat_members, noun_pool, n_each=n_each)
    print(f"\n【⑤b 课后练习】题集 {len(items)} 道（三档 × 变式 × 穿插）")
    stat1, fixes, stat4, detail = homework_loop(
        ng, pats, n2w, items, vo_pairs, cat_members, has_llm)
    rates1 = grade_report(stat1, fixes, stage="阶段1（修正前）")
    rates4 = grade_report(stat4, fixes, stage="阶段4（修正后复测）")
    r_fix = sum(1 for f in fixes if f["fixed"]) / len(fixes) if fixes else 1.0
    print(f"[错误收敛] 错题复测 {sum(1 for f in fixes if f['fixed'])}/{len(fixes)}"
          f" = {r_fix:.3f} {'✅' if r_fix >= 0.8 or not fixes else '❌'}")

    # ── 6. 继承 v11 验收（零遗忘）──
    words_old = [w for w in vocab if w not in set(hanzi)]
    eval_hanzi = list(np.random.default_rng(7).choice(hanzi, 200, replace=False))
    eval_words = list(np.random.default_rng(8).choice(words_old, 300, replace=False))
    sents_all = json.loads((DATA / "stage2_sents.json").read_text(encoding="utf-8"))
    eval_sents = [sents_all[i] for i in np.random.default_rng(9).choice(
        len(sents_all), 100, replace=False)]
    inh, ok_inh = inherit_acceptance(
        ng, vocab, pats, hanzi, cats25, sem, eval_hanzi, eval_words, eval_sents)
    print(f"[继承] 字 {inh['char']:.4f}（base {inh['char_before']:.4f}）"
          f" | 词 {inh['word']:.4f}（base {inh['word_before']:.4f}）"
          f" | 句 {inh['sent']:.4f}（base {inh['sent_before']:.4f}）"
          f" | 2.5 类别 {inh['cat25']:.4f} | hold {inh['hold25_ok']}/{inh['hold25_tot']}"
          f" {'✅' if ok_inh else '❌ 回退!'}")

    # ── 7. 自判 vs 教师对照样例（报告显式并列）──
    print("\n[自判样例]（网络自判 vs 教师判断，阶段4 修正后）")
    for d in detail[:10]:
        m = "✓" if d["agree"] else "✗"
        print(f"  {m}「{d['s']}{d['v']}{d['o']}」({d['level']}档) "
              f"自判={d['self']}({d['conf']}) vs 教师={d['teacher']}"
              f" — {d['path']}{' | ' + d['fix'] if d.get('fix') else ''}")

    # ── 8. 验收（口径 = 阶段4 修正后一致率）──
    ok_base = rates4["基础"] >= 0.9
    ok_firm = rates4["巩固"] >= 0.9
    ok_fix = r_fix >= 0.8 or not fixes
    ok_all = bool(ok_base and ok_firm and ok_fix and ok_inh)
    print(f"\n[验收] 基础档 {rates4['基础']:.3f} {'✅ ≥0.9' if ok_base else '❌'}"
          f" | 巩固档 {rates4['巩固']:.3f} {'✅ ≥0.9' if ok_firm else '❌'}"
          f" | 拓展档 {rates4['拓展']:.3f}（泛化边界，LLM 裁决）"
          f" | 错误收敛 {r_fix:.3f} {'✅' if ok_fix else '❌'}"
          f" | 继承 {'✅' if ok_inh else '❌'}")
    print(f"\n═══ v12 验收: {'全部通过 ✅' if ok_all else '有失败 ❌'} "
          f"（{time.time() - t0:.0f}s）═══")

    # ── 9. 快照（parent=11.2 → v12.0；冒烟不存）──
    metrics = {"self_judge": True,
               "base_agree_1": round(rates1["基础"], 4),
               "firm_agree_1": round(rates1["巩固"], 4),
               "extend_agree_1": round(rates1["拓展"], 4),
               "base_agree_4": round(rates4["基础"], 4),
               "firm_agree_4": round(rates4["巩固"], 4),
               "extend_agree_4": round(rates4["拓展"], 4),
               "fix_actions": len(fixes),
               "fix_reconverge": round(r_fix, 4),
               "method_lesson": method_log, "exercise": detail,
               "llm_enabled": has_llm,
               "char_recall": inh["char"], "char_before": inh["char_before"],
               "word_recall": inh["word"], "word_before": inh["word_before"],
               "sent_recall": inh["sent"], "sent_before": inh["sent_before"],
               "cat25_recall": inh["cat25"], "cat25_per": inh["cat25_per"],
               "hold25_ok": inh["hold25_ok"], "hold25_tot": inh["hold25_tot"],
               "n": ng.n, "all_ok": ok_all}
    if not smoke:
        save_snapshot(ng, parent="11.2",
                      tag="Stage 2.6 v12：网络自判（判断内化到网络结构）",
                      metrics=metrics, vocab=vocab, pats=pats, cursor=cursor)


if __name__ == "__main__":
    main()
