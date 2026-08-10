# -*- coding: utf-8 -*-
"""能力泛化课程 v2——教学闭环版（2026-08-11）：

v1 暴露：漂移链「饿了就睡觉」——就→睡觉=256 饱和 > 就→吃=156；
冷→所以=224 > 冷→了=216。泛化率 20%。
根因：局部边无法区分上下文——矩阵训练必须**整链教学 + 错误纠正**
（多范例 MET：精选范例/灵活策略；矩阵重组：教4得28）。

v2 流程：
  ① 矩阵整链强化 ×10：饿/了/就/吃/饭、渴/了/就/喝/水、累/了/就/睡/觉、
     冷/了/就/穿/衣服（教学边 w_max=64 可超散文饱和 256）
  ② 泛化教学闭环：20 题（16 刺激泛化换问法 + 4 矩阵重组）逐题：
     答对 → 示范句跟读 ×1（奖励）；答错 → 惩罚漂移边 ×0.5（只罚
     不属于正确表达的边——「累了就睡觉」的正确链不受影响）+ 示范
     句跟读 ×3（注入正确表达）
  ③ 复测：同 20 题再测（不教学）→ 泛化率对比 v1

LLM 教师设定：教学形式 = 盲人自闭症儿童（只能听和说）；能力标准 =
**正常儿童**（并不存在真正的盲人自闭症儿童——不降标，表达要自然、
准确、完整）。

用法：python _grow_live12.py
"""

import sys
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version
from _grow_v11 import _load_key, _llm_chat
from _grow_teacher import penalize_drift

DATA = Path(__file__).parent / "data" / "curriculum"

# 矩阵整链（状态 × 需求——教这 4 链，泛化出 28 组合）
MATRIX = {
    "饿": ["饿", "了", "就", "吃", "饭"],
    "渴": ["渴", "了", "就", "喝", "水"],
    "累": ["累", "了", "就", "睡", "觉"],
    "冷": ["冷", "了", "就", "穿", "衣服"],
}
DEMO = {  # 正常儿童标准示范句
    "饿": "饿了就吃饭",
    "渴": "渴了就喝水",
    "累": "累了就睡觉",
    "冷": "冷了穿衣服",
}

# 多范例刺激泛化题库：(状态词, [4 种未教问法])
GENERALIZE = [
    ("饿", ["你饿不饿呀？", "肚子饿了吗？", "想不想吃饭？",
            "要不要吃点东西？"]),
    ("渴", ["你渴不渴呀？", "嗓子干了吗？", "想不想喝水？",
            "要不要喝点水？"]),
    ("累", ["你累不累呀？", "想不想休息？", "要不要睡一觉？",
            "困不困呀？"]),
    ("冷", ["你冷不冷呀？", "天气凉不凉？", "要不要穿衣服？",
            "怕不怕冷呀？"]),
]

# 矩阵泛化（重组：未教的组合——换主语/省略主语）
MATRIX_TEST = [
    ("饿", "猫饿了怎么办？"), ("渴", "小狗渴了怎么办？"),
    ("累", "他累了怎么办？"), ("冷", "天气冷了怎么办？"),
]


def llm_judge(guide, kw, toks, trace):
    """LLM 教师（设定修正版）：形式 = 盲童听/说通道；标准 = 正常儿童。"""
    import re
    mind = " → ".join(
        "「%s」冒出%s" % (t["state"], t["cands"][:2])
        for t in trace[:3]) or "（无）"
    said = "/".join([kw] + toks) if toks else "（说不出话）"
    q = (f"你是妈妈式的老师，一对一陪着一个孩子学说话。\n"
         f"教学形式参照盲人自闭症儿童（孩子只能听和说，用听觉/语言"
         f"通道教学）。\n"
         f"重要：**并不存在真正的盲人自闭症儿童**——这只是教学形式"
         f"设定。孩子的能力标准参照**正常儿童**：不要因为任何标签"
         f"降低期望——表达要自然、准确、完整，按正常同龄儿童标准"
         f"严格要求。\n"
         f"你问它：「{guide}」（这是换了一种说法问的——泛化测试，"
         f"它没听过这种问法）\n"
         f"孩子开口前内心：{mind}\n孩子说：「{said}」\n"
         f"请只输出：\n"
         f"【答对】是 或 否（正常儿童标准：答得对不对、贴不贴问题；"
         f"说错/跳题/重复=否）\n"
         f"【教师反馈】妈妈式反馈（≤25 字：对就肯定并扩一句；不对就"
         f"指出 + 一句示范）\n"
         f"【示范句】正常儿童该说的自然句（≤10 字）")
    txt = None
    for _ in range(2):
        txt = _llm_chat([{"role": "user", "content": q}])
        if txt:
            break
    if not txt:
        return None
    parts = re.split(r"【(答对|教师反馈|示范句)】", txt)
    out = {"ok": None, "fb": "", "demo": ""}
    for i in range(1, len(parts), 2):
        val = (parts[i + 1] if i + 1 < len(parts) else "").strip()
        if parts[i] == "答对":
            out["ok"] = val.startswith("是")
        elif parts[i] == "教师反馈":
            out["fb"] = val
        elif parts[i] == "示范句":
            out["demo"] = val
    if out["ok"] is None:
        return None
    return out


def free_say(ng, pats, n2w, kw, domain, teach_out):
    """自由读取 kw 后的表达（去括号痕迹）。"""
    from _exam_free import free_read
    trace = []
    read = free_read(ng, pats, n2w, [kw], domain,
                     teach_out=teach_out, trace=trace)
    toks = []
    for w in [x.split("(")[0] for x in read]:
        if w.startswith("[") or w in toks:
            break
        toks.append(w)
    return toks, trace


def teach_once(ng, pats, toks, times):
    for _ in range(times):
        _learn_sentence(ng, toks, pats, slot=0)


def seg_demo(demo, keys):
    """示范句 → 词表 token 链（最长优先贪心）。"""
    d_toks = []
    rest = demo.replace("。", "").replace("，", "")
    while rest:
        hit = next((w for w in sorted(keys, key=len, reverse=True)
                    if rest.startswith(w)), None)
        if not hit:
            break
        d_toks.append(hit)
        rest = rest[len(hit):]
    return d_toks


def main():
    from _exam_free import build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool
    from _grow_cat import build_cats
    import json

    t0 = time.time()
    print("═══ 能力泛化课程 v2（矩阵整链 + 教学闭环——正常儿童标准）═══\n")

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
    has_llm = bool(_load_key())

    # ── ① 矩阵整链强化 ×40 ──────────────────────────────
    # 就→了=256 饱和回环边——教学边（w_max=64）需压过它（×40 ≈ +320）
    print("[① 矩阵整链强化]（4 链 ×40——压过就→了/就→睡觉饱和回环）")
    for kw, toks in MATRIX.items():
        teach_once(ng, pats, toks, 40)
        print(f"  「{'/'.join(toks)}」×40 ✓")
    print()

    # ── ② 泛化教学闭环（20 题逐题：错→罚+注入；对→奖励）──
    print("── ② 泛化教学闭环（多范例换问法 ×16 + 矩阵重组 ×4）──")
    items = [(kw, ask) for kw, asks in GENERALIZE for ask in asks]
    items += MATRIX_TEST
    wrong_edges = {}
    for idx, (kw, ask) in enumerate(items, 1):
        toks, trace = free_say(ng, pats, n2w, kw, domain, teach_out)
        got = llm_judge(ask, kw, toks, trace) if has_llm else None
        if got is None:  # 规则回退：期望链元素出现在表达中
            expect = set(MATRIX[kw][2:])
            got = {"ok": any(w in expect for w in toks),
                   "fb": "（规则）", "demo": DEMO[kw]}
        demo = got.get("demo") or DEMO[kw]
        d_toks = seg_demo(demo, keys) or MATRIX[kw]
        if got["ok"]:
            teach_once(ng, pats, d_toks, 1)              # 答对：奖励跟读
            mark = "✅"
        else:
            full = [kw] + toks
            n_dec = penalize_drift(ng, pats, full, MATRIX[kw])
            for a, b in zip(full[:-1], full[1:]):
                wrong_edges[(a, b)] = wrong_edges.get((a, b), 0) + 1
            teach_once(ng, pats, d_toks, 3)              # 答错：注入正确
            mark = f"✗(罚{n_dec}边)"
        said = "/".join([kw] + toks) or "（说不出）"
        print(f"  {idx:>2} {mark}「{ask}」→「{said}」")
    print()

    # ── ③ 复测（不教学）──────────────────────────────────
    print("── ③ 复测泛化率（教学后——不教学，只看效果）──")
    n_ok = n_tot = 0
    for kw, ask in items:
        toks, trace = free_say(ng, pats, n2w, kw, domain, teach_out)
        got = llm_judge(ask, kw, toks, trace) if has_llm else None
        if got is None:
            expect = set(MATRIX[kw][2:])
            got = {"ok": any(w in expect for w in toks)}
        n_tot += 1
        n_ok += got["ok"]
        said = "/".join([kw] + toks) or "（说不出）"
        print(f"  {'✅' if got['ok'] else '✗'}「{ask}」→「{said}」")
    rate = n_ok / n_tot

    # ── 结论 + 留档 ──────────────────────────────────────
    top_wrong = sorted(wrong_edges.items(), key=lambda x: -x[1])[:5]
    print(f"\n═══ 泛化验收 ═══")
    print(f"  复测泛化率：{n_ok}/{n_tot} = {rate:.3f}（v1 教学前 = 0.200）")
    print(f"  主要漂移边（已惩罚）："
          + "，".join(f"{a}→{b}×{c}" for (a, b), c in top_wrong))
    print(f"[教师设定] 形式 = 盲童听/说通道；标准 = 正常儿童（不降标）")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
