# -*- coding: utf-8 -*-
"""诊断：E2「叫哥哥」wta_k=4 时 妈妈↔爸爸 10 拍振荡——查互驱环边。"""
import numpy as np
from schema_net import build_pulse
from snapshot import load_snapshot

ng, vocab, pats, cursor = load_snapshot("runs/v54_2_20260811_190419")

WORDS = ["叫", "爸爸", "妈妈", "哥哥", "妹妹"]
print("== 词级出边（>0.1）==")
for w in WORDS:
    rows = []
    for i in pats[w]:
        for j, wt in ng.W_out[i][0].items():
            jw = next((x for x, ns in pats.items() if int(j) in ns), f"#{j}")
            rows.append((jw, wt))
    # 按目标词聚合
    agg = {}
    for jw, wt in rows:
        agg[jw] = agg.get(jw, 0.0) + wt
    out = {k: round(v, 2) for k, v in agg.items() if v > 0.1}
    print(f"  {w}: {out}")

print("\n== 词级入边（>0.1）==")
for w in WORDS:
    agg = {}
    for wi in pats[w]:
        for i in range(ng.n):
            ww = ng.W_out[i][0].get(wi, 0.0)
            if ww > 0.1:
                sw = next((x for x, ns in pats.items() if i in ns), f"#{i}")
                agg[sw] = agg.get(sw, 0.0) + ww
    print(f"  {w} <- { {k: round(v, 2) for k, v in agg.items()} }")

# 哥哥场景逐拍 v 轨迹
print("\n== 「叫 哥哥」wta_k=4 逐拍 ==")
ng.v = np.zeros((ng.n, ng.slots)); ng.spikes = np.zeros(ng.n); ng.pre_trace = np.zeros(ng.n)
ng.learn_gate = False; ng.wta_k = 4
n2w = {int(x): w for w, ns in pats.items() for x in ns}
for step, (seq, amp) in enumerate([(["叫"], [1.0]), (["哥哥"], [4.0]), ([], []), ([], [])]):
    ng.step(build_pulse(ng.n, pats[seq[0]], amp[0]) if seq else np.zeros(ng.n), slot=0)
    fired = sorted({n2w.get(int(x), f"#{x}") for x in np.where(ng.spikes > 0)[0]})
    vbaba = ng.v[np.array(pats["爸爸"]), 0]
    vmama = ng.v[np.array(pats["妈妈"]), 0]
    print(f"  拍{step}: 发放={fired}  爸爸v={vbaba} 妈妈v={vmama}")
