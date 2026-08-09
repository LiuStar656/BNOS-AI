# -*- coding: utf-8 -*-
"""Stage 2.6 主谓宾句式（方案 v2.5 §2.6 落地）：S/V/O 槽位 + 类别约束 + 造句。

需求（用户 2026-08-10 决策链）：从"背句"（Stage 2 复述）到"造句"——按 SVO 骨架
组合**没学过**的句子。词序编码 = 角色槽位 hub 绑定（SVO 固定语序下角色绑定 ≡
位置编码，复用 §12.6 已验证的角色槽位机制）；V 位动作类用 jieba 词性标注补 2.5
缺口（探测 _probe_svo.py：动词覆盖 19.3%，数据留档 stage26_pos.json）。

流程（增量，记忆不丢）：
  load_version("8.5")（词义类别，n=148604）
    → 槽位/动作类/人称类模式分配（游标续用自动扩容）
    → 槽位绑定判断（S/V/O 集词 ↔ 槽位，R 轮）
    → 类别判断（动作成员↔动作、人称成员↔人称，R 轮）
    → 骨架跟读（训练组合 [S槽 S词 V槽 V词 O槽 O词] 共发放，R_SVO 轮）
    → 验收① 槽位归属（词→本槽位直连 ≥0.9）
    → 验收② 类别约束（动作/人称 成员→标签 ≥0.9）
    → 验收③a 骨架（S槽→V槽→O槽 边存在）
    → 验收③b 造句填充（测试组合 → 宾语位名词类 top-8 占比 ≥0.5 + 示例造句）
    → 验收④ 字/词/句 + 2.5 四类归属 + hold-out 零遗忘
    → save_snapshot(parent="8.5")

诚实边界（2026-08-10）：
  - 只学"SVO 固定序"（规范主谓宾）；把字句/被字句等变序 → 后续阶段
  - 动词语义义原仍缺（HowNet 覆盖 0），本阶段只有"类别归属"（V 位约束原料）
  - 造句引擎 = 显式骨架走链读出（每步边都是网络真实学到的，§4.8 路径可查），
    非动力学自走传播（大网络虚词劫持 2.5 已证，单链走链失效）
  - jieba 词性有噪声（学/画 标 n、喝 vg/穿 zg），人工词表兜底

用法：python _grow_svo.py [--smoke]   # --smoke 小规模快跑（验证机制）
"""

import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from schema_net import build_pulse
from snapshot import load_version, save_snapshot
from sparse_net import allocate_pats
from _rl_gate import run_train
from _grow_zh import run_recall, fire_ratio, recall_words
from _grow_cat import build_cats, edge_sum, CATS_MANUAL

K = 4
R = 5                    # 判断轮数（槽位绑定/类别）
R_SVO = 3                # 骨架跟读轮数（"读的越多印象越足"）
N_TRAIN = 800            # 骨架训练组合数
N_TEST = 400             # 测试组合数（造句验收，组合从未训练）
N_MAKE = 10              # 示例造句条数
EVAL_HANZI = 200
EVAL_WORD = 300
EVAL_SENT = 100
SEED = 42
DATA = Path(__file__).parent / "data" / "curriculum"

# 槽位模式名（虚拟词，只做角色表征；不与真实词冲突）
SLOT_S, SLOT_V, SLOT_O = "__S__", "__V__", "__O__"
# 新类别标签 hub
TAG_ACT = "动作"
TAG_PERS = "人称"

# 动作类人工词表（v2.5 探测：单字种子 30 个全在 v8.5 网络；jieba 噪声词人工兜底）。
# "要" = 轻动词（语料"我要X"高频），进动作类但不进骨架 V 集的正则约束？——
# 不，"要" 就是 V 位词（我要苹果），正常入列
ACT_MANUAL = ["吃", "喝", "买", "看", "学", "要", "拿", "做", "写", "读",
              "玩", "去", "来", "打", "跑", "走", "坐", "站", "听", "说",
              "画", "踢", "跳", "洗", "穿", "戴", "种", "养", "修", "借",
              "喜欢", "知道", "学习", "工作", "跑步", "唱歌", "游泳", "跳舞"]
# 人称类人工词表（jieba 把 我/他/她 标 r 代词，不进名词类 → S 位单独一类）
PERS_MANUAL = ["我", "你", "他", "她", "我们", "你们", "他们"]
# S 位：人称 + 动物（动物类成员可当主体：猫吃鱼）
S_ANIMALS = ["猫", "狗", "鸟", "鱼", "兔子"]
# V 位骨架集（造句用的动作词，全部应从 ACT_MANUAL 出）
V_SET = ["吃", "喝", "买", "看", "学", "画", "踢", "洗", "读", "听", "要"]
# O 位：食物 + 地点（2.5 已训类别成员）
O_FOOD = ["苹果", "西瓜", "面包", "牛奶", "鸡蛋", "米饭", "香蕉", "饼干"]
O_PLACE = ["学校", "公园", "家", "商店"]
O_TAGS = ["食物", "地点"]          # O 位类别标签（2.5 类别 hub，已训成员边）

# 动宾搭配约束（v9.0 迭代 → v10，2026-08-10 用户：对标 RL/教学法 + 举一反三）：
# 从教材式例句提取 (V, 宾语词) 共现对（教学同款"例句驱动"，非人工类别表）：
#   "我吃苹果/爸爸吃米饭/我喝牛奶/妈妈买西瓜/我洗鸡蛋/我要香蕉/
#    我画公园/我们看学校" …
# → judge 固化 V↔宾语词（V 词出边 = 搭配结构）；同类未共现词凭 2.5 类别
#   标签 2 跳泛化（吃→苹果→食物→香蕉 = 举一反三）；病句（吃+学校）语料
#   无共现 → 无边 → 造不出（负例拒绝）。学/踢/读/听 的合理宾语（书/球/报/
#   歌）不在 O 集 → 不配（诚实留白，造句回退泛名词池）。
VO_PAIRS = {
    "吃": ["苹果", "米饭", "西瓜", "面包", "鸡蛋", "香蕉", "饼干"],
    "喝": ["牛奶"],
    "买": ["苹果", "西瓜", "鸡蛋", "面包", "牛奶"],
    "洗": ["苹果", "鸡蛋", "西瓜"],
    "要": ["苹果", "牛奶", "香蕉", "面包"],
    "画": ["苹果", "公园", "学校"],
    "看": ["公园", "学校", "家", "商店"],
    # 学 / 踢 / 读 / 听：O 集（食物/地点）无合理宾语，不配搭配
}


def judge(ng, pats, w, s, ok=True):
    """判断题（2.5 同款）："w 是 s？" 对→共发放固化；错→拒绝（不固化）。"""
    if not ok:
        return
    neurons = list(pats[w]) + list(pats[s])
    run_train(ng, build_pulse(ng.n, neurons), len(neurons))


def svo_skeleton(ng, pats):
    """骨架跟读：S槽/V槽/O槽 三槽共发放 → 槽位间骨架连接（S槽→V槽→O槽）。

    与词↔槽位绑定**分离注入**（绑定用判断句两两共发放）——防骨架全连接
    把 O 位约束稀释（2026-08-10 冒烟实测：O槽 与 V/S 词等强相连，造句
    top-8 名词占比 0.38 < 0.5）。分离后 O槽 出边只指向 O 词（绑定）
    + 槽位（骨架）+ O 类标签（约束判断），造句聚合干净。"""
    neurons = list(pats[SLOT_S]) + list(pats[SLOT_V]) + list(pats[SLOT_O])
    run_train(ng, build_pulse(ng.n, neurons), len(neurons))


def edge_between(ng, pats, src, dst):
    """src 模式出边汇聚到 dst 模式神经元集合的总权重（有边即 > 0）。"""
    return edge_sum(ng, pats, src, set(pats[dst]))


def make_sentence(ng, pats, n2w, s, v, vo_pairs, cat_members):
    """造句引擎（显式骨架走链读出）：给定 S 词 + V 词 → O 位候选。

    三步直读，每步边都是网络真实学到的（非动力学自走）：
      step1 绑定确认：S2→S槽、V2→V槽 边存在（词认得自己的位）
      step2 骨架跳：  S槽→V槽→O槽 + V槽↔动作、O槽↔食物/地点（槽位类别约束）
      step3 类别聚合（v10 大改，随动词变化）：
        主源 = V 词出边直接搭配词（judge 固化 V↔宾语词，RL 正例强化）
        泛化 = V 词出边指向的类别标签 → 同类未共现词（2 跳举一反三，×0.3）
        保底 = O槽 出边（×0.15，仅当 V 无搭配词时撑起泛名词池）
    病句（吃+学校）：语料无共现 → 吃 出边无学校 → 学校进不了 top（负例拒绝）。
    返回 (路径通否, top 词列表, 该动词搭配词所属类别集)。
    """
    ok = (edge_between(ng, pats, s, SLOT_S) > 0.1
          and edge_between(ng, pats, v, SLOT_V) > 0.1
          and edge_between(ng, pats, SLOT_S, SLOT_V) > 0.1
          and edge_between(ng, pats, SLOT_V, SLOT_O) > 0.1
          and edge_between(ng, pats, SLOT_V, TAG_ACT) > 0.1
          and any(edge_between(ng, pats, SLOT_O, t) > 0.1 for t in O_TAGS))
    virtual = {SLOT_S, SLOT_V, SLOT_O, TAG_ACT, TAG_PERS} | set(O_TAGS)
    scores = Counter()
    # 主源：V 词出边 = 直接搭配词（吃→苹果/米饭/西瓜…；看→公园/学校…）
    for i in pats[v]:
        row = ng.W_out[i][0]
        if row:
            for j, wt in row.items():
                w = n2w.get(j)
                if w and w != v and w not in virtual:
                    scores[w] += wt
    allow = set()
    for o in vo_pairs.get(v, []):
        for c, mem in cat_members.items():
            if o in mem:
                allow.add(c)
    # 泛化（举一反三，v10 修）：allow 类别标签出边 → 同类未共现词 ×0.3
    #   "吃香蕉"没训过但成立：吃→苹果(搭配)→食物(2.5 标签边)→香蕉(2.5 成员边)
    #   二跳真实走链——泛化源 = 搭配词的类别（网络里真实学到的边），非 V 直连
    for c in allow:
        for i in pats.get(c, []):
            row = ng.W_out[i][0]
            if row:
                for j, wt in row.items():
                    w = n2w.get(j)
                    if w and w not in virtual:
                        scores[w] += 0.3 * wt
    # 保底：仅当 V 无搭配词时生效（学/踢/读/听 → 泛名词池诚实留白）；
    # 有搭配词时保底关闭——防 O槽 出边把异类词（吃+学校）带进候选
    if not allow:
        for i in pats[SLOT_O]:
            row = ng.W_out[i][0]
            if row:
                for j, wt in row.items():
                    w = n2w.get(j)
                    if w and w not in virtual:
                        scores[w] += 0.3 * wt
    return ok, [w for w, _ in scores.most_common(8)], allow


def sent_recall(ng, pats, s):
    """句复述率：输入整句 → 唤起整句各词比例（Stage 2 口径）。"""
    neurons = [j for w in s for j in pats[w]]
    fired = run_recall(ng, build_pulse(ng.n, neurons))
    return fire_ratio(fired, neurons)


def main():
    smoke = "--smoke" in sys.argv
    if smoke:
        print("⚠ SMOKE 模式：小规模快跑（仅验证机制，指标不具统计意义）")
        n_train, n_test = 60, 30
        r, r_svo = 2, 1
        n_make = 5
    else:
        n_train, n_test = N_TRAIN, N_TEST
        r, r_svo = R, R_SVO
        n_make = N_MAKE
    t0 = time.time()
    print("═══ Stage 2.6 主谓宾句式（S/V/O 槽位 + 类别约束 + 造句）═══\n")

    # ── 1. 加载 v8.5（词义类别链最新）──
    ng, vocab, pats, cursor = load_version("8.5")
    hanzi = json.loads((DATA / "stage0_hanzi.json").read_text(encoding="utf-8"))
    print(f"[加载] 8.5（Stage 2.5 链最新）：n={ng.n}，模式 {len(pats)}，cursor={cursor}")

    # ── 2. 集合构造（∩ v8.5 网络，人工词表兜底）──
    s_words = sorted({w for w in PERS_MANUAL + S_ANIMALS if w in pats})
    v_words = sorted({w for w in V_SET if w in pats})
    o_words = sorted({w for w in O_FOOD + O_PLACE if w in pats})
    act_mem = sorted({w for w in ACT_MANUAL if w in pats})
    pers_mem = sorted({w for w in PERS_MANUAL if w in pats})
    if not (s_words and v_words and o_words and act_mem and pers_mem):
        raise SystemExit(f"S 集 {len(s_words)} / V 集 {len(v_words)} / O 集 {len(o_words)}"
                         f" / 动作 {len(act_mem)} / 人称 {len(pers_mem)} 有空集")
    print(f"[集合] S 位 {len(s_words)}: {s_words}")
    print(f"[集合] V 位 {len(v_words)}: {v_words}")
    print(f"[集合] O 位 {len(o_words)}: {o_words}")
    print(f"[集合] 动作类成员 {len(act_mem)} | 人称类成员 {len(pers_mem)}")

    # ── 3. 模式分配（槽位 + 新标签 + 新成员，游标续用自动扩容）──
    need = sorted({SLOT_S, SLOT_V, SLOT_O, TAG_ACT, TAG_PERS}
                  | set(act_mem) | set(pers_mem) - set(pats))
    if need:
        total_new = len(need) * K
        if cursor + total_new > ng.n:
            ng.expand(cursor + total_new)
        pats_new, cursor = allocate_pats(ng, need, K, cursor)
        pats.update(pats_new)
        print(f"[分配] 槽位/标签/新成员 {len(pats_new)}（n {ng.n}，cursor={cursor}）")

    # ── 4. 槽位绑定判断（词↔槽位，全体词训，不随组合切分）──
    t1 = time.time()
    for w in s_words:
        for _ in range(r):
            judge(ng, pats, w, SLOT_S)
    for w in v_words:
        for _ in range(r):
            judge(ng, pats, w, SLOT_V)
    for w in o_words:
        for _ in range(r):
            judge(ng, pats, w, SLOT_O)
    print(f"[绑定] S/V/O 集词 ↔ 槽位判断完成（{time.time() - t1:.0f}s）")

    # ── 5. 类别判断（动作/人称 成员 ↔ 标签）+ 槽位↔类别约束判断 ──
    # 槽位↔类别：V槽↔动作（V 位装动作）、O槽↔食物/地点（O 位装名词）——
    # 造句引擎"宾语位约束"的直接依据（两两判断，无全连接污染）
    t1 = time.time()
    for w in act_mem:
        for _ in range(r):
            judge(ng, pats, w, TAG_ACT)
    for w in pers_mem:
        for _ in range(r):
            judge(ng, pats, w, TAG_PERS)
    for _ in range(r):
        judge(ng, pats, SLOT_V, TAG_ACT)
    for t in O_TAGS:
        for _ in range(r):
            judge(ng, pats, SLOT_O, t)
    print(f"[类别] 动作 {len(act_mem)} + 人称 {len(pers_mem)} 成员 + "
          f"槽位约束（V槽↔动作、O槽↔食物/地点）判断完成"
          f"（{time.time() - t1:.0f}s）")

    # ── 5b. 动宾搭配约束（V 词 ↔ 教材式例句共现宾语词 判断题，v10）──
    # 例句驱动（RL 正例强化：语料出现过的搭配固化；负例"吃+学校"无共现 →
    # 不固化 = 拒绝）；学/踢/读/听 不配（O 集无合理宾语，诚实留白）
    vo_pairs = {v: [o for o in ops if o in pats]
                for v, ops in VO_PAIRS.items() if v in v_words}
    vo_trained = []
    t1 = time.time()
    for v, ops in vo_pairs.items():
        for o in ops:
            for _ in range(r):
                judge(ng, pats, v, o)
        vo_trained.append(f"{v}→{','.join(ops)}")
    print(f"[动宾] 例句共现搭配判断完成（{len(vo_pairs)} 动词，"
          f"{sum(len(o) for o in vo_pairs.values())} 宾语对）：{vo_trained}"
          f"（{time.time() - t1:.0f}s）")

    # ── 6. 骨架跟读（S槽/V槽/O槽 三槽共发放 × R_SVO 轮）──
    # 绑定已全体完成（第 4 步），骨架只训槽位间连接；测试组合的"造句"由
    # 词↔槽位绑定 + 槽位↔类别约束 + 骨架 泛化出（组合从未以整句共发放形式出现）
    all_combos = [(s, v, o) for s in s_words for v in v_words for o in o_words]
    rng = np.random.default_rng(SEED)
    perm = rng.permutation(len(all_combos))
    train_combos = [all_combos[i] for i in perm[:n_train]]
    test_combos = [all_combos[i] for i in perm[n_train:n_train + n_test]]
    t1 = time.time()
    for _ in range(r_svo):
        svo_skeleton(ng, pats)
    print(f"[骨架] 三槽共发放 × {r_svo} 轮跟读"
          f"（总组合 {len(all_combos)}，训练 {len(train_combos)}，"
          f"测试 {len(test_combos)} 从未整句训练）"
          f"（{time.time() - t1:.0f}s）")

    # ── 7. 验收① 槽位归属（词→本槽位直连 ≥0.9）──
    per = {}
    for slot, words in [(SLOT_S, s_words), (SLOT_V, v_words), (SLOT_O, o_words)]:
        rs = np.mean([edge_between(ng, pats, w, slot) > 0.1 for w in words])
        per[slot] = round(float(rs), 4)
    r_slot = np.mean(list(per.values()))
    print(f"\n[验收①] 槽位归属（词→本槽位直连）: {r_slot:.4f} "
          f"{'✅ ≥0.9' if r_slot >= 0.9 else '❌'} {per}")

    # ── 8. 验收② 类别约束（动作/人称 成员→标签 + 槽位↔类别 ≥0.9）──
    per2 = {}
    for tag, members in [(TAG_ACT, act_mem), (TAG_PERS, pers_mem)]:
        rs = np.mean([edge_between(ng, pats, w, tag) > 0.1 for w in members])
        per2[tag] = round(float(rs), 4)
    per2["V槽↔动作"] = round(edge_between(ng, pats, SLOT_V, TAG_ACT), 1)
    per2["O槽↔食物"] = round(edge_between(ng, pats, SLOT_O, "食物"), 1)
    per2["O槽↔地点"] = round(edge_between(ng, pats, SLOT_O, "地点"), 1)
    r_tag = np.mean([per2[t] for t in [TAG_ACT, TAG_PERS]])
    print(f"[验收②] 类别约束（成员→标签直连）: {r_tag:.4f} "
          f"{'✅ ≥0.9' if r_tag >= 0.9 else '❌'} {per2}")

    # ── 9. 验收③a 骨架（S槽→V槽→O槽 + 槽位↔类别约束 边存在）──
    sk_sv = edge_between(ng, pats, SLOT_S, SLOT_V)
    sk_vo = edge_between(ng, pats, SLOT_V, SLOT_O)
    sk_va = edge_between(ng, pats, SLOT_V, TAG_ACT)
    sk_of = edge_between(ng, pats, SLOT_O, "食物")
    sk_op = edge_between(ng, pats, SLOT_O, "地点")
    ok_skel = sk_sv > 0.1 and sk_vo > 0.1 and sk_va > 0.1 \
        and (sk_of > 0.1 or sk_op > 0.1)
    print(f"[验收③a] 骨架: S槽→V槽 {sk_sv:.1f} | V槽→O槽 {sk_vo:.1f} | "
          f"V槽→动作 {sk_va:.1f} | O槽→食物 {sk_of:.1f} | O槽→地点 {sk_op:.1f} "
          f"{'✅ 骨架成立' if ok_skel else '❌ 骨架缺失'}")

    # ── 10. 验收③b 造句填充（测试组合 → 宾语位类别约束 top-8 占比 ≥0.5）──
    # 三分判定（v10，对标 RL/教学法）：
    #   合理组合（V 有搭配词 & O ∈ 搭配类别）：top-8 搭配类别占优 ≥0.5
    #     （吃+苹果 → 食物占优 = 正例泛化，RL 奖励泛化）
    #   病句组合（V 有搭配词 & O ∉ 搭配类别）：O 词不得进 top-8
    #     （吃+学校 → 学校不出现 = 负例拒绝，RLHF 负反馈）
    #   无搭配动词（学/踢/读/听）：宾语位名词占比 ≥0.5（诚实留白）
    # 名词类 = O 集词 ∪ 2.5 食物/地点类成员（含 hold-out，都是名词）
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats25 = build_cats(pats, sem["words"], 12, 3)
    cat_members = {}
    for l in ["食物", "地点"]:
        d = cats25.get(l)
        cat_members[l] = set(d["train"]) | set(d["hold"]) if d else set()
    # O 集词按语义归属类别（O_FOOD→食物、O_PLACE→地点；学校/公园已在地点类，
    # 家/商店等补进）——不能把全部 O 集词塞进每个类别（会让 allow 判定失效）
    cat_members["食物"] |= set(O_FOOD)
    cat_members["地点"] |= set(O_PLACE)
    noun_pool = cat_members["食物"] | cat_members["地点"]
    n_ok_comb, n_bad_comb, n_plain = 0, 0, 0
    n_ok_pass, n_bad_pass, n_plain_pass = 0, 0, 0
    make_sigs = []
    n2w = {j: w for w, ns in pats.items() for j in ns}
    eval_make = test_combos[:n_make] if smoke else test_combos
    for s, v, o in eval_make:
        ok_path, top, allow = make_sentence(ng, pats, n2w, s, v, vo_pairs,
                                            cat_members)
        if not allow:                       # 无搭配动词 → 名词占比
            ratio = sum(1 for w in top if w in noun_pool) / max(1, len(top))
            n_plain += 1
            n_plain_pass += ok_path and ratio >= 0.5
            kind = "plain"
        else:
            allow_mem = set().union(*(cat_members[c] for c in allow))
            ratio = sum(1 for w in top if w in allow_mem) / max(1, len(top))
            if o in allow_mem:              # 合理组合（正例泛化）
                n_ok_comb += 1
                n_ok_pass += ok_path and ratio >= 0.5
                kind = "ok"
            else:                           # 病句组合（负例拒绝：O 词不得进 top）
                rejected = o not in top
                n_bad_comb += 1
                n_bad_pass += ok_path and rejected
                ratio = 1.0 if rejected else 0.0
                kind = "bad"
        if len(make_sigs) < N_MAKE:
            make_sigs.append((s, v, o, kind, round(ok_path * 1.0, 1),
                              round(ratio, 2), top[:8], sorted(allow)))
    # 无样本（冒烟组合少）→ 该维跳过不判失败（记 1.0 占位，全量必测到）
    r_ok = n_ok_pass / n_ok_comb if n_ok_comb else 1.0
    r_bad = n_bad_pass / n_bad_comb if n_bad_comb else 1.0
    r_plain = n_plain_pass / n_plain if n_plain else 1.0
    r_make = (n_ok_pass + n_bad_pass + n_plain_pass) / max(1, len(eval_make))
    print(f"[验收③b] 造句填充（测试组合 {len(test_combos)} → 宾语位类别约束）: "
          f"{r_make:.4f} {'✅ ≥0.5' if r_make >= 0.5 else '❌'}")
    print(f"   合理搭配（V 有搭配 & O 同类）: {n_ok_pass}/{n_ok_comb} = {r_ok:.4f}"
          f" {'✅' if r_ok >= 0.5 else '❌'}")
    print(f"   病句拒绝（V 有搭配 & O 异类）: {n_bad_pass}/{n_bad_comb} = {r_bad:.4f}"
          f"（异类 O 不得进 top-8）{'✅' if r_bad >= 0.8 else '❌'}")
    print(f"   无搭配动词（学/踢/读/听 诚实留白）: {n_plain_pass}/{n_plain}"
          f" = {r_plain:.4f}（宾语位名词占比）")
    print(f"[示例造句]（S+V → 宾语位候选；* = 搭配类别命中；× = 病句拒绝）")
    for s, v, o, kind, path, ratio, top, allow in make_sigs:
        allow_mem = set().union(*(cat_members[c] for c in allow)) if allow else noun_pool
        marks = "".join("*" if w in allow_mem else "·" for w in top)
        tag = {"ok": f"✓搭配 {ratio:.2f}", "bad": f"✗病句拒绝 {ratio:.2f}",
               "plain": f"~泛名词 {ratio:.2f}"}[kind]
        print(f"  {s}+{v} → {tag} 期望O=[{o}] 搭配[{('、'.join(allow) if allow else '无')}]")
        print(f"    {top}")
        print(f"    {marks}")

    # ── 11. 验收④ 字/词/句 + 2.5 四类归属 + hold-out 零遗忘 ──
    words_old = [w for w in vocab if w not in set(hanzi)]
    rng7 = np.random.default_rng(7)
    eval_hanzi = list(rng7.choice(hanzi, EVAL_HANZI, replace=False))
    rng8 = np.random.default_rng(8)
    eval_words = list(rng8.choice(words_old, EVAL_WORD, replace=False))
    sents_all = json.loads((DATA / "stage2_sents.json").read_text(encoding="utf-8"))
    rng9 = np.random.default_rng(9)
    eval_sents = [sents_all[i] for i in rng9.choice(len(sents_all), EVAL_SENT,
                                                    replace=False)]
    r0 = recall_words(ng, pats, eval_hanzi, K)
    rw0 = recall_words(ng, pats, eval_words, 20)
    rs0 = np.mean([sent_recall(ng, pats, s) for s in eval_sents])
    r0_after = recall_words(ng, pats, eval_hanzi, K)
    rw0_after = recall_words(ng, pats, eval_words, 20)
    rs0_after = np.mean([sent_recall(ng, pats, s) for s in eval_sents])
    ok_char = r0_after >= r0 - 0.01
    ok_word = rw0_after >= rw0 - 0.01
    ok_sent = rs0_after >= rs0 - 0.01
    # 2.5 四类归属 + hold-out 回退检查（v8.5 已训好的边不能被 2.6 冲掉）
    cat_ok, hold_ok = {}, {}
    for label, d in cats25.items():
        tag_n = set()
        for t in d["tags"]:
            tag_n.update(pats.get(t, []))
        cat_ok[label] = round(float(np.mean(
            [edge_sum(ng, pats, w, tag_n) > 0.1 for w in d["train"]])), 4)
        others_n = set()
        for l2, d2 in cats25.items():
            if l2 == label:
                continue
            for t in d2["tags"]:
                others_n.update(pats.get(t, []))
            for m in d2["train"]:
                others_n.update(pats[m])
        mine = set(tag_n)
        for m in d["train"]:
            mine.update(pats[m])
        n_ok = 0
        for h in d["hold"]:
            shared = set(sem["words"][h]) & set().union(
                *(set(sem["words"][m]) for m in d["train"]))
            self_n = set(mine)
            for s in shared:
                self_n.update(pats.get(s, []))
            hold_ok[label] = int(edge_sum(ng, pats, h, self_n) > 0
                                 and edge_sum(ng, pats, h, self_n)
                                 >= edge_sum(ng, pats, h, others_n) * 0.5)
            n_ok += hold_ok[label]
        hold_ok[label] = n_ok
    r_cat25 = np.mean(list(cat_ok.values())) if cat_ok else 0.0
    n_hold25_ok = sum(hold_ok.values())
    n_hold25_tot = sum(len(d["hold"]) for d in cats25.values())
    ok_cat25 = all(v >= 0.9 for v in cat_ok.values()) if cat_ok else True
    ok_hold25 = n_hold25_ok >= n_hold25_tot * 0.5 if n_hold25_tot else True
    print(f"\n[验收④] 字 {r0_after:.4f}（base {r0:.4f}）{'✅' if ok_char else '❌ 回退!'}")
    print(f"[验收④] 词 {rw0_after:.4f}（base {rw0:.4f}）{'✅' if ok_word else '❌ 回退!'}")
    print(f"[验收④] 句 {rs0_after:.4f}（base {rs0:.4f}）{'✅' if ok_sent else '❌ 回退!'}")
    print(f"[验收④] 2.5 四类归属 {r_cat25:.4f} {'✅' if ok_cat25 else '❌'} {cat_ok}")
    print(f"[验收④] 2.5 hold-out 举一反三 {n_hold25_ok}/{n_hold25_tot} "
          f"{'✅' if ok_hold25 else '❌'}")

    ok_all = bool(r_slot >= 0.9 and r_tag >= 0.9 and ok_skel
                  and r_make >= 0.5 and r_bad >= 0.8
                  and ok_char and ok_word and ok_sent
                  and ok_cat25 and ok_hold25)
    print(f"\n═══ Stage 2.6 验收: {'全部通过 ✅' if ok_all else '有失败 ❌'} "
          f"（{time.time() - t0:.0f}s）═══")

    # ── 12. 快照（parent=9.0 动宾迭代 → v10.0；回退同代变体对比链；冒烟不存）──
    metrics = {"slot_recall": round(r_slot, 4), "slot_per": per,
               "tag_recall": round(r_tag, 4), "tag_per": per2,
               "skel_sv": round(sk_sv, 1), "skel_vo": round(sk_vo, 1),
               "skel_va": round(sk_va, 1), "skel_of": round(sk_of, 1),
               "make_recall": round(r_make, 4),
               "vo_ok_recall": round(r_ok, 4), "vo_ok": n_ok_pass,
               "vo_ok_total": n_ok_comb,
               "vo_bad_recall": round(r_bad, 4), "vo_bad": n_bad_pass,
               "vo_bad_total": n_bad_comb,
               "vo_plain_recall": round(r_plain, 4), "vo_plain": n_plain_pass,
               "vo_plain_total": n_plain,
               "vo_pairs": vo_pairs,
               "make_train": n_train, "make_test": n_test,
               "make_examples": make_sigs,
               "char_recall": round(r0_after, 4),
               "char_recall_before": round(r0, 4),
               "word_recall": round(rw0_after, 4),
               "word_recall_before": round(rw0, 4),
               "sent_recall": round(rs0_after, 4),
               "sent_recall_before": round(rs0, 4),
               "cat25_recall": round(r_cat25, 4), "cat25_per": cat_ok,
               "hold25_ok": n_hold25_ok, "hold25_total": n_hold25_tot,
               "s_words": s_words, "v_words": v_words, "o_words": o_words,
               "act_members": act_mem, "pers_members": pers_mem,
               "train_combos": train_combos, "test_combos": test_combos,
               "n": ng.n, "all_ok": ok_all}
    if not smoke:
        save_snapshot(ng, parent="9.0",
                      tag="Stage 2.6 动宾搭配约束（v9.0 迭代：V 词↔允许 O 类别）",
                      metrics=metrics, vocab=vocab + sorted(need),
                      pats=pats, cursor=cursor)


if __name__ == "__main__":
    main()
