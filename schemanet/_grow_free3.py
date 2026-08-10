# -*- coding: utf-8 -*-
"""自发表达教学 v3（2026-08-10，v2 质量崩坏修复——用户批准"教学降档"）。

v2 教训（质量评估暴露）：引发边 ×20 轮把 我→疼 / 所以→狗 /
为什么→回家 推到 256 顶格 → 顶格边成黑洞 → 自由读链 2 跳后全部
收敛进 3 个循环模板（所以狗饿/但是疼帮/为什么回家）→ 刻板言语。

v3 修复：
  ① 教学降档：引发边 ×4 轮 + back 链 ×4 轮（边权 32 区间，不顶格）
  ② 等权教学：55 句完全等权（所以→我们/他/猫/狗 均衡，不独大）
  ③ 防环验收：free_read 带 3 词模式循环检测（黑洞即停）
  ④ 从 v24.0 重做（v25/v26 的 20 轮顶格作废——过度教学版本）

验收 = free_read 第 1 跳 ∈ back（提示渐隐到自发的验收口径不变）。

加载 v24.0 → 快照 v28.0。用法：python _grow_free3.py
"""

import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from _grow_self_express import STATES, express_read

DATA = Path(__file__).parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).parent / "runs"
R_EDGE = 4                      # 引发边教学轮数（v2 是 20——降档）
R_CHAIN = 4                     # back 链教学轮数（等权）

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
    print("═══ 自发表达教学 v3（降档 ×%d + 等权 + 防环）═══\n" % R_EDGE)
    ng, vocab, pats, cursor = load_version("24.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)

    # 等权教学：每句引发边 ×R_EDGE + back 链 ×R_CHAIN（55 句同一轮数）
    print(f"[教学] 55 句等权：引发边 ×{R_EDGE} + 表达链 ×{R_CHAIN}")
    for i, (label, front, back) in enumerate(TARGETS, 1):
        a, b = front[-1], back[0]
        for _ in range(R_EDGE):
            _learn_sentence(ng, [a, b], pats, slot=0)
        for _ in range(R_CHAIN):
            _learn_sentence(ng, back, pats, slot=0)
    print("[完成] 教学注入完毕")

    # 验收：层2 语用 + 边链自由读第 1 跳
    n_pass = n_fail = 0
    for i, (label, front, back) in enumerate(TARGETS, 1):
        layer2 = (len(back) == 2 and back[0] == "我"
                  and back[1] in STATE_SET)
        if layer2:
            read, _ = express_read(ng, pats, n2w, front[0], back)
            ok = read == back
            tag = "层2语用"
        else:
            read = free_read(ng, pats, n2w, front, domain)
            first = read[0].split("(")[0] if read else ""
            ok = first in back
            tag = "自由读"
        if ok:
            n_pass += 1
            print(f"  ✅ {i:2d}「{label}」{tag}："
                  f"{'/'.join(read[:4]) if read else ''}")
        else:
            n_fail += 1
            print(f"  ✗ {i:2d}「{label}」{tag}："
                  f"{'/'.join(read[:4]) if read else '∅'}")
    print(f"\n[结果] {n_pass}/{len(TARGETS)} 通过（等权降档教学后）")

    save_snapshot(ng, parent="24.0",
                  tag="自发表达教学 v3：引发边×4 降档 + 55 句等权 + "
                      "防环验收（v2 顶格黑洞修复）",
                  metrics={"passed": n_pass, "total": len(TARGETS),
                           "fails": n_fail, "r_edge": R_EDGE},
                  vocab=vocab, pats=pats, cursor=cursor)
    print(f"[完成] v28.0 已存（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
