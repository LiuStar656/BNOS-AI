# -*- coding: utf-8 -*-
"""OOV 固化修复（2026-08-10，复考暴露的根因）：

问题：_grow_oov.py / _grow_fix23.py 的固化从未执行——oov_count 只在
识别阶段 +1（每词 1 次 < ENTRENCH=3）→ OOV 词永远保持"字模式并集
身份"→ 共享字神经元（早饭 ∋ 饭 的 4012-4015）→ n2w 逆映射被覆盖
（n2w[4012]="早饭"）→ direct_next_multi 域内过滤读不出"饭"→
C/D/H 的 吃→饭 / 做→饭 / 睡→觉 全断（边存在但读出失败）。

修复：
① 8 个 OOV 词真正固化：allocate_pats 新模式（与字神经元解绑）
② 固化后重新喂教学句 ×R_OOV：新模式上重建句级边（在→椅子 等）
③ 验证：n2w 无污染（direct_next(做, {做,饭}) 非空）+ 断点边全在
④ 快照 v23.0

用法：python _grow_fix24.py
"""

import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from sparse_net import allocate_pats
from _grow_v16 import edge_between, direct_next_multi

RUNS_DIR = Path(__file__).parent / "runs"
K = 4
R_OOV = 8

OOV_WORDS = ["椅子", "操场", "起床", "晚饭", "午觉", "雨伞", "袜子", "早饭"]
OOV_LESSONS = [
    ("他在椅子上睡觉", ["他", "在", "椅子", "上", "睡觉"]),
    ("我们去操场跑步", ["我们", "去", "操场", "跑步"]),
    ("他早上起床", ["他", "早上", "起床"]),
    ("我们吃了晚饭", ["我们", "吃", "了", "晚饭"]),
    ("她在睡午觉", ["她", "在", "睡", "午觉"]),
    ("外面下雨要带雨伞", ["外面", "下雨", "要", "带", "雨伞"]),
    ("他穿了一双袜子", ["他", "穿", "了", "一", "双", "袜子"]),
    ("我们在家吃早饭", ["我们", "在", "家", "吃", "早饭"]),
]


def main():
    t0 = time.time()
    print("═══ OOV 固化修复：字并集解绑 → 正式词模式 ═══\n")

    ng, vocab, pats, cursor = load_version("22.0")
    keys = set(pats.keys())
    print(f"[加载] 22.0：n={ng.n}，词表 {len(keys)}")

    # ① 真正固化：allocate 新模式（与字神经元解绑）
    print("\n[固化] %d 个 OOV 词 → 正式词模式" % len(OOV_WORDS))
    for w in OOV_WORDS:
        if w not in pats:
            print(f"  ⚠ {w} 不在 pats（跳过）")
            continue
        old = pats[w]
        new_p, cursor = allocate_pats(ng, [w], K, cursor)
        pats[w] = new_p[w]
        print(f"  「{w}」{len(old)} 神经元 → 新模式 {pats[w]}（解绑字共享）")

    # ② 固化后重喂教学句（新模式上重建句级边）
    print(f"\n[重喂] 教学句 ×{R_OOV} 轮（新模式上重建边）")
    for _ in range(R_OOV):
        for sent, toks in OOV_LESSONS:
            _learn_sentence(ng, toks, pats, slot=0)

    # ③ 验证：n2w 污染消除 + 断点边重建
    n2w = {j: w for w, ns in pats.items() for j in ns}
    print("\n[验证] n2w 污染：")
    print(f"  n2w[饭 神经元] = {[n2w.get(j) for j in pats['饭']]}")
    top = direct_next_multi(ng, pats, n2w, ["做"], k=8, domain={"做", "饭"})
    print(f"  direct_next(做, {{做,饭}}) = {[(w, round(v, 1)) for w, v in top]}")
    print("\n[验证] 断点边重建：")
    for a, b in [("在", "椅子"), ("去", "操场"), ("早上", "起床"),
                 ("了", "晚饭"), ("睡", "午觉"), ("带", "雨伞"),
                 ("双", "袜子"), ("吃", "早饭"), ("吃", "饭"),
                 ("做", "饭"), ("睡", "觉")]:
        w = edge_between(ng, pats, a, b)
        mark = "✅" if w > 0 else "✗"
        print(f"  {mark} edge {a}→{b} = {w:g}")

    # ④ 快照
    save_snapshot(ng, parent="22.0",
                  tag="OOV 固化修复：8 词正式词模式（字并集解绑，n2w "
                      "污染消除）+ 重喂重建句级边",
                  metrics={"oov_words": OOV_WORDS},
                  vocab=vocab, pats=pats, cursor=cursor)
    print(f"\n[完成] 快照已存（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
