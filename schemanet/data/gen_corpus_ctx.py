# -*- coding: utf-8 -*-
"""生成 corpus_ctx.json：二阶依赖语料（上下文词能破平局）。

设计：每组模板中，中间词（mid）的后继在两组候选中平局（各 1:1），
而上下文词（ctx）通过"直接相邻"句子把某一候选锚定：
    ctx1 mid tgtA / ctx1 mid tgtB / ctx2 mid tgtA / ctx2 mid tgtB  → mid 后继平局
    ctx1 tgtA / ctx2 tgtB                                          → ctx→候选 直接转移
前缀 [ctx, mid]：末词 mid 后继平局 → 靠 ctx 的痕迹指向 tgtA/tgtB 破局。

梯度读出应学到 ctx_wgt[pos=ctx] > 0（用远端破局），超越纯末词 wsum。
"""
import json
from pathlib import Path

GROUPS = [
    # (ctx1, ctx2, mid, tgtA, tgtB)
    ("早上", "晚上", "吃饭", "香", "饱"),
    ("数学", "语文", "考试", "难", "简单"),
    ("夏天", "冬天", "天气", "热", "冷"),
    ("昨天", "今天", "上班", "累", "忙"),
]

RPT = 12  # 每组循环次数

sentences = []
for ctx1, ctx2, mid, tgtA, tgtB in GROUPS:
    for _ in range(RPT):
        sentences += [
            f"{ctx1}{mid}{tgtA}",
            f"{ctx1}{mid}{tgtB}",
            f"{ctx2}{mid}{tgtA}",
            f"{ctx2}{mid}{tgtB}",
            f"{ctx1}{tgtA}",
            f"{ctx2}{tgtB}",
        ]

# 保留重复：Hebbian 靠重复形成定式（RPT 控制每组句子的出现次数）
out = Path(__file__).parent / "corpus_ctx.json"
out.write_text(json.dumps(sentences, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"corpus_ctx.json: {len(sentences)} 句")
print("样例:", sentences[:8])
