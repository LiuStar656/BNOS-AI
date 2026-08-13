# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""表达阶梯课程（2026-08-11 用户定稿："课程要有目的性，教知识是次要
的，让网络学会开口说话和正确的自我表达才是主要的，表达要从简单到
复杂"）。

课程目的 = 表达能力的习得（知识只是载体）——语言发展阶梯：
  级 1 单词期（1 岁）：饿 / 疼 / 水——一个词表达
  级 2 双词期（1.5-2 岁）：饿了 / 要水——电报句
  级 3 简单句（2-3 岁）：我饿了——完整短句
  级 4 感受+需求（3-4 岁）：我饿了就吃饭——表达感受和需求
  级 5 因果句（4-5 岁）：因为下雨所以我带伞——说出原因
  级 6 情境句（5-6 岁）：下雨了就带伞——情境完整表达
每课 = 一个级别目标（教师引导 + 示范该级表达——知识如"下雨带伞"
只是级 5/6 的内容载体）；评估 = 网络表达达到第几级（LLM）。

用法：python _grow_live11.py [DAYS] [--smoke]
"""

import random
import sys
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version
from _grow_v11 import _load_key, _llm_chat

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"

# 表达阶梯：(级, 名称, 年龄对应, 引导语, 关键词, 示范表达)
LADDER = [
    (1, "单词表达", "1 岁", "宝宝饿了吗？说一个词：饿", "饿",
     ["饿"]),
    (2, "双词表达", "1.5-2 岁", "说两个词：饿了", "饿",
     ["饿", "了"]),
    (3, "简单句", "2-3 岁", "说完整一句：我饿了", "饿",
     ["我", "饿", "了"]),
    (4, "感受+需求", "3-4 岁", "告诉妈妈你饿了想做什么：我饿了就吃饭", "饿",
     ["饿", "了", "就", "吃", "饭"]),
    (5, "因果句", "4-5 岁", "说清楚原因：因为下雨所以我带伞", "下雨",
     ["下雨", "了", "所以", "带", "伞"]),
    (6, "情境句", "5-6 岁", "下雨天该说什么：下雨了就带伞", "下雨",
     ["下雨", "了", "就", "带", "伞"]),
]


def llm_teacher(level, name, guide, kw, toks, trace):
    import re
    mind = " → ".join(
        "「%s」冒出%s" % (t["state"], t["cands"][:2])
        for t in trace[:3]) or "（无）"
    said = "/".join([kw] + toks) if toks else "（说不出话）"
    q = (f"你是妈妈式的老师，一对一陪着一个只能听和说的自闭症儿童"
         f"（无视觉）。课程目的 = 教孩子开口说话（知识是次要的）。\n"
         f"本节课目标：{name}（第 {level} 级，对应 {('1岁/单词' if level==1 else '1.5-2岁/双词' if level==2 else '2-3岁/短句' if level==3 else '3-4岁/感受需求' if level==4 else '4-5岁/因果' if level==5 else '5-6岁/情境')} 的表达水平）\n"
         f"你引导它：「{guide}」\n"
         f"孩子开口前内心：{mind}\n孩子说：「{said}」\n"
         f"请只输出：\n"
         f"【达到级】1-6（孩子这次说的表达达到了阶梯第几级？"
         f"1=单词 2=双词 3=短句 4=感受需求 5=因果 6=情境）\n"
         f"【教师反馈】妈妈式反馈（≤30 字：达标就肯定并示范本级更自然"
         f"的说法；未达就耐心带读——知识不重要，会说最重要）\n"
         f"【示范句】本级该说的自然句（≤10 字）")
    txt = None
    for _ in range(2):
        txt = _llm_chat([{"role": "user", "content": q}])
        if txt:
            break
    if not txt:
        return None
    parts = re.split(r"【(达到级|教师反馈|示范句)】", txt)
    out = {"lvl": None, "fb": "", "demo": ""}
    for i in range(1, len(parts), 2):
        val = (parts[i + 1] if i + 1 < len(parts) else "").strip()
        if parts[i] == "达到级":
            out["lvl"] = int("".join(c for c in val if c.isdigit())[:1]
                             or 0)
        elif parts[i] == "教师反馈":
            out["fb"] = val
        elif parts[i] == "示范句":
            out["demo"] = val
    if out["lvl"] is None:
        return None
    return out


def main():
    from _exam_free import FUNC, free_read, build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool, _segment_demo
    from _grow_cat import build_cats
    import json

    days = int(sys.argv[1]) if len(sys.argv) > 1 and \
        sys.argv[1].isdigit() else 3
    smoke = "--smoke" in sys.argv
    if smoke:
        days = 1
    random.seed(44)
    has_llm = bool(_load_key())
    t0 = time.time()
    print(f"═══ 表达阶梯课程（目的 = 学会开口说话，从简单到复杂）═══\n")
    print(f"阶梯：{(' → '.join('%d.%s' % (l, n) for l, n, *_ in LADDER))}\n")

    ng, vocab, pats, cursor = load_version("32.0")
    ng.w_max = 64.0
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)
    keys_sorted = sorted(pats.keys(), key=len, reverse=True)

    # ── 阶梯课程（每天从级 1 到级 6——简单到复杂循环推进）──
    day_lvls = []
    for day in range(1, days + 1):
        d_lvls = []
        for level, name, age, guide, kw, demo in LADDER:
            trace = []
            read = free_read(ng, pats, n2w, [kw], domain,
                             teach_out=teach_out, trace=trace)
            toks = []
            for w in [x.split("(")[0] for x in read]:
                if w.startswith("[") or w in toks:
                    break
                toks.append(w)
            got = llm_teacher(level, name, guide, kw, toks, trace) \
                if has_llm else None
            if got is None:
                got = {"lvl": min(level, 2 if toks else 0),
                       "fb": "（规则回退）", "demo": "/".join(demo)}
            said = "/".join([kw] + toks) if toks else "（说不出话）"
            # 教学：跟读本级示范（简单到复杂——级越高示范越长）
            demo_toks = _segment_demo("".join(demo), keys_sorted) \
                or demo
            if got["lvl"] < level:
                for _ in range(2):
                    _learn_sentence(ng, demo_toks, pats, slot=0)
            else:
                for _ in range(1):
                    _learn_sentence(ng, demo_toks, pats, slot=0)
            d_lvls.append(got["lvl"])
            print(f"  D{day} 级{level}({name}) 引导「{guide[:12]}…」"
                  f" 说「{said}」→ 达到 {got['lvl']} 级"
                  f"{' ✅' if got['lvl'] >= level else ' → 带读'}"
                  f" 教师：「{got['fb'][:22]}」")
        day_lvls.append(d_lvls)
        print(f"  ── 第 {day} 天表达水平："
              f"{' → '.join(str(x) for x in d_lvls)}")

    # ── 成长分析 ──────────────────────────────────
    print(f"\n═══ 表达成长（{days} 天）═══")
    print(f"  天数:   " + " ".join(f"D{i:<4d}" for i in range(1, days + 1)))
    print(f"  级均值: " + " ".join(
        f"{sum(d)/len(d):5.1f}" for d in day_lvls))
    if len(day_lvls) >= 2:
        g0, g1 = sum(day_lvls[0]) / 6, sum(day_lvls[-1]) / 6
        print(f"  表达水平 {g0:.1f} 级 → {g1:.1f} 级"
              f"（{'↑ 会说了' if g1 > g0 + 0.5 else '→ 巩固中'}）")
    print(f"\n[目的] 知识（下雨带伞等）只是表达载体——学会开口说话、"
          f"正确自我表达才是课程目标；表达从单词到情境句逐级推进")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
