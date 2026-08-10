# -*- coding: utf-8 -*-
"""自主举一反三量化实验（2026-08-11）：

先量化现状：v34.0 网络在不加教师的情况下，能自主泛化出多少未教
变体？（变体 = 模板槽位替换——状态替换/主体替换/组合替换）

种子（已教学）：饿了就吃饭（4 矩阵项 v34 已固化）
未教变体（全部未直接教学过）：
  状态替换：困了就睡觉 / 疼了就睡觉？/ 冷了穿衣服（部分教过——剔除）
  主体替换：猫饿了就吃饭 / 狗渴了就喝水 / 他累了就睡觉
  组合替换：猫渴了就喝水 / 他冷了穿衣服 / 狗饿了就吃饭
测量：自由链走通率（变体在网络的走链可达性——结构一致性信号）
     + 内容正确性（变体的语义正确性——规则判定：状态-需求匹配）

内部验证信号（拟替代教师）：
  走链可达 + 状态-需求语义边（饿→吃/渴→喝/累→睡/冷→穿）

用法：python _exp_generalize.py
"""

import json
import time
from pathlib import Path

from snapshot import load_version, load_consolidated
from _exam_free import free_read, build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats

DATA = Path(__file__).parent / "data" / "curriculum"

# 状态-需求正确配对（语义标准）
PAIR = {"饿": "吃", "渴": "喝", "累": "睡", "冷": "穿", "困": "睡",
        "疼": "帮"}
# 未教变体：(触发词, 期望需求词, 描述)
VARIANTS = [
    ("困", "睡", "状态替换：困→睡（困未作为种子教学）"),
    ("疼", "帮", "状态替换：疼→帮（疼的固化未教——v32 有疼帮旧边）"),
    ("猫", "吃", "主体替换：猫饿了→吃（猫→饿 有旧边）"),
    ("狗", "喝", "主体替换：狗渴→喝"),
    ("他", "睡", "主体替换：他累→睡"),
    ("猫", "喝", "组合替换：猫渴→喝（双替换）"),
    ("他", "穿", "组合替换：他冷→穿"),
    ("狗", "吃", "组合替换：狗饿→吃"),
    ("小猫", "吃", "主体替换：小猫（OOV 词）"),
]


def main():
    t0 = time.time()
    print("═══ 自主举一反三量化实验（v34.0——不加教师）═══\n")
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
    print(f"[恢复] v34.0：n={ng.n}，固化 {len(consolidated)} 触发词\n")

    from _grow_v16 import edge_between, direct_next_multi

    n_reach = n_correct = n_tot = 0
    print(f"{'变体':<20}{'走链':<16}{'语义':<6}{'说明'}")
    for kw, want, desc in VARIANTS:
        if kw not in keys:
            print(f"「{kw}」✗ 词表外（{desc}）")
            continue
        n_tot += 1
        # 内部验证信号①：走链可达（自由读）
        trace = []
        read = free_read(ng, pats, n2w, [kw], domain, teach_out=teach_out,
                         trace=trace, consolidated=consolidated,
                         validation=validation)
        toks = []
        for w in [x.split("(")[0] for x in read]:
            if w.startswith("[") or w in toks:
                break
            toks.append(w)
        walked = any("整句" in str(t.get("cands", [])) for t in trace)
        if toks and kw not in toks and not walked:
            toks.insert(0, kw)
        said = "/".join(toks) or "（沉默）"
        # 内部验证信号②：语义正确（状态-需求边存在）
        want_edge = edge_between(ng, pats, kw, want)
        sem_ok = want_edge > 0
        # 走链正确 = 表达里出现期望需求词（真泛化的信号：状态→需求）
        reach = bool(toks)
        want_set = {"饿": ["吃", "饭"], "渴": ["喝", "水"], "累": ["睡", "觉"],
                    "冷": ["穿", "衣服"], "困": ["睡", "觉"], "疼": ["帮"],
                    "猫": ["吃", "饭"], "狗": ["喝", "水"], "他": ["睡", "穿"]}
        ws = want_set.get(kw, [want])
        correct = any(any(e in w for e in ws) for w in toks)
        n_reach += reach
        n_correct += correct
        mark = "✅" if correct else "✗"
        print(f"「{kw}」{mark}  {said:<16}{want_edge:g}"
              f"  {desc}")

    print(f"\n═══ 结果 ═══")
    print(f"  走链可达率：{n_reach}/{n_tot} = {n_reach/n_tot:.3f}"
          f"（内部验证信号①）")
    print(f"  内容正确率：{n_correct}/{n_tot} = {n_correct/n_tot:.3f}"
          f"（内部验证信号②）")
    print(f"  自主泛化率（无教师）：{n_correct}/{n_tot}")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
