# -*- coding: utf-8 -*-
"""定式网络模型版本链统一机制（时间戳快照 + 语义版本号 + 父子追溯 + 回退训练）。

需求（用户 2026-08-09）：
  "a 是第一版模型，经过训练产生 a+1，但 a 还是存在；a+1 再训练后出现 a+2，
   现在就有 a、a+1、a+2；如果 a+2 有问题，就可以用 a+1 来回退训练。
   回退再训练的时候，a+1 再训练就是 a+2.1，这样就可以对比 a+2 和 a+2.1 的区别。"

即：模型像软件版本（MAJOR.MINOR）一样管理——
  - 每次训练 = 产生一个新版本，旧版本永不删除（可追溯）
  - 正常续训：parent.MAJOR+1.0（a → a+1 → a+2 → a+3）
  - 回退训练：parent.MAJOR+1 的同代变体（a+2 出问题 → 回退 a+1 再训 = a+2.1，
    a+2 与 a+2.1 平级并存、可直接对比；再回退再训 = a+2.2 …）

版本号语义（类比软件版本）：
  a     = 1.0（根）
  a+1   = 2.0（parent=1.0）
  a+2   = 3.0（parent=2.0）
  a+2.1 = 3.1（回退 parent=2.0 再训练，与 a+2 同 major 可对比）

机制：
  - 目录 runs/v{M}_{N}_{时间戳}/（版本号 + 时间戳）
  - meta.json / 追溯索引 runs/index.jsonl 记录 major/minor/version/parent_version
  - save_snapshot(parent=None) → 缺省继承最新版本（正常链式增长）；
                              显式传 parent="2.0" → 回退训练（同代变体 +0.1）
  - load_version("3.1")        → 按版本号恢复（回退入口）
  - version_chain()            → 从任意版本回溯到根的完整链
  - 双后端：SparseSchemaNet（W_out 稀疏）与 SchemaNet（W 稠密）自动识别

用法：
    from snapshot import save_snapshot, load_version, version_chain
    save_snapshot(ng, tag="1.0 初始训练", vocab=words, pats=pats)        # a
    save_snapshot(ng, tag="2.0 续训",     vocab=words, pats=pats)        # a+1
    save_snapshot(ng, tag="3.0 续训",     vocab=words, pats=pats)        # a+2
    ng2, vocab, pats, cursor = load_version("2.0")                       # 回退到 a+1
    save_snapshot(ng2, parent="2.0", tag="3.1 回退续训",
                  vocab=vocab, pats=pats)                                # a+2.1（对比 a+2）
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
                  "stdp_pre", "stdp_neg", "trace_decay", "refractory", "learn_gate",
                  # v13.2 机制参数（2026-08-10 修复：此前缺字段 → 新机制网络
                  # 存/载后静默回退默认关闭，语义不可恢复。gain 是数组，不入
                  # params json，需 _pack_net 另存——未实施，见速度第二波报告）
                  "inh_loose", "std_dep", "std_rec", "edge_min", "inh_norm",
                  "refract_clear")


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
                    # vals 存 float64（2026-08-10 修复）：原 float32 使会话内
                    # 新学边（f64 增量）存载后截断 → 日志重放/版本恢复无法逐位
                    # 一致（对拍 8895 差异边实证）。旧快照（f32）载入兼容。
                    vals=np.array(vals, dtype=np.float64),
                    gain=np.array(ng.gain, dtype=np.float64))   # 增益调制数组（2026-08-10：此前不入快照，载后丢失）
    return dict(W=ng.W.astype(np.float32))


def _restore_net(z):
    params = json.loads(z["params"].tobytes().decode("utf-8"))
    rng = np.random.default_rng(42)   # 状态无关（W 已恢复，rng 仅后续噪声用）
    if "W" in z:
        from schema_net import SchemaNet
        ng = SchemaNet(rng=rng, **params)
        ng.W = z["W"].astype(np.float64)
    else:
        from sparse_net import SparseSchemaNet, _rows_from_arrays
        ng = SparseSchemaNet(rng=rng, **params)
        src_i, slot_k, dst_j, vals = z["src_i"], z["slot_k"], z["dst_j"], z["vals"]
        _rows_from_arrays(ng, src_i, slot_k, dst_j, vals)   # 批量构建（免逐条 dict 插入）
        if "gain" in z:   # 旧快照无 gain 字段 → 保持默认全 1（向后兼容）
            ng.gain = z["gain"].astype(np.float64)
    return ng


# ────────────────────────────────────────────────────────────────
#  版本管理（读写 index.jsonl）
# ────────────────────────────────────────────────────────────────

def snapshot_index(base=None):
    """追溯索引：全部版本按产生顺序（追加顺序 = 时间顺序）。

    只收带 version 的记录（v2.1 版本化之前的旧格式行无 version/major/minor，
    不参与语义版本链；其快照目录仍在，追溯无损）。"""
    idx = (base or RUNS) / "index.jsonl"
    if not idx.exists():
        return []
    rows = []
    for line in idx.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if "version" in r:
                rows.append(r)
    return rows


# ── 版本号（MAJOR.MINOR，类比软件版本）──

def _parse_version(v):
    """'3.1' → (3, 1)；int/缺省 minor → (n, 0)。"""
    s = str(v)
    parts = s.split(".")
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    return major, minor


def _v_str(major, minor):
    return f"{major}.{minor}"


def _new_version(parent_v, rows):
    """由父版本推出新版本号。

    正常续训（parent 存在）：major = parent.major + 1，minor 从 0 起
      （a+1 = parent 的 major+1.0）。
    回退训练：同一 major 下已存在的最大 minor + 1 → 与出问题的版本
      同 major 平级（a+2 = 3.0，回退 a+1 再训 = 3.1，可直接对比）。
    """
    if parent_v is None:                       # 根版本
        return 1, 0
    major = parent_v[0] + 1
    minors = [r["minor"] for r in rows if r.get("major") == major]
    return major, (max(minors) + 1 if minors else 0)


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
                  vocab=None, pats=None, cursor=None, base=None,
                  consolidated=None, validation=None):
    """训练后产生一个新版本：runs/v{M}_{N}_{时间戳}/net.npz + meta.json + result.json，
    追加追溯索引 runs/index.jsonl。

    参数：
        ng        网络（SparseSchemaNet 或 SchemaNet）
        parent    父版本号（'1.0' / '3.1'）；缺省 = 最新版本（正常链式增长
                  a→a+1→a+2）；显式传 N = 回退训练（同代变体：a+2 出问题
                  → 回退 a+1 再训 = a+2.1，与 a+2 平级可对比）
        tag       版本语义标签（如 "Stage2 短句跟读"）
        data_fp   训练数据指纹（文件路径/时间戳，追溯数据版本）
        metrics   验收指标 dict（记入 result.json 与追溯索引）
        vocab     词表 list
        pats      词→神经元模式字典 {word: [k 个神经元]}（v2.1 分配制）
        cursor    神经元分配游标 int（v2.1 扩容边界）
        consolidated  句子固化表（训练沉淀，2026-08-11）：{触发词:
                      [(toks, slots, ctype), ...]}
        validation    条件化验证表（对错标准）：{(qtype, kw, 句): (对, 错)}
        ——两者入 meta.json（load_consolidated 恢复）；槽位神经元随
        net.npz 的 W_out 持久化（孤儿边 + 注册表 = 完整恢复）
    返回：快照目录 Path。
    """
    base = base or RUNS
    base.mkdir(parents=True, exist_ok=True)
    rows = snapshot_index(base)
    if parent is None:
        parent_v = (rows[-1]["major"], rows[-1]["minor"]) if rows else None
    else:
        parent_v = _parse_version(parent)
    major, minor = _new_version(parent_v, rows)
    version = _v_str(major, minor)
    parent_str = _v_str(*parent_v) if parent_v else None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = _next_dir(base, f"v{major}_{minor}_{ts}")
    out.mkdir(parents=True, exist_ok=True)
    pats_json = {w: [int(x) for x in v] for w, v in (pats or {}).items()}

    np.savez_compressed(
        out / "net.npz",
        params=json.dumps(_net_params(ng)).encode("utf-8"),
        vocab=json.dumps(list(vocab or []), ensure_ascii=False).encode("utf-8"),
        pats=json.dumps(pats_json, ensure_ascii=False).encode("utf-8"),
        cursor=np.asarray([int(cursor or 0)], dtype=np.int64),
        ** _pack_net(ng))

    meta = {"version": version, "major": major, "minor": minor,
            "parent_version": parent_str, "ts": ts, "tag": tag,
            "net_kind": net_kind(ng), "n": ng.n, "slots": ng.slots,
            "learn_gate": ng.learn_gate, "data_fp": data_fp or "",
            "vocab_size": len(vocab or []), "pats_size": len(pats or {}),
            "cursor": int(cursor or 0)}
    if consolidated:
        meta["consolidated"] = consolidated
    if validation:
        meta["validation"] = [[list(k), list(v)] for k, v in validation.items()]
    (out / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "result.json").write_text(json.dumps(
        {"version": version, "parent_version": parent_str, "tag": tag, "ts": ts,
         "metrics": metrics or {}, "meta": meta},
        ensure_ascii=False, indent=1), encoding="utf-8")

    with open(base / "index.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"version": version, "major": major, "minor": minor,
                            "parent_version": parent_str,
                            "ts": ts, "dir": out.name, **meta,
                            "metrics": metrics or {}},
                           ensure_ascii=False) + "\n")
    print(f"[snapshot] v{version} (parent={parent_str})  {out}  tag={tag!r}")
    return out


# ────────────────────────────────────────────────────────────────
#  加载 / 追溯 / 回退（读）
# ────────────────────────────────────────────────────────────────

def load_snapshot(path):
    """恢复快照：返回 (ng, vocab, pats, cursor)。path 为目录或 net.npz。"""
    p = Path(path)
    if p.is_dir():
        p = p / "net.npz"
    z = np.load(p, allow_pickle=False)
    ng = _restore_net(z)
    vocab = json.loads(z["vocab"].tobytes().decode("utf-8"))
    pats = json.loads(z["pats"].tobytes().decode("utf-8")) if "pats" in z else {}
    pats = {w: [int(x) for x in v] for w, v in pats.items()}
    cursor = int(z["cursor"][0]) if "cursor" in z else 0
    return ng, vocab, pats, cursor


def load_version(version, base=None):
    """按版本号恢复（回退入口）：返回 (ng, vocab, pats, cursor)。
    version 接受 '1.0' / '3.1' / 3（→ 3.0）。"""
    base = base or RUNS
    want = _v_str(*_parse_version(version))
    for r in snapshot_index(base):
        if r.get("version") == want:
            return load_snapshot(base / r["dir"] / "net.npz")
    raise FileNotFoundError(f"版本 v{want} 不存在（见 runs/index.jsonl）")


def load_consolidated(version, base=None):
    """恢复训练沉淀（2026-08-11）：固化表 + 验证表（meta.json）。
    返回 (consolidated, validation)；快照无沉淀 → ({}, {})。
    与 load_version 配套：net.npz（W_out 槽位边）+ meta.json（注册表）
    = 完整恢复训练后状态（固化句可读、对错标准可用）。"""
    base = base or RUNS
    want = _v_str(*_parse_version(version))
    for r in snapshot_index(base):
        if r.get("version") == want:
            meta_fp = base / r["dir"] / "meta.json"
            if not meta_fp.exists():
                return {}, {}
            meta = json.loads(meta_fp.read_text(encoding="utf-8"))
            cons = meta.get("consolidated") or {}
            cons = {k: [tuple(t) for t in v] for k, v in cons.items()}
            val = meta.get("validation") or []
            val = {(k[0], k[1], tuple(k[2])): (v[0], v[1]) for k, v in val}
            return cons, val
    raise FileNotFoundError(f"版本 v{want} 不存在（见 runs/index.jsonl）")


def latest_snapshot(base=None):
    """最近版本（最新训练产物）的 net.npz 路径（用于续训）。"""
    rows = snapshot_index(base)
    if not rows:
        return None
    return (base or RUNS) / rows[-1]["dir"] / "net.npz"


def version_chain(version=None, base=None):
    """版本链：从指定版本（缺省最新）回溯 parent 到根，返回逐级记录列表。"""
    base = base or RUNS
    rows = {r.get("version"): r for r in snapshot_index(base)}
    if not rows:
        return []
    v = version if version is not None else _v_str(*max(
        (_parse_version(k) for k in rows), key=lambda t: (t[0], t[1])))
    v = _v_str(*_parse_version(v))
    chain = []
    seen = set()
    while v is not None and v in rows and v not in seen:
        chain.append(rows[v])
        seen.add(v)
        v = rows[v].get("parent_version")
    return chain
