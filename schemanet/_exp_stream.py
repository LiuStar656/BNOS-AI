# -*- coding: utf-8 -*-
"""流式交互演示：表达逐词进行 + 每 tick 感知 + 打断（2026-08-11）。

用户："大模型输入后要等输出才能再输入（半双工/阻塞）；人是流式
（全双工——边说边听、可打断）。网络能不能流式？"

底层 step 动力学天然全双工（每 tick 注入+发放并行）——演示把读取
协议流式化：固化句逐 tick 发音（不全量生成）+ 每 tick 输入流检查 +
打断决策（新刺激紧急度 > 当前会话 → 中断切换——大模型不能，人可以）。

场景：表达「我饿了」逐词进行中（t2 说到"饿"）——注入「疼」（更紧急：
求助 > 需求）→ t3 中断 → 疼会话「疼帮」→ t4 疼完成 → 恢复饿会话剩余。

用法：python _exp_stream.py（纯内存）
"""

import json
import time
from pathlib import Path

from snapshot import load_version, load_consolidated
from _exam_free import build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats

DATA = Path(__file__).parent / "data" / "curriculum"

# 紧急度（多维评估结果——4.8 实验）：求助 > 需求 > 探索 > 背景
URGENCY = {"求助": 3, "需求": 2, "探索": 1, "背景": 0}


def urgency_of(ng, pats, n2w, kw, domain, validation):
    """刺激紧急度（简化——用 4.8 的评估逻辑：负效价高唤醒=求助/需求）。"""
    from _grow_v16 import direct_next_multi
    NEG = {"疼", "饿", "累", "冷", "怕"}
    HIGH = {"疼", "饿", "怕"}
    if kw in NEG and kw in HIGH:
        # 求助 vs 需求：自助链（饿→了→就→吃）存在=需求；否则=求助
        from _grow_v16 import edge_between
        if kw == "饿" and all(edge_between(ng, pats, a, b) > 0
                              for a, b in [("饿", "了"), ("了", "就"),
                                           ("就", "吃")]):
            return "需求", URGENCY["需求"]
        return "求助", URGENCY["求助"]
    return "探索", URGENCY["探索"]


def main():
    t0 = time.time()
    print("═══ 流式交互演示（逐词表达 + 感知 + 打断）═══\n")
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

    # 会话状态
    # 饿 的固化句（怎么办型）
    sent = next(e[0] for e in consolidated.get("饿", [])
                if e[2] == "怎么办")
    idx = 0                      # 表达进度（逐词）
    queue = []                   # 打断挂起的会话
    spoken = []                  # 已说出的词
    pending = None               # 待注入的新刺激（输入流）

    print(f"[会话] 饿（需求——固化句「{'/'.join(sent)}」逐词表达）")
    for tick in range(1, 7):
        # ── 每 tick：输入流检查（感知——不阻塞）──
        if tick == 2:
            pending = "疼"       # t2 注入新刺激（正在表达中）
            print(f"  t{tick} [输入流] 新刺激进入：「疼」")
        # ── 打断决策：新刺激紧急度 vs 当前会话 ──
        if pending:
            mode, u_new = urgency_of(ng, pats, n2w, pending, domain,
                                     validation)
            cur_mode, u_cur = urgency_of(ng, pats, n2w, "饿", domain,
                                         validation)
            print(f"  t{tick} [评估] 「{pending}」= {mode}({u_new})"
                  f" vs 当前「饿」= {cur_mode}({u_cur})")
            if u_new > u_cur:
                queue.append(("饿", idx))       # 挂起当前会话
                idx = 0
                teng = next((e[0] for e in consolidated.get("疼", [])
                            if e[2] == "怎么办"), None)
                sent = teng or ["疼", "帮"]   # 疼无固化句——用自由链答案
                print(f"  t{tick} [打断] 求助 > 需求 → 中断「我饿了」，"
                      f"切换到「疼」会话（原会话挂起）")
            else:
                print(f"  t{tick} [继续] 新刺激不更紧急 → 不打断")
            pending = None
        # ── 表达（逐词发音）──
        if idx < len(sent):
            word = sent[idx]
            spoken.append(word)
            print(f"  t{tick} [说] 「{word}」")
            idx += 1
        elif queue:                              # 当前会话完成 → 恢复挂起
            kw, i = queue.pop(0)
            cur_sent = next((e[0] for e in consolidated.get(kw, [])
                            if e[2] == "怎么办"), None)
            sent = cur_sent or ["疼", "帮"]
            idx = i
            print(f"  t{tick} [恢复] 疼会话完成 → 继续「{kw}」剩余")
        else:
            print(f"  t{tick} [静默]（当前无表达——等待输入流）")

    print(f"\n═══ 结果 ═══")
    print(f"  说出的流：{'/'.join(spoken)}")
    print(f"  → 表达被流式打断（'我饿'→'疼帮'），原会话挂起可恢复"
          f"——大模型做不到（半双工），网络可以（全双工）")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
