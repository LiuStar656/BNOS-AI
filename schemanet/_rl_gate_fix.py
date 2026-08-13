# -*- coding: utf-8 -*-
"""补缺口实验（v2.2 §12.6b 缺口修复）：终止信号 + 上下文调制。

背景（规模压力测试暴露两个缺口）：
  - 终止缺口（S4）：贪心走链无停止判据，57/60 条沿噪声弱连接无限蔓延
  - 上下文缺口（S5/S6）：每跳只按当前词出边选，不知道"从哪来"，
    共享 hub 等权分支随机选、权重不对称时全聚到强分支

修复机制（本实验验证）：
  1. 整链跟读：训练时把整条链作为一句复读（链内非相邻词也共发放
     → 同链词建立弱直连）——为路径聚合提供信号
  2. 路径聚合走链 walk_chain_ctx：每步候选得分 = 路径上所有已见词
     出边聚合（工作记忆：记住起点/路径来调制分支选择）
  3. 强度衰减终止：下一步候选强度 < 上一步 × stop_ratio → 停止
     （联想收敛，不沿弱连接蔓延）

对照设计：
  - 旧走链 walk_chain（贪心，无上下文无终止）vs 新走链 walk_chain_ctx
  - 同一网络（含整链跟读），只改检索方式 → 提升可归因于检索机制
  - S4 复测：噪声场景下过冲率应降为 0，推理走通保持 100%
  - S5 复测：共享 hub 等权分支 → A1→B1、A2→B2 全对
  - S6 复测：分支权重不对称 → 全对（弱分支不再被强分支吸走）

用法：python _rl_gate_fix.py
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
N = 16384
R = 3                # 相邻对跟读轮数（主链方向性，强度 3+1）
R_FULL = 1           # 整链跟读轮数（非相邻弱连接，强度 1）
HOP = 10
STOP_RATIO = 0.4     # 终止：下一步强度 < 上一步 × 0.4 → 停止
RUNS = Path(__file__).parent / "runs"

EXTRA = list(SLOTS) + ["是"]


def save_result(data):
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


def train(ng, pats, pairs, chains, rounds=R, full_rounds=R_FULL, tag=""):
    """相邻对跟读（主链）+ 整链跟读（链内非相邻弱连接，供上下文调制）。"""
    t0 = time.time()
    for _ in range(rounds):
        for x, y in pairs:
            teach_pair(ng, pats, x, y)
    for _ in range(full_rounds):
        for c in chains:
            neurons = [i for w in c for i in pats[w]]
            run_train(ng, build_pulse(ng.n, neurons), len(neurons))
    return time.time() - t0


def walk_chain_ctx(ng, pats, seed, hops=HOP, stop_ratio=STOP_RATIO):
    """路径聚合走链 + 强度衰减终止。

    每步候选得分 = 路径上所有已见词出边的聚合（工作记忆：路径上下文
    调制分支选择）；下一步强度 < 上一步×ratio → 停止（联想收敛）。
    """
    out = []
    path = [seed]
    seen = {seed}
    prev_s = None
    for _ in range(hops):
        scores = Counter()
        for p in path:                       # 聚合整个路径的上下文
            for i in pats[p]:
                row = ng.W_out[i][0]
                if row:
                    for j, w in row.items():
                        scores[j] += w
        best = None
        for w, ns in pats.items():
            if w in SKIP or w in seen:
                continue
            s = sum(scores.get(j, 0.0) for j in ns)
            if s > 0 and (best is None or s > best[0]):
                best = (s, w)
        if best is None:
            break
        if prev_s is not None and best[0] < prev_s * stop_ratio:
            break                            # 强度衰减 → 联想该停了
        prev_s = best[0]
        out.append((best[1], best[0]))
        seen.add(best[1])
        path.append(best[1])
    return out


def walk_ok(ng, pats, chain, use_ctx):
    out = walk_chain_ctx(ng, pats, chain[0]) if use_ctx else walk_chain(
        ng, pats, chain[0], HOP)
    names = [chain[0]] + [w for w, _ in out]
    reached = chain[-1] in names
    overshoot = reached and names[-1] != chain[-1]
    return reached, overshoot, names


# ────────────────────────────────────────────────────────────────
#  F1：终止缺口（S4 复测：300 词独立链 + 300 对噪声）
# ────────────────────────────────────────────────────────────────

def f1_termination(seed=42, verbose=True):
    rng = np.random.default_rng(seed)
    chains, pairs = make_chains(rng, 60)
    words = list(dict.fromkeys([w for c in chains for w in c]))
    noise_pairs = [(rng.choice(words), rng.choice(words)) for _ in range(300)]
    noise_pairs = [(x, y) for x, y in noise_pairs if x != y]
    ng = make_net(seed)
    pats, _ = allocate_pats(ng, EXTRA + words, K)
    dt = train(ng, pats, pairs, chains)
    dt_n = time.time()
    for x, y in noise_pairs:
        teach_pair(ng, pats, x, y)
    dt_n = time.time() - dt_n

    res = {}
    for use_ctx, tag in ((False, "旧走链"), (True, "新走链")):
        n_ok = n_over = 0
        fails = []
        for c in chains:
            reached, overshoot, names = walk_ok(ng, pats, c, use_ctx)
            n_ok += int(reached)
            n_over += int(overshoot)
            if not reached:
                fails.append((c, names))
        res[tag] = {"rate": n_ok / len(chains), "overshoot": n_over}
        if verbose:
            print(f"  [F1:{tag}] 推理走通 {n_ok / len(chains):.1%}"
                  f"（{n_ok}/{len(chains)}），联想过冲 {n_over} 条")
            for c, names in fails[:3]:
                print(f"    ❌ 期望 {' → '.join(c)} | 实际 {' → '.join(names)}")
    return res


# ────────────────────────────────────────────────────────────────
#  F2：上下文缺口（S5 复测：共享 hub 等权分支）
# ────────────────────────────────────────────────────────────────

def f2_context_equal(seed=42, verbose=True):
    rng = np.random.default_rng(seed)
    chains = [["A1", "X", "B1"], ["A2", "X", "B2"]]
    pairs = [(c[i], c[i + 1]) for c in chains for i in range(len(c) - 1)]
    extra_chains, extra_pairs = make_chains(rng, 8, prefix="e")
    all_chains = chains + extra_chains
    words = list(dict.fromkeys([w for c in all_chains for w in c]))
    ng = make_net(seed)
    pats, _ = allocate_pats(ng, EXTRA + words, K)
    train(ng, pats, pairs + extra_pairs, all_chains)

    res = {}
    for use_ctx, tag in ((False, "旧走链"), (True, "新走链")):
        per = {}
        for start, target in (("A1", "B1"), ("A2", "B2")):
            out = walk_chain_ctx(ng, pats, start) if use_ctx else walk_chain(
                ng, pats, start, HOP)
            names = [start] + [w for w, _ in out]
            per[start] = (target in names, names)
        res[tag] = per
        if verbose:
            print(f"  [F2:{tag}] 共享 hub 等权分支（X 被两条链共享）:")
            for start, (ok, names) in per.items():
                print(f"    {start}: {' → '.join(names)} → "
                      f"{'✅ 走对分支' if ok else '❌ 走错（上下文缺口）'}")
    return res


# ────────────────────────────────────────────────────────────────
#  F3：上下文缺口（S6 复测：分支权重不对称）
# ────────────────────────────────────────────────────────────────

def f3_context_asym(seed=42, verbose=True):
    rng = np.random.default_rng(seed)
    chains = [["A1", "X", "B1"], ["A2", "X", "B2"]]
    words = list(dict.fromkeys([w for c in chains for w in c]))
    ng = make_net(seed)
    pats, _ = allocate_pats(ng, EXTRA + words, K)
    for _ in range(R):
        for x, y in [("A1", "X"), ("X", "B1")]:
            teach_pair(ng, pats, x, y)
    for x, y in [("A2", "X"), ("X", "B2")]:
        teach_pair(ng, pats, x, y)
    # 整链跟读（为上下文调制提供 A1↔B1、A2↔B2 弱直连）
    for c in chains:
        neurons = [i for w in c for i in pats[w]]
        run_train(ng, build_pulse(ng.n, neurons), len(neurons))

    res = {}
    for use_ctx, tag in ((False, "旧走链"), (True, "新走链")):
        per = {}
        for start, target in (("A1", "B1"), ("A2", "B2")):
            out = walk_chain_ctx(ng, pats, start) if use_ctx else walk_chain(
                ng, pats, start, HOP)
            names = [start] + [w for w, _ in out]
            per[start] = (target in names, names)
        res[tag] = per
        if verbose:
            print(f"  [F3:{tag}] 分支权重不对称（A1→X→B1 强、A2→X→B2 弱）:")
            for start, (ok, names) in per.items():
                print(f"    {start}: {' → '.join(names)} → "
                      f"{'✅ 走对分支' if ok else '❌ 走错（上下文缺口）'}")
    return res


def main():
    t0 = time.time()
    print("═══ 补缺口实验：终止信号 + 上下文调制 ═══\n")

    f1 = f1_termination(42)
    f2 = f2_context_equal(42)
    f3 = f3_context_asym(42)

    # 验收：新走链全过 + 旧走链暴露缺口
    ok_f1 = f1["新走链"]["rate"] == 1.0 and f1["新走链"]["overshoot"] == 0
    ok_f2 = all(ok for ok, _ in f2["新走链"].values())
    ok_f3 = all(ok for ok, _ in f3["新走链"].values())
    ok_all = ok_f1 and ok_f2 and ok_f3

    print("\n═══ 汇总 ═══")
    print(f"  [F1] 终止信号: 过冲 {f1['旧走链']['overshoot']} → "
          f"{f1['新走链']['overshoot']} 条, 走通 "
          f"{f1['新走链']['rate']:.0%} → {'✅' if ok_f1 else '❌'}")
    print(f"  [F2] 上下文(等权分支): {'✅' if ok_f2 else '❌'}")
    print(f"  [F3] 上下文(不对称分支): {'✅' if ok_f3 else '❌'}")
    print(f"\n═══ 总验收: {'两缺口修复完成 ✅' if ok_all else '未修复 ❌'} "
          f"（{time.time() - t0:.0f}s）═══")

    data = {
        "desc": "补缺口实验（v2.2 §12.6b）：终止信号 + 上下文调制",
        "params": {"K": K, "N": N, "R": R, "R_FULL": R_FULL,
                   "HOP": HOP, "STOP_RATIO": STOP_RATIO, "seed": 42},
        "summary": {
            "F1_旧过冲": f1["旧走链"]["overshoot"],
            "F1_新过冲": f1["新走链"]["overshoot"],
            "F1_新走通": f1["新走链"]["rate"],
            "F2_新全对": ok_f2,
            "F3_新全对": ok_f3,
            "all_ok": ok_all,
        },
        "F1_终止": f1, "F2_上下文等权": f2, "F3_上下文不对称": f3,
    }
    out = save_result(data)
    print(f"\n实验数据已留档: {out / 'result.json'}")


if __name__ == "__main__":
    main()
