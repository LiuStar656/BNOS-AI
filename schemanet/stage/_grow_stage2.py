# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""Stage 2 句级增量成长：短句跟读，学"句内结构"（先学字、再学词、再学句）。

需求（用户 2026-08-09 + 2026-08-10 逐步推进）：成长路线 Stage 2 短句级——
句内结构（主谓宾），整句跟读，验收句复述率 ≥0.95 + 前级零遗忘。

与 Stage 0-1 的连续（同一网络增量成长）：
  load_version("2.0")           # 词级网络（n=54000，13500 模式）
    → 句中新词增量分配（游标续用自动扩容，23035 新词）
    → 短句跟读（注入 句中各词模式 → 句内词间连接）
    → 验收：句复述率 / 前缀唤起（像"人之初→性本善"的句子级）
    → 字/词零遗忘（Stage 0-1 复述不回退）
    → save_snapshot（Stage 2 版本）

验收硬指标（方案 §四 Stage 2）：
  1. 句复述率（输入整句 → 唤起整句各词）≥ 0.95
  2. 前缀唤起（输入前 2 词 → 唤起后续词）> 0（句内结构 = 局部触发整块唤起）
  3. 字/词零遗忘：Stage 0-1 复述率不回退（≥ baseline - 0.01）

用法：python _grow_stage2.py [--smoke]   # --smoke 小规模冒烟（快跑通，验证机制）
"""

import os
import sys
# 禁多线程 BLAS/OpenMP（Windows 上 numpy 多线程偶发死锁，CPU≈0 卡死），须在 import numpy 前
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import json
import time
from pathlib import Path

import numpy as np

from schema_net import build_pulse
from snapshot import save_snapshot, load_version
from sparse_net import allocate_pats
from _grow_zh import run_train, run_recall, recall_words, fire_ratio

K = 4
EVAL_N = 500           # 句验收抽样
EVAL_HANZI = 200       # 字零遗忘抽样
EVAL_WORD = 300        # 词零遗忘抽样
R = 3                  # 句跟读轮数
SEED = 42
DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"


def train_sent(ng, neurons):
    """跟读一句：原地清零状态（省分配）+ 注入句中各词模式共发放即学。

    与 run_train 语义一致（不传播、清 trace），仅用原地清零避免每句
    重复分配 O(n) 数组（全量 88500 句 × n=147100 的分配是主要开销）。
    """
    ng.v[:] = 0.0
    ng.spikes[:] = 0.0
    ng.pre_trace[:] = 0.0
    ng.step(build_pulse(ng.n, neurons), slot=0)


def main():
    smoke = "--smoke" in sys.argv
    if smoke:
        print("⚠ SMOKE 模式：小规模快跑（仅验证机制，指标不具统计意义）")
    t0 = time.time()
    print("═══ Stage 2 句级增量成长（短句跟读，句内结构）═══\n")

    # ── 1. 加载最新词级网络（增量起点：6.0 = 2.0 续训链的最新，记忆全含）──
    ng, vocab, pats, cursor = load_version("6.0")
    hanzi = json.loads((DATA / "stage0_hanzi.json").read_text(encoding="utf-8"))
    words_old = [w for w in vocab if w not in set(hanzi)]
    print(f"[加载] 6.0（词级续训链最新）：n={ng.n}，模式 {len(pats)}，cursor={cursor}")

    # ── 2. 短句数据（Stage 2 专门数据：≤8 词无 UNK 短句）──
    sents = json.loads((DATA / "stage2_sents.json").read_text(encoding="utf-8"))
    n_eval = 100 if smoke else EVAL_N
    rounds = 1 if smoke else R
    rng = np.random.default_rng(SEED)
    idx = rng.choice(len(sents), n_eval, replace=False)
    eval_sents = [sents[i] for i in idx]
    train_sents = [s for i, s in enumerate(sents) if i not in set(idx)]
    if smoke:
        train_sents = train_sents[:3000]
    print(f"[数据] 短句 {len(sents)}（抽样验收 {len(eval_sents)}，训练 {len(train_sents)}，"
          f"轮数 {rounds}）")

    # ── 3. 句中未覆盖词增量分配（自动扩容，覆盖训练+验收全部句子）──
    need = sorted({w for s in train_sents + eval_sents for w in s if w not in pats})
    total_new = len(need) * K
    if cursor + total_new > ng.n:
        ng.expand(cursor + total_new)      # 一次性扩容（避免逐词 expand 的 O(n²)）
    pats_new, cursor = allocate_pats(ng, need, K, cursor)
    pats.update(pats_new)
    print(f"[增量] 句中新词分配 {len(pats_new)}（n {ng.n} → 自动扩容），"
          f"cursor={cursor}")

    # ── 4. 字/词零遗忘 baseline（Stage 0-1 复述率）──
    rng7 = np.random.default_rng(7)
    eval_hanzi = list(rng7.choice(hanzi, EVAL_HANZI, replace=False))
    rng8 = np.random.default_rng(8)
    eval_words = list(rng8.choice(words_old, EVAL_WORD, replace=False))
    r0 = recall_words(ng, pats, eval_hanzi, K)
    rw0 = recall_words(ng, pats, eval_words, 20)
    print(f"[baseline] 字复述 {r0:.4f} | 词复述 {rw0:.4f}")

    # ── 5. 短句跟读（整句注入：句中各词模式共发放 → 句内词间连接）──
    t1 = time.time()
    for r in range(rounds):
        for i, s in enumerate(train_sents):
            neurons = [j for w in s for j in pats[w]]
            ng.wta_k = len(neurons)          # 句训练：WTA = 句内目标数（防级联）
            train_sent(ng, neurons)
            if (i + 1) % 5000 == 0:
                print(f"    句 {i + 1}/{len(train_sents)}"
                      f"（{time.time() - t1:.0f}s）", flush=True)
        print(f"  轮 {r + 1}/{rounds} 完成（{time.time() - t1:.0f}s）", flush=True)

    # ── 6. 验收①：句复述率（输入整句 → 唤起整句各词）──
    def sent_recall(s):
        neurons = [j for w in s for j in pats[w]]
        fired = run_recall(ng, build_pulse(ng.n, neurons))
        return fire_ratio(fired, neurons)

    rs = np.mean([sent_recall(s) for s in eval_sents])
    print(f"\n[验收①] 句复述率（抽样 {len(eval_sents)}）: {rs:.4f} "
          f"{'✅ ≥0.95' if rs >= 0.95 else '❌ 未达标'}")

    # ── 7. 验收②：前缀唤起（输入前 2 词 → 后续词唤起，局部触发整块唤起）──
    def prefix_recall(s):
        if len(s) < 3:
            return None
        pre = [i for w in s[:2] for i in pats[w]]
        tail = [i for w in s[2:] for i in pats[w]]
        fired = run_recall(ng, build_pulse(ng.n, pre))
        return fire_ratio(fired, tail)

    evals = [prefix_recall(s) for s in eval_sents]
    evals = [x for x in evals if x is not None]
    rp = np.mean(evals)
    n_ok_pre = sum(1 for x in evals if x > 0)
    print(f"[验收②] 前缀唤起（前2词→后段）: {rp:.4f} "
          f"（{n_ok_pre}/{len(evals)} 句能唤起后段）"
          f"{'✅ 局部触发整块唤起' if n_ok_pre >= len(evals) * 0.5 else '❌'}")

    # ── 8. 验收③：字/词零遗忘（Stage 0-1 不回退）──
    r0_after = recall_words(ng, pats, eval_hanzi, K)
    rw0_after = recall_words(ng, pats, eval_words, 20)
    ok_char = r0_after >= r0 - 0.01
    ok_word = rw0_after >= rw0 - 0.01
    print(f"[验收③] 字复述 {r0_after:.4f}（base {r0:.4f}）"
          f"{'✅ 不回退' if ok_char else '❌ 回退!'}")
    print(f"[验收③] 词复述 {rw0_after:.4f}（base {rw0:.4f}）"
          f"{'✅ 不回退' if ok_word else '❌ 回退!'}")

    ok_sent = bool(rs >= 0.95)
    ok_prefix = bool(n_ok_pre >= len(evals) * 0.5)
    ok_all = bool(ok_sent and ok_prefix and ok_char and ok_word)
    print(f"\n═══ Stage 2 验收: {'全部通过 ✅' if ok_all else '有失败 ❌'} "
          f"（{time.time() - t0:.0f}s）═══")

    # ── 9. 快照（版本链继续，Stage 2 版本）──
    metrics = {"sent_recall": round(rs, 4), "prefix_recall": round(rp, 4),
               "prefix_ok": n_ok_pre, "prefix_total": len(evals),
               "char_recall": round(r0_after, 4),
               "char_recall_before": round(r0, 4),
               "word_recall": round(rw0_after, 4),
               "word_recall_before": round(rw0, 4),
               "new_words": len(pats_new), "n": ng.n, "all_ok": ok_all}
    save_snapshot(ng, tag="Stage 2 句级（短句跟读，句内结构）",
                  metrics=metrics, vocab=vocab + list(pats_new),
                  pats=pats, cursor=cursor)


if __name__ == "__main__":
    main()
