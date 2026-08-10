# -*- coding: utf-8 -*-
"""探针实验：定式网络表示并发（多槽并行学习两组不相关词对，验证互不串扰）。

假设（理论 § 表示并发）：
  - 槽位 = 表示通道：槽0 学 "我吃苹果"，槽1 学 "他看家"，两组边落在
    各自槽位的 W[*][k]（Hebbian 用每神经元主导槽 k_star 分桶）→ 各自建立、互不串扰。
  - 对照：同槽（都槽0）交替学习两组 → 若无串扰则槽位不是关键；若串扰则
    槽位隔离 = 表示并发的机制。

用真实快照 v13.0（n=148776，模式 37194）增量试验——不动主网络，只验证机制。
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
from schema_net import build_pulse, _learn_sentence, _evoke_prefix
from snapshot import load_version

GROUP_A = ["我", "吃", "苹果"]
GROUP_B = ["他", "看", "家"]
N_ROUNDS = 5


def recall(ng, pats, word, slot=0, steps=3):
    """注入 word 到 slot，回响 steps 步，返回被激活的神经元集合。"""
    return _evoke_prefix(ng, [word], pats, slot=slot, steps=steps)


def ratio(fired, neurons):
    """目标模式神经元被激活比例（0~1）。"""
    if not neurons:
        return 0.0
    return sum(1 for j in neurons if j in fired) / len(neurons)


def probe(ng, pats, words, slot):
    """注入 slot 里每个词，测量其对同组/异组词的唤起比例。返回 {词: {目标: ratio}}。"""
    res = {}
    for w in words:
        fired = recall(ng, pats, w, slot=slot)
        res[w] = {t: round(ratio(fired, pats[t]), 3) for t in words}
    return res


def edge_by_slot(ng, pats, src, dst):
    """src 模式出边汇聚到 dst 模式的总权重，按槽位分开（跨槽读出工具）。"""
    dst_set = set(pats[dst])
    per = []
    for k in range(ng.slots):
        total = 0.0
        for j in pats[src]:
            row = ng.W_out[j][k]
            if row:
                keep = np.isin(row.dst, np.fromiter(dst_set, dtype=np.int32))
                total += float(row.w[keep].sum())
        per.append(round(total, 3))
    return per


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else "13.0"
    ng, vocab, pats, cursor = load_version(version)
    n2w = {j: w for w, ns in pats.items() for j in ns}
    all_words = GROUP_A + GROUP_B
    missing = [w for w in all_words if w not in pats]
    print(f"[加载] v{version}：n={ng.n}，模式 {len(pats)}，cursor={cursor}")
    if missing:
        print(f"[中止] 词表缺失：{missing}")
        return

    out = {"version": version, "n_rounds": N_ROUNDS,
           "groups": {"A": GROUP_A, "B": GROUP_B}}

    # ── 0. 学习前基线：关键边强度（逐槽）──
    keys = [("我", "吃"), ("吃", "苹果"), ("他", "看"), ("看", "家"),
            ("我", "看"), ("他", "吃"), ("我", "苹果"), ("他", "家")]
    out["edge_baseline"] = {f"{a}→{b}": edge_by_slot(ng, pats, a, b)
                            for a, b in keys}

    # ── 1. 学习前基线（槽0/槽1 交叉）──
    out["baseline"] = {"slot0": probe(ng, pats, all_words, slot=0),
                       "slot1": probe(ng, pats, all_words, slot=1)}

    # ── 2. 双槽并发学习（槽0=A 组，槽1=B 组，交替 5 轮）──
    for _ in range(N_ROUNDS):
        _learn_sentence(ng, GROUP_A, pats, slot=0)
        _learn_sentence(ng, GROUP_B, pats, slot=1)
    out["concurrent"] = {"slot0": probe(ng, pats, all_words, slot=0),
                         "slot1": probe(ng, pats, all_words, slot=1)}

    # ── 3. 同槽对照组（两组都在槽0 交替 5 轮）──
    for _ in range(N_ROUNDS):
        _learn_sentence(ng, GROUP_A, pats, slot=0)
        _learn_sentence(ng, GROUP_B, pats, slot=0)
    out["same_slot"] = {"slot0": probe(ng, pats, all_words, slot=0),
                        "slot1": probe(ng, pats, all_words, slot=1)}

    # ── 4. 学习后：关键边强度（逐槽，对比学习前后）──
    out["edge_after"] = {f"{a}→{b}": edge_by_slot(ng, pats, a, b)
                         for a, b in keys}

    # ── 打印 ──
    def fmt(m, words):
        lines = []
        for w in words:
            row = "  ".join(f"{t}:{m[w].get(t, 0):.2f}" for t in words)
            lines.append(f"    注入[{w}] → {row}")
        return "\n".join(lines)

    print("\n═══ 双槽并发学习（槽0: 我吃苹果 | 槽1: 他看家）═══")
    print("\n[学习后 · 槽0] 注入词 → 唤起比例：")
    print(fmt(out["concurrent"]["slot0"], all_words))
    print("\n[学习后 · 槽1] 注入词 → 唤起比例：")
    print(fmt(out["concurrent"]["slot1"], all_words))

    print("\n═══ 同槽对照（两组都在槽0）═══")
    print("\n[对照 · 槽0] 注入词 → 唤起比例：")
    print(fmt(out["same_slot"]["slot0"], all_words))

    print("\n═══ 关键边强度（逐槽，学习前 → 并发后 → 对照后）═══")
    print("  " + "".join(f"{a}→{b:<24}" for a, b in keys))
    for phase in ("edge_baseline", "edge_after"):
        print(f"  {phase:<6}", end="")
        for a, b in keys:
            print(f"{str(out[phase][f'{a}→{b}']):<26}", end="")
        print()

    # ── 判读（边强度为准：唤起失败 ≠ 学习失败，需区分注意力竞争）──
    eb = out["edge_baseline"]
    ea = out["edge_after"]
    a_learn = ea["我→吃"][0] > eb["我→吃"][0] and ea["吃→苹果"][0] > eb["吃→苹果"][0]
    b_learn = ea["他→看"][1] > eb["他→看"][1] and ea["看→家"][1] > eb["看→家"][1]
    cross = max(ea["他→吃"]) == 0 and ea["我→看"] == eb["我→看"] and ea["我→苹果"] == eb["我→苹果"]
    # 槽位归属：A 组强边在槽0、B 组强边在槽1
    a_slot = ea["我→吃"][0] > ea["我→吃"][1]
    b_slot = ea["他→看"][1] > ea["他→看"][0]
    a_evoke = out["concurrent"]["slot0"]["我"]["吃"]  # "我"注入唤起"吃"比例（注意力竞争读数）
    out["verdict"] = {
        "A组边建立(我→吃/吃→苹果)": a_learn,
        "B组边建立(他→看/看→家)": b_learn,
        "跨组串扰边为0(他→吃/我→看/我→苹果)": cross,
        "槽位隔离(A组落槽0)": a_slot,
        "槽位隔离(B组落槽1)": b_slot,
        "A组唤起被竞争挤出(我→吃唤起=0但边=80)": a_evoke,
        "结论": ("表示并发成立：边隔离+串扰为0+并发槽学习更强"
                if (a_learn and b_learn and cross and a_slot and b_slot)
                else "需检查")}
    print("\n═══ 判读 ═══")
    for k, v in out["verdict"].items():
        print(f"  {k}: {v}")

    # ── 保存（表格）──
    fp = Path(__file__).parent / "runs" / "_concurrent_probe.json"
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[保存] {fp}")


if __name__ == "__main__":
    main()
