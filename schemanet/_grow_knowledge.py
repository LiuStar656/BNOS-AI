# -*- coding: utf-8 -*-
"""基本常识课程落地（2026-08-11，用户："设计教学，从教基本常识开始，
对标盲人自闭症儿童"——只能听和说，盲童听觉/语言通道代偿认知）。

课程（[PLAN]-盲人自闭症儿童基本常识课程）：
  A1 感知方式：耳朵听声音 / 手摸东西（盲童代偿认知方式本身）
  B1 起床流程：早上起床 → 洗手 → 刷牙 → 吃饭（生活序列语言化）
  B3 睡前流程：晚上吃饭 → 洗澡 → 睡觉
  B4 穿衣：冷了穿衣服 / 热了脱衣服
  C3 生病因果：生病了要吃药 / 生病了要看医生
  D1 危险物品：不能摸火 / 不能摸热水（烫）
  D2 交通：过马路看车
教学 = 常识链跟读 ×R + chain_read 验收（教了什么会什么）；
教学后的常识链进 teach_out → 自由运行中网络可自己冒出常识念头。

加载 v30.1 → 快照 v31.0。用法：python _grow_knowledge.py
"""

import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot

RUNS_DIR = Path(__file__).parent / "runs"
R = 6

# 常识链：[句名, tokens]（全词表内，已查证——"洗脸"拆 洗+脸）
LESSONS = [
    # A1 感知方式（盲童代偿认知）
    ("耳朵听声音", ["耳朵", "听", "声音"]),
    ("手摸东西", ["手", "摸", "东西"]),
    ("眼睛看东西", ["眼睛", "看", "东西"]),
    # B1 起床流程
    ("早上起床洗手刷牙吃饭", ["早上", "起床", "洗", "手", "刷牙", "吃", "饭"]),
    # B3 睡前流程
    ("晚上吃饭洗澡睡觉", ["晚上", "吃", "饭", "洗澡", "睡觉"]),
    # B4 穿衣
    ("热了脱衣服", ["热", "了", "脱", "衣服"]),
    # C3 生病因果
    ("生病了要吃药", ["生病", "了", "要", "吃", "药"]),
    ("生病了要看医生", ["生病", "了", "要", "看医生"]),
    # D1 危险物品
    ("不能摸火", ["不", "能", "摸", "火"]),
    ("不能摸热水", ["不", "能", "摸", "热水"]),
    # D2 交通
    ("过马路看车", ["过", "马路", "看", "车"]),
]

# 验收题：[(句, front, back)]
CHECKS = [
    ("耳朵听声音", ["耳朵"], ["听", "声音"]),
    ("手摸东西", ["手"], ["摸", "东西"]),
    ("早上起床洗手刷牙吃饭", ["早上"], ["起床", "洗", "手", "刷牙", "吃", "饭"]),
    ("晚上吃饭洗澡睡觉", ["晚上"], ["吃", "饭", "洗澡", "睡觉"]),
    ("热了脱衣服", ["热"], ["了", "脱", "衣服"]),
    ("生病了要吃药", ["生病"], ["了", "要", "吃", "药"]),
    ("不能摸火", ["不"], ["能", "摸", "火"]),
    ("不能摸热水", ["不"], ["能", "摸", "热水"]),
    ("过马路看车", ["过", "马路"], ["看", "车"]),
]


def main():
    from _exam_big import chain_read
    t0 = time.time()
    print("═══ 基本常识课程（盲人自闭症儿童·只能听和说）═══\n")
    ng, vocab, pats, cursor = load_version("30.1")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    missing = {w for _, toks in LESSONS for w in toks if w not in keys}
    print(f"[词表] {len(keys)} 词；课程词表外：{missing or '无'}")

    # 教学：常识链跟读 ×R
    for name, toks in LESSONS:
        for _ in range(R):
            _learn_sentence(ng, toks, pats, slot=0)
    print(f"[教学] {len(LESSONS)} 条常识链 ×{R} 轮\n")

    # 验收：chain_read（教了什么会什么）
    n_hit = n_tot = 0
    for name, front, back in CHECKS:
        read, brk = chain_read(ng, pats, n2w, front, back)
        ok = read == back
        n_tot += 1
        n_hit += ok
        print(f"  {'✅' if ok else '✗'}「{name}」→ "
              f"「{'/'.join(read) or '∅'}」"
              f"{'  [断:' + '→'.join(map(str, brk)) + ']' if brk else ''}")
    print(f"\n[验收] {n_hit}/{n_tot}")

    save_snapshot(ng, parent="30.1",
                  tag="基本常识课程：A1 感知方式 + B1/B3 生活流程 + "
                      "B4 穿衣 + C3 生病 + D1 危险 + D2 交通（盲童"
                      "听觉代偿，只能听和说）",
                  metrics={"lessons": len(LESSONS),
                           "checks": {"hit": n_hit, "tot": n_tot}},
                  vocab=vocab, pats=pats, cursor=cursor)
    print(f"[完成] v31.0 已存（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
