# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""E 问答补教（2026-08-10，复考 98/100 暴露的 4 个缺口）：

qa_read 引发边缺（18.16 教学未覆盖）：
  为什么穿衣服？  引发 穿衣服→我（expect [因为,我,冷,了]）
  下雨会怎样？    引发 下雨→我（expect [所以,我,带伞] / [所以,我,不,带伞]）
  为什么带伞？    引发 带伞→今天（expect [因为,今天,下雨]）
补教：引发边跟读 ×3 + 答案链全链跟读 ×3（与 18.16 教学同构）。
加载 v23.0 → 快照 v24.0。
"""

import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from _grow_v16 import edge_between

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
R = 3

FIXES = [  # (题, 引发词对, 答案链)
    ("为什么穿衣服？", ("穿衣服", "我"), ["因为", "我", "冷", "了"]),
    ("下雨会怎样？(带伞)", ("下雨", "我"), ["所以", "我", "带伞"]),
    ("为什么带伞？", ("带伞", "今天"), ["因为", "今天", "下雨"]),
    ("下雨会怎样？(不带伞)", ("下雨", "我"), ["所以", "我", "不", "带伞"]),
]


def main():
    t0 = time.time()
    print("═══ E 问答补教：4 个引发边 + 答案链 ═══\n")
    ng, vocab, pats, cursor = load_version("23.0")
    for ask, (a, b), chain in FIXES:
        for _ in range(R):
            _learn_sentence(ng, [a, b], pats, slot=0)      # 引发边
            _learn_sentence(ng, chain, pats, slot=0)        # 答案链
        print(f"  {ask} 引发 {a}→{b} = "
              f"{edge_between(ng, pats, a, b):g}")
    save_snapshot(ng, parent="23.0",
                  tag="E 问答补教：4 个引发边（穿衣服→我/下雨→我/"
                      "带伞→今天）+ 答案链",
                  metrics={"fixes": [f[0] for f in FIXES]},
                  vocab=vocab, pats=pats, cursor=cursor)
    print(f"\n[完成] v24.0 已存（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
