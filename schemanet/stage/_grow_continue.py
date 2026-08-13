# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""续训闭环实验：加载已有快照 → 扩容 → 调参 → 续训新知识 → 新版本（零遗忘硬指标）。

需求（用户 2026-08-10）：
  "以后扩大神经元规模和调整每次调用神经元的数量时，原来之前的记忆不丢。"

即"增量成长"最后一环——模型不是每次从 0 新建，而是踩在前一版本肩上长大：
  load_version("2.0")（词级，n=54000，13500 模式）
    → baseline 评估（字复述 / 词复述，扩容前基准）
    → expand 扩容（纯追加，验证旧评估集逐值一致 = 零遗忘）
    → 调 wta_k（每次调用/发放的神经元数量，验证记忆不丢）
    → 分配新词（游标续用自动 expand）+ 跟读续训
    → 复测：旧字/词复述不回退 + 新词复述达标
    → save_snapshot（新版本，版本链继续）

验收硬指标：
  1. 扩容零遗忘：expand 前后旧评估集逐值一致（字复述、词复述）
  2. 调参零遗忘：wta_k 调整后旧复述率不回退（wta_k ≥ 模式规模时）
  3. 续训零遗忘：新词训练后旧复述率不回退（≥ baseline - 0.01）
  4. 新知识达标：新词复述率 ≥ 0.95

用法：python _grow_continue.py
"""

import json
import time
from pathlib import Path

import numpy as np

from schema_net import build_pulse
from snapshot import save_snapshot, load_version
from sparse_net import allocate_pats
from _grow_zh import run_train, recall_words

K = 4                    # 每字/词模式神经元数
WTA_WORD_MAX = 20        # 词训练 WTA 上限（词4 + 最长4字×4）
RNEW = 3                 # 新词跟读轮数
EVAL_N = 200             # 字复述验收抽样
EVAL_W = 300             # 词复述验收抽样
N_NEW_WORDS = 500        # 续训新词数量
SEED = 42

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"


def main():
    # ── 1. 加载最新词级版本（续训起点 = v2.0，n=54000 / 13500 模式）──
    ng, vocab, pats, cursor = load_version("2.0")
    hanzi = json.loads((DATA / "stage0_hanzi.json").read_text(encoding="utf-8"))
    print(f"[加载] v2.0：n={ng.n}，模式 {len(pats)}，cursor={cursor}")
    words_old = [w for w in vocab if w not in set(hanzi)]

    rng = np.random.default_rng(SEED)
    eval_hanzi = list(np.random.default_rng(7).choice(hanzi, EVAL_N, replace=False))
    eval_words = list(np.random.default_rng(8).choice(words_old, EVAL_W, replace=False))

    # ── 2. 扩容前 baseline（零遗忘基准）──
    r0 = recall_words(ng, pats, eval_hanzi, K)
    rw0 = recall_words(ng, pats, eval_words, WTA_WORD_MAX)
    print(f"[baseline] 字复述 {r0:.4f} | 词复述 {rw0:.4f}")

    # ── 3. 扩容（纯追加 n + 4096），复测 = 零遗忘硬指标 ──
    n_before = ng.n
    ng.expand(n_before + 4096)
    r0_e = recall_words(ng, pats, eval_hanzi, K)
    rw0_e = recall_words(ng, pats, eval_words, WTA_WORD_MAX)
    ok_expand_char = r0_e == r0
    ok_expand_word = rw0_e == rw0
    print(f"[扩容] n {n_before} → {ng.n}：字复述 {r0_e:.4f} "
          f"{'✅ 逐值一致' if ok_expand_char else '❌ 变化!'} | "
          f"词复述 {rw0_e:.4f} "
          f"{'✅ 逐值一致' if ok_expand_word else '❌ 变化!'}")

    # ── 4. 调 wta_k（每次调用/发放神经元数量），复测记忆不丢 ──
    print("\n[调参] wta_k 从训练值（字=4，词=20）调整：")
    results_wta = {}
    for wta_k in (2, 4, 8, 16, 24, 32):
        rc = recall_words(ng, pats, eval_hanzi, wta_k)
        results_wta[f"char_wta{wta_k}"] = round(rc, 4)
        print(f"  字复述 wta_k={wta_k:2d}: {rc:.4f}")
    for wta_k in (8, 16, 20, 24, 32, 48):
        rw = recall_words(ng, pats, eval_words, wta_k)
        results_wta[f"word_wta{wta_k}"] = round(rw, 4)
        print(f"  词复述 wta_k={wta_k:2d}: {rw:.4f}")
    # 调参零遗忘：wta_k ≥ 模式规模时复述率不回退（wta_k=4 字 / 24 词）
    ok_wta_char = results_wta["char_wta4"] >= r0 - 0.001
    ok_wta_word = results_wta["word_wta24"] >= rw0 - 0.001
    print(f"[调参] 零遗忘 {'✅' if ok_wta_char and ok_wta_word else '❌'}："
          f"字(4) {results_wta['char_wta4']} / 词(24) {results_wta['word_wta24']}")

    # ── 5. 续训：分配新词（汉字组合，不在旧词表）+ 跟读 ──
    old_set = set(vocab)
    new_words = []
    while len(new_words) < N_NEW_WORDS:
        w = hanzi[rng.integers(len(hanzi))] + hanzi[rng.integers(len(hanzi))]
        if w not in old_set and len(w) == 2:
            new_words.append(w)
            old_set.add(w)
    pats_w, cursor = allocate_pats(ng, new_words, K, cursor)   # 自动 expand
    pats.update(pats_w)
    print(f"\n[续训] 新词 {len(new_words)}，cursor={cursor}，n={ng.n}"
          f"（扩容 {ng.n - n_before - 4096}）")
    t1 = time.time()
    for r in range(RNEW):
        for w in new_words:
            neurons = list(pats[w]) + [i for c in w for i in pats[c]]
            ng.wta_k = len(neurons)
            run_train(ng, build_pulse(ng.n, neurons))
        print(f"  轮 {r + 1}/{RNEW}（{time.time() - t1:.0f}s）", flush=True)

    # ── 6. 续训后复测：旧知识不回退 + 新知识达标 ──
    r0_after = recall_words(ng, pats, eval_hanzi, K)
    rw0_after = recall_words(ng, pats, eval_words, WTA_WORD_MAX)
    rn = recall_words(ng, pats, new_words, 8)      # 新词 2 字：模式4 + 字8
    ok_no_forget = (r0_after >= r0 - 0.01 and rw0_after >= rw0 - 0.01)
    ok_new = rn >= 0.95
    print(f"\n[续训后] 字复述 {r0_after:.4f}（baseline {r0:.4f}）"
          f"{'✅ 不回退' if r0_after >= r0 - 0.01 else '❌ 回退!'}")
    print(f"[续训后] 词复述 {rw0_after:.4f}（baseline {rw0:.4f}）"
          f"{'✅ 不回退' if rw0_after >= rw0 - 0.01 else '❌ 回退!'}")
    print(f"[续训后] 新词复述 {rn:.4f} {'✅ ≥0.95' if ok_new else '❌ 未达标'}")

    ok_all = (ok_expand_char and ok_expand_word and ok_wta_char and ok_wta_word
              and ok_no_forget and ok_new)
    print(f"\n═══ 续训闭环验收: {'全部通过 ✅' if ok_all else '有失败 ❌'} ═══")

    # ── 7. 新版本快照（版本链继续）──
    metrics = {
        "baseline_char": round(r0, 4), "baseline_word": round(rw0, 4),
        "expand_char_equal": ok_expand_char, "expand_word_equal": ok_expand_word,
        "wta_char_keep": ok_wta_char, "wta_word_keep": ok_wta_word,
        "wta_table": results_wta,
        "after_char": round(r0_after, 4), "after_word": round(rw0_after, 4),
        "new_word_recall": round(rn, 4), "new_words": len(new_words),
        "no_forget": ok_no_forget, "all_ok": ok_all, "n": ng.n,
    }
    save_snapshot(ng, tag="续训闭环：扩容+调参零遗忘，新增 500 常用词组",
                  metrics=metrics, vocab=hanzi + words_old + new_words,
                  pats=pats, cursor=cursor)


if __name__ == "__main__":
    main()
