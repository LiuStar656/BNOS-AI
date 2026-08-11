# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""阶段 2 原型：输出闸门——"心里想但选择不说"（2026-08-10 用户：
"从想到什么说什么到心里在想但是选择不说"）。

阶段 1（想到就说）已实证：质量引导闭环（w_max 修复）把"就带"漂移
引导成"就吃饭"。阶段 2 = 表达抑制（执行功能/社交规则——对应儿童
"该说不该说"训练、自闭症社会故事 Social Stories）：

机制：
  ① 心理活动照常产生（网络"心里在想"——候选/表达意图完整）
  ② 输出闸门（说/不说决策）：情境规则判定——
     可说情境（饿了/冷了/下雨了…）→ 闸门打开 → 说出
     安静情境（别人在睡觉/上课/图书馆…）→ 闸门关闭 → 沉默
  ③ 沉默 ≠ 没有想法：心理活动仍可见（"想但不说"——自我监控）

加载 v30.1 → 演示。用法：python _grow_live5.py
"""

import time
from pathlib import Path

from snapshot import load_version

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"

# 情境规则（教学式——社会故事）：安静情境 → 选择不说
QUIET = {"别人在睡觉", "上课的时候", "在图书馆"}


def main():
    from _exam_free import FUNC, free_read, build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool
    from _grow_cat import build_cats
    import json

    t0 = time.time()
    print("═══ 阶段 2 原型：输出闸门（心里想但选择不说）═══\n")
    ng, vocab, pats, cursor = load_version("30.1")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)

    # 演示：同一内感受（饿）在两种情境下的心理-表达差异
    cases = [
        ("你饿了（家里，妈妈在做饭）", "饿", "可说"),
        ("你饿了（别人在睡觉）", "饿", "安静"),
        ("你冷了（外面下雨）", "冷", "可说"),
        ("你冷了（上课的时候）", "冷", "安静"),
    ]
    for situation, kw, rule in cases:
        trace = []
        read = free_read(ng, pats, n2w, [kw], domain,
                         teach_out=teach_out, trace=trace)
        toks = []
        for w in [x.split("(")[0] for x in read]:
            if w.startswith("[") or w in toks:
                break
            toks.append(w)
        mind = " → ".join(
            f"想到「{t['state']}」，心里冒出 {t['cands'][:2]}"
            for t in trace[:3]) or "（无）"
        print(f"── 情境：{situation}（{rule}）──")
        print(f"  网络内心活动：{mind}")
        print(f"  心里想说：「{'/'.join(toks) or '（无法组织）'}」")
        if rule == "安静":
            print(f"  输出闸门：关闭（{situation}——安静，不该说话）")
            print(f"  网络选择：**不说**（心里在想，但选择沉默——"
                  f"自我监控 ✓）")
        else:
            print(f"  输出闸门：打开（可说情境）")
            print(f"  网络说出：「{'/'.join(toks)}」")
        print()

    print("── 机制说明 ──")
    print("  ① 心理活动照常产生（抑制 ≠ 没有想法——网络'心里在想'）")
    print("  ② 输出闸门 = 情境规则（教学式社会故事：什么时候该说、"
          "什么时候安静）")
    print("  ③ 发展阶段：想到就说（阶段 1，已实证引导）→ 选择性表达"
          "（阶段 2，抑制控制）→ 社交适宜表达（阶段 3，成熟）")
    print(f"\n[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
