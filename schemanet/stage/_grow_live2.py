# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""心理活动透明化 + LLM 质量评估 + 质量驱动奖励（2026-08-10 用户：
"从自闭症和眼瞎的角度出发，只能听和说，然后用大模型评估表达，目前
能不能看到网络的真实心理活动？如果能的话从心理活动和表达一致性以及
表达的自然程度打分，分越高奖励越高的方式引导网络正确表达"）。

架构（网络=盲人自闭症儿童，只能听和说）：
  ① 自由运行（持续刺激 → 自发表达，_grow_live 机制）
  ② 心理活动采集：free_read trace——每步候选 top-3 + 选择
     （网络"心里冒出"的词 = 完全可观测——定式网络透明性优势）
  ③ LLM 评估（只能听和说）：输入 = 听到的表达 + 网络内心独白
     （心理轨迹）→ 两个维度打分：
      一致性：心里想的和说出的贴不贴（想的是吃饭，说出猫睡觉 = 漂移）
      自然度：像不像人话（语法/语义/连贯）
  ④ 质量驱动奖励：总分 → _learn_sentence 轮数（高质高奖、低质不固
     化——漂移表达不焊死；LLM 无 key 回退规则评分）

用法：python _grow_live2.py [--smoke]
"""

import json
import sys
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version
from _grow_v11 import _load_key, _llm_chat

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"

# 表达场景（内感受 + 时间事件，各自的心理-表达期望）
SCENES = [
    ("饿", "你感到饿了（饥饿感积累到阈值）",
     {"吃", "饭"}, ["我", "饿", "了", "就", "吃", "饭"]),
    ("早上", "天亮了，早上到了（昼夜节律时刻）",
     {"起", "起床"}, ["早上", "起床"]),
    ("冷", "你感到冷了（冷感积累到阈值）",
     {"穿", "衣服"}, ["冷", "了", "就", "穿", "衣服"]),
]


def rule_score(trace, toks, expect):
    """规则回退评分（无 LLM key）：一致性 = 每步选择 ∈ 该步候选
    top-3（心里想的和说的一致）；自然度 = 链相邻对 ∈ 教学链比例。"""
    n_cons = sum(1 for t in trace if t["chosen"] in
                 [c for c, _ in t["cands"]]) if trace else 0
    consistency = n_cons / max(len(trace), 1)
    hit = sum(1 for w in toks if w in expect) if expect else 0
    natural = hit / max(len(toks), 1)
    return consistency * 10, natural * 10, "规则回退"


def llm_eval(stimulus, trace, toks):
    """LLM 评估（只能听和说）：一致性 + 自然度双维度 10 分制。"""
    mind = " → ".join(
        f"想到「{t['state']}」，心里冒出 {t['cands']}，"
        f"选了「{t['chosen']}」" for t in trace) or "（无）"
    said = "".join(toks) or "（说不出话）"
    q = (f"你是一个只能听和说的语言评估者（面对一个自闭症儿童，"
         f"它没有视觉，只能听和说）。\n"
         f"情境：{stimulus}\n"
         f"孩子开口前的内心活动（完全可观测的心理轨迹）：{mind}\n"
         f"孩子说出口的话：「{said}」\n"
         f"请从两个维度打分（0-10）：\n"
         f"【一致性】孩子说出口的话和它心里想的贴不贴？（想的是吃饭，"
         f"说出猫睡觉 = 不一致/漂移，低分；想的和说的一致 = 高分）\n"
         f"【自然度】说出口的话像不像人话？（语法正确、语义合理、连贯"
         f"自然 = 高分；重复循环、答非所问 = 低分）\n"
         f"【一句话评语】像真人老师一样一句话点评（≤25 字）")
    txt = _llm_chat([{"role": "user", "content": q}])
    if not txt:
        return None
    out = {"cons": None, "nat": None, "note": ""}
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("【一致性】"):
            out["cons"] = float("".join(c for c in line if c.isdigit()
                                        or c == ".")[:3] or 0)
        elif line.startswith("【自然度】"):
            out["nat"] = float("".join(c for c in line if c.isdigit()
                                       or c == ".")[:3] or 0)
        elif line.startswith("【一句话评语】"):
            out["note"] = line.replace("【一句话评语】", "").strip()
    if out["cons"] is None or out["nat"] is None:
        return None
    return out


def main():
    from _exam_free import FUNC, free_read, build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool
    from _grow_cat import build_cats

    smoke = "--smoke" in sys.argv
    has_llm = bool(_load_key())
    t0 = time.time()
    print("═══ 心理活动透明化 + LLM 质量评估 + 质量驱动奖励 ═══\n")
    print(f"教师：{'LLM 评估' if has_llm else '规则回退评估'}\n")

    ng, vocab, pats, cursor = load_version("29.2")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)

    sc = SCENES[:1] if smoke else SCENES
    total_r = 0
    for kw, stimulus, accept, expect in sc:
        # ① 自发表达 + 心理活动采集
        trace = []
        read = free_read(ng, pats, n2w, [kw], domain,
                         teach_out=teach_out, trace=trace)
        toks = [x.split("(")[0] for x in read]

        print(f"── 情境：{stimulus} ──")
        print(f"  网络内心活动（每步心里冒出什么）：")
        for t in trace[:6]:
            print(f"    「{t['state']}」→ 心里冒出 {t['cands']}"
                  f" → 选了「{t['chosen']}」")
        print(f"  网络说出口：「{'/'.join(toks) or '（说不出话）'}」")

        # ③ LLM / 规则评估（只能听和说）
        if has_llm:
            got = llm_eval(stimulus, trace, toks)
        else:
            got = None
        if got is None:
            cons, nat, src = rule_score(trace, toks, expect)
            got = {"cons": cons, "nat": nat, "note": "（规则回退评分）"}
        score = got["cons"] * got["nat"]               # 一致性×自然度（门槛×高度）
        print(f"  [评估·{('LLM' if has_llm else '规则')}]"
              f" 一致性 {got['cons']:.1f}/10 · 自然度 {got['nat']:.1f}/10"
              f" → 总分 {score:.1f}/100 {got['note']}")

        # ④ 质量驱动奖励：分越高奖励越高
        if score >= 80:
            r = 3
            tag = "高奖励固化（自然+一致——优质表达焊进网络）"
        elif score >= 60:
            r = 1
            tag = "低奖励（尚可——轻固化）"
        else:
            r = 0
            tag = "不奖励（漂移/不自然——不焊死，避免污染）"
        for _ in range(r):
            _learn_sentence(ng, expect, pats, slot=0)
        total_r += r
        print(f"  [奖励] 跟读期望表达 ×{r}（{tag}）\n")

    print(f"═══ 本轮结果 ═══")
    print(f"  总奖励注入：{total_r} 轮（质量驱动：高质高奖、低质不固化）")
    print(f"  心理活动可见性：每步候选/选择完全可观测"
          f"（定式网络透明性——对比黑盒 LLM 的不可解释）")


if __name__ == "__main__":
    main()
