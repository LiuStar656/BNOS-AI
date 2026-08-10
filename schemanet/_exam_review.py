# -*- coding: utf-8 -*-
"""考试答案审查：全量打印 170 题实际读出序列 + 无约束自由读取对照
（用户："你看一遍网络在之前考试的答案，不要光看分数"）。

审查点：
① 约束判定（考试口径）的实际读出——每题的 read 序列
② 自由读取对照：同样 front 下，不用期望链约束（domain=None、不找
   rest[0]），网络"自然想说"什么（top-1 链）——对照约束结果，看
   100/100 是"真会"还是"边存在性验证"
③ 判定口径弱点标注：F 层2 是"边存在即通"（read 硬编码），E 的
   引发边检查等

用法：python _exam_review.py 24.0
"""

import sys
from pathlib import Path

from snapshot import load_version
from _grow_v16 import edge_between, direct_next_multi
from _exam_big import (A_PAIRS, B_SENTS, C_SENTS, D_SENTS, H_SENTS, I_SENTS,
                       chain_read, oov_chain_read)

DATA = Path(__file__).parent / "data" / "curriculum"
VER = sys.argv[1] if len(sys.argv) > 1 else "24.0"


def free_read(ng, pats, n2w, front, k=8, steps=6):
    """无约束自由读取：front[-1] 出发，top-1 贪心链读（不加期望链）。
    返回 (读出词表, 断步)。"""
    seq = []
    cur = front[-1]
    for _ in range(steps):
        top = direct_next_multi(ng, pats, n2w, [cur], k=k, domain=None)
        if not top:
            break
        nxt, wt = top[0]
        if nxt in seq[-3:]:            # 防自环/循环
            seq.append(f"[循环]{nxt}")
            break
        seq.append(f"{nxt}{wt:g}")
        cur = nxt
    return seq


def main():
    ng, vocab, pats, cursor = load_version(VER)
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())

    # 组题（与考试一致）
    sections = [
        ("A 词语搭配", [("", [a], [b]) for a, b in A_PAIRS], "chain"),
        ("B 短句接话", [(s, f, b) for s, f, b in B_SENTS], "chain"),
        ("C 扩句修饰", [(s, f, b) for s, f, b in C_SENTS], "chain"),
        ("D 关系句", [(s, f, b) for s, f, b in D_SENTS], "chain"),
        ("H 压轴未见组合", [(s, f, b) for s, f, b in H_SENTS], "chain"),
        ("I OOV 字造词", [(s, f, b) for s, f, b in I_SENTS], "oov"),
    ]
    print(f"═══ 答案审查（v{VER}）：约束读出 vs 自由读出 ═══\n")
    for name, items, kind in sections:
        print(f"── {name} ──")
        for i, (sent, front, back) in enumerate(items, 1):
            if kind == "oov":
                read, brk = oov_chain_read(ng, pats, n2w, front, back, keys)
                disp = "/".join(read) or "∅"
            else:
                read, brk = chain_read(ng, pats, n2w, front, back)
                disp = "/".join(read) or "∅"
            free = " ".join(free_read(ng, pats, n2w, front))
            mark = "✅" if disp == "/".join(back) else "✗"
            brk_s = f"断{brk}" if brk else ""
            print(f"  {mark} {i:2d}「{sent or '/'.join(front)}」"
                  f"\n      期:{'/'.join(back)}\n      束:{disp} {brk_s}"
                  f"\n      自:{free}")
        print()

    # E 问答 / F 表达 / G 提问（各自判定函数）
    from _grow_qa_s3 import build_pool as qa_build_pool, qa_read
    from _grow_cat import build_cats
    from _grow_self_express import STATES, FCT_ITEMS, CAUSE_ITEMS
    from _grow_s3_ask import NEW_ASKS, RHET_ITEMS
    from _grow_s3_ask import chain_read as ask_chain_read
    import json

    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)

    print("── E 问答（qa_read）──")
    for i, (ask, kw, exp, layer) in enumerate(q_pool[:15], 1):
        read = qa_read(ng, pats, n2w, kw, exp)
        disp = "".join(read) or "∅"
        free = " ".join(free_read(ng, pats, n2w, [kw]))
        mark = "✅" if read == exp else "✗"
        trig = edge_between(ng, pats, kw, exp[1]) if len(exp) > 1 else 0
        print(f"  {mark} {i:2d}「{ask}」kw={kw} 引发={trig:g}"
              f"\n      期:{'/'.join(exp)}\n      束:{disp}"
              f"\n      自:{free}")
    print()

    print("── F 自我表达（express_read + 层2 读边版）──")
    f_items = ([(st, [st], d["expr"]) for st, d in STATES.items()]
               + [(n, [kw], ch) for n, ch, kw, t in FCT_ITEMS[:4]]
               + [(n, [kw], ch) for n, ch, kw in [CAUSE_ITEMS[0]]])
    for i, (sent, front, back) in enumerate(f_items, 1):
        if front[0] in set(STATES) and back[0] == "我":
            e = edge_between(ng, pats, "我", back[1])
            ok = e > 0
            disp = "我" + back[1] if ok else "∅"
            note = f"（层2 读边版：我→{back[1]}={e:g}）"
        else:
            from _grow_self_express import express_read
            read, st = express_read(ng, pats, n2w, front[0], back)
            ok = read == back
            disp = "".join(read) or "∅"
            note = f"（引发={st}）"
        free = " ".join(free_read(ng, pats, n2w, front))
        print(f"  {'✅' if ok else '✗'} {i:2d}「{sent}」{note}"
              f"\n      期:{'/'.join(back)}\n      束:{disp}"
              f"\n      自:{free}")
    print()

    print("── G 主动提问（ask 链读）──")
    g_items = [(q, [kw], qch) for q, kw, qch, ach in NEW_ASKS]
    g_items += [(n, [ch[0]], ch[1:]) for n, ch, k in RHET_ITEMS]
    for i, (sent, front, back) in enumerate(g_items, 1):
        read = ask_chain_read(ng, pats, n2w, front[0], back)
        disp = "".join(read) or "∅"
        free = " ".join(free_read(ng, pats, n2w, front))
        print(f"  {'✅' if read == back else '✗'} {i:2d}「{sent}」"
              f"\n      期:{'/'.join(back)}\n      束:{disp}"
              f"\n      自:{free}")


if __name__ == "__main__":
    main()
