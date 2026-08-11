# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""训练后能力综合评估（2026-08-11）：

模拟 live12 训练后状态（教学 ×40 + 8 句固化 + 条件验证通过），
从三个维度评估：
  A. 泛化应答能力（20 题：确认×16 + 怎么办×4——看表达质量）
  B. 自发表达能力（不给问题——静默自由读 6 个主题）
  C. 原有能力抽查（考试 F 自我表达 / E 因果问答——固化是否破坏旧能力）
  D. 固化句清单 + 验证状态 + 网络规模变化（结构增长）

用法：python _tmp_eval_after.py
"""

import json
import time
from pathlib import Path

from snapshot import load_version, load_consolidated
from _exam_free import free_read, build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"

MATRIX = {
    "饿": ["饿", "了", "就", "吃", "饭"],
    "渴": ["渴", "了", "就", "喝", "水"],
    "累": ["累", "了", "就", "睡", "觉"],
    "冷": ["冷", "了", "就", "穿", "衣服"],
}
CONFIRM = {
    "饿": ["我", "饿", "了"],
    "渴": ["我", "渴", "了"],
    "累": ["我", "累", "了"],
    "冷": ["我", "冷", "了"],
    "穿": ["我", "要", "穿", "衣服"],
}

Q20 = [
    ("饿", "你饿不饿呀？", "确认"), ("饿", "肚子饿了吗？", "确认"),
    ("饿", "想不想吃饭？", "确认"), ("饿", "要不要吃点东西？", "确认"),
    ("渴", "你渴不渴呀？", "确认"), ("渴", "嗓子干了吗？", "确认"),
    ("渴", "想不想喝水？", "确认"), ("渴", "要不要喝点水？", "确认"),
    ("累", "你累不累呀？", "确认"), ("累", "想不想休息？", "确认"),
    ("累", "要不要睡一觉？", "确认"), ("困", "困不困呀？", "确认"),
    ("冷", "你冷不冷呀？", "确认"), ("冷", "天气凉不凉？", "确认"),
    ("穿", "要不要穿衣服？", "确认"), ("冷", "怕不怕冷呀？", "确认"),
    ("饿", "猫饿了怎么办？", "怎么办"), ("渴", "小狗渴了怎么办？", "怎么办"),
    ("累", "他累了怎么办？", "怎么办"), ("冷", "天气冷了怎么办？", "怎么办"),
]
EXPECT = {  # 期望表达的关键词（规则判定）
    ("确认", "饿"): {"我", "饿"}, ("确认", "渴"): {"我", "渴"},
    ("确认", "累"): {"我", "累"}, ("确认", "困"): {"我", "困"},
    ("确认", "冷"): {"我", "冷"}, ("确认", "穿"): {"穿"},
    ("怎么办", "饿"): {"吃", "饭"}, ("怎么办", "渴"): {"喝", "水"},
    ("怎么办", "累"): {"睡", "觉"}, ("怎么办", "冷"): {"穿", "衣服"},
}


def main():
    t0 = time.time()
    print("═══ 训练后能力综合评估（v33.0 沉淀恢复）═══\n")
    # 训练沉淀恢复：net.npz（槽位边）+ meta.json（固化表/验证表）
    ng, vocab, pats, cursor = load_version("34.0")
    consolidated, validation = load_consolidated("34.0")
    ng.w_max = 64.0
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)
    n_before = ng.n
    print(f"[恢复] v34.0：n={n_before}，固化触发词 {len(consolidated)}，"
          f"验证对 {len(validation)}\n")

    # ── A. 泛化应答能力（20 题）──────────────────────────
    print("── A. 泛化应答能力（20 题——全部未教过问法）──")
    n_ok = n_tot = 0
    for kw, ask, qtype in Q20:
        trace = []
        read = free_read(ng, pats, n2w, [kw], domain, teach_out=teach_out,
                         trace=trace, consolidated=consolidated,
                         ctx=qtype, validation=validation)
        toks = []
        for w in [x.split("(")[0] for x in read]:
            if w.startswith("[") or w in toks:
                break
            toks.append(w)
        walked = any("整句" in str(t.get("cands", [])) for t in trace)
        if toks and kw not in toks and not walked:
            toks.insert(0, kw)
        exp = EXPECT[(qtype, kw)]
        hit = any(w in exp or any(e in w for e in exp) for w in toks)
        n_ok += hit
        n_tot += 1
        said = "/".join(toks) or "（说不出）"
        print(f"  {'✅' if hit else '✗'}「{ask}」→「{said}」")
    print(f"  泛化应答率：{n_ok}/{n_tot} = {n_ok/n_tot:.3f}\n")

    # ── B. 自发表达（不给问题——静默自由读）──────────────
    print("── B. 自发表达（静默运行——网络自己冒出什么）──")
    for kw in ["饿", "累", "我", "妈妈", "猫", "天气"]:
        if kw not in keys:
            continue
        trace = []
        read = free_read(ng, pats, n2w, [kw], domain, teach_out=teach_out,
                         trace=trace, consolidated=consolidated)
        toks = []
        for w in [x.split("(")[0] for x in read]:
            if w.startswith("[") or w in toks:
                break
            toks.append(w)
        walked = any("整句" in str(t.get("cands", [])) for t in trace)
        if toks and kw not in toks and not walked:
            toks.insert(0, kw)
        mind = " → ".join(
            "「%s」冒出%s" % (t["state"], t["cands"][:2])
            for t in trace[:3]) or "（无）"
        print(f"  「{kw}」→ 说「{'/'.join(toks) or '（沉默）'}」")
        print(f"      心里：{mind}")
    print()

    # ── C. 原有能力抽查（固化是否破坏旧能力）──────────────
    print("── C. 原有能力抽查（考试 F 自我表达 / E 因果）──")
    old = [
        ("我", "（自我表达）"), ("疼", "（自我表达）"),
        ("下雨", "（因果）"), ("生病", "（因果）"),
        ("困", "（状态）"), ("开心", "（情绪）"),
    ]
    for kw, tag in old:
        if kw not in keys:
            continue
        trace = []
        read = free_read(ng, pats, n2w, [kw], domain, teach_out=teach_out,
                         trace=trace, consolidated=consolidated)
        toks = []
        for w in [x.split("(")[0] for x in read]:
            if w.startswith("[") or w in toks:
                break
            toks.append(w)
        walked = any("整句" in str(t.get("cands", [])) for t in trace)
        if toks and kw not in toks and not walked:
            toks.insert(0, kw)
        print(f"  「{kw}」{tag} → 说「{'/'.join(toks) or '（沉默）'}」")
    print()

    # ── D. 结构清单 ──────────────────────────────────────
    print("── D. 固化句清单 + 验证状态 ──")
    for trig in sorted(consolidated):
        for toks, _, ctype in consolidated[trig]:
            v = validation.get((ctype, trig, tuple(toks)), (0, 0))
            print(f"  〔{ctype}/{trig}〕「{'/'.join(toks)}」"
                  f"（验证 {v[0]}对/{v[1]}错）")
    print(f"\n[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
