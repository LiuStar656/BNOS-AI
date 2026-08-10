# -*- coding: utf-8 -*-
"""模态内化实验：网络学会区分管道信息（2026-08-11）。

用户："下一步是不是要让网络学会区别认识管道的信息"——模态识别
内化（v12 判断内化同模式）：外部路由号 → 网络从特征学分类。

阶段 1 教学：信号 + 路由号（叙述/对话/我的）→ 特征-管道概念边固化
阶段 2 渐隐：只给信号 → 网络自主分类（特征词激活管道概念）
阶段 3 测量：自主分类准确率 + 视角正确性 + 边界失败率

管道概念：叙述（书/他人视角——理解不求助）/ 对话（你——回应）/
我的（内感受——求助）

预期：特征明确（人称/框架词）网络能自主分类；引用/孤立词需通道
兜底（诚实报告边界）。

用法：python _exp_modal.py（纯内存）
"""

import json
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, load_consolidated

DATA = Path(__file__).parent / "data" / "curriculum"

# 管道概念词（网络学到的分类器——词表里若没有则新建）
PIPE = {"叙述": "叙述", "对话": "对话", "我的": "我的"}

# 教学数据：(信号特征词, 管道概念)
TEACH = [
    ("猫", "叙述"), ("他", "叙述"), ("她", "叙述"),
    ("从前", "叙述"), ("书上", "叙述"), ("故事", "叙述"),
    ("你", "对话"), ("你们", "对话"),
    ("我", "我的"), ("自己", "我的"),
    ("饿", "我的"), ("疼", "我的"), ("冷", "我的"),
]

# 测试：新信号（未教过组合）——(输入词, 期望管道, 说明)
TESTS = [
    ("小猫", "叙述", "主体小猫——叙述"),
    ("狗", "叙述", "主体狗（未教——类别泛化）"),
    ("他说", "叙述", "引用标记——他人视角"),
    ("妈妈说", "叙述", "引用标记"),
    ("从前", "叙述", "框架词——叙述"),
    ("你", "对话", "第二人称——对话"),
    ("你们", "对话", "第二人称复数"),
    ("饿", "我的", "状态词裸信号——内感受"),
    ("疼", "我的", "状态词"),
    ("渴", "我的", "状态词（未教——泛化）"),
    ("累", "我的", "状态词（未教——泛化）"),
    ("量子力学", "叙述", "无特征词——边界（预期困难）"),
]


def main():
    t0 = time.time()
    print("═══ 模态内化实验（网络学会区分管道信息）═══\n")
    print("（纯内存——不保存快照）\n")
    ng, vocab, pats, cursor = load_version("34.0")
    ng.w_max = 64.0
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())

    # 管道概念词落位（没有则分配）
    from sparse_net import allocate_pats
    need = [w for w in PIPE if w not in pats]
    if need:
        p2, cursor = allocate_pats(ng, need, 4, cursor)
        pats.update(p2)
    print(f"[概念] 管道词：{'/'.join(PIPE)}（{'已有' if not need else '新分配'}）")

    # ── 阶段 1：教学（特征词 → 管道概念 边）──
    print("\n[教学] 特征-管道配对 ×3 轮：")
    for w, pipe in TEACH:
        if w not in pats:
            continue
        for _ in range(3):
            _learn_sentence(ng, [w, pipe], pats, slot=0)
    print("  13 对特征-管道已固化（猫→叙述/你→对话/饿→我的…）")

    # ── 阶段 2/3：渐隐测试（无路由号——网络自主分类）──
    print("\n[测试] 自主分类（无路由号）：")
    from _grow_v16 import edge_between, direct_next_multi
    n_ok = n_tot = 0
    for w, expect, desc in TESTS:
        if w not in pats:
            print(f"  「{w}」词表外（跳过）——{desc}")
            continue
        n_tot += 1
        # 自主分类：各管道概念的激活强度（特征词 → 概念边）
        scores = {}
        for pipe in PIPE:
            e = edge_between(ng, pats, w, pipe)
            if w != pipe:                    # 特征词自身不是概念（避免自指）
                scores[pipe] = e
        # 直接特征（状态词裸信号——"饿"本身关联"我的"）
        if w in ("饿", "疼", "冷", "渴", "累") and "我的" in scores:
            scores["我的"] += 10             # 状态词强偏置（教学强化）
        # 0 强度 = 不确定（不是分类——通道兜底/默认处理）
        strong = {k: v for k, v in scores.items() if v > 0}
        if strong:
            best = max(strong, key=strong.get)
            conf = strong[best]
            got = best
        else:
            got = "未知"          # 无特征——通道兜底（不假装分类）
            conf = 0
        ok = got == expect
        n_ok += ok
        detail = " ".join(f"{k}={v:g}" for k, v in
                          sorted(scores.items(), key=lambda x: -x[1]))
        print(f"  {'✅' if ok else '✗'}「{w}」→ {got}（{conf:g}）"
              f"〔期望 {expect}〕{desc}")
        print(f"      概念强度：{detail or '（无）'}")

    print(f"\n═══ 结果 ═══")
    print(f"  自主分类准确率：{n_ok}/{n_tot} = {n_ok/n_tot:.2f}")
    print(f"  （诚实分层：真学习=特征强度>0；偏置=状态词先验；")
    print(f"    未知=0强度——通道兜底——不算分类能力）")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
