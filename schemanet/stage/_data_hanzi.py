# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""收集常用汉字表 + 常用词组表（Stage 0 字级 / Stage 1 词组级 专门数据）。

需求（用户 2026-08-09）："先收集常用汉字表、常用词组表来训练，
就像人先学字、再学词、再学句一样，然后模型要增量训练。"

来源：corpus_clean.json（v2.0 干净原料语料，词表 8 万、UNK 2%）。

- Stage 0 常用汉字表（3500，对齐《现代汉语常用字表》规模）：
  全部 token 拆单字 → 字频统计 → 过滤非汉字 → top 3500
- Stage 1 常用词组表（10000）：token 频率 → 过滤（2-4 字纯汉字词）→ top 10000

输出（对齐 data/curriculum/ 纯列表风格）：
  data/curriculum/stage0_hanzi.json        （3500 常用字）
  data/curriculum/stage1_common_words.json （10000 常用词）

用法：python _data_hanzi.py
"""

import json
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
CUR = DATA / "curriculum"

N_HANZI = 3500        # 常用字数量（现代汉语常用字表 = 2500 常用 + 1000 次常用）
N_WORDS = 10000       # 常用词数量
WORD_MIN, WORD_MAX = 2, 4   # 词组表只收 2-4 字纯汉字词


def is_hanzi(ch):
    return "\u4e00" <= ch <= "\u9fff"


def main():
    corpus = json.loads((DATA / "corpus_clean.json").read_text(encoding="utf-8"))
    print(f"语料 {len(corpus)} 句")

    # ── 字频：所有 token 拆单字 ──
    char_freq = Counter()
    for toks in corpus:
        for t in toks:
            for ch in t:
                if is_hanzi(ch):
                    char_freq[ch] += 1
    hanzi = [ch for ch, _ in char_freq.most_common(N_HANZI)]
    # 若语料覆盖不足，按需补（corpus_clean 为电商+头条，应远超 3500 字）
    print(f"总字种 {len(char_freq)} → 常用字表 {len(hanzi)}")
    print(f"  字频 top10: {hanzi[:10]}")

    # ── 词频：token 过滤（2-4 字纯汉字）──
    word_freq = Counter()
    for toks in corpus:
        for t in toks:
            if WORD_MIN <= len(t) <= WORD_MAX and all(is_hanzi(c) for c in t):
                word_freq[t] += 1
    words = [w for w, _ in word_freq.most_common(N_WORDS)]
    print(f"总词种(2-4字) {len(word_freq)} → 常用词组表 {len(words)}")
    print(f"  词频 top10: {words[:10]}")

    # ── 字覆盖检查：常用字表中，出现在常用词里的字占比 ──
    chars_in_words = {c for w in words for c in w}
    cover = len(set(hanzi) & chars_in_words) / len(hanzi)
    print(f"常用字被常用词覆盖: {cover:.3f}（学完词后字可被词反哺）")

    # ── 输出 ──
    CUR.mkdir(parents=True, exist_ok=True)
    (CUR / "stage0_hanzi.json").write_text(
        json.dumps(hanzi, ensure_ascii=False), encoding="utf-8")
    (CUR / "stage1_common_words.json").write_text(
        json.dumps(words, ensure_ascii=False), encoding="utf-8")
    (CUR / "meta.json").write_text(
        json.dumps({
            "desc": "v2.0 分级纯净数据（Phase A）",
            "source": "corpus_clean.json",
            "repeat": 10,
            "stage0_hanzi": len(hanzi), "stage1_common_words": len(words),
            "n": {"stage0": 2000, "stage1": 12000, "stage2": 30000,
                  "stage3": 15000, "stage4": 20000, "stage5": 5000},
            "seed": 42,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n写出: {CUR / 'stage0_hanzi.json'}（{len(hanzi)} 字）")
    print(f"写出: {CUR / 'stage1_common_words.json'}（{len(words)} 词）")


if __name__ == "__main__":
    main()
