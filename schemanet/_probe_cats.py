# -*- coding: utf-8 -*-
"""探测：stage2_sents 中 6 类词的句内共现结构（类别实验数据可行性）。

v2（2026-08-10）：输出共现图连通分量——数据驱动 hold-out 选择需要
"hold-out ↔ 训练成员 同句共现"的连通块（方案 §2.5 举一反三的前提）。
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path("data/curriculum")
sents = json.loads((DATA / "stage2_sents.json").read_text(encoding="utf-8"))
freq = Counter(w for s in sents for w in s)

CATS = {
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

def components(adj):
    """无向图连通分量（≥2 词的块）。"""
    seen = set()
    comps = []
    for w in adj:
        if w in seen:
            continue
        stack, c = [w], []
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            c.append(x)
            stack.extend(adj[x] - seen)
        if len(c) >= 2:
            comps.append(c)
    return comps


for label, ws in CATS.items():
    present = [w for w in ws if w in freq]
    if not present:
        print(f"{label}: 无词在语料")
        continue
    wset = set(present)
    co_sents = 0
    co_pairs = Counter()
    per_word = Counter()
    adj = {w: set() for w in present}
    for s in sents:
        ins = [w for w in s if w in wset]
        if len(ins) >= 2:
            co_sents += 1
            for a in ins:
                per_word[a] += 1
                for b in ins:
                    if a != b:
                        co_pairs[frozenset((a, b))] += 1
                        adj[a].add(b)
                        adj[b].add(a)
    top_pairs = co_pairs.most_common(5)
    print(f"\n{label}: 在语料 {len(present)} 词 | 同句共现句 {co_sents} | "
          f"共现词对 {len(co_pairs)}")
    print(f"  共现对样例: {[('+'.join(sorted(p)), c) for p, c in top_pairs]}")
    print(f"  词频 top8: {[(w, freq[w]) for w in sorted(present, key=lambda x: -freq[x])[:8]]}")
    print(f"  连通块(≥2词): {[len(c) for c in sorted(components(adj), key=len, reverse=True)]}")
    for c in sorted(components(adj), key=len, reverse=True):
        print(f"    {len(c)}词块: {c}")
