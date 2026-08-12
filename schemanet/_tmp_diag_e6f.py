# -*- coding: utf-8 -*-
"""E6 判别实验：把"实验处理"与"代码诱导"的边界画出来。

D1 非操作性对照：奖励不依赖行为（每 cycle 50% 随机 release_da(+0.3)）
   —— 若频率也升 → 时点无关（纯权重增强）；不升 → 行为依赖奖励是关键
D2 错误边对照：预学习建 X→B 与 X→C，奖励标记 X→C（错误目标）
   —— 若 B 频率也升 → 非定向（da 全局效应）；不升/降 → 定向强化真实
D3 阈值扫描：行为阈值 BM∈{5,8,10} × {reward, neutral}——机械阈值效应？
D4 特异性：B 组空拍自发发放率 reward vs neutral——整体兴奋性 vs 特异性
"""
import numpy as np
from schema_net import build_pulse
from sparse_net import SparseSchemaNet, allocate_pats

N = 1024
K = 16
WTA_K = 8
P1, P2, P3 = 40, 100, 20
EVERY, WINDOW, AMP = 5, 2, 1.0
DA_PRE = 1.0
NP, NA, SP, DC = 0.05, 0.3, 0.15, 0.3
VARIANTS = (16, 12, 8, 4)
SEEDS = (42, 43)


def make_net(seed, mode):
    rng = np.random.default_rng(seed * 100 + mode)
    ng = SparseSchemaNet(n=N, slots=1, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=16.0, wta_k=WTA_K, noise_p=NP, noise_amp=NA,
                         refractory=1, stdp_pre=SP, std_dep=0.5, std_rec=0.85,
                         refract_clear=True, rng=rng)
    return ng, rng


def w_target(ng, x_n, tgt):
    return sum(ng.W_out[i][0].get(j, 0.0) for i in x_n for j in tgt
               if ng.W_out[i][0].get(j, 0.0) > 0)


def run_core(seed, mode_idx, BM=8, pre_extra=(), reward_target="B",
             random_reward=False, rand_p=0.5):
    """核心协议。pre_extra: 额外预学习模式（如 ("C",)）。reward_target: 奖励标记目标。
    random_reward: 非操作性奖励（与行为解耦）。返回结果 dict。"""
    ng, rng = make_net(seed, mode_idx)
    pats, _ = allocate_pats(ng, ["X", "B"] + list(pre_extra), K)
    x_n = list(pats["X"])
    b_n = list(pats["B"])
    tgt_sets = {"B": b_n}
    if pre_extra:
        for p in pre_extra:
            tgt_sets[p] = list(pats[p])
    tgt = tgt_sets[reward_target]
    t_mask = {name: np.zeros(N, dtype=bool) for name in tgt_sets}
    for name, ns in tgt_sets.items():
        t_mask[name][ns] = True
    pool = [i for i in range(N) if i not in set(x_n) | set().union(*tgt_sets.values())]

    # 预学习：X→B（及额外 X→C）
    for tname in ("B",) + pre_extra:
        for _ in range(2):
            ng.release_da(DA_PRE)
            ng.step(build_pulse(N, x_n, AMP), slot=0)
            ng.step(build_pulse(N, tgt_sets[tname], AMP), slot=0)
    ng.da = 0.0
    ng.da_expected = 0.0
    ng._elig_pairs.clear()
    w_pre = {name: round(w_target(ng, x_n, ns), 1) for name, ns in tgt_sets.items()}
    track_names = tuple(n for n in ("B", "C") if n in t_mask)

    def behave():
        return int(np.count_nonzero(ng.spikes[t_mask["B"]])) >= BM

    def mark(tname):
        for i in x_n:
            row = ng.W_out[i][0]
            if row:
                for j in tgt_sets[tname]:
                    if row.get(j, 0.0) > 0:
                        ng._elig_pairs[(int(i), int(j))] = 1.0

    def run_cycles(n_cycles, inject_pulse, lm, track_bg=()):
        """返回 (events, bg_rate_of_tracked_names, chaos_net)。"""
        events = 0
        bg_fire = {name: 0 for name in track_bg}
        net_fire = bg_steps = 0
        for _ in range(n_cycles):
            fired = False
            for si in range(EVERY):
                if si == 0:
                    ng.step(build_pulse(N, inject_pulse, AMP), slot=0)
                else:
                    ng.step(np.zeros(N), slot=0)
                    bg_steps += 1
                    if bool(np.any(ng.spikes > 0)):
                        net_fire += 1
                    for name in track_bg:
                        if bool(np.any(ng.spikes[t_mask[name]])):
                            bg_fire[name] += 1
                if not fired and si < WINDOW and behave():
                    fired = True
                    if lm == "reward":
                        mark(reward_target)
                        ng.release_da(+DC)
                    elif lm == "punish":
                        mark(reward_target)
                        ng.release_da(-DC)
            if fired:
                events += 1
        chaos = net_fire / bg_steps if bg_steps else 0.0
        bg_rate = {name: bg_fire[name] / bg_steps if bg_steps else 0.0
                   for name in track_bg}
        return events, bg_rate, chaos

    ng.learn_gate = False
    f_base, _, chaos = run_cycles(P1, x_n, "none", track_bg=track_names)

    # Phase 2 干预
    if random_reward:
        # D1 非操作性：随机时点注入，与行为解耦（标记全部 X→B 保证兑现对象存在）
        rand_rng = np.random.default_rng(seed * 7)
        events = 0
        for _ in range(P2):
            fired = False
            if rand_rng.random() < rand_p:
                mark("B")
                ng.release_da(+DC)
            for si in range(EVERY):
                if si == 0:
                    ng.step(build_pulse(N, x_n, AMP), slot=0)
                else:
                    ng.step(np.zeros(N), slot=0)
                if not fired and si < WINDOW and behave():
                    fired = True
            if fired:
                events += 1
        f_inter = events / P2 * 100.0
        bg_p2 = {}
        chaos_p2 = chaos
    else:
        lm = "none" if mode_idx == 2 else ("reward" if mode_idx == 0 else "punish")
        f_inter, bg_p2, _ = run_cycles(P2, x_n, lm, track_bg=track_names)

    ng.da = 0.0
    ng.da_expected = 0.0
    ng._elig_pairs.clear()
    w_post = {name: round(w_target(ng, x_n, ns), 1) for name, ns in tgt_sets.items()}

    # Phase 3 测试：B 行为频率 + B/C 自发率
    def make_variant(rng, x_neurons, pool, k):
        keep = set(int(i) for i in rng.choice(x_neurons, k, replace=False))
        need = K - len(keep)
        new = set(int(i) for i in rng.choice(pool, need, replace=False))
        return sorted(keep | new)

    variants = {k: (x_n if k == 16 else make_variant(rng, x_n, pool, k)) for k in VARIANTS}
    f_test = {}
    bg3 = {}
    for k in VARIANTS:
        ev, bg_r, _ = run_cycles(P3, variants[k], "none", track_bg=track_names)
        f_test[k] = ev / P3 * 100.0
        for name, r in bg_r.items():
            bg3.setdefault(name, []).append(r)
    return {
        "f_base": round(f_base / P1 * 100, 1), "f_inter": round(f_inter, 1),
        "f16": f_test[16], "f12": f_test[12], "f8": f_test[8], "f4": f_test[4],
        "w_pre": w_pre, "w_post": w_post, "chaos": round(chaos, 3),
        "bg_B_P3": round(np.mean(bg3["B"]) * 100, 1),
        "bg_C_P3": round(np.mean(bg3.get("C", [0])) * 100, 1) if "C" in bg3 else None,
    }


def show(tag, r):
    print(f"{tag:>28} | f_base {r['f_base']:>4} f_inter {r['f_inter']:>4} "
          f"f16 {r['f16']:>3.0f} f12 {r['f12']:>3.0f} f8 {r['f8']:>3.0f} f4 {r['f4']:>3.0f} "
          f"| wB {r['w_pre'].get('B', 0):>5}->{r['w_post'].get('B', 0):>6} "
          f"wC {r['w_pre'].get('C', 0):>5}->{r['w_post'].get('C', 0):>6} "
          f"| chaos {r['chaos']} bgB_P3 {r['bg_B_P3']}%")


print("═══ E6 判别实验（seeds 42,43）═══\n")

# ── D1 非操作性：随机奖励（无行为依赖）──
print("【D1 非操作性对照】随机 50% cycle 奖励，不依赖行为（对比操作性 reward≈100%/neutral≈28%）")
for sd in SEEDS:
    r = run_core(sd, 0, random_reward=True)
    show(f"D1 seed{sd} random-reward", r)

# ── D2 错误边：奖励 X→C（B 频率不应受益）──
print("\n【D2 错误边对照】预学习 X→B + X→C，奖励标记 X→C")
for sd in SEEDS:
    for rt in ("B", "C"):
        r = run_core(sd, 0, pre_extra=("C",), reward_target=rt)
        show(f"D2 seed{sd} reward->{rt}", r)

# ── D3 阈值扫描 ──
print("\n【D3 阈值扫描】BM ∈ {5,8,10} × {reward, neutral}")
for sd in SEEDS:
    for bm in (5, 8, 10):
        rr = run_core(sd, 0, BM=bm)
        nn = run_core(sd, 2, BM=bm)
        show(f"D3 seed{sd} BM={bm} reward", rr)
        show(f"D3 seed{sd} BM={bm} neutral", nn)

# ── D4 特异性：奖励 vs 中性 的 B 组自发率（D1-D3 输出中 bg_B_P3）──
print("\n【D4 特异性】B 组空拍自发率 bgB_P3（奖励 vs 中性，低=特异性增强）")
for sd in SEEDS:
    rr = run_core(sd, 0)
    nn = run_core(sd, 2)
    show(f"D4 seed{sd} reward", rr)
    show(f"D4 seed{sd} neutral", nn)
