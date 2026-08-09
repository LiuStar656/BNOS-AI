# -*- coding: utf-8 -*-
"""模型版本链演示（用户场景：a → a+1 → a+2 → 回退 a+1 训练出 a+2.1 对比）。

演示 snapshot.py 的语义版本机制（MAJOR.MINOR，类比软件版本）：
  v1.0 = a       （初始训练，根版本）
  v2.0 = a+1     （parent=1.0，续训）
  v3.0 = a+2     （parent=2.0，续训）
  a+2 有问题 → load_version("2.0") 回退到 a+1 → 再训练 → v3.1 = a+2.1
    （parent=2.0，与 a+2 同 major 平级 → 直接对比 a+2 vs a+2.1）
  v1.0/v2.0/v3.0 全部保留，可追溯；版本链可回溯到根。

用法：python _version_demo.py
"""

import shutil
from pathlib import Path

import numpy as np

from schema_net import SchemaNet, build_pulse, _word_pattern
from snapshot import save_snapshot, load_version, version_chain, snapshot_index

DEMO = Path(__file__).parent / "runs" / "_demo_versions"
N, K, SLOTS, SEED = 256, 2, 4, 42
W_MAX, REFRACTORY = 2.0, 1

SENTENCES = [
    ["人", "之", "初", "性", "本", "善"],   # 目标：人之初 → 性本善
    ["春", "来", "花", "自", "开", "落"],   # 对照
]


def fire_ratio(fired, neurons):
    return len(fired & set(neurons)) / max(1, len(neurons))


def recall(ng, pats, toks, pre_len=3):
    """前缀唤起率：输入前 pre_len 词 → 后续词神经元被唤起的比例。"""
    pre, suf = toks[:pre_len], toks[pre_len:]
    pulse = build_pulse(ng.n, np.concatenate([pats[w] for w in pre]))
    fired = ng.run_experience(pulse, slot=0)
    return fire_ratio(fired, np.concatenate([pats[w] for w in suf]))


def train(ng, pats, rounds):
    """跟读：整句反复注入 rounds 轮。"""
    for _ in range(rounds):
        for toks in SENTENCES:
            pulse = build_pulse(ng.n, np.concatenate([pats[w] for w in toks]))
            ng.run_experience(pulse, slot=0)


def metric(ng, pats):
    return {"recall_ren": round(recall(ng, pats, SENTENCES[0]), 3),
            "recall_chun": round(recall(ng, pats, SENTENCES[1]), 3)}


def new_net():
    return SchemaNet(n=N, slots=SLOTS, theta=1.0, membrane_decay=0.9, eta=0.1,
                     w_max=W_MAX, wta_k=16, noise_p=0.06, noise_amp=0.5,
                     refractory=REFRACTORY, rng=np.random.default_rng(SEED))


def main():
    if DEMO.exists():
        shutil.rmtree(DEMO)
    words = sorted({w for t in SENTENCES for w in t})
    pats = {w: _word_pattern(N, K, w) for w in words}

    # ── 1.0 = a：初始训练（根版本）──
    ng = new_net()
    train(ng, pats, 10)
    save_snapshot(ng, tag="1.0 = a 初始训练（跟读 10 轮）",
                  metrics=metric(ng, pats), vocab=words, pats=pats,
                  cursor=len(words) * K, base=DEMO)

    # ── 2.0 = a+1：加载 1.0 续训 ──
    ng, vocab, pats, cursor = load_version("1.0", base=DEMO)
    train(ng, pats, 10)
    save_snapshot(ng, tag="2.0 = a+1 续训（跟读 +10 轮）",
                  metrics=metric(ng, pats), vocab=vocab, pats=pats,
                  cursor=cursor, base=DEMO)

    # ── 3.0 = a+2：加载 2.0 续训 ──
    ng, vocab, pats, cursor = load_version("2.0", base=DEMO)
    train(ng, pats, 10)
    save_snapshot(ng, tag="3.0 = a+2 续训（跟读 +10 轮）",
                  metrics=metric(ng, pats), vocab=vocab, pats=pats,
                  cursor=cursor, base=DEMO)

    # ── a+2 有问题 → 回退 a+1(2.0) 再训练 → 3.1 = a+2.1（与 3.0 平级可对比）──
    ng, vocab, pats, cursor = load_version("2.0", base=DEMO)
    train(ng, pats, 20)   # 更充分训练
    save_snapshot(ng, parent="2.0", tag="3.1 = a+2.1 回退自 a+1 再训练（跟读 +20 轮）",
                  metrics=metric(ng, pats), vocab=vocab, pats=pats,
                  cursor=cursor, base=DEMO)

    # ── 追溯：全部版本 + 版本链 + 对比 ──
    print("\n── 全部版本（追溯索引）──")
    for r in snapshot_index(base=DEMO):
        print(f"  v{r['version']:<6} parent={r['parent_version']}  "
              f"tag={r['tag']!r}  metrics={r['metrics']}")
    print("\n── 最新版本链（3.1 → 根）──")
    for r in version_chain(base=DEMO):
        print(f"  v{r['version']} ← parent={r['parent_version']}  {r['tag']}")
    print("\n── a+2 vs a+2.1 对比（同代平级，均可 load_version 取出）──")
    rows = {r["version"]: r for r in snapshot_index(base=DEMO)}
    for v in ("3.0", "3.1"):
        r = rows[v]
        print(f"  v{v}  metrics={r['metrics']}  (net.npz 在 "
              f"runs/_demo_versions/{r['dir']})")
    print("\n── 历史版本仍在（a / a+1 / a+2 未删）──")
    for r in snapshot_index(base=DEMO):
        assert (DEMO / r["dir"] / "net.npz").exists(), r
    print("  全部版本 net.npz 存在 ✅")


if __name__ == "__main__":
    main()
