# -*- coding: utf-8 -*-
"""多维反应实验：人对刺激的反应 = 认知×效价×唤醒×动机×新颖性（2026-08-11）。

用户："你太一维了——看看人对客观事物的反应研究"。
依据：Russell 效价-唤醒环形模型；趋近-回避动机系统（正→趋近/负→回避/
低唤醒→趋近/高唤醒→回避）；Zajonc 新颖性（新奇→回避/熟悉→趋近）；
评估理论（多维评估→行为）。

网络信号映射：
  认知   = 验证分/候选强度（validation + direct_next）
  效价   = 情绪词关联（疼/饿/冷/怕=负；开心=正）
  唤醒   = 状态词高唤醒（疼/饿/怕——行动需求）vs 低（天气）
  动机   = 状态→需求边（趋近：饿→吃；回避：怕→躲）
  新颖性 = 验证分缺失度（无验证=新）

反应模式：求助/分享/探索/警惕/忽视/回避表达

用法：python _exp_mode2.py（纯内存）
"""

import json
import time
from pathlib import Path

from snapshot import load_version, load_consolidated
from _exam_free import build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats
from _grow_v16 import edge_between, direct_next_multi

DATA = Path(__file__).parent / "data" / "curriculum"

NEG = {"疼", "饿", "累", "冷", "怕", "难过", "生气", "困", "渴", "热"}
POS = {"开心", "高兴"}
HIGH_AROUSAL = {"疼", "饿", "怕", "困", "渴", "冷", "生气", "难过"}
LOW_AROUSAL = {"天气", "无聊", "累"}
APPROACH = {"饿": "吃", "渴": "喝", "累": "睡", "冷": "穿", "困": "睡"}
AVOID = {"怕": "躲"}          # 回避（疼→帮 是求助——趋近解决）

# 刺激：(主题词, 期望反应模式, 说明)
STIMS = [
    ("疼", "求助", "负效价+高唤醒——疼帮（趋近解决）"),
    ("开心", "分享", "正效价+趋近——我开心"),
    ("猫", "探索", "认知中+新颖中——假设验证"),
    ("量子力学", "警惕", "认知低+新颖高——Zajonc 回避（观察）"),
    ("天气", "忽视", "认知低+低唤醒——无聊"),
    ("饿", "需求", "负效价+高唤醒+认知高——饿了就吃饭"),
    ("怕", "回避", "负效价+回避——我害怕"),
]


def assess(ng, pats, n2w, kw, domain, validation):
    """多维评估 → (反应模式, 各维度值)。"""
    sig = {}
    # ① 认知（验证分 + 候选强度）
    v = sum(v0 - v1 for (qt, k2, toks), (v0, v1) in validation.items()
            if k2 == kw)
    top = direct_next_multi(ng, pats, n2w, [kw], k=2, domain=set(domain))
    w1 = top[0][1] if top else 0.0
    sig["认知"] = f"验证{v:g}/边{w1:g}"
    # ② 效价
    val = -1 if kw in NEG else (1 if kw in POS else 0)
    sig["效价"] = {-1: "负", 1: "正", 0: "中"}[val]
    # ③ 唤醒
    aro = 1 if kw in HIGH_AROUSAL else (0 if kw in LOW_AROUSAL else 0.5)
    sig["唤醒"] = {1: "高", 0.5: "中", 0: "低"}[aro]
    # ④ 动机（趋近/回避——状态→需求边）
    mot = "趋近" if kw in APPROACH and edge_between(ng, pats, kw,
                                                    APPROACH[kw]) > 0 \
        else ("回避" if kw in AVOID else "中")
    sig["动机"] = mot
    # ⑤ 新颖性（验证分缺失）
    nov = "新" if v <= 0 else ("中" if v < 3 else "熟")
    sig["新颖"] = nov

    # ── 多维 → 反应模式（优先序）──
    if val < 0 and aro == 1 and w1 > 0:
        # 需求 = 自助链可达（饿→了→就→吃——教学链 3 跳）
        req = APPROACH.get(kw)
        if req and all(edge_between(ng, pats, a, b) > 0
                       for a, b in [(kw, "了"), ("了", "就"),
                                    ("就", req)]):
            return "需求", sig            # 饿→需求（自助链可达）
        if kw in AVOID:
            return "回避", sig            # 怕→回避（负+高唤醒+回避边）
        return "求助", sig                # 疼→求助（帮边——需要人帮）
    if val > 0 and w1 > 0:
        return "分享", sig                # 开心→分享
    if aro == 0:
        return "忽视", sig                # 天气→忽视（低唤醒——无聊）
    if nov == "新" and w1 < 20:
        return "警惕", sig                # 量子力学→警惕（新+弱边）
    return "探索", sig                    # 猫→探索（认知中——假设）


def main():
    t0 = time.time()
    print("═══ 多维反应实验（认知×效价×唤醒×动机×新颖性）═══\n")
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

    n_ok = 0
    print(f"{'刺激':<10}{'期望':<6}{'选择':<6}{'评估明细'}")
    for kw, want, desc in STIMS:
        if kw not in keys:
            print(f"「{kw}」词表外（跳过）")
            continue
        mode, sig = assess(ng, pats, n2w, kw, domain, validation)
        ok = mode == want
        n_ok += ok
        detail = " ".join(f"{k}:{v}" for k, v in sig.items())
        print(f"「{kw}」{want:<6}{mode:<6}  {detail}")
    print(f"\n  多维反应正确率：{n_ok}/{len(STIMS)} = {n_ok/len(STIMS):.2f}")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
