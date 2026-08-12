# -*- coding: utf-8 -*-
"""实验前内部状态检查：v53.0（涌现起点 = v52.1 + 1000 空神经元池）

用户要求（2026-08-11）："实验之前先检查模型内部状态"——教学前确认
基座干净（零边起点）、机制参数就位、词表/池神经元状态明确，防止在
"非预期状态"上跑实验导致结论失真。

检查项：
  1. 机制参数（theta/wta_k/noise/DA/惩罚……——存/载一致性）
  2. 边统计（总数/权重直方图——涌现基座应为 0 边）
  3. 关键词存在性（叫/爸爸/妈妈/爷爷/妹妹……在 pats 的神经元）
  4. 池神经元（149396-150395）干净度（入边/出边 = 0？）
  5. 轨道状态（track_map/_track_readout——无强边应全空）
  6. 调质/资格迹/唤醒计数（da/elig/_elig_pairs/slot_freq）

用法：python _tmp_check_emerge_state.py
"""

import json
from collections import Counter
from pathlib import Path

import numpy as np

from snapshot import load_snapshot

RUN = Path(__file__).resolve().parent / "runs" / "v52_2_20260811_183718"
KEY_WORDS = ["叫", "爸爸", "妈妈", "爷爷", "奶奶", "妹妹", "哥哥", "姐姐",
             "弟弟", "我", "你", "他", "猫", "苹果", "吃", "说"]
POOL = (149396, 150395)      # v53.0 空神经元池范围（meta 登记）
STRONG = 16.0                # build_track_map 的主干/绑定档阈值


def main():
    ng, vocab, pats, cursor = load_snapshot(RUN)
    print(f"== 快照 {RUN.name} 加载 ==")
    print(f"net_kind=sparse  n={ng.n}  slots={ng.slots}  cursor={cursor}")

    # ── 1. 机制参数 ──
    print("\n── 1. 机制参数 ──")
    fields = ("theta", "membrane_decay", "eta", "w_max", "wta_k", "noise_p",
              "noise_amp", "weight_decay", "learn_gate", "stdp_pre", "stdp_neg",
              "trace_decay", "refractory", "inh_loose", "std_dep", "std_rec",
              "edge_min", "inh_norm", "refract_clear", "da_gain", "da_decay",
              "elig_decay", "da_max", "punish_factor", "td_rate")
    for f in fields:
        print(f"  {f} = {getattr(ng, f)}")
    print(f"  da = {ng.da}   da_expected = {ng.da_expected:.4f}   "
          f"last_rpe = {ng.last_rpe}")

    # ── 2. 边统计（零边起点？）──
    print("\n── 2. 边统计 ──")
    n_edge = 0
    w_hist = Counter()
    src_word_edge = 0          # 词神经元（pats 注册）发出的边
    src_pool_edge = 0          # 池神经元发出的边
    dst_pool_edge = 0          # 指向池神经元的边
    pats_set = set()
    for w, ns in pats.items():
        pats_set.update(int(x) for x in ns)
    for i in range(ng.n):
        row = ng.W_out[i][0]
        if not row:
            continue
        for j, w in row.items():
            n_edge += 1
            if w >= STRONG:
                w_hist["strong(≥16)"] += 1
            elif w > 0:
                w_hist["weak(0,16)"] += 1
            else:
                w_hist["zero"] += 1
            if i in pats_set:
                src_word_edge += 1
            if POOL[0] <= i <= POOL[1]:
                src_pool_edge += 1
            if POOL[0] <= j <= POOL[1]:
                dst_pool_edge += 1
    print(f"  总边数 = {n_edge}   （分布 {dict(w_hist)}）")
    print(f"  词神经元出边 = {src_word_edge}   池神经元出边 = {src_pool_edge}"
          f"   指向池入边 = {dst_pool_edge}")

    # ── 3. 关键词语义 ──
    print("\n── 3. 关键词在词表（pats）──")
    for w in KEY_WORDS:
        ns = pats.get(w)
        if ns:
            in_pool = sum(1 for x in ns if POOL[0] <= x <= POOL[1])
            print(f"  {w}: {ns}  (池内 {in_pool})")
        else:
            print(f"  {w}: ✗ 不在词表")
    # 词表规模分布（神经元跨度）
    min_n = min((min(v) for v in pats.values()), default=-1)
    max_n = max((max(v) for v in pats.values()), default=-1)
    print(f"  词表神经元跨度 = [{min_n}, {max_n}]（池范围 [{POOL[0]}, {POOL[1]}]）")

    # ── 4. 池神经元 ──
    print("\n── 4. 池神经元 [149396, 150395] ──")
    pool_fired = int((ng.slot_freq[POOL[0]:POOL[1] + 1] > 0).sum())
    print(f"  池神经元被唤醒计数 > 0 的个数 = {pool_fired}")

    # ── 5. 轨道状态 ──
    print("\n── 5. 轨道状态 ──")
    print(f"  track_map = {len(ng.track_map)} 条   槽位集合 = {len(ng._track_slots)} 个"
          f"   读出表 = {len(ng._track_readout)} 条")
    print(f"  _track_slots_list len = {len(ng._track_slots_list)}")

    # ── 6. 调质/资格迹/唤醒 ──
    print("\n── 6. 调质/资格迹/唤醒 ──")
    print(f"  elig 非零 = {int((ng.elig > 0).sum())}   _elig_pairs = {len(ng._elig_pairs)}")
    print(f"  _prev_inp = {ng._prev_inp}   _ctx_inp = {ng._ctx_inp}   _ctx_idle = {ng._ctx_idle}")
    print(f"  slot_freq 非零 = {int((ng.slot_freq > 0).sum())}"
          f"   max = {int(ng.slot_freq.max())}")
    gain_u = np.unique(ng.gain)
    print(f"  gain 取值 = {gain_u[:10]}{'…' if len(gain_u) > 10 else ''}")

    # ── 结论 ──
    print("\n── 结论 ──")
    ok = n_edge == 0
    print("零边起点 OK" if ok else f"⚠ 已有 {n_edge} 条边——不是零边起点")
    if pats.get("叫") and pats.get("爸爸"):
        print("叫/爸爸 词神经元就位 OK")
    else:
        print("⚠ 叫/爸爸 缺失——需 allocate_pats 补充")
    print(f"池神经元边 = {src_pool_edge + dst_pool_edge}（应 0）")


if __name__ == "__main__":
    main()
