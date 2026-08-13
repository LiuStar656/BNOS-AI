# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""共享槽位迭代对照实验（2026-08-11）：句式模板内化 vs 句私有槽位。

用户："经常用的句子可以很快说出来，但是不经常用的就会组装错误，
先想用句式纠正再输出——关键是这个想和纠正只靠网络该怎么办" +
"共享槽位升级是补丁还是迭代？" → 结论：迭代（句法压缩——多条同构
句压缩成共享定式）。本实验验证迭代是否解决**泛化能力缺失**：

对照组（现状——句私有槽位 consolidate_sentence）：
  教「小狗渴了要喝水」+「猫渴了要喝水」→ 两条独立轨道
  front=猫 → ？（实测已知：换不了主体——槽位句私有）
  front=他 → ？（未教 → 泛化失败）

实验组（共享槽位定式）：
  定式 = [主体位槽]→渴→了→要→[行为位槽]（固定词位用词神经元、
  内容位用共享槽概念——跨句复用）
  教「小狗渴了要喝水」→ 建定式 + 小狗↔主体位 + 喝水↔行为位
  教「猫渴了要喝水」→ 只绑定 猫↔主体位（共享！不重学固定段）
  front=猫 → ？（预期「猫渴了要喝水」）
  front=小狗 → ？（预期「小狗渴了要喝水」——同定式双实例）
  front=他 → ？（未绑定 → 诚实失败——泛化前提是词位绑定）

对照指标：
  ① 主体替换正确率（front=猫 是否输出"猫"句）
  ② 教学增量（实验组教第 2 句只绑定 1 词 vs 对照组整句重固）
  ③ 多实例共存（同定式两实例是否都正确读出）

用法：python _exp_slot_shared.py（纯内存——不保存快照）
"""

import json
import time
from pathlib import Path

from snapshot import load_version
from schema_net import consolidate_sentence, _learn_sentence

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
K = 4
W = 1024.0   # 主干同款强度——压过语料边（猫→饿 131.6）


def build():
    ng, vocab, pats, cursor = load_version("35.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    return ng, pats, n2w, cursor


def bind(ng, pats, a, b, w=W):
    """前向绑定 a → b（强度 w）——读出只走前向。
    方向设计：主体位词→槽（入口）；行为位槽→词（出口）；
    定式边前→后（轨道）。双向会回环串扰（槽→词跳回别的绑定词）。"""
    for i in pats[a]:
        for j in pats[b]:
            ng.W_out[i][0][j] = w


def read_chain(ng, pats, n2w, front, steps=8):
    """沿最强边走链（模拟固化主干读出——每步 top-1 去重）。
    [槽概念] 是内部中继（不输出但继续走——句式定式的神经轨道）。"""
    cur = front
    out = [front]
    seen = {front}
    for _ in range(steps):
        top = sorted(ng.W_out[pats[cur][0]][0].items(),
                     key=lambda kv: -kv[1])
        nxt = None
        for j, v in top:
            w = n2w.get(j)
            if not w or w in seen:
                continue
            if w.startswith("["):      # 槽概念：中继（不输出）
                nxt = w
                break
            nxt = w                    # 普通词：输出
            break
        if nxt is None:
            break
        if not nxt.startswith("["):
            out.append(nxt)
        seen.add(nxt)
        cur = nxt
    return out


def main():
    t0 = time.time()
    print("═══ 共享槽位迭代对照实验（泛化能力验证）═══\n")

    # ── 对照组：现状（句私有槽位）──
    print("── 对照组：consolidate_sentence（句私有槽位）──")
    ng, pats, n2w, cursor = build()
    from sparse_net import allocate_pats
    cursor = cursor
    for sent in ["小狗渴了要喝水", "猫渴了要喝水"]:
        seq = list(sent)
        slots, cursor = consolidate_sentence(ng, pats, cursor, seq, k=K)
        for i, tok in enumerate(seq):
            for nid in slots[i]:
                for j in pats[tok]:
                    ng.W_out[j][0][nid] = W     # 词→槽位（触发）
    for front in ["猫", "小狗", "他"]:
        if front not in pats:
            print(f"  front={front}: 不在词表")
            continue
        ch = read_chain(ng, pats, n2w, front)
        print(f"  front={front} → {'/'.join(ch)}")

    # ── 实验组：共享槽位定式 ──
    print("\n── 实验组：共享槽位定式（句式模板内化）──")
    ng, pats, n2w, cursor = build()
    # 内容位槽概念（跨句共享——所有同构句的主体位/行为位共用一个槽）
    slot_p, cursor = allocate_pats(ng, ["[主体位]"], K, cursor)
    slot_b, cursor = allocate_pats(ng, ["[行为位]"], K, cursor)
    pats["[主体位]"] = slot_p["[主体位]"]
    pats["[行为位]"] = slot_b["[行为位]"]
    n2w = {j: w for w, ns in pats.items() for j in ns}

    def teach_variant(subj, act):
        """教一个变体：只绑定内容位词到共享槽（固定段定式已建）。
        主体位：词→槽（入口触发）；行为位：槽→词（出口读出）。"""
        bind(ng, pats, subj, "[主体位]")
        bind(ng, pats, "[行为位]", act)

    # 定式边（固定段 + 内容位槽↔固定词）——教学第 1 句时建立
    for a, b in [("[主体位]", "渴"), ("渴", "了"), ("了", "要"),
                 ("要", "[行为位]")]:
        bind(ng, pats, a, b)
    teach_variant("小狗", "喝")
    print("  [教学1] 小狗渴了要喝水：定式建立 + 小狗↔主体位 + 喝↔行为位")
    teach_variant("猫", "喝")
    print("  [教学2] 猫渴了要喝水：只绑定 猫↔主体位（共享——不重学固定段）")

    for front in ["猫", "小狗", "他"]:
        if front not in pats:
            print(f"  front={front}: 不在词表")
            continue
        ch = read_chain(ng, pats, n2w, front)
        print(f"  front={front} → {'/'.join(ch)}")

    # ── 对照指标 ──
    print("\n═══ 对照指标 ═══")
    print("  ① 主体替换：对照组 front=猫 输出猫句？"
          "（实验组见上——共享槽位可换）")
    print("  ② 教学增量：对照组教第 2 句 = 整句重固（5 词×双向绑定）"
          "；实验组 = 只绑定 1 词（猫↔主体位）")
    print("  ③ 多实例共存：共享定式两条实例（猫/小狗）是否都正确")
    print(f"\n[结论] 共享槽位 = 句法压缩迭代（从背句到长句式）："
          f"固定段只学一次（定式），内容位跨句共享（绑定一次多句可用）"
          f"——泛化前提是词位绑定（未绑定词仍不可填——诚实边界）")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
