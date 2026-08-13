# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""探测：OpenHowNet 义原对 v7.0 词表的覆盖率与形态（词典学词义可行性）。

问题：给定式网络学词义，用 OpenHowNet 义原作判断题数据（词↔义原 对/错）。
本脚本验证：
  1. v7.0 词表有多少词能查到义原（覆盖率）
  2. 义原的中文注释形态（能否直接作网络模式词）
  3. 义原类型粗分：类别型（含 fruit/animal/tool…英文侧）+ 属性/功能型
  4. 6 个类别标签词对应的典型义原样例
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

import OpenHowNet

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"

# 义原英文侧 → 是否"类别型"（可作类别 hub 的粗判）
CATEGORYISH_EN = {
    "fruit", "vegetable", "food", "edible", "meat", "drink", "animal", "livestock",
    "bird", "fish", "insect", "mammal", "plant", "tree", "flower", "color",
    "color_attribute", "action", "sport", "place", "InstitutePlace", "building",
    "time", "date", "season", "school", "class", "organization",
}

def main():
    t0 = time.time()
    d = OpenHowNet.HowNetDict()
    print(f"[load] OpenHowNet 就绪（{time.time()-t0:.0f}s）")

    # 1. v7.0 词表
    sents = json.loads((DATA / "stage2_sents.json").read_text(encoding="utf-8"))
    vocab = sorted({w for s in sents for w in s})
    hanzi = set(json.loads((DATA / "stage0_hanzi.json").read_text(encoding="utf-8")))
    words = [w for w in vocab if w not in hanzi]
    print(f"\n词表: 句子词 {len(vocab)} | 汉字 {len(hanzi)} | 词 {len(words)}")

    # 2. 覆盖率：能查到 ≥1 个 sense 的词
    found, missing, sememe_count = {}, [], Counter()
    t1 = time.time()
    for w in words:
        try:
            senses = d.get_sememes_by_word(w)
        except Exception:
            senses = []
        if senses:
            sems = set()
            for s in senses:
                for sm in s["sememes"]:
                    sems.add(sm)
            found[w] = sorted(sems, key=str)
            for sm in sems:
                sememe_count[sm] += 1
        else:
            missing.append(w)
    print(f"覆盖: {len(found)}/{len(words)} = {len(found)/max(1,len(words)):.3f}"
          f"（{time.time()-t1:.0f}s）")
    print(f"未覆盖词样例: {missing[:15]}")

    # 3. 义原中文注释形态（义原对象含 zh 字段）
    sample_sememes = set()
    for w in found:
        sample_sememes.update(found[w])
    print(f"\n义原总数（去重）: {len(sample_sememes)}")

    # 4. 最常用的 20 个义原（跨词覆盖）——候选类别 hub
    print("\n高频义原 top20（跨词覆盖，候选类别 hub）:")
    for sm, c in sememe_count.most_common(20):
        print(f"  {sm} × {c}")

    # 5. 类别标签词的义原样例
    print("\n6 类标签词义原样例:")
    for w in ["食物", "水果", "蔬菜", "动物", "颜色", "动作", "时间", "地点", "学校"]:
        if w in found:
            print(f"  {w}: {found[w][:8]}")
        else:
            print(f"  {w}: 未查到")

    # 6. 词↔义原矩阵规模（判断题数据量）
    edges = sum(len(v) for v in found.values())
    print(f"\n词↔义原边: {edges}（判断题正例数据）")


if __name__ == "__main__":
    main()
