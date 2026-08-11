# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""探测：stage25_sememes 中 6 类标签义原的成员规模与共享属性义原（v3 词典学词义设计依据）。

v3（2026-08-10）：验证门判断题训练范围 = 6 类标签下的成员词↔义原边；
类别举一反三（hold-out）靠"与训练成员共享属性义原"走链。本脚本确认：
  1. 6 类标签义原（水果/食物/动物/兽/颜色/时间/行动/场所/位置）存在性与成员词数
  2. 成员词是否都在 v7.0 pats（已学词形）
  3. 训练成员与 hold-out 共享属性义原的比例（走链可行性）
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from snapshot import load_version

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"

# v7.0 词形过滤：只学纯中文 2-4 字词（HowNet 英文/专名义项混入严重）
ZH = re.compile(r"[\u4e00-\u9fff]{2,4}$")

LABELS = {
    "食物": ["水果", "食物"],
    "动物": ["动物", "兽"],
    "颜色": ["颜色"],
    "时间": ["时间"],
    "动作": ["行动"],
    "地点": ["场所", "位置"],
}

# v2 人工类别词表（数据质量护栏：训练成员优先用人工词表 ∩ 词典成员）
CATS_MANUAL = {
    "食物": ["苹果", "香蕉", "西瓜", "米饭", "面包", "鸡蛋", "牛奶", "水果", "蔬菜",
             "猪肉", "牛肉", "鸡肉", "蛋糕", "面条", "土豆", "萝卜", "葡萄", "草莓",
             "饺子", "馒头", "饼干", "橘子", "梨", "桃", "花生", "豆腐"],
    "动物": ["猫", "狗", "鸟", "鱼", "马", "牛", "羊", "猪", "鸡", "鸭",
             "兔子", "老虎", "大象", "猴子", "狮子", "熊", "狼", "蛇",
             "狐狸", "熊猫", "老鼠", "青蛙", "蝴蝶", "蚂蚁"],
    "颜色": ["红", "黄", "蓝", "白", "黑", "绿", "紫", "灰",
             "红色", "黄色", "蓝色", "绿色", "白色", "黑色", "粉色", "金色"],
    "动作": ["吃", "跑", "跳", "走", "看", "听", "说", "写", "读", "唱",
             "玩", "笑", "哭", "站", "坐", "打", "拿", "放", "开", "关",
             "洗", "买", "卖", "喝"],
    "时间": ["今天", "明天", "昨天", "早上", "晚上", "中午", "下午",
             "时候", "现在", "后来", "以前", "最近", "上午", "白天", "夜里",
             "春天", "夏天", "秋天", "冬天"],
    "地点": ["学校", "公园", "家", "医院", "商店", "超市", "图书馆", "办公室",
             "机场", "车站", "银行", "饭店", "工厂", "教室", "宿舍", "市场",
             "电影院", "书店"],
}


def main():
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    words = sem["words"]
    print(f"[数据] 覆盖词 {sem['stats']['covered']}，义原 {sem['stats']['sememes']}，"
          f"边 {sem['stats']['edges']}")

    # 义原集合（全量）+ 频次
    sfreq = Counter()
    for sems in words.values():
        for s in sems:
            sfreq[s] += 1

    # 确认标签义原存在性
    print("\n[标签义原存在性]")
    for label, tags in LABELS.items():
        hit = [(t, sfreq.get(t, 0)) for t in tags]
        print(f"  {label}: {hit}")

    # 加载 v7.0 词表
    ng, vocab, pats, cursor = load_version("7.0")
    vocab_set = set(vocab)
    print(f"\n[加载] v7.0: n={ng.n}，模式 {len(pats)}，词表 {len(vocab)}")

    # 每类成员：词的义原列表含该类任一标签义原，且在 v7.0 pats，纯中文 2-4 字
    print("\n[类别成员（纯中文 2-4 字过滤后）]")
    cat_members = {}
    for label, tags in LABELS.items():
        members = [w for w, sems in words.items()
                   if w in pats and ZH.match(w)
                   and any(t in sems for t in tags)]
        cat_members[label] = members
        # 标签词本身是否已在 v7.0 pats（复用 hub 模式）
        tags_in = [(t, t in pats) for t in tags]
        # 成员词的属性义原分布（非标签义原）
        attrs = Counter()
        for w in members:
            for s in words[w]:
                if s not in tags:
                    attrs[s] += 1
        print(f"  {label}({tags}): 标签在pats {tags_in} | 成员 {len(members)} 词")
        print(f"    共享属性义原 top8: {attrs.most_common(8)}")
        print(f"    样例: {members[:10]}")

    # 人工词表 ∩ 词典成员 ∩ pats（候选训练成员）
    print("\n[人工词表 ∩ 词典成员（训练成员候选）]")
    train_cand = {}
    for label in CATS_MANUAL:
        tags = set(LABELS[label])
        got = [(w, [s for s in words.get(w, []) if s not in tags])
               for w in CATS_MANUAL[label]
               if w in words and w in pats and w not in tags]
        train_cand[label] = got
        print(f"  {label}: {len(got)}/{len(CATS_MANUAL[label])} 词有词典义原")
        print(f"    样例: {[w for w, _ in got][:12]}")
        print(f"    义原例: {[(w, a[:4]) for w, a in got[:3]]}")

    # 人工词表词完整义原（定标签组依据）
    print("\n[人工词表词完整义原]")
    for label, ws in CATS_MANUAL.items():
        print(f"  ── {label} ──")
        for w in ws:
            sems = words.get(w)
            if sems is not None and w in pats:
                print(f"    {w}: {sems}")
            else:
                print(f"    {w}: (无词典义原{'/' + '未学' if w not in pats else ''})")

    # 共享属性义原可行性：前 30 成员两两共享非标签义原的对数
    print("\n[共享属性义原（走链可行性，纯中文过滤后）]")
    for label, members in cat_members.items():
        tags = set(LABELS[label])
        top = members[:30]
        share = 0
        for a in top:
            sa = set(words[a]) - tags
            for b in top:
                if a < b:
                    sb = set(words[b]) - tags
                    if sa & sb:
                        share += 1
        pairs = len(top) * (len(top) - 1) // 2
        print(f"  {label}: 前 {len(top)} 词 {share}/{pairs} 对共享属性义原"
              f"（{share/max(1,pairs):.2f}）")


if __name__ == "__main__":
    main()
