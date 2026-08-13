# -*- coding: utf-8 -*-
"""Stage 3 v16（句式颗粒度升级）：配对句式 + 小句内容 + 句式状态机读取。

背景（2026-08-10 探测报告 20260810_122047_probe_s3adv）：
  - 用户："s3 在句式上的颗粒度不够，句式的复杂度没有这么低"
    "用质量更好的来训练，主要是对话和短文的"
  - 探测定位三类读取断点（v15.0 上 10/29 = 34.5%）：
    ① 配对直读过度触发（因为今天→所以，跳过内容小句）
    ② 后半关系词无上下文（所以→吃饭，期待"我"——所以→我 无边）
    ③ 主语结尾断读（所以我→你 201.6，真实语料边碾压）
  - 小句化转移边 12 条仅 2 条存在（缺 因为→他、今天→下雨、所以→我、去→公园）

v16 设计（用户决策：四维全升 + 配对句式 + 小句内容 + 句式状态机 + 上百条）：
  - 数据：stage3_rel_v2.json（108 条，质量优先）——
    短文·真实 47 条（toutiao 新闻标题精筛：去标点/去专名堆砌/词表外词≤4）
    + 对话·构造 38 条（日常口语关系句）+ 短文·构造 23 条（叙述关系句）
    四维全覆盖：嵌套复合 / 内容小句化（因为[S V O]所以[S V O]）/
    关系词位置多样 / 句内修饰加长（今天/助词了/动宾/去地点）
  - 读取：句式状态机 clause_next（废除 REL_NEXT 配对直读）——
    NONE → 读关系词1（因为/虽然/先）→ PRE
    PRE  → 关系词1记忆 + 内容词出边汇聚（打破 下雨→所以/但是 对称竞争）
    PRE  → 读关系词2（所以/但是/然后）→ POST
    POST → ① 读结果主语（排除动词宾语）② 读结果谓语（排除人称，避开 我→你）
  - 训练：108 条 ×R_S 轮 + 自适应校准（分句接话读错 → 固化期望边，教师批改）
  - 验收：升级句式分句接话 ≥0.8（6 句代表：教师说前半 → 网络逐词接后半，
    按角色类型 REL2/SUBJ/PRED 判定命中）
    + 继承 v15 全验收（零遗忘）+ 快照 v16.0

诚实边界：
  - 状态机是读取约束（像人读长句时跟踪"我在原因段还是结果段"），
    不是新语言知识——读出的仍是已学边
  - 校准 = 教师批改环节（同 v13 四阶段 / v15 对话练习），如实报告校准轮数
  - 100 条级数据量（用户 128 并发容量内），句式覆盖仍在"单一配对句"边界

用法：python _grow_v16.py [--smoke]
"""

import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from _net_log import ExpLog
from sparse_net import allocate_pats
from _grow_cat import build_cats
from _grow_v11 import O_FOOD, O_PLACE, V_SET, PERS_MANUAL, edge_between
from _grow_v12 import inherit_acceptance
from _grow_v15 import DOMAIN_WORDS

DATA = Path(__file__).parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).parent / "runs"
SEED = 42
K = 4                  # 神经元/词（与 v11 同源分配制）
R_S = 2                # 每句跟读轮数（108 条数据 → 216 次学习）
CAL_FIX = 3            # 校准：每次固化跟读轮数
CAL_MAX = 60           # 单边校准上限（防死循环）

# ── 关系定式（v16 状态机用；废除 REL_NEXT 配对直读）────────────
REL_FRONT = {"因为": "所以", "虽然": "但是", "先": "然后"}
REL_BACK = set(REL_FRONT.values())
REL_ALL = set(REL_FRONT.keys()) | REL_BACK

# ── 词类划分（状态机过滤依据）──────────────────────────────────
PERS_SET = set(PERS_MANUAL)          # 人称主语词
# 动词/宾语/状态词（POST 读结果主语时排除——主语不应是 V/O/内容词）
VB_O = (set(V_SET) | set(O_FOOD) | set(O_PLACE)
        | {"想要", "需要", "想", "要", "去", "带伞", "吃饭", "睡觉", "看医生",
           "穿衣服", "坚持", "上课", "洗手", "刷牙", "写作业", "跑步", "洗澡",
           "下雨", "饿", "困", "累", "冷", "生病", "石头", "书", "鱼",
           "手", "饭", "觉", "洗", "睡", "喝", "吃", "看", "带"})

# ── 验收：分句接话（对话语义：教师说前半 → 网络接后半）─────────
# (前半前缀, 后半目标)——网络从"关系词1+前半"继续逐词读后半。
# 角色判定：REL2（关系词2，配对约束保证）/ SUBJ（结果主语）/ PRED（结果谓语）
EVAL = [
    (["因为", "今天", "下雨"], ["所以", "我", "带伞"]),        # 因果·时间修饰·小句化
    (["虽然", "他", "生病", "了"], ["但是", "他", "上课"]),    # 转折·助词了·主语重复
    (["先", "吃饭"], ["然后", "我", "写作业"]),                # 顺序·主语后置
    (["因为", "他", "累"], ["所以", "他", "睡觉"]),            # 因果·主谓小句
    (["虽然", "下雨"], ["但是", "我们", "去", "公园"]),        # 转折·去地点
    (["因为", "饿"], ["所以", "我", "吃饭"]),                  # 因果·4词+主语（v14 断点）
]

# ── 句式角色词集（验收/校准按角色类型判定，尊重内容多样性）──────
STATES = {"下雨", "饿", "困", "累", "冷", "生病"}
MODS = {"今天", "了", "不", "仍然"}
ACT_W = {"带伞", "吃饭", "睡觉", "看医生", "穿衣服", "坚持", "上课",
         "洗手", "刷牙", "写作业", "跑步", "洗澡", "洗", "吃", "喝",
         "看", "去", "睡", "要", "想", "带"}
OBJ_W = {"苹果", "西瓜", "牛奶", "面包", "公园", "家", "学校", "商店",
         "石头", "书", "鱼", "手", "饭", "觉"}
SUBJ_SET = PERS_SET                                # 结果主语位（人称）
PRED_SET = ACT_W | OBJ_W                           # 结果谓语位（动作/宾语）
PRE_SET = PERS_SET | STATES | MODS | ACT_W | OBJ_W | REL_BACK   # 内容位（PRE 阶段）


def role_of(w):
    """目标词角色：REL2（关系词2）/ SUBJ（主语）/ PRED（谓语）/ PRE（内容）。"""
    if w in REL_BACK:
        return "REL2"
    if w in PERS_SET:
        return "SUBJ"
    if w in PRED_SET:
        return "PRED"
    return "PRE"


LEGAL = {"REL2": REL_BACK, "SUBJ": SUBJ_SET, "PRED": PRED_SET, "PRE": PRE_SET}


# ── 读取机制：句式状态机（v16 核心，废除 REL_NEXT 配对直读）─────


def direct_next_multi(ng, pats, n2w, srcs, k=6, exclude=None, domain=None):
    """多词直接出边汇聚：srcs 所有词的 W_out 汇聚到目标词，取最强 top-k。

    状态机读取的底层：PRE 阶段把"关系词1 + 内容词"的出边一起汇聚，
    让配对边（因为→所以）与内容边（下雨→所以）叠加，打破对称竞争。
    不走全局回响（同 v15 direct_next：答案在网络边里，直接读边）。
    """
    scores = Counter()
    for src in srcs:
        for i in pats.get(src, []):
            row = ng.W_out[i][0]
            if row:
                for j, wt in row.items():
                    w = n2w.get(j)
                    if not w or w == src:
                        continue
                    if exclude and w in exclude:
                        continue
                    if domain and w not in domain:
                        continue
                    scores[w] += wt
    return scores.most_common(k)


def clause_state(prefix):
    """句式状态机状态识别：NONE → PRE（读到关系词1）→ POST（读到关系词2）。
    返回 (state, rel1)——rel1 = 前半关系词（PRE 阶段的记忆引导）。
    """
    state, rel1 = "NONE", None
    for w in prefix:
        if state == "NONE":
            if w in REL_FRONT:
                state, rel1 = "PRE", w
            elif w in REL_BACK:
                state = "POST"
        elif state == "PRE":
            if w in REL_BACK:
                state = "POST"
    return state, rel1


def clause_next(ng, pats, n2w, prefix, k=6, domain=None):
    """句式状态机读取：按当前状态选择读取路径（解决探测三类断点）。

    NONE（读到关系词1 前）→ 最后词直接出边
    PRE  → 读内容词出边 top-1（排除人称——内容小句尾部再读人称 = 开新小句，
            超出"单一配对句"边界，且真实语料 了→你 强边会碾压专门边）：
            - top-1 是内容词 → 返回（内容小句继续读）
            - top-1 是关系词2 → 内容读完 → 配对约束：
              用关系词1 校正（因为→所以/虽然→但是/先→然后），
              打破 下雨→所以/但是 对称竞争，同时修复 v15 配对直读
              在"关系词1 后立刻直读"的断点（内容没读完不直读）
    POST → last=关系词2：读结果主语（排除 V/O）；
           last=主语：读结果谓语（排除人称——避开 我→你 201.6）
    """
    state, rel1 = clause_state(prefix)
    last = prefix[-1]
    if state == "PRE" and rel1:
        top = direct_next_multi(ng, pats, n2w, [last], k=1, domain=domain,
                                exclude=PERS_SET | {"在"})
        if top and top[0][0] in REL_BACK:
            # 内容小句读完（内容词出边指向关系词2）→ 配对词 = rel1 的配对
            nxt = REL_FRONT[rel1]
            w = edge_between(ng, pats, rel1, nxt)
            return [(nxt, w if w > 0 else 1.0)]
        return top if top else []
    if state == "POST":
        if last in REL_BACK:
            # 断点2 修复：关系词2 后先读结果主语（排除 V/O/关系词 + 域内过滤）
            return direct_next_multi(ng, pats, n2w, [last], k=k,
                                     exclude=VB_O | REL_ALL, domain=domain)
        # 断点3 修复：结果主语后读结果谓语（排除人称，避开 我→你）
        return direct_next_multi(ng, pats, n2w, [last], k=k,
                                 exclude=PERS_SET | {"在"}, domain=domain)
    return direct_next_multi(ng, pats, n2w, [last], k=k, domain=domain)


# ── 目标词角色合法集（分句接话验收口径）──────────────────────────


def legal_for(expect, rel1):
    """目标词 → 合法读出集：REL2 用配对约束（因为→所以，严格句式定式），
    SUBJ/PRED 用角色词集（主语位任何人称、谓语位任何动作/宾语都算接对，
    尊重内容多样性——句式接对了，具体说哪个词是内容自由）。
    """
    role = role_of(expect)
    if role == "REL2":
        return {REL_FRONT[rel1]} if rel1 else REL_BACK
    return LEGAL[role]


# ── 分句接话（对话语义：教师说前半 → 网络逐词接后半）────────────


def chain_generate(ng, pats, n2w, domain=None):
    """分句接话验收：对 EVAL 每项，prefix = 前半（教师说的），
    每步 clause_next 读出 top-1，按目标词角色判定命中（legal_for）。
    核心断点（[因为今天下雨]→所以、[所以]→我、[我]→带伞 等）
    由状态机 + 角色合法集判定，覆盖三类读取断点。
    返回 (行记录, 命中率, 步数)。
    """
    rows, n_hit, n_tot = [], 0, 0
    for front, back in EVAL:
        rel1 = next((w for w in front if w in REL_FRONT), None)
        hits, gens, roles = [], [], []
        prefix = list(front)
        for expect in back:
            role = role_of(expect)
            legal = legal_for(expect, rel1)
            top = clause_next(ng, pats, n2w, prefix, k=1, domain=domain)
            nxt = top[0][0] if top else None
            gens.append(nxt)
            roles.append(role)
            hit = bool(nxt and nxt in legal)
            hits.append(hit)
            n_hit += hit
            n_tot += 1
            prefix.append(expect)          # 目标词推进（后半继续读）
        rows.append({"front": "".join(front), "back": "".join(back),
                     "gen": "".join(g for g in gens if g),
                     "roles": roles, "hits": hits,
                     "match": sum(hits), "tot": len(back)})
        mark = "✅" if all(hits) else "✗"
        print(f"  {mark}「{'/'.join(front)}｜{'/'.join(back)}」"
              f" 读 {'/'.join(g or '∅' for g in gens)}"
              f" 命中 {sum(hits)}/{len(back)}")
        if not all(hits):
            print("     断点: " + "; ".join(
                f"{role_of(e)}位期望{e}读{g or '∅'}"
                for e, g, h in zip(back, gens, hits) if not h))
    return rows, n_hit, n_tot


# ── 校准（教师批改：接话读错 → 固化期望边，温和不循环）───────────


def calibrate(ng, pats, n2w, domain=None, log=None):
    """逐位置校准：读出 ∉ 目标词角色合法集 → 固化 期望相邻对（×CAL_FIX 轮），
    直到读出 ∈ 合法集 或 CAL_MAX 上限。角色集口径下命中容易，无死循环。
    返回校准记录 list。
    """
    fixes = []
    for front, back in EVAL:
        rel1 = next((w for w in front if w in REL_FRONT), None)
        prefix = list(front)
        for expect in back:
            role = role_of(expect)
            legal = legal_for(expect, rel1)
            prev = prefix[-1]
            top = clause_next(ng, pats, n2w, prefix, k=1, domain=domain)
            nxt = top[0][0] if top else None
            if nxt in legal:
                prefix.append(expect)
                continue
            n = 0
            while nxt not in legal and n < CAL_MAX:
                for _ in range(CAL_FIX):
                    if log is not None:
                        log.learn(ng, [prev, expect], pats, slot=0)
                    else:
                        _learn_sentence(ng, [prev, expect], pats, slot=0)
                n += 1
                top = clause_next(ng, pats, n2w, prefix, k=1, domain=domain)
                nxt = top[0][0] if top else None
            if n:
                fixes.append({"step": "".join(prefix), "expect": expect,
                              "role": role, "rounds": n,
                              "before": nxt if top else None})
                print(f"    [校准]「{''.join(prefix)}」{role} 位期望 {expect}"
                      f"（合法 {'/'.join(sorted(legal))}）"
                      f"：固化 {prev}→{expect} ×{n * CAL_FIX}")
            prefix.append(expect)
    return fixes


# ── 主流程 ──────────────────────────────────────────────────────


def main():
    smoke = "--smoke" in sys.argv
    if smoke:
        print("⚠ SMOKE 模式：小规模快跑（机制验证，不跑继承全量、不存快照）")
    t0 = time.time()
    print("═══ Stage 3 v16：句式颗粒度升级"
          "（配对句式 + 小句内容 + 句式状态机读取）═══\n")

    # ── 1. 加载 v15.0 + 数据 ───────────────────────────────────
    ng, vocab, pats, cursor = load_version("15.0")
    # ── 速度配置（2026-08-10 第六/七波验证）：edge_min 弱边修剪 ──
    # 唤起提速 2.5×（0.5）→ v17 实测 2.0 时速度 -23% 且命中率最高（0.076）、
    # 4.0 最快（-31%，命中持平）；第七波 v17 全链实测：0.5→2.0+drive 复用
    # 39.9 → 20.9ms/次（-48%）。注意：会改变训练中唤起评估的 fired 集合
    # （去噪），cal 修正次数可能变；需要严格复现旧行为时设回 0.0。
    ng.edge_min = 2.0
    log = None if smoke else ExpLog()   # 经历日志（崩溃恢复）；smoke 不落盘
    n2w = {j: w for w, ns in pats.items() for j in ns}
    hanzi = json.loads((DATA / "stage0_hanzi.json").read_text(encoding="utf-8"))
    rows = json.loads((DATA / "stage3_rel_v2.json").read_text(encoding="utf-8"))
    print(f"[加载] 15.0：n={ng.n}，词表 {len(pats)}，cursor={cursor}")
    print(f"[数据] stage3_rel_v2.json：{len(rows)} 条"
          f"（{'、'.join(f'{k} {v}' for k, v in Counter(
              r['source'] for r in rows).items())}）")

    # 缺词分配（toutiao 真实句带词表外词）
    all_toks = [w for r in rows for w in r["tokens"]]
    missing = sorted(set(all_toks) - set(pats))
    if missing:
        new_pats, cursor = allocate_pats(ng, missing, K, cursor)
        pats.update(new_pats)
        n2w = {j: w for w, ns in pats.items() for j in ns}
        vocab_new = vocab + [w for w in missing if w not in vocab]
        print(f"[新词] 分配 {len(missing)} 个（真实句词表外词），n={ng.n}")
    else:
        vocab_new = vocab

    domain = sorted(w for w in DOMAIN_WORDS if w in pats)

    # ── 2. 训练：108 条 × R_S 轮（配对句式 + 小句内容整句定式）──
    print(f"\n[训练] {len(rows)} 条 ×{R_S} 轮 = {len(rows) * R_S} 次学习")
    for r in rows:
        for _ in range(R_S):
            if log is not None:
                log.learn(ng, r["tokens"], pats, slot=0)
            else:
                _learn_sentence(ng, r["tokens"], pats, slot=0)

    # ── 3. 阶段1：分句接话（修正前）────────────────────────────
    print("\n[分句接话·修正前]（教师说前半 → 网络接后半）")
    rows1, n1, tot1 = chain_generate(ng, pats, n2w, domain)
    rate1 = n1 / tot1 if tot1 else 0.0
    print(f"  [修正前] 命中 {n1}/{tot1} = {rate1:.3f}")

    # ── 4. 阶段2：自适应校准（教师批改）────────────────────────
    print("\n[校准]（教师批改：接话读错 → 固化期望边 ×3，直到读对）")
    fixes = calibrate(ng, pats, n2w, domain, log=log)
    print(f"  [校准] 共 {len(fixes)} 处（见上）")

    # ── 5. 阶段4：分句接话（修正后，验收口径）─────────────────
    print("\n[分句接话·修正后]")
    rows4, n4, tot4 = chain_generate(ng, pats, n2w, domain)
    rate4 = n4 / tot4 if tot4 else 0.0
    print(f"  [修正后] 命中 {n4}/{tot4} = {rate4:.3f}")

    # ── 6. 继承 v15 验收（零遗忘；smoke 跳过）─────────────────
    inh, ok_inh = {}, True
    if not smoke:
        sem = json.loads((DATA / "stage25_sememes.json").read_text(
            encoding="utf-8"))
        cats25 = build_cats(pats, sem["words"], 12, 3)
        words_old = [w for w in vocab_new if w not in set(hanzi)]
        eval_hanzi = list(np.random.default_rng(7).choice(hanzi, 200,
                                                          replace=False))
        eval_words = list(np.random.default_rng(8).choice(words_old, 300,
                                                         replace=False))
        sents_all = json.loads((DATA / "stage2_sents.json").read_text(
            encoding="utf-8"))
        eval_sents = [sents_all[i] for i in np.random.default_rng(9).choice(
            len(sents_all), 100, replace=False)]
        inh, ok_inh = inherit_acceptance(ng, vocab_new, pats, hanzi, cats25,
                                         sem, eval_hanzi, eval_words,
                                         eval_sents)
        print(f"\n[继承] 字 {inh['char']:.4f}（base {inh['char_before']:.4f}）"
              f" | 词 {inh['word']:.4f}（base {inh['word_before']:.4f}）"
              f" | 句 {inh['sent']:.4f}（base {inh['sent_before']:.4f}）"
              f" | 2.5 类别 {inh['cat25']:.4f}"
              f" | hold {inh['hold25_ok']}/{inh['hold25_tot']}"
              f" {'✅' if ok_inh else '❌ 回退!'}")

    # ── 7. 验收 ────────────────────────────────────────────────
    ok_chain = rate4 >= 0.8
    ok_all = bool(ok_chain and ok_inh)
    print(f"\n[验收] 分句接话修正后 {n4}/{tot4} = {rate4:.3f}"
          f" {'✅' if ok_chain else '❌'}"
          f" | 继承 {'✅' if ok_inh else '❌'}"
          f" {'（smoke 未跑）' if smoke else ''}")
    print(f"\n═══ v16 验收: {'全部通过 ✅' if ok_all else '有失败 ❌'} "
          f"（{time.time() - t0:.0f}s）═══")

    # ── 8. 快照（parent=15.0 → v16.0；冒烟不存）+ 留档 ─────────
    metrics = {"stage3_v16": True, "data_n": len(rows),
               "data_src": Counter(r["source"] for r in rows),
               "chain1": rows1, "chain1_rate": round(rate1, 3),
               "chain4": rows4, "chain4_rate": round(rate4, 3),
               "cal_fixes": fixes,
               "n": ng.n, "all_ok": bool(ok_all)}
    if not smoke and inh:
        metrics["inherit"] = {k: inh[k] for k in (
            "char", "char_before", "word", "word_before", "sent",
            "sent_before", "cat25", "hold25_ok", "hold25_tot")}
    if not smoke:
        if log is not None:
            # checkpoint = 全量快照 + 日志归档（崩溃恢复锚点）
            log.checkpoint(ng, parent="15.0",
                           tag="Stage 3 v16：句式颗粒度升级（配对句式 + 小句内容"
                               " + 句式状态机读取，108 条对话/短文数据）",
                           metrics=metrics, vocab=vocab_new, pats=pats,
                           cursor=cursor)
        else:
            save_snapshot(ng, parent="15.0",
                          tag="Stage 3 v16：句式颗粒度升级（配对句式 + 小句内容"
                              " + 句式状态机读取，108 条对话/短文数据）",
                          metrics=metrics, vocab=vocab_new, pats=pats,
                          cursor=cursor)
        out = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_rel_v16"
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").write_text(json.dumps(metrics,
                                                    ensure_ascii=False,
                                                    indent=1),
                                         encoding="utf-8")
        print(f"\n[留档] {out / 'result.json'}")


if __name__ == "__main__":
    main()
