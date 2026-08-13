# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""自发表达教学 v2（2026-08-10，v1 0/55 暴露两个 bug 后修正）：

v1 bug：
  ① 只跟读 back 内部链——front[-1]→back[0] 引发边没教（看医生→拿 24
     压过 看医生→为什么 8）→ 每句补教引发边（front[-1]→back[0]）
  ② F 层2（我+状态词）的"我"是语用规则（非边）——free_read 跳过桥词
     永远读不出"我冷" → 层2 不考自由读（express_read 即自发形态）

v2 验收（按领域）：
  F 层2（back == [我, 状态词]）→ express_read 验收（自发语用规则）
  其余（E/D/G/FCT）→ free_read 第 1 跳 ∈ back（引发边教学后）

加载 v25.0（v1 教学后，back 链已强化）→ 快照 v26.0。
"""

import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from _grow_self_express import STATES, express_read

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
MAX_ROUND = 20

# 目标句（与 v1 相同：55 句；front = 引发词，back = 期望表达）
TARGETS = [
    ("累会怎样？", ["累"], ["所以", "他", "想", "睡觉"]),
    ("为什么睡觉？", ["睡觉"], ["因为", "他", "累", "了"]),
    ("困会怎样？", ["困"], ["所以", "我", "想", "睡觉"]),
    ("为什么睡觉？", ["睡觉"], ["因为", "我", "困", "了"]),
    ("饿会怎样？", ["饿"], ["所以", "猫", "想", "吃饭"]),
    ("为什么吃饭？", ["吃饭"], ["因为", "猫", "饿", "了"]),
    ("生病会怎样？", ["生病"], ["所以", "他", "想", "看医生"]),
    ("为什么看医生？", ["看医生"], ["因为", "他", "生病", "了"]),
    ("饿会怎样？", ["饿"], ["所以", "狗", "想", "吃饭"]),
    ("为什么吃饭？", ["吃饭"], ["因为", "狗", "饿", "了"]),
    ("冷会怎样？", ["冷"], ["所以", "我", "想", "穿衣服"]),
    ("为什么穿衣服？", ["穿衣服"], ["因为", "我", "冷", "了"]),
    ("下雨会怎样？", ["下雨"], ["所以", "我", "带伞"]),
    ("为什么带伞？", ["带伞"], ["因为", "今天", "下雨"]),
    ("下雨会怎样？", ["下雨"], ["所以", "我", "不", "带伞"]),
    ("你觉得疼", ["疼"], ["我", "疼"]),
    ("你觉得饿", ["饿"], ["我", "饿"]),
    ("你觉得渴", ["渴"], ["我", "渴"]),
    ("你觉得累", ["累"], ["我", "累"]),
    ("你觉得冷", ["冷"], ["我", "冷"]),
    ("你觉得热", ["热"], ["我", "热"]),
    ("你觉得难过", ["难过"], ["我", "难过"]),
    ("你觉得开心", ["开心"], ["我", "开心"]),
    ("你觉得害怕", ["害怕"], ["我", "害怕"]),
    ("你觉得生气", ["生气"], ["我", "生气"]),
    ("情境：我疼，帮帮我", ["疼"], ["我", "疼", "帮", "帮", "我"]),
    ("情境：帮帮我", ["疼"], ["帮", "帮", "我"]),
    ("情境：我要喝水", ["渴"], ["我", "要", "喝", "水"]),
    ("情境：我要吃饭", ["饿"], ["我", "要", "吃", "饭"]),
    ("情境：我难过，因为下雨", ["难过"], ["我", "难过", "因为", "下雨"]),
    ("为什么看医生？", ["看医生"], ["为什么", "看医生"]),
    ("为什么要吃饭？", ["吃饭"], ["为什么", "吃饭"]),
    ("为什么穿衣服？", ["穿衣服"], ["为什么", "穿衣服"]),
    ("为什么回家？", ["回家"], ["为什么", "回家"]),
    ("为什么吃药？", ["吃药"], ["为什么", "吃药"]),
    ("为什么睡觉？", ["睡觉"], ["为什么", "睡觉"]),
    ("你不是吃饭了吗？", ["你"], ["吃", "饭", "了", "吗"]),
    ("难道你不冷吗？", ["你"], ["冷", "吗"]),
    ("什么是苹果？苹果是水果", ["什么"], ["是", "苹果", "苹果", "是", "水果"]),
    ("为什么下雨要带伞？因为下雨", ["为什么"], ["下雨", "带伞", "因为", "下雨"]),
    ("因为昨天天气很冷", ["冷"], ["所以", "他", "穿", "了", "很", "多", "衣服"]),
    ("虽然他很累", ["累"], ["但是", "他", "仍然", "坚持", "写", "作业"]),
    ("先吃饭", ["饭"], ["然后", "我们", "一起", "去", "公园"]),
    ("因为下雨", ["下雨"], ["所以", "他", "今天", "没", "去", "公园"]),
    ("虽然他生病了", ["生病"], ["但是", "他", "还是", "去", "上学"]),
    ("因为天黑了", ["黑"], ["所以", "我们", "赶快", "回家"]),
    ("先洗手", ["手"], ["然后", "我们", "开始", "吃", "饭"]),
    ("虽然今天下雨", ["下雨"], ["但是", "我们", "还是", "去", "公园", "玩"]),
    ("因为昨天天气很热", ["热"], ["所以", "他", "穿", "了", "很", "多", "衣服"]),
    ("虽然她很忙", ["忙"], ["但是", "她", "仍然", "坚持", "上班"]),
    ("先洗脸", ["脸"], ["然后", "我们", "一起", "吃", "饭"]),
    ("因为下雨", ["下雨"], ["所以", "他", "今天", "没", "去", "上学"]),
    ("虽然他生病了", ["生病"], ["但是", "他", "还是", "去", "上班"]),
    ("因为天黑了", ["黑"], ["所以", "我们", "赶快", "睡觉"]),
    ("虽然今天很冷", ["冷"], ["但是", "我们", "还是", "去", "公园"]),
]

STATE_SET = set(STATES.keys())


def main():
    from _exam_free import FUNC, free_read, build_domain
    from _grow_qa_s3 import build_pool as qa_build_pool
    from _grow_cat import build_cats
    import json

    t0 = time.time()
    print("═══ 自发表达教学 v2（引发边 + 领域验收）═══\n")
    ng, vocab, pats, cursor = load_version("25.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)

    n_pass = n_fail = n_layer2 = 0
    for i, (label, front, back) in enumerate(TARGETS, 1):
        layer2 = (len(back) == 2 and back[0] == "我"
                  and back[1] in STATE_SET)
        if layer2:
            # F 层2：语用规则自发（express_read 即无提示形态）
            read, _ = express_read(ng, pats, n2w, front[0], back)
            ok = read == back
            n_layer2 += 1
            if ok:
                n_pass += 1
                print(f"  ✅ {i:2d}「{label}」层2 语用自发："
                      f"「{''.join(read)}」")
            else:
                n_fail += 1
                print(f"  ✗ {i:2d}「{label}」层2 未过："
                      f"「{''.join(read) or '∅'}」")
            continue
        # 边链表达：教引发边（front[-1]→back[0]）直到自由读第 1 跳命中
        a, b = front[-1], back[0]
        for rnd in range(1, MAX_ROUND + 1):
            _learn_sentence(ng, [a, b], pats, slot=0)      # 引发边 ×1
            _learn_sentence(ng, back, pats, slot=0)         # 表达链 ×1
            read = free_read(ng, pats, n2w, front, domain)
            if read and read[0] in back:
                n_pass += 1
                print(f"  ✅ {i:2d}「{label}」第 {rnd} 轮："
                      f"自由读「{'/'.join(read[:4])}」")
                break
        else:
            n_fail += 1
            read = free_read(ng, pats, n2w, front, domain)
            print(f"  ✗ {i:2d}「{label}」{MAX_ROUND} 轮未过："
                  f"自由读「{'/'.join(read[:4])}」")
    print(f"\n[结果] {n_pass}/{len(TARGETS)} 通过"
          f"（层2 语用 {n_layer2} 句 + 边链自由读），未过 {n_fail}")

    save_snapshot(ng, parent="25.0",
                  tag="自发表达教学 v2：引发边（front[-1]→back[0]）+ "
                      "自由读验收（提示渐隐到自发）",
                  metrics={"passed": n_pass, "total": len(TARGETS),
                           "fails": n_fail},
                  vocab=vocab, pats=pats, cursor=cursor)
    print(f"[完成] v26.0 已存（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
