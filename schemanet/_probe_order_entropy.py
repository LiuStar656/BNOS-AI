# -*- coding: utf-8 -*-
"""结构有序度诊断 v2——"有向脉冲熵减"的可计算验证（全版本 + 段内分析）。

Phase 1（静态，全版本链）：强度分布 Shannon 熵 H_strength / 偏度 skew /
  饱和与弱边占比 / 出度 top1% 占比
Phase 2（动态，全版本）：注入词测分支参数 σ（候选数比率）
Phase 3（段内，稳定词跟踪）：各版本稳定词模式神经元的传出边强度
  （fan-out / 平均强度 / 强边占比 / 强度熵）→ 关键路径是否随成长集中
Phase 4（跃迁，共同边分析）：v16→v17（扩量）与 v32→v33（条件化验证门）
  相邻版本的共同边强度变化（强化/弱化/不变 + 新增/删除）→ 经历是否在
  强化既有路径（有向集中）而非制造随机新边

用法：cd schemanet && python _probe_order_entropy.py
输出：runs/_order_entropy.json + runs/fig_order_entropy.png + 控制台表格
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from snapshot import RUNS, snapshot_index, load_snapshot

BINS = 50
OUT_JSON = RUNS / "_order_entropy.json"
OUT_FIG = RUNS / "fig_order_entropy.png"
STABLE_CANDIDATES = ("我", "吃", "了", "是", "的", "猫", "水", "喜欢", "不要")
JUMP_PAIRS = [("16.0", "17.0"), ("32.0", "33.0")]


# ────────────────────────────────────────────────────────────────
#  Phase 1：静态度量
# ────────────────────────────────────────────────────────────────

def _strength_entropy(w):
    """log 空间直方图 Shannon 熵（归一化 H/log(bins)）。全等值 → 0。
    只取 w>0（负边为 RL 归因处罚产物，统计上无意义且 log10 无定义）。"""
    w = w[w > 0]
    if len(w) == 0:
        return 0.0
    lo, hi = np.log10(w.min()), np.log10(w.max())
    if not np.isfinite(lo) or not np.isfinite(hi) or hi - lo < 1e-9:
        return 0.0
    hist, _ = np.histogram(np.log10(w), bins=BINS, range=(lo, hi))
    p = hist / hist.sum()
    p = p[p > 0]
    return float(-np.sum(p * np.log(p)) / np.log(BINS))


def _skew(x):
    n = len(x)
    if n < 3:
        return 0.0
    s = x.std()
    if s == 0:
        return 0.0
    return float(np.mean((x - x.mean()) ** 3) / s ** 3)


def static_metrics(npz_path, stable_idx=None):
    z = np.load(npz_path, allow_pickle=False)
    params = json.loads(z["params"].tobytes().decode("utf-8"))
    n = int(params.get("n", 0))
    slots = int(params.get("slots", 0))
    if "vals" in z:                       # sparse 快照
        vals = z["vals"].astype(np.float64)
        src_i = z["src_i"].astype(np.int64)
    else:                                 # dense 旧快照（W 矩阵）
        W = z["W"].astype(np.float64)
        idx = np.nonzero(W)
        vals = W[idx]
        src_i = idx[0].astype(np.int64)
    E = len(vals)
    m = {
        "n": n, "slots": slots, "E": int(E),
        "w_mean": float(vals.mean()) if E else 0.0,
        "w_max": float(vals.max()) if E else 0.0,
        "sat_ratio": float((vals >= 1.99).mean()) if E else 0.0,
        "weak_ratio": float((vals < 0.5).mean()) if E else 0.0,
        "neg_edges": int((vals < 0).sum()),
        "skew": _skew(vals) if E else 0.0,
        "H_strength": _strength_entropy(vals) if E else 0.0,
    }
    if E:
        deg = np.bincount(src_i, minlength=n)
        d = deg[deg > 0]
        p = d / d.sum()
        m["H_deg"] = float(-np.sum(p * np.log(p)))
        order = np.sort(d)[::-1]
        k = max(1, int(round(len(order) * 0.01)))
        m["deg_top1pct_share"] = float(order[:k].sum() / order.sum())
    else:
        m["H_deg"] = 0.0
        m["deg_top1pct_share"] = 0.0
    # Phase 3：稳定词传出边（静态直读，无需加载网络）
    if stable_idx is not None and len(stable_idx) > 0 and E:
        sel = np.isin(src_i, np.fromiter(stable_idx, dtype=np.int64))
        if sel.sum() > 0:
            ws = vals[sel]
            m["pw_fanout"] = int(sel.sum())
            m["pw_wmean"] = float(ws.mean())
            m["pw_strong_ratio"] = float((ws >= 1.0).mean())
            m["pw_H"] = _strength_entropy(ws)
    return m


# ────────────────────────────────────────────────────────────────
#  Phase 2：动态 σ（全版本）
# ────────────────────────────────────────────────────────────────

def _cand_count(ng):
    vmax = ng.v.max(axis=1) if ng.v.ndim == 2 else ng.v
    if hasattr(ng, "refractory_left"):
        return int(((vmax >= ng.theta) & (ng.refractory_left == 0)).sum())
    return int((vmax >= ng.theta).sum())


def dynamic_sigma(ng, pats, words, steps=4):
    """注入词 → 跑 steps 步 → σ = 相邻候选数比率均值（0/0 跳过）。"""
    from schema_net import build_pulse
    sigmas = []
    for w in words:
        idxs = pats.get(w)
        if not idxs:
            continue
        ng.v[:] = 0.0
        ng.spikes[:] = 0.0
        if hasattr(ng, "pre_trace"):
            ng.pre_trace[:] = 0.0
        if hasattr(ng, "refractory_left"):
            ng.refractory_left[:] = 0
        ng.step(build_pulse(ng.n, idxs), slot=0)
        prev = _cand_count(ng)
        for _ in range(steps):
            ng.step(np.zeros(ng.n), slot=0)
            cur = _cand_count(ng)
            if prev > 0:
                sigmas.append(cur / prev)
            prev = cur
    return float(np.mean(sigmas)) if sigmas else float("nan")


# ────────────────────────────────────────────────────────────────
#  Phase 4：共同边强度变化（关键跃迁）
# ────────────────────────────────────────────────────────────────

def _key(src, slot, dst, n_max):
    return (src.astype(np.int64) * 16 + slot.astype(np.int64)) * (n_max + 1) + dst.astype(np.int64)


def common_edge_delta(npz_a, npz_b, sample_mod=8, n_max=200000):
    """抽样 src % sample_mod == 0 的边，统计共同边 w 变化与新增/删除。"""
    za, zb = np.load(npz_a, allow_pickle=False), np.load(npz_b, allow_pickle=False)
    if "vals" not in za or "vals" not in zb:
        return None

    def prep(z):
        src = z["src_i"].astype(np.int64)
        slot = z["slot_k"].astype(np.int64)
        dst = z["dst_j"].astype(np.int64)
        vals = z["vals"].astype(np.float64)
        keep = src % sample_mod == 0
        src, slot, dst, vals = src[keep], slot[keep], dst[keep], vals[keep]
        k = _key(src, slot, dst, n_max)
        o = np.argsort(k, kind="stable")
        return k[o], vals[o]

    ka, va = prep(za)
    kb, vb = prep(zb)
    common = np.intersect1d(ka, kb)
    ia = np.searchsorted(ka, common)
    ib = np.searchsorted(kb, common)
    wa, wb = va[ia], vb[ib]
    eps = 1e-9
    up = int((wb - wa > eps).sum())
    down = int((wa - wb > eps).sum())
    same = len(common) - up - down
    return {
        "sampled_a": int(len(ka)), "sampled_b": int(len(kb)),
        "common": int(len(common)),
        "up_ratio": up / len(common) if len(common) else 0.0,
        "down_ratio": down / len(common) if len(common) else 0.0,
        "same_ratio": same / len(common) if len(common) else 0.0,
        "mean_dw": float((wb - wa).mean()) if len(common) else 0.0,
        "added_ratio": (len(kb) - len(common)) / len(kb) if len(kb) else 0.0,
        "deleted_ratio": (len(ka) - len(common)) / len(ka) if len(ka) else 0.0,
    }


# ────────────────────────────────────────────────────────────────
#  主流程
# ────────────────────────────────────────────────────────────────

def main():
    rows = snapshot_index()
    if not rows:
        print("runs/index.jsonl 无版本记录")
        return
    versions = sorted(rows, key=lambda r: (r["major"], r["minor"]))
    reps = {}
    for r in versions:
        if r["major"] not in reps:
            reps[r["major"]] = r
    chain = [reps[k] for k in sorted(reps)]

    # 稳定词：v2 起的 pats 交集
    pats_sets = {}
    for r in chain:
        npz = RUNS / r["dir"] / "net.npz"
        if not npz.exists():
            continue
        z = np.load(npz, allow_pickle=False)
        if "pats" in z:
            pats_sets[r["version"]] = set(json.loads(z["pats"].tobytes().decode("utf-8")).keys())
    common_words = None
    for w in STABLE_CANDIDATES:
        if all(w in s for s in pats_sets.values()):
            common_words = w
            break
    stable_idx = None
    if common_words:
        all_idx = set()
        for r in chain:
            npz = RUNS / r["dir"] / "net.npz"
            if not npz.exists():
                continue
            z = np.load(npz, allow_pickle=False)
            if "pats" in z:
                all_idx.update(json.loads(z["pats"].tobytes().decode("utf-8")).get(common_words, []))
        stable_idx = all_idx

    print("版本链（主版本 %d 个） 稳定词=%s 模式神经元=%d"
          % (len(chain), common_words, len(stable_idx or [])))
    results = []
    for i, r in enumerate(chain):
        npz = RUNS / r["dir"] / "net.npz"
        if not npz.exists():
            print("  跳过（无 net.npz）：v%s %s" % (r["version"], r["dir"]))
            continue
        m = static_metrics(npz, stable_idx)
        rec = {
            "version": r["version"], "tag": r.get("tag", ""),
            "parent": r.get("parent_version"), "E": m["E"], "n": m["n"],
            "w_mean": m["w_mean"], "w_max": m["w_max"],
            "sat_ratio": m["sat_ratio"], "weak_ratio": m["weak_ratio"],
            "neg_edges": m["neg_edges"],
            "skew": m["skew"], "H_strength": m["H_strength"],
            "H_deg": m["H_deg"], "deg_top1pct_share": m["deg_top1pct_share"],
        }
        if "pw_fanout" in m:
            rec.update(pw_fanout=m["pw_fanout"], pw_wmean=m["pw_wmean"],
                       pw_strong_ratio=m["pw_strong_ratio"], pw_H=m["pw_H"])
        # Phase 2：全版本动态 σ
        ng, vocab, pats, cursor = load_snapshot(npz)
        pw = [w for w in ("我", "吃", "石头", "痛", "不要", "了", "是", "的", "猫", "水")
              if w in pats][:5]
        if not pw:
            pw = list(pats.keys())[:5]
        rec["sigma"] = dynamic_sigma(ng, pats, pw)
        results.append(rec)
        pwline = (" fanout=%8d pw_w=%.3f strong=%4.2f" % (rec["pw_fanout"], rec["pw_wmean"],
                   rec["pw_strong_ratio"])) if "pw_fanout" in rec else ""
        print("v%-4s σ=%6.2f Hstr=%.3f skew=%7.1f top1%%=%.3f E=%9d%s  %s"
              % (rec["version"], rec["sigma"], rec["H_strength"], rec["skew"],
                 rec["deg_top1pct_share"], rec["E"], pwline, (rec["tag"] or "")[:30]))

    # Phase 4：关键跃迁共同边
    jumps = {}
    by_v = {r["version"]: r for r in chain}
    for va, vb in JUMP_PAIRS:
        if va in by_v and vb in by_v:
            na = RUNS / by_v[va]["dir"] / "net.npz"
            nb = RUNS / by_v[vb]["dir"] / "net.npz"
            j = common_edge_delta(na, nb)
            if j:
                jumps["%s→%s" % (va, vb)] = j
                print("\n跃迁 %s→%s：共同边 %d 条（抽样 %d/%d）"
                      % (va, vb, j["common"], j["sampled_a"], j["sampled_b"]))
                print("  强化 %.1f%% / 弱化 %.1f%% / 不变 %.1f%%  Δw均值 %+.4f  新增占比 %.1f%% 删除占比 %.1f%%"
                      % (j["up_ratio"] * 100, j["down_ratio"] * 100, j["same_ratio"] * 100,
                         j["mean_dw"], j["added_ratio"] * 100, j["deleted_ratio"] * 100))

    OUT_JSON.write_text(json.dumps({"versions": results, "jumps": jumps},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n结果 → %s" % OUT_JSON)

    # 画图
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
        plt.rcParams["axes.unicode_minus"] = False
        vers = [r["version"] for r in results]
        x = np.arange(len(vers))
        fig, ax1 = plt.subplots(figsize=(11, 6))
        ax1.plot(x, [r["H_strength"] for r in results], "o-", color="tab:blue",
                 label="H_strength（归一化）")
        ax1.plot(x, [r["skew"] for r in results], "s-", color="tab:orange",
                 label="skew（强度偏度）")
        ax1.set_ylabel("强度分布度量", color="tab:blue")
        ax2 = ax1.twinx()
        svals = [r["sigma"] if r["sigma"] is not None else np.nan for r in results]
        ax2.plot(x, svals, "^-", color="tab:red", label="σ（分支参数）")
        ax2.axhline(1.0, color="gray", ls="--", lw=0.8)
        ax2.set_ylabel("σ", color="tab:red")
        ax1.set_xticks(x)
        ax1.set_xticklabels(vers, rotation=90, fontsize=8)
        ax1.set_xlabel("版本")
        fig.suptitle("结构有序度诊断 v2（全版本 + 稳定词跟踪）")
        fig.legend(loc="upper left", fontsize=8)
        fig.tight_layout()
        fig.savefig(OUT_FIG, dpi=130)
        print("图 → %s" % OUT_FIG)
    except Exception as e:
        print("画图跳过：%s" % e)


if __name__ == "__main__":
    main()
