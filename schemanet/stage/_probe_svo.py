# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""Stage 2.6 数据可行性探测：jieba 词性标注 → V 位动作类 / S/O 位名词类候选。

背景（方案 v2.4 §2.6）：Stage 2.5 动作类因 OpenHowNet 覆盖 0 诚实跳过 → V 位无类别
可用。本探测验证替代数据源：jieba.posseg 对 v8.5 词表的动词/名词覆盖，输出可留档的
词性标注数据 stage26_pos.json（动作类成员的离线抽取依据，机制同 stage25_sememes.json）。

过滤规则（防污染）：
  - 只取纯中文 2-4 字词（ZH24，与 2.5 一致）
  - 词性取 posseg 首个标签（多义取首标注，jieba 默认词频优先）
  - 词必须已在 v8.5 网络模式里（pats）——类别判断题要能注入

用法：python _probe_svo.py
输出：data/curriculum/stage26_pos.json（词→词性 + stats）+ 控制台统计
"""
import json
import re
import time
from collections import Counter
from pathlib import Path

import jieba.posseg as pseg

from snapshot import load_version

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
ZH24 = re.compile(r"[\u4e00-\u9fff]{2,4}$")

# 动词词性标签（jieba.posseg 约定）
V_TAGS = {"v", "vd", "vn"}          # v=动词 vd=副动词 vn=名动词
N_TAGS = {"n", "nr", "ns", "nt", "nz", "ng"}   # 名词族（普通/人名/地名/机构/专名/名语素）

# 动作类人工种子词（质量护栏：词性标注有噪声，用高频动作词锚定抽查）
V_SEEDS = {"吃", "喝", "买", "看", "学", "要", "拿", "做", "写", "读",
           "玩", "去", "来", "打", "跑", "走", "坐", "站", "听", "说",
           "画", "踢", "跳", "洗", "穿", "戴", "种", "养", "修", "借"}
# S/O 位种子（人工词表，与 2.5 CATS_MANUAL 同源；单字"我/他/家/书"等不滤）
N_SEEDS = {"我", "他", "她", "爸爸", "妈妈", "哥哥", "姐姐", "老师", "同学",
           "苹果", "香蕉", "水", "牛奶", "面包", "学校", "公园", "家", "书", "球"}


def main():
    t0 = time.time()
    ng, vocab, pats, cursor = load_version("8.5")
    words = [w for w in vocab if w in pats and ZH24.match(w)]
    print(f"[加载] 8.5（Stage 2.5 链最新）：n={ng.n}，模式 {len(pats)}，"
          f"纯中文 2-4 字词 {len(words)}（{time.time()-t0:.0f}s）")

    # 全词表词性标注（jieba 单次批量标注更稳，但词表 3 万级逐词 posseg 慢；
    # 这里只标 2-4 字词，必要时分批）
    tag_map, v_cnt, n_cnt, v_multi = {}, Counter(), Counter(), Counter()
    for w in words:
        # 整词一个 token 才取该标签；被切碎（如"三明治"→"三/明治"）取首 token 标签
        # 作近似（本探测只关心词级粗粒度词性，噪声留在动作类候选人工抽查兜底）
        tag = list(pseg.cut(w))[0].flag
        tag_map[w] = tag
        if tag in V_TAGS:
            v_cnt[tag] += 1
        if tag in N_TAGS:
            n_cnt[tag] += 1
        v_multi[tag] += 1
    print(f"[标注] {len(tag_map)} 词（{time.time()-t0:.0f}s）")

    verbs = [w for w, t in tag_map.items() if t in V_TAGS]
    nouns = [w for w, t in tag_map.items() if t in N_TAGS]
    print(f"[覆盖] 动词 {len(verbs)}（{len(verbs)/len(tag_map):.3f}）| "
          f"名词 {len(nouns)}（{len(nouns)/len(tag_map):.3f}）")

    # 动作类候选：v 标签 ∩ 高频（词表本来就是按语料频次进 pats 的，顺序即频率代理）
    v_top = verbs[:80]
    print(f"[动作类候选 top80] {v_top[:20]} …")
    v_seed_hit, v_seed_miss = [], []
    for w in V_SEEDS:
        tag = list(pseg.cut(w))[0].flag
        (v_seed_hit if w in pats and tag in V_TAGS else v_seed_miss).append((w, tag, w in pats))
    print(f"[动作种子] {len(v_seed_hit)}/{len(V_SEEDS)} 在网络且标 v: {v_seed_hit}")
    print(f"[动作种子] 未命中（词不在网络/标签非 v）: {v_seed_miss}")
    n_seed_hit, n_seed_miss = [], []
    for w in N_SEEDS:
        tag = list(pseg.cut(w))[0].flag
        (n_seed_hit if w in pats and tag in N_TAGS else n_seed_miss).append((w, tag, w in pats))
    print(f"[名词种子] {len(n_seed_hit)}/{len(N_SEEDS)} 在网络且标 n: {n_seed_hit}")
    print(f"[名词种子] 未命中: {n_seed_miss}")

    # 词性分布 top15
    print(f"[词性分布 top15] {v_multi.most_common(15)}")

    out = DATA / "stage26_pos.json"
    out.write_text(json.dumps({
        "source": "jieba.posseg",
        "version": "1.0",
        "date": time.strftime("%Y-%m-%d"),
        "base_version": "8.5",
        "words": {w: tag_map[w] for w in tag_map},
        "stats": {"total": len(tag_map),
                  "verbs": len(verbs),
                  "nouns": len(nouns),
                  "v_ratio": round(len(verbs) / len(tag_map), 4)},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[输出] {out}（{out.stat().st_size/1024:.0f} KB）")


if __name__ == "__main__":
    main()
