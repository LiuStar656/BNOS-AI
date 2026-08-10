# -*- coding: utf-8 -*-
"""增量快照对拍 v2（真实崩溃恢复场景）：checkpoint(学习前) → 学习 100 句（日志）→
recover = checkpoint + 重放日志 → 与直接学习逐边 0 差异（方案测试计划 #1）。"""
import sys
import time
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np

from snapshot import load_snapshot, RUNS
import _net_log as nl

SNAPSHOT = RUNS / "v13_0_20260810_111247" / "net.npz"
N_SENT = 100
SEED = 7
TAG = "增量对拍临时v2"


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


def cleanup(log, cp):
    arch = log.arch / f"{cp}.jsonl"
    if arch.exists():
        arch.unlink()
    shutil.rmtree(RUNS / cp, ignore_errors=True)
    lines = (RUNS / "index.jsonl").read_text(encoding="utf-8").splitlines()
    keep = [l for l in lines if l.strip() and TAG not in l]
    (RUNS / "index.jsonl").write_text("\n".join(keep) + "\n", encoding="utf-8")
    log.close()
    if log.log.exists():
        log.log.unlink()


def main():
    ng0, vocab, pats, cursor = load_snapshot(SNAPSHOT)
    rng = np.random.default_rng(SEED)
    words = list(pats.keys())
    rng.shuffle(words)
    sents = [[words[i], words[i + 1], words[i + 2]] for i in range(0, 3 * N_SENT, 3)]

    # ── 记录方：checkpoint(学习前) → 100 句 learn（E 事件进 active）──
    log = nl.ExpLog()
    ng_a, _, _, _ = load_snapshot(SNAPSHOT)
    ng_a.rng = np.random.default_rng(42)
    cp = log.checkpoint(ng_a, vocab, pats, cursor, tag=TAG)
    t0 = time.perf_counter()
    for s in sents:
        log.learn(ng_a, s, pats, slot=0)
    t_log = time.perf_counter() - t0
    log_sz = log.log.stat().st_size
    # 模拟崩溃：active 保留，不 checkpoint

    # ── 参考方：同种子直接学习 100 句（计时 = 纯学习基线）──
    ng_ref, _, _, _ = load_snapshot(SNAPSHOT)
    ng_ref.rng = np.random.default_rng(42)
    t0 = time.perf_counter()
    for s in sents:
        nl._learn_sentence(ng_ref, s, pats, slot=0)
    t_learn = time.perf_counter() - t0

    # ── 恢复：load checkpoint + 重放 active ──
    t0 = time.perf_counter()
    ng_rep, v2, p2, c2 = log.recover_latest()
    t_rep = time.perf_counter() - t0
    log.flush()
    log_sz = log.log.stat().st_size

    print(f"纯学习 100 句: {t_learn:.2f}s（{t_learn/100*1000:.0f}ms/句）| "
          f"学习+日志: {t_log:.2f}s（{t_log/100*1000:.0f}ms/句）| "
          f"日志增量: {(t_log-t_learn)/100*1000:.1f}ms/句")
    print(f"日志: {N_SENT} 句 → {log_sz} 字节（{log_sz/N_SENT:.0f}B/句）| "
          f"checkpoint: {cp} | 恢复: {t_rep:.2f}s")
    diff = diff_all(ng_rep, ng_ref)
    print(f"[对拍] 重放恢复 vs 直接学习: 差异边数 = {diff}  "
          f"{'✅ 位级一致（0 差异）' if diff == 0 else '❌ 分叉'}")
    # 附加：恢复后网络与"崩溃时"网络（ng_a）也应一致
    diff2 = diff_all(ng_rep, ng_a)
    print(f"[对拍] 重放恢复 vs 崩溃时状态: 差异边数 = {diff2}  "
          f"{'✅ 位级一致' if diff2 == 0 else '❌ 分叉'}")
    cleanup(log, cp)
    print("[清理] 完成")


if __name__ == "__main__":
    main()
