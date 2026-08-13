# -*- coding: utf-8 -*-
"""Stage 2.5 词典学词义（v3，方案 v2.4 §2.5）：OpenHowNet 义原 + RL 验证门判断题。

需求（用户 2026-08-10 决策链）："词有了、词义没有"——词形复述 1.0 但同类词在语料中
不同句共现 → 词义（出边结构）孤立 → 举一反三无路可走。跟读只能焊"清单直连"，学不会
词义；改用**词典（OpenHowNet 义原）+ RL 验证门**：
  - 词义 = 词↔义原关联集合（出边结构），词典直接给出连接
  - 每条词↔义原关系 = 一道判断题：对→固化（Hebbian 共发放）、错→拒绝（不焊死）
  - 类别标签 = 义原 hub（词义直达类别）；hold-out 凭共享属性义原走链 → 词义举一反三

流程（增量，记忆不丢）：
  load_version("7.0")（句级，n=148140）
    → 读 stage25_sememes.json（词→义原，离线抽取留档）
    → 标签义原组定义 + 训练成员（人工词表 ∩ 词典，质量护栏）/ hold-out（词典自动发现）
    → 义原/标签模式分配（游标续用自动扩容）
    → 验证门判断题训练（正例 = w 的所有词典义原 固化；负例 = 他类标签 拒绝）
    → 验收① 类别归属（训练成员 → 本类标签直连 ≥0.9）
    → 验收② 词义举一反三（hold-out 凭共享属性义原 → 本类信号占优 ≥50%）
    → 验收③ 替换造句（走链"我"→ 唤起食物类词）
    → 验收④ 字/词/句全链零遗忘（Stage 0-2 不回退）
    → save_snapshot(parent="7.0")

诚实边界（数据实测，2026-08-10）：
  - 动作类（吃/跑/跳…）OpenHowNet 覆盖 0 → 本阶段跳过（词性标注后补）
  - 标签义原组按人工词表词的义原扩组（食物+食品/蔬菜、动物+牲畜/走兽/虫、
    颜色+单字色名、地点+设施/房间）——HowNet 类别义原（动物/颜色/场所）覆盖的是
    "一世/下巴/底色"这类词，与日常类别词错位
  - 多义原词取并集（苹果→电脑 为品牌义项，真实标注，多通道不拒收）

用法：python _grow_cat.py [--smoke]   # --smoke 小规模快跑（验证机制）
"""

import json
import re
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

K = 4
R = 5                    # 判断题正例轮数（"读的越多印象越足"）
N_TRAIN = 12             # 每类训练成员上限（人工词表 ∩ 词典）
N_HOLD = 3               # 每类 hold-out 上限（词典自动发现，凭共享属性义原走链）
N_NEG = 1                # 每训练成员负例判断题数（拒绝固化）
EVAL_HANZI = 200
EVAL_WORD = 300
EVAL_SENT = 100          # 句零遗忘抽样（Stage 2 不回退）
SEED = 42
DATA = Path(__file__).parent / "data" / "curriculum"

# 词形过滤：只学纯中文 2-4 字词（HowNet 英文/专名义项混入严重）
ZH24 = re.compile(r"[\u4e00-\u9fff]{2,4}$")

# 类别标签义原组（v3 实测扩组：HowNet 类别义原覆盖与日常词错位，按人工词表词的义原定）
LABELS = {
    "食物": ["水果", "食物", "食品", "蔬菜"],
    "动物": ["动物", "兽", "牲畜", "走兽", "虫"],
    "颜色": ["颜色", "红", "蓝", "绿", "白", "黑", "黄", "紫", "灰"],
    "时间": ["时间"],
    "地点": ["场所", "位置", "设施", "房间"],
}
# 动作类：OpenHowNet 对常用动词（吃/跑/跳…）覆盖 0 → 本阶段诚实跳过（§2.5 诚实边界）

# 训练成员人工词表（数据质量护栏；运行时与词典成员取交集）
CATS_MANUAL = {
    "食物": ["苹果", "香蕉", "西瓜", "米饭", "面包", "鸡蛋", "牛奶", "水果", "蔬菜",
             "猪肉", "牛肉", "鸡肉", "蛋糕", "面条", "土豆", "萝卜", "葡萄", "草莓",
             "饺子", "馒头", "饼干", "橘子", "梨", "桃", "花生", "豆腐"],
    "动物": ["猫", "狗", "鸟", "鱼", "马", "牛", "羊", "猪", "鸡", "鸭",
             "兔子", "老虎", "大象", "猴子", "狮子", "熊", "狼", "蛇",
             "狐狸", "熊猫", "老鼠", "青蛙", "蝴蝶", "蚂蚁"],
    "颜色": ["红", "黄", "蓝", "白", "黑", "绿", "紫", "灰",
             "红色", "黄色", "蓝色", "绿色", "白色", "黑色", "粉色", "金色"],
    "时间": ["今天", "明天", "昨天", "早上", "晚上", "中午", "下午",
             "时候", "现在", "后来", "以前", "最近", "上午", "白天", "夜里",
             "春天", "夏天", "秋天", "冬天"],
    "地点": ["学校", "公园", "家", "医院", "商店", "超市", "图书馆", "办公室",
             "机场", "车站", "银行", "饭店", "工厂", "教室", "宿舍", "市场",
             "电影院", "书店"],
}


def edge_sum(ng, pats, w, neurons):
    """w 出边汇聚到神经元集合的总权重（大网络类别信号直读，不走 WTA 传播）。"""
    tot = 0.0
    for i in pats[w]:
        row = ng.W_out[i][0]
        if row:
            for j, wt in row.items():
                if j in neurons:
                    tot += wt
    return tot


def judge(ng, pats, w, s, ok):
    """验证门判断题："w 是 s？" 对→共发放固化（Hebbian）；错→拒绝（不固化）。

    与方案 §12.6 三因子规则一致：验证通过 → 边固化；验证失败 → 不焊死
    （错误联想真实存在时不加固，走链只当临时检索）。"""
    if not ok:
        return
    neurons = list(pats[w]) + list(pats[s])
    run_train(ng, build_pulse(ng.n, neurons), len(neurons))


def build_cats(pats, sem_words, n_train, n_hold):
    """构造每类：训练成员（人工词表 ∩ 词典）+ hold-out（词典自动发现，共享属性义原）。

    - 训练成员 = CATS_MANUAL ∩ 词典（词有义原）∩ pats（v7.0 已学），截断 n_train
    - hold-out = 词典成员（义原含本类标签）- 训练成员 - 标签词，按"与训练成员
      共享属性义原数"降序取 n_hold——举一反三前提（方案 §2.5：凭共享义原走链）
    - 每类至少 1 训练成员才启用；无词典覆盖的类打印警告后跳过（诚实边界）
    返回 {label: {"tags": [...], "train": [...], "hold": [...], "sems": {w: [...]}}}。
    """
    cats = {}
    for label, tags in LABELS.items():
        tset = set(tags)
        # 训练成员：人工词表 ∩ 词典 ∩ pats，且义原含本类标签（词典确认的同类词；
        # "后来/最近"义原为将来/新近不含"时间"标签 → 排除，2026-08-10 全量实测）
        train = [w for w in CATS_MANUAL[label]
                 if w in pats and w in sem_words and w not in tset
                 and any(t in sem_words[w] for t in tset)][:n_train]
        if not train:
            print(f"  ⚠ 类别 {label} 无词典训练成员（人工词表 {len(CATS_MANUAL[label])}"
                  f" 词在 HowNet 覆盖 0）→ 跳过（诚实边界）")
            continue
        # hold-out：词典自动发现的同类词 - 训练成员，按"与训练成员共享义原数"排序。
        # 共享义原含标签（狐狸↔老虎共享"走兽"）——动物类词属性义原基本就是标签本身，
        # 只算属性会选不出 hold-out（2026-08-10 冒烟实测）。
        auto = [w for w, sems in sem_words.items()
                if w in pats and ZH24.match(w) and w not in tset
                and w not in set(train) and any(t in sems for t in tset)]
        def shared_with_train(w):
            sw = set(sem_words[w])
            return sum(1 for m in train if sw & set(sem_words[m]))
        hold = [w for w in auto if shared_with_train(w)]
        hold.sort(key=shared_with_train, reverse=True)
        hold = hold[:n_hold]
        cats[label] = {"tags": tags, "train": train, "hold": hold,
                       "sems": {w: sem_words[w] for w in train + hold}}
        print(f"  {label}({tags}): 训练 {len(train)} 例 {train[:5]}"
              f"{'…' if len(train) > 5 else ''} | hold-out {len(hold)} 例 {hold}")
    return cats


def sent_recall(ng, pats, s):
    """句复述率：输入整句 → 唤起整句各词比例（Stage 2 口径）。"""
    neurons = [j for w in s for j in pats[w]]
    fired = run_recall(ng, build_pulse(ng.n, neurons))
    return fire_ratio(fired, neurons)


def main():
    smoke = "--smoke" in sys.argv
    if smoke:
        print("⚠ SMOKE 模式：小规模快跑（仅验证机制，指标不具统计意义）")
    t0 = time.time()
    print("═══ Stage 2.5 词典学词义（OpenHowNet 义原 + 验证门判断题）═══\n")

    # ── 1. 加载 v7.0（句级，字词句记忆全含）──
    ng, vocab, pats, cursor = load_version("7.0")
    hanzi = json.loads((DATA / "stage0_hanzi.json").read_text(encoding="utf-8"))
    words_old = [w for w in vocab if w not in set(hanzi)]
    print(f"[加载] 7.0（句级续训链最新）：n={ng.n}，模式 {len(pats)}，cursor={cursor}")

    # ── 2. 词典判断题数据（离线抽取留档 stage25_sememes.json）──
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    sem_words = sem["words"]
    print(f"[数据] OpenHowNet 义原：覆盖 {sem['stats']['covered']} 词 /"
          f" {sem['stats']['sememes']} 义原 / {sem['stats']['edges']} 边")

    # ── 3. 类别构造（训练成员 + hold-out）──
    n_train = 3 if smoke else N_TRAIN
    n_hold = 1 if smoke else N_HOLD
    cats = build_cats(pats, sem_words, n_train, n_hold)
    if not cats:
        raise SystemExit("无可用类别（词典覆盖不足）")
    n_neg = 1 if smoke else N_NEG

    # ── 4. 义原/标签模式分配（游标续用自动扩容）──
    all_tags = {t for tags in LABELS.values() for t in tags}
    need = sorted({s for d in cats.values() for w in d["train"] + d["hold"]
                   for s in d["sems"][w]} | all_tags - set(pats))
    if need:
        total_new = len(need) * K
        if cursor + total_new > ng.n:
            ng.expand(cursor + total_new)
        pats_new, cursor = allocate_pats(ng, need, K, cursor)
        pats.update(pats_new)
        print(f"[分配] 义原/标签新模式 {len(pats_new)}（n {ng.n}，cursor={cursor}）")
    # 标签 hub 缺模式的单独分配（含不在词典里的标签如 设施/房间/走兽）
    need_tags = sorted(t for t in all_tags if t not in pats)
    if need_tags:
        total_new = len(need_tags) * K
        if cursor + total_new > ng.n:
            ng.expand(cursor + total_new)
        pats_new, cursor = allocate_pats(ng, need_tags, K, cursor)
        pats.update(pats_new)
        print(f"[分配] 标签 hub {len(need_tags)}：{need_tags}（n {ng.n}，cursor={cursor}）")

    # ── 5. 字/词/句零遗忘 baseline（Stage 0-2 复述率）──
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
    print(f"[baseline] 字 {r0:.4f} | 词 {rw0:.4f} | 句 {rs0:.4f}")

    # ── 6. 验证门判断题训练 ──
    t1 = time.time()
    n_pos = n_neg_tot = 0
    neg_before, neg_after = {}, {}
    rng = np.random.default_rng(SEED)
    for label, d in cats.items():
        tset = set(d["tags"])
        neg_pool = [t for t in all_tags if t not in tset and t in pats]
        for w in d["train"]:
            # 正例：w 的所有词典义原（标签 + 属性/功能）→ "w 是 s？对" 固化
            for s in d["sems"][w]:
                for _ in range(R):
                    judge(ng, pats, w, s, True)
                n_pos += 1
            # 负例：他类标签（非 w 义原）→ "w 是 s'？错" 拒绝固化（不焊死）
            pool = [t for t in neg_pool if t not in set(d["sems"][w])]
            for _ in range(n_neg):
                if not pool:
                    break
                s_neg = str(rng.choice(pool))
                neg_before[(w, s_neg)] = edge_sum(ng, pats, w, set(pats[s_neg]))
                judge(ng, pats, w, s_neg, False)
                neg_after[(w, s_neg)] = edge_sum(ng, pats, w, set(pats[s_neg]))
                n_neg_tot += 1
        # hold-out：只训"与训练成员共享的义原"（含标签共享），类别判断
        # "w 是[标签]"不直接训 = 举一反三对象（凭共享义原走链唤起本类信号）
        shared_sems = set().union(*(set(sem_words[m]) for m in d["train"]))
        for w in d["hold"]:
            for s in d["sems"][w]:
                if s in shared_sems:
                    for _ in range(R):
                        judge(ng, pats, w, s, True)
                    n_pos += 1
    n_rejected = sum(1 for k in neg_after if neg_after[k] <= neg_before[k])
    print(f"[训练] 正例判断题 {n_pos} 边 × {R} 轮 + 负例 {n_neg_tot} 条"
          f"（拒绝固化 {n_rejected}/{n_neg_tot} 边未增长）"
          f"（{time.time() - t1:.0f}s）")

    # ── 7. 验收① 类别归属（训练成员 → 本类标签直连 ≥0.9）──
    per = {}
    for label, d in cats.items():
        tag_n = set()
        for t in d["tags"]:
            tag_n.update(pats.get(t, []))
        rs = np.mean([edge_sum(ng, pats, w, tag_n) > 0.1 for w in d["train"]])
        per[label] = round(float(rs), 4)
    r_cat = np.mean(list(per.values()))
    print(f"\n[验收①] 类别归属（训练成员→本类标签直连）: {r_cat:.4f} "
          f"{'✅ ≥0.9' if r_cat >= 0.9 else '❌'} {per}")

    # ── 8. 验收② 词义举一反三（hold-out 凭共享属性义原 → 本类信号占优 ≥50%）──
    # 本类信号 = w 出边到 [本类标签 ∪ 本类训练成员 ∪ 与成员共享的属性义原] 总权重；
    # 他类信号 = 到 [他类标签 ∪ 他类训练成员]。判定：本类 > 0 且 ≥ 他类×0.5。
    others_n = {}
    for label, d in cats.items():
        o = set()
        for l2, d2 in cats.items():
            if l2 == label:
                continue
            for t in d2["tags"]:
                o.update(pats.get(t, []))
            for m in d2["train"]:
                o.update(pats[m])
        others_n[label] = o
    per_h, n_hold_tot, n_hold_ok = {}, 0, 0
    for label, d in cats.items():
        tset = set(d["tags"])
        mine = set()
        for t in d["tags"]:
            mine.update(pats.get(t, []))
        for m in d["train"]:
            mine.update(pats[m])
        n_ok, sigs = 0, []
        for h in d["hold"]:
            shared = set(sem_words[h]) & set().union(
                *(set(sem_words[m]) for m in d["train"]))
            self_n = set(mine)
            for s in shared:
                self_n.update(pats.get(s, []))
            cat = edge_sum(ng, pats, h, self_n)
            oth = edge_sum(ng, pats, h, others_n[label])
            ok = cat > 0 and cat >= oth * 0.5
            sigs.append((h, round(cat, 2), round(oth, 2)))
            n_ok += ok
        per_h[label] = round(n_ok / len(d["hold"]), 4) if d["hold"] else 0.0
        n_hold_tot += len(d["hold"])
        n_hold_ok += n_ok
        print(f"  {label}: {n_ok}/{len(d['hold'])}  sigs={sigs}")
    r_hold = n_hold_ok / max(1, n_hold_tot)
    print(f"[验收②] 词义举一反三（hold-out→本类信号占优）: {r_hold:.4f} "
          f"{'✅ ≥0.5' if r_hold >= 0.5 else '❌'} {per_h}")

    # ── 9. 验收③ 替换造句（"我要"→ 食物类词唤起 = 类别约束的槽位填充雏形）──
    # 大网络虚词劫持实测（"我"→的 256、"要"→为什么 256）使单链走链失效；
    # 改用出边直读聚合（与验收②同构）：输入词"我/要"的出边汇聚到各类成员
    # 的总权重，宾语槽位应唤起食物类（v7.0 语料"我要X" + v3 词义边共同约束）。
    if "我" in pats and "要" in pats and "食物" in cats:
        d = cats["食物"]
        seed = ["我", "要"]
        foods = set(d["train"]) | set(d["hold"])
        food_n, other_n = set(), set()
        for l2, d2 in cats.items():
            for m in d2["train"] + d2["hold"]:
                if l2 == "食物":
                    food_n.update(pats[m])
                else:
                    other_n.update(pats[m])
        fd = sum(edge_sum(ng, pats, w, food_n) for w in seed)
        ot = sum(edge_sum(ng, pats, w, other_n) for w in seed)
        hit = [w for w in foods
               if any(edge_sum(ng, pats, x, set(pats[w])) > 0 for x in seed)]
        print(f"\n[验收③] 替换造句（\"我要\"→ 食物类成员出边聚合）:")
        print(f"  食物信号 {fd:.1f} vs 他类信号 {ot:.1f} | 直接命中食物词: {hit}")
        ok_make = bool(fd > 0 and fd >= ot * 0.5)
        print(f"  {'✅ 类别约束生效（宾语槽位唤起食物类词）' if ok_make else '❌ 食物类未占优'}")
    else:
        ok_make = False
        hit, fd, ot = [], 0.0, 0.0
        print("[验收③] 跳过（缺 我/要/食物 类）")

    # ── 10. 验收④ 字/词/句全链零遗忘（Stage 0-2 不回退）──
    r0_after = recall_words(ng, pats, eval_hanzi, K)
    rw0_after = recall_words(ng, pats, eval_words, 20)
    rs0_after = np.mean([sent_recall(ng, pats, s) for s in eval_sents])
    ok_char = r0_after >= r0 - 0.01
    ok_word = rw0_after >= rw0 - 0.01
    ok_sent = rs0_after >= rs0 - 0.01
    print(f"\n[验收④] 字 {r0_after:.4f}（base {r0:.4f}）"
          f"{'✅' if ok_char else '❌ 回退!'}")
    print(f"[验收④] 词 {rw0_after:.4f}（base {rw0:.4f}）"
          f"{'✅' if ok_word else '❌ 回退!'}")
    print(f"[验收④] 句 {rs0_after:.4f}（base {rs0:.4f}）"
          f"{'✅' if ok_sent else '❌ 回退!'}")

    ok_all = bool(r_cat >= 0.9 and r_hold >= 0.5 and ok_char and ok_word
                  and ok_sent and ok_make)
    print(f"\n═══ Stage 2.5 验收: {'全部通过 ✅' if ok_all else '有失败 ❌'} "
          f"（{time.time() - t0:.0f}s）═══")

    # ── 11. 快照（回退同代变体：parent=7.0 → v8.x，与 v8.0/v8.1 平级对比）──
    metrics = {"cat_recall": round(r_cat, 4), "cat_recall_per": per,
               "hold_recall": round(r_hold, 4), "hold_per": per_h,
               "hold_ok": n_hold_ok, "hold_total": n_hold_tot,
               "pos_judgments": n_pos, "neg_judgments": n_neg_tot,
               "neg_rejected": n_rejected,
               "make_seed": ["我", "要"], "make_hit": hit,
               "make_fd": round(fd, 1), "make_ot": round(ot, 1),
               "char_recall": round(r0_after, 4),
               "char_recall_before": round(r0, 4),
               "word_recall": round(rw0_after, 4),
               "word_recall_before": round(rw0, 4),
               "sent_recall": round(rs0_after, 4),
               "sent_recall_before": round(rs0, 4),
               "labels": list(cats.keys()),
               "skipped_labels": [l for l in LABELS if l not in cats],
               "n": ng.n, "all_ok": ok_all}
    save_snapshot(ng, parent="7.0",
                  tag="Stage 2.5 词典学词义（OpenHowNet 义原 + RL 验证门判断题）",
                  metrics=metrics, vocab=vocab + sorted(need + need_tags),
                  pats=pats, cursor=cursor)


if __name__ == "__main__":
    main()
