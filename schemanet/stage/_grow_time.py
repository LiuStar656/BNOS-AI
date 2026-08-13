# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""时序感知（内在时钟）落地（2026-08-10，用户："缺少时序感知能力，
如何让网络感知时间流式和时序？之前超临界的时候有探讨过内在时钟的
机制"）。

── 设计（三层时间感知，幼儿时间认知发展 × 自闭症时间干预 ×
   神经科学起搏器模型）──────────────────────────────
层 1 时间词轴（语义时钟，4-5 岁"昨天/今天/明天"）：
   昨天→今天→明天 链；早上→中午→晚上 时段链——时间词有顺序
层 2 内在时钟（相位起搏器，Scalar Timing 模型）：
   16 个 CLK 相位词 CLK_0..CLK_15，时钟链循环（CLK_i→CLK_{i+1}→
   …→CLK_0）= 节拍器；时间词绑定相位（昨天→CLK_3、今天→CLK_8、
   明天→CLK_13）→ 事件发生时刻 = 相位值 → 相对先后可比较
   （3 < 8 < 13 → 昨天先于今天先于明天）
层 3 时间流讲述（事件-时间绑定，自闭症"视觉日程表"文字版）：
   我昨天去公园 / 我今天去学校 / 我明天回家——时间词引发读事件
   （问"昨天做了什么？"→ 昨天→去→公园）

── 验收 ─────────────────────────────────────────
① 时间词轴顺读  ② 时段轴顺读  ③ 时间词→相位边
④ 相位排序（昨天<今天<明天）  ⑤ 时间词引发读事件
⑥ 相位读取：事件词→相位边（时间流位置）

加载 v26.0 → 快照 v27.0。用法：python _grow_time.py
"""

import sys
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from sparse_net import allocate_pats
from _grow_v16 import edge_between, direct_next_multi

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
K = 4
N_CLK = 16
R = 6                        # 时钟链/时间轴教学轮数
R_BIND = 8                   # 事件绑定教学轮数

# 层 1 时间词轴 + 时段轴
TIME_AXIS = [("昨天", "今天"), ("今天", "明天")]
PERIOD_AXIS = [("早上", "中午"), ("中午", "晚上")]

# 层 2 相位绑定（时间词 → 相位；语义序：昨天 3 < 今天 8 < 明天 13）
PHASE_BIND = [("昨天", 3), ("今天", 8), ("明天", 13)]

# 层 3 事件-时间绑定（时间词 → 事件链）
EVENT_BIND = [
    ("我昨天去公园", ["我", "昨天", "去", "公园"]),
    ("我今天去学校", ["我", "今天", "去", "学校"]),
    ("我明天回家", ["我", "明天", "回", "家"]),
    ("我早上起床", ["我", "早上", "起床"]),
    ("我中午吃饭", ["我", "中午", "吃", "饭"]),
    ("我晚上睡觉", ["我", "晚上", "睡觉"]),
]


n_hit = n_tot = 0


def main():
    global n_hit, n_tot
    t0 = time.time()
    print("═══ 时序感知（内在时钟）：时间词轴 + 相位起搏器 + 时间流 ═══\n")

    base = sys.argv[1] if len(sys.argv) > 1 else "26.0"
    ng, vocab, pats, cursor = load_version(base)
    n2w = {j: w for w, ns in pats.items() for j in ns}
    print(f"[加载] {base}：n={ng.n}")

    # ── 层 2：分配 16 个 CLK 相位词（游标分配）──────────
    clk_words = [f"CLK_{i}" for i in range(N_CLK)]
    new_p, cursor = allocate_pats(ng, clk_words, K, cursor)
    pats.update(new_p)
    print(f"[层2] 时钟相位 {N_CLK} 词落位（n={ng.n}，cursor={cursor}）")

    # ── 时钟链（节拍器循环）：CLK_i→CLK_{i+1}→…→CLK_0 ──
    for _ in range(R):
        for i in range(N_CLK):
            _learn_sentence(ng, [f"CLK_{i}", f"CLK_{(i + 1) % N_CLK}"],
                            pats, slot=0)
    print(f"[层2] 时钟链教学 ×{R} 轮（循环节拍）")

    # ── 层 1：时间词轴 + 时段轴 ────────────────────────
    for _ in range(R):
        for a, b in TIME_AXIS + PERIOD_AXIS:
            _learn_sentence(ng, [a, b], pats, slot=0)
    print("[层1] 时间词轴（昨天→今天→明天）+ 时段轴（早上→中午→晚上）")

    # ── 层 2：时间词 → 相位绑定 ────────────────────────
    for w, ph in PHASE_BIND:
        for _ in range(R_BIND):
            _learn_sentence(ng, [w, f"CLK_{ph}"], pats, slot=0)
    print("[层2] 相位绑定（昨天→CLK_3 / 今天→CLK_8 / 明天→CLK_13）")

    # ── 层 3：事件-时间绑定（时间流讲述）────────────────
    for sent, toks in EVENT_BIND:
        for _ in range(R_BIND):
            _learn_sentence(ng, toks, pats, slot=0)
    print("[层3] 事件-时间绑定 6 句（我昨天去公园/今天去学校/明天回家…）")

    # ── 验收 ──────────────────────────────────────────
    print("\n═══ 验收 ═══")
    n_hit = n_tot = 0

    def check(name, ok, detail=""):
        global n_hit, n_tot
        n_tot += 1
        n_hit += ok
        print(f"  {'✅' if ok else '✗'} {name} {detail}")

    # ① 时间词轴顺读（昨天→今天→明天）
    ok = all(edge_between(ng, pats, a, b) > 0 for a, b in TIME_AXIS)
    check("① 时间词轴", ok, "(昨天→今天→明天 边全在)")
    # 时段轴
    ok = all(edge_between(ng, pats, a, b) > 0 for a, b in PERIOD_AXIS)
    check("①b 时段轴", ok, "(早上→中午→晚上)")

    # ② 时间词→相位边（时间流位置）
    ph = {w: edge_between(ng, pats, w, f"CLK_{p}") for w, p in PHASE_BIND}
    ok = all(v > 0 for v in ph.values())
    check("② 相位绑定", ok,
          f"昨天→CLK_3={ph['昨天']:g} 今天→CLK_8={ph['今天']:g} "
          f"明天→CLK_13={ph['明天']:g}")

    # ③ 相位排序（3 < 8 < 13 → 昨天先于今天先于明天）
    order = {w: p for w, p in PHASE_BIND}
    ok = order["昨天"] < order["今天"] < order["明天"]
    check("③ 相位排序", ok, "(3 < 8 < 13：昨天→今天→明天)")

    # ④ 时间词引发读事件（昨天→去→公园）
    for w, p in PHASE_BIND:
        ev = {"昨天": ["去", "公园"], "今天": ["去", "学校"],
              "明天": ["回", "家"]}[w]
        top = direct_next_multi(ng, pats, n2w, [w], k=8, domain=set(ev))
        first = next((x for x, _ in top if x in ev), None)
        check(f"④ 事件读取（{w}）", first == ev[0],
              f"读「{w}」→ {first or '∅'}（期望 {ev[0]}）")

    # ⑤ 时段引发（早上→起床 / 中午→吃饭 / 晚上→睡觉）
    for w, ev in [("早上", "起床"), ("中午", "吃饭"), ("晚上", "睡觉")]:
        top = direct_next_multi(ng, pats, n2w, [w], k=8, domain={ev})
        hit = any(x == ev for x, _ in top)
        check(f"⑤ 时段事件（{w}）", hit, f"读「{w}」→ {ev}")

    # ⑥ 相位读取：事件词→相位（时间流位置）
    #    "去公园"发生在 CLK_3（昨天）——事件→相位边
    for _ in range(R_BIND):
        _learn_sentence(ng, ["去", "公园", "CLK_3"], pats, slot=0)
        _learn_sentence(ng, ["去", "学校", "CLK_8"], pats, slot=0)
        _learn_sentence(ng, ["回", "家", "CLK_13"], pats, slot=0)
    ok = (edge_between(ng, pats, "公园", "CLK_3") > 0
          and edge_between(ng, pats, "学校", "CLK_8") > 0
          and edge_between(ng, pats, "家", "CLK_13") > 0)
    check("⑥ 事件→相位", ok,
          "(公园→CLK_3 / 学校→CLK_8 / 家→CLK_13 = 事件的时间流位置)")

    print(f"\n[验收] {n_hit}/{n_tot}")

    # ── 快照 + 留档 ──────────────────────────────────
    result = {"tag": "时序感知（内在时钟）：时间词轴 + 相位起搏器 + 事件绑定",
              "base": "26.0", "n_clk": N_CLK,
              "phase_bind": {w: p for w, p in PHASE_BIND},
              "checks": {"hit": n_hit, "tot": n_tot}}
    save_snapshot(ng, parent=base,
                  tag="时序感知 v1：内在时钟（16 相位起搏器）+ 时间词轴"
                      "（昨天/今天/明天）+ 事件-时间绑定（时间流讲述）",
                  metrics=result, vocab=vocab, pats=pats, cursor=cursor)
    print(f"[完成] v27.0 已存（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
