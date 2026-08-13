# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""黑洞治疗 + 50% 边压缩对照实验（2026-08-11）。

用户要求：
  ① 诊断治疗黑洞——诊断结论：教学域内 0 黑洞；黑洞结构残留 =
     X↔「的」类双向强边回声环（11.2 双向——候选全回环 → [黑洞]）
  ② 边总体压缩 50% 对照——学过的和没学过的差距减少后，能力下降没有

四组对照（v35.0 独立加载 ×4）：
  A 原始（现状）
  B 治疗（双向回声环 ×0.3——黑洞结构压缩）
  C 压缩 50%（全部边 ×0.5——学过的/没学过的差距等比减半）
  D 治疗 + 压缩 50%

能力指标：
  ① 教学域 178 词 free_read 链长均值 / [黑洞] 率 / [循环] 率
  ② 固化句读出（consolidated——不走边，应不受影响）
  ③ 自由链漂移度（链是否越走越长进散文残留）

用法：python _exp_cure_blackhole.py（纯内存——不保存快照）
"""

import json
import time
from pathlib import Path

from snapshot import load_version, load_consolidated
from _exam_free import build_domain, build_teach_out, free_read
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
ECHO_THRESH = 8.0        # 双向环判定阈值
ECHO_FACTOR = 0.3        # 回声环压缩因子


def cure_echo_rings(ng, pats, n2w):
    """治疗黑洞：双向强边回声环（A↔B 都 ≥阈值）压缩 ×0.3——
    回声环是黑洞结构（候选全回环 → 链截断）；单向强边（学过的
    正确链）不动。"""
    n = 0
    for a in list(pats):
        ra = ng.W_out[pats[a][0]][0]
        for j, v in list(ra.items()):
            if v < ECHO_THRESH or j not in n2w:
                continue
            b = n2w[j]
            if b not in pats:
                continue
            rb = ng.W_out[pats[b][0]][0].get(pats[a][0], 0)
            if rb >= ECHO_THRESH:
                for i in pats[a]:
                    row = ng.W_out[i][0]
                    if j in row:
                        row[j] *= ECHO_FACTOR
                for i in pats[b]:
                    row = ng.W_out[i][0]
                    if pats[a][0] in row:
                        row[pats[a][0]] *= ECHO_FACTOR
                n += 1
    return n


def shrink_all(ng, factor=0.5):
    """边总体压缩：全部非零边 ×factor（学过的/没学过的差距等比减半）。"""
    n = 0
    for i in range(ng.n):
        row = ng.W_out[i][0]
        for j in list(row.keys()):
            row[j] *= factor
            n += 1
    return n


def build(version="35.0"):
    ng, vocab, pats, cursor = load_version(version)
    n2w = {j: w for w, ns in pats.items() for j in ns}
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)
    cons, val = load_consolidated("34.0")
    return ng, pats, n2w, domain, teach_out, cons


def assess(ng, pats, n2w, domain, teach_out, cons):
    """能力评估：域内链长/黑洞率/循环率 + 固化句读出。"""
    lens, black, loop = [], 0, 0
    for w in sorted(domain):
        read = free_read(ng, pats, n2w, [w], domain, teach_out=teach_out,
                         consolidated=cons)
        toks = [x.split("(")[0] for x in read]
        lens.append(len(toks))
        if "[黑洞]" in toks:
            black += 1
        if "[循环]" in toks:
            loop += 1
    # 固化句读出（不走边——能力应不变）
    cons_ok = 0
    for kw, items in cons.items():
        if kw not in pats:
            continue
        read = free_read(ng, pats, n2w, [kw], domain, teach_out=teach_out,
                         consolidated=cons)
        toks = [x.split("(")[0] for x in read]
        if toks and "[" not in toks[0]:
            cons_ok += 1
    return (sum(lens) / len(lens), black, loop, cons_ok, len(cons))


def main():
    t0 = time.time()
    print("═══ 黑洞治疗 + 50% 边压缩对照实验（v35.0 ×4 组）═══\n")
    groups = {}
    for name in ["A 原始", "B 治疗", "C 压缩50%", "D 治疗+压缩50%"]:
        ng, pats, n2w, domain, teach_out, cons = build()
        if "B" in name or "D" in name:
            n_ring = cure_echo_rings(ng, pats, n2w)
        if "C" in name or "D" in name:
            n_shrink = shrink_all(ng, 0.5)
        groups[name] = assess(ng, pats, n2w, domain, teach_out, cons)
        extra = ""
        if "B" in name or "D" in name:
            extra += f" 治疗回声环 {n_ring} 对"
        if "C" in name or "D" in name:
            extra += f" 压缩 {n_shrink} 条边"
        avg, black, loop, cons_ok, n_cons = groups[name]
        print(f"  {name}: 链长 {avg:.2f} | 黑洞 {black} | 循环 {loop} | "
              f"固化句读出 {cons_ok}/{n_cons}{extra}")
    print(f"\n[结论] 黑洞结构（双向回声环）已定位并治疗；等比压缩 50%"
          f"不改变候选排序（学过的仍是 top）——能力是否下降见链长/"
          f"固化句读出对照。")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
