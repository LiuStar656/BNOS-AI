# -*- coding: utf-8 -*-
"""时钟并行教师（2026-08-11 用户定稿："内在时钟和教师刺激是并行的，
内在时钟在自己走，老师刺激是额外的，就像人什么都没干但是时间也在
流逝"）。

背景（用户指出）：超临界报告暴露网络是"注入→有限步回响→停"的离散
模式（回响步 1/3/5 后 v 越积越高卡住）——没有底层时间流。内在时钟 =
让网络"永动"：每时刻时间都在流逝（人什么都没干时间也在走），教师
刺激是叠加其上的额外输入（并行，不是驱动）。

架构：
  for t in 时间轴（连续流逝）:
    ① 时钟推进：phase = t mod 16——底层永动（网络"活着"的时长）
    ② 空闲时段（无教师）：网络静息运行——时钟激活 + 念头冒出
       （时钟唤起/联想——自己想起事情）
    ③ 教师时刻（课表，并行叠加）：教师说/引导 → 网络表达 → 评估
       （一致性×自然度）→ 鼓励奖励/示范/处罚注入
  日志 = 时间线：每一时刻都有"网络的状态"（空闲也在流逝——不卡住）

用法：python _grow_live8.py [--smoke]
"""

import random
import sys
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version
from _grow_v11 import _load_key, _llm_chat

DATA = Path(__file__).parent / "data" / "curriculum"
TOTAL = 32                      # 时间轴总长（2 天 × 16 相位）
PHASE_MEM = {range(2, 6): "早上", range(6, 10): "中午",
             range(10, 14): "晚上"}

# 教师课表（并行叠加在时钟上的额外刺激——备课内容）
LESSONS = {
    5: ("饿的感受", "你饿不饿呀？", "饿",
        ["饿", "了", "就", "吃", "饭"]),
    12: ("早上起床流程", "早上起床要做什么呀？", "早上",
         ["早上", "起床", "洗", "手", "刷牙", "吃", "饭"]),
    20: ("下雨怎么办", "下雨了要做什么呀？", "下雨",
         ["下雨", "了", "就", "带", "伞"]),
    26: ("危险物品", "火能摸吗？", "火",
         ["不", "能", "摸", "火"]),
}


def main():
    from _exam_free import FUNC, free_read, build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool
    from _grow_cat import build_cats
    from _grow_teacher import teacher_once, penalize_drift
    import json

    random.seed(11)
    smoke = "--smoke" in sys.argv
    has_llm = bool(_load_key())
    t0 = time.time()
    print("═══ 时钟并行教师（底层时间永动 + 教师叠加）═══\n")
    print(f"时间轴 {TOTAL} 时刻；教师课表 {sorted(LESSONS)}（并行叠加）\n")

    ng, vocab, pats, cursor = load_version("32.0")
    ng.w_max = 64.0
    n2w = {j: w for w, ns in pats.items() for j in ns}
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)

    phase = 0
    last_tail = None
    n_idle = n_teach = n_thought = 0
    for t in range(TOTAL):
        phase = (phase + 1) % 16
        mem_word = next((w for r, w in PHASE_MEM.items() if phase in r),
                        None)
        # ① 时钟推进（底层永动——时间流逝，什么都不干也在走）
        if t in LESSONS and not smoke or (smoke and t in (5, 20)):
            # ③ 教师时刻（并行叠加的额外刺激）
            name, guide, kw, expect = LESSONS[t]
            n_teach += 1
            trace = []
            read = free_read(ng, pats, n2w, [kw], domain,
                             teach_out=teach_out, trace=trace)
            toks = []
            for w in [x.split("(")[0] for x in read]:
                if w.startswith("[") or w in toks:
                    break
                toks.append(w)
            said = "/".join([kw] + toks) if toks else "（说不出话）"
            got = teacher_once((name, guide, kw, expect, "课"),
                               trace, toks) if has_llm else None
            if got is None:
                cons = sum(1 for tr in trace
                           if tr["chosen"] in [c for c, _ in tr["cands"]]
                           ) / max(len(trace), 1) * 10
                nat = 7.0 if any(w in expect for w in toks) else 2.0
                got = {"cons": cons, "nat": nat, "fb": "", "demo": ""}
            score = got["cons"] * got["nat"]
            print(f"[t={t:2d} 相位{phase:2d}] ★教师：「{guide}」"
                  f"（{name}——叠加刺激）")
            print(f"       网络内心冒出："
                  f"{' → '.join('「%s」%s' % (tr['state'], tr['cands'][:2])
                               for tr in trace[:3]) or '（无）'}")
            print(f"       网络说：「{said}」"
                  f" 评分 {got['cons']:.0f}×{got['nat']:.0f}"
                  f"={score:.0f}")
            if score >= 80:
                for _ in range(3):
                    _learn_sentence(ng, expect, pats, slot=0)
                print(f"       教师：「{got['fb']}」（奖励固化 ×3）")
            elif score >= 40:
                for _ in range(2):
                    _learn_sentence(ng, expect, pats, slot=0)
                print(f"       教师：「{got['fb']}」（示范跟读 ×2）")
            else:
                n_dec = penalize_drift(ng, pats, toks, expect)
                for _ in range(2):
                    _learn_sentence(ng, expect, pats, slot=0)
                print(f"       教师：「{got['fb']}」")
                print(f"       [处罚] 漂移边降权 ×0.5（{n_dec} 条）"
                      f"＋ [注入] 跟读 ×2")
        else:
            # ② 空闲时段：时间流逝——网络静息运行（念头自己冒出）
            n_idle += 1
            if random.randint(1, 4) == 1:
                seed_w = last_tail if (last_tail and random.random() < .5) \
                    else mem_word
                if seed_w:
                    trace = []
                    read = free_read(ng, pats, n2w, [seed_w], domain,
                                     teach_out=teach_out, trace=trace)
                    toks = []
                    for w in [x.split("(")[0] for x in read]:
                        if w.startswith("[") or w in toks:
                            break
                        toks.append(w)
                    if toks:
                        last_tail = toks[-1]
                        n_thought += 1
                        print(f"[t={t:2d} 相位{phase:2d}] （空闲——时间"
                              f"流逝）冒出念头「{seed_w}/{'/'.join(toks)}」"
                              f"（{'时钟唤起' if seed_w == mem_word else '联想'}）")

    print(f"\n═══ 时间线统计 ═══")
    print(f"  总时刻 {TOTAL}：空闲 {n_idle}（时间持续流逝——不卡住）"
          f" · 念头 {n_thought} · 教师介入 {n_teach}")
    print(f"  架构：时钟底层永动（每时刻都在走——人没事干时间也在"
          f"流逝）＋ 教师并行叠加（课表时刻额外刺激）")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
