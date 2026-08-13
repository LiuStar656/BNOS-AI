# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""自发 sleep 实验：网络自己的能力（weight_decay + Hebbian 补偿）——2026-08-11

用户："sleep 应该是网络自己的能力，而不是代码的能力——能让网络自己学会吗？"

机制（网络自身的动力学——非外部函数）：
  weight_decay：每步全边 ×(1-decay)——自然衰减（网络参数）
  Hebbian 补偿：活跃边（发放对）被强化——对抗衰减
  → 用进废退：活跃边保持、不活跃边自然弱化——自发压缩
  → 睡眠 = 无输入运行（自发活动/重放）——活跃回路被保持、弱边衰减

对照：
  外部 sleep_compress（代码遍历降权——之前）vs 自发 sleep（动力学）

测量：
  ① 自发压缩率（睡眠 N tick 后弱边衰减——边数/权重变化）
  ② 定式保持（活跃边——教学过的——Hebbian 补偿保持）
  ③ 能力（睡眠后泛化——等价？）
  ④ 睡眠多次（多夜——压缩渐进——能力保持？）

用法：python _exp_sleep_self.py（纯内存）
"""

import json
import time
from pathlib import Path

from snapshot import load_version, load_consolidated
from _exam_free import free_read, build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats
from _grow_v16 import edge_between

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"

Q10 = [("饿", "确认"), ("渴", "确认"), ("累", "确认"), ("困", "确认"),
       ("冷", "确认"), ("穿", "确认"), ("饿", "怎么办"), ("渴", "怎么办"),
       ("累", "怎么办"), ("冷", "怎么办")]


def q10(ng, pats, n2w, domain, teach_out, cons, val):
    ok = 0
    for kw, ctx in Q10:
        read = free_read(ng, pats, n2w, [kw], domain, teach_out=teach_out,
                         consolidated=cons, validation=val, ctx=ctx)
        toks = [x.split("(")[0] for x in read]
        out = []
        for w in toks:
            if w.startswith("[") or w in out:
                break
            out.append(w)
        ok += bool(out)
    return ok


def main():
    t0 = time.time()
    print("═══ 自发 sleep（网络自己的能力——weight_decay + Hebbian 补偿）═══\n")
    print("（纯内存——不保存快照）\n")
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))

    ng, vocab, pats, cursor = load_version("35.0")
    cons, val = load_consolidated("35.0")
    ng.w_max = 64.0
    ng.weight_decay = 0.002          # 开启自发衰减（网络参数——每步 ×0.998）
    n2w = {j: w for w, ns in pats.items() for j in ns}
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)

    e0 = sum(len(ng.W_out[i][0]) for i in range(ng.n))
    s0 = sum(1 for i in range(ng.n)
             for w in ng.W_out[i][0].values() if w >= 1.0)
    ok0 = q10(ng, pats, n2w, domain, teach_out, cons, val)
    strong_e = edge_between(ng, pats, "饿", "了")     # 教学定式边
    weak_e = edge_between(ng, pats, "疼", "帮")        # 旧边（未教学强化）
    print(f"[白天] 边 {e0:,} | 活跃 {s0:,} | 泛化 {ok0}/10")
    print(f"  定式边：饿→了={strong_e:g}  旧边：疼→帮={weak_e:g}")

    # ── 夜间睡眠：无输入自发运行（网络自发活动）──
    print(f"\n[夜间] 无输入自发运行（weight_decay 0.002/步——用进废退）：")
    import numpy as np
    for night in range(1, 4):
        for _ in range(1000):        # 每夜 1000 tick 自发活动
            ng.spikes = np.zeros(ng.n)
            ng.step(np.zeros(ng.n), slot=0)
        e = sum(len(ng.W_out[i][0]) for i in range(ng.n))
        s = sum(1 for i in range(ng.n)
                for w in ng.W_out[i][0].values() if w >= 1.0)
        se = edge_between(ng, pats, "饿", "了")
        we = edge_between(ng, pats, "疼", "帮")
        ok = q10(ng, pats, n2w, domain, teach_out, cons, val)
        print(f"  夜{night}后：边 {e:,} | 活跃 {s:,} | "
              f"定式 饿→了={se:g} | 旧边 疼→帮={we:g} | 泛化 {ok}/10")

    # ── 结论 ──
    e1 = sum(len(ng.W_out[i][0]) for i in range(ng.n))
    s1 = sum(1 for i in range(ng.n)
             for w in ng.W_out[i][0].values() if w >= 1.0)
    ok1 = q10(ng, pats, n2w, domain, teach_out, cons, val)
    se1 = edge_between(ng, pats, "饿", "了")
    we1 = edge_between(ng, pats, "疼", "帮")
    print(f"\n═══ 结论 ═══")
    print(f"  自发压缩：活跃边 {s0:,} → {s1:,}"
          f"（{'✅ 弱边自然衰减' if s1 < s0 else '⚠️ 未压缩'}）")
    print(f"  定式保持：饿→了 {strong_e:g} → {se1:g}"
          f"（{'✅ Hebbian 补偿（活跃回路自持）' if se1 >= strong_e*0.8 else '⚠️ 定式也衰减'}）")
    print(f"  旧边变化：疼→帮 {weak_e:g} → {we1:g}"
          f"（{'✅ 非活跃自然衰减（用进废退）' if we1 < weak_e else '⚠️ 未衰减'}）")
    print(f"  能力：泛化 {ok0}/10 → {ok1}/10"
          f"（{'✅ 睡眠后保持' if ok0 == ok1 else '⚠️ 变化'}）")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
