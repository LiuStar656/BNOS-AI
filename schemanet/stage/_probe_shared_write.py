# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""共同上下文直写方案评估（v35 单快照）：tick 错开直写同一文件 vs 写前拉取合并。

用户方案（2026-08-11）：两个进程把内容写进同一个上下文（同一快照文件），
靠时间 tick 不同错开写入时刻，认为"这样两边都能同时存"。

本探针用**顺序执行**模拟"最理想的 tick 错开"（写入时刻完全不重叠）——
若最理想情况都保不住双方记忆，则真实运行（写窗可能重叠）只会更糟：

  S1 tick 错开直写（用户方案原样）：
     A = load(v35) → 学「我吃苹果」(槽0) → 直写 shared/net.npz   （tick 1）
     B = load(v35) → 学「他看家」(槽1) → 直写 shared/net.npz   （tick 2，各自独立内存）
     → 检查最终文件：可加载？A 的记忆还在吗？B 的呢？
  S2 对照（写前拉取合并，事务式写回）：
     C = load(v35) → 学「累休息」(槽0) → 直写 shared2/net.npz   （tick 1）
     D = load(v35) → 学「冷穿」(槽1) → 写前读 shared2，把 C 的边 max 合并进自己
     → 再直写 shared2/net.npz                                （tick 2）
     → 检查最终文件：双方记忆是否共存？

判定：
  S1 预期：文件可加载（错开写不损坏），但只有后写者（B）的记忆——
     A 的记忆被全量覆盖（lost update，与 tick 错开无关）。
  S2 预期：文件可加载且双方记忆共存（写前拉取 = 把"共同上下文"的
     最新状态合并进自己再写回，每次写回 = 双方并集）。

用法：python stage/_probe_shared_write.py
留档：runs/_probe_shared_write_{ts}/result.json
"""
import json
import shutil
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snapshot import load_snapshot, _pack_net, _net_params
from schema_net import _learn_sentence, _evoke_prefix

ROOT = Path(__file__).resolve().parent.parent
SRC_NPZ = ROOT / "runs" / "v35_0_20260811_044836" / "net.npz"

N_ROUNDS = 5
PAIRS = [("我", "吃", 0), ("他", "看", 1), ("累", "休息", 0), ("冷", "穿", 1)]


# ────────────────────────────────────────────────────────────────
#  工具
# ────────────────────────────────────────────────────────────────

def edge_by_slot(ng, pats, src, dst):
    dst_set = set(pats[dst])
    per = []
    for k in range(ng.slots):
        total = 0.0
        for j in pats[src]:
            row = ng.W_out[j][k]
            if row:
                keep = np.isin(row.dst, np.fromiter(dst_set, dtype=np.int32))
                total += float(row.w[keep].sum())
        per.append(round(total, 3))
    return per


def net_payload(ng, vocab, pats, cursor):
    pats_json = {w: [int(x) for x in v] for w, v in pats.items()}
    return dict(
        params=json.dumps(_net_params(ng)).encode("utf-8"),
        vocab=json.dumps(list(vocab), ensure_ascii=False).encode("utf-8"),
        pats=json.dumps(pats_json, ensure_ascii=False).encode("utf-8"),
        cursor=np.asarray([int(cursor or 0)], dtype=np.int64),
        **_pack_net(ng))


def save_to(ng, vocab, pats, cursor, target):
    """直写目标路径（用户方案原样：不原子替换，直接覆盖写同一文件）。"""
    np.savez_compressed(target, **net_payload(ng, vocab, pats, cursor))


def learn(ng, words, pats, slot):
    for _ in range(N_ROUNDS):
        _learn_sentence(ng, words, pats, slot=slot)


def read_edges(fp, pairs):
    """读快照文件 → 各关键边强度（带可加载性判断）。"""
    try:
        ng, vocab, pats, cursor = load_snapshot(fp)
    except Exception as e:
        return {"loadable": False, "error": f"{type(e).__name__}: {e}"}
    out = {"loadable": True}
    for s, d, k in pairs:
        out[f"{s}→{d}(槽{k})"] = edge_by_slot(ng, pats, s, d)[k]
    return out


def diff_edges_max_into(ng_dst, ng_src, slots):
    """把 src 相对公共基准新增/变化的边 max 合并进 dst（写前拉取合并）。"""
    n = min(len(ng_dst.W_out), len(ng_src.W_out))
    n_apply = 0
    for i in range(n):
        for slot in range(slots):
            rb = ng_src.W_out[i][slot]
            if not rb:
                continue
            for j, w in rb.items():
                row = ng_dst.W_out[i][slot]
                cur = row.get(j, 0.0)
                if w > cur:
                    row[j] = w
                    n_apply += 1
    return n_apply


# ────────────────────────────────────────────────────────────────
#  main
# ────────────────────────────────────────────────────────────────

def main():
    if not SRC_NPZ.exists():
        print(f"[中止] 找不到 v35 快照: {SRC_NPZ}")
        return
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT / "runs" / f"_probe_shared_write_{ts}"
    for d in ("base", "shared", "shared2"):
        (run_dir / d).mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC_NPZ, run_dir / "base" / "net.npz")
    base_npz = run_dir / "base" / "net.npz"
    shared1 = run_dir / "shared" / "net.npz"
    shared2 = run_dir / "shared2" / "net.npz"

    base_ng, _, pats, _ = load_snapshot(base_npz)
    base_ref = {f"{s}→{d}(槽{k})": edge_by_slot(base_ng, pats, s, d)[k]
                for s, d, k in PAIRS}

    print("═══ 共同上下文直写方案评估（v35 单快照）═══", flush=True)
    print(f"  基准边: {base_ref}", flush=True)
    rep = {"meta": {"ts": ts, "version": "35.0", "n_rounds": N_ROUNDS,
                    "base_edges": base_ref}, "sections": {}}

    # ── S1：tick 错开直写同一文件（用户方案原样，顺序=最理想错开）──
    print("\n[S1] tick 错开直写（A tick1 写 → B tick2 写，各自独立内存）", flush=True)
    ngA, vocab, pats, cursor = load_snapshot(base_npz)
    learn(ngA, ["我", "吃", "苹果"], pats, slot=0)
    save_to(ngA, vocab, pats, cursor, shared1)          # tick 1：A 写入
    print(f"  [tick1] A 学「我吃苹果」→ 写 shared/net.npz", flush=True)
    ngB, vocab, pats, cursor = load_snapshot(base_npz)  # B 用自己的独立内存副本（不重读共享）
    learn(ngB, ["他", "看", "家"], pats, slot=1)
    save_to(ngB, vocab, pats, cursor, shared1)          # tick 2：B 覆盖写
    print(f"  [tick2] B 学「他看家」（内存副本）→ 写 shared/net.npz（覆盖）", flush=True)
    s1 = read_edges(shared1, PAIRS)
    rep["sections"]["S1_tick错开直写"] = s1
    print(f"  [最终 shared/net.npz] {s1}", flush=True)
    a_lost = s1["loadable"] and s1["我→吃(槽0)"] == base_ref["我→吃(槽0)"]
    b_kept = s1["loadable"] and s1["他→看(槽1)"] > 0
    rep["sections"]["S1判定"] = {
        "A记忆(我→吃)是否丢失": a_lost,
        "B记忆(他→看)是否保留": b_kept,
        "结论": ("tick 错开不损坏文件，但后写覆盖先写——"
                 "A 的记忆从共同上下文消失（lost update 与错开无关）"
                 if (a_lost and b_kept) else "与预期不符，需检查")}
    print(f"  A 记忆丢失={a_lost} | B 记忆保留={b_kept}", flush=True)

    # ── S2：对照——写前拉取合并（事务式写回）──
    print("\n[S2] 对照：写前拉取合并（B 写前先读共享，把 A 的边合并进自己再写）", flush=True)
    ngC, vocab, pats, cursor = load_snapshot(base_npz)
    learn(ngC, ["累", "休息"], pats, slot=0)
    save_to(ngC, vocab, pats, cursor, shared2)          # tick 1：C 写入
    print(f"  [tick1] C 学「累休息」→ 写 shared2/net.npz", flush=True)
    ngD, vocab, pats, cursor = load_snapshot(base_npz)
    learn(ngD, ["冷", "穿"], pats, slot=1)
    n_merge = diff_edges_max_into(ngD, ngC, ngD.slots)  # 写前拉取：C 的边并入 D
    print(f"  [写前] D 读 C 写入的共享快照，max 合并 {n_merge} 条边进自己", flush=True)
    save_to(ngD, vocab, pats, cursor, shared2)          # tick 2：D 写回（含 C 的记忆）
    print(f"  [tick2] D 学「冷穿」+ C 的记忆 → 写 shared2/net.npz", flush=True)
    s2 = read_edges(shared2, PAIRS)
    rep["sections"]["S2_写前拉取合并"] = s2
    print(f"  [最终 shared2/net.npz] {s2}", flush=True)
    c_kept = s2["loadable"] and s2["累→休息(槽0)"] > base_ref["累→休息(槽0)"]
    d_kept = s2["loadable"] and s2["冷→穿(槽1)"] > 0
    rep["sections"]["S2判定"] = {
        "C记忆(累→休息)保留": c_kept,
        "D记忆(冷→穿)保留": d_kept,
        "结论": ("写前拉取合并使每次写回 = 双方记忆并集，共同上下文不丢记忆"
                 if (c_kept and d_kept) else "与预期不符，需检查")}
    print(f"  C 记忆保留={c_kept} | D 记忆保留={d_kept}", flush=True)

    rep["sections"]["summary"] = {
        "S1 tick错开直写": rep["sections"]["S1判定"]["结论"],
        "S2 写前拉取合并": rep["sections"]["S2判定"]["结论"],
    }
    print("\n═══ 汇总 ═══", flush=True)
    for k, v in rep["sections"]["summary"].items():
        print(f"  {k}: {v}", flush=True)
    (run_dir / "result.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {run_dir}", flush=True)


if __name__ == "__main__":
    main()
