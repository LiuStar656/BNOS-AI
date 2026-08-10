# -*- coding: utf-8 -*-
"""真实多轮对话 v2（2026-08-10，v1 2/13 暴露根因后重做）。

v1 教训：自由读(问题词) 走问题词的最强教学链，但 ≠ 问题相关回应
（今天→下雨 256 压过 今天→去 64；下雨→所以→猫睡觉 漂移）——
网络"会说话但不会对话"：回应不受问题语义约束。

v2 对话教学（铁律 6"对话即学习"落地）：
  每轮 = 教学单元：教师问句（问题词）→ 期望回应链
    ① 引发边教学：问题词→回应首内容词（饿→我："你饿了吗"→"我饿了"）
    ② 回应链教学：跟读期望回应（[我,饿,了,就,吃,饭]）
  验收双轨：chain_read（教学验证形态）+ free_read（自发形态）抽查
加载 v27.1 → 快照 v28.1。

用法：python _grow_dialog2.py
"""

import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot

DATA = Path(__file__).parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).parent / "runs"
R_EDGE = 4
R_CHAIN = 4

# 场景轮次：[(教师问句, 问题词, 期望回应链)]
SCENES = {
    "① 吃饭": [
        ("你饿了吗？", "饿", ["我", "饿", "了", "就", "吃", "饭"]),
        ("那你想吃什么？", "想", ["我", "想", "吃", "饭"]),
        ("吃饱了做什么？", "饱", ["吃", "完", "饭", "就", "睡觉"]),
    ],
    "② 下雨": [
        ("外面下雨了怎么办？", "下雨", ["下雨", "了", "就", "带", "伞"]),
        ("雨停了做什么？", "停", ["去", "公园", "玩"]),
    ],
    "③ 天黑": [
        ("天黑了该做什么？", "黑", ["天", "黑", "了", "就", "睡觉"]),
        ("你累了吗？", "累", ["我", "累", "了", "就", "睡觉"]),
        ("明天早上呢？", "早上", ["早上", "起床"]),
    ],
    "④ 疼": [
        ("你怎么了？", "疼", ["我", "疼"]),
        ("需要帮忙吗？", "帮", ["帮", "帮", "我"]),
    ],
    "⑤ 学校": [
        ("你今天去学校吗？", "今天", ["今天", "去", "学校"]),
        ("明天呢？", "明天", ["明天", "回", "家"]),
        ("昨天去哪了？", "昨天", ["昨天", "去", "公园"]),
    ],
}


def main():
    from _grow_v16 import edge_between
    from _exam_free import FUNC, free_read, build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool
    from _grow_cat import build_cats
    from _exam_big import chain_read
    import json

    t0 = time.time()
    print("═══ 真实多轮对话 v2（每轮 = 教学单元）═══\n")
    ng, vocab, pats, cursor = load_version("27.1")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)

    # ── 对话教学：每轮引发边 + 回应链 ────────────────
    n_turns = n_ok = 0
    for scene, turns in SCENES.items():
        print(f"── {scene} ──")
        for t_i, (teacher, kw, expect) in enumerate(turns, 1):
            n_turns += 1
            # 引发边：问题词→回应链首词（chain_read 检查 front[-1]→
            # back[0]——无论桥词与否，直接教 expect[0]；v2 教训：
            # FUNC 跳词导致教了 停→公园 而 chain_read 要 停→去）
            first = expect[0]
            for _ in range(R_EDGE):
                _learn_sentence(ng, [kw, first], pats, slot=0)
            for _ in range(R_CHAIN):
                _learn_sentence(ng, expect, pats, slot=0)
            # 验收：教学链约束读（期望链约束 = 教学验证形态）
            read, brk = chain_read(ng, pats, n2w, [kw], expect)
            ok = read == expect
            n_ok += ok
            # 自发抽查（自由读第一跳）
            free = free_read(ng, pats, n2w, [kw], domain,
                             teach_out=teach_out)
            f_toks = [x.split("(")[0] for x in free]
            f_ok = any(x in expect for x in f_toks[:2])
            print(f"  轮{t_i} 师：「{teacher}」")
            print(f"     网（教学读）：{'/'.join(read) or '∅'}"
                  f"{' ✅' if ok else ' ✗'}"
                  f"{'  [断:' + '→'.join(map(str, brk)) + ']' if brk else ''}")
            print(f"     网（自发）：{'/'.join(f_toks[:5]) or '∅'}"
                  f"{' ✅' if f_ok else ''}")
        print()

    rate = n_ok / n_turns
    print(f"═══ 对话成绩（教学验证形态）═══")
    print(f"  轮次通过率：{n_ok}/{n_turns} = {rate:.3f}")
    passed = rate >= 0.8
    print(f"  {'✅ 对话能力达标（≥0.8）' if passed else '✗ 未达标'}")

    save_snapshot(ng, parent="27.1",
                  tag="真实多轮对话 v2：5 场景 14 轮教学单元（问题词→"
                      "回应链引发教学 + 双轨验收）",
                  metrics={"turns": n_turns, "ok": n_ok,
                           "rate": round(rate, 3)},
                  vocab=vocab, pats=pats, cursor=cursor)
    print(f"[完成] 快照已存（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
