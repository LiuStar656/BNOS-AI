# -*- coding: utf-8 -*-
"""提速改造对拍：numba 版 step vs 参考实现（原逻辑复刻）。

2026-08-10 numba 提速（传播 add.at / Hebbian·STDP _merge_rows / WTA argpartition）
必须保证语义逐位一致——对拍铁律"结构不变≠性能不变"。

做法：
  - load_version("13.0") 两份独立副本（同种子 rng → 同噪声序列）
  - 同一教学序列（20 组词对 × 3 轮）：新网用 step，参考网用 step_ref（原逻辑）
  - 学习后全表逐边对拍（dst/w 完全一致，容差 0）
  - 顺带测速：新 step vs step_ref（原逻辑速度），看提速比

用法：python -u _check_speed_opt.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
from schema_net import _learn_sentence, _evoke_prefix, build_pulse
from snapshot import load_version

VERSION = "13.0"
N_PAIRS = 20
N_ROUNDS = 3
SEED = 7


def step_ref(ng, input_pulse, slot=0):
    """复刻 numba 优化前的 step 逻辑：传播逐行累加 + Hebbian/STDP batch_update。"""
    slot = min(slot, ng.slots - 1)
    noise = (ng.rng.random(ng.n) < ng.noise_p) * ng.noise_amp
    ng.v = ng.v * ng.membrane_decay + noise[:, None]
    ng.v[:, slot] += input_pulse
    if ng.std_dep > 0:
        ng.fat *= ng.std_rec
    if ng.spikes.any():
        for k in range(ng.slots):
            senders = np.where((ng.spikes > 0) & (ng.last_k_star == k))[0]
            if len(senders):
                drive = np.zeros(ng.n)
                for i in senders:
                    e = ng._edge_row(i, k)
                    if e is not None:
                        w = e[1] * (1.0 - ng.fat[i])
                        if ng.edge_min > 0:
                            keep = w >= ng.edge_min
                            if not keep.any():
                                continue
                            drive[e[0][keep]] += w[keep]
                        else:
                            drive[e[0]] += w
                if ng.inh_norm > 0:
                    tot = drive.sum()
                    if tot > ng.inh_norm:
                        drive *= ng.inh_norm / tot
                ng.v[:, k] += drive
    if ng.refract_clear and ng.refractory > 0:
        ng.v[ng.refractory_left > 0] = 0.0
    k_star = ng.v.argmax(axis=1)
    vmax = ng.v[np.arange(ng.n), k_star]
    eligible = np.ones(ng.n, dtype=bool)
    if ng.refractory > 0:
        eligible = ng.refractory_left == 0
    candidates = np.where((vmax >= ng.theta) & eligible)[0]
    if len(candidates) > ng.wta_k:
        key = vmax[candidates] * ng.gain[candidates]
        top = candidates[np.argsort(key)[::-1][: ng.wta_k]]
    else:
        top = candidates
    new_spikes = np.zeros(ng.n)
    if len(top):
        if ng.inh_loose < 1.0 and len(candidates) > len(top):
            losers = np.setdiff1d(candidates, top)
            if len(losers):
                ng.v[losers, :] *= ng.inh_loose
        new_spikes[top] = 1.0
        if ng.std_dep > 0:
            ng.fat[top] = ng.std_dep
        if ng.learn_gate:
            pending = {}
            for a in top:
                ka = int(k_star[a])
                for c in top:
                    if a == c:
                        continue
                    row = ng.W_out[c][ka]
                    nv = row.get(a, 0.0) + ng.eta
                    if nv > ng.w_max:
                        nv = ng.w_max
                    pending.setdefault((c, ka), {})[a] = nv
            for (c, ka), pairs in pending.items():
                ng.W_out[c][ka].batch_update(pairs)
            if (ng.stdp_pre > 0 or ng.stdp_neg > 0) and ng.pre_trace.any():
                pre_idx = np.where(ng.pre_trace > ng.trace_thres)[0]
                if ng.stdp_pre > 0 and len(pre_idx):
                    pending = {}
                    for jj in top:
                        kj = int(k_star[jj])
                        for pp in pre_idx:
                            if jj == pp:
                                continue
                            row = ng.W_out[pp][kj]
                            nv = row.get(jj, 0.0) + ng.stdp_pre
                            if nv > ng.w_max:
                                nv = ng.w_max
                            pending.setdefault((pp, kj), {})[jj] = nv
                    for (pp, kj), pairs in pending.items():
                        ng.W_out[pp][kj].batch_update(pairs)
                if ng.stdp_neg > 0 and len(pre_idx):
                    pending = {}
                    for pp in pre_idx:
                        kp = int(k_star[pp])
                        for jj in top:
                            if pp == jj:
                                continue
                            row = ng.W_out[jj][kp]
                            nv = row.get(pp, 0.0) - ng.stdp_neg
                            if nv < 0.0:
                                nv = 0.0
                            pending.setdefault((jj, kp), {})[pp] = nv
                    for (jj, kp), pairs in pending.items():
                        ng.W_out[jj][kp].batch_update(pairs)
            if ng.weight_decay:
                f = 1.0 - ng.weight_decay
                for i in range(ng.n):
                    for k in range(ng.slots):
                        row = ng.W_out[i][k]
                        if row:
                            row.scale(f)
    ng.v[top, :] = 0.0
    if ng.learn_gate and len(top):
        ng.slot_freq[top, k_star[top]] += 1
    ng.spikes = new_spikes
    ng.last_k_star = k_star
    ng.pre_trace = ng.pre_trace * ng.trace_decay + new_spikes
    if ng.refractory > 0:
        ng.refractory_left = np.maximum(ng.refractory_left - 1, 0)
        if len(top):
            ng.refractory_left[top] = ng.refractory
    return new_spikes


def learn_with(ng, pats, pairs, step_fn, rounds=N_ROUNDS):
    """用指定 step 驱动教学（复刻 _learn_sentence 流程）。
    step_fn 签名统一为 fn(ng, pulse, slot)——绑定方法在外层包 lambda。"""
    for x, y in pairs:
        for _ in range(rounds):
            ng.v = np.zeros((ng.n, ng.slots))
            ng.spikes = np.zeros(ng.n)
            ng.pre_trace = np.zeros(ng.n)
            for w in (x, y):
                ng.v = np.zeros((ng.n, ng.slots))
                ng.spikes = np.zeros(ng.n)
                step_fn(ng, build_pulse(ng.n, pats[w]), slot=0)
                ng.spikes = np.zeros(ng.n)
                step_fn(ng, np.zeros(ng.n), slot=0)
            for _ in range(4):
                ng.spikes = np.zeros(ng.n)
                step_fn(ng, np.zeros(ng.n), slot=0)


def diff_all(ng_a, ng_b):
    """全表逐边对拍：返回差异边数（dst 或 w 不等）。"""
    diff = 0
    for i in range(ng_a.n):
        for k in range(ng_a.slots):
            ra, rb = ng_a.W_out[i][k], ng_b.W_out[i][k]
            if len(ra) != len(rb):
                diff += len(ra) + len(rb)
                continue
            if len(ra) == 0:
                continue
            if not np.array_equal(ra.dst, rb.dst):
                diff += 1
            elif not np.array_equal(ra.w, rb.w):
                diff += 1
    return diff


def main():
    ng, vocab, pats, cursor = load_version(VERSION)
    rng = np.random.default_rng(SEED)
    words = [w for w in pats.keys()]
    rng.shuffle(words)
    pairs = [(words[i], words[i + 1]) for i in range(0, 2 * N_PAIRS, 2)]

    # 两份独立副本（同种子 rng → 同噪声序列）
    ng_new, _, _, _ = load_version(VERSION)
    ng_ref, _, _, _ = load_version(VERSION)
    print(f"[对拍] v{VERSION}：n={ng_new.n}，词对 {len(pairs)} × {N_ROUNDS} 轮")

    # numba 首次编译预热（不计时、不对拍）：学 1 对触发 _merge_rows 编译
    ng_warm, _, _, _ = load_version(VERSION)
    learn_with(ng_warm, pats, pairs[:1],
               lambda ng2, p, slot=0: ng2.step(p, slot))
    del ng_warm

    # 参考版（原逻辑）先跑并计时
    t0 = time.perf_counter()
    learn_with(ng_ref, pats, pairs, step_ref)
    t_ref = time.perf_counter() - t0

    # 新版正式跑并计时（内核已编译，纯执行）
    t0 = time.perf_counter()
    learn_with(ng_new, pats, pairs,
               lambda ng2, p, slot=0: ng2.step(p, slot))
    t_new = time.perf_counter() - t0

    print(f"[耗时] 参考实现：{t_ref:.2f}s | numba 版：{t_new:.2f}s | "
          f"提速 {t_ref / t_new:.1f}×")

    # 全表逐边对拍（各学 N_PAIRS×N_ROUNDS 轮后状态应完全一致）
    diff = diff_all(ng_new, ng_ref)
    if diff == 0:
        print(f"[对拍] ✅ 全表逐边一致（差异边数 = 0）——语义无损")
    else:
        print(f"[对拍] ❌ 差异边数 = {diff} —— 语义被破坏，需排查")
    # 顺带唤起对拍
    fired_new = _evoke_prefix(ng_new, ["我"], pats, slot=0, steps=3)
    fired_ref = _evoke_prefix(ng_ref, ["我"], pats, slot=0, steps=3)
    print(f"[唤起] 新={len(fired_new)} 参考={len(fired_ref)} "
          f"一致={fired_new == fired_ref}")


if __name__ == "__main__":
    main()
