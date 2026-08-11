# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""声音概念鲁棒性探针：类内多样化 + 环境干扰（2026-08-11）。

用户问题："鸟的声音有无数种，同时还会根据各种情况出现干扰"——
概念形成必须回答：类内多样实例能否汇聚成同一概念？环境干扰下
唤起还能否保持？类间相似声会不会混淆？

设计（空白网络 n=4096，机制参数对齐 v35）：
  教学：8 种鸟叫变体（啁啾/鸣啭/短促 × 频率档）+ 2 种牛叫 + 2 种猫叫，
        各自绑定概念词（鸟/牛/猫，词表自建）。
  验证① 类内汇聚：8 种鸟叫变体各自唤起"鸟"？
  验证② 干扰扫描：鸟叫 + 白噪声 SNR {20,10,5,0}dB → 唤起曲线（抗噪边界）
  验证③ 掩蔽混叠：鸟叫+牛叫同时 → 唤起"鸟"/"牛"（竞争 or 共存）
  验证④ 类间混淆：牛/猫变体 → 不唤起"鸟"（交叉）
  验证⑤ 剪弱边前后对比：剪 <1.0 弱边对干扰鲁棒性的影响

用法：python stage/_probe_sound_robust.py
留档：runs/_probe_sound_robust_{ts}/result.json
"""
import json
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema_net import _learn_sentence, build_pulse
from sparse_net import SparseSchemaNet, allocate_pats

ROOT = Path(__file__).resolve().parent.parent

SR = 8000
FRAME_MS = 50
N_FREQ, N_ENG = 16, 4
N_ROUNDS = 3
N = 4096


# ────────────────────────────────────────────────────────────────
#  物理层：多样合成音 + 干扰（纯信号处理）
# ────────────────────────────────────────────────────────────────

def synth_chirp(f0, f1, dur, amp=1.0):
    """啁啾：频率线性扫描 f0→f1。"""
    t = np.arange(int(SR * dur)) / SR
    phase = 2 * np.pi * (f0 * t + (f1 - f0) * t ** 2 / (2 * dur))
    return amp * np.sin(phase)


def synth_trill(f, fmod, rate, dur, amp=1.0):
    """鸣啭：中心频率 f，±fmod 快速调频 rate Hz。"""
    t = np.arange(int(SR * dur)) / SR
    return amp * np.sin(2 * np.pi * f * t + fmod / rate * np.sin(2 * np.pi * rate * t))


def synth_chip(f, on, dur, amp=1.0):
    """短促叫：短音 + 停顿交替（chip 序列）。"""
    n = int(SR * dur)
    t = np.arange(n) / SR
    env = (t % (2 * on)) < on
    return amp * np.sin(2 * np.pi * f * t) * env


def add_noise(wave, snr_db, kind="white", seed=1):
    """加噪：white 白噪声 / rain 低频有色噪声（雨声）/ wind 慢调制噪声（风声）。"""
    rng = np.random.default_rng(seed)
    n = len(wave)
    sig = np.sqrt(np.mean(wave ** 2))
    p_noise = sig / (10 ** (snr_db / 20))
    if kind == "white":
        nz = rng.normal(0, p_noise, n)
    elif kind == "rain":
        nz = rng.normal(0, p_noise, n)
        b = np.ones(32) / 32                      # 低通（低频雨声）
        nz = np.convolve(nz, b, mode="same") * 8
    elif kind == "wind":
        nz = rng.normal(0, p_noise, n)
        env = 0.5 + 0.5 * np.sin(2 * np.pi * 0.8 * np.arange(n) / SR)   # ~0.8Hz 慢调制
        nz = nz * env * 4
    return wave + nz


def mix(w1, w2):
    """混叠：两信号等幅叠加。"""
    m = min(len(w1), len(w2))
    return (w1[:m] + w2[:m]) / 2


def encode_frames(wave):
    """声波 → 帧词序列（同 _probe_sound_modal：过零率+能量 AGC）。"""
    fr = int(SR * FRAME_MS / 1000)
    frame_s = FRAME_MS / 1000.0
    segs = [wave[i:i + fr] for i in range(0, len(wave) - fr, fr)]
    rms = np.array([np.sqrt(np.mean(s ** 2)) for s in segs])
    max_rms = max(rms.max(), 1e-9)
    words = []
    for s, r in zip(segs, rms):
        r_n = r / max_rms
        if r_n < 0.02:
            continue                      # 静音帧跳过：STDP 只学尾帧→词桥，
                                          # 静音尾帧会让短促叫唤起断链（节奏维度本轮不做）

        sgn = np.sign(s)
        n_z = int(np.count_nonzero(sgn[1:] != sgn[:-1]))
        freq = n_z / (2 * frame_s)
        f_bin = min(int(freq / (SR / 2) * N_FREQ), N_FREQ - 1)
        e_bin = min(int(r_n * N_ENG), N_ENG - 1)
        words.append(f"z{f_bin}e{e_bin}")
    return words


# 教学语料：鸟 8 变体（类内多样）/ 牛 2 / 猫 2
def bird_corpus():
    return [
        ("bird_chirp_hi", synth_chirp(2500, 3500, 0.5)),
        ("bird_chirp_lo", synth_chirp(1500, 2200, 0.5)),
        ("bird_trill_2k", synth_trill(2000, 300, 12, 0.5)),
        ("bird_trill_3k", synth_trill(3000, 400, 9, 0.5)),
        ("bird_chip_2k5", synth_chip(2500, 0.04, 0.5)),
        ("bird_chip_2k", synth_chip(2000, 0.04, 0.5)),
        ("bird_chip_3k5", synth_chip(3500, 0.03, 0.5)),
        ("bird_long_4k", synth_chirp(3800, 4000, 0.6)),
        ("bird_warb", synth_trill(1800, 200, 6, 0.7)),
    ]


def other_corpus():
    return [
        ("cow_moo", "牛", synth_chirp(180, 120, 0.5)),
        ("cow_low", "牛", synth_chirp(220, 160, 0.4)),
        ("cat_mew", "猫", synth_trill(900, 150, 8, 0.4)),
        ("cat_hi", "猫", synth_chirp(1100, 900, 0.3)),
    ]


# ────────────────────────────────────────────────────────────────
#  网络 / 教学 / 验证
# ────────────────────────────────────────────────────────────────

def build_net():
    # noise_p=0：教学纯信号。n=4096 时 6% 噪声 = 每步 245 个噪声神经元，
    # 360 步教学后全池神经元被噪声选中 ~21 次 → 噪声 hub 边累积到 1.5+
    # （剪不掉）→ 猫帧→hub→鸟 两跳中继（类间混淆 1.0 的机制）。
    # 干扰由物理层 add_noise 提供（网络底噪的影响已在单音探针记录）。
    ng = SparseSchemaNet(rng=np.random.default_rng(7), n=N, slots=4,
                         theta=1.0, membrane_decay=0.9, eta=0.1, w_max=64.0,
                         wta_k=20, noise_p=0.0, noise_amp=0.5,
                         weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5,
                         stdp_neg=0.0, trace_decay=0.5, refractory=1,
                         learn_gate=True, inh_loose=0.3, std_dep=0.0,
                         std_rec=0.85, edge_min=0.0, inh_norm=0.0,
                         refract_clear=False)
    return ng


SENSE_ALL = [f"z{f}e{e}" for f in range(N_FREQ) for e in range(N_ENG)]  # 感知模式预置（耳蜗 tonotopy）


def allocate(ng, pats, cursor, seqs, concept_words):
    all_w = ({w for seq in seqs for w in seq} | set(concept_words) | set(SENSE_ALL))
    words = [w for w in sorted(all_w) if w not in pats]   # 已分配的不重分（覆盖会断边）
    if words:
        new_pats, cursor = allocate_pats(ng, words, 4, cursor)
        pats.update(new_pats)
    return cursor


def teach(ng, pats, seq, word, rounds=N_ROUNDS):
    for _ in range(rounds):
        _learn_sentence(ng, seq + [word], pats, slot=0)


def prune_weak(ng, eps=1.0):
    n = 0
    for i in range(ng.n):
        for k in range(ng.slots):
            row = ng.W_out[i][k]
            if row:
                for j in list(row.keys()):
                    if row.get(j, 0.0) < eps:
                        del row[j]
                        n += 1
    return n


def evoke_ratio(ng, pats, seq, word, steps=3):
    """受控测量：关 learn_gate + 关噪声（evoke 也学习；噪声 hub 中继）。"""
    saved_g, saved_n = ng.learn_gate, ng.noise_p
    ng.learn_gate, ng.noise_p = False, 0.0
    try:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        fired = set()
        for w in seq:
            ng.v = np.zeros((ng.n, ng.slots))
            ng.spikes = np.zeros(ng.n)        # 帧间清（仿 _learn_sentence）
            ng.step(build_pulse(ng.n, pats[w]), slot=0)
            fired |= set(int(x) for x in np.where(ng.spikes > 0)[0])
            ng.step(np.zeros(ng.n), slot=0)
            fired |= set(int(x) for x in np.where(ng.spikes > 0)[0])
        for _ in range(steps):
            ng.step(np.zeros(ng.n), slot=0)
            fired |= set(int(x) for x in np.where(ng.spikes > 0)[0])
        return round(sum(1 for j in pats[word] if j in fired) / len(pats[word]), 3)
    finally:
        ng.learn_gate, ng.noise_p = saved_g, saved_n


# ────────────────────────────────────────────────────────────────
#  main
# ────────────────────────────────────────────────────────────────

def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT / "runs" / f"_probe_sound_robust_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    print("═══ 声音概念鲁棒性：类内多样化 + 环境干扰 ═══", flush=True)
    rep = {"meta": {"ts": ts, "n": N, "rounds": N_ROUNDS,
                    "bird_variants": 8, "snr_scan": [20, 10, 5, 0]},
           "sections": {}}

    birds = bird_corpus()
    others = other_corpus()

    # ── 教学 ──
    ng = build_net()
    pats, cursor = {}, 0
    seqs = [encode_frames(w) for _, w in birds]
    seqs += [encode_frames(w) for _, _, w in others]
    cursor = allocate(ng, pats, cursor, seqs, ["鸟", "牛", "猫"])
    for name, w in birds:
        teach(ng, pats, encode_frames(w), "鸟")
    for name, word, w in others:
        teach(ng, pats, encode_frames(w), word)
    n_prune = prune_weak(ng, eps=1.0)
    print(f"[教学] 8 鸟 + 4 他音 × {N_ROUNDS} 轮，剪弱边 {n_prune} 条", flush=True)
    rep["sections"]["教学"] = {"bird_variants": [n for n, _ in birds],
                                "others": [n for n, _, _ in others],
                                "pruned": n_prune}

    # ── ① 类内汇聚：8 种鸟叫 → 唤起"鸟" ──
    s1 = {}
    print("\n═══ ① 类内汇聚（8 种鸟叫各自唤起「鸟」）═══", flush=True)
    for name, w in birds:
        seq = encode_frames(w)
        r = evoke_ratio(ng, pats, seq, "鸟")
        s1[name] = r
        print(f"  {name}: 唤起鸟 = {r}", flush=True)
    s1["verdict"] = ("类内汇聚成立：8 种鸟叫全部唤起鸟 ≥0.5"
                     if all(v >= 0.5 for v in s1.values()) else "有变体唤起失败")
    rep["sections"]["1_类内汇聚"] = s1

    # ── ② 干扰扫描：白噪声 SNR 曲线 ──
    s2 = {"white": {}, "rain": {}, "wind": {}}
    print("\n═══ ② 干扰扫描（鸟叫 + 噪声，唤起鸟）═══", flush=True)
    for kind in ("white", "rain", "wind"):
        for snr in (20, 10, 5, 0):
            r = evoke_ratio(ng, pats, encode_frames(add_noise(birds[0][1], snr, kind)), "鸟")
            s2[kind][f"SNR{snr}dB"] = r
        print(f"  {kind}: {s2[kind]}", flush=True)
    rep["sections"]["2_干扰扫描"] = s2

    # ── ③ 掩蔽混叠：鸟叫+牛叫同时 ──
    s3 = {}
    print("\n═══ ③ 掩蔽混叠（鸟叫+牛叫同时，等幅）═══", flush=True)
    m = mix(birds[0][1], others[0][2])
    s3["混合帧序列"] = encode_frames(m)
    s3["唤起鸟"] = evoke_ratio(ng, pats, encode_frames(m), "鸟")
    s3["唤起牛"] = evoke_ratio(ng, pats, encode_frames(m), "牛")
    print(f"  唤起鸟 = {s3['唤起鸟']} | 唤起牛 = {s3['唤起牛']}", flush=True)
    rep["sections"]["3_掩蔽混叠"] = s3

    # ── ④ 类间混淆：牛/猫变体 → 不唤起"鸟" ──
    s4 = {}
    print("\n═══ ④ 类间混淆（牛/猫变体 → 唤起鸟？）═══", flush=True)
    for name, word, w in others:
        r = evoke_ratio(ng, pats, encode_frames(w), "鸟")
        s4[f"{name}→鸟"] = r
        print(f"  {name}: 唤起鸟 = {r}", flush=True)
    s4["verdict"] = ("类间隔离成立" if all(v <= 0.25 for v in s4.values())
                     else "存在类间混淆")
    rep["sections"]["4_类间混淆"] = s4

    # ── ⑤ 剪弱边对比 ──
    print("\n═══ ⑤ 剪弱边对鲁棒性的影响（对照组：不剪）═══", flush=True)
    ng2 = build_net()
    pats2, cursor2 = {}, 0
    seqs2 = [encode_frames(w) for _, w in birds] + [encode_frames(w) for _, _, w in others]
    cursor2 = allocate(ng2, pats2, cursor2, seqs2, ["鸟", "牛", "猫"])
    for name, w in birds:
        teach(ng2, pats2, encode_frames(w), "鸟")
    for name, word, w in others:
        teach(ng2, pats2, encode_frames(w), word)
    s5 = {"不剪·唤起鸟(SNR0dB)": evoke_ratio(ng2, pats2,
          encode_frames(add_noise(birds[0][1], 0, "white")), "鸟"),
          "不剪·牛→鸟交叉": evoke_ratio(ng2, pats2, encode_frames(others[0][2]), "鸟"),
          "剪后·唤起鸟(SNR0dB)": s2["white"]["SNR0dB"],
          "剪后·牛→鸟交叉": s4["cow_moo→鸟"]}
    print(f"  {s5}", flush=True)
    rep["sections"]["5_剪弱边对比"] = s5

    rep["sections"]["summary"] = {
        "类内汇聚": s1["verdict"],
        "干扰扫描": "白噪声 SNR0dB 仍唤起" if s2["white"]["SNR0dB"] > 0 else "SNR0dB 失效（有抗噪边界）",
        "掩蔽混叠": f"鸟={s3['唤起鸟']} 牛={s3['唤起牛']}",
        "类间混淆": s4["verdict"],
    }
    print("\n═══ 汇总 ═══", flush=True)
    for k, v in rep["sections"]["summary"].items():
        print(f"  {k}: {v}", flush=True)
    (run_dir / "result.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {run_dir}", flush=True)


if __name__ == "__main__":
    main()
