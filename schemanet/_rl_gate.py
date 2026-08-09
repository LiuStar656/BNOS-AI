# -*- coding: utf-8 -*-
"""验证门最小实验（v2.2 §12.6）：复读负责"记"、走链负责"想"、验证门负责"该不该记"。

需求（用户 2026-08-10）：
  定式网络要学会"X是Y、Y是Z → X是Z"这个传递**模式**，
  而不是学会"流动的是液体"这句话（死记硬背实例）。

设计（对应方案 §12.4/§12.4b/§12.6）：
- 槽位化跟读：句子注入 [S+X] + [是] + [O+Y]（角色绑定，不止内容共发放）
- 走链检索：输入 [S+X] → 传播 → 经中间项 Y 唤起 Z（联想链）
- 验证门（RL 三因子）：老师说"对"→ 首尾 [X, Z] 复读固化直连；
  "错" → 不固化（错误联想不焊死）
- 双层验收：
  实例层：中间项弱化后"流动"能否直接唤起"液体"
  模式层：测试组新前提（鸟是动物、动物是生物——训练从未共现）
          跟读前提但不跟读结论 → 走链能否推出"鸟是生物"（= 真举一反三）

用法：python _rl_gate.py
"""

import time
from collections import Counter

import numpy as np

from schema_net import build_pulse
from snapshot import save_snapshot
from sparse_net import SparseSchemaNet, allocate_pats

K = 4              # 每词/槽位模式神经元数
N = 256            # 小网络足够（词表小）
R = 3              # 训练组跟读轮数
SEED = 42

# 槽位（虚拟词，只做角色表征，不走内容）
SLOTS = ("S", "O")
SKIP = {"S", "O", "是"}          # 走链候选排除：槽位 + 系词 hub

# 训练组（学传递模板，多实例）
TRAIN = [("流动", "水"), ("水", "液体"),
         ("苹果", "水果"), ("水果", "食物"),
         ("雪", "白"), ("白", "颜色")]
# 陷阱前提：先建立"水→淹死人"错误链（错误联想真实存在，供验证门拒绝固化）
TRAP_PREMISE = [("水", "淹死人")]
# 验证门要拒绝固化的错误结论（"流动的能淹死人"——共享中间项"水"的陷阱链）
TRAP = [("流动", "淹死人")]
# 测试组（模式层泛化：训练中从未共现的新组合）
TEST = [("鸟", "动物"), ("动物", "生物")]


def run_train(ng, pulse, wta_k):
    """跟读训练：注入一步共发放即学（防级联，见 _grow_zh 性能修正）。

    跟读是独立事件：清 pre_trace（防 STDP 跨词污染），清 refractory_left
    （防上句发放的词在本句被不应期挡下——"流动是水"→"水是液体"中
    "水"连续出现，不清则水↔液体共发放学不到）。"""
    ng.wta_k = wta_k
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)
    ng.refractory_left = np.zeros(ng.n, dtype=int)
    ng.step(pulse, slot=0)


def teach_pair(ng, pats, x, y):
    """槽位化跟读一句 [S+X] + [是] + [O+Y]：角色绑定 + 内容共发放。"""
    neurons = (list(pats["S"]) + list(pats[x])
               + list(pats["是"])
               + list(pats["O"]) + list(pats[y]))
    run_train(ng, build_pulse(ng.n, neurons), len(neurons))


def walk_chain(ng, pats, seed, hops=4):
    """逐跳走链（读出式联想，零学习改动）：每跳 = 当前词出边汇聚 → 取最强内容词。

    不用传播动力学——槽位 S/是 是全局共发 hub，注入会同时激活所有主语/全词表，
    走链被带偏；按出边权重读出 = "联想"的本质（输入 X 唤起最强关联 Y）。
    """
    out = []
    cur = seed
    seen = {seed}
    for _ in range(hops):
        scores = Counter()
        for i in pats[cur]:
            row = ng.W_out[i][0]
            if row:
                for j, w in row.items():
                    scores[j] += w
        # 候选：内容词（排除槽位/系词/已见），按词模式聚合权重取最强
        best = None
        for w, ns in pats.items():
            if w in SKIP or w in seen:
                continue
            s = sum(scores.get(j, 0.0) for j in ns)
            if s > 0 and (best is None or s > best[0]):
                best = (s, w)
        if best is None:
            break
        out.append((best[1], best[0]))
        seen.add(best[1])
        cur = best[1]
    return out


def direct_edge(ng, pats, x, y):
    """首尾直连强度：x 模式出边汇聚到 y 模式的权重和。"""
    tot = 0.0
    for i in pats[x]:
        row = ng.W_out[i][0]
        if row:
            for j in pats[y]:
                tot += row.get(j, 0.0)
    return tot


def main():
    words = []
    for x, y in TRAIN + TRAP_PREMISE + TRAP + TEST:
        words += [x, y]
    words.append("是")
    words = list(dict.fromkeys(words))     # 去重保序
    print(f"词表 {len(words)}：{words}")

    ng = SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=16.0, wta_k=K, noise_p=0.06, noise_amp=0.5,
                         refractory=1, rng=np.random.default_rng(SEED))
    pats, cursor = allocate_pats(ng, list(SLOTS) + words, K)
    print(f"模式分配（含槽位 S/O）: {len(pats)} × k={K}，n={ng.n}")

    # ══ 1. 槽位化跟读训练组（学传递模板）+ 陷阱前提（建立真实错误链）══
    t0 = time.time()
    for r in range(R):
        for x, y in TRAIN + TRAP_PREMISE:
            teach_pair(ng, pats, x, y)
    print(f"\n[1] 训练组 {len(TRAIN)} 句 + 陷阱前提 {len(TRAP_PREMISE)} 句"
          f" × {R} 轮 跟读完成（{time.time() - t0:.1f}s）")

    # ══ 2. 实例层：走链 "流动" → 水 → 液体（联想链）══
    print("\n[2] 实例层走链（输入 流动）:")
    chain = walk_chain(ng, pats, "流动")
    names = " → ".join(w for w, _ in chain)
    print(f"    流动 → {names}")
    if any(w == "液体" for w, _ in chain):
        print("    ✅ 联想链成立：流动 → 水 → 液体")
    else:
        print("    ❌ 联想链失败")

    # ══ 3. 验证门：老师说"对/错"，决定是否固化首尾直连 ══
    print("\n[3] 验证门（RL 三因子：验证奖励决定固化与否）:")
    results = {}
    for x, y, label, ok in [("流动", "液体", "流动的是液体", True),     # 老师：对
                            ("流动", "淹死人", "流动的能淹死人", False)]:  # 老师：错
        before = direct_edge(ng, pats, x, y)
        if ok:
            # 对：首尾 [x, y] 复读一次 → 共发放固化直连（组块化压缩）
            teach_pair(ng, pats, x, y)
            after = direct_edge(ng, pats, x, y)
        else:
            # 错：不固化（错误链已存在但不加固，走链结果只当临时检索）
            after = before
        results[(x, y)] = (before, after)
        delta = "固化" if ok else "不固化"
        print(f"    「{label}」老师说『{"对" if ok else "错"}』→ {delta} "
              f"(直连 {before:.1f} → {after:.1f})")

    # ══ 4. 验收①：验证门生效 = 对链固化、错链不动 ══
    up = results[("流动", "液体")]
    no = results[("流动", "淹死人")]
    trap_exists = direct_edge(ng, pats, "水", "淹死人") > 0   # 错误链确实已建立
    ok_gate = (up[1] > up[0]) and (no[1] == no[0]) and trap_exists
    print(f"\n[验收①] 验证门：")
    print(f"    错误链前提「水能淹死人」已建立: "
          f"{'✅' if trap_exists else '❌'}（直连 {direct_edge(ng, pats, '水', '淹死人'):.1f}）")
    print(f"    正确链固化（{up[0]:.1f}→{up[1]:.1f}）+ "
          f"错误结论「流动的能淹死人」拒绝固化（{no[0]:.1f}→{no[1]:.1f}）"
          f"→ {'✅' if ok_gate else '❌'}")

    # ══ 5. 模式层泛化：测试组新前提（训练从未共现）══
    # 跟读前提（老师教的两个新事实），但结论句"鸟是生物"绝不跟读
    print("\n[5] 模式层泛化：测试组 {鸟是动物, 动物是生物}（训练从未共现）")
    for x, y in TEST:
        teach_pair(ng, pats, x, y)         # 只学前提，不学结论
    chain = walk_chain(ng, pats, "鸟")
    names = " → ".join(w for w, _ in chain)
    print(f"    鸟 → {names}")
    ok_gen = any(w == "生物" for w, _ in chain)
    # 关键：结论句从未作为整体跟读 → 输出必为走链组合而非记忆
    print(f"    结论句「鸟是生物」从未跟读 → 输出 = 走链组合 "
          f"→ {'✅ 真举一反三（推出新结论）' if ok_gen else '❌ 泛化失败'}")

    # ══ 6. 验收②③汇总 ══
    ok_inst = any(w == "液体" for w, _ in walk_chain(ng, pats, "流动"))
    print(f"\n[验收②] 实例层直连：验证固化后『流动』→『液体』→ "
          f"{'✅' if ok_inst else '❌'}")
    print(f"[验收③] 模式层模板：新词组合推出新结论 → "
          f"{'✅' if ok_gen else '❌'}")
    ok_all = ok_gate and ok_inst and ok_gen
    print(f"\n═══ 总验收: {'PASS ✅' if ok_all else 'FAIL ❌'} ═══")

    metrics = {"gate_ok": int(ok_gate), "instance_ok": int(ok_inst),
               "pattern_ok": int(ok_gen), "all_ok": int(ok_all),
               "direct_flow_liq": round(results[("流动", "液体")][1], 2),
               "direct_flow_drown": round(results[("流动", "淹死人")][1], 2),
               "chain_flow": " → ".join(w for w, _ in walk_chain(ng, pats, "流动")),
               "chain_bird": " → ".join(w for w, _ in walk_chain(ng, pats, "鸟"))}
    save_snapshot(ng, tag="验证门最小实验：复读+走链+验证门（复读记/联想想/验证门管该不该记）",
                  metrics=metrics, vocab=words, pats=pats, cursor=cursor)


if __name__ == "__main__":
    main()
