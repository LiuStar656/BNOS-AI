# -*- coding: utf-8 -*-
"""投稿补全实验 E6：混沌环境下奖惩对行为频率的定向调节（操作性条件反射受控实证）。

现象（用户在混沌定式网络中的观察）：输入激活的神经元和突触产生的行为被奖励后，
相同或相似输入产生该行为的频率变高；被惩罚后变低。

理论定位：R-STDP 三因子（Izhikevich 2007，Δw = DA × e）——多巴胺门控 Hebbian/STDP，
对应操作性条件反射（Skinner）与奖赏预测误差（Schultz 1997）。

受控设计（详见 docs/[PLAN]-E6-混沌环境下奖惩行为频率调节受控实验.md）：
  - 混沌网络：SparseSchemaNet(n=1024, slots=1, 间歇混沌)；混沌判定 = 非注入步
    自发发放率 > 0
  - 预学习：STDP 时序教学（X 先发 → B 后发，da=+1.0）×2 → 单向 X→B 边；
    **预学习后清残留 da/资格迹**（v2.1 根因：da 按 0.9/步衰减需 ~30 步，
    不清则测量期"无奖惩也写边"→ 自振 chaos=1.0、权重暴涨）
  - 行为事件：注入后的响应窗口（注入步 + 后 1 步）内 B 神经元 ≥8 个同时发放
  - 三组对照：奖励（行为 → 标记活跃 X→B 资格迹 + release_da(+0.3)）/
    惩罚（行为 → 标记资格迹 + release_da(-0.3)）/
    中性（不注入奖惩，纯复读零改动）
  - **干预在 learn_gate=False 下进行（v2.2 关键修正）**：隔离"纯奖惩经资格迹
    兑现"效应（release_da 直接写边、不受 learn_gate 控制），无 Hebbian"使用
    增强"混杂。v2.1 用 learn_gate=True 时 Hebbian+兑现双重强化 → 少数 B 神经
    元垄断 WTA → 行为集合坍缩（发放数 < 阈值 → 行为解体）——马太效应；
    已由诊断 _tmp_diag_e6d 实证。learn_gate=False 时三组效应纯净、3 seeds 稳健
  - 泛化梯度：X 变体 = 保留 k∈{16,12,8,4} 个 X 神经元 + 空闲池补足 16 个
  - 流程：基线（冻结纯测量）→ 干预 → 冻结测试（X 及各变体）
  - 指标：行为频率（行为事件 / 注入周期 × 100）+ 干预效应 + 泛化曲线 + Cohen's d

用法：
    python _paper_rl_behavior.py                    # 冒烟：seed=42 × 3 组（n=1024）
    python _paper_rl_behavior.py --seeds 42,43,44,45,46
    # 补实验（2026-08-12 扩参）：
    #   --n 2048         规模扫描（N 参数化，输出目录带 s{n}）
    #   --learn-gate     消融轴：干预阶段开学习门（复现马太坍缩；默认 False=正式协议）
    #   --modes reward   只跑指定组（发生率扫描用）
    #   例：python _paper_rl_behavior.py --n 4096 --seeds 42,43
    #       python _paper_rl_behavior.py --learn-gate --modes reward --seeds 1..50（发生率）
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from schema_net import build_pulse
from sparse_net import SparseSchemaNet, allocate_pats

N = 1024                # 默认规模（--n 可覆盖，模块级全局：main 内 global N 赋值）
LG_INTERVENE = False    # 干预阶段学习门状态（--learn-gate 可覆盖；False=正式协议）
K = 16                 # 每模式神经元数
WTA_K = 8
PRE_ROUNDS = 2         # 预学习轮数（教学奖励建立 X→B）
P1_CYCLES = 40         # 基线注入周期数
P2_CYCLES = 100        # 干预注入周期数
P3_CYCLES = 20         # 每相似度测试注入周期数
INJECT_EVERY = 5       # 每 5 步一个注入周期
WINDOW = 2             # 响应窗口 = 注入步 + 后 1 步
INJECT_AMP = 1.0
BEHAVE_MIN = 8         # 行为判定：B 神经元 ≥8 个同时发放
DA_PRE = 1.0           # 预学习教学奖励
DA_CTRL = 0.3          # 干预奖励/惩罚幅度（小幅度——防过强化坍缩）
VARIANTS = (16, 12, 8, 4)
RUNS = Path(__file__).resolve().parent / "runs"


def make_net(seed, rng):
    """混沌网络：间歇混沌背景（STDP 时序教学建单向 X→B（无互驱环），
    std_dep=0.5 强疲劳 + refract_clear 清复燃 → "爆发后收敛"的间歇混沌，
    行为成为可分辨事件）。v2.2：noise 0.05/0.3、stdp_pre=0.15（弱预学习
    边 w≈4——Regime 8，_tmp_diag_e6b 3 seeds 验证双向调节稳健）。
    rng 按 mode 区分（seed*100+mode_idx）——三组为独立样本（非共享噪声）。"""
    return SparseSchemaNet(n=N, slots=1, theta=1.0, membrane_decay=0.9, eta=0.1,
                           w_max=16.0, wta_k=WTA_K, noise_p=0.05, noise_amp=0.3,
                           refractory=1, stdp_pre=0.15, std_dep=0.5, std_rec=0.85,
                           refract_clear=True, rng=rng)


def make_variant(rng, x_neurons, pool, k):
    """X 变体：保留 k 个 X 神经元 + 空闲池补足 16 个（k 越小相似度越低）。"""
    keep = set(int(i) for i in rng.choice(x_neurons, k, replace=False))
    need = K - len(keep)
    new = set(int(i) for i in rng.choice(pool, need, replace=False))
    return sorted(keep | new)


def run_one(seed, mode):
    rng = np.random.default_rng(seed * 100 + {"reward": 0, "punish": 1, "neutral": 2}[mode])
    ng = make_net(seed, rng)
    pats, _ = allocate_pats(ng, ["X", "B"], K)
    x_n = list(pats["X"])
    b_n = list(pats["B"])
    b_mask = np.zeros(N, dtype=bool)
    b_mask[b_n] = True
    pool = [i for i in range(N) if i not in set(x_n) | set(b_n)]

    def behave_event():
        """行为事件：当前步 B 神经元 ≥BEHAVE_MIN 个同时发放。"""
        return int(np.count_nonzero(ng.spikes[b_mask]) >= BEHAVE_MIN)

    # ── 预学习：STDP 时序教学（X 先发 → B 后发 → 只建单向 X→B 边，
    #    不建 B→X 反向边 → 注入后无互驱自振）──
    for _ in range(PRE_ROUNDS):
        ng.release_da(DA_PRE)
        ng.step(build_pulse(N, x_n, INJECT_AMP), slot=0)   # X 发放（前驱）
        ng.step(build_pulse(N, b_n, INJECT_AMP), slot=0)   # B 发放（后继）→ STDP 建 X→B
    # v2.1 根因①：清残留 da/资格迹——防测量期"无奖惩也写边"自振
    ng.da = 0.0
    ng.da_expected = 0.0
    ng._elig_pairs.clear()

    def w_xb():
        """X 模式出边汇聚到 B 模式的权重和（连通性观测）。"""
        tot = 0.0
        for i in x_n:
            row = ng.W_out[i][0]
            if row:
                for j in b_n:
                    tot += row.get(j, 0.0)
        return tot

    w_pre = w_xb()

    def mark_elig():
        """行为发生时标记活跃 X→B 配对（Δw=DA×e 的 e——资格迹）。
        只标有边权的配对（无 B→X 反向边）；惩罚经 LTD 兑现同一对象。"""
        for i in x_n:
            row = ng.W_out[i][0]
            if row:
                for j in b_n:
                    if row.get(j, 0.0) > 0:
                        ng._elig_pairs[(int(i), int(j))] = 1.0

    def run_cycles(n_cycles, inject_pulse, learn_mode):
        """跑 n 个注入周期；返回 (行为事件数, 非注入步自发发放率)。
        每周期 = 注入步 + 响应步；行为在窗口（注入步 + 后 1 步）内发生计 1 次。
        奖惩：行为在窗口内发生 → 标记资格迹 + release_da（每周期至多 1 次）；
        干预在 learn_gate=False 下经 release_da 兑现（v2.2 方案 C）。"""
        events = 0
        bg_fire = bg_steps = 0
        for cyc in range(n_cycles):
            fired_win = False
            for step_in_cyc in range(INJECT_EVERY):
                if step_in_cyc == 0:
                    ng.step(build_pulse(N, inject_pulse, INJECT_AMP), slot=0)
                else:
                    ng.step(np.zeros(N), slot=0)
                    bg_steps += 1
                    if bool(np.any(ng.spikes > 0)):
                        bg_fire += 1
                if not fired_win and step_in_cyc < WINDOW and behave_event():
                    fired_win = True
                    if learn_mode == "reward":
                        mark_elig()
                        ng.release_da(+DA_CTRL)
                    elif learn_mode == "punish":
                        mark_elig()
                        ng.release_da(-DA_CTRL)
            if fired_win:
                events += 1
        chaos = bg_fire / bg_steps if bg_steps else 0.0
        return events, chaos

    # ── Phase 1 基线（learn_gate=False 纯测量）──
    ng.learn_gate = False
    f_base, chaos_ratio = run_cycles(P1_CYCLES, x_n, "none")

    # ── Phase 2 干预（默认 learn_gate=False——纯奖惩资格迹兑现；
    #    --learn-gate 时开学习门 = Hebbian 使用增强 × 兑现双通道 → 复现马太坍缩；
    #    neutral 组 learn_mode="none" 零改动，纯复读基线）──
    ng.learn_gate = LG_INTERVENE
    lm = "none" if mode == "neutral" else mode
    f_inter, _ = run_cycles(P2_CYCLES, x_n, lm)
    ng.learn_gate = False

    # ── Phase 3 冻结测试（清残留 da/资格迹，纯测量唤起频率）──
    ng.da = 0.0
    ng.da_expected = 0.0
    ng._elig_pairs.clear()
    variants = {k: (x_n if k == 16 else make_variant(rng, x_n, pool, k))
                for k in VARIANTS}
    f_test = {}
    for k in VARIANTS:
        ev, _ = run_cycles(P3_CYCLES, variants[k], "none")
        f_test[k] = ev / P3_CYCLES * 100.0   # 行为事件 / 注入周期 × 100

    return {
        "seed": seed, "mode": mode,
        "chaos_ratio": round(chaos_ratio, 4),
        "w_pre": round(w_pre, 3),
        "w_post": round(w_xb(), 3),
        "f_base": round(f_base / P1_CYCLES * 100.0, 3),
        "f_inter": round(f_inter / P2_CYCLES * 100.0, 3),
        "f_test": {str(k): round(v, 3) for k, v in f_test.items()},
    }


def main():
    global N, LG_INTERVENE
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="42", help="逗号分隔的 seed 列表")
    ap.add_argument("--n", type=int, default=1024, help="网络规模（神经元数，规模扫描用）")
    ap.add_argument("--learn-gate", action="store_true",
                    help="干预阶段开学习门（复现马太坍缩；默认关闭=正式协议）")
    ap.add_argument("--modes", default="reward,punish,neutral", help="逗号分隔的干预组")
    args = ap.parse_args()
    N = args.n
    LG_INTERVENE = args.learn_gate
    seeds = [int(s) for s in args.seeds.split(",")]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    t0 = time.time()
    print(f"═══ E6 混沌环境下奖惩行为频率调节受控实验（N={N}, "
          f"learn_gate={LG_INTERVENE}）═══", flush=True)
    results = []
    for seed in seeds:
        for mode in modes:
            r = run_one(seed, mode)
            results.append(r)
            print(f"[seed={seed} {mode:7s}] chaos={r['chaos_ratio']:.3f} "
                  f"w_pre={r['w_pre']:.2f}→w_post={r['w_post']:.2f} "
                  f"f_base={r['f_base']:.2f} f_inter={r['f_inter']:.2f} "
                  f"f_test={ {k: v for k, v in r['f_test'].items()} }", flush=True)

    # ── 汇总统计 ──
    by_mode = {m: [r for r in results if r["mode"] == m] for m in modes}

    def mstd(key, rows, fmap=None):
        vals = [fmap(r) if fmap else r[key] for r in rows]
        a = np.array(vals, dtype=float)
        sd = float(a.std(ddof=1)) if len(a) > 1 else 0.0
        return round(float(a.mean()), 3), round(sd, 3)

    summary = {"modes": {}}
    for m in by_mode:
        rows = by_mode[m]
        f_test_m = {str(k): mstd("f_test", rows, lambda r, kk=k: r["f_test"][str(kk)])
                    for k in VARIANTS}
        summary["modes"][m] = {
            "chaos_ratio": mstd("chaos_ratio", rows),
            "f_base": mstd("f_base", rows),
            "f_inter": mstd("f_inter", rows),
            "f_test": f_test_m,
        }

    # 效应量：奖励/惩罚组 vs 中性组（测试期 X，即 k=16 频率）
    def cohens_d(a, b):
        a, b = np.array(a, dtype=float), np.array(b, dtype=float)
        s = np.sqrt(((len(a) - 1) * a.std(ddof=1) ** 2
                     + (len(b) - 1) * b.std(ddof=1) ** 2) / (len(a) + len(b) - 2))
        return float((a.mean() - b.mean()) / s) if s > 0 else 0.0

    def group_f16(m):
        return [r["f_test"]["16"] for r in by_mode.get(m, [])]

    d_rew = d_pun = None
    if "reward" in modes and "neutral" in modes and by_mode["neutral"] and by_mode["reward"]:
        d_rew = cohens_d(group_f16("reward"), group_f16("neutral"))
    if "punish" in modes and "neutral" in modes and by_mode["neutral"] and by_mode["punish"]:
        d_pun = cohens_d(group_f16("punish"), group_f16("neutral"))
    summary["cohens_d_vs_neutral"] = {
        "reward": round(d_rew, 3) if d_rew is not None else None,
        "punish": round(d_pun, 3) if d_pun is not None else None,
    }
    summary["n_seeds"] = len(seeds)

    # ── 马太坍缩发生率（--learn-gate 且 reward 组时才有意义）──
    collapse = None
    if LG_INTERVENE and "reward" in modes and by_mode.get("reward"):
        rw = by_mode["reward"]
        coll = [r for r in rw if r["f_test"]["16"] == 0.0]
        w_surge = [r for r in rw if r["w_post"] > r["w_pre"] * 3]
        collapse = {
            "collapsed": len(coll), "total": len(rw),
            "rate": round(len(coll) / len(rw), 4) if rw else 0.0,
            "w_surge_rate": round(len(w_surge) / len(rw), 4) if rw else 0.0,
        }
        print(f"\n─── 马太坍缩发生率（learn_gate=True, reward, n={len(rw)} seeds）───", flush=True)
        print(f"  坍缩(f16=0%)：{collapse['collapsed']}/{collapse['total']} "
              f"({collapse['rate']*100:.1f}%) | "
              f"权重暴涨(>3×pre)：{collapse['w_surge_rate']*100:.1f}%", flush=True)

    print("\n─── 汇总（mean±std）───", flush=True)
    for m in summary["modes"]:
        s = summary["modes"][m]
        print(f"[{m:7s}] chaos={s['chaos_ratio']} f_base={s['f_base']} "
              f"f_inter={s['f_inter']} f_test={s['f_test']}", flush=True)
    if "reward" in modes and "neutral" in modes:
        print(f"效应量 vs 中性：reward d={d_rew:+.3f} | punish d={d_pun:+.3f}", flush=True)

    data = {
        "tag": f"E6 混沌环境下奖惩行为频率调节受控实验（N={N}, learn_gate={LG_INTERVENE}）",
        "params": {"N": N, "K": K, "WTA_K": WTA_K, "PRE_ROUNDS": PRE_ROUNDS,
                   "P1_CYCLES": P1_CYCLES, "P2_CYCLES": P2_CYCLES,
                   "P3_CYCLES": P3_CYCLES, "INJECT_EVERY": INJECT_EVERY,
                   "WINDOW": WINDOW, "BEHAVE_MIN": BEHAVE_MIN,
                   "DA_PRE": DA_PRE, "DA_CTRL": DA_CTRL,
                   "VARIANTS": list(VARIANTS), "seeds": seeds,
                   "learn_gate": LG_INTERVENE, "modes": modes},
        "summary": summary,
        "results": results,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    if collapse:
        data["collapse_rate"] = collapse
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = f"s{N}" if N != 1024 else ""
    tag += "_lg" if LG_INTERVENE else ""
    out_dir = RUNS / f"paper_e6_{tag}_{ts}" if tag else RUNS / f"paper_e6_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print(f"\n留档: {out_dir}/  elapsed {data['elapsed_sec']}s", flush=True)


if __name__ == "__main__":
    main()
