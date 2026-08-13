# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""稳定工作记忆 + 压力测试（2026-08-11）。

目标：隔离保持回路（gain 调制——WTA 排序增益）——稳定工作记忆。
教训（_exp_wm.py）：全局竞争下"更强的边"无效（功能词 256 垄断）——
工作记忆需要隔离空间（大脑前额叶对应——gain 是现成的隔离机制）。

机制：
  保持组 H（4 新神经元——专用）
  绑定：饿↔H 双向（写入口 + 读出口）
  自持：H 内部互连（循环——delay activity）
  增益：H 的 gain 调高（WTA 排序 v×gain——竞争优先）
  写入：注入饿 → 饿发 → H 驱动 → H 发（gain 优先）→ 自持
  读出：H 发 → 饿 驱动（累积——超过功能词）→ 饿 回忆

压力测试：
  远度：维持多少 tick（N=100 窗口——发放曲线/稳定窗口）
  精度：回忆保真（读出的 top 是"饿"不是噪声——每 10 tick 检查）
  边界：gain/绑定边权 参数扫描 → 维持时长 vs 参数（最小稳定参数）

用法：python _exp_wm2.py（纯内存）
"""

import numpy as np
from schema_net import build_pulse
from snapshot import load_version


def build_hold(ng, pats, cursor, word="饿", k=4, gain_v=8.0, bind_w=64.0,
               loop_w=64.0):
    """建保持回路：保持组 H（k 神经元）——绑定词 ↔ 自持 ↔ 增益。"""
    from sparse_net import allocate_pats
    p, cursor = allocate_pats(ng, [f"__H_{word}__"], k, cursor)
    H = p[f"__H_{word}__"]
    W = ng.W_out
    # 绑定（双向：饿→H 写 / H→饿 读）
    for i in H:
        for j in pats[word]:
            W[i][0][j] = bind_w      # H→饿（读出）
            W[j][0][i] = bind_w      # 饿→H（写入）
    # 自持（H 内部互连——循环）
    for i in H:
        for j in H:
            if i != j:
                W[i][0][j] = loop_w
    # 增益（WTA 排序优先——隔离机制）
    ng.gain[H] = gain_v
    return H, cursor


def run_hold(ng, pats, n2w, word="饿", H=None, steps=100, clear_at=None,
             record_word=None):
    """注入词 → 空白推进 → 返回 词/H 的发放序列。"""
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)
    ng.step(build_pulse(ng.n, pats[word]), slot=0)
    word_set = set(pats[word])
    h_set = set(H) if H is not None else set()
    trace_w, trace_h, trace_top = [], [], []
    for t in range(1, steps + 1):
        ng.step(np.zeros(ng.n), slot=0)
        fired = np.where(ng.spikes > 0)[0]
        trace_w.append(sum(1 for i in fired if i in word_set))
        trace_h.append(sum(1 for i in fired if i in h_set))
        # 精度：回忆读出的 top 词（H 发 → 饿 驱动——检查饿 激活）
        if record_word and t % 10 == 0:
            v_e = ng.v[pats[word]].max()
            v_noise = ng.v[pats["了"]].max() if "了" in pats else 0
            trace_top.append((round(float(v_e), 1),
                              round(float(v_noise), 1)))
    return trace_w, trace_h, trace_top


def main():
    print("═══ 稳定工作记忆（隔离保持回路）+ 压力测试 ═══\n")
    print("（纯内存——不保存快照）\n")
    ng, vocab, pats, cursor = load_version("35.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}

    # ── 建保持回路（饿）──
    H, cursor = build_hold(ng, pats, cursor)
    print(f"[保持回路] H={H}（gain={ng.gain[H[0]]:g}，"
          f"绑定/自持边 64）\n")

    # ── ① 远度测试：100 tick 维持窗口 ──
    print("── ① 远度（维持时长——100 tick 窗口）──")
    tw, th, tt = run_hold(ng, pats, n2w, steps=100, H=H, record_word="饿")
    n_h = sum(1 for x in th if x > 0)
    n_w = sum(1 for x in tw if x > 0)
    print(f"  饿 发放：{n_w}/100 tick（H 发放：{n_h}/100 tick）")
    print(f"  发放样例：t1-10 饿={tw[:10]} H={th[:10]}")
    print(f"           t50-60 饿={tw[49:60]} H={th[49:60]}")
    print(f"           t90-100 饿={tw[89:]} H={th[89:]}")
    # 稳定窗口（最后一次发放位置——之后是否持续）
    last = max((i for i, x in enumerate(th) if x > 0), default=-1)
    print(f"  最后维持 tick：{last + 1}/100"
          f"（{'✅ 全程维持' if last > 80 else '⚠️ 中途衰减'}）")

    # ── ② 精度测试：每 10 tick 检查回忆保真（饿 vs 噪声 了）──
    print("\n── ② 精度（回忆保真——饿 vs 噪声）──")
    print("  tick  饿激活  噪声(了)  保真")
    ok_p = 0
    for i, (ve, vn) in enumerate(tt):
        t = (i + 1) * 10
        keep = ve > vn
        ok_p += keep
        print(f"  {t:>4}  {ve:>6.1f}  {vn:>6.1f}  {'✅' if keep else '❌'}")
    print(f"  精度：{ok_p}/{len(tt)}（饿 激活 > 噪声 的比例）")

    # ── ③ 边界：增益/边权参数扫描 → 维持时长 ──
    print("\n── ③ 边界（参数扫描——最小稳定参数）──")
    print(f"  {'增益':<6}{'绑定边':<8}{'维持tick':<10}{'判定'}")
    for gain_v in [2, 4, 8, 16]:
        for bind_w in [16, 32, 64]:
            ng2, v2, p2, c2 = load_version("35.0")
            H2, _ = build_hold(ng2, p2, c2, gain_v=gain_v, bind_w=bind_w)
            tw2, th2, _ = run_hold(ng2, p2, n2w, steps=50, H=H2)
            n = sum(1 for x in th2 if x > 0)
            ok = "✅ 稳定" if n >= 40 else ("⚠️ 部分" if n >= 10 else "❌ 失效")
            print(f"  {gain_v:<6}{bind_w:<8}{n:<10}{ok}")

    print(f"\n═══ 结论 ═══")
    print(f"  远度：保持回路维持 {n_h}/100 tick（稳定窗口见上）")
    print(f"  精度：{ok_p}/{len(tt)}（回忆保真率）")
    print(f"  边界：参数扫描表——最小稳定参数（增益/绑定边）")


if __name__ == "__main__":
    main()
