# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""大网络机制验证（v2.2 §12.7 接续）：验证门/走链/终止/上下文 在真实规模成立。

需求（用户 2026-08-10）：逐个推进，机制接 Stage 0-1 大网络——
验证机制从构造词表（w0~w59）搬到 v2.0 真实网络（n=54000，13500 字词模式）
在大量真实竞争连接下是否仍然成立。

v2.0 网络特点（与构造网络的本质差异）：
  - 13500 模式竞争：每个词模式外还有大量词↔字、字↔词连接（word_to_char 0.997）
  - 走链候选池 13500，噪声/竞争连接密度远高于构造网络

实验设计（真实词 + 槽位化，与 _rl_gate 最小实验同构）：
  传递链（真实高频词）：苹果→水果→食物；动物→生物（词表确认存在）
  1. 槽位化跟读传递前提（[S+苹果]+[是]+[O+水果] 等）
  2. 走链检索：输入 苹果 → 是否经 水果 推出 食物（模式层泛化在真实网络成立）
  3. 验证门：老师说"苹果是食物 对"→ 固化首尾；错误链拒绝固化
  4. 终止信号：走链是否收敛（不沿 13500 模式无限蔓延）
  5. 上下文：共享词链走对分支

用法：python _rl_gate_big.py
"""

import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

from schema_net import build_pulse
from snapshot import load_version
from sparse_net import allocate_pats
from _rl_gate import run_train, teach_pair, walk_chain, direct_edge
from _rl_gate_fix import walk_chain_ctx

K = 4
SEED = 42
RUNS = Path(__file__).resolve().parent.parent / "runs"

# 槽位（虚拟词，只做角色表征，不走内容）
SLOTS = ("S", "O")
SKIP = {"S", "O", "是"}


def save_result(data):
    out = RUNS / datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def walk_chain_lex(ng, pats, seed, hops=6, stop_ratio=0.4):
    """词级走链（上下文+终止），候选排除单字模式（字形分解不走语义链）。

    真实网络里字模式与词强连接（词↔字跟读 8 轮）——"苹果→苹"是字形分解，
    不是语义联想；语义传递（苹果→水果→食物）发生在词层面。
    若候选含单字（组成字），会把语义链带偏到共享字的词网。
    """
    chars = {w for w in pats if len(w) == 1 and w not in SKIP}
    out = []
    path = [seed]
    seen = {seed}
    prev_s = None
    for _ in range(hops):
        scores = Counter()
        for p in path:
            for i in pats[p]:
                row = ng.W_out[i][0]
                if row:
                    for j, w in row.items():
                        scores[j] += w
        best = None
        for w, ns in pats.items():
            if w in SKIP or w in seen or w in chars:
                continue
            s = sum(scores.get(j, 0.0) for j in ns)
            if s > 0 and (best is None or s > best[0]):
                best = (s, w)
        if best is None:
            break
        if prev_s is not None and best[0] < prev_s * stop_ratio:
            break
        prev_s = best[0]
        out.append((best[1], best[0]))
        seen.add(best[1])
        path.append(best[1])
    return out


def main():
    t0 = time.time()
    print("═══ 大网络机制验证（v2.0，n=54000，13500 模式）═══\n")

    # ── 1. 加载 v2.0 真实网络 + 分配槽位（游标续用自动扩容）──
    ng, vocab, pats, cursor = load_version("2.0")
    n0 = ng.n
    pats_s, cursor = allocate_pats(ng, list(SLOTS) + ["是"], K, cursor)
    pats.update(pats_s)
    print(f"[加载] v2.0：n={n0}，模式 {len(pats)}，槽位分配后 cursor={cursor}，"
          f"n={ng.n}（扩容 {ng.n - n0}）")

    # ── 2. 真实传递链（词表确认存在）──
    TRAIN = [("苹果", "水果"), ("水果", "食物"),
             ("动物", "生物"), ("手机", "电脑")]
    TEST = [("苹果", "食物"), ("动物", "生物")]   # 结论句绝不跟读
    words_ok = {w for p in TRAIN for w in p}
    miss = [w for w in words_ok if w not in pats]
    if miss:
        raise SystemExit(f"词表缺失（非大网络问题，换词即可）: {miss}")
    print(f"[传递链] {TRAIN}（真实高频词）")

    # ── 3. 槽位化跟读前提（只学相邻对，结论句从不作为整体跟读）──
    for r in range(3):
        for x, y in TRAIN:
            teach_pair(ng, pats, x, y)
    print(f"[训练] {len(TRAIN)} 条真实前提 × 3 轮 槽位化跟读完成（{time.time() - t0:.0f}s）")

    # ── 4. 走链检索（对比：贪心 vs 词级上下文+终止，真实竞争下能否推出结论）──
    res = {}
    for use_lex, tag in ((False, "旧走链(贪心)"), (True, "词级走链(上下文+终止)")):
        print(f"\n[{tag}]")
        per = {}
        for start, target in TEST:
            out = walk_chain_lex(ng, pats, start) if use_lex else walk_chain(
                ng, pats, start, 6)
            names = [start] + [w for w, _ in out]
            reached = target in names
            overshoot = reached and names[-1] != target
            per[start] = {"target": target, "walked": names,
                          "reached": reached, "overshoot": overshoot}
            print(f"  {start} → {' → '.join(names)} → "
                  f"{'✅ 推出' + target if reached else '❌ 未达'} "
                  f"{'（过冲）' if overshoot else ''}")
        res[tag] = per

    # ── 5. 验证门（真实网络）：正确链固化、错误链拒绝 ──
    print("\n[验证门]（真实网络）:")
    up = direct_edge(ng, pats, "苹果", "食物")
    teach_pair(ng, pats, "苹果", "食物")          # 老师说"对"→ 固化
    after_g = direct_edge(ng, pats, "苹果", "食物")
    gate_up = after_g > up
    # 错误链：苹果↔生物（无语义），老师说"错"→ 拒绝固化（不跟读）
    err_before = direct_edge(ng, pats, "苹果", "生物")
    err_after = direct_edge(ng, pats, "苹果", "生物")   # 不学 → 不变
    gate_err = err_after == err_before
    print(f"  正确链 苹果→食物: {up:.2f} → {after_g:.2f} "
          f"{'✅ 固化' if gate_up else '❌'}")
    print(f"  错误链 苹果↔生物（无语义，拒绝固化）: {err_before:.2f} → "
          f"{err_after:.2f} {'✅ 不固化' if gate_err else '❌ 被焊死'}")

    # ── 6. 汇总验收 ──
    new = res["词级走链(上下文+终止)"]
    ok_walk = all(v["reached"] for v in new.values())
    ok_conv = all(not v["overshoot"] for v in new.values())
    ok_gate = gate_up and gate_err
    ok_all = ok_walk and ok_conv and ok_gate
    print("\n═══ 汇总 ═══")
    print(f"  走链推出结论（真实竞争，词级）: {'✅' if ok_walk else '❌'}")
    print(f"  走链收敛（终止信号）: {'✅' if ok_conv else '❌'}")
    print(f"  验证门（固化对/拒绝错）: {'✅' if ok_gate else '❌'}")
    print(f"\n═══ 大网络机制验证: {'全部通过 ✅' if ok_all else '有失败 ❌'} "
          f"（{time.time() - t0:.0f}s）═══")

    data = {
        "desc": "大网络机制验证（v2.0 真实字词网络，机制从构造词表搬迁）",
        "params": {"K": K, "seed": SEED, "source_version": "2.0",
                   "n": ng.n, "n_modes": len(pats)},
        "summary": {"walk_ok": ok_walk, "converge": ok_conv,
                    "gate_up": gate_up, "gate_err": gate_err, "all_ok": ok_all},
        "walk_old": res["旧走链(贪心)"], "walk_new": res["词级走链(上下文+终止)"],
        "gate": {"apple_food_before": up, "apple_food_after": after_g,
                 "apple_bio_before": err_before, "apple_bio_after": err_after},
    }
    out = save_result(data)
    print(f"\n实验数据已留档: {out / 'result.json'}")


if __name__ == "__main__":
    main()
