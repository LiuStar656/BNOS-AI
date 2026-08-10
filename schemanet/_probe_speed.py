# -*- coding: utf-8 -*-
"""探针实验：训练/推理速度随训练语句量的对照基准（优化前基线测量）。

设计（用户 2026-08-10：用快照试试，变量用训练的语句量来做对照）：
  - 快照 v13.0 上，自变量 = 训练语句量 N
  - N ∈ [10, 20, 50, 100, 200]（词对教学，每句 N_ROUNDS=10 轮，与 128 并发实验对齐）
  - 每个 N 在干净快照上重载（隔离累积效应，只测"语句量"这一个变量）
  - 测：
      训练吞吐：N 句学习总耗时 → 每教学次秒数（核心：随 N 平线=固定开销瓶颈，
                爬升=随边数/结构退化的瓶颈）
      推理吞吐：学习后 N 次唤起耗时 → 毫秒/次（learn_gate 关闭 = 纯检索）
  - 顺带记录边数增长（基线/学后/新增）——解释退化归因：传播随边数变宽、
    weight_decay O(n×slots) 固定 → 两者的合成曲线
  - 输出表格 + 保存 runs/_speed_bench.json（后续画图用）

用法：python -u _probe_speed.py [version=13.0]
"""
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
from schema_net import _learn_sentence, _evoke_prefix
from snapshot import load_version

VERSION = "13.0"
N_ROUNDS = 10          # 与 _probe_boundary 对齐
SEED = 42
N_LIST = [10, 20, 50, 100, 200]   # 训练语句量自变量


def count_edges(ng):
    """稀疏网络非零边总数（O(n×slots) 遍历，一次性可接受）。"""
    total = 0
    for i in range(ng.n):
        for k in range(ng.slots):
            row = ng.W_out[i][k]
            if row:
                total += len(row)
    return total


def evoke_sec(ng, pats, pairs, slot=0, steps=3):
    """N 次唤起耗时：每对词注入首词回响 steps 步，learn_gate 关闭（纯检索）。"""
    saved = ng.learn_gate
    ng.learn_gate = False        # 冻结态：只测推理，不学
    t0 = time.perf_counter()
    for x, y in pairs:
        _evoke_prefix(ng, [x], pats, slot=slot, steps=steps)
    dt = time.perf_counter() - t0
    ng.learn_gate = saved
    return dt / max(len(pairs), 1)


def run_case(version, pairs, n):
    """在干净快照上学习 n 句（×N_ROUNDS 轮），返回速度指标 + 边数。"""
    ng, vocab, pats, cursor = load_version(version)
    t_load = time.perf_counter()
    nnz0 = count_edges(ng)
    t0 = time.perf_counter()
    for x, y in pairs[:n]:
        for _ in range(N_ROUNDS):
            _learn_sentence(ng, [x, y], pats, slot=0)
    learn_sec = time.perf_counter() - t0
    nnz1 = count_edges(ng)
    ev = evoke_sec(ng, pats, pairs[:n])
    return {"n": n, "n_teach": n * N_ROUNDS,
            "learn_sec": round(learn_sec, 2),
            "sec_per_teach": round(learn_sec / (n * N_ROUNDS), 4),
            "evoke_ms": round(ev * 1000, 2),
            "nnz_before": nnz0, "nnz_after": nnz1,
            "nnz_delta": nnz1 - nnz0,
            "load_sec": round(time.perf_counter() - t_load, 2)}


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else VERSION
    ng0, vocab, pats, cursor = load_version(version)
    print(f"[加载] v{version}：n={ng0.n}，模式 {len(pats)}，基线边数 {count_edges(ng0)}")

    # ── 候选词对：随机采样 + 基线弱边过滤（与 _probe_boundary 同款）──
    max_g = max(N_LIST)
    rng = np.random.default_rng(SEED)
    words = [w for w in pats.keys()]
    rng.shuffle(words)
    pairs = []
    for i in range(0, len(words) - 1, 2):
        if len(pairs) >= max_g:
            break
        x, y = words[i], words[i + 1]
        fired = _evoke_prefix(ng0, [x], pats, slot=0, steps=3)
        fwd = sum(1 for j in pats[y] if j in fired) / max(len(pats[y]), 1)
        fired = _evoke_prefix(ng0, [y], pats, slot=0, steps=3)
        rev = sum(1 for j in pats[x] if j in fired) / max(len(pats[x]), 1)
        if fwd < 0.3 and rev < 0.3:
            pairs.append((x, y))
    print(f"[词对] 筛选出 {len(pairs)} 组初始不相关词对（基线唤起 < 0.3）")
    del ng0

    out = {"version": version, "n_rounds": N_ROUNDS,
           "n_list": N_LIST, "cases": {}}
    print("\n═══ 速度基准：训练语句量 N → 训练/推理速度 ═══")
    print(f"{'N句':>4} {'教学次':>6} {'学习总秒':>8} {'每教学秒':>9} "
          f"{'唤起毫秒/次':>10} {'基线边':>9} {'学后边':>9} {'新增边':>8}")
    for n in N_LIST:
        res = run_case(version, pairs, n)
        out["cases"][str(n)] = res
        print(f"{n:>4} {res['n_teach']:>6} {res['learn_sec']:>8.1f} "
              f"{res['sec_per_teach']:>9.4f} {res['evoke_ms']:>10.2f} "
              f"{res['nnz_before']:>9} {res['nnz_after']:>9} {res['nnz_delta']:>8}")

    # ── 判读：每教学秒随 N 的斜率（固定开销 vs 随结构退化）──
    cs = out["cases"]
    ys = [cs[str(n)]["sec_per_teach"] for n in N_LIST]
    slope = (ys[-1] - ys[0]) / (N_LIST[-1] - N_LIST[0])      # 秒/句 增量
    growth = (ys[-1] / ys[0] - 1) * 100 if ys[0] else 0.0    # 相对退化 %
    out["verdict"] = {
        "每教学秒[最小N→最大N]": [ys[0], ys[-1]],
        "随N退化幅度": f"{growth:.1f}%",
        "每句新增耗时斜率": f"{slope:.5f}s/句",
        "判读": ("固定开销主导（weight_decay O(n×slots)/Hebbian O(k²) 是瓶颈，"
                 "与边数关系弱 → 优化应打 Python 循环）"
                 if growth < 20 else
                 "随结构退化（边数增长推宽传播 → 优化应打传播批量/多核）"),
    }
    print("\n═══ 判读 ═══")
    for k, v in out["verdict"].items():
        print(f"  {k}: {v}")

    fp = Path(__file__).parent / "runs" / "_speed_bench.json"
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[保存] {fp}")


if __name__ == "__main__":
    main()
