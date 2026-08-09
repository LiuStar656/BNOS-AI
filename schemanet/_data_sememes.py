# -*- coding: utf-8 -*-
"""抽取 OpenHowNet 义原 → data/curriculum/stage25_sememes.json（Stage 2.5 词典学词义数据）。

需求（方案 v2.4 §2.5）：词义 = 词↔义原关联集合。OpenHowNet（清华 THUNLP 开源，MIT）
约 2000 义原标注 20 万概念。本脚本把 v7.0 词表（stage2_sents 的词）的义原标注
抽取为可留档的判断题数据：{"苹果": ["水果", "树", ...]}（义原中文注释去重）。

过滤规则（防污染网络词表）：
  - 只取纯汉字注释（跳过含数字/英文/标点的义原注释）
  - 注释长度 1-4 字（跳过"特定牌子"等过长属性短语）
  - 跳过单字停用（的/了/是/在…，虚词不作物义）
  - 词本身无任何合格义原 → 不进表（覆盖率的诚实反映）

用法：python _data_sememes.py
输出：data/curriculum/stage25_sememes.json + 控制台统计
"""
import json
import re
import time
from collections import Counter
from pathlib import Path

import OpenHowNet

DATA = Path(__file__).parent / "data" / "curriculum"

# 停用义原（虚词/功能词类，不作物义）
STOP = {"的", "了", "是", "在", "和", "与", "或", "及", "等", "们", "被", "把",
        "给", "对", "从", "为", "以", "而", "但", "如果", "由于", "因为", "所以",
        "虽然", "但是", "专", "单位", "值"}

# 义原中文注释：多字白名单检查（有些义原注释像"举止值/样式值"是 HowNet 属性值，
# 保留有语义的，过滤明显的元标注）
JUNK = {"样式值", "属性值", "行为值", "举止值", "特定牌子", "北朝鲜"}


def clean_sememe(sm):
    """Sememe 对象 → 中文注释（str(sm) 形如 'fruit|水果'，取 | 后中文）。"""
    s = str(sm)
    zh = s.split("|")[-1].strip() if "|" in s else s.strip()
    if not zh or len(zh) > 4 or not re.fullmatch(r"[\u4e00-\u9fff]+", zh):
        return None
    if zh in STOP or zh in JUNK:
        return None
    return zh


def main():
    t0 = time.time()
    d = OpenHowNet.HowNetDict()
    print(f"[load] OpenHowNet 就绪（{time.time()-t0:.0f}s）")

    sents = json.loads((DATA / "stage2_sents.json").read_text(encoding="utf-8"))
    hanzi = set(json.loads((DATA / "stage0_hanzi.json").read_text(encoding="utf-8")))
    vocab = sorted({w for s in sents for w in s if w not in hanzi})
    print(f"[词表] v7.0 词（stage2_sents 去汉字）: {len(vocab)}")

    sememes, sememe_freq, covered, missing = {}, Counter(), 0, []
    t1 = time.time()
    for w in vocab:
        try:
            senses = d.get_sememes_by_word(w)
        except Exception:
            senses = []
        if not senses:
            missing.append(w)
            continue
        sems = set()
        for s in senses:
            for sm in s["sememes"]:
                zh = clean_sememe(sm)
                if zh:
                    sems.add(zh)
        if sems:
            sememes[w] = sorted(sems)
            covered += 1
            for sm in sems:
                sememe_freq[sm] += 1
        else:
            missing.append(w)
    print(f"[抽取] 覆盖 {covered}/{len(vocab)} = {covered/max(1,len(vocab)):.3f}"
          f"（{time.time()-t1:.0f}s）")
    print(f"[义原] 去重 {len(sememe_freq)}，总边 {sum(sememe_freq.values())}")
    print(f"[高频义原 top20]（跨词覆盖，候选类别 hub）:")
    for sm, c in sememe_freq.most_common(20):
        print(f"  {sm} × {c}")
    print(f"[样例]")
    for w in ["苹果", "西瓜", "猫", "学校", "吃", "红色", "今天"]:
        print(f"  {w}: {sememes.get(w, '未覆盖')[:8]}")

    out = DATA / "stage25_sememes.json"
    out.write_text(json.dumps({"source": "OpenHowNet",
                               "version": "2.0",
                               "date": time.strftime("%Y-%m-%d"),
                               "words": sememes,
                               "stats": {"covered": covered,
                                         "total": len(vocab),
                                         "sememes": len(sememe_freq),
                                         "edges": sum(sememe_freq.values())}},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[输出] {out}（{out.stat().st_size/1024:.0f} KB）")


if __name__ == "__main__":
    main()
