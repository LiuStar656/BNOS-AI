# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""B2: 群编码连续注入——mel 向量 → 神经元群（引擎零改造）（2026-08-11）。

路线穷尽（用户："继续，直到完全走不通"）：
  B1(VQ 离散原型) → B3(长帧压缩轨迹) → B2(连续表示，本脚本)
B2 不量化 mel 向量：每维 8 个神经元（阈值 1/8..8/8），值 v → 激活
ceil(v×8) 个——连续值映射到神经元群激活数量（population coding，标准
神经编码，纯物理）。帧 = 64 神经元群（8 维 × 8），帧间转移 = 群间
Hebbian（STDP：注入帧 i+1 时 pre_trace 有帧 i 群 → W[帧i][0][帧i+1]）。
wta_k 升到 64（帧群 64 神经元必须全发放，否则群信息被 WTA 截断）。

验证：感知（帧群流→概念）/ 生成（概念→群链→mel 值读出→声带→声波→
再听）/ 交叉。

用法：python stage/_probe_pop_coding.py
留档：runs/_probe_pop_coding_{ts}/result.json
"""
import json
import time
import wave as wavmod
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema_net import build_pulse
from sparse_net import SparseSchemaNet, allocate_pats
from stage._probe_sound_mel import build_net as _mknet, SR, FRAME_MS, _mel_triangles
_W, _CENTERS = _mel_triangles(n_fft=2048)   # 2048 FFT 三角滤波器（200ms 帧）

ROOT = Path(__file__).resolve().parent.parent
SOUND_DIR = ROOT / "runs" / "_real_sounds"

N_DIM = 8                       # mel 维度
PER_DIM = 8                     # 每维神经元数（群编码分辨率）
WTA = N_DIM * PER_DIM           # wta_k：帧群必须全发放
N_ROUNDS = 3


def load_wav_8k(fp):
    w = wavmod.open(str(fp), "rb")
    n, sr, ch = w.getnframes(), w.getframerate(), w.getnchannels()
    d = np.frombuffer(w.readframes(n), dtype=np.int16).reshape(-1, ch)[:, 0]
    d = d.astype(np.float64) / 32767.0
    if sr != SR:
        t_new = np.arange(int(len(d) * SR / sr)) / SR
        d = np.interp(t_new, np.arange(len(d)) / sr, d)
    return d / (np.sqrt(np.mean(d ** 2)) + 1e-9)


def mel_frames(wave, n_fft=2048, sub_ms=50):
    """200ms 长帧（B3 结论：长帧轨迹短，生成可行）+ 子帧频谱平均。"""
    sub = int(SR * sub_ms / 1000)
    win = np.hanning(sub)
    frames = []
    for i in range(0, len(wave) - sub * 4, sub * 4):
        seg = wave[i:i + sub * 4]
        acc = np.zeros(len(_CENTERS))
        for k in range(4):
            spec = np.abs(np.fft.rfft(seg[k * sub:(k + 1) * sub] * win, n_fft)) ** 2
            acc += _W @ spec
        be = acc / 4
        m = be.max()
        if m > 1e-12:
            frames.append(be / m)
    return np.array(frames) if frames else np.zeros((0, len(_CENTERS)))


def pop_encode(vec):
    """mel 向量 → 群神经元索引（值 v → 该维前 ceil(v×8) 个神经元）。"""
    idx = []
    for d, v in enumerate(vec):
        n = min(max(int(np.ceil(v * PER_DIM)), 0), PER_DIM)
        idx.extend(range(d * PER_DIM, d * PER_DIM + n))
    return np.array(idx, dtype=np.int32)


def pop_decode(fired, pats):
    """发放的群神经元 → mel 向量（激活数量/PER_DIM 还原值）。"""
    vec = np.zeros(N_DIM)
    for j in fired:
        d = j // PER_DIM
        if d < N_DIM:
            vec[d] = max(vec[d], (j % PER_DIM + 1) / PER_DIM)
    return vec


def pulse_for(idx, n):
    p = np.zeros(n)
    p[idx] = 1.0
    return p


def teach_flow(ng, frames, word, pats, n):
    """群流教学：帧群序列 + 概念词（感知）/ 概念词 + 帧群序列（生成）。"""
    for _ in range(N_ROUNDS):
        for f in frames:                            # 感知：帧流 + 词
            ng.v = np.zeros((n, ng.slots))
            ng.spikes = np.zeros(n)
            ng.step(pulse_for(pop_encode(f), n), slot=0)
            ng.spikes = np.zeros(n)
            ng.step(np.zeros(n), slot=0)
        ng.v = np.zeros((n, ng.slots))
        ng.spikes = np.zeros(n)
        ng.step(build_pulse(n, pats[word]), slot=0)
        ng.spikes = np.zeros(n)
        ng.step(np.zeros(n), slot=0)
        for f in frames:                            # 生成：词 + 帧流
            ng.v = np.zeros((n, ng.slots))
            ng.spikes = np.zeros(n)
            ng.step(pulse_for(pop_encode(f), n), slot=0)
            ng.spikes = np.zeros(n)
            ng.step(np.zeros(n), slot=0)


def evoke_word(ng, frames, word, pats, n, steps=3):
    """注入帧群流 → 词模式激活比例（受控测量）。"""
    saved_g, saved_n = ng.learn_gate, ng.noise_p
    ng.learn_gate, ng.noise_p = False, 0.0
    try:
        ng.v = np.zeros((n, ng.slots))
        ng.spikes = np.zeros(n)
        ng.pre_trace = np.zeros(n)
        fired = set()
        for f in frames:
            ng.v = np.zeros((n, ng.slots))
            ng.spikes = np.zeros(n)
            ng.step(pulse_for(pop_encode(f), n), slot=0)
            fired |= set(int(x) for x in np.where(ng.spikes > 0)[0])
            ng.step(np.zeros(n), slot=0)
            fired |= set(int(x) for x in np.where(ng.spikes > 0)[0])
        for _ in range(steps):
            ng.step(np.zeros(n), slot=0)
            fired |= set(int(x) for x in np.where(ng.spikes > 0)[0])
        return round(sum(1 for j in pats[word] if j in fired) / len(pats[word]), 3)
    finally:
        ng.learn_gate, ng.noise_p = saved_g, saved_n


def generate_flow(ng, word, pats, n, steps=30):
    """注入概念 → 回响 → 每步读出 mel 向量（群激活）→ 帧序列。"""
    saved_g, saved_n = ng.learn_gate, ng.noise_p
    ng.learn_gate, ng.noise_p = False, 0.0
    try:
        ng.v = np.zeros((n, ng.slots))
        ng.spikes = np.zeros(n)
        ng.pre_trace = np.zeros(n)
        ng.step(build_pulse(n, pats[word]), slot=0)
        frames = []
        for _ in range(steps):
            ng.step(np.zeros(n), slot=0)
            fired = set(int(x) for x in np.where(ng.spikes > 0)[0])
            vec = pop_decode(fired, pats)
            if vec.sum() > 0:
                frames.append(vec)
        return np.array(frames)
    finally:
        ng.learn_gate, ng.noise_p = saved_g, saved_n


def voicebox_vec(vecs, dur_ms=200, repeat=4):
    """mel 向量帧 → 多带正弦叠加（码本声带）。"""
    fr = int(SR * dur_ms * repeat / 1000)
    t = np.arange(fr) / SR
    out = []
    for vec in vecs:
        wave = sum(0.5 * vec[k] * np.sin(2 * np.pi * _CENTERS[k] * t)
                   for k in range(len(vec)))
        m = np.abs(wave).max()
        out.append(wave / (m + 1e-9) * 0.5)
    return np.concatenate(out) if out else np.zeros(0)


def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT / "runs" / f"_probe_pop_coding_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print("═══ B2: 群编码连续注入（mel 向量 → 神经元群）═══", flush=True)
    rep = {"meta": {"ts": ts, "dims": N_DIM, "per_dim": PER_DIM, "wta": WTA},
           "sections": {}}

    real = {"鸟": SOUND_DIR / "bird_real.wav",
            "牛": SOUND_DIR / "cow_real.wav",
            "猫": SOUND_DIR / "cat_real.wav"}
    frames = {w: mel_frames(load_wav_8k(fp)) for w, fp in real.items()}
    for w, fr in frames.items():
        print(f"  {w}: {len(fr)} 帧 × mel{N_DIM}（200ms 长帧）", flush=True)

    n = 4096
    ng = SparseSchemaNet(rng=np.random.default_rng(7), n=n, slots=4,
                         theta=1.0, membrane_decay=0.9, eta=0.1, w_max=64.0,
                         wta_k=WTA, noise_p=0.0, noise_amp=0.5,
                         weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5,
                         stdp_neg=0.0, trace_decay=0.5, refractory=1,
                         learn_gate=True, inh_loose=0.3, std_dep=0.0,
                         std_rec=0.85, edge_min=0.0, inh_norm=0.0,
                         refract_clear=False)
    pats, cursor = {}, 0
    words = ["鸟", "牛", "猫"]
    new_pats, cursor = allocate_pats(ng, words, 4, cursor)
    pats.update(new_pats)

    for w in words:
        teach_flow(ng, frames[w], w, pats, n)
    print("  教学完成（群流 + 概念词，双向）", flush=True)

    # ── ① 感知：帧群流 → 唤起 ──
    print("\n═══ ① 感知（帧群流 → 唤起概念）═══", flush=True)
    s1 = {}
    for w in words:
        s1[f"{w}流→{w}"] = evoke_word(ng, frames[w], w, pats, n)
    print(f"  {s1}", flush=True)
    rep["sections"]["1_感知"] = s1

    # ── ② 交叉 ──
    print("\n═══ ② 交叉 ═══", flush=True)
    s2 = {f"{wa}流→{wb}": evoke_word(ng, frames[wa], wb, pats, n)
          for wa in words for wb in words if wa != wb}
    print(f"  {s2}", flush=True)
    rep["sections"]["2_交叉"] = s2

    # ── ③ 生成：概念 → 群链 → mel → 声带 → 再听 ──
    print("\n═══ ③ 生成（概念→群链→mel→声波→再听）═══", flush=True)
    s3 = {}
    for w in words:
        gen = generate_flow(ng, w, pats, n, steps=len(frames[w]) + 2)
        k = min(len(gen), len(frames[w]))
        dist = np.mean(np.abs(gen[:k] - frames[w][:k])) if k else 999
        wav = voicebox_vec(gen)
        heard = mel_frames(wav)
        ev = evoke_word(ng, heard, w, pats, n) if len(heard) else None
        s3[w] = {"生成帧数": len(gen), "mel 平均距离": round(float(dist), 4),
                 "再听唤起": ev}
        print(f"  {w}: 生成 {len(gen)} 帧 mel距离={dist:.4f} 再听唤起={ev}", flush=True)
        pcm = np.clip(wav, -1, 1)
        with wavmod.open(str(run_dir / f"{w}_pop.wav"), "wb") as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(SR)
            f.writeframes((pcm * 32767).astype(np.int16).tobytes())
    rep["sections"]["3_生成"] = s3

    rep["sections"]["summary"] = {"感知": s1, "交叉": s2, "生成": s3}
    print("\n═══ 汇总 ═══", flush=True)
    for k, v in rep["sections"]["summary"].items():
        print(f"  {k}: {v}", flush=True)
    (run_dir / "result.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {run_dir}", flush=True)


if __name__ == "__main__":
    main()
