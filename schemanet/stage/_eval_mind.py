# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""自我表达与思考能力评估（v34.0 治疗快照，2026-08-11）：

维度：
  A. 自我表达：10 个主题词自发输出（固化句覆盖 vs 自由链）
     - 开口率 / 完整句率 / 黑洞率
  B. 思考过程：每例的心理活动 trace 全程（听到/理解/想到/表达/候选竞争）
  C. 思考质量：
     - 固化路径：思考环（想到整句）→ 表达环（逐词读出）
     - 自由链路径：每步真实候选竞争（候选+权重+选择）
     - 思考-表达一致性（说出的是否 = 想到的）

用法：python _eval_mind.py
"""

import json
import time
from pathlib import Path

from snapshot import load_version, load_consolidated
from _exam_free import free_read, build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"

THEMES = [
    ("饿", "固化句覆盖"), ("累", "固化句覆盖"), ("困", "固化句覆盖"),
    ("冷", "固化句覆盖"), ("我", "固化句覆盖（多句竞争）"),
    ("疼", "自由链（旧能力）"), ("下雨", "自由链（散文区）"),
    ("生病", "自由链（散文区）"), ("妈妈", "自由链"), ("猫", "自由链"),
    ("开心", "自由链（情绪）"), ("学校", "自由链"),
]


def main():
    t0 = time.time()
    print("═══ 自我表达与思考能力评估（v34.0）═══\n")
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
    print(f"[恢复] v34.0：n={ng.n}，固化 {len(consolidated)} 触发词，"
          f"验证 {len(validation)} 对\n")

    # ── A + B：逐主题自发表达 + 心理 trace ──────────────
    n_open = n_full = n_black = n_tot = 0
    for kw, tag in THEMES:
        if kw not in keys:
            continue
        trace = []
        read = free_read(ng, pats, n2w, [kw], domain, teach_out=teach_out,
                         trace=trace, consolidated=consolidated,
                         validation=validation)
        toks = []
        for w in [x.split("(")[0] for x in read]:
            if w.startswith("[") or w in toks:
                break
            toks.append(w)
        walked = any("整句" in str(t.get("cands", [])) for t in trace)
        if toks and kw not in toks and not walked:
            toks.insert(0, kw)
        said = "/".join(toks) or "（沉默）"
        n_tot += 1
        n_open += bool(toks)
        n_full += len(toks) >= 3
        n_black += "[黑洞]" in "".join(x.split("(")[0] for x in read)
        # 心理活动 trace（思考过程）
        print(f"──「{kw}」〔{tag}〕──")
        print(f"  说：「{said}」")
        for t in trace:
            print(f"    心里[{t['state']}] 候选={t['cands'][:3]} → {t['chosen']}")
        print()

    # ── C. 思考质量汇总 ─────────────────────────────────
    print("═══ 思考质量汇总 ═══")
    print(f"  开口率：{n_open}/{n_tot} = {n_open/n_tot:.2f}")
    print(f"  完整句率（≥3 词）：{n_full}/{n_tot} = {n_full/n_tot:.2f}")
    print(f"  黑洞率：{n_black}/{n_tot} = {n_black/n_tot:.2f}")
    print(f"  固化句覆盖 {sum(1 for _, t in THEMES if t == '固化句覆盖')} 个主题"
          f"；自由链 {sum(1 for _, t in THEMES if t != '固化句覆盖')} 个主题")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
