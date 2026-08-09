# -*- coding: utf-8 -*-
"""举一反三泛化压力测试（v2.2 §12.6 扩展）：五个递进级别，验证"彻底泛化"。

需求（用户 2026-08-10）：继续测试，直到举一反三能力彻底泛化。

L1 规模泛化：词表 40+、实例 15+，传递模板仍成立（多链随机生成）
L2 链长泛化：4 跳传递链（A→B→C→D→E）可达
L3 新词外推：训练中从未出现过的全新词，只学前提 → 推出结论
L4 中间项断开：验证门固化直连后，把中间项出边清零（"拿掉水"），
               直连仍在 = 组块化彻底（不再是 A→B→C 借道）
L5 随机性验证：多随机种子重复 L1，统计成功率排除偶然

用法：python _rl_gate_stress.py
"""

import time
from collections import Counter

import numpy as np

from schema_net import build_pulse
from sparse_net import SparseSchemaNet, allocate_pats
from _rl_gate import run_train, teach_pair, walk_chain, direct_edge, SLOTS, SKIP

K = 4
N = 4096
R = 3
HOP = 10            # 走链最大跳数（覆盖 4 跳链 + 余量）

# 槽位 + 系词（走链候选排除）
EXTRA = list(SLOTS) + ["是"]


def make_net(seed=42):
    ng = SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=16.0, wta_k=K, noise_p=0.06, noise_amp=0.5,
                         refractory=1, rng=np.random.default_rng(seed))
    return ng


def make_chains(rng, n_chain=5, len_chain=5, vocab_pool=60):
    """生成 n_chain 条独立链（链内不共享词），返回 (chains, pairs)。"""
    pool = [f"w{i}" for i in range(vocab_pool)]
    rng.shuffle(pool)
    chains, pairs = [], []
    k = 0
    for _ in range(n_chain):
        chain = pool[k:k + len_chain]
        k += len_chain
        chains.append(chain)
        pairs += [(chain[i], chain[i + 1]) for i in range(len_chain - 1)]
    return chains, pairs


def train_pairs(ng, pats, pairs, rounds=R):
    for _ in range(rounds):
        for x, y in pairs:
            teach_pair(ng, pats, x, y)


def chain_ok(ng, pats, chain):
    """走链从链首出发，hops 内是否到达链尾。"""
    out = walk_chain(ng, pats, chain[0], HOP)
    names = [chain[0]] + [w for w, _ in out]
    return names[-1] == chain[-1], names


def test_l1(seed=42, n_chain=5, len_chain=5, verbose=True):
    """L1+L2：规模泛化（40+ 词）+ 链长泛化（4 跳链）。"""
    rng = np.random.default_rng(seed)
    chains, pairs = make_chains(rng, n_chain, len_chain)
    ng = make_net(seed)
    words = list(dict.fromkeys([w for c in chains for w in c]))
    pats, _ = allocate_pats(ng, EXTRA + words, K)
    train_pairs(ng, pats, pairs)
    n_ok = 0
    details = []
    for c in chains:
        ok, names = chain_ok(ng, pats, c)
        n_ok += int(ok)
        details.append((c, ok, names))
    rate = n_ok / len(chains)
    if verbose:
        print(f"  [L1/L2] 词表 {len(words)}，实例 {len(pairs)}，链 {len(chains)}×{len_chain} 跳"
              f"→ 全链走通率 {rate:.0%}（{n_ok}/{len(chains)}）")
        for c, ok, names in details:
            print(f"    {'✅' if ok else '❌'} {' → '.join(c)} | 实际 {' → '.join(names)}")
    return rate, details


def test_l3(seed=42, verbose=True):
    """L3 新词外推：训练从未出现的词，只学前提 → 推出结论。"""
    rng = np.random.default_rng(seed)
    # 训练用一组普通词（保证 S/O/是 hub 建立）
    train_words = [f"t{i}" for i in range(12)]
    train_pairs = [(train_words[i], train_words[i + 1]) for i in range(0, 11, 2)]
    # 全新词：训练时零连接
    new = ["麒麟", "瑞兽", "神兽"]          # 新词从未训练
    ng = make_net(seed)
    pats, _ = allocate_pats(ng, EXTRA + train_words + new, K)
    train_pairs_ng(ng, pats, train_pairs)
    # 只学新前提（麒麟是瑞兽、瑞兽是神兽），结论"麒麟是神兽"绝不教
    teach_pair(ng, pats, "麒麟", "瑞兽")
    teach_pair(ng, pats, "瑞兽", "神兽")
    out = walk_chain(ng, pats, "麒麟", HOP)
    names = ["麒麟"] + [w for w, _ in out]
    ok = names[-1] == "神兽"
    if verbose:
        print(f"  [L3] 新词外推：麒麟 → 瑞兽 → 神兽（三词训练零共现）")
        print(f"    实际: {' → '.join(names)} → {'✅ 推出新结论' if ok else '❌ 失败'}")
    return ok, names


def train_pairs_ng(ng, pats, pairs):
    for x, y in pairs:
        teach_pair(ng, pats, x, y)


def test_l4(seed=42, verbose=True):
    """L4 中间项断开：固化直连后"拿掉水"，直连仍在（组块化彻底）。

    摘除中间项 B = 清 B 出边 + 清所有指向 B 的边（A→B 也没了）。
    固化后 A 只剩直连 C 可达；对照（未固化）A 无路可走。
    """
    ng = make_net(seed)
    words = ["A", "B", "C", "D"]
    pats, _ = allocate_pats(ng, EXTRA + words, K)
    for x, y in [("A", "B"), ("B", "C"), ("C", "D")]:
        teach_pair(ng, pats, x, y)

    # 对照组：未固化前就摘除 B
    ng2 = make_net(seed)
    pats2, _ = allocate_pats(ng2, EXTRA + words, K)
    for x, y in [("A", "B"), ("B", "C"), ("C", "D")]:
        teach_pair(ng2, pats2, x, y)
    remove_word(ng2, pats2, "B")
    out_ctrl = walk_chain(ng2, pats2, "A", HOP)
    names_ctrl = ["A"] + [w for w, _ in out_ctrl]
    ok_ctrl_broken = not any(w == "C" for w in names_ctrl[1:])

    # 实验组：验证门固化 A→C 后再摘除 B
    before = direct_edge(ng, pats, "A", "C")
    teach_pair(ng, pats, "A", "C")
    after = direct_edge(ng, pats, "A", "C")
    remove_word(ng, pats, "B")
    out = walk_chain(ng, pats, "A", HOP)
    names = ["A"] + [w for w, _ in out]
    ok_direct = any(w == "C" for w in names[1:])

    if verbose:
        print(f"  [L4] 中间项断开（拿掉 B）：A→B→C→D 跟读")
        print(f"    对照组（未固化即摘除 B）: {' → '.join(names_ctrl)} → "
              f"{'✅ 断开（证明必须靠直连）' if ok_ctrl_broken else '❌ 竟还通？'}")
        print(f"    实验组（固化 A→C 后摘除 B，直连 {before:.1f}→{after:.1f}）:")
        print(f"      {' → '.join(names)} → "
              f"{'✅ 直连仍在（组块化彻底）' if ok_direct else '❌ 断开'}")
    return ok_direct and ok_ctrl_broken, (before, after), names


def remove_word(ng, pats, w):
    """从网络摘除词 w：清出边 + 清所有指向它的边（"拿掉水"）。"""
    for i in pats[w]:
        ng.W_out[i][0].clear()
    for i in range(ng.n):
        row = ng.W_out[i][0]
        if row:
            for j in pats[w]:
                row.pop(j, None)


def test_l5(seeds, n_chain=5, len_chain=5, verbose=True):
    """L5 随机性验证：多种子重复 L1，成功率统计。"""
    rates = []
    for s in seeds:
        rate, _ = test_l1(s, n_chain, len_chain, verbose=False)
        rates.append(rate)
    rates = np.array(rates)
    ok = rates.mean() >= 0.9
    if verbose:
        print(f"  [L5] 随机性验证：{len(seeds)} 个种子全链走通率 "
              f"均值 {rates.mean():.0%}，最低 {rates.min():.0%}"
              f" → {'✅ 稳定泛化' if ok else '❌ 不稳定'}")
        print(f"    seeds={seeds}, rates={[f'{r:.0%}' for r in rates]}")
    return ok, rates


def main():
    t0 = time.time()
    print("═══ 举一反三泛化压力测试 ═══\n")

    ok_l1, _ = test_l1(verbose=True, n_chain=8, len_chain=5)   # 40 词 ≥ 40+ 门槛
    ok_l3, _ = test_l3(verbose=True)
    ok_l4, _, _ = test_l4(verbose=True)
    ok_l5, _ = test_l5([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], n_chain=8, verbose=True)

    print("\n═══ 汇总 ═══")
    print(f"  [L1] 规模泛化（40 词/32 实例）: {'✅' if ok_l1 == 1.0 else '❌'} {ok_l1:.0%}")
    print(f"  [L2] 链长泛化（4 跳）: 已含于 L1 全链走通率")
    print(f"  [L3] 新词外推: {'✅' if ok_l3 else '❌'}")
    print(f"  [L4] 中间项断开（组块化彻底）: {'✅' if ok_l4 else '❌'}")
    print(f"  [L5] 随机性稳定: {'✅' if ok_l5 else '❌'}")
    ok_all = ok_l1 == 1.0 and ok_l3 and ok_l4 and ok_l5
    print(f"\n═══ 总验收: {'彻底泛化 ✅' if ok_all else '未彻底泛化 ❌'} "
          f"（{time.time() - t0:.0f}s）═══")


if __name__ == "__main__":
    main()
