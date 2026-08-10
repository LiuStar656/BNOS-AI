# -*- coding: utf-8 -*-
"""探针实验：并发学习压力测试——找并发量边界（崩溃拐点）。

设计：
  - 并发量 G ∈ [1,2,4,8,16,32,64]：同一学习期交替学习 G 组不相关词对
  - 所有组同一槽 slot=0（剥离槽位隔离，测纯并发拥挤的机制容量）
  - 每组 10 轮教学（_learn_sentence 教学式）
  - 每组在"干净快照 v13.0"上重载（隔离并发量效应，不做累积）
  - 崩溃判定：唤起成功率 < 50%（定式保真度断崖）或激活规模爆炸（超临界迹象）
  - 副实验：槽位轮转（组 mod 4 分槽）对比——槽位隔离能推多远
"""
import sys
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import psutil
from schema_net import build_pulse, _learn_sentence, _evoke_prefix
from snapshot import load_version

MAX_G = 128
N_ROUNDS = 10
SUCCESS_THRESHOLD = 0.5          # 单组唤起 ≥ 0.5 视为成功
VERSION = "13.0"
SEED = 42
CROSS_SAMPLE = 8
MAX_WORKERS = 8


def rss_mb():
    return psutil.Process().memory_info().rss / 1024 / 1024


def ratio(fired, neurons):
    if not neurons:
        return 0.0
    return sum(1 for j in neurons if j in fired) / len(neurons)


def evoke_ratio(ng, pats, x, y, slot=0):
    fired = _evoke_prefix(ng, [x], pats, slot=slot, steps=3)
    return round(ratio(fired, pats[y]), 3)


def fire_count(ng, pats, x, slot=0, steps=4):
    """注入 x 后回响 steps 步，累计发放神经元总数（激活规模）。"""
    ng.v = np.zeros_like(ng.v)
    ng.spikes = np.zeros(ng.n, dtype=np.float64)
    ng.step(build_pulse(ng.n, pats[x]), slot=slot)
    total = int((ng.spikes > 0).sum())
    for _ in range(steps):
        ng.step(np.zeros(ng.n), slot=slot)
        total += int((ng.spikes > 0).sum())
    return total


def run_case(version, pairs, slot_fn=None, rounds=N_ROUNDS, cross_sample=8):
    """在干净快照上学习 G 组，返回指标 + 耗时 + 内存。slot_fn(i) 给第 i 组的槽位。
    cross_sample：串扰测量抽样数（O(G×k) 替代 O(G²)）。"""
    t0 = time.perf_counter()
    rss0 = rss_mb()
    ng, vocab, pats, cursor = load_version(version)
    rss_loaded = rss_mb()
    if slot_fn is None:
        slot_fn = lambda i: 0
    for i, (x, y) in enumerate(pairs):
        for _ in range(rounds):
            _learn_sentence(ng, [x, y], pats, slot=slot_fn(i))
    t_learn = time.perf_counter() - t0
    rss_learned = rss_mb()
    succ, evokes, cross, scales = 0, [], [], []
    rng2 = np.random.default_rng(SEED + len(pairs))
    for i, (x, y) in enumerate(pairs):
        s = slot_fn(i)
        e = evoke_ratio(ng, pats, x, y, slot=s)
        evokes.append(e)
        succ += 1 if e >= SUCCESS_THRESHOLD else 0
        # 串扰：抽样 cross_sample 个其他组测量（O(G×k)）
        others = [j for j in range(len(pairs)) if j != i]
        if len(others) > cross_sample:
            others = list(rng2.choice(others, cross_sample, replace=False))
        worst = 0.0
        for j in others:
            a, b = pairs[j]
            c1 = evoke_ratio(ng, pats, x, b, slot=s)
            c2 = evoke_ratio(ng, pats, x, a, slot=s)
            worst = max(worst, c1, c2)
        cross.append(worst)
        scales.append(fire_count(ng, pats, x, slot=s))
    return {"success": succ, "n": len(pairs),
            "success_rate": round(succ / len(pairs), 3),
            "mean_evoke": round(float(np.mean(evokes)), 3),
            "median_evoke": round(float(np.median(evokes)), 3),
            "max_cross": round(float(np.max(cross)), 3),
            "mean_scale": round(float(np.mean(scales)), 1),
            "max_scale": int(np.max(scales)),
            "learn_sec": round(t_learn, 2),
            "total_sec": round(time.perf_counter() - t0, 2),
            "rss_loaded_mb": round(rss_loaded, 0),
            "rss_learned_mb": round(rss_learned, 0),
            "rss_delta_mb": round(rss_learned - rss0, 0)}


def run_task(args):
    """进程池任务：version, pairs, G, mode → (G, mode, res)。"""
    version, pairs, G, mode = args
    slot_fn = (lambda i: i % 4) if mode == "rotated" else None
    res = run_case(version, pairs[:G], slot_fn=slot_fn,
                   rounds=N_ROUNDS, cross_sample=CROSS_SAMPLE)
    return G, mode, res


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else VERSION
    ng0, vocab, pats, cursor = load_version(version)
    print(f"[加载] v{version}：n={ng0.n}，模式 {len(pats)}，cursor={cursor}")

    # ── 候选词对：随机采样 + 基线弱边过滤（X→Y 与 Y→X 都弱）──
    max_g = MAX_G
    rng = np.random.default_rng(SEED)
    words = [w for w in pats.keys()]
    rng.shuffle(words)
    pairs, seen = [], set()
    for i in range(0, len(words) - 1, 2):
        x, y = words[i], words[i + 1]
        if len(pairs) >= max_g:
            break
        fwd = evoke_ratio(ng0, pats, x, y)
        rev = evoke_ratio(ng0, pats, y, x)
        if fwd < 0.3 and rev < 0.3:     # 初始不相关
            pairs.append((x, y))
    print(f"[词对] 筛选出 {len(pairs)} 组初始不相关词对（基线唤起 < 0.3）")
    if len(pairs) < max_g:
        print(f"[警告] 候选不足：仅 {len(pairs)} 组，MAX_G 降到 {len(pairs)}")
        max_g = len(pairs)

    out = {"version": version, "n_rounds": N_ROUNDS,
           "success_threshold": SUCCESS_THRESHOLD,
           "pairs": [[a, b] for a, b in pairs]}
    g_list = [1, 2, 4, 8, 16, 32, 64, 128]
    g_list = [g for g in g_list if g <= max_g]
    rot_list = [g for g in g_list if g >= 4]

    tasks = ([(G, "same_slot") for G in g_list]
             + [(G, "rotated") for G in rot_list])
    t0 = time.perf_counter()
    fp = Path(__file__).parent / "runs" / "_concurrent_boundary.json"
    fp.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n[多进程] 启动 {min(MAX_WORKERS, len(tasks))} workers，共 {len(tasks)} 个并发点（边算边保存）...")
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(run_task, (version, pairs, G, mode)): (G, mode)
                for G, mode in tasks}
        done = 0
        for fut in futs:
            G, mode, res = fut.result()
            out.setdefault(mode, {})[G] = res
            done += 1
            fp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  ✓ G={G} {mode} 完成（{done}/{len(tasks)}），耗时 {time.perf_counter()-t0:.0f}s")
    print(f"[多进程] 全部完成，总耗时 {time.perf_counter() - t0:.0f}s")

    same = out["same_slot"]
    rot = out.get("rotated", {})

    print("\n═══ 并发量扫描（同槽 slot=0，纯并发拥挤）═══")
    print(f"{'G':>3} {'成功率':>7} {'均唤起':>7} {'最大串扰':>8} {'均激活':>7} "
          f"{'学习秒':>7} {'总秒':>6} {'RSS加载':>7} {'RSS增量':>7}")
    for G in g_list:
        res = same[G]
        print(f"{G:>3} {res['success_rate']:>7.2f} {res['mean_evoke']:>7.2f} "
              f"{res['max_cross']:>8.2f} {res['mean_scale']:>7.1f} "
              f"{res['learn_sec']:>7.1f} {res['total_sec']:>6.1f} "
              f"{res['rss_loaded_mb']:>7.0f} {res['rss_delta_mb']:>7.0f}")

    print("\n═══ 槽位轮转副实验（组 mod 4 → 4 槽，模拟多任务）═══")
    print(f"{'G':>3} {'成功率':>7} {'均唤起':>7} {'最大串扰':>8} {'学习秒':>7} {'RSS增量':>7}")
    for G in rot_list:
        res = rot[G]
        print(f"{G:>3} {res['success_rate']:>7.2f} {res['mean_evoke']:>7.2f} "
              f"{res['max_cross']:>8.2f} {res['learn_sec']:>7.1f} {res['rss_delta_mb']:>7.0f}")

    # ── 崩溃点判定（同槽主实验）──
    rates = {G: out["same_slot"][G]["success_rate"] for G in g_list}
    crash = [G for G, r in rates.items() if r < SUCCESS_THRESHOLD]
    out["verdict"] = {
        "各G成功率": rates,
        "崩溃点(成功率<0.5)": (crash[0] if crash else "未达"),
        "崩溃前最大G": (crash[0] // 2 if crash else max(rates)),
        "激活规模是否爆炸": {G: out["same_slot"][G]["max_scale"] for G in g_list},
    }

    print("\n═══ 判读 ═══")
    for k, v in out["verdict"].items():
        print(f"  {k}: {v}")

    fp = Path(__file__).parent / "runs" / "_concurrent_boundary.json"
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[保存] {fp}")


if __name__ == "__main__":
    main()
