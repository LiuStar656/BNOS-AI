# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""求证循环 v2：假设-验证（先思考再求证）最小实验（2026-08-11）：

用户批评："这个过于依赖 LLM 了——不是调用问题，而是不会先思考。
先思考可能是什么，再求证，不然会形成路径依赖。"

依据：学习 = 预测误差驱动——没有预测就没有误差就没有学习；直接
求证（LLM 给答案）= 灌注翻版 + 路径依赖。先思考（假设生成）→
内部验证 → 猜对自举（零 LLM）/ 猜错求证（带假设问）→ 误差驱动。

假设生成机制：
  ① 模板填充：种子模板 X渴了→就→Y——已知状态-需求边（渴→喝）
  ② 类比迁移：OOV/缺边时用同类已知配对（猫→饿→吃 → 小猫→吃）
  ③ 候选 = 网络的"猜测"（trace 可见——想到什么）

流程（纯内存，不碰快照）：
  缺口 → 假设生成 → 内部验证（走链通 = 自举，零 LLM）
       → 验证不过 → LLM 求证（带假设："是不是该X？"）→ 误差 → 修正固化

测量：
  假设生成率 / 假设正确率（猜对率——决定 LLM 成本）/
  自举率（内部验证通过——零 LLM）/ LLM 调用量

用法：python _exp_ask2.py
"""

import json
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, load_consolidated
from _exam_free import free_read, build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats
from _grow_v11 import _load_key, _llm_chat
from _grow_v16 import edge_between, direct_next_multi

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"

# 情境：(触发词, 期望需求, 提问, 已知状态-需求模板边(用于假设))
SCENES = [
    ("狗", "喝", "狗渴了怎么办？", "渴", "喝"),
    ("猫", "喝", "猫渴了怎么办？", "渴", "喝"),
    ("小猫", "吃", "小猫饿了怎么办？", "饿", "吃"),
    ("困", "睡", "困了怎么办？", "累", "睡"),     # 困≈累（同类状态）
    ("生病", "休息", "生病了怎么办？", "疼", "帮"),  # 类比失败情境
]


def hypothesis(ng, pats, n2w, kw, tpl_state, tpl_req, keys):
    """① 假设生成：用已知状态-需求模板边（tpl_state→tpl_req）猜。
    候选 = 模板需求词 + 网络 top 联想——trace 记录"想到"。"""
    cands = [tpl_req]
    try:
        top = direct_next_multi(ng, pats, n2w, [tpl_state], k=4,
                                domain=set(keys))
        for w, _ in top[:3]:
            if w not in cands:
                cands.append(w)
    except Exception:
        pass
    return cands


def main():
    from schema_net import consolidate_sentence
    t0 = time.time()
    print("═══ 求证循环 v2：假设-验证（先思考再求证）═══\n")
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
    has_llm = bool(_load_key())
    cursor2 = cursor

    n_guess = n_guess_ok = n_bootstrap = n_ask = n_absorb = 0
    print(f"{'情境':<16}{'先思考(假设)':<18}{'内部验证':<8}{'求证':<8}{'结果'}")
    for kw, want, ask, ts, tr in SCENES:
        if kw not in keys:
            print(f"「{ask}」词表外")
            continue
        # ① 假设生成（先思考——trace 可见）
        cands = hypothesis(ng, pats, n2w, kw, ts, tr, keys)
        guess = cands[0]
        n_guess += 1
        guess_ok = guess == want or any(w in guess for w in want)
        n_guess_ok += guess_ok
        print(f"「{ask}」")
        print(f"    先思考：想到『{guess}』（候选 {cands}）"
              f"{'✅猜对' if guess_ok else '❌猜错'}")
        # ② 内部验证：假设走链（kw→状态→需求）
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
        self_ok = any(any(e in w for e in [want]) for w in toks)
        if self_ok:
            n_bootstrap += 1
            print(f"    内部验证：走通『{'/'.join(toks)}』→ 自举固化（零 LLM）✓")
            slots, cursor2 = consolidate_sentence(
                ng, pats, cursor2, toks or [kw])
            consolidated.setdefault(kw, []).append(
                (toks, slots, "怎么办"))
            continue
        # ③ 猜错/走不通 → 求证 LLM（带假设问——误差驱动）
        n_ask += 1
        if not has_llm:
            print(f"    求证：无 LLM（跳过）")
            continue
        q = (f"孩子猜：「{kw}…{guess}？」你说：「{ask}」"
             f"孩子猜得对吗？请回答：【对】或【错】+ 一句示范（≤10 字）")
        txt = None
        for _ in range(2):
            txt = _llm_chat([{"role": "user", "content": q}])
            if txt:
                break
        ok_guess = txt and ("【对】" in txt or txt.strip().startswith("对"))
        demo = txt.split("示范")[-1].strip("：: \n")[:12] if txt else ""
        print(f"    求证：LLM 判『{txt[:30]}』"
              f"{'（假设对——确认强化）' if ok_guess else '（假设错——误差修正）'}")
        # 固化（示范或假设）
        from _grow_qa_s3 import _segment_demo
        d_toks = _segment_demo(demo, sorted(keys, key=len, reverse=True)) \
            if demo else [kw, guess]
        if not d_toks:
            d_toks = [kw, guess]
        for _ in range(3):
            _learn_sentence(ng, d_toks, pats, slot=0)
        slots, cursor2 = consolidate_sentence(ng, pats, cursor2, d_toks)
        consolidated.setdefault(kw, []).append((d_toks, slots, "怎么办"))
        n_absorb += 1

    print(f"\n═══ 统计 ═══")
    print(f"  假设生成率：{n_guess}/{len(SCENES)}（网络先思考——不再直接问）")
    print(f"  假设正确率（猜对）：{n_guess_ok}/{n_guess}"
          f" = {n_guess_ok/n_guess:.2f}")
    print(f"  自举率（内部验证通过——零 LLM）：{n_bootstrap}/{n_guess}")
    print(f"  求证率（需要 LLM）：{n_ask}/{n_guess}"
          f"（v1 全部求证 vs v2 只求证猜错的）")
    print(f"  LLM 调用：{n_ask} 次（v1 实验 5 次——v2 减少"
          f"{5 - n_ask if n_ask <= 5 else 0} 次）")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
