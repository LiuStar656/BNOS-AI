# -*- coding: utf-8 -*-
"""三字经机制第二层验证：人之初 → 性本善（局部触发、整块唤起）。

复读（已有，Hopfield 自联想）：
    输入整句 → 唤起整句（26 字母复述 26/26、整句涟漪复述率 1.000）。
本实验验证"下一句条件反射"：
    输入前缀"人之初" → 网络内唤起"性本善"（说出后续）。

机制（pattern completion，Hopfield 模式补全）：
    ① 跟读：句子反复经历（整句注入）→ 句内所有词共发放 → Hebbian
       形成句内强互连 → 句子固化为一个完整模式（"读的越多印象越足"）
    ② 唤起：只输入前缀（句首词神经元）→ 句内连接驱动后续词神经元
       发放 → 完整模式被补全 → "听到人之初，知道下一句是性本善"

对应 v2.0 Stage 2 短句级核心验收（句复述 ≥0.95 + 局部触发唤起），
且这是网络内长出来的（非 _sent_ripple 的外挂检索）。

用法：python _sanzi_jing.py
"""

import numpy as np

from schema_net import SchemaNet, build_pulse, _word_pattern

N = 256          # 神经元数（固定，不扩容——本验证无需扩容）
K = 2            # 每词模式神经元数
SLOTS = 4        # 多槽（语言实验同款架构；输入打 slot 0）
R = 30           # 跟读重复次数（"读的越多印象越足"）
W_MAX = 2.0      # Hebbian 连接饱和值
SEED = 42

# 句子集：A/B/C 无共词（干净对照）；D 与 A 共享"性"（串扰观察）
SENTENCES = [
    ["人", "之", "初", "性", "本", "善"],   # A 三字经：人之初 → 性本善
    ["春", "来", "花", "自", "开", "落"],   # B 对照（无共词）
    ["风", "吹", "云", "散", "去", "远"],   # C 对照（无共词）
    ["性", "相", "近", "习", "相", "远"],   # D 与 A 共享"性"（串扰观察）
]
PRE_LEN = 3      # 前缀词数（输入前半句，唤起后半句）


def fire_ratio(fired, neurons):
    """fired 中命中 neurons 的比例（覆盖率，噪声神经元不算）。"""
    return len(fired & set(neurons)) / max(1, len(neurons))


def main():
    rng = np.random.default_rng(SEED)
    ng = SchemaNet(n=N, slots=SLOTS, theta=1.0, membrane_decay=0.9, eta=0.1,
                   w_max=W_MAX, wta_k=16, noise_p=0.06, noise_amp=0.5,
                   refractory=1, rng=rng)

    # 词模式（固定 n 哈希；模式补全验证不涉及扩容）
    words = sorted({w for toks in SENTENCES for w in toks})
    pats = {w: _word_pattern(N, K, w) for w in words}
    print(f"词表 {len(words)} 词，每词 {K} 神经元，n={N}")

    # ── 跟读训练：整句反复经历 → 句内全连接（模式固化）──
    for r in range(1, R + 1):
        for toks in SENTENCES:
            pulse = build_pulse(N, np.concatenate([pats[w] for w in toks]))
            ng.run_experience(pulse, slot=0)
    print(f"跟读完成：{len(SENTENCES)} 句 × {R} 次")

    # ── 评估 ──
    print("\n── ① 整句复述（输入整句 → 唤起自己）──")
    for toks in SENTENCES:
        all_n = np.concatenate([pats[w] for w in toks])
        pulse = build_pulse(N, all_n)
        fired = ng.run_experience(pulse, slot=0)
        r_ = fire_ratio(fired, all_n)
        print(f"  {' '.join(toks):<14} 复述率 {r_:.3f}  "
              f"fired={len(fired)}")

    print("\n── ② 前缀唤起（输入前半句 → 唤起后半句）──")
    for toks in SENTENCES:
        pre, suf = toks[:PRE_LEN], toks[PRE_LEN:]
        pre_n = np.concatenate([pats[w] for w in pre])
        suf_n = np.concatenate([pats[w] for w in suf])
        pulse = build_pulse(N, pre_n)
        fired = ng.run_experience(pulse, slot=0)
        pre_r = fire_ratio(fired, pre_n)   # 复述（输入部分回响）
        suf_r = fire_ratio(fired, suf_n)   # 唤起（后续被补全）
        suf_printed = " ".join(suf) if suf_r >= 0.5 else "?" * len(suf)
        print(f"  {' '.join(pre):<8} → {suf_printed:<10} "
              f"前缀命中 {pre_r:.3f} / 后续唤起 {suf_r:.3f}  "
              f"fired={len(fired)}")

    # ── 判定 ──
    print("\n── 判定 ──")
    results = []
    for toks in SENTENCES:
        pre, suf = toks[:PRE_LEN], toks[PRE_LEN:]
        suf_n = np.concatenate([pats[w] for w in suf])
        pulse = build_pulse(N, np.concatenate([pats[w] for w in pre]))
        fired = ng.run_experience(pulse, slot=0)
        suf_r = fire_ratio(fired, suf_n)
        ok = "成立" if suf_r >= 0.5 else "未成立"
        print(f"  {' '.join(pre)} → {' '.join(suf)}：{ok}（后续唤起 {suf_r:.3f}）")
        results.append({
            "prefix": " ".join(pre), "completion": " ".join(suf),
            "suffix_recall": round(suf_r, 4), "ok": suf_r >= 0.5,
        })

    # ── 统一快照留档（snapshot.py：时间戳 + 追溯索引 + 模型/模式字典持久化）──
    from snapshot import save_snapshot
    out = save_snapshot(
        ng,
        tag="三字经第二层验证：人之初→性本善（局部触发、整块唤起）",
        data_fp="构造句集（非语料）",
        metrics={
            "suffix_recall": [r["suffix_recall"] for r in results],
            "all_completed": all(r["ok"] for r in results),
        },
        vocab=words, pats=pats, cursor=len(words) * K)
    print(f"留档: {out / 'result.json'}  （追溯: runs/index.jsonl）")


if __name__ == "__main__":
    main()
