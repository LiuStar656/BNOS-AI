# -*- coding: utf-8 -*-
"""[EXP] 自然涌现教学：「叫爸爸」→ 爸爸（回答）+ 联想 + 泛化

方案：[PLAN]-定式网络自然涌现条件（从代码灌结构到法则+经验长结构）
协议（§四——老师只做三件事，不碰网络结构）：
  说（注入词序 + 韵律强调 amp）→ 给零食（release_da 奖励——DA 门控）→ 验证
  边全部由 STDP/Hebbian 自然长出（零边起点 v53.0 = v52.1 + 1000 空池）

阶段：
  A. 基座自检（load v53.0——零边起点确认，实验前内部状态检查）
  B. 教学「叫 爸爸」×N（奖励 + 论元强调）→ 叫→爸爸 边涌现曲线
  C. 验证：叫→爸爸（联想 System 1）/ 叫爸爸→爸爸（回答 System 2）
  D. 教学「叫 妈妈」×N → 已教论元竞争（叫妈妈→妈妈 压掉爸爸）
  E. 泛化：未教论元（叫妹妹 / 叫哥哥）——诚实记录（PLAN 问题 2 已知弱点）
  F. 存档：快照 + runs/index.jsonl 登记

用法：python _exp_emerge_baba.py
"""

import json
import time
from pathlib import Path

import numpy as np

from schema_net import build_pulse
from snapshot import load_snapshot, save_snapshot
from sparse_net import allocate_pats

BASE = Path(__file__).resolve().parent / "runs" / "v52_2_20260811_183718"  # v53.0
N_TEACH_BABA = 30        # 「叫 爸爸」教学次数
N_TEACH_MAMA = 30        # 「叫 妈妈」教学次数
AMP_LIGHT = 1.0          # 动词轻声（须 ≥θ=1.0 才发放；θ 下 0.5 不发放）
AMP_ARG = 4.0            # 论元强调（PLAN 条件 4：amp=4——论元 v 最高→竞争胜出）
AMP_STRONG = 20.0        # 新词重读（未教论元泛化对照：强调 > 联想边 w_max=16）
REWARD = 2.0             # 每次教学零食量（da_max=2.0 截断）
K = 4                    # 每词模式神经元数
STRONG = 16.0            # 主干/绑定档阈值（build_track_map）
KEY_ARGS = ["爸爸", "妈妈", "爷爷", "奶奶", "妹妹", "哥哥"]
UNSEEN_ARGS = ["妹妹", "哥哥"]     # 未教论元（泛化测试）


def n2w_map(pats):
    """neuron → word 反查（词神经元唯一属于一词——分配制）。"""
    m = {}
    for w, ns in pats.items():
        for x in ns:
            m[int(x)] = w
    return m


def teach_once(ng, pats, seq, amps, reward=REWARD):
    """自然涌现教学一次：零食（DA 门控）→ 说（逐词注入 + 韵律强调）。
    句内：注入拍清 spikes（教学式——无传播驱动）、空拍留痕（trace 衰减 0.5）
    → STDP 只学相邻前驱（叫→爸爸）；句尾再给零食（资格迹兑现 (叫,爸爸) 配对）。"""
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)      # 句间清痕迹（跨次教学不串扰）
    ng.release_da(reward)              # 先给零食——学习开关（da=0 不学）
    for w, amp in zip(seq, amps):
        ng.spikes = np.zeros(ng.n)
        ng.step(build_pulse(ng.n, pats[w], amp), slot=0)
        ng.spikes = np.zeros(ng.n)
        ng.step(np.zeros(ng.n), slot=0)   # 空拍：痕迹衰减（前驱仍 >0.3 阈值）
    ng.release_da(reward)              # 句尾零食——延迟归因兑现 (叫,爸爸)


def recall(ng, pats, seq, amps, max_steps=10, wta_k=None):
    """冻结态检索（零学习改动——learn_gate=False）：
    逐词注入（词间连续——传播链自然延续，注入叠加驱动）→ 空拍至收敛。
    关键：空拍**不清 spikes**——上一拍发放是传播源，清掉即断链
    （联想 drive 就传不出去；_grow_zh.run_recall 同协议）。
    可选 wta_k：WTA 窗口收窄对照（PLAN 条件 3——多候选竞争收窄）。"""
    n2w = n2w_map(pats)
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)
    gate = ng.learn_gate
    wta_old = ng.wta_k
    ng.learn_gate = False
    if wta_k:
        ng.wta_k = wta_k
    timeline = []
    for w, amp in zip(seq, amps):
        ng.step(build_pulse(ng.n, pats[w], amp), slot=0)
        now = {n2w.get(int(x), f"#{x}") for x in np.where(ng.spikes > 0)[0]}
        timeline.append((f"注入{w}", now))
    for _ in range(max_steps):
        ng.step(np.zeros(ng.n), slot=0)
        now = {n2w.get(int(x), f"#{x}") for x in np.where(ng.spikes > 0)[0]}
        timeline.append(("空拍", now))
        if not now:
            break
    ng.learn_gate = gate
    ng.wta_k = wta_old
    return timeline


def edge_weight(ng, pats, pre, post, slot=0):
    """pre→post 全部模式边的权重（均值/最大/条数）。"""
    ws = [ng.W_out[i][slot].get(j, 0.0)
          for i in pats[pre] for j in pats[post]]
    return float(np.mean(ws)), float(np.max(ws)), int(np.sum(np.array(ws) > 0))


def count_edges(ng):
    return sum(len(r) for i in range(ng.n) for r in [ng.W_out[i][0]] if r)


def show_timeline(tl, title):
    print(f"    {title}")
    for tag, words in tl:
        disp = " ".join(sorted(words)) if words else "—"
        print(f"      {tag:>8} → {disp}")


def main():
    t0 = time.time()
    # ── A. 基座自检（实验前内部状态检查）──
    ng, vocab, pats, cursor = load_snapshot(BASE)
    n_edge0 = count_edges(ng)
    print(f"[A] 基座 {BASE.name}: n={ng.n}  边={n_edge0}  "
          f"w_max={ng.w_max}  wta_k={ng.wta_k}  theta={ng.theta}")
    assert n_edge0 == 0, "基座不是零边起点——检查失败"

    # 教学词确认（词表缺失则分配——但 37145 词词表应齐）
    need = set(["叫", "爸爸", "妈妈"]) | set(KEY_ARGS) | set(UNSEEN_ARGS)
    missing = [w for w in need if w not in pats]
    if missing:
        pats, cursor = allocate_pats(ng, missing, K, cursor)
        print(f"    ⚠ 补词表: {missing}")

    print(f"[B] 教学「叫 爸爸」×{N_TEACH_BABA}（奖励 {REWARD} + 论元强调 {AMP_ARG}）")
    curve = []
    for i in range(1, N_TEACH_BABA + 1):
        teach_once(ng, pats, ["叫", "爸爸"], [AMP_LIGHT, AMP_ARG])
        if i in (1, 5, 10, 20, 30):
            m, mx, nn = edge_weight(ng, pats, "叫", "爸爸")
            curve.append((i, m, mx, nn))
            print(f"    第 {i:2d} 次: 叫→爸爸 均值 {m:6.3f} 最大 {mx:6.3f} 边数 {nn}"
                  f"  总边 {count_edges(ng)}")
    m, mx, nn = edge_weight(ng, pats, "叫", "爸爸")
    print(f"    教学完成: 叫→爸爸 = 均值 {m:.3f} 最大 {mx:.3f}（w_max={ng.w_max} 封顶）"
          f"  总边 = {count_edges(ng)}")

    print("[C] 验证（冻结检索 learn_gate=False）")
    show_timeline(recall(ng, pats, ["叫"], [AMP_LIGHT]), "C1 输入「叫」→ 联想 System 1")
    show_timeline(recall(ng, pats, ["叫", "爸爸"], [AMP_LIGHT, AMP_ARG]),
                  "C2 输入「叫 爸爸」→ 回答 System 2")
    show_timeline(recall(ng, pats, ["爸爸"], [AMP_ARG]), "C3 对照「爸爸」")

    print(f"[D] 教学「叫 妈妈」×{N_TEACH_MAMA}（已教论元——竞争）")
    for i in range(1, N_TEACH_MAMA + 1):
        teach_once(ng, pats, ["叫", "妈妈"], [AMP_LIGHT, AMP_ARG])
    for pre, post in [("叫", "爸爸"), ("叫", "妈妈")]:
        m, mx, nn = edge_weight(ng, pats, pre, post)
        print(f"    {pre}→{post} = 均值 {m:.3f} 最大 {mx:.3f} 边数 {nn}")
    show_timeline(recall(ng, pats, ["叫", "妈妈"], [AMP_LIGHT, AMP_ARG]),
                  "D1 输入「叫 妈妈」→ 竞争胜出？（wta_k=20 全带出对照）")
    show_timeline(recall(ng, pats, ["叫", "妈妈"], [AMP_LIGHT, AMP_ARG], wta_k=4),
                  "D2 输入「叫 妈妈」wta_k=4 → 竞争收窄？")
    show_timeline(recall(ng, pats, ["叫"], [AMP_LIGHT]), "D3 输入「叫」→ 联想（多论元并存？）")
    show_timeline(recall(ng, pats, ["叫"], [AMP_LIGHT], wta_k=4),
                  "D4 输入「叫」wta_k=4 → 联想收窄？")

    print(f"[E] 泛化：未教论元（{UNSEEN_ARGS}——PLAN 问题 2 已知弱点，诚实记录）")
    for w in UNSEEN_ARGS:
        show_timeline(recall(ng, pats, ["叫", w], [AMP_LIGHT, AMP_ARG]),
                      f"E1 输入「叫 {w}」（未教，wta_k=20）")
        show_timeline(recall(ng, pats, ["叫", w], [AMP_LIGHT, AMP_ARG], wta_k=4),
                      f"E2 输入「叫 {w}」（未教，wta_k=4）")
        show_timeline(recall(ng, pats, ["叫", w], [AMP_LIGHT, AMP_STRONG], wta_k=4),
                      f"E3 输入「叫 {w}」（未教，wta_k=4 + 强强调 {AMP_STRONG}——"
                      "新词重读：强调 > 联想边 16）")

    # ── F. 存档 ──
    metrics = {
        "emerge_baba": {
            "base": "53.0", "teach_baba": N_TEACH_BABA, "teach_mama": N_TEACH_MAMA,
            "amp": {"light": AMP_LIGHT, "arg": AMP_ARG}, "reward": REWARD,
            "curve": [[i, m, mx, nn] for i, m, mx, nn in curve],
            "final_baba_edge": edge_weight(ng, pats, "叫", "爸爸"),
            "final_mama_edge": edge_weight(ng, pats, "叫", "妈妈"),
            "total_edges": count_edges(ng),
        },
    }
    out = save_snapshot(
        ng, parent="53.0", vocab=vocab, pats=pats, cursor=cursor, metrics=metrics,
        tag=f"自然涌现教学：叫爸爸→爸爸（奖励+论元强调，{N_TEACH_BABA}+{N_TEACH_MAMA} 次）"
            f"+ 未教论元泛化记录（问题 2）", data_fp=str(BASE))
    print(f"[F] 快照: {out}")
    print(f"耗时 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
