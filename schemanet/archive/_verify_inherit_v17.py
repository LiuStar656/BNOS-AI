# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""v17 继承验收补跑：v17.0 快照上重跑 v15/v16 全继承（字/词/句/2.5 类别零遗忘）。

背景（2026-08-10）：v17 训练管线（_probe_expose_prose.py）按 PLAN 只跑
EVAL 6 句分句接话验收（修正前 ≥0.95 + 校准 ≤1）；继承 v15 全验收未在
管线内——散文先见不扩词表不删边（只增边），理论上零遗忘，但需实测闭环。
本脚本在 v17.0 上重跑 _grow_v16.py 同款继承验收：同 eval 集抽样种子
（rng 7/8/9）、同 build_cats 参数、同 inherit_acceptance 调用——
v17.0 词表 == v16.0 词表（散文/后教均未分配新词），eval 集与 v16 验收
完全一致，指标可直接对照 v16（字/词 1.0000、句 0.9255、类别 1.0000、hold 15/15）。

用法：python _verify_inherit_v17.py
"""

import json
import time
from pathlib import Path

import numpy as np

from snapshot import load_version
from _grow_cat import build_cats
from _grow_v12 import inherit_acceptance

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


def main():
    t0 = time.time()
    print("═══ v17 继承验收补跑（v17.0 快照 → v15/v16 全继承零遗忘）═══\n")

    # ── 1. 加载 v17.0（n=149068，词表与 v16 相同）─────────────
    ng, vocab, pats, cursor = load_version("17.0")
    print(f"[加载] 17.0：n={ng.n}，词表 {len(pats)}，cursor={cursor}")

    # ── 2. eval 集构造（与 _grow_v16 同款：同种子、同参数）─────
    hanzi = json.loads((DATA / "stage0_hanzi.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats25 = build_cats(pats, sem["words"], 12, 3)
    words_old = [w for w in vocab if w not in set(hanzi)]
    eval_hanzi = list(np.random.default_rng(7).choice(hanzi, 200, replace=False))
    eval_words = list(np.random.default_rng(8).choice(words_old, 300,
                                                     replace=False))
    sents_all = json.loads((DATA / "stage2_sents.json").read_text(
        encoding="utf-8"))
    eval_sents = [sents_all[i] for i in np.random.default_rng(9).choice(
        len(sents_all), 100, replace=False)]
    print(f"[eval 集] 字 200 / 词 300 / 句 100（与 v16 验收同款）")

    # ── 3. 继承验收（v16 同款调用）────────────────────────────
    inh, ok_inh = inherit_acceptance(ng, vocab, pats, hanzi, cats25,
                                     sem, eval_hanzi, eval_words,
                                     eval_sents)
    print(f"\n[继承] 字 {inh['char']:.4f}（base {inh['char_before']:.4f}）"
          f" | 词 {inh['word']:.4f}（base {inh['word_before']:.4f}）"
          f" | 句 {inh['sent']:.4f}（base {inh['sent_before']:.4f}）"
          f" | 2.5 类别 {inh['cat25']:.4f}"
          f" | hold {inh['hold25_ok']}/{inh['hold25_tot']}"
          f" {'✅' if ok_inh else '❌ 回退!'}")
    print(f"[对照 v16] 字 1.0000 | 词 1.0000 | 句 0.9255 | 类别 1.0000"
          f" | hold 15/15")
    print(f"\n═══ v17 继承验收: {'全部通过 ✅' if ok_inh else '有失败 ❌'}"
          f"（{time.time() - t0:.0f}s）═══")

    # ── 4. 留档 ───────────────────────────────────────────────
    out_dir = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_verify_inherit_v17"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"tag": "v17 继承验收补跑（零遗忘）", "base": "17.0",
              "inherit": inh, "all_ok": bool(ok_inh),
              "ref_v16": {"char": 1.0, "word": 1.0, "sent": 0.9255,
                          "cat25": 1.0, "hold25": "15/15"},
              "sec": round(time.time() - t0, 1)}
    (out_dir / "result.json").write_text(json.dumps(result,
                                                    ensure_ascii=False,
                                                    indent=1),
                                         encoding="utf-8")
    print(f"[留档] {out_dir / 'result.json'}")


if __name__ == "__main__":
    main()
