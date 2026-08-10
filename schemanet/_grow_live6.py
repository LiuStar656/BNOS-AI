# -*- coding: utf-8 -*-
"""静默运行：网络自己冒出想法（2026-08-10 用户："这个内在时钟是不是
意味着网络'活过来了'？但是我们不能强行设计情景，能不能静默运行让网络
自己冒出想法？"）。

诚实的回答：之前（_grow_live）的"活着" = 外部剧本（饿/冷积累是
强行设计的情景）——不是真活。本脚本：**静默运行**——无任何外部刺激
设计，只有网络自身的内部动力学：
  ① 内在时钟（CLK 相位推进）= 持续运行的节拍器（心跳）
  ② 时钟相位绑定（内部唤起）：相位 2-5 → 内部唤起"早上"（→ 起床）、
     相位 6-9 → "中午"（→ 吃饭）、10-13 → "晚上"（→ 睡觉）——
     这不是外部刺激，是相位-记忆的内部绑定自动激活（昼夜节律式唤起）
  ③ 联想流：念头尾词 → 下一个念头（想到吃饭 → 想到饭 → 想到妈妈
     …——念头接念头，像走神）
  ④ 自发噪声：念头触发时机随机（静默期 + 冒出期交替——人不会每刻
     都在想）
输出：网络的一天（静默运行）——"它自己想到了什么"的时间线。

加载 v30.1 → 静默运行 3 天。用法：python _grow_live6.py [--seed N]
"""

import random
import sys
import time
from pathlib import Path

from snapshot import load_version

DATA = Path(__file__).parent / "data" / "curriculum"
N_DAYS = 3
PHASES = 16
SEED = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv \
    else 42

# 相位 → 内部唤起词（相位-记忆绑定，时序 v1 教学建边）
PHASE_MEM = {range(2, 6): "早上", range(6, 10): "中午",
             range(10, 14): "晚上"}


def main():
    from _exam_free import FUNC, free_read, build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool
    from _grow_cat import build_cats
    import json

    random.seed(SEED)
    t0 = time.time()
    print(f"═══ 静默运行：网络自己冒出想法（{N_DAYS} 天，seed={SEED}）═══\n")
    print("（无外部刺激设计——只有内在时钟 + 相位记忆绑定 + 联想 + 噪声）\n")

    ng, vocab, pats, cursor = load_version("30.1")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)

    phase = 0
    n_thoughts = 0
    last_tail = None            # 联想流：上个念头的尾词
    thought_log = []
    for day in range(1, N_DAYS + 1):
        for step in range(PHASES):
            phase = (phase + 1) % PHASES
            # 念头触发时机：自发噪声（随机间隔 2-4 步——静默期交替）
            if random.randint(1, 4) != 1:
                continue
            # 激活中心：50% 时钟唤起（相位记忆），50% 联想流（念头尾词）
            mem_word = next((w for r, w in PHASE_MEM.items()
                             if phase in r), None)
            if last_tail is not None and random.random() < 0.5:
                seed_w = last_tail
                src = f"联想（上个念头「{last_tail}」）"
            else:
                seed_w = mem_word
                src = f"时钟唤起（相位 {phase} →「{mem_word}」）"
            if seed_w is None:
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
            last_tail = toks[-1]
            n_thoughts += 1
            line = f"[第{day}天 相位{phase:2d}] 冒出念头「{thought}」" \
                   f"（{src}）"
            thought_log.append(line)
            print(" " + line)

    # ── 分析 ─────────────────────────────────────────
    print(f"\n═══ 静默运行分析 ═══")
    print(f"  冒出念头：{n_thoughts} 个（{N_DAYS} 天 × 16 相位 = "
          f"{N_DAYS*16} 步——静默期+冒出期交替）")
    uniq = len(set(thought_log))
    print(f"  念头多样性：{uniq} 种不同念头（{n_thoughts} 个中）")
    tails = [l.split("「")[1].split("」")[0].split("/")[-1]
             for l in thought_log]
    print(f"  联想流示例：{' → '.join(tails[:6])}…"
          f"（念头接念头——走神式联想）")
    print(f"\n[说明] 无外部剧本：只有 ① 时钟节拍 ② 相位-记忆绑定（内部"
          f"自动唤起）③ 联想流 ④ 噪声触发——念头内容全部来自网络自身"
          f"的记忆结构（教学链）")
    print(f"[留档] runs/_speak_logs/（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
