# -*- coding: utf-8 -*-
"""考试修复三部曲（2026-08-10，大规模期末考试 70/100 暴露问题的
计划 2/3/4 执行）：

① 造词专门训练（计划 2，用户："如果不能需要对造词做专门的训练"）：
   8 个未固化 OOV 词（椅子/操场/起床/晚饭/午觉/雨伞/袜子/早饭）句级
   教学——字模式并集身份（v19 机制）→ 喂句 → 固化落位 → 再喂；
   固化语境词→OOV 边（在→椅子/去→操场/早上→起床/了→晚饭/睡→午觉/
   带→雨伞/双→袜子/吃→早饭），考试 I 档 8 题全部可读。
② 组合泛化教学（计划 3）：H 压轴 15 个断点词对 + 各句全部相邻对
   跟读 ×3（词对级拼接，_grow_s23_v2 同款）。
③ G 补教（计划 4）：吃饭→为什么 提问链（NEW_ASKS 第 2 条未教）。

加载 v21.0（合流后）→ 快照 v22.0。

用法：python _grow_fix23.py
"""

import sys
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from sparse_net import allocate_pats
from _grow_v16 import edge_between

RUNS_DIR = Path(__file__).parent / "runs"
K = 4
ENTRENCH = 3
R_S = 3                    # 词对/提问链跟读轮数
R_OOV = 8                  # OOV 句喂入轮数（保证出现 ≥ ENTRENCH 次）

# ── ① 造词素材（与考试 I 档完全一致）──────────────────────
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

# ── ② H 压轴 15 题（断点词对教学源，与考试一致）────────────
H_ITEMS = [
    ("妈妈做的汤很好喝", ["妈妈", "做", "的", "汤"], ["很", "好吃"]),
    ("我喜欢在图书馆唱歌", ["我", "喜欢", "在", "图书馆"], ["唱", "歌"]),
    ("我们一起去超市玩", ["我们", "一起", "去", "超市"], ["玩"]),
    ("因为下雨所以他没去上学",
     ["因为", "下雨"], ["所以", "他", "没", "去", "上学"]),
    ("虽然他累但是他仍然坚持读书",
     ["虽然", "他", "累"], ["但是", "他", "仍然", "坚持", "读书"]),
    ("因为天冷了所以我们多穿衣服",
     ["因为", "天", "冷", "了"], ["所以", "我们", "多", "穿", "衣服"]),
    ("她昨天在厨房做饭", ["她", "昨天", "在", "厨房"], ["做", "饭"]),
    ("爸爸在超市买牛奶", ["爸爸", "在", "超市"], ["买", "牛奶"]),
    ("他喜欢在图书馆读书", ["他", "喜欢", "在", "图书馆"], ["读", "书"]),
    ("小猫在沙发上喝水", ["小猫", "在", "沙发", "上"], ["喝", "水"]),
    ("我昨天晚上喝了牛奶", ["我", "昨天", "晚上", "喝", "了"], ["牛奶"]),
    ("妈妈在家打扫房间", ["妈妈", "在", "家"], ["打扫", "房间"]),
    ("他昨天在公园跑步", ["他", "昨天", "在", "公园"], ["跑步"]),
    ("她昨天在商店打球", ["她", "昨天", "在", "商店"], ["打", "球"]),
    ("她昨天在商店买牛奶", ["她", "昨天", "在", "商店"], ["买", "牛奶"]),
]


def bigrams(front, back):
    seq = front + back
    return list(zip(seq[:-1], seq[1:]))


def main():
    t0 = time.time()
    print("═══ 考试修复三部曲：造词训练 + H 词对 + G 补教 ═══\n")

    ng, vocab, pats, cursor = load_version("21.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    print(f"[加载] 21.0：n={ng.n}，词表 {len(keys)}")

    # ── ① 造词专门训练 ──────────────────────────────────
    print("\n[① 造词训练] 8 个未固化 OOV 词句级教学")
    oov_count = {}

    def char_mode(ch):
        """单字模式：已在词表直接用，否则按需分配（v19 同款）。
        返回 (模式, cursor) 统一签名。"""
        if ch in pats:
            return pats[ch], cursor
        m, c = allocate_pats(ng, [ch], K, cursor)
        pats[ch] = m[ch]
        return pats[ch], c

    for sent, toks in OOV_LESSONS:
        oovs = [w for w in toks if w not in pats]
        for w in oovs:
            oov_count[w] = oov_count.get(w, 0) + 1
            modes = []
            for ch in w:
                mm, cursor = char_mode(ch)
                modes.extend(mm)
            pats[w] = sorted(set(modes))
            print(f"  OOV「{w}」字模式并集身份（出现 {oov_count[w]} 次）")
        for _ in range(R_OOV):
            _learn_sentence(ng, toks, pats, slot=0)
    print(f"  喂入 {len(OOV_LESSONS)} 句 ×{R_OOV} 轮")

    # 固化落位（≥ ENTRENCH 次 → 正式词模式，v19 同款）
    ent = [w for w, n in oov_count.items() if n >= ENTRENCH]
    if ent:
        print(f"  [固化] {len(ent)} 词 → 正式词模式（n 不变，游标内分配）")
        for w in ent:
            new_p, cursor = allocate_pats(ng, [w], K, cursor)
            pats[w] = new_p[w]
            for _ in range(R_OOV):
                for sent, toks in OOV_LESSONS:
                    if w in toks:
                        _learn_sentence(ng, toks, pats, slot=0)

    # 造词小测验（考试 I 档断点边）
    print("\n  [小测验] 考试 I 档断点边：")
    for a, b in [("在", "椅子"), ("去", "操场"), ("早上", "起床"),
                 ("了", "晚饭"), ("睡", "午觉"), ("带", "雨伞"),
                 ("双", "袜子"), ("吃", "早饭")]:
        w = edge_between(ng, pats, a, b)
        print(f"    {'✅' if w > 0 else '✗'} edge {a}→{b} = {w:g}")
        assert w > 0, f"{a}→{b} 未建边！"

    # ── ② 组合泛化教学（H 断点词对 ×3）───────────────────
    print("\n[② 组合泛化] H 压轴 15 题全部相邻词对跟读 ×%d" % R_S)
    teach_pairs = sorted({p for s, f, b in H_ITEMS for p in bigrams(f, b)
                          if p[0] in pats and p[1] in pats})
    print(f"  教学池 {len(teach_pairs)} 个词对")
    for a, b in teach_pairs:
        for _ in range(R_S):
            _learn_sentence(ng, [a, b], pats, slot=0)

    # ── ③ G 补教：吃饭→为什么 提问链 ─────────────────────
    print("\n[③ G 补教] 吃饭→为什么 提问链 ×%d" % R_S)
    for _ in range(R_S):
        _learn_sentence(ng, ["吃饭", "为什么"], pats, slot=0)
        _learn_sentence(ng, ["为什么", "吃饭"], pats, slot=0)
    w = edge_between(ng, pats, "吃饭", "为什么")
    print(f"  edge 吃饭→为什么 = {w:g}")

    # ── 快照 ─────────────────────────────────────────────
    save_snapshot(ng, parent="21.0",
                  tag="考试修复三部曲：造词训练（8 OOV 固化）+ H 组合"
                      "泛化词对 + G 补教（吃饭→为什么）",
                  metrics={"oov_words": sorted(oov_count),
                           "h_pairs": len(teach_pairs)},
                  vocab=vocab, pats=pats, cursor=cursor)
    print(f"\n[完成] 快照已存（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
