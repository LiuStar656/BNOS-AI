# -*- coding: utf-8 -*-
"""卷二：域内自由表达考试（2026-08-10，评卷暴露"接话 100 分 /
自己说话 0-3 分"后正式化）。

考法：题干（front）给出 → 网络**无提示自由开口**（top-1 贪心链，
域内过滤虚词枢纽——v15 哲学：把 的/了/不/我 类 256 霸主边挡在
说话域外，让内容词/关系词能冒头）。
输出卷面（不做判定），由人评卷。

用法：python _exam_free.py 24.0 > 卷二.txt
"""

import sys
from pathlib import Path

from snapshot import load_version
from _grow_v16 import direct_next_multi
from _exam_big import A_PAIRS, B_SENTS, C_SENTS, D_SENTS, H_SENTS, I_SENTS

DATA = Path(__file__).parent / "data" / "curriculum"
VER = sys.argv[1] if len(sys.argv) > 1 else "24.0"

# 说话域 = **白名单**（v15"对话域词表"哲学）：教学见过的词才许说——
# 课程 166 条 + 各教学池 + 考试题 + 常用功能词。排除法挡不住散文
# 实词（人208/世界240/第一217.6 实测），必须白名单。
def build_teach_out(rows, q_pool):
    """教学出边表 TEACH_OUT = {src: {dst}}：全部教学句（课程 166 +
    各教学池 + 考试题）的相邻对——自由读的"教学链约束"（自发表达 =
    无提示地行走教学链；散文 256 边不在教学链 → 自动出域）。"""
    from _exam_big import A_PAIRS, B_SENTS, C_SENTS, D_SENTS, H_SENTS, I_SENTS
    from _grow_self_express import STATES, FCT_ITEMS, CAUSE_ITEMS
    from _grow_s3_ask import NEW_ASKS, RHET_ITEMS
    out = {}

    def add(seq):
        for a, b in zip(seq[:-1], seq[1:]):
            out.setdefault(a, set()).add(b)

    # 与说话域收窄一致：教学链只收 对话·构造 + 短文·构造
    # （短文·真实/toutiao 散文句的相邻对会污染教学出边表——
    # 实测 但是→凯尔特人/这腿 混入，导致自由读漂移）
    for r in rows:
        if r["source"] in ("对话·构造", "短文·构造"):
            add(r["tokens"])
    for items in (A_PAIRS, B_SENTS, C_SENTS, D_SENTS, H_SENTS, I_SENTS):
        for item in items:
            if len(item) == 3:
                sent, front, back = item
                add(front + back)
            else:
                add(list(item))
    for ask, kw, exp, layer in q_pool:
        add([kw] + exp)
    for st, d in STATES.items():
        add(d["expr"])
        for sit, kw in d["situ"]:
            add([sit])
    for n, ch, kw, t in FCT_ITEMS:
        add(ch)
    for n, ch, kw in CAUSE_ITEMS:
        add(ch)
    for q, kw, qch, ach in NEW_ASKS:
        add([kw] + qch)
        add(qch + ach)
    for n, ch, k in RHET_ITEMS:
        add(ch)
    # 时间轴教学链（时序 v1）
    add(["昨天", "今天", "明天"])
    add(["早上", "中午", "晚上"])
    # 扩链句（_grow_chain 20 句）与对话期望链（_grow_dialog2/3）——
    # v29.1 教训：教学链表必须含全部教学来源，否则新教学链在自由读
    # 里被滤掉（了→就 读不出，强化 60 次也无效）
    from _grow_chain import CHAIN_SENTS
    for toks in CHAIN_SENTS[1::2]:
        add(toks)
    # 基本常识课程链（_grow_knowledge——盲童常识教学融入运行）
    from _grow_knowledge import LESSONS
    for name, toks in LESSONS:
        add(toks)
    from _grow_dialog3 import SCENES as _D_SCENES
    for _turns in _D_SCENES.values():
        for _t in _turns:
            add([_t[1]] + _t[2])
    return out


def build_domain(ng, pats, rows, q_pool):
    """说话域 = 考试词汇域（白名单精确化，2026-08-10 质量评估闭环）：
    只含 ① 全部考题 front/back 用词 ② 各教学池词 ③ 表达必需功能词
    ④ 关系词/时间词。散文镜像词（大/小/好/坏/说）不在任何期望链 →
    自动出域（死词打地鼠问题根治：不再手写 DEAD，域即过滤器）。"""
    import json
    words = set()
    from _exam_big import (A_PAIRS, B_SENTS, C_SENTS, D_SENTS, H_SENTS,
                           I_SENTS)
    for a, b in A_PAIRS:
        words.update([a, b])
    for items in (B_SENTS, C_SENTS, D_SENTS, H_SENTS, I_SENTS):
        for sent, front, back in items:
            words.update(front)
            words.update(back)
    for ask, kw, exp, layer in q_pool:
        words.add(kw)
        words.update(exp)
    from _grow_self_express import STATES, FCT_ITEMS, CAUSE_ITEMS
    for st, d in STATES.items():
        words.add(st)
        words.update(d["expr"])
        for sit, kw in d["situ"]:
            words.add(kw)
    for n, ch, kw, t in FCT_ITEMS:
        words.update(ch)
        words.add(kw)
    for n, ch, kw in CAUSE_ITEMS:
        words.update(ch)
        words.add(kw)
    from _grow_s3_ask import NEW_ASKS, RHET_ITEMS
    for q, kw, qch, ach in NEW_ASKS:
        words.add(kw)
        words.update(qch)
        words.update(ach)
    for n, ch, k in RHET_ITEMS:
        words.update(ch)
    # 关系词 / 时间词 / 表达必需功能词
    words.update({"所以", "但是", "然后", "因为", "虽然", "先", "如果",
                  "为什么", "昨天", "今天", "明天", "早上", "中午", "晚上",
                  "很", "了", "的", "不", "在", "我", "你", "他", "她",
                  "我们", "你们", "他们", "要", "会", "能", "想", "就",
                  "都", "也", "还", "没", "别", "和", "把", "被", "着",
                  "过", "呢", "吗", "啊", "吧", "一", "上", "下", "里",
                  "外", "去", "来", "做", "是", "有", "帮", "水", "饭",
                  "药", "家"})
    return words & set(pats.keys())


# 功能词（桥词）：自由读时内容词优先——top-k 里跳过功能词取第一个
# 内容词（v15"域内过滤"落地：虚词枢纽 256 不再压死内容词，但虚词
# 仍保留在域内可作桥——链如 "洗→手→然后→我→想→睡觉"）
FUNC = {"的", "不", "在", "我", "你", "他", "她", "我们", "你们",
        "他们", "是", "有", "和", "都", "也", "很", "还", "要",
        "会", "能", "想", "着", "过", "呢", "吗", "啊", "吧", "一",
        "上", "下", "里", "外", "去", "来", "没", "别", "把", "被",
        "又", "再", "这", "那", "开始", "继续", "一直", "常常", "有时",
        "什么", "怎么"}   # 就/了 已移除：衔接副词/完成态（内容性，
                          # 同 所以/但是——"饿了"的"了"是表达内容）


# 语言过滤器（质量评估闭环：循环模板 → 提取废话黑洞边 → 禁掉）：
# 无语义循环边（多→大"多大"散文 254.4、好→什么"什么好"256…）——
# 自由读时跳过，防止链被吸进废话循环。合法链（所以→猫→睡觉、
# 唱→歌"唱歌"）不禁。
BAN_EDGES = {("多", "大"), ("大", "多"), ("好", "什么"), ("什么", "好"),
             ("好", "还是"), ("还是", "好"), ("说", "大"), ("说", "多"),
             ("为什么", "多"), ("玩", "大"), ("歌", "唱"), ("饿", "所以"),
             ("大", "说"), ("多", "说"), ("什么", "为什么"),
             ("为什么", "大"), ("大", "为什么"), ("我", "大"), ("大", "我"),
             ("说", "为什么"), ("然后", "大"), ("好", "大"),
             ("我", "疼"), ("我", "看"), ("我", "帮")}

# 关系词 + 状态词（人称桥允许的衔接语境：但是→[我]→累 / 所以→[我]→
# 想 / 饿→[我]→饿了（"我饿了"表达——状态词后接主语"我"是表达语用
# 规则，v18.12 层2：状态词→"我"+状态）
REL_WORDS = {"所以", "但是", "然后", "因为", "虽然", "先", "如果", "为什么",
             "饿", "冷", "累", "疼", "渴", "困", "难过", "开心", "害怕",
             "生气", "热"}
PRONOUNS = {"我", "你", "他", "她", "我们", "你们", "他们"}

# 死词（自由读不可作目标）：大/说/好/还是/什么——在自由读语境下
# 其 256 出边全是废话黑洞（多大/说大/什么好/还是好），直接滤掉；
# "多"保留（"很多"合法）。质量评估闭环提取。
DEAD = {"大", "说", "好", "还是", "什么"}

# 收敛停止（理论框架 §3.9 终止信号）：下一步 top-1 权 < 上一步 × 0.4
# → 链自然终止（防无限延伸/散文底噪拖尾）
CONVERGE = 0.4


def _is_loop(seq):
    """3 词/2 词模式重复检测（黑洞循环：所以→狗→饿→所以→狗…）。"""
    if len(seq) < 4:
        return False
    for L in (3, 2):
        for i in range(len(seq) - 2 * L + 1):
            if seq[i:i + L] == seq[i + L:i + 2 * L]:
                return True
    return False


def free_read(ng, pats, n2w, front, domain, k=16, steps=8, teach_out=None,
              trace=None, consolidated=None, ctx=None, validation=None):
    """域内自由读（教学链约束 + 内容优先 + 强桥中继）。

    自发表达 = 无提示地行走教学链：每步 top-k 中，内容词候选必须 ∈
    teach_out[cur]（教学出边——散文 256 边不在教学链 → 自动出域）；
    桥词（FUNC）放行作中继。这是"chain_read 去掉 front 提示"的
    泛化形态（教学验证 → 自发表达）。
    规则：内容词候选与桥词 top-1 比较——桥权 ≥ 内容 ×2 走桥
    （所以→我256 ≫ 所以→猫128 → 我→想→睡觉）；桥词中继 ≤4 跳；
    收敛停止（权骤降 ×0.4）；循环检测（3 词模式重复 → [黑洞]）。

    consolidated（句子固化表，2026-08-11）：{起始词: [(句子, 槽位, 类型)]}
    ——起始词命中固化句 → 沿槽位脊柱整句读出（公式化语言：固定常用
    句整块调取；序列完整性由脊柱保证）。

    思考环（2026-08-11 用户："网络缺少中间步骤是机械的寻找最优路
    径"——自闭症干预的认知中介）：固化命中不直接输出——先"停住，
    想一想"（时间延迟——PRT 时间延迟法）：trace 记录"想到整句"，
    然后表达环逐词读出。回答路径 = 听到 → 理解 → 思考 → 表达。

    validation（条件化验证，2026-08-11 用户："对错有多个维度，不
    能单一化"）：{(qtype, 主题, 句子): (对, 错)}——"这句话作为该
    类型问题（该主题）的回答"的对错——条件性区辨入网（同句不同
    问法独立验证：饿了就吃饭答"怎么办"✅、答"想不想吃饭"❌，互不
    污染）。选择：该条件下验证通过 → 读出；未验证 → 组合路径；
    验证否定（错>对）→ 该条件下禁用（过度选择的修复——问法类型
    维度显著化）。"""
    seq, cur = [], front[-1]
    last_w = None
    for _ in range(steps):
        # 唤醒计数（2026-08-11 sleep 接入修复）：free_read 是静态读边
        # 不走 step——slot_freq（唤醒频率）必须由读取路径自己更新，
        # 否则 sleep_consolidate 会把"未被教学注入"的常用词全部当低频
        # 弱化（实测一轮误弱化 5600 万边）。读取 = 唤醒。
        if hasattr(ng, "slot_freq") and cur in pats:
            ng.slot_freq[pats[cur]] += 1
        # 整句固化读出：命中起始词 → 先思考环（内部激活），后表达环
        if consolidated:
            cands = consolidated.get(cur)
            if cands:
                # 条件性区辨：问法类型调制（样本刺激）+ 条件化验证
                pool = [c for c in cands if not ctx or c[2] == ctx]
                if not pool:
                    pool = cands

                def _vscore(c):
                    v = (validation or {}).get(
                        (ctx, cur, tuple(c[0])), (0, 0))
                    return v[0] - v[1]

                ok_pool = [c for c in pool if _vscore(c) > 0]
                pick = None
                if ok_pool:
                    pick = ok_pool[0]        # 该条件下已验证通过 → 用
                elif any(_vscore(c) < 0 for c in pool):
                    pick = None              # 该条件下已验证否定 → 禁用
                else:
                    pick = pool[0]           # 未验证 → 组合路径（频率）
                if pick is not None:
                    # 思考环：内部激活候选——先想再说（trace 可见）
                    if trace is not None:
                        v = (validation or {}).get(
                            (ctx, cur, tuple(pick[0])), (0, 0))
                        trace.append({"state": cur,
                                      "cands": ["整句「%s」验证%d/%d"
                                                % ("".join(pick[0]),
                                                   v[0], v[1])],
                                      "chosen": "整句"})
                    # 表达环：逐词读出（输出完整句——触发词可能在句中，
                    # 确认句「我饿了」的触发词"饿"在位置 1，"我"不能丢）
                    for tok in pick[0]:
                        seq.append(f"{tok}({1024:g})")
                        if trace is not None:
                            trace.append({"state": "表达", "cands": [tok],
                                          "chosen": tok})
                        cur = tok
                        last_w = 1024.0
                        if _is_loop(seq):
                            seq.append("[黑洞]")
                            return seq
                    break   # 表达收束：整句说完即完成（固定常用句——
                            # 不漂移接自由链，杜绝"…就…[黑洞]"尾巴）
        top = direct_next_multi(ng, pats, n2w, [cur], k=k, domain=domain)

        def _filt(tp, src):
            """教学链约束（内容词 + 桥词都必须 ∈ teach_out[src]——
            散文 256 双向边自动出域）+ 禁边/死词；中继同滤。"""
            to = (teach_out or {}).get(src, set())
            return [(w, v) for w, v in tp
                    if (src, w) not in BAN_EDGES and w not in DEAD
                    and (teach_out is not None and w in to)]
        top = _filt(top, cur)
        if not top:
            return seq
        content = [(w, v) for w, v in top if w not in FUNC]
        bridge = [(w, v) for w, v in top if w in FUNC]
        # 人称桥语义化（2026-08-10 质量评估闭环）：人称代词
        # （我/你/他/她/我们…）作中继桥只允许"关系词衔接后"——
        # "但是→[我]→累"（但是我累了 ✓）合法；"累→[我]→疼"
        # （状态词后接人称 ✗）禁止——根治"我"万能桥（禁边打地鼠
        # 确认的架构级问题）
        if bridge and bridge[0][0] in PRONOUNS and cur not in REL_WORDS:
            bridge = []
        # 回环回避（2026-08-11 泛化课程暴露）：饱和回环边（就→了=256）
        # 常排 top-1——直接选它会被防环截断、思维卡死；跳过已经说过的
        # 词转向次优候选（只有全部候选都是回环/被滤才终止）
        looped = {cur} | set(seq[-3:])
        if not content:
            if not bridge:
                return seq
            nxt = bridge[0][0]              # 纯桥跳板
        elif bridge and bridge[0][1] >= content[0][1] * 2:
            b2 = next(((w, v) for w, v in bridge if w not in looped), None)
            nxt = (b2 or bridge[0])[0]      # 强桥链优先（跳过回环桥）
        else:
            c2 = next(((w, v) for w, v in content if w not in looped), None)
            nxt = (c2 or content[0])[0]     # 内容优先（跳过回环词）
        # 桥词中继：从桥词继续读，直到内容词（≤4 跳；同滤禁边）
        hops, last_top = 0, top
        while nxt in FUNC and hops < 4:
            top = direct_next_multi(ng, pats, n2w, [nxt], k=k, domain=domain)
            top = _filt(top, nxt)
            last_top = top
            if not top:
                break
            nxt2 = next((w for w, _ in top if w not in FUNC), None)
            if nxt2:
                nxt = nxt2
                break
            nxt = top[0][0]
            hops += 1
        if nxt in FUNC or nxt == cur:
            seq.append(f"[循环]{nxt}")
            break
        if nxt == cur or nxt in seq[-3:]:
            seq.append(f"[循环]{nxt}")
            break
        wt = next((v for w, v in last_top if w == nxt), 0.0)
        # 心理活动采集（透明化）：当前状态 + 候选 top-3（网络心里
        # 冒出的词）+ 选择（说出的词）——"网络在想什么"完全可观测
        if trace is not None:
            trace.append({"state": cur,
                          "cands": [(w, round(v, 1)) for w, v in top[:3]],
                          "chosen": nxt})
        # 收敛停止（终止信号）：边权骤降 → 链自然终止
        if last_w is not None and wt < last_w * CONVERGE:
            break
        last_w = wt
        seq.append(f"{nxt}({wt:g})")
        if _is_loop(seq):
            seq.append("[黑洞]")
            break
        cur = nxt
    return seq


def main():
    ng, vocab, pats, cursor = load_version(VER)
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())

    # 题型：A 全 20 + B/C/D/H/I 全部 + E/F/G（各自 front）
    from _grow_qa_s3 import build_pool as qa_build_pool
    from _grow_cat import build_cats
    from _grow_self_express import STATES, FCT_ITEMS, CAUSE_ITEMS
    from _grow_s3_ask import NEW_ASKS, RHET_ITEMS
    import json
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)
    print(f"═ 卷二：域内自由表达考试（v{VER}）═ 说话域白名单 "
          f"{len(domain)} 词（教学词表）\n")

    groups = [
        ("A 词语搭配", [("「%s」，接下来说什么？" % a, [a]) for a, b in A_PAIRS]),
        ("B 短句接话", [(s, f) for s, f, b in B_SENTS]),
        ("C 扩句修饰", [(s, f) for s, f, b in C_SENTS]),
        ("D 关系句", [(s, f) for s, f, b in D_SENTS]),
        ("E 问答", [(ask, [kw]) for ask, kw, exp, layer in q_pool[:15]]),
        ("F 自我表达", ([(f"你觉得{st}，你会说什么？", [st])
                        for st, d in STATES.items()]
                       + [(f"情境：{n}", [kw]) for n, ch, kw, t in FCT_ITEMS[:4]]
                       + [(f"情境：{CAUSE_ITEMS[0][0]}", [CAUSE_ITEMS[0][2]])])),
        ("G 主动提问", ([(q, [kw]) for q, kw, qch, ach in NEW_ASKS]
                      + [(f"（教师说：{n}）", [ch[0]]) for n, ch, k in RHET_ITEMS])),
        ("H 压轴未见组合", [(s, f) for s, f, b in H_SENTS]),
        ("I OOV 字造词", [(s, f) for s, f, b in I_SENTS]),
    ]
    n = 0
    for name, items in groups:
        print(f"── {name} ──")
        for i, (sent, front) in enumerate(items, 1):
            n += 1
            read = free_read(ng, pats, n2w, front, domain,
                              teach_out=teach_out)
            print(f"【{n}】{sent}")
            print(f"  网络自己说：{'/'.join(read) or '（说不出）'}\n")


if __name__ == "__main__":
    main()
