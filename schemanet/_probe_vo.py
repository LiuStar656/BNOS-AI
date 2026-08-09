# -*- coding: utf-8 -*-
"""临时：真实语料动宾共现探测（跑完即删）。

目标：验证"语料驱动搭配"可行性——V 集动词在真实语料里后接名词的频率，
若"吃/喝/买"后接"苹果/米饭/牛奶"类高频 → 从语料就能学搭配，无需人工表。
语料：raw/ 外卖评论（waimai）+ 头条新闻（toutiao）。
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import jieba.posseg as pseg

DATA = Path(__file__).parent / "data" / "curriculum"
V_SET = ["吃", "喝", "买", "看", "学", "画", "踢", "洗", "读", "听", "要"]

def text_lines():
    """语料文本迭代器：外卖评论 + 头条标题。"""
    wm = DATA / "raw" / "waimai.csv"
    try:
        with wm.open(encoding="utf-8-sig") as f:
            rd = csv.reader(f)
            head = next(rd)
            ci = next((i for i, h in enumerate(head)
                       if "comment" in h.lower() or "review" in h.lower()
                       or "text" in h.lower()), 0)
            for row in rd:
                if len(row) > ci and row[ci].strip():
                    yield row[ci]
    except FileNotFoundError:
        pass
    tt = DATA / "raw" / "toutiao_cat_data.txt"
    try:
        for line in tt.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                yield parts[1]
    except FileNotFoundError:
        pass

def main():
    vo = {v: Counter() for v in V_SET}
    n_sent = 0
    for t in text_lines():
        n_sent += 1
        words = list(pseg.cut(t))
        for idx, (w, fl) in enumerate(words):
            if w in V_SET:
                # 后接 1-2 个名词（跳过量词/助词）：如 吃(苹果) 买(一瓶牛奶)
                for off in (1, 2):
                    if idx + off < len(words):
                        w2, f2 = words[idx + off]
                        if w2 in V_SET or len(w2) == 0:
                            continue
                        if f2.startswith("n") and w2 not in ("了", "的", "吧", "啊"):
                            vo[w][w2] += 1
                            break
    print(f"句数: {n_sent}")
    for v in V_SET:
        top = vo[v].most_common(8)
        tot = sum(vo[v].values())
        print(f"  {v}: 共现宾语词频 {tot} 条 → {top}")

if __name__ == "__main__":
    main()
