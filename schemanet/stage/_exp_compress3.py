# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""受控压缩实验：外部控制 sleep 范围（压多少权重以下的弱边）——2026-08-11

用户："这个压缩能不能被外部来控制范围？比如说 sleep 多少权重以下的弱边"

受控压缩（外部参数）：
  sleep_below：压缩阈值（只压权重 < 此值的边——强边永不压）
  factor：压缩强度（×0.5——弱边降权）
  定式保护：强边（≥sleep_below）不动——固化句主干天然保护

扫描：sleep_below = 1/10/50/200
  ① 压缩范围（多少边被压/强边保留数）
  ② 定式保护（饿→了 632——各阈值下是否保持）
  ③ 旧边（疼→帮 77——阈值 100 时被压——77<100）
  ④ 能力（泛化等价）
对比：自发版（无差别——定式 632→1.6——失败）vs 受控版

用法：python _exp_compress3.py（纯内存）
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


def compress_below(ng, sleep_below, factor=0.5):
    """受控压缩：只压权重 < sleep_below 的边（强边保护）。"""
    n_comp = 0
    for i in range(ng.n):
        row = ng.W_out[i][0]
        for j, w in list(row.items()):
            if w < sleep_below:
                row[j] = w * factor
                n_comp += 1
    return n_comp


def main():
    t0 = time.time()
    print("═══ 受控压缩（外部控制 sleep 范围）═══\n")
    print("（纯内存——不保存快照）\n")
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))

    print(f"  {'阈值':<8}{'压缩边数':<10}{'饿→了(632)':<12}"
          f"{'疼→帮(77)':<12}{'泛化':<8}{'判定'}")
    for sleep_below in [1, 10, 50, 100, 200, 500]:
        ng, vocab, pats, cursor = load_version("35.0")
        cons, val = load_consolidated("35.0")
        ng.w_max = 64.0
        n2w = {j: w for w, ns in pats.items() for j in ns}
        cats = build_cats(pats, sem["words"], 12, 3)
        q_pool = qa_build_pool(rows, cats)
        domain = build_domain(ng, pats, rows, q_pool)
        teach_out = build_teach_out(rows, q_pool)
        e_before = edge_between(ng, pats, "饿", "了")
        t_before = edge_between(ng, pats, "疼", "帮")
        n = compress_below(ng, sleep_below)
        e_after = edge_between(ng, pats, "饿", "了")
        t_after = edge_between(ng, pats, "疼", "帮")
        ok = q10(ng, pats, n2w, domain, teach_out, cons, val)
        protect = "✅ 定式保" if e_after == e_before else "⚠️ 定式损"
        print(f"  {sleep_below:<8}{n:<10}{e_after:<12.1f}"
              f"{t_after:<12.1f}{ok}/10    {protect}")

    print(f"\n═══ 结论 ═══")
    print(f"  外部控制 ✓：sleep_below 决定压缩范围"
          f"（压 <阈值 的弱边——强边保护）")
    print(f"  定式保护：饿→了 632——所有阈值下保持（≥阈值不压）")
    print(f"  可调粒度：阈值 1=只压幽灵 / 50=压中弱边 / 500=压大多数")
    print(f"  对比自发版：无差别衰减（定式 632→1.6 失败）→ 受控版保护")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
