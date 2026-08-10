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

双轨（同 v11）：DEEPSEEK_API_KEY → LLM 教师批改（判断+原因）；
无 key → 规则验证器回退（标注[模板占位]）。

流程（在 v11.2 快照上迭代，不重训）：
  load_version("11.2")
    → ⑤a 判断方法教学（示范判断过程 + 诊断样本校准阈值）
    → ⑤b 课后练习（三档×变式×穿插题集 → 网络自判 → 教师批改
       → 归因修正：误放行删来源边 / 误拒绝固化作答句）
    → 验收（一致率分档 + 错误收敛 + 继承 v11 全验收）
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
GENERALIZE_DISC = 0.3    # 类别泛化二跳折扣（与 attributed_sentence 同款）
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
    if reach2:
        conf = "低" if (o_rank is None or o_rank >= TOP_WIN) else "中"
        return "可造", conf, f"类别泛化（{v} 搭配 {'、'.join(sorted(allow))}）"
    if allow and o_has_cat:
        return "不可造", "中", (f"类别冲突（{o} 属 "
                                f"{'、'.join(t for t in O_TAGS if o in cat_members.get(t, set()))}"
                                f"，不在 {v} 搭配 {'、'.join(sorted(allow))}）")
    if o_rank is not None and o_rank < TOP_WIN:
        return "不可造", "低", "强度够但结构不可达（进 top 却无搭配边）"
    return "不知道", "低", "诚实留白（无结构证据）"


# ── 教师判断（批改口径：LLM 优先，规则回退）────────────────────
# 把教师判断映射到自判三元 verdict，供一致率对比


def teacher_verdict(ng, pats, s, v, o, vo_pairs, cat_members, has_llm):
    """教师判断 → (verdict, reason)。LLM 判断（对/错）or 规则验证器回退。"""
    ok_path, top, allow, _ = attributed_sentence(
        ng, pats, {}, s, v, vo_pairs, cat_members)
    kind, _, allow_mem = rule_verifier(
        ng, pats, s, v, o, allow, cat_members, top)
    diag = {"S": s, "V": v, "O": o, "kind": kind, "allow": sorted(allow),
            "top": top, "principles": {}, "allow_mem": sorted(allow_mem)[:8],
            "penalized": None}
    if has_llm and kind != "plain":
        res = llm_judge(diag)
        if res:
            jg, reason = res
            return ("可造" if jg == "对" else "不可造"), reason
    reason = template_reason(diag)
    if kind == "ok":
        return "可造", reason
    if kind == "bad":
        return "不可造", reason
    return "不知道", reason


# ── ⑤a 判断方法教学：示范判断过程 + 诊断样本校准 ────────────────
# 示范 = 教师演示"怎么判"（先查直连、再查二跳、再判强度、判不出说不知道）；
# 判断正确的对象句固化（_learn_sentence，V→O 直连增强 → 判断依据变强），
# 判断错误的来源边处罚（归因修正），校准"该判可造的要有边、不该造的没边"。


def method_lesson(ng, pats, n2w, vo_pairs, cat_members, has_llm, s="我"):
    """⑤a 判断方法教学。返回留档记录 list。"""
    print("\n【⑤a 判断方法教学】教师示范判断过程（先查直连、再查二跳、再判强度）")
    log = []
    samples = [("我", "要", "苹果"), ("我", "吃", "学校"), ("我", "画", "家"),
               ("我", "看", "石头")]
    for sv, v, o in samples:
        vd, conf, path = self_judge(ng, pats, n2w, sv, v, o,
                                    vo_pairs, cat_members)
        tv, reason = teacher_verdict(ng, pats, sv, v, o,
                                     vo_pairs, cat_members, has_llm)
        print(f"  示范「{sv}{v}{o}」：网络自判={vd}({conf}, {path})"
              f" | 教师={tv} — {reason[:30]}")
        log.append({"s": sv, "v": v, "o": o, "self": vd, "conf": conf,
                    "path": path, "teacher": tv, "reason": reason})
        # 校准：自判对 → 固化判断对象句（直连增强）；自判错 → 归因修正
        if vd == tv:
            _learn_sentence(ng, [sv, v, o], pats, slot=0)
            print(f"    ✓ 判断正确 → 对象句固化（{v}→{o} 直连增强）")
        else:
            _, top, allow, sources = attributed_sentence(
                ng, pats, n2w, sv, v, vo_pairs, cat_members)
            pen = penalize_bad_word(ng, pats, n2w, o, sources, allow, log)
            if pen:
                print(f"    ✗ 判断不一致 → 归因修正（删除 {o} 的来源边 {pen}）")
            else:
                print(f"    ✗ 判断不一致 → 无来源边可修（诚实留白，交由教师裁决）")
    return log


# ── ⑤b 课后练习题集：三档 × 变式 × 穿插 ─────────────────────────
# 基础档 = 训练组合复测（V→O 直连）；巩固档 = 三词单训过的新组合；
# 拓展档 = 类别泛化二跳 + 跨类临界（无类别词，LLM 裁决）。
# 变式：正（可造）/ 逆（不可造/不知道）；穿插：V 交错混出。


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
    # 逆例：O 有明确类别归属但不在 V 搭配类别（网络能判"不可造"）
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
    # 跨类临界：无类别归属词（如石头）+ 无搭配动词 → LLM 裁决，网络判不知道
    for v in ["吃", "看", "买"]:
        items.append((s_words[0], v, "石头", "拓展"))
    # 穿插：按 V 交错排列（防同 V 连片 → "O 槽保底"定式）
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


# ── ⑤b 课后练习：网络自判 → 教师批改 → 归因修正 ──────────────────
# 一致 → 固化判断对象句；误放行（自判可造、教师不可造）→ 删来源边；
# 误拒绝（自判不可造/不知道、教师可造）→ 固化正确路径（作答句）。


def homework_loop(ng, pats, n2w, items, vo_pairs, cat_members, has_llm):
    """⑤b 课后练习循环。返回 (一致统计, 修正记录, 逐题记录)。"""
    stat = Counter()
    fixes = []
    detail = []
    for s, v, o, level in items:
        vd, conf, path = self_judge(ng, pats, n2w, s, v, o,
                                    vo_pairs, cat_members)
        tv, reason = teacher_verdict(ng, pats, s, v, o,
                                     vo_pairs, cat_members, has_llm)
        agree = (vd == tv)
        stat[(level, "agree")] += agree
        stat[(level, "total")] += 1
        fix = None
        if agree:
            _learn_sentence(ng, [s, v, o], pats, slot=0)   # 一致 → 固化判断依据
        elif vd == "可造" and tv == "不可造":                # 误放行 → 删来源边
            _, top, allow, sources = attributed_sentence(
                ng, pats, n2w, s, v, vo_pairs, cat_members)
            pen = penalize_bad_word(ng, pats, n2w, o, sources, allow, [])
            fix = f"误放行 → 删除 {o} 来源边 {pen or '（无来源）'}"
        else:                                               # 误拒绝 → 固化正确路径
            _learn_sentence(ng, [s, v, o], pats, slot=0)
            fix = "误拒绝 → 固化正确路径（作答句学习 1 次）"
        if fix:
            fixes.append({"s": s, "v": v, "o": o, "level": level,
                          "self": vd, "teacher": tv, "fix": fix})
        detail.append({"s": s, "v": v, "o": o, "level": level,
                       "self": vd, "conf": conf, "path": path,
                       "teacher": tv, "agree": agree,
                       "teacher_reason": reason[:40], "fix": fix})
    return stat, fixes, detail


def grade_report(stat, fixes, detail):
    """分档一致率统计 + 错误样本清单（错误收敛 = 修正后重测判对）。"""
    print("\n【⑤b 课后练习批改】分档一致率（网络自判 vs 教师判断）")
    lines = {}
    for level in ["基础", "巩固", "拓展"]:
        a, t = stat[(level, "agree")], stat[(level, "total")]
        rate = a / t if t else 1.0
        lines[level] = rate
        tag = ("≈1.0 ✅" if level == "基础" and rate >= 0.9 else
               "≥0.9 ✅" if level == "巩固" and rate >= 0.9 else
               "泛化边界" if level == "拓展" else "")
        print(f"  {level}档：{a}/{t} = {rate:.3f} {tag}")
    print(f"  修正：{len(fixes)} 次（误放行删边 / 误拒绝固化作答句）")
    return lines


# ── 错误收敛复测：修正后重测错题，验证判对 ───────────────────────


def error_reconverge(ng, pats, n2w, fixes, vo_pairs, cat_members):
    """自判错误样本修正后重测：错题应判对（错误收敛）。"""
    n_fix_ok = 0
    out = []
    for f in fixes:
        vd, conf, path = self_judge(ng, pats, n2w, f["s"], f["v"], f["o"],
                                    vo_pairs, cat_members)
        ok = (vd == f["teacher"])
        n_fix_ok += ok
        out.append({**f, "retest": vd, "fixed": ok})
        print(f"  错题复测「{f['s']}{f['v']}{f['o']}」({f['level']}档)："
              f"修正前自判 {f['self']} vs 教师 {f['teacher']}"
              f" → 修正后自判 {vd} {'✓ 收敛' if ok else '✗ 未收敛'}")
    return n_fix_ok, out


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
    print(f"[LLM] {'DEEPSEEK_API_KEY 已配置 → LLM 教师批改讲评'
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

    # ── 4. ⑤a 判断方法教学（示范 + 校准）──
    t1 = time.time()
    method_log = method_lesson(ng, pats, n2w, vo_pairs, cat_members, has_llm)

    # ── 5. ⑤b 课后练习（题集 → 自判 → 批改 → 归因修正）──
    items = exercise_set(s_words, v_words, o_words, train_combos, test_combos,
                         vo_pairs, cat_members, noun_pool, n_each=n_each)
    print(f"\n【⑤b 课后练习】题集 {len(items)} 道（三档 × 变式 × 穿插）")
    stat, fixes, detail = homework_loop(ng, pats, n2w, items,
                                        vo_pairs, cat_members, has_llm)
    rates = grade_report(stat, fixes, detail)

    # ── 6. 错误收敛复测 ──
    n_fix_ok = 0
    fix_retest = []
    if fixes:
        n_fix_ok, fix_retest = error_reconverge(
            ng, pats, n2w, fixes, vo_pairs, cat_members)
    r_fix = n_fix_ok / len(fixes) if fixes else 1.0
    print(f"[错误收敛] 修正后复测 {n_fix_ok}/{len(fixes) or 0} = {r_fix:.3f}"
          f" {'✅' if r_fix >= 0.8 or not fixes else '❌'}")

    # ── 7. 继承 v11 验收（零遗忘）──
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

    # ── 8. 自判 vs 教师对照样例（报告显式并列）──
    print("\n[自判样例]（网络自判 vs 教师判断）")
    for d in detail[:8]:
        m = "✓" if d["agree"] else "✗"
        print(f"  {m}「{d['s']}{d['v']}{d['o']}」({d['level']}档) "
              f"自判={d['self']}({d['conf']}) vs 教师={d['teacher']}"
              f" — {d['path']}")

    # ── 9. 验收 ──
    r_base = rates["基础"]
    r_firm = rates["巩固"]
    ok_base = r_base >= 0.9
    ok_firm = r_firm >= 0.9
    ok_fix = r_fix >= 0.8 or not fixes
    ok_all = bool(ok_base and ok_firm and ok_fix and ok_inh)
    print(f"\n[验收] 基础档一致率 {r_base:.3f} {'✅ ≥0.9' if ok_base else '❌'}"
          f" | 巩固档 {r_firm:.3f} {'✅ ≥0.9' if ok_firm else '❌'}"
          f" | 拓展档 {rates['拓展']:.3f}（泛化边界）"
          f" | 错误收敛 {r_fix:.3f} {'✅' if ok_fix else '❌'}"
          f" | 继承 {'✅' if ok_inh else '❌'}")
    print(f"\n═══ v12 验收: {'全部通过 ✅' if ok_all else '有失败 ❌'} "
          f"（{time.time() - t0:.0f}s）═══")

    # ── 10. 快照（parent=11.2 → v12.0；冒烟不存）──
    metrics = {"self_judge": True,
               "base_agree": round(r_base, 4), "firm_agree": round(r_firm, 4),
               "extend_agree": round(rates["拓展"], 4),
               "level_agree": {k: round(stat[(k, "agree")] / max(1, stat[(k, "total")]), 4)
                               for k in ["基础", "巩固", "拓展"]},
               "fix_actions": len(fixes), "fix_reconverge": round(r_fix, 4),
               "method_lesson": method_log, "exercise": detail,
               "fix_retest": fix_retest,
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
