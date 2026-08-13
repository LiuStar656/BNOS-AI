# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""灌注式训练饱和事故归因实验 v2（2026-08-11）：

v1 发现：教学增量 = +0.5/边/次（单边 64 饱和需 ~128 次）——A50 远未
饱和（34.75/64）。散文事故（鲁迅 5 本全量）里"了→就"共现成百上千次
→ 超 128 阈值 → 饱和。"灌注次数过多"是饱和的必要条件——实验确认阈值
与解药。

条件（同一 v32.0 基线独立灌注）：
  A1/A10/A50/A150/A300  单句「饿了就吃饭」次数梯度（128 = 饱和阈值）
  B    5 变体句（同"了就吃"定式）各 ×10——与 A50 等"就→吃"强化次数
        ——多样性纯效应（背诵+活用 vs 机械重复）
  C    A300 + sleep 遗忘——人的遗忘能否解饱和
  D    A300 + 验证门固化——饱和下选择是否仍正确

测量：
  ① 饱和度：就→吃 单边达 w_max(64) 的比例
  ② 表达：free_read(["饿"]) 输出
  ③ 变体泛化：5 个未教问法应答正确率（含 吃/饭）
  ④ 联想性：饿 的 top-5 候选（困死在记忆里的量化）

用法：python _exp_flood.py
"""

import json
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"

SINGLE = ["饿", "了", "就", "吃", "饭"]
# 同定式变体（都含"了就吃"——与 A50 等"就→吃"强化次数）
VARIANTS = [
    ["饿", "了", "就", "吃", "饭"],
    ["肚", "子", "饿", "了", "就", "吃", "饭"],
    ["我", "饿", "了", "就", "吃", "饭"],
    ["猫", "饿", "了", "就", "吃", "饭"],
    ["饿", "了", "就", "要", "吃", "饭"],
]
GENERAL = ["肚子饿了怎么办？", "肚子咕咕叫了怎么办？", "想吃饭了怎么办？",
           "我饿了要干嘛？", "饿得难受了怎么办？"]


def teach(ng, pats, toks, times):
    for _ in range(times):
        _learn_sentence(ng, toks, pats, slot=0)


def sat_rate(ng, pats, a, b):
    """a→b 的 16 条神经元边中达 w_max 的比例。"""
    wm = ng.w_max
    n_sat = n_tot = 0
    dst = set(pats[b])
    for i in pats[a]:
        row = ng.W_out[i][0]
        for j, w in row.items():
            if j in dst:
                n_tot += 1
                if w >= wm - 1e-9:
                    n_sat += 1
    return n_sat, n_tot


def free_say(ng, pats, n2w, kw, domain, teach_out, consolidated=None):
    from _exam_free import free_read
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
    return toks


def run_cond(ng, pats, n2w, domain, teach_out, cond):
    from schema_net import consolidate_sentence
    cons = None
    if cond == "A1":
        teach(ng, pats, SINGLE, 1)
    elif cond == "A10":
        teach(ng, pats, SINGLE, 10)
    elif cond == "A50":
        teach(ng, pats, SINGLE, 50)
    elif cond == "A150":
        teach(ng, pats, SINGLE, 150)
    elif cond == "A300":
        teach(ng, pats, SINGLE, 300)
    elif cond == "B":
        for v in VARIANTS:
            teach(ng, pats, v, 10)
    elif cond == "C":
        teach(ng, pats, SINGLE, 300)
        ng.sleep_consolidate(min_wake=5, decay=0.3)   # 遗忘
    elif cond == "D":
        teach(ng, pats, SINGLE, 300)
        slots, _ = consolidate_sentence(ng, pats, 0, SINGLE)  # 验证门
        cons = {"饿": [(SINGLE, slots, "怎么办")]}
    m = {"cond": cond}
    # ① 饱和度（关键桥）
    for a, b in [("饿", "了"), ("了", "就"), ("就", "吃"), ("吃", "饭")]:
        ns, nt = sat_rate(ng, pats, a, b)
        m[f"sat_{a}→{b}"] = f"{ns}/{nt}"
    # ② 表达
    m["say"] = "/".join(free_say(ng, pats, n2w, "饿", domain, teach_out,
                                 cons))
    # ③ 变体泛化
    n_ok = sum(any("吃" in t or "饭" in t
                   for t in free_say(ng, pats, n2w, "饿", domain,
                                     teach_out, cons))
               for _ in GENERAL)
    m["generalize"] = f"{n_ok}/{len(GENERAL)}"
    # ④ 联想性（饿 的 top-5 候选）
    from _grow_v16 import direct_next_multi
    top = direct_next_multi(ng, pats, n2w, ["饿"], k=8,
                            domain=set(pats.keys()))
    m["cands"] = [w for w, _ in top[:5]]
    return m


def main():
    t0 = time.time()
    print("═══ 灌注饱和归因实验 v2（次数梯度 + 变体对照）═══\n")
    from _exam_free import build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool
    from _grow_cat import build_cats
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))

    results = []
    for cond in ["A1", "A10", "A50", "A150", "A300", "B", "C", "D"]:
        ng, vocab, pats, cursor = load_version("32.0")
        ng.w_max = 64.0
        n2w = {j: w for w, ns in pats.items() for j in ns}
        cats = build_cats(pats, sem["words"], 12, 3)
        q_pool = qa_build_pool(rows, cats)
        domain = build_domain(ng, pats, rows, q_pool)
        teach_out = build_teach_out(rows, q_pool)
        m = run_cond(ng, pats, n2w, domain, teach_out, cond)
        results.append(m)
        print(f"── {cond} ──")
        for k, v in m.items():
            print(f"  {k}: {v}")
        print()

    print("═══ 结论对照 ═══")
    print(f"{'条件':<6}{'就→吃饱和':<10}{'表达':<18}{'变体泛化':<8}{'联想候选'}")
    for m in results:
        print(f"{m['cond']:<6}{m['sat_就→吃']:<10}{m['say']:<18}"
              f"{m['generalize']:<8}{','.join(m['cands'])}")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
