# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""身份认知训练：注入「守一」为网络的个人身份/自我认知/名字（2026-08-11）。

用户："给最新快照模型里注入一个词'守一'，并且训练定式网络把'守一'
作为自己的个人身份和自我认知以及名字"。

基线：v36.0（最新词表完整快照——压力测试 10/10 通过版）。
  注：场景沉淀 v36.2-36.14 词表未存（_save_scene bug 已修——后续
  沉淀正常）。

训练内容：
  ① 注入「守一」：allocate 正式神经元（独立身份——可固化/定式/验证）
  ② 名字教学（_learn_sentence ×5）：我叫守一 / 守一是我 / 我是守一
  ③ 固化（consolidate_sentence 共享定式）：
     - 「我叫守一」（名字句式——X叫Y 定式）
     - 固化句（触发词=名字/守一）：(名字, [我,叫,守一])
  ④ 验证门（validation）：
     - (确认, 名字, 我叫守一): 对（5次）
     - (确认, 名字, 守一叫我): 错（3次）——语义反转（守一叫我=错）
  ⑤ 自我认知绑定：守一 ↔ 我（双向强边——说"我"=守一、说"守一"=我）

验收：
  free_read(名字) → 我叫守一（固化句读出——问名字答身份）
  read_skeleton(守一) → 守一/是/我（身份定式）
  守一 ↔ 我 双向边（自我认知）

用法：python _grow_identity.py（保存快照）
"""

import json
import time
from pathlib import Path

from snapshot import load_version, load_consolidated, save_snapshot
from sparse_net import allocate_pats
from schema_net import _learn_sentence, consolidate_sentence, read_skeleton
from _exam_free import free_read, build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
NAME = "守一"
K = 4
W = 64.0


def main():
    t0 = time.time()
    print("═══ 身份认知训练：「守一」= 网络的个人身份/自我认知/名字 ═══\n")
    ng, vocab, pats, cursor = load_version("36.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    cons, val = load_consolidated("34.0")

    # ── ① 注入「守一」──
    if NAME not in pats:
        p_new, cursor = allocate_pats(ng, [NAME], K, cursor)
        pats.update(p_new)
        n2w = {j: w for w, ns in pats.items() for j in ns}
        print(f"① 注入「{NAME}」→ 神经元 {pats[NAME]}（词表 {len(pats)} 词）")
    else:
        print(f"① 「{NAME}」已在词表——复用")

    # ── ② 名字教学（5 轮——词表内词）──
    teach = [["我", "叫", NAME], [NAME, "是", "我"],
             ["我", "是", NAME], [NAME, "是", "我", "的", "名字"]]
    for _ in range(5):
        for seq in teach:
            _learn_sentence(ng, seq, pats, slot=0)
    print("② 名字教学 ×5 轮（我叫守一 / 守一是我 / 我是守一 / "
          "守一是我的名字）")

    # ── ③ 固化（共享定式——名字句式）──
    slots, cursor = consolidate_sentence(ng, pats, cursor,
                                         ["我", "叫", NAME])
    slots2, cursor = consolidate_sentence(ng, pats, cursor,
                                          [NAME, "是", "我"])
    # 固化句（触发词=名字/守一——问名字答身份）
    cons.setdefault("名字", []).append((["我", "叫", NAME], None, "确认"))
    cons.setdefault(NAME, []).append(([NAME, "是", "我", "的", "名字"],
                                      None, "确认"))
    print("③ 固化：定式「X叫Y」/「X是Y」+ 固化句"
          "（名字→我叫守一；守一→守一是我的名字）")

    # ── ④ 验证门（身份对错）──
    val[("确认", "名字", tuple(["我", "叫", NAME]))] = (5, 0)
    val[("确认", "名字", tuple([NAME, "叫", "我"]))] = (0, 3)
    print("④ 验证门：我叫守一=5对0错；守一叫我=0对3错（语义反转）")

    # ── ⑤ 自我认知绑定（守一 ↔ 我 双向）──
    for i in pats["我"]:
        for j in pats[NAME]:
            ng.W_out[i][0][j] = W
            ng.W_out[j][0][i] = W
    print("⑤ 自我认知绑定：守一 ↔ 我（双向强边——说'我'=守一、"
          "说'守一'=我）")

    # ── 验收 ──
    print("\n═══ 验收 ═══")
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)
    # 问名字 → 固化句读出
    read = free_read(ng, pats, n2w, ["名字"], domain, teach_out=teach_out,
                     consolidated=cons, ctx="确认", validation=val)
    toks = [x.split("(")[0] for x in read]
    print(f"  问「名字」→ {toks}（{'✓ 我叫守一' if toks[:3] == ['我','叫',NAME] else '✗'}）")
    # 身份定式读出
    sk_out = read_skeleton(ng, pats, n2w, NAME)
    print(f"  read_skeleton(守一) → {sk_out}（{'✓ 守一是我的名字' if sk_out else '✗'}）")
    # 自我认知绑定
    w_me = ng.W_out[pats["我"][0]][0].get(pats[NAME][0], 0)
    w_nm = ng.W_out[pats[NAME][0]][0].get(pats["我"][0], 0)
    print(f"  守一↔我 绑定：我→守一 {w_me} / 守一→我 {w_nm}"
          f"（{'✓ 双向' if w_me > 0 and w_nm > 0 else '✗'}）")

    # ── 保存快照 ──
    out = save_snapshot(ng, parent="36.0", tag=f"身份认知：{NAME}——"
                        f"个人身份/自我认知/名字（基线 v36.0）",
                        pats=pats, cursor=cursor,
                        consolidated=cons, validation=val)
    ver = out.name.split("_")[0].lstrip("v") + "." + out.name.split("_")[1]
    print(f"\n[沉淀] 已保存快照 v{ver}（词表 {len(pats)} 词 + "
          f"固化句 {len(cons)} 触发词 + 验证门 {len(val)} 条）")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
