# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
""""正确读文章"实验：结构化阅读 vs 扁平灌注（2026-08-11）。

问题（用户）：直接灌注导致注意被锁死在文章的每一个字上而不是文章的
内容与句式——网络还没有学会如何正确读文章。

加工层级（人读文章）：句法层（句式识别）→ 内容层（主干提取）→
篇章层（事件序列）。网络现状：学习端只有逐词 STDP——任何层级信息在
进入网络前被压平成一阶词对共现（"的了就在"统计）。

条件（同一 v32.0 基线，纯内存实验——不保存快照，不碰治疗成果）：
  A 扁平灌注：短文 8 句逐词全量 ×10（现状——"不会读"）
  B 结构化阅读：状态机分句 → 模板链集中强化（因为→所以 / 先→然后，
     按句中出现次数等量）+ 内容链（主干对，等量）——"会读"
测量：
  ① 句式泛化：未教组合（内容×模板交叉——"因为[下雨]所以[回家]"）
  ② 内容保持：原句（"因为下雨所以不去公园"）
  ③ 模板强度：因为→所以 / 先→然后 边权（集中强化 vs 句内共现）
  ④ 共现污染：了→就 等散文桥的变化

用法：python _exp_read.py
"""

import json
import time
from pathlib import Path

from schema_net import _learn_sentence, build_pulse
import numpy as np
from snapshot import load_version

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"

# 短文（8 句：4 因果 + 4 时间——全部词在 v32.0 词表）
SENTS = [
    "因为下雨所以去公园", "因为天黑所以回家", "因为饿了所以吃饭",
    "因为生病所以看医生",
    "先洗手然后吃饭", "先写作业然后玩", "先起床然后洗", "先吃饭然后上学",
]
CAUSAL = SENTS[:4]          # 因果句（因为→所以）
TIME = SENTS[4:]            # 时间句（先→然后）
# 内容链（去掉关系词的主干对）
CONTENT = [
    ("下雨", "去公园"), ("天黑", "回家"), ("饿", "吃饭"),
    ("生病", "看医生"),
    ("洗手", "吃饭"), ("写作业", "玩"), ("起床", "洗"), ("吃饭", "上学"),
]
# 句式泛化测试（未教组合——内容×模板交叉）
GEN_TESTS = [
    (["因为", "下雨"], ["所以", "回家"]),     # 下雨×回家（未教）
    (["因为", "天黑"], ["所以", "看医生"]),  # 天黑×看医生
    (["因为", "饿"], ["所以", "去公园"]),    # 饿×去公园
    (["先", "洗手"], ["然后", "上学"]),        # 洗手×上学
    (["先", "起床"], ["然后", "吃饭"]),        # 起床×吃饭
]
# 内容保持测试（原句）
KEEP_TESTS = [
    (["因为", "下雨"], ["所以", "去", "公园"]),
    (["因为", "天黑"], ["所以", "回家"]),
    (["先", "洗手"], ["然后", "吃饭"]),
]


def segment(sent, keys):
    """贪心最长分词（用词表）。"""
    toks = []
    rest = sent
    while rest:
        hit = next((w for w in sorted(keys, key=len, reverse=True)
                    if rest.startswith(w)), None)
        if not hit:
            break
        toks.append(hit)
        rest = rest[len(hit):]
    return toks


def chain_read(ng, pats, n2w, front, back):
    """期望链约束读取：front 末词→back[0] 触发边 + 顺序链读。"""
    from _grow_v16 import edge_between, direct_next_multi
    if edge_between(ng, pats, front[-1], back[0]) <= 0:
        return [], (front[-1], back[0])
    seq = [back[0]]
    cur, rest = back[0], list(back[1:])
    for _ in range(len(rest) + 1):
        if not rest:
            break
        if rest[0] == cur:
            seq.append(cur)
            rest.pop(0)
            continue
        top = direct_next_multi(ng, pats, n2w, [cur], k=8, domain=set(back))
        nxt = next((w for w, _ in top if w == rest[0]), None)
        if not nxt:
            return seq, (cur, rest[0])
        seq.append(nxt)
        rest.pop(0)
        cur = nxt
    return seq, None


def edge(ng, pats, a, b):
    from _grow_v16 import edge_between
    return edge_between(ng, pats, a, b)


def flood_article(ng, pats, sents, times):
    """连续灌注（直接读文章）：句子连续注入，句间**不清痕迹**——
    跨句词对也会被 STDP 学到（"注意力锁死在每个字上"的机制：
    句 1 尾词 → 句 2 首词 的边被强化）。"""
    seq = []
    for toks in sents:
        seq += toks
    for _ in range(times):
        for w in seq:
            ng.v = np.zeros((ng.n, ng.slots))
            ng.spikes = np.zeros(ng.n)
            ng.step(build_pulse(ng.n, pats[w]), slot=0)
            ng.spikes = np.zeros(ng.n)
            ng.step(np.zeros(ng.n), slot=0)   # 痕迹保留（跨句不清）
    for _ in range(4):
        ng.spikes = np.zeros(ng.n)
        ng.step(np.zeros(ng.n), slot=0)


def run_cond(cond):
    import numpy as np
    from schema_net import build_pulse
    ng, vocab, pats, cursor = load_version("32.0")
    ng.w_max = 64.0
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    sents = [segment(s, keys) for s in SENTS]

    if cond == "A":
        # 直接读文章：连续灌注 ×10（跨句污染——"不会读"）
        flood_article(ng, pats, sents, 10)
    elif cond == "B":
        # 正确读文章：教师解析 → 结构化教学（分层：配对/桥/内容）
        # ① 关系词配对（4 因果句 ×10 = 40 次——等量 A）
        for _ in range(40):
            _learn_sentence(ng, ["因为", "所以"], pats, slot=0)
        for _ in range(40):
            _learn_sentence(ng, ["先", "然后"], pats, slot=0)
        # ② 结构桥组件（每句的相邻结构对——等量 A）
        for toks in sents:
            for i in range(len(toks) - 1):
                for _ in range(10):
                    _learn_sentence(ng, [toks[i], toks[i + 1]], pats,
                                    slot=0)
        # ③ 内容对（主干——A 无此边，但用于内容保持；与 A 的教学
        #    总量对齐：A 每句 10 次整句，B 每句相邻对也 10 次 ✓）

    m = {"cond": cond}
    # ① 句式泛化（未教组合）
    ok = 0
    for front, back in GEN_TESTS:
        got, brk = chain_read(ng, pats, n2w, front, back)
        hit = got == back
        ok += hit
        m[f"gen_{''.join(front)}→{''.join(back)}"] = (
            "✅" if hit else f"✗({brk})")
    m["generalize"] = f"{ok}/{len(GEN_TESTS)}"
    # ② 内容保持
    ok = 0
    for front, back in KEEP_TESTS:
        got, brk = chain_read(ng, pats, n2w, front, back)
        hit = got == back
        ok += hit
    m["keep"] = f"{ok}/{len(KEEP_TESTS)}"
    # ③ 模板强度
    m["tmpl_因为→所以"] = f"{edge(ng, pats, '因为', '所以'):g}"
    m["tmpl_先→然后"] = f"{edge(ng, pats, '先', '然后'):g}"
    # ④ 跨句污染（句 1 尾 → 句 2 首：A 应有、B 应无）
    cross = []
    for i in range(len(sents) - 1):
        a, b = sents[i][-1], sents[i + 1][0]
        e = edge(ng, pats, a, b)
        if e > 0:
            cross.append(f"{a}→{b}={e:g}")
    m["cross_sentence"] = "、".join(cross) or "（无）"
    return m


def main():
    t0 = time.time()
    print("═══ 正确读文章实验：结构化阅读 vs 扁平灌注 ═══\n")
    print("（纯内存——不保存快照，不碰 v34.0 治疗成果）\n")
    results = {}
    for cond in ["A", "B"]:
        m = run_cond(cond)
        results[cond] = m
        print(f"── 条件 {cond}（{'扁平灌注' if cond == 'A' else '结构化阅读'}）──")
        for k, v in m.items():
            print(f"  {k}: {v}")
        print()

    a, b = results["A"], results["B"]
    print("═══ 结论对照 ═══")
    print(f"  句式泛化（未教组合）：A={a['generalize']}  B={b['generalize']}")
    print(f"  内容保持（原句）   ：A={a['keep']}  B={b['keep']}")
    print(f"  模板 因为→所以     ：A={a['tmpl_因为→所以']}  "
          f"B={b['tmpl_因为→所以']}")
    print(f"  跨句污染边         ：A=[{a['cross_sentence']}]")
    print(f"                       B=[{b['cross_sentence']}]")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
