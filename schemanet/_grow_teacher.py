# -*- coding: utf-8 -*-
"""LLM 教师系统（2026-08-11 用户定稿："让 llm 教师成为网络的唯二
（内在时钟）刺激源，教师用说和引导的方式带网络学会自我表达和基本
常识——提前设计教学内容背景，观察记录心理活动和表达一致性以及表达
自然程度打分（鼓励但也示范更自然表达）和奖励，表达和心里不一致的
引导正确表达（处罚和注入正确的表达方式）"）。

架构：
  刺激源：① 内在时钟（持续运行节拍）② LLM 教师（唯一主动刺激——
          说和引导）
  教师职责链（每课）：
    备课（教学内容背景：常识课程 + 自我表达课程）
    → 说（引导语）
    → 观察（心理活动 trace：候选/选择——网络心里想的）
    → 网络表达（自由读说出）
    → 打分（一致性 × 自然度——门槛×高度）
    → 反馈（四档）：
       一致且自然（≥80）→ 鼓励 + 奖励固化 ×3
       一致但生硬（60-79）→ 鼓励 + 示范更自然表达（跟读 ×2）
       漂移但可辨（40-59）→ 指出 + 示范（跟读 ×2）
       严重漂移（<40）→ **处罚**（漂移边降权 ×0.5——说错了别老说）
                        + **注入正确表达**（示范跟读 ×2）
  教师一次调用多节（对齐 _speak 压缩模式：一致性/自然度/反馈/示范）

用法：python _grow_teacher.py [--smoke]
"""

import sys
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from _grow_v11 import _load_key, _llm_chat

DATA = Path(__file__).parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).parent / "runs"

# ── 备课：教学内容背景（教师设计——常识课程 + 自我表达）────
CURRICULUM = [
    # (课题, 引导语, 关键词, 期望表达, 领域)
    ("早上起床流程", "早上起床要做什么呀？", "早上",
     ["早上", "起床", "洗", "手", "刷牙", "吃", "饭"], "常识"),
    ("饿的感受", "你饿不饿呀？", "饿",
     ["饿", "了", "就", "吃", "饭"], "自我表达"),
    ("下雨怎么办", "下雨了要做什么呀？", "下雨",
     ["下雨", "了", "就", "带", "伞"], "常识"),
    ("晚上流程", "晚上要做什么呀？", "晚上",
     ["晚上", "吃", "饭", "洗澡", "睡觉"], "常识"),
    ("危险的物品", "火能摸吗？", "火",
     ["不", "能", "摸", "火"], "安全常识"),
]


def teacher_once(lesson, trace, toks):
    """教师一次调用：打分（一致性×自然度）+ 反馈 + 示范（妈妈式）。"""
    kw = lesson[2]
    mind = " → ".join(
        f"想到「{t['state']}」，心里冒出 {t['cands'][:2]}"
        for t in trace[:4]) or "（无）"
    said = "/".join([kw] + toks) or "（说不出话）"
    q = (f"你是妈妈式的老师，一对一陪着一个只能听和说的自闭症儿童"
         f"（无视觉——听和说是它认识世界的全部通道）。\n"
         f"本节课的内容背景：教「{lesson[0]}」（{lesson[4]}）。\n"
         f"你刚才引导它：「{lesson[1]}」\n"
         f"孩子开口前的内心活动（完全可观测）：{mind}\n"
         f"孩子说出口：「{said}」\n"
         f"请只输出以下节（每行一个）：\n"
         f"【一致性】0-10（说出口的和心里想的贴不贴；不一致 = 心里想"
         f"吃饭却说雨伞）\n"
         f"【自然度】0-10（像不像人话：语法/语义/连贯）\n"
         f"【教师反馈】妈妈式自然反馈（≤28 字：说得好平静地肯定；"
         f"说得怪就一句'老师问的是…'；想带读就'来，跟老师说：…'，"
         f"带读句和【示范句】一致）\n"
         f"【示范句】此刻孩子该说的更自然完整的表达（≤10 字）")
    txt = _llm_chat([{"role": "user", "content": q}])
    if not txt:
        return None
    out = {"cons": None, "nat": None, "fb": "", "demo": ""}
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("【一致性】"):
            out["cons"] = float("".join(c for c in line if c.isdigit()
                                        or c == ".")[:3] or 0)
        elif line.startswith("【自然度】"):
            out["nat"] = float("".join(c for c in line if c.isdigit()
                                       or c == ".")[:3] or 0)
        elif line.startswith("【教师反馈】"):
            out["fb"] = line.replace("【教师反馈】", "").strip()
        elif line.startswith("【示范句】"):
            out["demo"] = line.replace("【示范句】", "").strip()
    if out["cons"] is None or out["nat"] is None:
        return None
    return out


def penalize_drift(ng, pats, toks, expect):
    """处罚：表达链中不属于正确表达的相邻边降权 ×0.5（说错了别老说
    ——对齐 _speak V→O 减半哲学；正确表达链不动）。"""
    expect_set = set(expect)
    n_dec = 0
    for a, b in zip(toks[:-1], toks[1:]):
        if b in expect_set:
            continue
        if a not in pats or b not in pats:
            continue
        dst = set(pats[b])
        for i in pats[a]:
            row = ng.W_out[i][0]
            for j in list(row.keys()):
                if j in dst:
                    row[j] = row[j] * 0.5
                    n_dec += 1
    return n_dec


def main():
    from _exam_free import FUNC, free_read, build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool, _segment_demo
    from _grow_cat import build_cats
    import json

    smoke = "--smoke" in sys.argv
    has_llm = bool(_load_key())
    t0 = time.time()
    print("═══ LLM 教师系统（唯二刺激源：内在时钟 + 教师）═══\n")
    print(f"教师：{'LLM（DeepSeek）' if has_llm else '规则回退'}\n")

    ng, vocab, pats, cursor = load_version("31.0")
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

    lessons = CURRICULUM[:2] if smoke else CURRICULUM
    n_encourage = n_demo = n_punish = 0
    for i, lesson in enumerate(lessons, 1):
        name, guide, kw, expect, area = lesson
        print(f"── 第 {i} 课：{name}（{area}）──")
        print(f"  教师：「{guide}」")

        # 观察 + 表达
        trace = []
        read = free_read(ng, pats, n2w, [kw], domain,
                         teach_out=teach_out, trace=trace)
        toks = []
        for w in [x.split("(")[0] for x in read]:
            if w.startswith("[") or w in toks:
                break
            toks.append(w)
        said = "/".join([kw] + toks) if toks else "（说不出话）"
        mind = " → ".join(
            "「%s」冒出%s" % (t["state"], t["cands"][:2])
            for t in trace[:3]) or "（无）"
        print(f"  网络内心：{mind}")
        print(f"  网络说：「{said}」")

        # 打分（一致性×自然度）
        got = teacher_once(lesson, trace, toks) if has_llm else None
        if got is None:
            cons = sum(1 for t in trace
                       if t["chosen"] in [c for c, _ in t["cands"]]
                       ) / max(len(trace), 1) * 10
            nat = 7.0 if any(w in expect for w in toks) else 2.0
            got = {"cons": cons, "nat": nat,
                   "fb": "（规则回退反馈）", "demo": "跟老师说："}
        score = got["cons"] * got["nat"]

        # 反馈四档
        if score >= 80:
            n_encourage += 1
            for _ in range(3):
                _learn_sentence(ng, expect, pats, slot=0)
            print(f"  评分：{got['cons']:.0f}×{got['nat']:.0f}={score:.0f}"
                  f" ✅ 说得对！")
            print(f"  教师：「{got['fb']}」（奖励固化 ×3）")
        elif score >= 60:
            n_demo += 1
            for _ in range(2):
                _learn_sentence(ng, expect, pats, slot=0)
            print(f"  评分：{got['cons']:.0f}×{got['nat']:.0f}={score:.0f}"
                  f" 🟡 意思对，可以更自然")
            print(f"  教师：「{got['fb']}」")
            print(f"  示范：「{got['demo']}」（跟读 ×2）")
        elif score >= 40:
            n_demo += 1
            for _ in range(2):
                _learn_sentence(ng, expect, pats, slot=0)
            print(f"  评分：{got['cons']:.0f}×{got['nat']:.0f}={score:.0f}"
                  f" 🟠 表达和心里不太一致")
            print(f"  教师：「{got['fb']}」")
            print(f"  示范：「{got['demo']}」（跟读 ×2）")
        else:
            n_punish += 1
            n_dec = penalize_drift(ng, pats, toks, expect)
            for _ in range(2):
                _learn_sentence(ng, expect, pats, slot=0)
            print(f"  评分：{got['cons']:.0f}×{got['nat']:.0f}={score:.0f}"
                  f" 🔴 心里想的和说的不一致！")
            print(f"  教师：「{got['fb']}」")
            print(f"  [处罚] 漂移边降权 ×0.5（{n_dec} 条边——说错了别"
                  f"老说）")
            print(f"  [注入] 正确表达「{'/'.join(expect)}」跟读 ×2")
        print()

    print(f"═══ 教学日统计 ═══")
    print(f"  鼓励奖励 {n_encourage} · 示范引导 {n_demo} · 处罚+注入 "
          f"{n_punish}")
    print(f"  刺激源：内在时钟（持续运行）+ LLM 教师（说和引导）——"
          f"唯二")

    save_snapshot(ng, parent="31.0",
                  tag="LLM 教师系统：备课→说引导→观察心理→一致性×自然"
                      "度打分→鼓励奖励/示范/处罚+注入（5 课）",
                  metrics={"encourage": n_encourage, "demo": n_demo,
                           "punish": n_punish},
                  vocab=vocab, pats=pats, cursor=cursor)
    print(f"[完成] v32.0 已存（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
