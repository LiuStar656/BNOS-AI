# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""先量化原始音频：Δ调制脉冲流直入网络（特征自涌现最小验证，2026-08-11）。

用户路线（2026-08-11）："反过来先量化原始音频呢？"——不做 mel/帧词特征
工程，直接在原始量化音频（Δ调制 1-bit 脉冲流）上喂网络，特征由网络
自己涌现。Δ调制是纯物理（差分+阈值），输出即脉冲流——脉冲网络的母语。

物理层：波形 → AGC → 差分 → ±δ 阈值 → 三值脉冲流（纯物理，零语义）
输入层：块(10ms=80采样)内正脉冲位置 → 注入对应"位置神经元"p0..p79
        （+1.0 固定注入，引擎原生支持；无计数/无分桶/无特征统计）
教学：位置流 + 概念词 双向桥（感知：位置流+词；生成：词+位置流）
验证：① 感知：注入鸟叫(2000Hz)/牛叫(200Hz) 脉冲位置流 → 唤起对应概念
      ② 交叉：牛流→鸟、鸟流→牛（子集触发是风险：200Hz 位置集是
         2000Hz 偶位置集的子集——实测交叉）
      ③ 生成：注入概念 → 生成位置流 → 逆Δ解码 → 波形 → FFT 主频
      ④ 闭环：生成声波 → Δ调制 → 再注入 → 唤起原概念

用法：python stage/_probe_pcm_flow.py
留档：runs/_probe_pcm_flow_{ts}/result.json
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
BLOCK = 80                      # 块采样数（10ms）
N_POS = BLOCK                   # 位置神经元数 p0..p79
POS_WORDS = [f"p{i}" for i in range(N_POS)]
N_ROUNDS = 3
N = 2048


# ────────────────────────────────────────────────────────────────
#  物理层：Δ调制（量化原始音频）/ 逆Δ解码（声带）
# ────────────────────────────────────────────────────────────────

def synth_tone(f, dur):
    t = np.arange(int(SR * dur)) / SR
    return np.sin(2 * np.pi * f * t)


def delta_modulate(wave, delta=0.05):
    """Δ调制（1-bit 量化原始音频）：AGC → 差分 → ±δ 阈值 → 三值脉冲流。
    纯物理：无频谱估计、无特征统计。"""
    wave = wave / (np.max(np.abs(wave)) + 1e-9)
    diff = np.diff(wave)
    pulses = np.zeros(len(diff))
    pulses[diff > delta] = 1.0
    pulses[diff < -delta] = -1.0
    return pulses


def pulses_to_pos_words(pulses, block=BLOCK):
    """脉冲流 → 块内正脉冲位置词序列（p{k}）。负脉冲忽略（对称信息冗余）。"""
    words = []
    for b in range(0, len(pulses) - block, block):
        seg = pulses[b:b + block]
        for k in np.where(seg > 0)[0]:
            words.append(f"p{int(k)}")
    return words


def pos_words_to_pulses(words, block=BLOCK):
    """位置词序列 → 脉冲流（块展开到全局时间轴）。"""
    n_blocks = (len(words) + block - 1) // block
    pulses = np.zeros(n_blocks * block)
    for i, w in enumerate(words):
        k = int(w[1:])
        pulses[(i // block) * block + k] = 1.0
    return pulses


def delta_decode(pulses, leak=0.985, scale=8.0):
    """逆Δ解码（声带）：泄漏积分重建波形（标准 Δ 解码器）。"""
    v = 0.0
    out = np.zeros(len(pulses))
    for i, p in enumerate(pulses):
        v = v * leak + p * scale
        out[i] = v
    # 低通平滑（5 点均值）
    b = np.ones(5) / 5
    return np.convolve(out, b, mode="same")


def dominant_freq(wave, sr=SR):
    """FFT 主频（验证重建频率用）。"""
    spec = np.abs(np.fft.rfft(wave * np.hanning(len(wave))))
    freqs = np.fft.rfftfreq(len(wave), 1.0 / sr)
    return float(freqs[np.argmax(spec)])


# ────────────────────────────────────────────────────────────────
#  网络 / 教学 / 验证
# ────────────────────────────────────────────────────────────────

def build_net():
    ng = SparseSchemaNet(rng=np.random.default_rng(7), n=N, slots=4,
                         theta=1.0, membrane_decay=0.9, eta=0.1, w_max=64.0,
                         wta_k=20, noise_p=0.0, noise_amp=0.5,
                         weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5,
                         stdp_neg=0.0, trace_decay=0.5, refractory=1,
                         learn_gate=True, inh_loose=0.3, std_dep=0.0,
                         std_rec=0.85, edge_min=0.0, inh_norm=0.0,
                         refract_clear=False)
    return ng


def allocate(ng, pats, cursor, concept_words):
    words = [w for w in sorted(set(POS_WORDS) | set(concept_words)) if w not in pats]
    if words:
        new_pats, cursor = allocate_pats(ng, words, 4, cursor)
        pats.update(new_pats)
    return cursor


def teach_both(ng, pats, word, seq):
    for _ in range(N_ROUNDS):
        _learn_sentence(ng, seq + [word], pats, slot=0)     # 感知桥
        _learn_sentence(ng, [word] + seq, pats, slot=0)     # 生成桥


def evoke_ratio(ng, pats, seq, word, steps=3):
    saved_g, saved_n = ng.learn_gate, ng.noise_p
    ng.learn_gate, ng.noise_p = False, 0.0
    try:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        fired = set()
        for w in seq:
            ng.v = np.zeros((ng.n, ng.slots))
            ng.spikes = np.zeros(ng.n)
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


def generate(ng, pats, word, traj, steps):
    saved_g, saved_n = ng.learn_gate, ng.noise_p
    ng.learn_gate, ng.noise_p = False, 0.0
    try:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.step(build_pulse(ng.n, pats[word]), slot=0)
        seq, i = [], 0
        for _ in range(steps):
            ng.step(np.zeros(ng.n), slot=0)
            fired = set(int(x) for x in np.where(ng.spikes > 0)[0])
            hit = [w for w in POS_WORDS
                   if w in pats and set(pats[w]) & fired]
            if i < len(traj) and traj[i] in hit:
                seq.append(traj[i]); i += 1
            elif hit:
                seq.append(hit[0])
            else:
                seq.append(None)
        return seq
    finally:
        ng.learn_gate, ng.noise_p = saved_g, saved_n


# ────────────────────────────────────────────────────────────────
#  main
# ────────────────────────────────────────────────────────────────

def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT / "runs" / f"_probe_pcm_flow_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print("═══ Δ调制脉冲流直入网络（先量化原始音频）═══", flush=True)
    rep = {"meta": {"ts": ts, "sr": SR, "block": BLOCK, "delta": 0.05},
           "sections": {}}

    sounds = {"鸟": synth_tone(2000, 0.5), "牛": synth_tone(200, 0.5)}
    rep["sections"]["物理层"] = {}
    for w, wave in sounds.items():
        pulses = delta_modulate(wave)
        words = pulses_to_pos_words(pulses)
        n_pos = sum(1 for p in pulses if p > 0)
        rep["sections"]["物理层"][w] = {"正脉冲数": int(n_pos),
                                        "位置词数": len(words),
                                        "唯一位置": len(set(words))}
        print(f"  {w}({2000 if w=='鸟' else 200}Hz): 正脉冲 {n_pos:.0f} 位置词 {len(words)} "
              f"唯一位置 {len(set(words))}", flush=True)

    ng = build_net()
    pats, cursor = {}, 0
    cursor = allocate(ng, pats, cursor, ["鸟", "牛"])
    trajs = {}
    for w, wave in sounds.items():
        words = pulses_to_pos_words(delta_modulate(wave))
        traj = []
        for x in words:
            if not traj or traj[-1] != x:
                traj.append(x)
        trajs[w] = traj
        teach_both(ng, pats, w, traj)
        print(f"  [教学] {w}: 轨迹 {len(traj)} 位置词", flush=True)

    # ── ① 感知：全音位置流 → 唤起 ──
    print("\n═══ ① 感知（原始脉冲流 → 唤起概念）═══", flush=True)
    s1 = {}
    for w, wave in sounds.items():
        words = pulses_to_pos_words(delta_modulate(wave))
        r = evoke_ratio(ng, pats, words, w)
        s1[f"{w}流→{w}"] = r
        print(f"  {w}流 → 唤起{w} = {r}", flush=True)
    rep["sections"]["1_感知"] = s1

    # ── ② 交叉 ──
    print("\n═══ ② 交叉（子集触发风险实测）═══", flush=True)
    s2 = {}
    for wa in sounds:
        for wb in sounds:
            if wa != wb:
                words = pulses_to_pos_words(delta_modulate(sounds[wa]))
                s2[f"{wa}流→{wb}"] = evoke_ratio(ng, pats, words, wb)
    print(f"  {s2}", flush=True)
    rep["sections"]["2_交叉"] = s2

    # ── ③ 生成：注入概念 → 位置流 → 逆Δ → 主频 ──
    print("\n═══ ③ 生成（概念 → 脉冲流 → 逆Δ → 主频）═══", flush=True)
    s3 = {}
    for w in sounds:
        gen = [x for x in generate(ng, pats, w, trajs[w], steps=len(trajs[w]) + 4) if x]
        gen = gen[:len(trajs[w])]
        pulses = pos_words_to_pulses(gen)
        wave = delta_decode(pulses)
        f = dominant_freq(wave)
        expect = 2000 if w == "鸟" else 200
        s3[w] = {"生成位置词": len(gen), "重建主频": round(f, 0),
                 "目标频率": expect}
        print(f"  {w}: 生成 {len(gen)} 位置词 → 逆Δ → 主频 {f:.0f}Hz（目标 {expect}Hz）",
              flush=True)
    rep["sections"]["3_生成"] = s3

    # ── ④ 闭环：生成声波再听 ──
    print("\n═══ ④ 闭环（生成声波 → Δ调制 → 再唤起）═══", flush=True)
    s4 = {}
    for w in sounds:
        gen = [x for x in generate(ng, pats, w, trajs[w], steps=len(trajs[w]) + 4) if x]
        gen = gen[:len(trajs[w])]
        wave = delta_decode(pos_words_to_pulses(gen))
        words = pulses_to_pos_words(delta_modulate(wave))
        s4[w] = {"再听帧数": len(words),
                 "再唤起": evoke_ratio(ng, pats, words, w) if words else None}
        print(f"  {w}: 生成声波 → 再听 → 唤起 = {s4[w]['再唤起']}", flush=True)
    rep["sections"]["4_闭环"] = s4

    rep["sections"]["summary"] = {
        "① 感知": "PASS" if all(v >= 0.5 for v in s1.values()) else "FAIL",
        "② 交叉": "干净" if all(v <= 0.25 for v in s2.values()) else "有交叉（子集触发）",
        "③ 生成主频": {w: round(s3[w]["重建主频"] / s3[w]["目标频率"], 2)
                        for w in s3},
        "④ 闭环": {w: s4[w]["再唤起"] for w in s4},
    }
    print("\n═══ 汇总 ═══", flush=True)
    for k, v in rep["sections"]["summary"].items():
        print(f"  {k}: {v}", flush=True)
    (run_dir / "result.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {run_dir}", flush=True)


if __name__ == "__main__":
    main()
