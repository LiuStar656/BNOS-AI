# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""E+O 混合事件重放对拍（_speak 风格）：教学 + 痛觉 + 惩罚 → checkpoint + 重放逐边 0 差异。"""
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from snapshot import load_snapshot, RUNS
import _speak
from _speak import _LOG, _pain_event
from _net_log import ExpLog

SNAPSHOT = RUNS / "v13_0_20260810_111247" / "net.npz"
TAG = "E+O对拍临时"


def diff_all(ng_a, ng_b):
    diff = 0
    for i in range(ng_a.n):
        for k in range(ng_a.slots):
            ra, rb = ng_a.W_out[i][k], ng_b.W_out[i][k]
            if len(ra) != len(rb):
                diff += len(ra) + len(rb)
                continue
            if len(ra) == 0:
                continue
            if not np.array_equal(ra.dst, rb.dst):
                diff += 1
            elif not np.array_equal(ra.w, rb.w):
                diff += 1
    return diff


def main():
    ng0, vocab, pats, cursor = load_snapshot(SNAPSHOT)
    rng = np.random.default_rng(7)
    words = list(pats.keys())
    rng.shuffle(words)
    assert "石头" in pats, "需要 石头 在词表"

    # ── 原始方：checkpoint（学习前）→ E+O 混合序列 ──
    ng_a, _, _, _ = load_snapshot(SNAPSHOT)
    ng_a.rng = np.random.default_rng(42)
    cp = _LOG.checkpoint(ng_a, vocab, pats, cursor, tag=TAG)
    for i in range(5):   # E 教学 × 5
        _LOG.learn(ng_a, words[i * 3: i * 3 + 3], pats, slot=0)
    _pain_event(ng_a, pats, "碰了", "石头", link_times=2)   # E×6 + decay_path×2
    _LOG.append_op("penalize", src="想要", dst="石头")       # O 惩罚
    from _grow_v11 import penalize_edge
    penalize_edge(ng_a, pats, "想要", "石头")
    _LOG.flush()
    n_ev = sum(1 for _ in _LOG._iter_events())

    # ── 恢复：checkpoint + 重放全部事件 ──
    ng_rep, v2, p2, c2 = _LOG.recover_latest()

    diff = diff_all(ng_rep, ng_a)
    types = {}
    for ev in _LOG._iter_events():
        types[ev["t"]] = types.get(ev["t"], 0) + 1
    print(f"日志事件: {types}（共 {n_ev}）")
    print(f"[对拍] 重放恢复 vs 原始 E+O 序列: 差异边数 = {diff}  "
          f"{'✅ 位级一致' if diff == 0 else '❌ 分叉'}")

    # ── 清理 ──
    arch = _LOG.arch / f"{cp}.jsonl"
    if arch.exists():
        arch.unlink()
    shutil.rmtree(RUNS / cp, ignore_errors=True)
    lines = (RUNS / "index.jsonl").read_text(encoding="utf-8").splitlines()
    keep = [l for l in lines if l.strip() and TAG not in l]
    (RUNS / "index.jsonl").write_text("\n".join(keep) + "\n", encoding="utf-8")
    _LOG.close()
    if _LOG.log.exists():
        _LOG.log.unlink()
    print("[清理] 完成")


if __name__ == "__main__":
    main()
