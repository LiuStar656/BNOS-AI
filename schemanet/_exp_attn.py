# -*- coding: utf-8 -*-
"""多信号处理模式实验（2026-08-11）：

用户："要验证的是，网络是全部处理还是竞争处理还是串行处理"。

三种处理模式（同一场景三刺激并行）：
  A. 全部处理（并行注入）：build_pulse 同时注入三刺激词神经元 → step
     传播 → 看 WTA 发放结果（多个=全部处理；一个主导=动力学竞争）
  B. 竞争处理（salience）：assess 多维评估 → 加权分 argmax → 只处理
     最高优先的刺激
  C. 串行处理（回合制）：按 salience 排序 → 依次处理（回合制）

场景：
  ① 疼（身体-求助）+ 妈妈来了（听觉-回应）+ CLK_5（时间背景）
  ② 饿（需求）+ 猫（探索-新颖）+ 天气（低唤醒-背景）

用法：python _exp_attn.py（纯内存）
"""

import json
import time
from pathlib import Path

import numpy as np
from schema_net import build_pulse
from snapshot import load_version, load_consolidated
from _exam_free import free_read, build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats
from _grow_v16 import edge_between, direct_next_multi

DATA = Path(__file__).parent / "data" / "curriculum"

# 刺激场景：(名称, [刺激词], 说明)
SCENES = [
    ("身体+听觉+时间", ["疼", "妈妈", "CLK_5"],
     "疼（求助）vs 妈妈（回应）vs 时钟（背景）"),
    ("需求+探索+背景", ["饿", "猫", "天气"],
     "饿（需求）vs 猫（探索）vs 天气（背景）"),
]

NEG = {"疼", "饿", "累", "冷", "怕"}
HIGH = {"疼", "饿", "怕"}


def salience(ng, pats, n2w, kw, domain, validation):
    """多维评估 → 显著性加权分（效价×唤醒×认知×新颖）。"""
    v = sum(v0 - v1 for (qt, k2, toks), (v0, v1) in validation.items()
            if k2 == kw)
    top = direct_next_multi(ng, pats, n2w, [kw], k=2, domain=set(domain))
    w1 = top[0][1] if top else 0.0
    val = -1 if kw in NEG else (0.5 if kw == "猫" else 0)
    aro = 1 if kw in HIGH else (0 if kw == "天气" else 0.5)
    nov = 1 if v <= 0 and w1 < 20 else 0
    s = (abs(val) * 2 + aro) * (1 + min(w1, 50) / 50) + nov
    return round(s, 2), {"效价": val, "唤醒": aro, "边": w1, "验证": v}


def mode_A_parallel(ng, pats, n2w, stims):
    """全部处理：并行注入三刺激 → WTA 传播 → 观察发放。"""
    idxs = []
    for w in stims:
        if w in pats:
            idxs += pats[w]
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.step(build_pulse(ng.n, idxs), slot=0)
    out = []
    for _ in range(3):
        ng.spikes = np.zeros(ng.n)
        ng.step(np.zeros(ng.n), slot=0)
        fired = np.where(ng.spikes > 0)[0]
        words = [n2w.get(i, f"#{i}") for i in fired[:8]]
        out.append(words)
    return out


def mode_B_compete(ng, pats, n2w, stims, domain, validation):
    """竞争处理：salience argmax → 只处理最高。"""
    scores = {w: salience(ng, pats, n2w, w, domain, validation)
              for w in stims}
    winner = max(scores, key=lambda w: scores[w][0])
    return winner, scores


def mode_C_serial(ng, pats, n2w, stims, domain, validation, teach_out,
                  consolidated):
    """串行处理：按 salience 排序 → 依次走链。"""
    scores = {w: salience(ng, pats, n2w, w, domain, validation)
              for w in stims}
    order = sorted(scores, key=lambda w: -scores[w][0])
    res = []
    for kw in order:
        trace = []
        read = free_read(ng, pats, n2w, [kw], domain, teach_out=teach_out,
                         trace=trace, consolidated=consolidated)
        toks = []
        for w in [x.split("(")[0] for x in read]:
            if w.startswith("[") or w in toks:
                break
            toks.append(w)
        walked = any("整句" in str(t.get("cands", [])) for t in trace)
        if toks and kw not in toks and not walked:
            toks.insert(0, kw)
        res.append((kw, "/".join(toks) or "（沉默）"))
    return res


def main():
    t0 = time.time()
    print("═══ 多信号处理模式实验（并行 vs 竞争 vs 串行）═══\n")
    print("（纯内存——不保存快照）\n")
    ng, vocab, pats, cursor = load_version("34.0")
    consolidated, validation = load_consolidated("34.0")
    ng.w_max = 64.0
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)

    for name, stims, desc in SCENES:
        print(f"── 场景：{name}（{desc}）──")
        # A. 全部处理（并行注入 → WTA）
        waves = mode_A_parallel(ng, pats, n2w, stims)
        print(f"  A 并行注入 WTA 发放：")
        for i, ws in enumerate(waves):
            print(f"    步{i+1}: {ws}")
        # B. 竞争处理（salience argmax）
        winner, scores = mode_B_compete(ng, pats, n2w, stims, domain,
                                        validation)
        print(f"  B salience 竞争：")
        for w in stims:
            print(f"    {w}: salience={scores[w][0]}（{scores[w][1]}）")
        print(f"    → 胜者：{winner}（只处理它）")
        # C. 串行处理（回合）
        order = mode_C_serial(ng, pats, n2w, stims, domain, validation,
                              teach_out, consolidated)
        print(f"  C 串行回合（按 salience 排序）：")
        for kw, said in order:
            print(f"    「{kw}」→ 说「{said}」")
        print()

    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
