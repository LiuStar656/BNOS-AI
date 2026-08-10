# -*- coding: utf-8 -*-
"""Stage 2.6 v13（复杂句式练习题）：A 型「S 想要 O」+ B 型「S 在 V O」判断题。

需求（2026-08-10 用户）：
  - "句子变复杂一点：我要苹果 → 我想要苹果、他看石头 → 他在看石头"
  - "用复杂句式来做练习题；答不出来或答错要纠正，然后让大模型告诉他
    正确答案和解析"
  - "对错特别是判断题可以用代码不用大模型，大模型只负责告诉正确答案和解析"

设计（v12 课后练习框架复用，判定全代码化）：
  - 题集：A/B 两型 × 三档 × 变式穿插（12 道显式语义标注，人工定题）
  - 网络自判：核心三元 (S,V,O) 走 v12 self_judge（结构检查，纯代码）；
    A 型 V=想要/需要（无搭配类别 → 诚实留白"不知道"）；
    B 型去修饰词（在/想）取核心三元（在 = 体标记，结构无信号，标注诚实）
  - 教师判定：**代码规则**（不用 LLM）——
      宽松动词 {看, 想要, 需要, 买} → 任意宾语可造（语义能说，价值另算）
      严格动词 → 类别比对（O ∈ V 搭配类别 可造；O 有类别但不在 → 不可造）
  - 修正：复用 v12 四原则（一致不动 / 误放行删边 / 误拒绝固化整句 /
      保守诚实不动）；固化学整句（含修饰词 → 建立转移定式）
  - LLM 讲评：只对答错/答不出（自判 ≠ 教师）生成「正确答案 + 解析」
    （两行格式；无 key 回退模板占位）

验收：
  - 阶段1 修正前 / 阶段4 修正后 分档一致率
  - 错误收敛（错题复测）
  - 继承 v12 全验收（字/词/句 + 2.5 类别 + hold-out 零遗忘）
  - save_snapshot(parent="12.0") → v13.0

用法：python _grow_v13.py [--smoke]
"""

import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from _grow_cat import build_cats
from _grow_v11 import (attributed_sentence, penalize_bad_word, _load_key,
                       _llm_chat, O_FOOD, O_PLACE, O_TAGS,
                       VO_PAIRS, V_SET, PERS_MANUAL, S_ANIMALS)
from _grow_v12 import self_judge, inherit_acceptance

DATA = Path(__file__).parent / "data" / "curriculum"
SEED = 42

# ── 题集（12 道，A/B 两型 × 三档 × 变式穿插，人工语义标注）──────
# A 型 = [S, 想要/需要, O]（想要族直接带宾语）
# B 型 = [S, 在/想, V, O]（修饰词 + 核心动词）
COMPLEX_ITEMS = [
    # 基础档（简单句升级、直连可达）
    (["我", "想要", "苹果"], "基础"),
    (["他", "在", "看", "石头"], "基础"),
    (["我", "在", "吃", "西瓜"], "基础"),
    (["我", "需要", "牛奶"], "基础"),
    # 巩固档（新组合 / 类别泛化）
    (["我", "想要", "香蕉"], "巩固"),
    (["他", "想要", "饼干"], "巩固"),
    (["我", "想", "看", "公园"], "巩固"),
    (["他", "在", "吃", "苹果"], "巩固"),
    # 拓展档（临界：语义能说但价值坏 / 明确错误句）
    (["我", "想要", "石头"], "拓展"),    # 临界：能说（石头坏但不影响句子合法性）
    (["我", "在", "吃", "学校"], "拓展"),  # 错：类别冲突（学校不是食物）
    (["他", "在", "吃", "石头"], "拓展"),  # 错：语义+价值（保守诚实不动）
    (["我", "在", "看", "石头"], "拓展"),  # 临界：能说（v12 已固化 看→石头）
]

# 宽松动词：语义上几乎任意宾语都合法（价值判断与句子合法性分开）
LOOSE_V = {"看", "想要", "需要", "买"}


# ── 解析：复杂句 → (S, V, O, mods) ──────────────────────────────


def parse_complex(tokens):
    """A 型 [S, 想要/需要, O] → V=想要；B 型 [S, 在/想, V, O] → 去修饰词取 V。"""
    if len(tokens) == 3:
        return tokens[0], tokens[1], tokens[2], []
    if len(tokens) == 4:
        return tokens[0], tokens[2], tokens[3], [tokens[1]]
    raise ValueError(f"不支持句长 {len(tokens)}: {tokens}")


# ── 教师判定（代码规则，不用 LLM）───────────────────────────────


def teacher_rule(ng, pats, tokens, vo_pairs, cat_members):
    """教师判定 → (verdict, basis)。判定依据 = 代码规则（宽松/严格动词类别比对）。

    宽松动词（看/想要/需要/买）：语义上几乎任意宾语都能说 → 可造
      （价值判断与句子合法性分开：石头是坏东西，但"想要石头/看石头"能说）
    严格动词：类别比对——O ∈ V 搭配类别成员 → 可造；
      O 有明确类别归属但不在 V 搭配 → 不可造；其余（V 无搭配/O 无类别）→ 不可造
      （教师必须有明确答案，不留"不知道"；网络自判才允许诚实留白）
    """
    s, v, o, mods = parse_complex(tokens)
    if v in LOOSE_V:
        return "可造", "宽松动词（任意宾语语义合法，价值另算）"
    allow = set()
    for ov in vo_pairs.get(v, []):
        for c, mem in cat_members.items():
            if ov in mem:
                allow.add(c)
    allow_mem = set().union(*(cat_members[c] for c in allow)) if allow else set()
    if o in allow_mem:
        return "可造", f"{o} ∈ {v} 搭配类别 [{'、'.join(sorted(allow))}]"
    o_has_cat = any(o in cat_members.get(t, set()) for t in O_TAGS)
    if o_has_cat:
        cat_own = "、".join(t for t in O_TAGS if o in cat_members.get(t, set()))
        return "不可造", f"{o} 属 {cat_own}，不在 {v} 搭配类别"
    return "不可造", f"{v} 严格动词且 {o} 无合法搭配（语义/价值双重拒绝）"


# ── 网络自判（核心三元走 v12 self_judge）────────────────────────


def complex_self_judge(ng, pats, n2w, tokens, vo_pairs, cat_members):
    """网络自判复杂句 → (verdict, conf, path)。

    核心三元 (S,V,O) 走 v12 self_judge（结构检查）；
    修饰词（在/想）网络无结构信号 → 诚实标注"修饰未判"。
    """
    s, v, o, mods = parse_complex(tokens)
    vd, conf, path = self_judge(ng, pats, n2w, s, v, o,
                                vo_pairs, cat_members)
    if mods:
        path = f"{'、'.join(mods)}修饰未判（核心判定：{path}）"
    return vd, conf, path


# ── 修正（复用 v12 四原则；固化学整句含修饰词）──────────────────


def complex_apply_fix(ng, pats, n2w, tokens, vd, tv, vo_pairs, cat_members):
    """按不一致类型修正。返回修正描述（None = 无动作）。"""
    s, v, o, _ = parse_complex(tokens)
    if vd == tv:
        return None
    if vd == "可造" and tv == "不可造":
        _, top, allow, sources = attributed_sentence(
            ng, pats, n2w, s, v, vo_pairs, cat_members)
        pen = penalize_bad_word(ng, pats, n2w, o, sources, allow, [])
        return f"误放行 → 删除 {o} 来源边 {pen or '（无来源）'}"
    if tv == "可造":
        _learn_sentence(ng, tokens, pats, slot=0)
        return f"误拒绝 → 固化正确路径（学 {'、'.join(tokens)} 1 次）"
    return None                                   # 保守诚实：不建立错误边


# ── LLM 讲评（只对答错/答不出：正确答案 + 解析）─────────────────
# 判定 = 代码规则；LLM 只负责"告诉正确答案和解析"（2026-08-10 用户定）


def llm_explain(tokens, vd, tv, has_llm):
    """LLM 生成「正确答案 + 解析」两行。无 key / 失败 → 模板占位。"""
    sent = "".join(tokens)
    ans_txt = f"能说「{sent}」" if tv == "可造" else f"不能说「{sent}」"
    if not has_llm:
        return (f"[模板占位] 正确答案：{ans_txt}。\n"
                f"[模板占位] 解析：教师规则判定为{tv}（依据代码类别比对，"
                f"非 LLM）。")
    q = (f"你是中文教师。判断题：能否说「{sent}」？学生自判为「{vd}」，"
         f"正确答案是「{'能说' if tv == '可造' else '不能说'}」。"
         f"请只输出两行：第一行「正确答案：{ans_txt}。」；"
         f"第二行「解析：不超过 40 字的语法/语义解释（如：'想要'表达"
         f"想要得到某物；'在'表示正在进行的动作；'吃'的宾语只能是食物）。」")
    txt = _llm_chat([{"role": "user", "content": q}])
    if txt is None:
        return (f"[模板占位] 正确答案：{ans_txt}。\n"
                f"[模板占位] 解析：LLM 调用失败回退。")
    return txt.strip()[:160]


# ── 练习主循环（四阶段，同 v12 口径）────────────────────────────


def complex_homework(ng, pats, n2w, items, vo_pairs, cat_members, has_llm):
    """阶段1 全题自判+批改 → 阶段2 统一修正 → 阶段3 错题复测 → 阶段4 全题复测。"""
    stat1 = Counter()
    detail = []
    for tokens, level in items:
        vd, conf, path = complex_self_judge(ng, pats, n2w, tokens,
                                            vo_pairs, cat_members)
        tv, basis = teacher_rule(ng, pats, tokens, vo_pairs, cat_members)
        agree = (vd == tv)
        stat1[(level, "agree")] += agree
        stat1[(level, "total")] += 1
        detail.append({"sent": "".join(tokens), "tokens": tokens, "level": level,
                       "self": vd, "conf": conf, "path": path,
                       "teacher": tv, "teacher_basis": basis, "agree": agree})
    # 阶段2：LLM 讲评（答错/答不出 → 正确答案+解析，2026-08-10 用户定）
    # 所有"自判 ≠ 教师"的题都要讲评（含保守诚实不动网络的不一致题）
    for d in detail:
        if not d["agree"]:
            d["explain"] = llm_explain(d["tokens"], d["self"], d["teacher"],
                                       has_llm)
    # 统一修正（仅按四原则需要动作的）
    fixes = []
    for d in detail:
        fix = complex_apply_fix(ng, pats, n2w, d["tokens"], d["self"],
                                d["teacher"], vo_pairs, cat_members)
        if fix:
            d["fix"] = fix
            fixes.append(d)
    # 阶段3：错题复测（收敛）
    n_fix_ok = 0
    for f in fixes:
        vd, conf, path = complex_self_judge(ng, pats, n2w, f["tokens"],
                                            vo_pairs, cat_members)
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
            print(f"  保守诚实「{d['sent']}」({d['level']}档)："
                  f"自判 {d['self']} vs 教师 {d['teacher']}"
                  f" → 不修正（无结构证据，诚实留白）")
        if d.get("explain"):
            print(f"    LLM 讲评：{d['explain'].replace(chr(10), ' ')}")
    # 阶段4：全题复测（验收口径）
    stat4 = Counter()
    for tokens, level in items:
        vd, _, _ = complex_self_judge(ng, pats, n2w, tokens,
                                      vo_pairs, cat_members)
        tv, _ = teacher_rule(ng, pats, tokens, vo_pairs, cat_members)
        stat4[(level, "agree")] += (vd == tv)
        stat4[(level, "total")] += 1
    return stat1, fixes, stat4, detail


def grade_report(stat, fixes, stage="阶段1（修正前）"):
    print(f"\n【复杂句式练习题 {stage}】分档一致率（网络自判 vs 教师代码规则）")
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
        print(f"  修正：{len(fixes)} 次（误放行删边 / 误拒绝固化整句）")
    return rates


def main():
    smoke = "--smoke" in sys.argv
    if smoke:
        print("⚠ SMOKE 模式：小规模快跑（机制验证，不跑继承全量）")
    has_llm = bool(_load_key())
    t0 = time.time()
    print("═══ Stage 2.6 v13：复杂句式练习题（A 型想要族 + B 型体标记）═══\n")
    print(f"[判定] 教师 = 代码规则（宽松/严格动词）| 网络自判 = v12 self_judge"
          f"\n[LLM] {'DEEPSEEK_API_KEY 已配置 → LLM 只讲评（正确答案+解析）'
                if has_llm else '无 API key → 模板占位讲评'}")

    # ── 1. 加载 v12.0（网络自判最新）──
    ng, vocab, pats, cursor = load_version("12.0")
    hanzi = json.loads((DATA / "stage0_hanzi.json").read_text(encoding="utf-8"))
    print(f"[加载] 12.0：n={ng.n}，模式 {len(pats)}，cursor={cursor}")

    # ── 2. 集合构造（∩ v12.0 网络）──
    s_words = sorted({w for w in PERS_MANUAL + S_ANIMALS if w in pats})
    v_words = sorted({w for w in V_SET if w in pats})
    o_words = sorted({w for w in O_FOOD + O_PLACE if w in pats})
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
    n2w = {j: w for w, ns in pats.items() for j in ns}
    # 题集词校验（题里每个词必须在网络模式中）
    missing = sorted({w for tks, _ in COMPLEX_ITEMS for w in tks if w not in pats})
    if missing:
        raise SystemExit(f"题集词不在网络模式: {missing}")

    # ── 3. 练习题（阶段1 → 修正 → 复测 → 阶段4）──
    print(f"\n【复杂句式练习题】题集 {len(COMPLEX_ITEMS)} 道（A/B 两型 × 三档 × 穿插）")
    stat1, fixes, stat4, detail = complex_homework(
        ng, pats, n2w, COMPLEX_ITEMS, vo_pairs, cat_members, has_llm)
    rates1 = grade_report(stat1, fixes, stage="阶段1（修正前）")
    rates4 = grade_report(stat4, fixes, stage="阶段4（修正后复测）")
    r_fix = (sum(1 for f in fixes if f["fixed"]) / len(fixes)
             if fixes else 1.0)
    print(f"[错误收敛] 错题复测 {sum(1 for f in fixes if f['fixed'])}/{len(fixes)}"
          f" = {r_fix:.3f} {'✅' if r_fix >= 0.8 or not fixes else '❌'}")

    # ── 4. 逐题对照（含 LLM 讲评全文）──
    print("\n[逐题对照]（网络自判 vs 教师代码判定，阶段4 后）")
    for d in detail:
        m = "✓" if d["agree"] else "✗"
        print(f"  {m}「{d['sent']}」({d['level']}档) "
              f"自判={d['self']}({d['conf']}, {d['path']})"
              f" vs 教师={d['teacher']}"
              f"{' | ' + d['fix'] if d.get('fix') else ''}")

    # ── 5. 继承 v12 验收（零遗忘；smoke 跳过）──
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

    # ── 6. 验收 ──
    ok_base = rates4["基础"] >= 0.9
    ok_firm = rates4["巩固"] >= 0.9
    ok_fix = r_fix >= 0.8 or not fixes
    ok_all = bool(ok_base and ok_firm and ok_fix and ok_inh)
    print(f"\n[验收] 基础 {rates4['基础']:.3f} {'✅' if ok_base else '❌'}"
          f" | 巩固 {rates4['巩固']:.3f} {'✅' if ok_firm else '❌'}"
          f" | 拓展 {rates4['拓展']:.3f}（泛化边界）"
          f" | 错误收敛 {r_fix:.3f} {'✅' if ok_fix else '❌'}"
          f" | 继承 {'✅' if ok_inh else '❌'}"
          f" {'（smoke 未跑）' if smoke else ''}")
    print(f"\n═══ v13 验收: {'全部通过 ✅' if ok_all else '有失败 ❌'} "
          f"（{time.time() - t0:.0f}s）═══")

    # ── 7. 快照（parent=12.0 → v13.0；冒烟不存）──
    metrics = {"complex_exercise": True,
               "base_agree_1": round(rates1["基础"], 4),
               "firm_agree_1": round(rates1["巩固"], 4),
               "extend_agree_1": round(rates1["拓展"], 4),
               "base_agree_4": round(rates4["基础"], 4),
               "firm_agree_4": round(rates4["巩固"], 4),
               "extend_agree_4": round(rates4["拓展"], 4),
               "fix_actions": len(fixes),
               "fix_reconverge": round(r_fix, 4),
               "items": detail,
               "llm_enabled": has_llm, "llm_judge": False,
               "n": ng.n, "all_ok": ok_all}
    if not smoke:
        save_snapshot(ng, parent="12.0",
                      tag="Stage 2.6 v13：复杂句式练习题（A 型想要族 + B 型体标记，代码判定 + LLM 讲评）",
                      metrics=metrics, vocab=vocab, pats=pats, cursor=cursor)
        # 练习数据独立留档（每次实验必须保存）
        out = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_complex_exercise"
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").write_text(json.dumps(metrics, ensure_ascii=False,
                                                    indent=1), encoding="utf-8")


RUNS_DIR = Path(__file__).parent / "runs"


if __name__ == "__main__":
    main()
