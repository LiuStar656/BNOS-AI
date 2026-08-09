# -*- coding: utf-8 -*-
"""举一反三规模扩大压力测试（v2.2 §12.6b 延续）：三个维度扩大规模。

需求（用户 2026-08-10）：继续，扩大规模。

S1-S3 词表规模：100 / 300 / 1000 词（独立链 20/60/200 条 × 5 词），
        验证传递模板在大词表下是否稀释
S4  噪声干扰：300 词独立链 + 300 对随机无关词对（噪声 1 轮 vs 链内 3 轮），
        验证走链不被无关连接带偏（真实词表必然有大量噪声关联）
S5  共享 hub 链网：词被多条链共享（真实语义网结构，如"水"同时连接多个概念），
        验证走链在共享/分支下仍通（如实记录分支竞争）

用法：python _rl_gate_scale.py
"""

import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

from schema_net import build_pulse
from sparse_net import SparseSchemaNet, allocate_pats
from _rl_gate import run_train, teach_pair, walk_chain, SLOTS, SKIP

K = 4
N = 16384           # 1000 词 × 4 = 4000 + 槽位，留 4 倍余量
R = 3
HOP = 10
RUNS = Path(__file__).parent / "runs"

EXTRA = list(SLOTS) + ["是"]


def save_result(data):
    """实验数据留档：runs/{YYYYMMDD_HHMMSS}/result.json（实验必留档规范）。"""
    out = RUNS / datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def make_net(seed=42):
    return SparseSchemaNet(n=N, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                           w_max=16.0, wta_k=K, noise_p=0.06, noise_amp=0.5,
                           refractory=1, rng=np.random.default_rng(seed))


def make_chains(rng, n_chain, len_chain=5, prefix="w"):
    """n_chain 条独立链（链内不共享词）。"""
    pool = [f"{prefix}{i}" for i in range(n_chain * len_chain)]
    rng.shuffle(pool)
    chains, pairs = [], []
    k = 0
    for _ in range(n_chain):
        chain = pool[k:k + len_chain]
        k += len_chain
        chains.append(chain)
        pairs += [(chain[i], chain[i + 1]) for i in range(len_chain - 1)]
    return chains, pairs


def train(ng, pats, pairs, rounds=R, tag=""):
    t0 = time.time()
    for _ in range(rounds):
        for x, y in pairs:
            teach_pair(ng, pats, x, y)
    return time.time() - t0


def walk_ok(ng, pats, chain):
    out = walk_chain(ng, pats, chain[0], HOP)
    names = [chain[0]] + [w for w, _ in out]
    reached = chain[-1] in names            # 推理走通：链尾被访问
    overshoot = reached and names[-1] != chain[-1]   # 联想过冲：到链尾后继续走
    return reached, overshoot, names


def run_scale(seed, n_chain, verbose=True):
    """S1-S3：词表规模测试。"""
    rng = np.random.default_rng(seed)
    chains, pairs = make_chains(rng, n_chain)
    words = list(dict.fromkeys([w for c in chains for w in c]))
    ng = make_net(seed)
    pats, _ = allocate_pats(ng, EXTRA + words, K)
    dt = train(ng, pats, pairs)
    n_ok = n_over = 0
    fails = []
    details = []
    for c in chains:
        reached, overshoot, names = walk_ok(ng, pats, c)
        n_ok += int(reached)
        n_over += int(overshoot)
        details.append({"expected": c, "walked": names,
                        "reached": reached, "overshoot": overshoot})
        if not reached:
            fails.append((c, names))
    rate = n_ok / len(chains)
    if verbose:
        print(f"  [S{3 if n_chain >= 200 else 2 if n_chain >= 60 else 1}] "
              f"词表 {len(words)} / 实例 {len(pairs)} / {len(chains)} 链 → "
              f"推理走通 {rate:.1%}（{n_ok}/{len(chains)}），"
              f"联想过冲 {n_over} 条，训练 {dt:.1f}s")
        for c, names in fails[:5]:
            print(f"    ❌ 期望 {' → '.join(c)} | 实际 {' → '.join(names)}")
    return rate, fails, details


def run_noise(seed=42, verbose=True):
    """S4：300 词独立链 + 300 对随机噪声词（噪声 1 轮 vs 链内 3 轮）。"""
    rng = np.random.default_rng(seed)
    chains, pairs = make_chains(rng, 60)          # 300 词独立链
    words = list(dict.fromkeys([w for c in chains for w in c]))
    # 300 对随机噪声（从词表内随机取，可能跨链）
    noise_pairs = [(rng.choice(words), rng.choice(words)) for _ in range(300)]
    noise_pairs = [(x, y) for x, y in noise_pairs if x != y]
    ng = make_net(seed)
    pats, _ = allocate_pats(ng, EXTRA + words, K)
    dt1 = train(ng, pats, pairs, rounds=R)
    dt2 = train(ng, pats, noise_pairs, rounds=1)  # 噪声只学 1 轮
    n_ok = n_over = 0
    fails = []
    details = []
    for c in chains:
        reached, overshoot, names = walk_ok(ng, pats, c)
        n_ok += int(reached)
        n_over += int(overshoot)
        details.append({"expected": c, "walked": names,
                        "reached": reached, "overshoot": overshoot})
        if not reached:
            fails.append((c, names))
    rate = n_ok / len(chains)
    if verbose:
        print(f"  [S4] 噪声干扰：{len(words)} 词链 + {len(noise_pairs)} 对随机噪声"
              f"（噪声 1 轮 vs 链内 3 轮）→ 推理走通 {rate:.1%}（{n_ok}/{len(chains)}），"
              f"联想过冲 {n_over} 条，训练 {dt1 + dt2:.1f}s")
        for c, names in fails[:5]:
            print(f"    ❌ 期望 {' → '.join(c)} | 实际 {' → '.join(names)}")
    return rate, n_over, fails, details


def run_shared_hub(seed=42, verbose=True):
    """S5：共享 hub 链网（真实语义网：词被多条链共享）。

    结构：X 是 hub，两条链共享它——A1→X→B1、A2→X→B2。
    验证：从 A1/A2 走链都能到达 X（共享中间项可复用），
    到 X 后分支竞争（B1/B2 等权）如实记录——贪心走链取第一个最强后继。
    """
    rng = np.random.default_rng(seed)
    chains = [["A1", "X", "B1"], ["A2", "X", "B2"]]
    pairs = [(c[i], c[i + 1]) for c in chains for i in range(len(c) - 1)]
    # 再加两条独立链增加规模干扰
    extra_chains, extra_pairs = make_chains(rng, 8, prefix="e")
    words = list(dict.fromkeys([w for c in chains + extra_chains for w in c]))
    ng = make_net(seed)
    pats, _ = allocate_pats(ng, EXTRA + words, K)
    train(ng, pats, pairs + extra_pairs)
    results = {}
    for start in ("A1", "A2"):
        out = walk_chain(ng, pats, start, HOP)
        names = [start] + [w for w, _ in out]
        reached_hub = "X" in names
        # 分支后是否还走对（A1→B1、A2→B2）
        target = {"A1": "B1", "A2": "B2"}[start]
        reached_own_branch = target in names
        results[start] = (reached_hub, reached_own_branch, names)
    if verbose:
        print("  [S5] 共享 hub 链网：A1→X→B1、A2→X→B2（X 被两条链共享，分支等权）")
        for start, (hub, branch, names) in results.items():
            print(f"    {start}: {' → '.join(names)} → "
                  f"{'✅ 经共享 hub' if hub else '❌ 未达 hub'}，"
                  f"{'✅ 走对分支' if branch else '❌ 分支竞争（上下文缺口）'}")
    return results


def run_shared_branch(seed=42, verbose=True):
    """S6：共享 hub 分支权重不对称——分支可区分时能否走对。

    与 S5 同构，但 B1 学 3 轮、B2 只学 1 轮 → X 出边 B1(3轮) > B2(1轮)。
    验证：权重不对称时贪心走链能选对强分支（弱分支被权重差过滤）。
    """
    rng = np.random.default_rng(seed)
    chains = [["A1", "X", "B1"], ["A2", "X", "B2"]]
    words = list(dict.fromkeys([w for c in chains for w in c]))
    ng = make_net(seed)
    pats, _ = allocate_pats(ng, EXTRA + words, K)
    # A1→X→B1 学 3 轮（强分支）；A2→X→B2 只学 1 轮（弱分支）
    for _ in range(R):
        for x, y in [("A1", "X"), ("X", "B1")]:
            teach_pair(ng, pats, x, y)
    for x, y in [("A2", "X"), ("X", "B2")]:
        teach_pair(ng, pats, x, y)
    results = {}
    for start, target in (("A1", "B1"), ("A2", "B2")):
        out = walk_chain(ng, pats, start, HOP)
        names = [start] + [w for w, _ in out]
        results[start] = (target in names, names)
    if verbose:
        print("  [S6] 分支权重不对称：A1→X→B1（3 轮）、A2→X→B2（1 轮）")
        for start, (ok, names) in results.items():
            print(f"    {start}: {' → '.join(names)} → "
                  f"{'✅ 权重强分支优先' if ok else '❌ 走错'}")
    return results


def main():
    t0 = time.time()
    print("═══ 举一反三规模扩大压力测试 ═══\n")

    r1, f1, d1 = run_scale(42, 20)     # 100 词
    r2, f2, d2 = run_scale(42, 60)     # 300 词
    r3, f3, d3 = run_scale(42, 200)    # 1000 词
    r4, o4, f4, d4 = run_noise(42)
    s5 = run_shared_hub(42)
    s6 = run_shared_branch(42)

    ok_s1 = r1 == 1.0
    ok_s2 = r2 == 1.0
    ok_s3 = r3 == 1.0
    ok_s4 = r4 == 1.0
    ok_s5 = all(branch for _, branch, _ in s5.values())
    ok_s6 = all(ok for ok, _ in s6.values())
    ok_all = ok_s1 and ok_s2 and ok_s3 and ok_s4 and ok_s5 and ok_s6

    print("\n═══ 汇总 ═══")
    print(f"  [S1] 100 词（20 链）: {'✅' if ok_s1 else '❌'} {r1:.1%}")
    print(f"  [S2] 300 词（60 链）: {'✅' if ok_s2 else '❌'} {r2:.1%}")
    print(f"  [S3] 1000 词（200 链）: {'✅' if ok_s3 else '❌'} {r3:.1%}")
    print(f"  [S4] 噪声干扰: 推理走通 {'✅' if ok_s4 else '❌'} {r4:.1%}"
          f"，联想过冲 {o4} 条（终止缺口）")
    print(f"  [S5] 共享 hub 等权分支: {'✅' if ok_s5 else '❌'}"
          f"（上下文缺口，详见上方）")
    print(f"  [S6] 分支权重不对称: {'✅' if ok_s6 else '❌'}")
    print(f"\n═══ 总验收: {'规模扩大全通过 ✅' if ok_all else '有缺口 ❌'} "
          f"（{time.time() - t0:.0f}s）═══")

    # ── 实验数据留档 ──
    data = {
        "desc": "举一反三规模扩大压力测试（S1-S6）",
        "params": {"K": K, "N": N, "R": R, "HOP": HOP, "seed": 42},
        "summary": {
            "S1_100词": r1, "S2_300词": r2, "S3_1000词": r3,
            "S4_噪声推理走通": r4, "S4_联想过冲条数": o4,
            "S5_共享hub等权分支全对": ok_s5,
            "S6_权重不对称分支全对": ok_s6,
            "all_ok": ok_all,
        },
        "S1_100词_details": d1,
        "S2_300词_details": d2,
        "S3_1000词_details": d3,
        "S4_噪声_details": d4,
        "S5_共享hub": {k: {"reached_hub": h, "own_branch": b, "walked": n}
                       for k, (h, b, n) in s5.items()},
        "S6_权重不对称": {k: {"ok": o, "walked": n}
                        for k, (o, n) in s6.items()},
    }
    out = save_result(data)
    print(f"\n实验数据已留档: {out / 'result.json'}")


if __name__ == "__main__":
    main()
