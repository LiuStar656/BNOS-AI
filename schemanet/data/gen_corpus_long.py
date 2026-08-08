# -*- coding: utf-8 -*-
"""生成 corpus_long.json：长程关联语料（ctx 距末词 >3 词位置破平局）。

设计（对应 Phase 4 验收"学到 Hebbian 学不动的模式：长程关联（>3 词）"）：

每组的模式（ctx1/ctx2 分属两个语义锚）：
    长句（4 词前缀）：ctx fill1 fill2 mid tgtA / ctx fill1 fill2 mid tgtB
                      → mid 的后继在 tgtA/tgtB 间平局（各 1:1）
    短句（2 词）：     ctx tgtA / ctx tgtB（ctx 与目标词**直接相邻**出现）
                      → W 沉淀 ctx→tgt 直接转移

关键：完整前缀 [ctx, fill1, fill2, mid]（4 词）中，ctx 距末词 mid 3 个位置
（pos=3）。bigram/wsum 只看末词 mid 的后继 → 平局无法破；只有梯度读出学到
ctx_wgt[pos=3] > 0（信任远端 ctx 的转移）才能破局 → 长程关联的可验证场景。

对照组设计：ctx2 与 tgtB 锚定（"小红跳舞"）→ 前缀 [小红,和,朋友,一起] 应破
平局指向 跳舞；若 ctx_wgt 学反（信任错误远端）则指向 唱歌。
"""
import json
from pathlib import Path

import jieba

# (ctx1, ctx2, fill1, fill2, mid, tgtA, tgtB)
GROUPS = [
    ("小明", "小红", "和", "朋友", "一起", "唱歌", "跳舞"),
    ("春天", "秋天", "的", "风", "很", "舒服", "干燥"),
    ("爸爸", "妈妈", "喜欢", "在", "厨房", "做饭", "看书"),
    ("早上", "晚上", "常常", "在", "客厅", "跑步", "睡觉"),
]

RPT = 12

sentences = []
for ctx1, ctx2, f1, f2, mid, tgtA, tgtB in GROUPS:
    for _ in range(RPT):
        sentences += [
            f"{ctx1}{f1}{f2}{mid}{tgtA}",   # mid 后继平局侧 A
            f"{ctx1}{f1}{f2}{mid}{tgtB}",
            f"{ctx2}{f1}{f2}{mid}{tgtA}",   # mid 后继平局侧 B
            f"{ctx2}{f1}{f2}{mid}{tgtB}",
            f"{ctx1}{tgtA}",                # ctx→tgt 直接转移锚定
            f"{ctx2}{tgtB}",
        ]

# 分词校验（验证填充词不被 jieba 合词，保证前缀长度与 pos 位次）
print("分词校验：")
for s in sentences[:24]:
    print(f"  {s} → {jieba.lcut(s)}")

out = Path(__file__).parent / "corpus_long.json"
out.write_text(json.dumps(sentences, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\ncorpus_long.json: {len(sentences)} 句（4 组 × 6 模板 × {RPT} 次）")
