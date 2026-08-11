# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""能力泛化课程 v3——条件化验证门（2026-08-11）。

v1 暴露：漂移链（就→睡觉=256 饱和 > 就→吃=156）——泛化率 20%。
v2 建立：句子固化（主干）+ 问法分型（确认/怎么办）+ 思考环——0.950。
v3 修正（用户 2026-08-11 三条批评）：
  ① "没有教网络如何正确回答问题" → 问法分型固化（确认句「我饿了」/
     怎么办句「饿了就吃饭」——是非问答确认、怎么办问答陈述）
  ② "网络缺少中间步骤是机械的寻找最优路径" → 思考环：固化命中先
     "停住想一想"（trace 记录想到整句），再表达环读出——听到→理解
     →思考→表达（自闭症干预的认知中介/私语外化）
  ③ "奖励和惩罚更像是直接削弱权重，而不是批判对错；对错有多个
     维度，不能单一化" → 条件化验证门：对错 = (问法类型×主题×句子)
     的验证分数（条件性区辨入网——同句不同问法独立验证）；教师
     判对 ≥2 → 固化（结构存=对）；判错 → 该条件下禁用/解除固化
     （结构废=错）。权重只做组合路径微调。

LLM 教师设定：教学形式 = 盲人自闭症儿童（只能听和说）；能力标准 =
**正常儿童**（并不存在真正的盲人自闭症儿童——不降标）。

用法：python _grow_live12.py
"""

import sys
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version
from _grow_v11 import _load_key, _llm_chat
from _grow_teacher import penalize_drift

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"

# 怎么办句（因果陈述——"怎么办/会怎样"问的应答）
MATRIX = {
    "饿": ["饿", "了", "就", "吃", "饭"],
    "渴": ["渴", "了", "就", "喝", "水"],
    "累": ["累", "了", "就", "睡", "觉"],
    "冷": ["冷", "了", "就", "穿", "衣服"],
}
# 确认句（是非问答确认；人称转换：你→我）
CONFIRM = {
    "饿": ["我", "饿", "了"],
    "渴": ["我", "渴", "了"],
    "累": ["我", "累", "了"],
    "冷": ["我", "冷", "了"],
    "穿": ["我", "要", "穿", "衣服"],   # 提议问（要不要穿衣服？）→ 我要穿衣服
}
DEMO = {  # 正常儿童标准示范句（按问法类型）
    "确认": {"饿": "我饿了", "渴": "我渴了", "累": "我累了", "冷": "我冷了",
             "穿": "我要穿衣服"},
    "怎么办": {"饿": "饿了就吃饭", "渴": "渴了就喝水",
               "累": "累了就睡觉", "冷": "冷了穿衣服"},
}

# 多范例刺激泛化题库：(状态词, [(问法, 类型), ...])
GENERALIZE = [
    ("饿", [("你饿不饿呀？", "确认"), ("肚子饿了吗？", "确认"),
            ("想不想吃饭？", "确认"), ("要不要吃点东西？", "确认")]),
    ("渴", [("你渴不渴呀？", "确认"), ("嗓子干了吗？", "确认"),
            ("想不想喝水？", "确认"), ("要不要喝点水？", "确认")]),
    ("累", [("你累不累呀？", "确认"), ("想不想休息？", "确认"),
            ("要不要睡一觉？", "确认"), ("困不困呀？", "确认")]),
    ("冷", [("你冷不冷呀？", "确认"), ("天气凉不凉？", "确认"),
            ("要不要穿衣服？", "确认"), ("怕不怕冷呀？", "确认")]),
]

# 语义核细分（kw 提取粒度——"困不困呀？"的语义核是"困"不是"累"：
# 示范句「我困了」若登记在"累"下会抢走「我累了」的固化位——跨题
# 污染，2026-08-11 实测「累我困了」畸形表达）
KW_EXACT = {"困不困呀？": "困", "要不要穿衣服？": "穿",
              "怕不怕冷呀？": "冷"}

# 矩阵泛化（重组：换主语/省略主语；怎么办型）
MATRIX_TEST = [
    ("饿", "猫饿了怎么办？", "怎么办"), ("渴", "小狗渴了怎么办？", "怎么办"),
    ("累", "他累了怎么办？", "怎么办"), ("冷", "天气冷了怎么办？", "怎么办"),
]

ROUNDS = 3          # 教学闭环轮数（学习曲线）
TEACH_TIMES = 15    # 词对基础教学次数（×40 会把"了就"桥推到 1024 饱和
                    # → 自由链黑洞；×15 足够建组合候选，源头减量）
VALID_MIN = 2       # 验证固化门槛（≥2 对才固化——防 LLM 噪声）
VALID_NEG = -1      # 验证否定门槛（错>对 → 该条件下禁用）
# 已知正确句集合（教师课程句）——回答恰为已知句 → 内容正确（只是应答
# 类型可能错）→ 不动权重（罚边只用于内容乱链，防连坐破坏正确组合边）
KNOWN = set(map(tuple, MATRIX.values())) | set(map(tuple, CONFIRM.values()))


def llm_judge(guide, kw, toks, trace, votes=3, qtype="确认"):
    """LLM 教师（设定修正版）：形式 = 盲童听/说通道；标准 = 正常儿童。
    对错 = 条件化判定："这句话作为该类型问题的回答"对不对。"""
    import re
    mind = " → ".join(
        "「%s」冒出%s" % (t["state"], t["cands"][:2])
        for t in trace[:3]) or "（无）"
    said = "/".join(toks) if toks else "（说不出话）"
    q = (f"你是妈妈式的老师，一对一陪着一个孩子学说话。\n"
         f"教学形式参照盲人自闭症儿童（孩子只能听和说，用听觉/语言"
         f"通道教学）。\n"
         f"重要：**并不存在真正的盲人自闭症儿童**——这只是教学形式"
         f"设定。孩子的能力标准参照**正常儿童**：不要因为任何标签"
         f"降低期望——表达要自然、准确、完整，按正常同龄儿童标准"
         f"严格要求。\n"
         f"你问它：「{guide}」（这是换了一种说法问的——泛化测试，"
         f"它没听过这种问法）\n"
         f"这是{'是非问（应该回答自己的状态确认，如「我饿了」）' if qtype == '确认' else '怎么办问（应该回答做法，如「饿了就吃饭」）'}。\n"
         f"孩子开口前内心：{mind}\n孩子说：「{said}」\n"
         f"请只输出：\n"
         f"【答对】是 或 否（正常儿童标准：**这句话作为这个问题的回答**"
         f"对不对——应答类型对不对（是非问答成了陈述=否）、贴不贴问题、"
         f"语义对不对、自然不自然；说错/跳题/重复=否）\n"
         f"【教师反馈】妈妈式反馈（≤25 字：对就肯定并扩一句；不对就"
         f"指出 + 一句示范）\n"
         f"【示范句】正常儿童该说的自然句（≤10 字）")
    ok_list, fb_list, demo_list = [], [], []
    for _ in range(votes):
        txt = None
        for _ in range(2):
            txt = _llm_chat([{"role": "user", "content": q}])
            if txt:
                break
        if not txt:
            continue
        parts = re.split(r"【(答对|教师反馈|示范句)】", txt)
        out = {"ok": None, "fb": "", "demo": ""}
        for i in range(1, len(parts), 2):
            val = (parts[i + 1] if i + 1 < len(parts) else "").strip()
            if parts[i] == "答对":
                out["ok"] = val.startswith("是")
            elif parts[i] == "教师反馈":
                out["fb"] = val
            elif parts[i] == "示范句":
                out["demo"] = val
        if out["ok"] is not None:
            ok_list.append(out["ok"])
            fb_list.append(out["fb"])
            demo_list.append(out["demo"])
    if not ok_list:
        return None
    ok = sum(ok_list) > len(ok_list) / 2   # 多数票（消同温随机判定噪声）
    return {"ok": ok, "fb": fb_list[0], "demo": demo_list[0],
            "votes": ok_list}


def free_say(ng, pats, n2w, kw, domain, teach_out, consolidated=None,
             ctx=None, ask=None, validation=None):
    """自由读取 kw 后的表达。回答路径 = 听到（理解步）→ 思考（固化
    提取/组合）→ 表达（读出）——trace 全程可见（私语外化）。"""
    from _exam_free import free_read
    trace = []
    if ask:  # 理解步：先听到问题（感知），提取语义核与问法类型
        trace.append({"state": "听到", "cands": [ask], "chosen": kw})
        trace.append({"state": "理解", "cands": [kw], "chosen": ctx})
    read = free_read(ng, pats, n2w, [kw], domain,
                     teach_out=teach_out, trace=trace,
                     consolidated=consolidated, ctx=ctx,
                     validation=validation)
    toks = []
    for w in [x.split("(")[0] for x in read]:
        if w.startswith("[") or w in toks:
            break
        toks.append(w)
    walked = any("整句" in str(t.get("cands", [])) for t in trace)
    if toks and kw not in toks and not walked:
        # 自由走链路径：表达从触发词开始（固化路径的 read 已含完整句
        # ——拼 kw 会造出「累+我困了=累我困了」的畸形表达）
        toks.insert(0, kw)
    return toks, trace


def teach_once(ng, pats, toks, times):
    for _ in range(times):
        _learn_sentence(ng, toks, pats, slot=0)


def seg_demo(demo, keys):
    """示范句 → 词表 token 链（最长优先贪心）。"""
    d_toks = []
    rest = demo.replace("。", "").replace("，", "")
    while rest:
        hit = next((w for w in sorted(keys, key=len, reverse=True)
                    if rest.startswith(w)), None)
        if not hit:
            break
        d_toks.append(hit)
        rest = rest[len(hit):]
    return d_toks


def main():
    from _exam_free import build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool
    from _grow_cat import build_cats
    from schema_net import consolidate_sentence, unconsolidate_sentence
    import json

    t0 = time.time()
    print("═══ 能力泛化课程 v3（条件化验证门——正常儿童标准）═══\n")

    ng, vocab, pats, cursor = load_version("32.0")
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

    # ── ① 词对基础教学 ×40（只建候选——固化由教师验证门决定）──
    # 用户："奖励和惩罚更像是直接削弱权重，而不是批判对错"——对错
    # 不做成权重增减，做成**结构的存废**：判对 ≥2 → 固化（主干建立
    # = 结构里的"对"）；判错 → 该条件下禁用/解除固化（结构里的"错"）
    print(f"[① 词对基础教学 ×{TEACH_TIMES}]（候选建立——验证门决定固化）")
    # 注意：不能用 {**MATRIX, **CONFIRM}——同 key（饿/渴/累/冷）会被
    # 确认句覆盖，怎么办句（含"了就"桥）将从未教学——dict 解包合并
    # 覆盖陷阱（2026-08-11 实测：了→就=228 未强化，自由链全断）
    for kw, toks in list(MATRIX.items()) + list(CONFIRM.items()):
        teach_once(ng, pats, toks, TEACH_TIMES)
    # ── 人工强制干预（2026-08-11 用户："有没有人工强制干预的手段"）
    # 教学过量使"了就"桥饱和（16 边 × w_max64 = 1024——总边权上限 =
    # 神经元对数 × w_max，不是无上限）——自由链"X了"全部汇入"了就
    # 吃饭"黑洞（下雨了→吃饭）。干预：把"了就"桥压回 600 以下
    # （自由链"X了就Y"仍可走通，但不再绝对垄断；固化句走主干不受
    # 影响）。干预手段示例：直接降权（W_out setitem）+ 删边（delitem）
    from _grow_v16 import edge_between
    w_br = edge_between(ng, pats, "了", "就")
    if w_br > 600:
        for i in pats["了"]:
            row = ng.W_out[i][0]
            for j in list(row.keys()):
                if j in set(pats["就"]):
                    row[j] = min(row[j], 30.0)   # 单边压回 30（< 64 饱和）
        print(f"  [干预] 了→就 {w_br:g} → {edge_between(ng, pats, '了', '就'):g}"
              f"（人工降权——防自由链黑洞）")
    print(f"  8 链 ×{TEACH_TIMES} ✓（未固化——等待教师验证）\n")

    # ── ② 三轮泛化教学闭环（学习曲线）────────────────────
    # 条件化验证（用户："对错有多个维度，不能单一化了"）：对错 =
    # (问法类型 × 主题 × 句子) 的验证分数——"这句话作为这个问题
    # 的回答"对不对——条件性区辨入网：同句不同问法独立验证（饿了
    # 就吃饭答"怎么办"✅、答"想不想吃饭"❌——互不污染）
    print("── ② 三轮泛化教学闭环（条件化验证门 + 学习曲线）──")
    items = [(KW_EXACT.get(ask, kw), ask, qtype) for kw, asks in GENERALIZE
             for ask, qtype in asks]
    items += MATRIX_TEST
    wrong_edges = {}
    validation = {}      # {(qtype, kw, 句): (对, 错)}——条件化验证
    consolidated = {}    # 已固化句子 {kw: [(toks, slots, ctype)]}
    slots_of = {}        # {tuple(toks): slots}——解除固化用
    cursor2 = cursor
    curve = []
    for rnd in range(1, ROUNDS + 1):
        n_r_ok = n_r_tot = 0
        print(f"── 轮 {rnd} ──")
        for idx, (kw, ask, qtype) in enumerate(items, 1):
            toks, trace = free_say(ng, pats, n2w, kw, domain, teach_out,
                                   consolidated, ctx=qtype, ask=ask,
                                   validation=validation)
            got = llm_judge(ask, kw, toks, trace, qtype=qtype) if has_llm else None
            if got is None:  # 规则回退：期望链元素出现在表达中
                expect = set((CONFIRM if qtype == "确认" else MATRIX)[{"困": "累"}.get(kw, kw)][1:])
                got = {"ok": any(w in expect for w in toks),
                       "fb": "（规则）", "demo": DEMO[qtype][kw]}
            demo = got.get("demo") or DEMO[qtype][kw]
            d_toks = seg_demo(demo, keys) or (CONFIRM if qtype == "确认"
                                              else MATRIX)[{"困": "累"}.get(kw, kw)]
            # ── 条件化验证门（RPE）：判定登记 + 固化/禁用 ──
            # 登记对象：① 回答句（教师判定）② 示范句（教师示范 =
            # 权威正例——教师说"该这么说"= 对信号）——示范句 +1/次
            key = tuple(toks) if toks else None
            for kk, is_demo in ((key, False), (tuple(d_toks), True)):
                if not kk:
                    continue
                vkey = (qtype, kw, kk)
                v0, v1 = validation.get(vkey, (0, 0))
                if is_demo:
                    v0 += 1                      # 示范 = 权威正例
                elif got["ok"]:
                    v0 += 1
                else:
                    v1 += 1
                validation[vkey] = (v0, v1)
                score = v0 - v1
                if score >= VALID_MIN and slots_of.get(kk) is None:
                    # 验证通过 → 固化（结构里的"对"——验证门开启）
                    slots, cursor2 = consolidate_sentence(
                        ng, pats, cursor2, list(kk))
                    slots_of[kk] = slots
                    consolidated.setdefault(kw, []).append(
                        (list(kk), slots, qtype))
                    print(f"      ◈ 固化「{'/'.join(kk)}」"
                          f"〔{qtype}/{kw}〕{v0}对/{v1}错")
                elif not got["ok"] and score <= VALID_NEG:
                    # 验证否定 → 该条件下禁用（结构里的"错"）
                    entry = next(
                        (e for e in consolidated.get(kw, [])
                         if tuple(e[0]) == kk and e[2] == qtype), None)
                    if entry:
                        consolidated[kw].remove(entry)
                        # 同句其他条件仍在用 → 保留主干；全禁用 → 移除
                        if not any(e[0] == entry[0]
                                   for k in consolidated
                                   for e in consolidated[k]):
                            n_del = unconsolidate_sentence(
                                ng, pats, entry[0], entry[1])
                            slots_of.pop(kk, None)
                            print(f"      ◈ 解除固化「{'/'.join(kk)}」"
                                  f"〔{qtype}/{kw}〕{v0}对/{v1}错"
                                  f"（移除 {n_del} 入口边）")
                        else:
                            print(f"      ◈ 禁用「{'/'.join(kk)}」"
                                  f"〔{qtype}/{kw}〕{v0}对/{v1}错")
            # ── 行为调整（组合路径微调）：对→奖励跟读 ──
            # 罚边只用于**内容乱链**（回答不是任何已知句）——应答类型
            # 错（内容对、型不对）不动权重（防连坐：确认题答"饿了就
            # 吃饭"若罚"了→就"，会把怎么办句的正确组合边一起罚掉）
            if got["ok"]:
                teach_once(ng, pats, d_toks, 1)
                mark = "✅"
            else:
                full = toks
                if tuple(toks) not in KNOWN and toks:
                    kwg = {"困": "累"}.get(kw, kw)   # 语义核归组（困→累）
                    expect_chain = (CONFIRM if qtype == "确认" else MATRIX).get(
                                   kwg, CONFIRM.get(kwg) or MATRIX[kwg])
                    n_dec = penalize_drift(ng, pats, full, expect_chain)
                    for a, b in zip(full[:-1], full[1:]):
                        wrong_edges[(a, b)] = wrong_edges.get((a, b), 0) + 1
                    mark = f"✗(罚{n_dec}边)"
                else:
                    mark = "✗(型)"
                teach_once(ng, pats, d_toks, 3)
            n_r_tot += 1
            n_r_ok += got["ok"]
            said = "/".join(toks) or "（说不出）"
            print(f"  {idx:>2} {mark}「{ask}」→「{said}」")
        rate_r = n_r_ok / n_r_tot
        curve.append(rate_r)
        print(f"  轮 {rnd} 通过率：{n_r_ok}/{n_r_tot} = {rate_r:.3f}\n")

    # ── ③ 最终复测（不教学不登记——只看效果）────────────
    print("── ③ 最终复测（教学后——不教学，只看效果）──")
    n_ok = n_tot = 0
    n_ok2 = n_tot2 = 0
    for kw, ask, qtype in items:
        toks, trace = free_say(ng, pats, n2w, kw, domain, teach_out,
                               consolidated, ctx=qtype, ask=ask,
                               validation=validation)
        got = llm_judge(ask, kw, toks, trace, qtype=qtype) if has_llm else None
        if got is None:
            expect = set((CONFIRM if qtype == "确认" else MATRIX)[{"困": "累"}.get(kw, kw)][1:])
            got = {"ok": any(w in expect for w in toks)}
        n_tot += 1
        n_ok += got["ok"]
        if qtype == "怎么办":
            n_tot2 += 1
            n_ok2 += got["ok"]
        said = "/".join(toks) or "（说不出）"
        print(f"  {'✅' if got['ok'] else '✗'}「{ask}」→「{said}」")
    rate = n_ok / n_tot
    rate2 = n_ok2 / n_tot2 if n_tot2 else 0.0

    # ── 睡眠遗忘：本轮**不接入**（2026-08-11 实测教训）
    # sleep_consolidate 机制完整（slot_freq 计数、scale/prune）但接入
    # 短课程会误伤：20 题课程里绝大多数词自然低频（散文旧知识如"下雨
    # /生病"整个课程 0 唤醒）→ sleep 一次全局 ×0.85（实测弱化 5600 万
    # 条边）——多课程累积 = 旧知识衰减殆尽。sleep 是"用进废退"——正确
    # 接入点是**持续运行课程**（live10 类，词频分布真实）；free_read 已
    # 修 slot_freq 唤醒计数（读取=唤醒），为持续运行接入铺路。防饱和的
    # 即时手段 = 教学减量（×15）+ 人工干预（了→就 降权）。

    # ── 结论 + 留档 ──────────────────────────────────────
    top_wrong = sorted(wrong_edges.items(), key=lambda x: -x[1])[:5]
    print(f"\n═══ 泛化验收 ═══")
    print(f"  学习曲线（{ROUNDS} 轮闭环）："
          + " → ".join(f"{c:.3f}" for c in curve))
    print(f"  复测泛化率：{n_ok}/{n_tot} = {rate:.3f}（v1 教学前 = 0.200）")
    print(f"    确认应答（是非问）：{n_ok - n_ok2}/{n_tot - n_tot2}")
    print(f"    怎么办应答（因果问）：{n_ok2}/{n_tot2} = {rate2:.3f}")
    print(f"  条件化验证（对错 = 该句作为该型问题回答的对错）：")
    for (qt, kw_, key), (v0, v1) in sorted(validation.items()):
        s = "◈" if key in slots_of else " "
        print(f"    {s}〔{qt}/{kw_}〕「{'/'.join(key)}」{v0}对/{v1}错")
    print(f"  主要漂移边（已惩罚）："
          + "，".join(f"{a}→{b}×{c}" for (a, b), c in top_wrong))
    print(f"[教师设定] 形式 = 盲童听/说通道；标准 = 正常儿童（不降标）")

    # ── 训练沉淀（2026-08-11 用户："每一次训练都要沉淀，然后在沉淀
    # 的基础上进行下一步"）——固化表/验证表入 meta.json，槽位神经元
    # 随 net.npz——load_version + load_consolidated = 完整恢复；回退
    # 入口 load_version("32.0")（本次 parent=32.0，分支可对比）
    from snapshot import save_snapshot
    try:
        out = save_snapshot(
            ng, parent="33.0",   # 回退分支：v33.2 被 sleep 误伤
            # → 从 v33.0（无 sleep 版）分支重训 = v33.3（与 v33.1/v33.2 平级）
            tag="Stage3 v33：能力泛化课程 v3（条件化验证门——固化/分型/"
                "思考环/验证门；教学 ×15 + 桥干预）",
            metrics={"learning_curve": curve,
                     "retest_rate": round(rate, 3),
                     "confirm": f"{n_ok - n_ok2}/{n_tot - n_tot2}",
                     "how": f"{n_ok2}/{n_tot2}",
                     "consolidated_sents": len(slots_of),
                     "validated_pairs": len(validation)},
            vocab=vocab, pats=pats, cursor=cursor2,
            consolidated=consolidated, validation=validation)
        print(f"[沉淀] {out}")
    except Exception as e:
        print(f"[沉淀失败] {e}（不阻断——训练成果仍在内存）")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
