# -*- coding: utf-8 -*-
"""考试卷面生成（2026-08-10，用户："重新进行考试，不要用代码打分，
做完后你来评卷"）。

输出格式：题目 → 网络回答（约束读出）| 网络自己说（无约束自由读）
——不做任何 ✅/✗/分数判定，全部留给人评卷。

用法：python _exam_paper.py 24.0 > 卷面.txt
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
    """无约束自由读取：front[-1] 出发 top-1 贪心链（网络自己开口）。"""
    seq = []
    cur = front[-1]
    for _ in range(steps):
        top = direct_next_multi(ng, pats, n2w, [cur], k=k, domain=None)
        if not top:
            break
        nxt, wt = top[0]
        if nxt in seq[-3:]:
            seq.append(f"[循环]{nxt}")
            break
        seq.append(f"{nxt}")
        cur = nxt
    return seq


def main():
    ng, vocab, pats, cursor = load_version(VER)
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    print(f"═ 定式网络考试卷面（v{VER}）═ 网络回答 = 约束读出（期望链"
          f"提示下的接话）；网络自己说 = 无约束 top-1 链\n")

    sections = [
        ("A 词语搭配", [("「{0}」，接下来说什么？", [a], [b])
                        for a, b in A_PAIRS], "chain"),
        ("B 短句接话", [(s, f, b) for s, f, b in B_SENTS], "chain"),
        ("C 扩句修饰", [(s, f, b) for s, f, b in C_SENTS], "chain"),
        ("D 关系句", [(s, f, b) for s, f, b in D_SENTS], "chain"),
        ("H 压轴未见组合", [(s, f, b) for s, f, b in H_SENTS], "chain"),
        ("I OOV 字造词", [(s, f, b) for s, f, b in I_SENTS], "oov"),
    ]
    for name, items, kind in sections:
        print(f"── {name} ──")
        for i, (sent, front, back) in enumerate(items, 1):
            if kind == "oov":
                read, brk = oov_chain_read(ng, pats, n2w, front, back, keys)
            else:
                read, brk = chain_read(ng, pats, n2w, front, back)
            paper = sent.format(front[0]) if "{" in sent else sent
            print(f"【{i}】{paper}")
            print(f"  网络回答：{'/'.join(read) or '（说不出）'}"
                  f"{'（链断 ' + '→'.join(str(x) for x in brk) + '）' if brk else ''}")
            print(f"  参考回答：{'/'.join(back)}")
            print(f"  网络自己说：{'/'.join(free_read(ng, pats, n2w, front)) or '（说不出）'}\n")

    # E / F / G
    from _grow_qa_s3 import build_pool as qa_build_pool, qa_read
    from _grow_cat import build_cats
    from _grow_self_express import STATES, FCT_ITEMS, CAUSE_ITEMS, express_read
    from _grow_s3_ask import NEW_ASKS, RHET_ITEMS
    from _grow_s3_ask import chain_read as ask_chain_read
    import json

    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)

    print("── E 问答 ──")
    for i, (ask, kw, exp, layer) in enumerate(q_pool[:15], 1):
        read = qa_read(ng, pats, n2w, kw, exp)
        print(f"【{i}】{ask}")
        print(f"  网络回答：{''.join(read) or '（说不出）'}")
        print(f"  参考回答：{'/'.join(exp)}")
        print(f"  网络自己说：{'/'.join(free_read(ng, pats, n2w, [kw])) or '（说不出）'}\n")

    print("── F 自我表达 ──")
    f_items = ([(f"你觉得{st}，你会说什么？", [st], d["expr"])
                for st, d in STATES.items()]
               + [(f"情境：{n}", [kw], ch) for n, ch, kw, t in FCT_ITEMS[:4]]
               + [(f"情境：{CAUSE_ITEMS[0][0]}", [CAUSE_ITEMS[0][2]],
                   CAUSE_ITEMS[0][1])])
    for i, (sent, front, back) in enumerate(f_items, 1):
        read, st = express_read(ng, pats, n2w, front[0], back)
        print(f"【{i}】{sent}")
        print(f"  网络回答：{''.join(read) or '（说不出）'}")
        print(f"  参考回答：{'/'.join(back)}")
        print(f"  网络自己说：{'/'.join(free_read(ng, pats, n2w, front)) or '（说不出）'}\n")

    print("── G 主动提问 ──")
    g_items = [(q, [kw], qch) for q, kw, qch, ach in NEW_ASKS]
    g_items += [(f"（教师说：{n}）", [ch[0]], ch[1:]) for n, ch, k in RHET_ITEMS]
    for i, (sent, front, back) in enumerate(g_items, 1):
        read = ask_chain_read(ng, pats, n2w, front[0], back)
        print(f"【{i}】{sent}")
        print(f"  网络回答：{''.join(read) or '（说不出）'}")
        print(f"  参考回答：{'/'.join(back)}")
        print(f"  网络自己说：{'/'.join(free_read(ng, pats, n2w, front)) or '（说不出）'}\n")


if __name__ == "__main__":
    main()
