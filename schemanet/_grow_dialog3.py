# -*- coding: utf-8 -*-
"""自发对话训练（2026-08-10，"123"第 2 项）。

对话教学（v28.2）验收形态 = chain_read（教学验证）13/13；但自发
形态（free_read 问题词回应）仍弱（今天→下雨 256 漂移）。本脚本：
  每轮：free_read(问题词) 前 2 跳 ∈ 期望回应链 → 自发达标；
  不达标 → 强化跟读期望回应链 ×4（≤3 轮）→ 再验。
目标：自发对话达标率 ≥ 0.8（提示渐隐到自发的对话版）。

加载 v28.2 → 快照 v28.3。用法：python _grow_dialog3.py
"""

import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot

DATA = Path(__file__).parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).parent / "runs"
R_STRONG = 10        # v1 教训：256 顶格边需 28 轮反超——
                      # 10×6=60 次跟读才够
MAX_ROUND = 6

SCENES = {
    "① 吃饭": [
        ("你饿了吗？", "饿", ["我", "饿", "了", "就", "吃", "饭"], {"吃", "饭", "饿"}),
        ("那你想吃什么？", "想", ["我", "想", "吃", "饭"], {"吃", "饭"}),
        ("吃饱了做什么？", "饱", ["吃", "完", "饭", "就", "睡觉"], {"睡", "睡觉"}),
    ],
    "② 下雨": [
        ("外面下雨了怎么办？", "下雨", ["下雨", "了", "就", "带", "伞"], {"带", "伞"}),
        ("雨停了做什么？", "停", ["去", "公园", "玩"], {"去", "公园", "玩"}),
    ],
    "③ 天黑": [
        ("天黑了该做什么？", "黑", ["天", "黑", "了", "就", "睡觉"], {"睡", "睡觉"}),
        ("你累了吗？", "累", ["我", "累", "了", "就", "睡觉"], {"睡", "睡觉"}),
        ("明天早上呢？", "早上", ["早上", "起床"], {"起", "起床"}),
    ],
    "④ 疼": [
        ("你怎么了？", "疼", ["我", "疼"], {"疼", "帮"}),   # 我疼/帮帮我都合理
        ("需要帮忙吗？", "帮", ["帮", "帮", "我"], {"帮"}),
    ],
    "⑤ 学校": [
        ("你今天去学校吗？", "今天", ["今天", "去", "学校"], {"去", "学校"}),
        ("明天呢？", "明天", ["明天", "回", "家"], {"回", "家"}),
        ("昨天去哪了？", "昨天", ["昨天", "去", "公园"], {"去", "公园"}),
    ],
}


def main():
    from _exam_free import FUNC, free_read, build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool
    from _grow_cat import build_cats
    import json

    t0 = time.time()
    print("═══ 自发对话训练（自由读验收问题词自发回应）═══\n")
    ng, vocab, pats, cursor = load_version("28.2")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)

    n_turns = n_ok = n_boost = 0
    for scene, turns in SCENES.items():
        print(f"── {scene} ──")
        for t_i, (teacher, kw, expect, accept) in enumerate(turns, 1):
            n_turns += 1
            done = False
            for rnd in range(MAX_ROUND):
                read = free_read(ng, pats, n2w, [kw], domain,
                                 teach_out=teach_out)
                toks = [x.split("(")[0] for x in read]
                ok = any(x in accept for x in toks[:2])
                if ok:
                    n_ok += 1
                    print(f"  轮{t_i} 师：「{teacher}」")
                    print(f"     网（自发）：{'/'.join(toks[:6]) or '∅'} ✅"
                          f"{'（第 %d 轮强化后）' % rnd if rnd else ''}")
                    done = True
                    break
                for _ in range(R_STRONG):
                    _learn_sentence(ng, expect, pats, slot=0)
                n_boost += 1
            if not done:
                read = free_read(ng, pats, n2w, [kw], domain,
                                 teach_out=teach_out)
                toks = [x.split("(")[0] for x in read]
                print(f"  轮{t_i} 师：「{teacher}」")
                print(f"     网（自发）：{'/'.join(toks[:6]) or '∅'} ✗"
                      f"（{MAX_ROUND} 轮强化未达）")
        print()

    rate = n_ok / n_turns
    print(f"═══ 自发对话成绩 ═══")
    print(f"  自发回应率：{n_ok}/{n_turns} = {rate:.3f}"
          f"（强化 {n_boost} 处）")
    passed = rate >= 0.8
    print(f"  {'✅ 自发对话达标（≥0.8）' if passed else '✗ 未达标'}")

    save_snapshot(ng, parent="28.2",
                  tag="自发对话训练：13 轮自由读验收问题词自发回应"
                      "（强化跟读 ≤3 轮）",
                  metrics={"turns": n_turns, "ok": n_ok,
                           "boosts": n_boost, "rate": round(rate, 3)},
                  vocab=vocab, pats=pats, cursor=cursor)
    print(f"[完成] 快照已存（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
