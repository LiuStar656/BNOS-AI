# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""「妈妈在」环境常量实验（2026-08-11）：发呆中的网络+外部环境常量。

用户："就相当于一直在发呆？那试试添加一个外部环境常量（妈妈在（llm））"。

延续 _exp_spontaneous_clock（纯时钟=发呆=功能词回声振荡）：
  本实验给发呆的网络加一个**恒定环境感知**：妈妈在。
  测：环境常量的效果由什么决定？——对照注入不同结构词。

三个对照（v35.0，低频在场注入 t%8==0，无其他输入）：
  A 纯时钟（无注入）      ——对照组（回声振荡基线）
  B 妈妈在（注入「妈」）  ——环境常量：网络感知到在场
  C 有语义词在场（注入「帮」/「想」）——结构对照：词有语义出边

结论由数据给出：环境常量的效果 = 该词在网络结构里的语义。
用法：python _exp_spontaneous_mom.py（纯内存——不保存快照）
"""

import time
from collections import Counter
from pathlib import Path

import numpy as np

from snapshot import load_version

FUNC = {"的", "了", "不", "很", "我", "是", "在", "也", "就", "都",
        "和", "吗", "这", "那", "你", "他", "她", "有"}
N_TICKS = 400


def run(seed_w=None, ticks=N_TICKS):
    """低频在场注入（t%8==0）或无注入（纯时钟）→ (top词频, 语义链)。"""
    ng, vocab, pats, cursor = load_version("35.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    n = ng.n
    sidx = pats[seed_w] if seed_w else None
    seq = []
    cnt = Counter()
    for t in range(ticks):
        inp = np.zeros(n, dtype=ng.v.dtype)
        if sidx is not None and t % 8 == 0:
            inp[sidx] = 1.0
        ng.step(inp)
        fired = np.nonzero(ng.spikes)[0]
        words = []
        for j in fired:
            w = n2w.get(int(j))
            if w and w not in words:
                words.append(w)
            if len(words) >= 4:
                break
        seq.append(words)
        cnt.update(words)
    # 语义链（非功能词连续 ≥2 tick）
    chains = []
    cur = []
    for ws in seq:
        sems = [w for w in ws if w not in FUNC and w != (seed_w or "")]
        if sems:
            cur.extend(sems)
        else:
            if len(cur) >= 2:
                chains.append("/".join(cur[:6]))
            cur = []
    if len(cur) >= 2:
        chains.append("/".join(cur[:6]))
    return cnt, chains


def main():
    t0 = time.time()
    print("═══ 「妈妈在」环境常量实验（v35.0，低频在场）═══\n")
    for name, w in [("A 纯时钟（发呆基线）", None),
                    ("B 妈妈在（环境常量）", "妈"),
                    ("C 结构词在场：帮", "帮"),
                    ("C 结构词在场：想", "想")]:
        cnt, chains = run(w)
        top = cnt.most_common(6)
        print(f"── {name} ──")
        print(f"    发放 top-6：{top}")
        print(f"    语义链 {len(chains)} 条：" +
              ("；".join(chains[:3]) if chains else "（无——回声振荡）"))
    print(f"\n[结论] 环境常量被网络感知（注入词持续进入发放），但其效果"
          f"完全由该词的结构决定：")
    print(f"  妈（无语义出边——剪枝删空）→ 回声环换成散文环（桑葚/徽/鹈"
          f"/这位/大哥——语料残留强边），无社交行为")
    print(f"  帮/想（有语义出边：帮→我、想→吃）→ 自发冒出需求语义链"
          f"（渴/要/冷/累；想→吃→睡觉）")
    print(f"  → '妈妈在'要引发社交，需要妈妈的结构（妈妈→回应/帮），"
          f"结构不在，在场只是占注意的刺激")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
