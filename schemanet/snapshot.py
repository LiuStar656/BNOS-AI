# -*- coding: utf-8 -*-
"""定式网络模型版本链统一机制（时间戳快照 + 版本号 + 父子追溯 + 回退训练）。

需求（用户 2026-08-09）：
  "a 是第一版模型，经过训练产生 a+1，但 a 还是存在；a+1 再训练后出现 a+2，
   现在就有 a、a+1、a+2；如果 a+2 有问题，就可以用 a+1 来回退训练。"

即：模型像 git 版本一样管理——
  - 每次训练 = 产生一个新版本（基于当前模型继续学习）
  - 旧版本永不删除（可追溯）
  - 任意历史版本可回退续训（产生新版本，旧版本仍保留）

机制：
  - 目录 runs/v{版本号}_{时间戳}/，版本号全局单调递增（a → a+1 → a+2 …）
  - meta.json / 追溯索引 runs/index.jsonl 记录 version 与 parent_version（父子链）
  - save_snapshot(parent=None)  → parent 缺省继承最新版本（正常链式增长）；
                                  显式传 parent=N → 回退训练（从版本 N 分支）
  - load_version(N)            → 按版本号恢复（回退入口）
  - version_chain()            → 从任意版本回溯到根的完整链
  - 双后端：SparseSchemaNet（W_out 稀疏）与 SchemaNet（W 稠密）自动识别

用法：
    from snapshot import save_snapshot, load_version, version_chain
    save_snapshot(ng, tag="v1 初始训练", vocab=words, pats=pats)          # a
    save_snapshot(ng, tag="v2 续训",     vocab=words, pats=pats)          # a+1（parent=v1）
    save_snapshot(ng, tag="v3 续训",     vocab=words, pats=pats)          # a+2（parent=v2）
    ng2, vocab, pats, cursor = load_version(2)                            # 回退到 a+1
    # ... 继续训练 ng2 ...
    save_snapshot(ng2, parent=2, tag="v4 回退续训", vocab=vocab, pats=pats)  # 分支
    for r in version_chain():       # 最新 → 根，逐级可追溯
        print(r["version"], "←", r["parent_version"], r["tag"])
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np

RUNS = Path(__file__).resolve().parent / "runs"

_PARAMS_FIELDS = ("n", "slots", "theta", "membrane_decay", "eta", "w_max", "wta_k",
                  "noise_p", "noise_amp", "weight_decay", "slot_cap",
                  "stdp_pre", "stdp_neg", "trace_decay", "refractory", "learn_gate")


# ────────────────────────────────────────────────────────────────
#  网络打包（sparse/dense 双后端）
# ────────────────────────────────────────────────────────────────

def _net_params(ng):
    return {f: getattr(ng, f) for f in _PARAMS_FIELDS if hasattr(ng, f)}


def net_kind(ng):
    return "sparse" if hasattr(ng, "W_out") else "dense"


def _pack_net(ng):
    """网络 → npz 附加字段（不含 params/vocab/pats/cursor，由调用方统一写）。"""
    if net_kind(ng) == "sparse":
        src_i, slot_k, dst_j, vals = [], [], [], []
        for i in range(ng.n):
            for k in range(ng.slots):
                for j, w in ng.W_out[i][k].items():
                    src_i.append(i)
                    slot_k.append(k)
                    dst_j.append(j)
                    vals.append(w)
        return dict(src_i=np.array(src_i, dtype=np.int32),
                    slot_k=np.array(slot_k, dtype=np.int8),
                    dst_j=np.array(dst_j, dtype=np.int32),
                    vals=np.array(vals, dtype=np.float32))
    return dict(W=ng.W.astype(np.float32))


def _restore_net(z):
    params = json.loads(z["params"].tobytes().decode("utf-8"))
    rng = np.random.default_rng(42)   # 状态无关（W 已恢复，rng 仅后续噪声用）
    if "W" in z:
        from schema_net import SchemaNet
        ng = SchemaNet(rng=rng, **params)
        ng.W = z["W"].astype(np.float64)
    else:
        from sparse_net import SparseSchemaNet
        ng = SparseSchemaNet(rng=rng, **params)
        src_i, slot_k, dst_j, vals = z["src_i"], z["slot_k"], z["dst_j"], z["vals"]
        for i, k, j, w in zip(src_i, slot_k, dst_j, vals):
            ng.W_out[int(i)][int(k)][int(j)] = float(w)
        ng.invalidate_edge_cache()
    return ng


# ────────────────────────────────────────────────────────────────
#  版本管理（读写 index.jsonl）
# ────────────────────────────────────────────────────────────────

def snapshot_index(base=None):
    """追溯索引：全部版本按产生顺序（追加顺序 = 时间顺序）。"""
    idx = (base or RUNS) / "index.jsonl"
    if not idx.exists():
        return []
    rows = []
    for line in idx.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _next_version(base):
    rows = snapshot_index(base)
    vers = [r.get("version", 0) for r in rows]
    return (max(vers) if vers else 0) + 1


# ────────────────────────────────────────────────────────────────
#  快照（写）
# ────────────────────────────────────────────────────────────────

def _next_dir(base, name):
    out = base / name
    n = 1
    while out.exists():
        out = base / f"{name}_{n}"
        n += 1
    return out


def save_snapshot(ng, *, parent=None, tag="", data_fp=None, metrics=None,
                  vocab=None, pats=None, cursor=None, base=None):
    """训练后产生一个新版本：runs/v{版本}_{时间戳}/net.npz + meta.json + result.json，
    追加追溯索引 runs/index.jsonl。

    参数：
        ng        网络（SparseSchemaNet 或 SchemaNet）
        parent    父版本号 int；缺省 = 最新版本（正常链式增长，a→a+1→a+2）；
                  显式传 N = 回退到版本 N 训练出的分支
        tag       版本语义标签（如 "Stage2 短句跟读"）
        data_fp   训练数据指纹（文件路径/时间戳，追溯数据版本）
        metrics   验收指标 dict（记入 result.json 与追溯索引）
        vocab     词表 list
        pats      词→神经元模式字典 {word: [k 个神经元]}（v2.1 分配制）
        cursor    神经元分配游标 int（v2.1 扩容边界）
    返回：快照目录 Path。
    """
    base = base or RUNS
    base.mkdir(parents=True, exist_ok=True)
    version = _next_version(base)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = _next_dir(base, f"v{version}_{ts}")
    if parent is None:
        rows = snapshot_index(base)
        parent = rows[-1].get("version") if rows else None
    pats_json = {w: [int(x) for x in v] for w, v in (pats or {}).items()}

    np.savez_compressed(
        out / "net.npz",
        params=json.dumps(_net_params(ng)).encode("utf-8"),
        vocab=json.dumps(list(vocab or []), ensure_ascii=False).encode("utf-8"),
        pats=json.dumps(pats_json, ensure_ascii=False).encode("utf-8"),
        cursor=np.asarray([int(cursor or 0)], dtype=np.int64),
        ** _pack_net(ng))

    meta = {"version": version, "parent_version": parent, "ts": ts, "tag": tag,
            "net_kind": net_kind(ng), "n": ng.n, "slots": ng.slots,
            "learn_gate": ng.learn_gate, "data_fp": data_fp or "",
            "vocab_size": len(vocab or []), "pats_size": len(pats or {}),
            "cursor": int(cursor or 0)}
    (out / "meta.json").write_text(
        json.dumps(meta, ensure_asc