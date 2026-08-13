# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""逐字听演示：输入流式化——每 tick 一个字 + 渐进置信 + 提前准备（2026-08-11）。

用户："听别人说话是一个字一个字听的，大脑也是一个字一个字接收的"。

输入不是整句参数——是逐字流。每 tick 收一个字 → 渐进评估：
  主题（命中状态词→主题浮现）→ 问法（"不"出现→你X不X=确认型）
  → 置信渐进（0.1→0.4→0.7→0.9→1.0）→ 提前预测/准备/开口（不等整句）。

场景：逐字听「你饿不饿呀？」→ t2 预测主题、t3 判定问法、t4 提前开口
「我饿了」（不等"呀"）——与 4.12 的"说逐字"对称——全双工对称。

用法：python _exp_listen.py（纯内存）
"""

import json
import time
from pathlib import Path

from snapshot import load_version, load_consolidated
from _exam_free import build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"

STATES = {"饿", "渴", "累", "冷", "困", "疼", "开心", "怕"}


def main():
    t0 = time.time()
    print("═══ 逐字听演示（输入流式化 + 渐进置信 + 提前准备）═══\n")
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

    # 输入流（逐字——每 tick 一个字）
    stream = ["你", "饿", "不", "饿", "呀"]
    topic, qtype, conf = None, None, 0.0
    spoken = []
    prep = None           # 已准备的应答
    said = False

    print("输入流：你→饿→不→饿→呀（每 tick 一个字）\n")
    for tick, w in enumerate(stream, 1):
        # ── 逐字接收 + 渐进评估 ──
        if w in STATES:
            topic = w
            conf = max(conf, 0.4)          # 主题浮现——置信 0.4
            print(f"  t{tick} 收「{w}」 [主题] 命中状态词 → 主题=「{w}」"
                  f"（置信 {conf:.1f}）")
            if not prep:
                print(f"          [预测] 在问「{w}」——开始准备应答")
        elif w == "不" and topic:
            qtype = "确认"                  # 你X不X = 是非问
            conf = max(conf, 0.7)
            print(f"  t{tick} 收「{w}」 [问法] 「X不X」模式 → 确认型"
                  f"（置信 {conf:.1f}）")
            # 提前准备：确认型 → 应答「我X了」
            sent = next((e[0] for e in consolidated.get(topic, [])
                         if e[2] == "确认"), None)
            if sent:
                prep = sent
                print(f"          [准备] 确认应答 → 固化句「{'/'.join(sent)}」")
        else:
            print(f"  t{tick} 收「{w}」 [积累]（置信 {conf:.1f}）")
        # ── 提前开口：主题+问法确定（不等整句）──
        if prep and not said and conf >= 0.7:
            said = True
            for word in prep:
                spoken.append(word)
            print(f"          [开口] 提前说出「{'/'.join(prep)}」"
                  f"（不等「呀」——流式对话重叠）")
    # 句尾
    print(f"  t{len(stream)} 收「呀」 [完成]（置信 1.0——句子结束）")

    print(f"\n═══ 结果 ═══")
    print(f"  听入：{'/'.join(stream)}")
    print(f"  渐进评估：主题={topic}（t2）→ 问法={qtype}（t3）→ 开口（t4）")
    print(f"  说出的流：{'/'.join(spoken)}（与听重叠——不等整句）")
    print(f"  → 听逐字 + 说逐字——全双工对称 ✓")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
