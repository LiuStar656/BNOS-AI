# -*- coding: utf-8 -*-
"""Phase 2 最小验证：频率门控慢衰减（sleep_consolidate）。

验证 A/B 定式（同池不同槽）→ 高频复习 A、低频复习 B → sleep 整理：
  ① 唤醒计数口径：只数发放神经元主导槽（A 高 / B 低）
  ② 活跃槽不动：高频槽（A/槽0）连接强度 sleep 前后不变
  ③ 低频槽渐进衰减：低频槽（B/槽1）连接强度 ×(1-decay)
  ④ 可复活：B 衰减 1 周期后复习 B → 连接强度回升
  ⑤ 归零回收：连接衰减 ≤ eps 后被删除（稀疏回收）
  ⑥ 冻结拒绝：learn_gate=False 时 sleep 返回 0、W 物理零改动
  ⑦ 静息不计数：空脉冲步不增长 slot_freq；sleep 后计数重置

用法：python _accept_prune.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from schema_net import build_pulse
from sparse_net import SparseSchemaNet

N, SLOTS = 256, 2
SEED = 42
PAT_A = np.arange(16)          # 定式 A：神经元 0-15（槽 0）
PAT_B = np.arange(48, 64)      # 定式 B：神经元 48-63（槽 1，与 A 不重叠）
MIN_WAKE, DECAY, EPS = 10, 0.3, 1e-4

results = []


def mk_net():
    return SparseSchemaNet(n=N, slots=SLOTS, theta=1.0, membrane_decay=0.9, eta=0.1,
                           w_max=16.0, wta_k=8, noise_p=0.02, noise_amp=0.5,
                           weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5, stdp_neg=0.0,
                           refractory=1, rng=np.random.default_rng(SEED))


def run_pattern(ng, pat, slot, times=1):
    """注入模式 pat 到 slot，空步传播至收敛，重复 times 次（学习/复习）。"""
    for _ in range(times):
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.step(build_pulse(ng.n, pat), slot=slot)
        for _ in range(6):
            ng.step(np.zeros(ng.n), slot=slot)


def slot_strength(ng, pat, slot):
    """定式所在槽的连接总强度（模式神经元出边，目标也在发放集合内才计入？——
    直接按 W_out[i][slot] 全量求和，含串扰目标；测的是"该槽残留强度"）。"""
    return float(sum(w for i in pat for w in ng.W_out[i][slot].values()))


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")


def main():
    print("═" * 64)
    print("Phase 2 最小验证：频率门控慢衰减（sleep_consolidate）")
    print(f"n={N} slots={SLOTS}  A=PAT_A(槽0)×40  B=PAT_B(槽1)×2  "
          f"min_wake={MIN_WAKE} decay={DECAY} eps={EPS}")

    # ── 学习：A 高频复习（槽0）、B 低频复习（槽1）──
    ng = mk_net()
    run_pattern(ng, PAT_A, 0, times=40)
    run_pattern(ng, PAT_B, 1, times=2)

    fa = float(ng.slot_freq[PAT_A, 0].mean())
    fb = float(ng.slot_freq[PAT_B, 1].mean())
    fa_cross = float(ng.slot_freq[PAT_B, 0].mean())  # B 神经元在槽0 的串扰计数
    print(f"\n① 唤醒计数: A(槽0)均值={fa:.1f}  B(槽1)均值={fb:.1f}  B在槽0串扰={fa_cross:.2f}")
    check("A 高频（≥MIN_WAKE）", fa >= MIN_WAKE, f"fa={fa:.1f}")
    check("B 低频（<MIN_WAKE）", fb < MIN_WAKE, f"fb={fb:.1f}")
    check("静息串扰不计数（B 在槽0 ≈0）", fa_cross < 1.0, f"fa_cross={fa_cross:.2f}")

    sA0, sB1 = slot_strength(ng, PAT_A, 0), slot_strength(ng, PAT_B, 1)
    print(f"  B 定式槽1 强度={sB1:.2f}（>0 说明学习沉淀）")
    check("B 定式已沉淀", sB1 > 1.0, f"sB1={sB1:.2f}")

    # ── sleep：低频槽衰减、活跃槽不动 ──
    cleared, weakened = ng.sleep_consolidate(min_wake=MIN_WAKE, decay=DECAY, eps=EPS)
    sA1, sB2 = slot_strength(ng, PAT_A, 0), slot_strength(ng, PAT_B, 1)
    print(f"\n②③ sleep 后: A(槽0) {sA0:.2f}→{sA1:.2f}  B(槽1) {sB1:.2f}→{sB2:.2f}  "
          f"弱化{weakened}条/删除{cleared}条")
    check("活跃槽不动（A 强度不变）", abs(sA1 - sA0) < 1e-6, f"{sA0:.2f}→{sA1:.2f}")
    check("低频槽衰减 ×(1-decay)", abs(sB2 - sB1 * (1 - DECAY)) < 1e-6 * max(1, sB1),
          f"期望 {sB1 * (1 - DECAY):.2f}")
    check("sleep 后计数重置", float(ng.slot_freq.sum()) == 0, f"sum={ng.slot_freq.sum()}")

    # ── 可复活：B 衰减 1 周期后复习 → 强度回升 ──
    run_pattern(ng, PAT_B, 1, times=40)
    sB3 = slot_strength(ng, PAT_B, 1)
    print(f"\n④ 复习 B×40 后: B(槽1) {sB2:.2f}→{sB3:.2f}")
    check("B 可复活（复习后强度回升）", sB3 > sB2, f"{sB2:.2f}→{sB3:.2f}")

    # ── 归零回收（单元断言：构造接近 eps 的连接）──
    ng2 = mk_net()
    ng2.W_out[10][0] = {20: EPS * 2}   # 0.0002 > eps
    ng2.slot_freq[10, 0] = 0
    c1, _ = ng2.sleep_consolidate(min_wake=MIN_WAKE, decay=DECAY, eps=EPS)
    v1 = ng2.W_out[10][0].get(20, 0.0)
    c2, _ = ng2.sleep_consolidate(min_wake=MIN_WAKE, decay=DECAY, eps=EPS)
    v2 = ng2.W_out[10][0].get(20, 0.0)
    print(f"\n⑤ 归零回收: 首周期 {EPS*2}→{v1}（删{c1}）→ 次周期→{v2}（删{c2}）")
    check("首周期未删（衰减中保留在槽位上）", v1 > 0 and c1 == 0, f"v1={v1}")
    check("次周期归零删除（回收空间）", v2 == 0.0 and c2 == 1, f"v2={v2} c2={c2}")

    # ── 冻结拒绝 ──
    ng3 = mk_net()
    ng3.W_out[10][0] = {20: 1.0}
    ng3.slot_freq[10, 0] = 0
    ng3.learn_gate = False
    c3, _ = ng3.sleep_consolidate(min_wake=MIN_WAKE, decay=DECAY, eps=EPS)
    v3 = ng3.W_out[10][0].get(20, 0.0)
    print(f"\n⑥ 冻结态: sleep 返回={c3}  连接保持={v3}")
    check("冻结态拒绝执行", c3 == 0 and v3 == 1.0, f"c3={c3} v3={v3}")

    # ── 静息不计数 ──
    ng4 = mk_net()
    for _ in range(50):
        ng4.v = np.zeros((ng4.n, ng4.slots))
        ng4.spikes = np.zeros(ng4.n)
        ng4.step(np.zeros(ng4.n), slot=0)   # 空脉冲（静息，无输入）
    s = float(ng4.slot_freq.sum())
    print(f"\n⑦ 静息 50 空步后计数总和={s}")
    check("静息不增长计数", s == 0, f"sum={s}")

    # ── 汇总 ──
    npass = sum(1 for _, ok in results if ok)
    print("\n" + "═" * 64)
    print(f"汇总: {npass}/{len(results)} PASS")
    for name, ok in results:
        if not ok:
            print(f"  FAIL  {name}")
    if npass == len(results):
        print("全部 PASS ✓")
    else:
        print("存在 FAIL ✗")
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
