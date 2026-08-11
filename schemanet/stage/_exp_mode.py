# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""刺激评估 → 模式选择实验（2026-08-11）：

用户："不是看到句式切换模式，而是看到句式根据需求选择模式——
看到一个问题会选择回答/思考推测/无视等不同模式。"

模式选择 = 刺激 × 内部状态评估的结果（不是句式类型决定）：
  高置信（固化+验证 / 候选独强）→ 回答
  中置信（候选竞争激烈 / 模板可填）→ 思考推测
  低置信+相关 → 存疑标记（事后学习）
  低置信+无关 → 无视

刺激集（同一"问句"类型——测试模式分化）：
  已知：你饿不饿呀？（固化句） / 疼了怎么办？（疼帮）
  半知：猫渴了怎么办？（模板可填 渴→喝 但 猫→渴 缺）
  未知-相关：量子力学是什么？（无候选——但算"相关"？测试）
  未知-无关：今天天气怎么样？（不在知识域）
  半知-2：小狗饿了怎么办？

用法：python _exp_mode.py（纯内存）
"""

import json
import time
from pathlib import Path

from snapshot import load_version, load_consolidated
from _exam_free import free_read, build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats
from _grow_v16 import edge_between, direct_next_multi

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"

STIMS = [
    ("饿", None, "你饿不饿呀？", "已知（固化句）"),
    ("疼", None, "疼了怎么办？", "已知（自由链疼帮）"),
    ("猫", "渴", "猫渴了怎么办？", "半知（缺 猫→渴 边）"),
    ("量子力学", None, "什么是量子力学？", "未知（词表外）"),
    ("天气", None, "今天天气怎么样？", "半知（有知识但竞争）"),
    ("狗", "饿", "小狗饿了怎么办？", "半知（缺边）"),
]


def assess(ng, pats, n2w, kw, state, domain, teach_out, consolidated,
           validation):
    """刺激评估 → (模式, 置信度, 信号)。kw=主题词 state=问句状态词。"""
    sig = {}
    # ① 固化命中 + 验证（遍历验证表——按句内容匹配）
    for (qt, k2, toks), (v0, v1) in validation.items():
        if k2 == kw and v0 > v1:
            sig["固化验证"] = f"「{'/'.join(toks)}」{v0}对"
            return "回答", 0.95, sig
    # ② 问句内容粒度：主体→状态 的边（"猫渴了"→查 猫→渴）
    if state and kw in pats and state in pats:
        e = edge_between(ng, pats, kw, state)
        sig["主体→状态"] = f"{kw}→{state}={e:g}"
        if e <= 0:
            return "思考推测", 0.45, sig   # 缺边——不确定——先猜
    # ③ 候选竞争（绝对强度 + 相对差距）
    top = direct_next_multi(ng, pats, n2w, [kw], k=4,
                            domain=set(pats.keys()))
    if top:
        w1 = top[0][1]
        w2 = top[1][1] if len(top) > 1 else 0.0
        sig["候选"] = f"{top[0][0]}={w1:g} vs {top[1][0] if len(top) > 1 else '—'}={w2:g}"
        if w1 < 20:
            sig["候选"] += "（弱边）"
            return "存疑标记", 0.20, sig    # 弱边 = 几乎不懂
        if w2 == 0 or w1 > w2 * 1.3:
            return "回答", 0.85, sig
        return "思考推测", 0.55, sig
    # ④ 相关性
    if kw in pats:
        sig["相关"] = "词表内"
        return "存疑标记", 0.30, sig
    sig["相关"] = "词表外"
    return "无视", 0.05, sig


def main():
    t0 = time.time()
    print("═══ 刺激评估 → 模式选择实验 ═══\n")
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

    EXPECT = {"饿": "回答", "疼": "思考推测", "猫": "思考推测",
              "量子力学": "存疑标记", "天气": "思考推测", "狗": "回答"}
    n_ok = 0
    print(f"{'刺激':<14}{'期望模式':<10}{'选择':<10}{'置信':<6}{'信号'}")
    for kw, state, ask, tag in STIMS:
        mode, conf, sig = assess(ng, pats, n2w, kw, state, domain,
                                 teach_out, consolidated, validation)
        ok = mode == EXPECT[kw]
        n_ok += ok
        s = "、".join(f"{k}:{v}" for k, v in sig.items())
        print(f"「{ask}」{EXPECT[kw]:<10}{mode:<10}{conf:.2f}  {s}")
    print(f"\n  模式选择正确率：{n_ok}/{len(STIMS)} = {n_ok/len(STIMS):.2f}")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
