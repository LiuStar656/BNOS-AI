# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""治疗一 v2：知识进边——cons 固化句 → 共享定式（2026-08-11）。

v1 教训：STDP 教学 ×5（≈0.5 权重）竞争不过旧边；且"触发词→句首"
在前向链上结构性不可达（触发词在句中——回溯需要逆向联想——治疗二）。
正确路径：consolidate_sentence（shared 定式）= 模板的边化——
每句建定式进模型（ng.skeletons 注册 + 槽位主干边）——模型"会走"
整句，不再是代码查模板。

验证：裸 read_skeleton 从句首词读——治前（只有守一定式）vs 治后。

用法：python stage/_treat_knowledge_to_edges.py [--save]
"""
import json
import sys
import time
from pathlib import Path

from snapshot import load_version, load_consolidated, save_snapshot
from schema_net import consolidate_sentence, read_skeleton

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
VER = "40.1"


def main():
    t0 = time.time()
    save = "--save" in sys.argv
    ng, vocab, pats, cursor = load_version(VER)
    cons, val = load_consolidated(VER)
    n2w = {j: w for w, ns in pats.items() for j in ns}

    targets = []
    for kw, cands in cons.items():
        for toks, slots, ctype in cands:
            if toks:
                targets.append((kw, toks, ctype))

    print(f"═══ 治疗一 v2：cons → 共享定式（模板边化）═══")
    print(f"加载 v{VER} | 固化句 {len(targets)} 句\n")

    def sk_read(seed):
        out = read_skeleton(ng, pats, n2w, seed,
                            skeletons=getattr(ng, "skeletons", None))
        return "/".join(out) if out else "（无定式）"

    print(f"{'触发词':<6}{'句子':<14}{'治前定式读出':<20}{'治后定式读出':<20}")
    print("─" * 66)
    fixed = 0
    n_sk_before = len(ng.skeletons or {})
    for kw, toks, ctype in targets:
        head = toks[0]
        before = sk_read(head)
        # 治疗：建共享定式（模板边化——主干/槽位/绑定全进模型）
        slots, cursor = consolidate_sentence(ng, pats, cursor, toks,
                                             k=4, w=64.0, shared=True)
        after = sk_read(head)
        mark = ""
        if after != "（无定式）" and after != before:
            fixed += 1
            mark = "✓新定式"
        elif after == before and before != "（无定式）":
            mark = "（共享合并）"
        print(f"{kw:<6}{''.join(toks):<14}{before:<20}{after:<20}{mark}")

    n_sk_after = len(ng.skeletons or {})
    print("─" * 66)
    print(f"定式表：{n_sk_before} → {n_sk_after} 个"
          f"（模型层真结构——剥离代码层后裸读可见）")
    print(f"（触发词→句首的桥 = 逆向联想——归治疗二）")

    if save:
        out = save_snapshot(ng, parent=VER,
            tag=f"治疗一v2：cons→共享定式（{n_sk_before}→{n_sk_after} 定式——模板边化）",
            vocab=vocab, pats=pats, cursor=cursor,
            consolidated=cons, validation=val,
            metrics={"treat1": {"sk_before": n_sk_before,
                                "sk_after": n_sk_after}})
        print(f"\n[保存] {out}")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
