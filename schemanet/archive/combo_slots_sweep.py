# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""combo 对照实验：变量 = 神经元内部槽数量（13 → 8192），并行运行。

对照组 = 13 槽（combo 所需最小槽数：原子 0/1/2 + 排列共享 3 + 组合 4..12），
实验组逐级放大。同一实验内容（先学 abc 原子 → 再学组合序列），唯一变量是槽数。

指标：原子保留（atom_after）/ 排列一致性 / 组合纯度 / 覆盖次数（evictions）/
有值槽数（slot_total_used，观测大槽下是否有闲置空间被误用）。

留档：每个配置独立目录 runs/YYYYMMDD_HHMMSS_slots{slots}/，汇总表额外存
runs/YYYYMMDD_HHMMSS_slots_summary.json，禁止覆盖历史数据。
"""
import json
import os
import time
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

from schema_net import CONFIG, run_combo_experiment

BASE = Path(__file__).resolve().parent.parent

# 尽可能大：基线 13 槽 → 每档翻倍 → 8192（每进程 W≈64MB，10 进程并行）
SLOTS_LIST = [13, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192]


def _run_one(args):
    slots, run_stamp = args
    t0 = time.time()
    cfg = dict(CONFIG)
    cfg["slots"] = slots          # 唯一变量：神经元内部槽数量
    r = run_combo_experiment(cfg)
    perm_sets = [tuple(v) for v in r["perm_response"].values()]
    summary = {
        "slots": slots,
        "n": cfg["n"],
        "slot_cap": cfg.get("slot_cap"),
        "weight_decay": cfg.get("weight_decay"),
        "noise_amp": cfg.get("noise_amp"),
        "atom_after": r["atom_after"],
        "perm_consistent": len(set(perm_sets)) == 1,
        "perm_response": r["perm_response"],
        "evictions": r["evictions"],
        "purity_cover": r["purity_cover"],
        "purity_in": r["purity_in"],
        "slot_total_used": sum(1 for t in r["slot_totals"] if t > 0),
        "slot_total_sum": round(sum(r["slot_totals"]), 1),
        "elapsed_s": round(time.time() - t0, 1),
    }
    # 独立留档（并行进程共享 run_stamp，靠 _slots{slots} 区分目录）
    run_dir = BASE / "runs" / f"{run_stamp}_slots{slots}"
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "full": r}, f, ensure_ascii=False,
                  indent=2, default=float)
    return summary


if __name__ == "__main__":
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    n_proc = min(len(SLOTS_LIST), os.cpu_count() or 4)
    print(f"combo 槽数量对照实验  n=32  并行 {n_proc} 进程")
    print(f"槽序列: {SLOTS_LIST}")
    print("=" * 66)

    t_start = time.time()
    with Pool(n_proc) as pool:
        results = pool.map(_run_one, [(s, run_stamp) for s in SLOTS_LIST])

    print(f"\n{'槽数':<7}{'原子保留(a/b/c)':<20}{'排列一致':<8}{'挤掉':<6}"
          f"{'有值槽':<7}{'用时s':<7}")
    print("-" * 66)
    for s in results:
        aa = "/".join(f"{v:.2f}" for v in s["atom_after"].values())
        print(f"{s['slots']:<7}{aa:<22}{'是' if s['perm_consistent'] else '否':<8}"
              f"{s['evictions']:<6}{s['slot_total_used']:<7}{s['elapsed_s']:<7}")

    # 汇总留档
    summary_dir = BASE / "runs" / f"{run_stamp}_slots_summary.json"
    with open(summary_dir, "w", encoding="utf-8") as f:
        json.dump({"stamp": run_stamp, "slots_list": SLOTS_LIST,
                   "results": results,
                   "total_elapsed_s": round(time.time() - t_start, 1)},
                  f, ensure_ascii=False, indent=2)
    print(f"\n总计 {round(time.time() - t_start, 1)}s，汇总留档: {summary_dir}")
