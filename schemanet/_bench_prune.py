# -*- coding: utf-8 -*-
"""剪枝前后性能基准（2026-08-11）：加载/推理/读边/评估/内存对比。

用法：python _bench_prune.py（纯内存——不保存快照）
"""
import json
import time
import gc
from pathlib import Path

from snapshot import load_version, load_consolidated
from _exam_free import free_read, build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats
from _grow_v16 import direct_next_multi, edge_between

DATA = Path(__file__).parent / "data" / "curriculum"


def bench(fn, n=100):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return sum(ts) / n * 1000   # ms


def main():
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))

    results = {}
    for phase in ["剪枝前", "剪枝后"]:
        print(f"═══ {phase} ═══")
        # 加载
        t0 = time.perf_counter()
        ng, vocab, pats, cursor = load_version("34.0")
        cons, val = load_consolidated("34.0")
        t_load = time.perf_counter() - t0
        n2w = {j: w for w, ns in pats.items() for j in ns}
        cats = build_cats(pats, sem["words"], 12, 3)
        q_pool = qa_build_pool(rows, cats)
        domain = build_domain(ng, pats, rows, q_pool)
        teach_out = build_teach_out(rows, q_pool)
        # 边数
        n_edge = sum(len(ng.W_out[i][0]) for i in range(ng.n))
        print(f"  加载: {t_load*1000:.0f} ms | 边: {n_edge:,}")

        # free_read（泛化 20 题全流程）
        t0 = time.perf_counter()
        for kw, ctx in [("饿","确认"),("渴","确认"),("累","确认"),
                        ("困","确认"),("冷","确认"),("穿","确认"),
                        ("饿","怎么办"),("渴","怎么办"),("累","怎么办"),
                        ("冷","怎么办")]:
            free_read(ng, pats, n2w, [kw], domain, teach_out=teach_out,
                      consolidated=cons, validation=val, ctx=ctx)
        t_read = (time.perf_counter() - t0) / 10 * 1000
        print(f"  free_read 单次: {t_read:.2f} ms")

        # direct_next_multi
        kw = "饿"
        d = bench(lambda: direct_next_multi(ng, pats, n2w, [kw], k=8,
                                            domain=set(pats.keys())), 50)
        print(f"  direct_next_multi: {d:.3f} ms")

        # edge_between
        e = bench(lambda: edge_between(ng, pats, "饿", "吃"), 200)
        print(f"  edge_between: {e:.3f} ms")

        # 内存（粗略——边存储）
        mem = n_edge * 12 / 1e6
        print(f"  边存储: {mem:.0f} MB")
        results[phase] = {"load_ms": t_load*1000, "edge": n_edge,
                          "read_ms": t_read, "next_ms": d,
                          "edge_ms": e, "mem_mb": mem}
        if phase == "剪枝前":
            ng.sleep_consolidate(min_wake=5, decay=0.3, eps=1.0)
            del ng, cons, val, n2w, cats, q_pool, domain, teach_out
            gc.collect()
            print("  [剪枝] sleep eps=1.0 执行\n")

    a, b = results["剪枝前"], results["剪枝后"]
    print("═══ 对比 ═══")
    print(f"  加载: {a['load_ms']:.0f} → {b['load_ms']:.0f} ms"
          f"（{b['load_ms']/a['load_ms']*100:.0f}%）")
    print(f"  free_read: {a['read_ms']:.2f} → {b['read_ms']:.2f} ms"
          f"（{b['read_ms']/a['read_ms']*100:.0f}%）")
    print(f"  direct_next: {a['next_ms']:.3f} → {b['next_ms']:.3f} ms"
          f"（{b['next_ms']/a['next_ms']*100:.0f}%）")
    print(f"  edge_between: {a['edge_ms']:.3f} → {b['edge_ms']:.3f} ms"
          f"（{b['edge_ms']/a['edge_ms']*100:.0f}%）")
    print(f"  边存储: {a['mem_mb']:.0f} → {b['mem_mb']:.0f} MB"
          f"（{b['mem_mb']/a['mem_mb']*100:.0f}%）")


if __name__ == "__main__":
    main()
