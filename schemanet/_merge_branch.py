# -*- coding: utf-8 -*-
"""快照链合流：把 18.12（表达）/18.16（问答）/18.19（v19 正式课程）
分支的教学边合并回主链（2026-08-10）。

背景（大规模期末考试暴露，问题 1）：
  18.x 多个教学脚本各自 load_version("17.0") → 快照全部是 17.0 的
  并列分支（index.jsonl 实证），主链只有 17.0→18.21→19.0→20.0——
  问答/表达/对话教学的边"学了但丢了"，v20.0 考试 E 问答 1/15、
  F 自我表达 10/15（层2 假通）全断在此。

合流算法：
  ① base = 17.0（分支共同祖先，n/pats 与分支完全一致——神经元索引可比）
  ② 对每个分支：diff = 分支 W_out 中与 base 不同的边（新增 + 变化）
  ③ target = 20.0（主链当前端）：diff 边合并——target 已有则取 max
     （保留两侧教学成果；不叠加防推超平衡边——v16 教训）
  ④ 保存新快照 parent=20.0（版本号自动推 21.0）

用法：python _merge_branch.py
"""

import time
from pathlib import Path

from snapshot import load_version, save_snapshot
from _grow_v16 import edge_between

RUNS = Path(__file__).parent / "runs"
BRANCHES = ["18.12", "18.16", "18.19"]     # 表达 / 问答 / v19 正式课程
BASE = "17.0"                              # 分支共同祖先
TARGET = "20.0"                            # 主链当前端


def diff_edges(ng_b, ng_base, slots):
    """分支相对基准的边差异：{(i, slot, j): w}（新增 + 变化）。"""
    out = {}
    n = min(len(ng_b.W_out), len(ng_base.W_out))
    for i in range(n):
        for slot in range(slots):
            rb = ng_b.W_out[i][slot]
            bb = ng_base.W_out[i][slot]
            for j, w in rb.items():
                if bb.get(j, 0.0) != w:
                    out[(i, slot, j)] = w
    return out


def main():
    t0 = time.time()
    print("═══ 快照链合流：分支教学边 → 主链 ═══\n")

    ng_base, _, _, _ = load_version(BASE)
    ng_tgt, vocab, pats, cursor = load_version(TARGET)
    slots = ng_tgt.slots
    print(f"[基准] {BASE}：n={ng_base.n} | [目标] {TARGET}：n={ng_tgt.n}")

    merged = 0
    for ver in BRANCHES:
        ng_b, _, _, _ = load_version(ver)
        t1 = time.time()
        diff = diff_edges(ng_b, ng_base, slots)
        n_add = n_chg = 0
        for (i, slot, j), w in diff.items():
            cur = ng_tgt.W_out[i][slot].get(j, 0.0)
            if cur <= 0:
                n_add += 1
            elif w != cur:
                n_chg += 1
            if w > cur:                      # 取 max：保留两侧教学成果
                ng_tgt.W_out[i][slot][j] = w
        merged += len(diff)
        print(f"  {ver}：diff {len(diff)} 条边"
              f"（新增 {n_add} / 变化 {n_chg}，{time.time()-t1:.0f}s）")

    # ── 验证：修链后关键边应存在 ─────────────────────────
    n2w = {j: w for w, ns in pats.items() for j in ns}
    print("\n[验证] 关键教学边（修链后应为正）：")
    for a, b in [("累", "他"), ("疼", "帮"), ("帮", "我"), ("渴", "要"),
                 ("饿", "要"), ("难过", "因为"), ("我", "疼"), ("我", "饿"),
                 ("带伞", "因为"), ("吃", "草莓酱")]:
        print(f"  edge {a}→{b}: {edge_between(ng_tgt, pats, a, b):g}")

    # ── 快照 ─────────────────────────────────────────────
    save_snapshot(ng_tgt, parent=TARGET,
                  tag="快照链合流：18.12 表达 + 18.16 问答 + 18.19 正式"
                      "课程分支边并入主链（考试暴露问题 1 修复）",
                  metrics={"merged_edges": merged,
                           "branches": BRANCHES,
                           "base": BASE, "target": TARGET},
                  vocab=vocab, pats=pats, cursor=cursor)
    print(f"\n[完成] 合流 {merged} 条边（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
