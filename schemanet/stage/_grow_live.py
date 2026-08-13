# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""网络自由运行（"活着"模式，2026-08-10 用户构想："通过时序（持续
运行、持续刺激，就像活着一样）对网络缓慢刺激，让网络主动开口说话"）。

设计（内感受驱动的自发语言）：
  持续运行载体 = 内在时钟（16 相位 CLK 循环节拍，时序 v1 已有）
  每步（= 一个相位）：
    ① 时钟推进（网络持续运行——"活着"）
    ② 内感受刺激积累：饿/渴/累/冷 每步 +rate（饥饿感缓慢积累）
    ③ 时间事件：早上相位区间 → 注入"早上"（该做什么？）；中午 →
       "中午"；晚上 → "晚上"（外部刺激流）
    ④ 阈值开口：积累 ≥ 阈值 → **自发表达**（free_read 状态词——
       没人问，自己说）——表达后刺激清零（满足感：吃了就不饿）
    ⑤ 时间事件注入同理：时刻到了 → 自发说该做的事（起床/吃饭/睡觉）
  输出"网络的一天"生命日志 + 验收（自发表达次数/内容质量/节律性）。

加载 v29.2 → 自由运行 3 天（48 相位步/天）。用法：python _grow_live.py
"""

import time
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
N_DAYS = 3
PHASES_PER_DAY = 16

# 内感受刺激源：积累速率 / 触发阈值 / 满足后清零
STIMULI = {
    "饿": {"accum": 0, "rate": 1, "thr": 6},
    "渴": {"accum": 0, "rate": 1, "thr": 8},
    "累": {"accum": 0, "rate": 1, "thr": 12},
    "冷": {"accum": 0, "rate": 1, "thr": 14},
}

# 时间事件（外部刺激流）：相位区间 → (时间词, 期望表达内容词)
# 一天 16 相位：早上 2-5、中午 6-9、晚上 10-13、深夜 14-1
TIME_EVENTS = [
    (range(2, 6), "早上", {"起", "起床"}),
    (range(6, 10), "中午", {"吃", "饭"}),
    (range(10, 14), "晚上", {"睡", "睡觉"}),
]


def main():
    from _exam_free import FUNC, free_read, build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool
    from _grow_cat import build_cats
    from snapshot import load_version
    import json

    t0 = time.time()
    print("═══ 网络自由运行（持续刺激 → 自发开口，" + f"{N_DAYS} 天）═══\n")
    ng, vocab, pats, cursor = load_version("29.2")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)

    n_spont = n_ok = 0
    log = []
    phase = 0
    for day in range(1, N_DAYS + 1):
        for step in range(PHASES_PER_DAY):
            phase = (phase + 1) % PHASES_PER_DAY
            # ① 时钟推进（网络持续运行）
            # ② 内感受积累
            for st, s in STIMULI.items():
                s["accum"] += s["rate"]
            # ③ 时间事件（时刻到了 → 自发说该做的事）
            for prange, t_word, accept in TIME_EVENTS:
                if phase in prange:
                    read = free_read(ng, pats, n2w, [t_word], domain,
                                     teach_out=teach_out)
                    toks = [x.split("(")[0] for x in read]
                    hit = any(x in accept for x in toks[:2])
                    if hit:
                        n_spont += 1
                        n_ok += 1
                        expr = "".join(toks[:6])
                        log.append(f"[第{day}天 相位{phase:2d} {t_word}]"
                                   f" 时刻到了 → 自发：「{expr}」 ✅")
                    break
            # ④ 内感受满 → 自发表达（没人问，自己说）
            for st, stim in STIMULI.items():
                if stim["accum"] >= stim["thr"]:
                    read = free_read(ng, pats, n2w, [st], domain,
                                     teach_out=teach_out)
                    toks = [x.split("(")[0] for x in read]
                    hit = any(x in ({"吃", "饭"} if st == "饿" else
                                    {"喝", "水"} if st == "渴" else
                                    {"睡", "睡觉"} if st == "累" else
                                    {"穿", "衣服"}) for x in toks[:2])
                    n_spont += 1
                    n_ok += hit
                    expr = "/".join(toks[:6]) or "（说不出）"
                    log.append(f"[第{day}天 相位{phase:2d} {st}积累"
                               f"{stim['accum']}/{stim['thr']}] 自发："
                               f"「{expr}」{' ✅' if hit else ' ✗'}"
                               f"（满足 → {st}清零）")
                    stim["accum"] = 0       # ⑤ 满足消退

    # ── 生命日志 ─────────────────────────────────────
    print("═══ 网络的一天（生命日志摘录）═══")
    for line in log[:18]:
        print(" " + line)
    if len(log) > 18:
        print(f"  …（共 {len(log)} 条自发表达）")

    print(f"\n═══ 自由运行验收 ═══")
    print(f"  自发开口次数：{n_spont}（{N_DAYS} 天 × 16 相位 = "
          f"{N_DAYS*16} 步）")
    print(f"  自发表达质量：{n_ok}/{n_spont} = {n_ok/n_spont:.3f}"
          f"（表达 ∈ 教学链期望）")
    print(f"  节律性：饿的刺激周期 = {STIMULI['饿']['thr']} 步"
          f"（积累→开口→清零→再积累 = 生理节律闭环）")

    # 留档
    out = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_live"
    out.mkdir(parents=True, exist_ok=True)
    (out / "life_log.txt").write_text("\n".join(log), encoding="utf-8")
    print(f"\n[留档] {out}/life_log.txt（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
