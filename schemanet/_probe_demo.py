# -*- coding: utf-8 -*-
"""临时：LLM 教师边界案例演示（vs 规则验证器，用完即删）。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import json
import numpy as np
from _grow_v11 import (llm_judge, rule_verifier, attributed_sentence,
                       VO_PAIRS, DATA)
from snapshot import load_version
from _grow_cat import build_cats

ng, vocab, pats, cursor = load_version("11.1")
sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
cats25 = build_cats(pats, sem["words"], 12, 3)
cat_members = {}
for l in ["食物", "地点"]:
    d = cats25.get(l)
    cat_members[l] = set(d["train"]) | set(d["hold"]) if d else set()
from _grow_v11 import O_FOOD, O_PLACE
cat_members["食物"] |= set(O_FOOD)
cat_members["地点"] |= set(O_PLACE)
vo_pairs = {v: [o for o in ops if o in pats] for v, ops in VO_PAIRS.items()}
n2w = {j: w for w, ns in pats.items() for j in ns}

demo = [("我", "吃", "苹果"), ("我", "吃", "石头"),
        ("我", "看", "石头"), ("我", "喝", "学校"),
        ("我", "画", "石头"), ("我", "买", "学校")]
print("[教师演示] LLM 判断 vs 规则验证器（不改网络）")
for s, v, o in demo:
    ok_path, top, allow, _ = attributed_sentence(
        ng, pats, n2w, s, v, vo_pairs, cat_members)
    kind_r, _, allow_mem = rule_verifier(
        ng, pats, s, v, o, allow, cat_members, top)
    d = {"S": s, "V": v, "O": o, "kind": kind_r,
         "allow": sorted(allow), "top": top,
         "principles": {}, "allow_mem": sorted(allow_mem)[:8],
         "penalized": None}
    res = llm_judge(d)
    jg_l, r_l = res if res else ("回退", "（调用失败/越界拦截）")
    print(f"  {s}+{v}+{o} → 规则: {kind_r:5s} | LLM: {jg_l} — {r_l}")
