# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""临时诊断：v11 合理搭配 125/170 vs v10 170/170 回归原因。
加载 v10.0，不处罚，跑 attributed_sentence 400 测试组合，打印失败明细。"""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from snapshot import load_version
from _grow_cat import build_cats
from _grow_v11 import (attributed_sentence, rule_verifier, SEED,
                       PERS_MANUAL, S_ANIMALS, V_SET, O_FOOD, O_PLACE,
                       VO_PAIRS, SLOT_S, SLOT_V, SLOT_O, N_TRAIN, N_TEST)

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
ng, vocab, pats, cursor = load_version("10.0")
s_words = sorted({w for w in PERS_MANUAL + S_ANIMALS if w in pats})
v_words = sorted({w for w in V_SET if w in pats})
o_words = sorted({w for w in O_FOOD + O_PLACE if w in pats})
vo_pairs = {v: [o for o in ops if o in pats]
            for v, ops in VO_PAIRS.items() if v in v_words}
sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
cats25 = build_cats(pats, sem["words"], 12, 3)
cat_members = {}
for l in ["食物", "地点"]:
    d = cats25.get(l)
    cat_members[l] = set(d["train"]) | set(d["hold"]) if d else set()
cat_members["食物"] |= set(O_FOOD)
cat_members["地点"] |= set(O_PLACE)
noun_pool = cat_members["食物"] | cat_members["地点"]

all_combos = [(s, v, o) for s in s_words for v in v_words for o in o_words]
rng = np.random.default_rng(SEED)
perm = rng.permutation(len(all_combos))
test_combos = [all_combos[i] for i in perm[N_TRAIN:N_TRAIN + N_TEST]]
n2w = {j: w for w, ns in pats.items() for j in ns}

n_ok = n_bad = n_plain = 0
n_ok_pass = n_bad_pass = n_plain_pass = 0
fail_ok = []
penalty_log = []
for s, v, o in test_combos:
    ok_path, top, allow, sources = attributed_sentence(
        ng, pats, n2w, s, v, vo_pairs, cat_members)
    kind, principles, allow_mem = rule_verifier(
        ng, pats, s, v, o, allow, cat_members, top)
    # 模拟 v11 处罚循环
    if kind != "plain":
        bad_in_top = [w for w in top if w not in allow_mem and w in noun_pool]
    else:
        bad_in_top = [w for w in top if w not in noun_pool]
    for bw in bad_in_top:
        srcs = sources.get(bw)
        if not srcs:
            continue
        for src_type, src_w, j, wt in srcs:
            removed = []
            dst_n = set(pats[bw])
            for i in pats.get(src_w, []):
                row = ng.W_out[i][0]
                for jj in list(row):
                    if jj in dst_n:
                        removed.append((i, jj, row[jj]))
                        del row[jj]
                        ng.invalidate_edge_cache()
            if removed:
                penalty_log.append({"src_word": src_w, "dst_word": bw,
                                    "src_type": src_type, "removed": removed})
    if kind == "ok":
        n_ok += 1
        ratio = sum(1 for w in top if w in allow_mem) / max(1, len(top))
        if ok_path and ratio >= 0.5:
            n_ok_pass += 1
        else:
            fail_ok.append((s, v, o, round(ratio, 2), ok_path, top[:8],
                            sorted(allow_mem)))
    elif kind == "bad":
        n_bad += 1
        rejected = o not in top
        n_bad_pass += ok_path and rejected
    else:
        n_plain += 1
        ratio = sum(1 for w in top if w in noun_pool) / max(1, len(top))
        n_plain_pass += ok_path and ratio >= 0.5

print(f"含处罚复跑：ok {n_ok_pass}/{n_ok}，bad {n_bad_pass}/{n_bad}，"
      f"plain {n_plain_pass}/{n_plain}")
print(f"处罚记录 {len(penalty_log)} 次：")
for e in penalty_log:
    print(f"  {e['src_word']}→{e['dst_word']}（{e['src_type']}）"
          f"删 {len(e['removed'])} 边")
print(f"失败 ok 组合 {len(fail_ok)}：")
for s, v, o, ratio, path, top, am in fail_ok[:25]:
    print(f"  {s}+{v}+{o} ratio={ratio} 路径={path} allow={am}")
    print(f"    top={top}")
