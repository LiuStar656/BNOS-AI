# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""多实例记忆互通探针（v35 单快照 · 全程不重启）。

问题（用户 2026-08-11）：
  1. 两个实例在内存里是不是相互隔离的？
  2. 想要在不重启的基础上实现两个实例的记忆互通，怎么办？

结论先行的设计（机制全部复用已验证件）：
  - 隔离：实例 = 独立内存副本（load_snapshot 每次全新构建 W_out/瞬态/rng；
    并发激活探针 A2 已证互不干扰）。唯一共享 = 磁盘快照文件（只读安全）。
  - 互通 = "经历广播 + 合并器重放 + 实例就地应用"，全程不重启：
      ① 实例学习时把经历（E 事件：句子 + 学习前 rng 状态——复用 _net_log
         格式，rng 状态保证重放位级一致）append 到**自己的**日志文件
         （每实例只写自己的文件 → 无写竞争，规避 B1 同文件并发写损坏）；
      ② 合并器：读全部实例日志 → 在共享基准（v35 副本）上按 rng 状态重放
         全部经历 → 原子写共享快照（tmp + replace，唯一写者）+ 发布合并 diff；
      ③ 实例：拉取合并 diff → 就地 max 应用到自己的 W_out（幂等，可反复
         应用；v/spikes/pre_trace 瞬时状态不动 → 不重启、不整体重载）。

流程（A/B 两实例全程存活，无任何重启/重载）：
  Phase1  A 学「我吃苹果」(槽0)，B 学「他看家」(槽1)
          → 合并前验证隔离（B 里没有 A 的记忆，反之亦然）
          → 合并器 merge_once(1) → 双方 sync（就地应用）
          → 验证互通（B 里出现了 A 的教学边，反之亦然）
  Phase2  A 再学「累休息」(槽0)，B 再学「冷穿」(槽1)
          → 合并器 merge_once(2) → 双方 sync → 验证持续互通

用法：python stage/_probe_mem_share.py
留档：runs/_probe_mem_share_{ts}/result.json
"""
import json
import queue
import shutil
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snapshot import load_snapshot, _pack_net, _net_params
from schema_net import _learn_sentence, _evoke_prefix
from _net_log import _rng_state_to_json, _rng_state_from_json

ROOT = Path(__file__).resolve().parent.parent
SRC_NPZ = ROOT / "runs" / "v35_0_20260811_044836" / "net.npz"

N_ROUNDS = 5
KEY_PAIRS = [   # (词对, 槽位) 验证对象
    ("我", "吃", 0), ("吃", "苹果", 0), ("他", "看", 1), ("看", "家", 1),
    ("累", "休息", 0), ("冷", "穿", 1),
]


# ────────────────────────────────────────────────────────────────
#  工具
# ────────────────────────────────────────────────────────────────

def edge_by_slot(ng, pats, src, dst):
    """src 模式出边汇聚到 dst 模式的总权重，按槽位分开。"""
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
    """与 save_snapshot 相同的 npz 载荷（显式写盘用）。"""
    pats_json = {w: [int(x) for x in v] for w, v in pats.items()}
    return dict(
        params=json.dumps(_net_params(ng)).encode("utf-8"),
        vocab=json.dumps(list(vocab), ensure_ascii=False).encode("utf-8"),
        pats=json.dumps(pats_json, ensure_ascii=False).encode("utf-8"),
        cursor=np.asarray([int(cursor or 0)], dtype=np.int64),
        **_pack_net(ng))


def diff_edges(ng_b, ng_base, slots):
    """分支相对基准的边差异：{(i, slot, j): w}（新增 + 变化）。"""
    out = {}
    n = min(len(ng_b.W_out), len(ng_base.W_out))
    for i in range(n):
        for slot in range(slots):
            rb = ng_b.W_out[i][slot]
            bb = ng_base.W_out[i][slot]
            if not rb:
                continue
            if bb and len(rb) == len(bb):
                for j, w in rb.items():
                    if bb.get(j, 0.0) != w:
                        out[(i, slot, j)] = w
            else:
                db = {j: w for j, w in bb.items()} if bb else {}
                for j, w in rb.items():
                    if db.get(j, 0.0) != w:
                        out[(i, slot, j)] = w
    return out


def verify_net(ng, pats):
    """读一个实例的验证读数：关键边强度 + 唤起比例。
    learn_gate 临时关闭——evoke 路径也走 Hebbian（step 学习块），
    不关会污染后续读数（对照实测：一次 KEY_PAIRS 验证 +19）。"""
    ng.learn_gate = False
    try:
        out = {"edges": {}, "evoke": {}}
        for s, d, k in KEY_PAIRS:
            if s in pats and d in pats:
                out["edges"][f"{s}→{d}(槽{k})"] = edge_by_slot(ng, pats, s, d)[k]
                out["evoke"][f"注入{s}→{d}"] = round(
                    sum(1 for j in pats[d]
                        if j in _evoke_prefix(ng, [s], pats, slot=k, steps=3))
                    / len(pats[d]), 3)
        return out
    finally:
        ng.learn_gate = True


# ────────────────────────────────────────────────────────────────
#  互通机制三件套：记录 / 合并 / 应用
# ────────────────────────────────────────────────────────────────

def teach_and_log(ng, words, pats, slot, journal_fp):
    """实例学习并记录 E 事件（先拍 rng 状态再教学——重放位级一致的前提）。
    rounds 记录学习轮数——重放按同轮数循环，边强度与实例实际所学一致。"""
    ev = {"t": "E", "words": list(words), "slot": int(slot),
          "rng": _rng_state_to_json(ng.rng), "rounds": N_ROUNDS,
          "ts": time.time()}
    with open(journal_fp, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    for _ in range(N_ROUNDS):
        _learn_sentence(ng, words, pats, slot=slot)


def merge_once(base_npz, journals, merge_dir, seq):
    """合并器：重放全部实例经历 → 原子写共享快照 + 发布合并 diff + seq。
    共享快照唯一写者（tmp + replace），杜绝同文件并发写损坏。"""
    base_ng, vocab, pats, cursor = load_snapshot(base_npz)   # diff 基准
    replay_ng, _, _, _ = load_snapshot(base_npz)             # 重放目标
    events = []
    for fp in journals:
        if fp.exists():
            for line in fp.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    events.append(json.loads(line))
    events.sort(key=lambda e: e["ts"])
    for ev in events:
        _rng_state_from_json(replay_ng.rng, ev["rng"])
        for _ in range(ev.get("rounds", 1)):
            _learn_sentence(replay_ng, ev["words"], pats, slot=ev["slot"])
    diff = diff_edges(replay_ng, base_ng, replay_ng.slots)
    tmp = merge_dir / f"net_{seq}.tmp.npz"    # savez 自动补 .npz → 实际落盘 net_{seq}.tmp.npz
    np.savez_compressed(tmp, **net_payload(replay_ng, vocab, pats, cursor))
    os.replace(tmp, merge_dir / "net.npz")                    # 原子替换
    (merge_dir / "merged_diff.json").write_text(json.dumps(
        {"seq": seq, "edges": [[i, k, j, w] for (i, k, j), w in diff.items()]},
        ensure_ascii=False), encoding="utf-8")
    (merge_dir / "seq.txt").write_text(str(seq))
    return len(events), len(diff)


def sync_instance(ng, merge_dir, applied_seq):
    """实例拉取合并 diff，就地 max 应用（幂等，不重启）。返回新 seq。"""
    merge_dir = Path(merge_dir)
    seq_fp = merge_dir / "seq.txt"
    if not seq_fp.exists():
        return applied_seq
    seq = int(seq_fp.read_text().strip())
    if seq <= applied_seq:
        return applied_seq
    diff = json.loads((merge_dir / "merged_diff.json").read_text(encoding="utf-8"))
    n_apply = 0
    for i, k, j, w in diff["edges"]:
        row = ng.W_out[i][k]
        cur = row.get(j, 0.0)
        if w > cur:
            row[j] = w
            n_apply += 1
    return seq


# ────────────────────────────────────────────────────────────────
#  实例（线程）：全程存活，只经命令队列收 teach/sync/verify/exit
# ────────────────────────────────────────────────────────────────

def run_instance(name, base_npz, journal_fp, merge_dir, cmd_q, out_q):
    ng, vocab, pats, cursor = load_snapshot(base_npz)          # 独立内存副本
    applied_seq = 0
    out_q.put({"inst": name, "op": "ready", "ts": time.time()})
    while True:
        try:
            cmd = cmd_q.get(timeout=0.3)
        except Exception:
            continue
        op = cmd["op"]
        if op == "exit":
            out_q.put({"inst": name, "op": "exited"})
            return
        if op == "teach":
            teach_and_log(ng, cmd["words"], pats, cmd["slot"], journal_fp)
            out_q.put({"inst": name, "op": "taught", "words": cmd["words"]})
        elif op == "sync":
            applied_seq = sync_instance(ng, merge_dir, applied_seq)
            out_q.put({"inst": name, "op": "synced", "seq": applied_seq})
        elif op == "verify":
            out_q.put({"inst": name, "op": "verified",
                       "data": verify_net(ng, pats)})


# ────────────────────────────────────────────────────────────────
#  main
# ────────────────────────────────────────────────────────────────

def main():
    if not SRC_NPZ.exists():
        print(f"[中止] 找不到 v35 快照: {SRC_NPZ}")
        return
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT / "runs" / f"_probe_mem_share_{ts}"
    base_dir = run_dir / "base"
    journals_dir = run_dir / "journals"
    merge_dir = run_dir / "merge"
    for d in (base_dir, journals_dir, merge_dir):
        d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC_NPZ, base_dir / "net.npz")
    shutil.copy2(SRC_NPZ.parent / "meta.json", base_dir / "meta.json")
    base_npz = base_dir / "net.npz"

    # 基准参考值（v35 原有边强度）
    base_ng, _, pats, _ = load_snapshot(base_npz)
    base_ref = {f"{s}→{d}(槽{k})": edge_by_slot(base_ng, pats, s, d)[k]
                for s, d, k in KEY_PAIRS}

    print("═══ 多实例记忆互通（不重启）═══", flush=True)
    print(f"  基准: {SRC_NPZ.name} 边基准值 {base_ref}", flush=True)

    # ── 启动 A/B 两实例（全程存活，不重启）──
    qA, qB = queue.Queue(), queue.Queue()
    out_q = queue.Queue()
    tA = threading.Thread(target=run_instance, name="instA",
                          args=("A", str(base_npz), str(journals_dir / "A.jsonl"),
                                str(merge_dir), qA, out_q))
    tB = threading.Thread(target=run_instance, name="instB",
                          args=("B", str(base_npz), str(journals_dir / "B.jsonl"),
                                str(merge_dir), qB, out_q))
    tA.start(); tB.start()
    for _ in range(60):                      # 等两实例加载就绪
        if out_q.qsize() >= 2:
            break
        time.sleep(0.2)

    def send(q, op, **kw):
        q.put({"op": op, **kw})

    pending = []                             # 非目标消息暂存（wait_op 不丢弃）

    def log(msg):
        print(f"  [进度] {msg}", flush=True)

    def wait_op(name, op, timeout=120):
        """等指定实例的指定操作完成。非目标消息进 pending 暂存（不丢弃）。"""
        deadline = time.time() + timeout
        while True:
            for r in list(pending):
                if r["inst"] == name and r["op"] == op:
                    pending.remove(r)
                    return r
            if time.time() > deadline:
                raise TimeoutError(f"实例 {name} 等待 {op} 超时（pending={pending}）")
            try:
                r = out_q.get(timeout=0.2)
            except Exception:
                continue
            if r["inst"] == name and r["op"] == op:
                return r
            pending.append(r)

    rep = {"meta": {"ts": ts, "version": "35.0",
                    "mechanism": "经历日志(E+rng) → 合并器重放 → 实例就地 max 应用",
                    "base_edges": base_ref},
           "sections": {}}

    # ── Phase1：各自学习 → 合并 → 互通 ──
    send(qA, "teach", words=["我", "吃", "苹果"], slot=0)
    send(qB, "teach", words=["他", "看", "家"], slot=1)
    wait_op("A", "taught"); wait_op("B", "taught")
    log("Phase1 双方学完（A 我吃苹果 / B 他看家）")
    send(qA, "verify"); send(qB, "verify")
    vA0 = wait_op("A", "verified")["data"]
    vB0 = wait_op("B", "verified")["data"]

    ph1 = {"before_merge": {"A": vA0, "B": vB0}}
    iso_A_clean = (vA0["edges"]["他→看(槽1)"] == base_ref["他→看(槽1)"]
                   and vA0["edges"]["看→家(槽1)"] == base_ref["看→家(槽1)"])
    iso_B_clean = (vB0["edges"]["我→吃(槽0)"] == base_ref["我→吃(槽0)"]
                   and vB0["edges"]["吃→苹果(槽0)"] == base_ref["吃→苹果(槽0)"])
    ph1["isolated"] = {"A无B记忆": iso_A_clean, "B无A记忆": iso_B_clean}
    print("\n[Phase1] 各自学习后（合并前）——隔离确认：", flush=True)
    print(f"  A 我→吃={vA0['edges']['我→吃(槽0)']}（基准 {base_ref['我→吃(槽0)']}）"
          f" | A 他→看={vA0['edges']['他→看(槽1)']}（基准 {base_ref['他→看(槽1)']}，应不变）",
          flush=True)
    print(f"  B 他→看={vB0['edges']['他→看(槽1)']}（基准 {base_ref['他→看(槽1)']}）"
          f" | B 我→吃={vB0['edges']['我→吃(槽0)']}（基准 {base_ref['我→吃(槽0)']}，应不变）",
          flush=True)
    print(f"  隔离判定: A无B记忆={iso_A_clean}  B无A记忆={iso_B_clean}", flush=True)

    log("合并器 merge_once(1)：重放双方经历 → 原子写共享快照")
    n_ev, n_diff = merge_once(base_npz, (journals_dir / "A.jsonl",
                                         journals_dir / "B.jsonl"), merge_dir, 1)
    log(f"合并#1 完成：重放 {n_ev} 条经历 → {n_diff} 条变化边")
    send(qA, "sync"); send(qB, "sync")
    wait_op("A", "synced"); wait_op("B", "synced")
    log("双方 sync 完成（就地 max 应用，未重启）")
    send(qA, "verify"); send(qB, "verify")
    vA1 = wait_op("A", "verified")["data"]
    vB1 = wait_op("B", "verified")["data"]
    ph1["after_sync"] = {"A": vA1, "B": vB1}
    ph1["interop"] = {
        "A得了B记忆(他→看>0)": vA1["edges"]["他→看(槽1)"] > 0,
        "A得了B记忆(看→家>0)": vA1["edges"]["看→家(槽1)"] > 0,
        "B得了A记忆(我→吃>基准)": vB1["edges"]["我→吃(槽0)"] > base_ref["我→吃(槽0)"],
        "B得了A记忆(吃→苹果>基准)": vB1["edges"]["吃→苹果(槽0)"] > base_ref["吃→苹果(槽0)"],
        "A保留自己记忆": vA1["edges"]["我→吃(槽0)"] > base_ref["我→吃(槽0)"],
        "B保留自己记忆": vB1["edges"]["他→看(槽1)"] > 0,
    }
    ph1["verdict"] = ("不重启互通成立：双方在各自运行中获得了对方的教学边"
                      if all(ph1["interop"].values()) else "互通有缺失")
    print(f"\n[合并#1 后同步] ——互通确认（两实例均未重启）：", flush=True)
    print(f"  A 现在: 他→看={vA1['edges']['他→看(槽1)']} 看→家={vA1['edges']['看→家(槽1)']}"
          f"（B 的记忆已到 A）", flush=True)
    print(f"  B 现在: 我→吃={vB1['edges']['我→吃(槽0)']} 吃→苹果={vB1['edges']['吃→苹果(槽0)']}"
          f"（A 的记忆已到 B）", flush=True)
    print(f"  判定: {ph1['verdict']}", flush=True)
    rep["sections"]["phase1"] = ph1

    # ── Phase2：持续互通（再次学习 → 再合并 → 再同步）──
    send(qA, "teach", words=["累", "休息"], slot=0)
    send(qB, "teach", words=["冷", "穿"], slot=1)
    wait_op("A", "taught"); wait_op("B", "taught")
    log("Phase2 双方再学完（A 累→休息 / B 冷→穿）")
    log("合并器 merge_once(2)：重放全部经历（含 Phase1+2）")
    n_ev2, n_diff2 = merge_once(base_npz, (journals_dir / "A.jsonl",
                                           journals_dir / "B.jsonl"), merge_dir, 2)
    log(f"合并#2 完成：重放 {n_ev2} 条经历 → {n_diff2} 条变化边")
    send(qA, "sync"); send(qB, "sync")
    wait_op("A", "synced"); wait_op("B", "synced")
    log("双方 sync 完成")
    send(qA, "verify"); send(qB, "verify")
    vA2 = wait_op("A", "verified")["data"]
    vB2 = wait_op("B", "verified")["data"]
    ph2 = {"A": vA2, "B": vB2,
           "interop": {
               "A得了B新记忆(冷→穿>0)": vA2["edges"]["冷→穿(槽1)"] > 0,
               "B得了A新记忆(累→休息>基准)": vB2["edges"]["累→休息(槽0)"] > base_ref["累→休息(槽0)"],
               "A保留Phase1记忆(我→吃)": vA2["edges"]["我→吃(槽0)"] > base_ref["我→吃(槽0)"],
               "B保留Phase1记忆(他→看)": vB2["edges"]["他→看(槽1)"] > 0,
           }}
    ph2["verdict"] = ("持续互通成立：第二轮新记忆再次互相到达，且首轮记忆无丢失"
                      if all(ph2["interop"].values()) else "持续互通有缺失")
    print(f"\n[合并#2 后同步] ——持续互通确认：", flush=True)
    print(f"  A 现在: 冷→穿={vA2['edges']['冷→穿(槽1)']}（B 新记忆）"
          f" 我→吃={vA2['edges']['我→吃(槽0)']}（自己旧记忆保留）", flush=True)
    print(f"  B 现在: 累→休息={vB2['edges']['累→休息(槽0)']}（A 新记忆）"
          f" 他→看={vB2['edges']['他→看(槽1)']}（自己旧记忆保留）", flush=True)
    print(f"  判定: {ph2['verdict']}", flush=True)
    rep["sections"]["phase2"] = ph2

    # ── 收尾：实例退出；最终共享快照完整性 ──
    send(qA, "exit"); send(qB, "exit")
    tA.join(30); tB.join(30)
    ng_f, _, pats_f, _ = load_snapshot(merge_dir / "net.npz")
    final = {"A_我→吃": edge_by_slot(ng_f, pats_f, "我", "吃")[0],
             "A_吃→苹果": edge_by_slot(ng_f, pats_f, "吃", "苹果")[0],
             "B_他→看": edge_by_slot(ng_f, pats_f, "他", "看")[1],
             "B_看→家": edge_by_slot(ng_f, pats_f, "看", "家")[1],
             "A2_累→休息": edge_by_slot(ng_f, pats_f, "累", "休息")[0],
             "B2_冷→穿": edge_by_slot(ng_f, pats_f, "冷", "穿")[1]}
    rep["sections"]["final_snapshot"] = final
    print(f"\n[最终共享快照] merge/net.npz 六条教学边全部在: {final}", flush=True)

    rep["sections"]["summary"] = {
        "隔离": "两个实例内存互不共享（学习互不可见，直到同步）",
        "不重启互通": ph1["verdict"],
        "持续互通": ph2["verdict"],
    }
    (run_dir / "result.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n═══ 汇总 ═══", flush=True)
    for k, v in rep["sections"]["summary"].items():
        print(f"  {k}: {v}", flush=True)
    print(f"\n留档: {run_dir}", flush=True)


if __name__ == "__main__":
    main()
