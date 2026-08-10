# -*- coding: utf-8 -*-
"""结构有序度诊断——"有向脉冲熵减"的可计算验证（2026-08-11）。

对 runs/ 版本链（v1.0 → v34.0）做离线分析：
  Phase 1（静态）：每个版本快照的
    - H_strength：非零边强度分布的 Shannon 熵（log 空间，按 log(bins) 归一化）
    - skew       ：强度分布偏度（正偏 = 少数强边 + 大量弱边的长尾分化）
    - sat_ratio  ：w≥1.99 的饱和边占比（w_max=2.0 截断顶 bin）
    - weak_ratio ：w<0.5 弱边占比
    - H_deg / deg_top1pct_share：出度分布熵 / top1% 神经元出度占比（hub 长尾）
  Phase 2（动态）：每个版本注入任意词，测候选数比率 σ（分支参数，
    复用 archive/_debug_avalanche.py 方法）→ 观察 σ 随成长的收敛/发散。

判定（若"有向脉冲熵减"成立）：
  - 成熟期段内 H_strength 下降（强度分布分化 = 有序化）
  - skew 上升 / top1% 出度占比上升（hub 结构形成 = 结构有序化）
  - σ 保持在临界附近（≈1），不发散
否定结果同样有效（说明"熵减"表述需修正）。

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


# ────────────────────────────────────────────────────────────────
#  Phase 1：静态度量
# ────────────────────────────────────────────────────────────────

def _strength_entropy(w):
    """log 空间直方图 Shannon 熵（归一化 H/log(bins)）。全等值 → 0。"""
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


def static_metrics(npz_path):
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
    return m


# ────────────────────────────────────────────────────────────────
#  Phase 2：动态 σ（分支参数，候选数比率）
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
#  主流程
# ────────────────────────────────────────────────────────────────

def main():
    rows = snapshot_index()
    if not rows:
        print("runs/index.jsonl 无版本记录")
        return
    # 按主版本号排序（旧 → 新），取每个 major 的主链代表（minor=0 优先）
    versions = sorted(rows, key=lambda r: (r["major"], r["minor"]))
    reps = {}
    for r in versions:
        if r["major"] not in reps:
            reps[r["major"]] = r
    chain = [reps[k] for k in sorted(reps)]

    print("版本链（主版本 %d 个）" % len(chain))
    results = []
    for i, r in enumerate(chain):
        npz = RUNS / r["dir"] / "net.npz"
        if not npz.exists():
            print("  跳过（无 net.npz）：v%s %s" % (r["version"], r["dir"]))
            continue
        m = static_metrics(npz)
        rec = {
            "version": r["version"], "tag": r.get("tag", ""),
            "parent": r.get("parent_version"), "E": m["E"], "n": m["n"],
            "w_mean": m["w_mean"], "w_max": m["w_max"],
            "sat_ratio": m["sat_ratio"], "weak_ratio": m["weak_ratio"],
            "skew": m["skew"], "H_strength": m["H_strength"],
            "H_deg": m["H_deg"], "deg_top1pct_share": m["deg_top1pct_share"],
        }
        # Phase 2：动态 σ（每 2 个版本测一次，省时）
        if i % 2 == 0 or i == len(chain) - 1:
            ng, vocab, pats, cursor = load_snapshot(npz)
            probe_words = [w for w in ("我", "吃", "石头", "痛", "不要", "了", "是", "的")
                           if w in pats][:5]
            if not probe_words:
                probe_words = list(pats.keys())[:5]
            rec["sigma"] = dynamic_sigma(ng, pats, probe_words)
        else:
            rec["sigma"] = None
        results.append(rec)
        print("v%-4s σ=%5.2f Hstr=%5.3f skew=%7.1f sat=%5.3f top1%%=%5.3f E=%8d n=%6d  %s"
              % (rec["version"],
                 rec["sigma"] if rec["sigma"] is not None else float("nan"),
                 rec["H_strength"], rec["skew"], rec["sat_ratio"],
                 rec["deg_top1pct_share"], rec["E"], rec["n"],
                 (rec["tag"] or "")[:36]))

    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print("\n结果 → %s" % OUT_JSON)

    # 画图
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        vers = [r["version"] for r in results]
        x = np.arange(len(vers))
        fig, ax1 = plt.subplots(figsize=(11, 5))
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
        fig.suptitle("结构有序度诊断（有向脉冲熵减验证）")
        fig.legend(loc="upper left", fontsize=8)
        fig.tight_layout()
        fig.savefig(OUT_FIG, dpi=130)
        print("图 → %s" % OUT_FIG)
    except Exception as e:
        print("画图跳过：%s" % e)


if __name__ == "__main__":
    main()
