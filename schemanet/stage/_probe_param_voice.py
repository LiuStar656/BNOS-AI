# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""参数投射 + 轨迹定式 + 物理发声：定式网络学发声的最小验证（2026-08-11）。

用户设计（2026-08-11）：
  ① 声音的高低×宽窄直接投射到神经元槽位（参数空间 = 神经元空间，无转译）
  ② 一句话 = 1t..10t 时间窗口内激活哪些参数神经元（轨迹 = 时序激活模式）
  ③ 音色是物理层面（发声载体）的事情——网络只学参数轨迹，发声器产生音色
  ④ 网络容量：无上限槽位/神经元（自动扩容）——已具备

实现：
  参数网格：16 音高 P × 16 带宽 B = 256 参数神经元（q{P}_{B}，预置）
  发声器（物理层）：(P,B) → 基频 f(P) 正弦 + B 个谐波（B=0 纯音，B=15 饱满）
  提取器（再听）：过零率→基频→P；FFT 峰数→带宽→B
  教学：概念 ↔ 参数轨迹（跟读建边，双向桥，与"我→吃→苹果"同机制）
  验证：生成轨迹一致率 / 声波往返（voice→extract）/ 再听唤起 / 交叉

用法：python stage/_probe_param_voice.py
留档：runs/_probe_param_voice_{ts}/result.json + wav
"""
import json
import time
import wave as wavmod
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema_net import _learn_sentence, build_pulse
from sparse_net import SparseSchemaNet, allocate_pats

ROOT = Path(__file__).resolve().parent.parent

SR = 8000
N_P, N_B = 16, 16               # 音高 × 带宽 参数网格
PARAM_WORDS = [f"q{p}_{b}" for p in range(N_P) for b in range(N_B)]
PT_DUR = 0.1                    # 每个参数点时长（s）
N_ROUNDS = 3


# ────────────────────────────────────────────────────────────────
#  物理层：发声器（音色） / 提取器（再听）
# ────────────────────────────────────────────────────────────────

def f_of_p(p):
    """音高 P0..P15 → 100..4000Hz（对数刻度）。"""
    return 100.0 * (40.0 ** (p / (N_P - 1)))


def voice_param(p, b, dur=PT_DUR, sr=SR):
    """发声器：基频 f(p) 正弦 + b 个谐波（带宽=谐波数——音色在物理层）。"""
    f = f_of_p(p)
    t = np.arange(int(sr * dur)) / sr
    wave = np.sin(2 * np.pi * f * t)
    for k in range(2, b + 2):
        wave += (1.0 / k) * np.sin(2 * np.pi * f * k * t)
    m = np.max(np.abs(wave))
    return wave / (m + 1e-9) * 0.5


def voice_trajectory(words):
    """参数轨迹 → 声波（逐点发声拼接）。"""
    return np.concatenate([voice_param(*parse_word(w)) for w in words])


def parse_word(w):
    """q{P}_{B} → (p, b)"""
    body = w[1:]
    p, b = body.split("_")
    return int(p), int(b)


def extract_param(wave, dur=PT_DUR, sr=SR):
    """提取器（再听）：过零率→基频→P；FFT 峰数→带宽→B。"""
    n = int(sr * dur)
    if len(wave) < n:
        wave = np.pad(wave, (0, n - len(wave)))
    seg = wave[:n]
    sgn = np.sign(seg)
    n_z = int(np.count_nonzero(sgn[1:] != sgn[:-1]))
    f = n_z / (2 * dur)
    p = int(round((N_P - 1) * np.log(f / 100.0) / np.log(40.0)))
    p = max(0, min(N_P - 1, p))
    spec = np.abs(np.fft.rfft(seg * np.hanning(n)))
    # 谐波峰检测：阈值降到 0.04×max（谐波按 1/k 衰减，第 8 谐波=0.125，
    # 0.15 阈值会漏掉高阶谐波 → 带宽低估 → 再听唤起失败）
    peak_mask = (spec > 0.04 * spec.max()) & (spec > 1e-6)
    peaks = 0
    prev = False
    for m in peak_mask:
        if m and not prev:
            peaks += 1
        prev = m
    b = max(0, min(N_B - 1, peaks - 1))
    return p, b


def extract_trajectory(wave):
    """声波 → 参数轨迹（逐点提取）。"""
    n = int(SR * PT_DUR)
    words = []
    for i in range(0, len(wave) - n + 1, n):
        p, b = extract_param(wave[i:i + n])
        words.append(f"q{p}_{b}")
    return words


# ────────────────────────────────────────────────────────────────
#  网络 / 教学 / 验证
# ────────────────────────────────────────────────────────────────

def build_net():
    ng = SparseSchemaNet(rng=np.random.default_rng(7), n=4096, slots=4,
                         theta=1.0, membrane_decay=0.9, eta=0.1, w_max=64.0,
                         wta_k=20, noise_p=0.0, noise_amp=0.5,
                         weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5,
                         stdp_neg=0.0, trace_decay=0.5, refractory=0,
                         learn_gate=True, inh_loose=0.3, std_dep=0.0,
                         std_rec=0.85, edge_min=0.0, inh_norm=0.0,
                         refract_clear=False)
    return ng


def allocate(ng, pats, cursor, concept_words):
    words = [w for w in sorted(set(PARAM_WORDS) | set(concept_words)) if w not in pats]
    if words:
        new_pats, cursor = allocate_pats(ng, words, 4, cursor)
        pats.update(new_pats)
    return cursor


def teach_both(ng, pats, word, traj):
    for _ in range(N_ROUNDS):
        _learn_sentence(ng, traj + [word], pats, slot=0)     # 感知桥
        _learn_sentence(ng, [word] + traj, pats, slot=0)     # 生成桥


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
            hit = [w for w in PARAM_WORDS
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
    run_dir = ROOT / "runs" / f"_probe_param_voice_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print("═══ 参数投射 + 轨迹定式 + 物理发声 ═══", flush=True)
    rep = {"meta": {"ts": ts, "grid": f"{N_P}音高×{N_B}带宽", "pt_dur": PT_DUR},
           "sections": {}}

    # 教学轨迹（概念 ↔ 参数轨迹）：高→低、窄→宽 等
    words_traj = {
        "苹果": [(10, 2), (8, 5), (6, 8), (4, 11)],      # 高→低 + 窄→宽
        "猫叫": [(12, 1), (11, 2), (10, 3), (9, 4)],      # 高音渐低（窄）
        "牛叫": [(1, 2), (1, 4), (1, 6), (1, 8)],         # 低音渐宽
    }
    trajs = {w: [f"q{p}_{b}" for p, b in pts] for w, pts in words_traj.items()}
    for w, t in trajs.items():
        print(f"  [教学] {w}: 轨迹 {t}", flush=True)

    # ── 物理层自检：发声→提取 往返精度 ──
    print("\n═══ 物理层自检（voice → extract 往返）═══", flush=True)
    rep["sections"]["物理自检"] = {}
    for w, t in trajs.items():
        wave = voice_trajectory(t)
        back = extract_trajectory(wave)
        k = min(len(t), len(back))
        same = sum(1 for a, b in zip(t[:k], back[:k]) if a == b)
        rep["sections"]["物理自检"][w] = {"轨迹": t, "提取": back,
                                          "一致率": round(same / k, 3)}
        print(f"  {w}: {t} → 声波 → {back} | 一致率 {same/k:.2f}", flush=True)

    # ── 网络教学 ──
    ng = build_net()
    pats, cursor = {}, 0
    cursor = allocate(ng, pats, cursor, list(trajs.keys()))
    for w, t in trajs.items():
        teach_both(ng, pats, w, t)
    print("\n  教学完成（3 概念 × 轨迹 × 3 轮）", flush=True)

    # ── 感知：注入轨迹 → 唤起概念 ──
    print("\n═══ 感知（轨迹 → 唤起概念）═══", flush=True)
    s1 = {f"{w}轨迹→{w}": evoke_ratio(ng, pats, trajs[w], w) for w in trajs}
    print(f"  {s1}", flush=True)
    rep["sections"]["感知"] = s1

    # ── 交叉 ──
    print("\n═══ 交叉 ═══", flush=True)
    s2 = {f"{wa}→{wb}": evoke_ratio(ng, pats, trajs[wa], wb)
          for wa in trajs for wb in trajs if wa != wb}
    print(f"  {s2}", flush=True)
    rep["sections"]["交叉"] = s2

    # ── 生成：概念 → 轨迹 → 发声器 → 声波 → 再听提取 → 唤起 ──
    print("\n═══ 生成（概念→轨迹→发声→再听→唤起）═══", flush=True)
    s3 = {}
    for w in trajs:
        gen = [x for x in generate(ng, pats, w, trajs[w], steps=len(trajs[w]) + 4) if x]
        gen = gen[:len(trajs[w])]
        wave = voice_trajectory(gen)
        heard = extract_trajectory(wave)
        ev = evoke_ratio(ng, pats, heard, w) if heard else None
        k = min(len(gen), len(trajs[w]))
        same = sum(1 for a, b in zip(gen[:k], trajs[w][:k]) if a == b)
        s3[w] = {"生成轨迹": gen, "轨迹一致率": round(same / k, 3) if k else 0.0,
                 "再听提取": heard, "再听唤起": ev}
        print(f"  {w}: 生成 {gen} 一致率={s3[w]['轨迹一致率']} 再听唤起={ev}",
              flush=True)
        pcm = np.clip(wave, -1, 1)
        with wavmod.open(str(run_dir / f"{w}_发声.wav"), "wb") as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(SR)
            f.writeframes((pcm * 32767).astype(np.int16).tobytes())
    rep["sections"]["生成"] = s3

    rep["sections"]["summary"] = {
        "物理往返": {w: rep["sections"]["物理自检"][w]["一致率"] for w in trajs},
        "感知": s1, "交叉": s2,
        "生成一致率/再听": {w: (s3[w]["轨迹一致率"], s3[w]["再听唤起"]) for w in trajs},
    }
    print("\n═══ 汇总 ═══", flush=True)
    for k, v in rep["sections"]["summary"].items():
        print(f"  {k}: {v}", flush=True)
    (run_dir / "result.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {run_dir}", flush=True)


if __name__ == "__main__":
    main()
