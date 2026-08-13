# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""推理性能测量（第六波逐步优化用）：唤起耗时 + 单步构成 + 强边命中率。
用法：python _probe_infer.py [step_tag]  → 结果追加 runs/_infer_bench.json
step_tag 如 "baseline" / "step1_pre_trace" / "step2_fire_idx" ..."""
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from schema_net import _evoke_prefix, build_pulse
from snapshot import load_snapshot, RUNS
import sparse_net as sm

SNAPSHOT = RUNS / "v13_0_20260810_111247" / "net.npz"
TAG = sys.argv[1] if len(sys.argv) > 1 else "baseline"
OUT = Path(__file__).resolve().parent.parent / "runs" / "_infer_bench.json"


def strong_edges(ng, pats, step=997, w_min=8.0):
    n2w = {j: w for w, ns in pats.items() for j in ns}
    edges = []
    for i in range(0, ng.n, step):
        for k in range(ng.slots):
            row = ng.W_out[i][k]
            if not len(row):
                continue
            for j, w in zip(row.dst, row.w):
                if w >= w_min:
                    edges.append((i, k, int(j), float(w)))
    return edges, n2w


def evoke_speed(ng, pats, words, rounds=3, n=20):
    """唤起测速：n 词 × 3 步，多轮取最快（毫秒/次）。"""
    ts = []
    for r in range(rounds):
        t0 = time.perf_counter()
        for w in words[:n]:
            _evoke_prefix(ng, [w], pats, slot=0, steps=3)
        ts.append((time.perf_counter() - t0) / n * 1000)
    return {"min_ms": min(ts), "rounds": [round(x, 2) for x in ts]}


def hit_rate(ng, pats, edges, n2w, steps=3):
    """强边命中率：唤起源词后目标神经元是否激活。"""
    hit = tot = 0
    for i, k, j, w in edges:
        src = n2w.get(i)
        if src is None or src not in pats:
            continue
        ng.v = np.zeros((ng.n, ng.slots)); ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        f = _evoke_prefix(ng, [src], pats, slot=k, steps=steps)
        tot += 1
        if j in f:
            hit += 1
    return {"hit": hit, "tot": tot, "rate": round(hit / tot, 4)}


def step_profile(ng, pats, words, n_steps=20):
    """单步构成分段计时（推理路径，edge_min 场景）。返回 ms/步 各段。"""
    S = {}
    def tk(k):
        S[k] = [S.get(k, [0, 0.0])[0] + 1, S.get(k, [0, 0.0])[1]]
        return time.perf_counter()
    def tc(k, t0): S[k][1] += time.perf_counter() - t0

    def step_t(ng, pulse, slot=0):
        slot = min(slot, ng.slots - 1)
        t = tk("noise")
        raw = ng.rng.random(ng.n)
        sm._update_v(ng.n, ng.slots, ng.v, ng.fat, raw, np.nonzero(pulse)[0],
                     slot, ng.membrane_decay, ng.noise_p, ng.noise_amp,
                     ng.std_dep, ng.std_rec)
        tc("noise", t)
        if ng.spikes.any():
            for k in range(ng.slots):
                t = tk("where")
                senders = np.where((ng.spikes > 0) & (ng.last_k_star == k))[0]
                tc("where", t)
                if len(senders):
                    t = tk("collect")
                    ds, ws = [], []
                    for i in senders:
                        e = ng._edge_row(i, k)
                        if e is not None:
                            ds.append(e[0]); ws.append(e[1])
                    tc("collect", t)
                    if ds:
                        t = tk("prop")
                        all_dst = np.concatenate(ds)
                        all_w = np.concatenate(ws)
                        drive = np.zeros(ng.n)
                        sm._prop_accum(all_dst, all_w, ng.edge_min, drive)
                        tc("prop", t)
                        ng.v[:, k] += drive
        if ng.refract_clear and ng.refractory > 0:
            ng.v[ng.refractory_left > 0] = 0.0
        t = tk("wta")
        n_c = sm._wta_cand(ng.n, ng.slots, ng.v, ng.last_k_star,
                           ng.refractory_left, ng.theta, ng._is_cand,
                           ng._cand_idx, ng._cand_val)
        tc("wta", t)
        candidates = ng._cand_idx[:n_c]
        vmax_c = ng._cand_val[:n_c]
        k_star = ng.last_k_star
        t = tk("topk")
        if len(candidates) > ng.wta_k:
            key = vmax_c * ng.gain[candidates]
            top = candidates[np.argsort(key)[::-1][: ng.wta_k]]
        else:
            top = candidates
        tc("topk", t)
        new_spikes = np.zeros(ng.n)
        if len(top):
            if ng.inh_loose < 1.0 and len(candidates) > len(top):
                mark = np.zeros(ng.n, dtype=bool)
                mark[top] = True
                losers = candidates[~mark[candidates]]
                if len(losers):
                    ng.v[losers, :] *= ng.inh_loose
            new_spikes[top] = 1.0
            if ng.std_dep > 0:
                ng.fat[top] = ng.std_dep
        ng.v[top, :] = 0.0
        ng.spikes = new_spikes
        ng.last_k_star = k_star
        ng.pre_trace = ng.pre_trace * ng.trace_decay + new_spikes
        if ng.refractory > 0:
            ng.refractory_left = np.maximum(ng.refractory_left - 1, 0)
            if len(top):
                ng.refractory_left[top] = ng.refractory
        S.setdefault("_nc", [0, 0.0]); S["_nc"][0] += 1; S["_nc"][1] += n_c

    ng.v = np.zeros((ng.n, ng.slots)); ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)
    for _ in range(3):
        step_t(ng, build_pulse(ng.n, pats[words[0]]))
    for _ in range(n_steps):
        step_t(ng, np.zeros(ng.n))
    n = S["_nc"][0]
    tot = sum(v[1][1] for v in S.items() if not v[0].startswith("_"))
    prof = {k: round(v[1] / v[0] * 1000, 3) for k, v in S.items()
            if not k.startswith("_")}
    prof["_total_ms_step"] = round(tot / n * 1000, 3)
    prof["_cand_avg"] = round(S["_nc"][1] / n, 0)
    return prof


def main():
    ng, vocab, pats, cursor = load_snapshot(SNAPSHOT)
    words = list(pats.keys())
    ng.learn_gate = False
    ng.edge_min = 0.5
    edges, n2w = strong_edges(ng, pats)

    # 预热（numba 编译）
    for _ in range(3):
        _evoke_prefix(ng, [words[0]], pats, slot=0, steps=3)

    rec = {"tag": TAG, "edge_min": ng.edge_min, "ts": time.strftime("%H%M%S"),
           "evoke": evoke_speed(ng, pats, words),
           "hit": hit_rate(ng, pats, edges, n2w),
           "profile": step_profile(ng, pats, words)}
    print(f"[{TAG}] 唤起 {rec['evoke']['min_ms']:.1f}ms/次 | "
          f"命中 {rec['hit']['rate']:.3f} | "
          f"构成 {rec['profile']}")

    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    data[TAG] = rec
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[存] {OUT}")


if __name__ == "__main__":
    main()
