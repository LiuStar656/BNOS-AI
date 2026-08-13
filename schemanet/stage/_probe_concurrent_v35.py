# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""定式网络（v35 单快照）并发探针：同时激活 + 不同实例最后记忆同时写入。

问题（用户 2026-08-11）：
  1. 定式网络能不能被同时激活？
  2. 运行在不同实例里，最后的记忆能不能"同时写入"同一个快照？

实验设计（全部基于 v35.0 这一个快照的副本，不动 runs/ 主链）：

  A. 同时激活
     A1 串行基准：单实例加载 v35 → 记录激活输出（direct_next 读边 + evoke 回响）
     A2 多进程并发激活：3 个进程同时加载同一快照文件、同时回响，
        输出与基准逐项比对（每个实例独立内存副本 → 预期互不干扰）
     A3 多线程共享对象：1 个实例内 3 线程共用同一 ng 对象同时激活
        （direct_next 无状态 → 预期不变；evoke 共享 v/spikes/pre_trace
        可变状态 → 预期互相串扰）——同一实例内部并发的边界

  B. 最后记忆同时写入（两实例各学一组词对，学完一起写）
     B1 同文件并发写：2 进程各自学完 → 同时 savez 到**同一个** net.npz
        → 检查：文件能否加载？双方记忆是否都在？（预期覆盖/损坏，丢一侧）
     B2 合并写入：2 实例各学一组 → diff（相对 v35 基准）取 max 合并进
        同一快照 → 检查双方记忆是否都在（合并 = 正确的"同时写入"）

学习组（与 _probe_concurrent 同口径，槽位隔离）：
  A 组（槽0）：我 → 吃 → 苹果    B 组（槽1）：他 → 看 → 家

用法：python stage/_probe_concurrent_v35.py
留档：runs/_probe_concurrent_v35_{ts}/result.json
"""
import json
import shutil
import threading
import time
import multiprocessing as mp
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snapshot import load_snapshot, _pack_net, _net_params
from schema_net import _learn_sentence, _evoke_prefix
from _grow_v16 import direct_next_multi

ROOT = Path(__file__).resolve().parent.parent
SRC_VER = "35.0"
SRC_NPZ = ROOT / "runs" / "v35_0_20260811_044836" / "net.npz"

GROUP_A = ["我", "吃", "苹果"]     # 槽 0
GROUP_B = ["他", "看", "家"]       # 槽 1
N_ROUNDS = 5

# 同时激活探针词（全部须在 pats；脚本内自动过滤缺失）
PROBE_WORDS = ["我", "饿", "猫", "累", "他", "吃"]


# ────────────────────────────────────────────────────────────────
#  工具
# ────────────────────────────────────────────────────────────────

def n2w_of(pats):
    return {j: w for w, ns in pats.items() for j in ns}


def probe_output(ng, pats, n2w, words):
    """一次激活探针：每词 读边 top-5 + 回响激活神经元集合（确定性输出）。"""
    out = {}
    for w in words:
        nxt = direct_next_multi(ng, pats, n2w, [w], k=5)
        fired = sorted(int(x) for x in _evoke_prefix(ng, [w], pats, slot=0, steps=3))
        out[w] = {"next": [x for x, _ in nxt], "fired": fired}
    return out


def edge_by_slot(ng, pats, src, dst):
    """src 模式出边汇聚到 dst 模式的总权重，按槽位分开（跨槽读出工具）。"""
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


def net_payload(ng, vocab, pats, cursor):
    """与 save_snapshot 相同的 npz 载荷（显式写盘用，绕开版本号自动分配）。"""
    pats_json = {w: [int(x) for x in v] for w, v in pats.items()}
    return dict(
        params=json.dumps(_net_params(ng)).encode("utf-8"),
        vocab=json.dumps(list(vocab), ensure_ascii=False).encode("utf-8"),
        pats=json.dumps(pats_json, ensure_ascii=False).encode("utf-8"),
        cursor=np.asarray([int(cursor or 0)], dtype=np.int64),
        **_pack_net(ng))


def edge_check(ng, pats, src, dst, slot):
    return edge_by_slot(ng, pats, src, dst)[slot]


def evoke_ratio(ng, pats, src, dst, slot=0, steps=3):
    """注入 src → 回响 steps 步 → dst 模式神经元被激活比例（0~1）。"""
    fired = _evoke_prefix(ng, [src], pats, slot=slot, steps=steps)
    return round(sum(1 for j in pats[dst] if j in fired) / len(pats[dst]), 3)


# ────────────────────────────────────────────────────────────────
#  A2 多进程并发激活 worker（每个进程独立加载同一快照文件）
# ────────────────────────────────────────────────────────────────

def _proc_activate(words, src_npz, out_fp, ready_ev, go_ev):
    ng, vocab, pats, cursor = load_snapshot(src_npz)
    n2w = n2w_of(pats)
    ready_ev.set()                      # 加载完成，等主进程放行
    go_ev.wait(120)
    res = probe_output(ng, pats, n2w, words)
    Path(out_fp).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")


# ────────────────────────────────────────────────────────────────
#  B1 并发写 worker（各自学一组，然后同时写同一个 net.npz）
# ────────────────────────────────────────────────────────────────

def _proc_learn_write(seq, slot, src_npz, diff_fp, ready_ev, go_ev,
                      target_npz, status_fp):
    ng, vocab, pats, cursor = load_snapshot(src_npz)
    base, _, _, _ = load_snapshot(src_npz)          # diff 基准（学习前副本）
    for _ in range(N_ROUNDS):
        _learn_sentence(ng, seq, pats, slot=slot)
    diff = diff_edges(ng, base, ng.slots)
    Path(diff_fp).write_text(json.dumps(
        [[i, k, j, w] for (i, k, j), w in diff.items()], ensure_ascii=False),
        encoding="utf-8")
    payload = net_payload(ng, vocab, pats, cursor)  # 先打包再同步，写盘窗口尽量重叠
    ready_ev.set()
    go_ev.wait(120)
    try:
        np.savez_compressed(target_npz, **payload)
        status = "write_ok"
    except Exception as e:
        status = f"write_fail: {type(e).__name__}: {e}"
    Path(status_fp).write_text(json.dumps({"status": status}), encoding="utf-8")


# ────────────────────────────────────────────────────────────────
#  main
# ────────────────────────────────────────────────────────────────

def main():
    if not SRC_NPZ.exists():
        print(f"[中止] 找不到 v35 快照: {SRC_NPZ}")
        return
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT / "runs" / f"_probe_concurrent_v35_{ts}"
    base_dir = run_dir / "base"            # 单独一个快照（v35 副本）
    race_dir = run_dir / "race"
    merged_dir = run_dir / "merged"
    for d in (base_dir, race_dir, merged_dir):
        d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC_NPZ, base_dir / "net.npz")
    shutil.copy2(SRC_NPZ.parent / "meta.json", base_dir / "meta.json")
    src_npz = base_dir / "net.npz"         # 全程只用这一个快照文件

    print(f"═══ v35 单快照并发探针 ═══ 源: {SRC_NPZ.name} → {run_dir.name}")
    rep = {"meta": {"ts": ts, "version": SRC_VER, "snapshot": "base/ 单快照（v35 副本）",
                    "groups": {"A(槽0)": GROUP_A, "B(槽1)": GROUP_B},
                    "n_rounds": N_ROUNDS},
           "sections": {}}

    # ── A1 串行基准 ─────────────────────────────────────────
    ng, vocab, pats, cursor = load_snapshot(src_npz)
    n2w = n2w_of(pats)
    words = [w for w in PROBE_WORDS if w in pats]
    print(f"\n[加载] 基准: n={ng.n} 模式={len(pats)} 探针词={words}")
    t0 = time.perf_counter()
    ref = probe_output(ng, pats, n2w, words)
    rep["sections"]["A1_ref"] = {"probe_words": words,
                                 "evoke_n_neurons": {w: len(v["fired"])
                                                     for w, v in ref.items()}}
    print(f"  A1 基准完成（{time.perf_counter()-t0:.1f}s）")

    # ── A2 多进程并发激活（3 进程同时加载 + 同时回响）────────
    print("\n═══ A2 多进程并发激活（3 进程 · 同一快照文件）═══")
    ctx = mp.get_context("spawn")
    ready_evs = [ctx.Event() for _ in range(3)]
    go_ev = ctx.Event()
    procs, fps = [], []
    for k in range(3):
        fp = run_dir / f"proc{k}_out.json"
        fps.append(fp)
        p = ctx.Process(target=_proc_activate,
                        args=(words, str(src_npz), str(fp), ready_evs[k], go_ev))
        p.start()
        procs.append(p)
    # 等 3 个进程都加载完同一快照并就绪（ready 在加载后置位）
    deadline = time.time() + 180
    while time.time() < deadline and not all(e.is_set() for e in ready_evs):
        time.sleep(0.05)
    if not all(e.is_set() for e in ready_evs):
        print("[警告] 部分进程加载超时，仍放行")
    go_ev.set()                            # 同时放行：3 进程一起回响
    for p in procs:
        p.join(300)
    a2 = {"alive_after": sum(1 for p in procs if p.is_alive()),
          "outputs": {}}
    all_same = True
    for k, fp in enumerate(fps):
        res = json.loads(fp.read_text(encoding="utf-8"))
        same = res == ref
        all_same &= same
        a2["outputs"][f"proc{k}"] = {"same_as_ref": same}
        print(f"  proc{k}: 输出与基准 {'完全一致' if same else 'DIFF'}")
    a2["verdict"] = ("多进程同时激活互不干扰：3 实例输出与基准逐项一致"
                     if all_same else "存在干扰（输出与基准不一致）")
    rep["sections"]["A2"] = a2
    print(f"  结论: {a2['verdict']}")

    # ── A3 多线程共享对象（同一 ng，3 线程同时激活）─────────
    print("\n═══ A3 多线程共享对象（同一实例内 3 线程同时激活）═══")
    ng, vocab, pats, cursor = load_snapshot(src_npz)
    n2w = n2w_of(pats)
    results = [None] * 3
    barrier = threading.Barrier(3)
    match_cnt = [0] * 3

    def _thread_probe(tid):
        barrier.wait()                     # 3 线程同时起跑
        for _ in range(5):
            res = probe_output(ng, pats, n2w, words)
            if res == ref:
                match_cnt[tid] += 1

    threads = [threading.Thread(target=_thread_probe, args=(k,))
               for k in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(300)
    a3 = {"match_rounds": match_cnt,
          "verdict": ("共享对象内并发激活稳定（5 轮全同）"
                      if all(m == 5 for m in match_cnt)
                      else "共享对象内并发激活串扰（evoke 共享 v/spikes/pre_trace）")}
    rep["sections"]["A3"] = a3
    print(f"  3 线程各 5 轮 vs 基准 一致轮数: {match_cnt}")
    print(f"  结论: {a3['verdict']}")

    # ── B1 同文件并发写（2 进程同时写同一个 net.npz）─────────
    print("\n═══ B1 同文件并发写（2 进程各学一组 → 同时写同一 net.npz）═══")
    ctx = mp.get_context("spawn")
    readyA, readyB = ctx.Event(), ctx.Event()
    go_ev = ctx.Event()
    target_npz = race_dir / "net.npz"
    wA = ctx.Process(target=_proc_learn_write,
                     args=(GROUP_A, 0, str(src_npz), str(race_dir / "diff_A.json"),
                           readyA, go_ev, str(target_npz), str(race_dir / "status_A.json")))
    wB = ctx.Process(target=_proc_learn_write,
                     args=(GROUP_B, 1, str(src_npz), str(race_dir / "diff_B.json"),
                           readyB, go_ev, str(target_npz), str(race_dir / "status_B.json")))
    wA.start(); wB.start()
    # 等两个进程都学完并打包好（ready 在打包后置位，紧邻 go_ev.wait）→ 同时放行写盘
    deadline = time.time() + 300
    while time.time() < deadline and not (readyA.is_set() and readyB.is_set()):
        time.sleep(0.05)
    if not (readyA.is_set() and readyB.is_set()):
        print("[警告] 学习/打包超时，仍放行写盘")
    go_ev.set()
    for p in (wA, wB):
        p.join(300)

    b1 = {"status": {}}
    for name in ("A", "B"):
        st = json.loads((race_dir / f"status_{name}.json").read_text(encoding="utf-8"))
        b1["status"][name] = st["status"]
        print(f"  {name} 组写盘: {st['status']}")

    # 检查最终文件：能否加载？双方记忆在不在？
    b1["loadable"] = True
    try:
        ng_r, vocab_r, pats_r, cursor_r = load_snapshot(target_npz)
        b1["loadable"] = True
        b1["edges"] = {
            "A_我→吃(槽0)": edge_check(ng_r, pats_r, "我", "吃", 0),
            "A_吃→苹果(槽0)": edge_check(ng_r, pats_r, "吃", "苹果", 0),
            "B_他→看(槽1)": edge_check(ng_r, pats_r, "他", "看", 1),
            "B_看→家(槽1)": edge_check(ng_r, pats_r, "看", "家", 1),
        }
    except Exception as e:
        b1["loadable"] = False
        b1["error"] = f"{type(e).__name__}: {e}"
    # 基准对照（v35 原有边强度）
    base_edges = {
        "A_我→吃(槽0)": edge_check(ng, pats, "我", "吃", 0),
        "A_吃→苹果(槽0)": edge_check(ng, pats, "吃", "苹果", 0),
        "B_他→看(槽1)": edge_check(ng, pats, "他", "看", 1),
        "B_看→家(槽1)": edge_check(ng, pats, "看", "家", 1),
    }
    b1["base_edges"] = base_edges
    if b1["loadable"]:
        b1["both_memories"] = all(
            b1["edges"][k] > base_edges[k] for k in base_edges)
        b1["verdict"] = ("文件可加载且双方记忆都在（偶然串行？）"
                         if b1["both_memories"]
                         else "至少一侧记忆丢失 / 被覆盖（最后写入者胜或文件损坏）")
    else:
        b1["verdict"] = "文件损坏：npz 无法加载（并发写同一路径）"
    rep["sections"]["B1"] = b1
    print(f"  最终文件可加载: {b1['loadable']}")
    if b1["loadable"]:
        for k, v in b1["edges"].items():
            print(f"    {k}: 最终={v}（基准={base_edges[k]}）")
    print(f"  结论: {b1['verdict']}")

    # ── B2 合并写入（diff 取 max 合并进同一快照）─────────────
    print("\n═══ B2 合并写入（diff 合并 → 单快照，双方记忆共存）═══")
    ng_m, vocab_m, pats_m, cursor_m = load_snapshot(src_npz)
    diffs = {}
    for name in ("A", "B"):
        rows = json.loads((race_dir / f"diff_{name}.json").read_text(encoding="utf-8"))
        diffs[name] = {(i, k, j): w for i, k, j, w in rows}
    n_apply = 0
    for name, diff in diffs.items():
        for (i, k, j), w in diff.items():
            cur = ng_m.W_out[i][k].get(j, 0.0)
            if w > cur:
                ng_m.W_out[i][k][j] = w
                n_apply += 1
    merged_npz = merged_dir / "net.npz"
    np.savez_compressed(merged_npz, **net_payload(ng_m, vocab_m, pats_m, cursor_m))
    shutil.copy2(SRC_NPZ.parent / "meta.json", merged_dir / "meta.json")

    ng_f, _, pats_f, _ = load_snapshot(merged_npz)
    b2 = {
        "diff_A": len(diffs["A"]), "diff_B": len(diffs["B"]), "applied": n_apply,
        "edges": {
            "A_我→吃(槽0)": edge_check(ng_f, pats_f, "我", "吃", 0),
            "A_吃→苹果(槽0)": edge_check(ng_f, pats_f, "吃", "苹果", 0),
            "B_他→看(槽1)": edge_check(ng_f, pats_f, "他", "看", 1),
            "B_看→家(槽1)": edge_check(ng_f, pats_f, "看", "家", 1),
        },
        "evoke_ratio": {
            "注入我→吃(槽0)": evoke_ratio(ng_f, pats_f, "我", "吃", slot=0),
            "注入吃→苹果(槽0)": evoke_ratio(ng_f, pats_f, "吃", "苹果", slot=0),
            "注入他→看(槽1)": evoke_ratio(ng_f, pats_f, "他", "看", slot=1),
            "注入看→家(槽1)": evoke_ratio(ng_f, pats_f, "看", "家", slot=1),
        },
    }
    b2["both_memories"] = all(
        b2["edges"][k] > base_edges[k] for k in base_edges)
    b2["verdict"] = ("合并成功：单快照内 A/B 双方记忆共存"
                     if b2["both_memories"] else "合并后仍有缺失")
    rep["sections"]["B2"] = b2
    print(f"  diff: A={len(diffs['A'])} 条 / B={len(diffs['B'])} 条，应用 {n_apply} 条")
    for k, v in b2["edges"].items():
        print(f"    {k}: 合并后={v}（基准={base_edges[k]}）")
    print(f"  唤起比例: {b2['evoke_ratio']}")
    print(f"  结论: {b2['verdict']}")

    # ── 汇总 + 留档 ─────────────────────────────────────────
    rep["sections"]["summary"] = {
        "A2_多进程同时激活": a2["verdict"],
        "A3_同实例多线程": a3["verdict"],
        "B1_同文件并发写": b1["verdict"],
        "B2_合并写入": b2["verdict"],
    }
    (run_dir / "result.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n═══ 汇总 ═══")
    for k, v in rep["sections"]["summary"].items():
        print(f"  {k}: {v}")
    print(f"\n留档: {run_dir}")


if __name__ == "__main__":
    main()
