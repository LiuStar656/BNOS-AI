# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""沉默自发表达实验（2026-08-11）：网络沉默时会不会自己想说话？

用户："定式网络现在能不能沉默的时候自己想说话？"

三个能力（分别在已有实验单独验证过）：
  A 想（念头流）——_grow_live6 静默运行：内在时钟+相位记忆+联想流+噪声
  B 说（开口）——_scene_recall 自发回忆：空闲+有内容→说出来
  C 想→说（表达意图）——念头携带"值得说"的信号→外化——本实验测 C

本实验在 v36.0 上**完全静默**运行：无外部输入、无 LLM、无场景事件。
  念头 = free_read(相位唤起/联想尾词) 从网络结构读出（边链——网络自己想的）
  表达意图 = 念头命中动机词（网络词表内，非代码模板）：
    疑问（怎么办/为什么/吗）→ 提问动机
    需求（饿/疼/困/渴/冷）→ 求助动机
    社交（妈）→ 分享动机
    皆无 → 只"想"不"说"（内心独白——人沉默时也不全说出来）

用法：python _exp_spontaneous.py [--seed N]（纯内存——不保存快照）
"""

import random
import sys
import time
from pathlib import Path

from snapshot import load_version

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
N_DAYS = 3
PHASES = 16
SEED = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 42

# 相位-记忆绑定（时序 v1 教学建边——网络已学过，映射只是触发种子）
PHASE_MEM = {range(2, 6): "早上", range(6, 10): "中午",
             range(10, 14): "晚上"}
# 表达意图动机词（网络词表内）
MOTIVE = {
    "疑问": ["怎", "么", "办", "为", "什", "么", "吗"],
    "需求": ["饿", "疼", "困", "渴", "冷"],
    "社交": ["妈"],
}


def motive_of(toks):
    """念头链 → 表达意图（优先级：疑问 > 需求 > 社交）。"""
    for name, ws in [("疑问", MOTIVE["疑问"]), ("需求", MOTIVE["需求"]),
                     ("社交", MOTIVE["社交"])]:
        if any(w in ws for w in toks):
            return name
    return None


def main():
    from _exam_free import FUNC, free_read, build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool
    from _grow_cat import build_cats
    import json

    random.seed(SEED)
    t0 = time.time()
    print(f"═══ 沉默自发表达实验（v36.0，{N_DAYS} 天静默，seed={SEED}）═══\n")
    print("（无外部输入/无 LLM/无场景事件——只有内在时钟+相位记忆+联想+噪声）\n")

    ng, vocab, pats, cursor = load_version("36.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)

    phase = 0
    thoughts = []        # 想的（含动机判定）
    spoken = []          # 说的（有意图才外化）
    last_tail = None
    for day in range(1, N_DAYS + 1):
        for step in range(PHASES):
            phase = (phase + 1) % PHASES
            # 念头触发时机：自发噪声（随机间隔——静默期+冒出期交替）
            if random.randint(1, 4) != 1:
                continue
            # 激活中心：50% 时钟唤起（相位记忆），50% 联想流（念头尾词）
            mem_word = next((w for r, w in PHASE_MEM.items()
                             if phase in r), None)
            if last_tail is not None and random.random() < 0.5:
                seed_w = last_tail
                src = f"联想（念头「{last_tail}」）"
            else:
                seed_w = mem_word
                src = f"时钟唤起（相位{phase}→「{mem_word}」）"
            if seed_w is None or seed_w not in pats:
                continue
            trace = []
            read = free_read(ng, pats, n2w, [seed_w], domain,
                             teach_out=teach_out, trace=trace)
            toks = []
            for w in [x.split("(")[0] for x in read]:
                if w.startswith("[") or w in toks:
                    break
                toks.append(w)
            if not toks:
                continue
            thought = "/".join(toks)
            motive = motive_of(toks)
            item = {"day": day, "phase": phase, "thought": thought,
                    "src": src, "motive": motive}
            thoughts.append(item)
            # 表达意图 → 开口（想的内容外化——4.11 私语外化）
            if motive:
                spoken.append(item)
                tag = {"疑问": "想问", "需求": "想求助", "社交": "想分享"}[motive]
                print(f"  [第{day}天 相位{phase:2d}] 开口「{thought}」"
                      f"（{src}——{tag}）")
            else:
                print(f"  [第{day}天 相位{phase:2d}] 内心「{thought}」"
                      f"（{src}——独白，没说）")
            last_tail = toks[-1]

    # ── 分析 ─────────────────────────────────────────
    n = len(thoughts)
    n_sp = len(spoken)
    print(f"\n═══ 分析 ═══")
    print(f"  静默 {N_DAYS} 天 × 16 相位 = {N_DAYS*16} 步")
    print(f"  冒出念头：{n} 个（想）| 开口说话：{n_sp} 个（说）")
    if n:
        from collections import Counter
        m = Counter(x["motive"] for x in thoughts)
        print(f"  动机分布：{dict(m)}")
        print(f"  开口率：{n_sp/n:.0%}（其余为内心独白——"
              f"人沉默时也不会把每个念头都说出来）")
    uniq = len({x["thought"] for x in thoughts})
    print(f"  念头多样性：{uniq} 种不同内容（{n} 个中——网络结构决定）")
    print(f"\n[结论] 沉默时网络{'能' if n_sp else '不能'}自己开口说话"
          f"——内容全部来自网络自身记忆结构（教学链/相位绑定），"
          f"触发时机是内部动力学（时钟+噪声），动机判定是念头语义")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
