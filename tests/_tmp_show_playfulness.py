# -*- coding: utf-8 -*-
"""提取活泼实验两组实际输出文本，并排对比（人工文本判断，不依赖关键词打分）。"""
import json

p = r"E:\杂项\BNOS_AI_project\docs\experiments\cognitive_evolution_test\runs\20260812_163410_noinst_playfulness\probe_samples.jsonl"
rows = [json.loads(l) for l in open(p, encoding="utf-8")]
by = {}
for r in rows:
    by.setdefault(r["group"], {}).setdefault(r["input"], []).append(r)


def body(raw):
    start = raw.find("【自然回复】")
    if start == -1:
        return raw[:300]
    seg = raw[start + len("【自然回复】"):]
    end = seg.find("【")
    return seg[:end if end != -1 else 400].strip()


for i in range(8):
    low, high = by["PL_low"][i][0], by["PL_high"][i][0]
    print(f"===== 输入{i}: {low['text']} =====")
    print(f"活泼0.1: {body(low['raw'])}")
    print(f"活泼0.9: {body(high['raw'])}")
    print()
