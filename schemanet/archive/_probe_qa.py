# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""临时：疑问词在 v9.0 词表覆盖检查（跑完即删）。"""
from snapshot import load_version

ng, vocab, pats, cursor = load_version("9.0")
Q = ["什么", "谁", "哪里", "哪儿", "为什么", "怎么", "几", "多少", "哪",
     "怎样", "如何", "吗", "呢", "有没有", "是不是"]
print(f"n={ng.n} vocab={len(vocab)} pats={len(pats)}")
for w in Q:
    print(f"  {w}: {'在词表' if w in pats else '❌ 不在'}")
