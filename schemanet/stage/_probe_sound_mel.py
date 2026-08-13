# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""mel 频谱物理层：真实自然音效逆向解析 + 反推（2026-08-11 第二轮）。

用户路线（2026-08-11）：过零率单频编码解析真实音效 = 帧词散乱
（鸟跳变率 0.735 / 牛 0.621 / 猫 0.49，反推一致率 0.08/0.53/0.20）——
牛头不对马嘴的量化根因是物理层假设（声音=单频+能量）不匹配真实频谱。
本轮物理层升级：**mel 频谱编码**（分帧 FFT → 8 个 mel 频带能量 → 阈值化
成 8 位频谱形状指纹 = 帧词 m0..m255；纯信号处理，无转译模型）。

  A. 逆向解析：真实音效（ESC-50 bird/cow/cat）mel 编码 vs 过零率编码
     → 期望：跳变率显著下降、主帧占比上升（频谱形状比单频估计稳定）
  B. 反推：mel 轨迹教学 → 注入概念生成 → 轨迹一致率（对比过零率版）
  C. 声带升级 + 可听对比：真实原声 / mel 重建（原声→mel→多带合成）
     / 网络生成（概念→mel 轨迹→多带合成）三个 wav 存盘

声带（多带合成）：mel 帧词激活频带各振一个正弦（f=带中心、幅度=档位）
叠加——音色从"单音"升级为"频谱形状"，与 mel 编码对称。

用法：python stage/_probe_sound_mel.py
留档：runs/_probe_sound_mel_{ts}/result.json + 三个 wav
"""
import json
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema_net import _learn_sentence, build_pulse
from sparse_net import SparseSchemaNet, allocate_pats

ROOT = Path(__file__).resolve().parent.parent
SOUND_DIR = ROOT / "runs" / "_real_sounds"

SR = 8000
FRAME_MS = 50
N_BANDS = 8                      # mel 频带数（8 位频谱指纹 → 256 帧词）
MEL_WORDS = [f"m{i}" for i in range(2 ** N_BANDS)]
N_ROUNDS = 3
N = 4096


# ────────────────────────────────────────────────────────────────
#  物理层：mel 频谱编码 / 多带声带
# ────────────────────────────────────────────────────────────────

def _mel_triangles(n_bands=N_BANDS, sr=SR, n_fft=512):
    """mel 标度三角滤波器组（0~4kHz，纯信号处理）。返回 (权重矩阵, 带中心Hz)。"""
    mel = lambda f: 2595.0 * np.log10(1.0 + f / 700.0)
    imel = lambda m: 700.0 * (10.0 ** (m / 2595.0) - 1.0)
    m_lo, m_hi = mel(50.0), mel(sr / 2 - 50.0)
    edges = imel(np.linspace(m_lo, m_hi, n_bands + 2))
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    W = np.zeros((n_bands, len(freqs)))
    centers = []
    for k in range(n_bands):
        lo, c, hi = edges[k], edges[k + 1], edges[k + 2]
        centers.append(c)
        tri = np.where(freqs <= c, (freqs - lo) / max(c - lo, 1e-9),
                       (hi - freqs) / max(hi - c, 1e-9))
        W[k] = np.clip(tri, 0, 1)
    return W, np.array(centers)


_W, _CENTERS = _mel_triangles()


def encode_mel_frames(wave, thresh=0.25):
    """声波 → mel 帧词序列：50ms 帧 → hann 窗 rfft → 8 带能量 →
    帧内归一（AGC 在频域，响度不变）→ 阈值化 → 8 位指纹 → m{0..255}。"""
    fr = int(SR * FRAME_MS / 1000)
    n_fft = 512
    win = np.hanning(fr)
    words = []
    for i in range(0, len(wave) - fr, fr):
        seg = wave[i:i + fr] * win
        spec = np.abs(np.fft.rfft(seg, n_fft)) ** 2
        band_e = _W @ spec
        m = band_e.max()
        if m <= 1e-12:
            continue
        bits = (band_e / m > thresh).astype(int)     # 帧内归一 → 阈值
        val = int("".join(map(str, bits)), 2)
        words.append(f"m{val}")
    return words


def parse_mel(word):
    """帧词 m{val} → 8 位激活带（bit k = 频带 k 激活）。"""
    return [(int(word[1:]) >> k) & 1 for k in range(N_BANDS)]


def voicebox_mel(mel_words, dur_ms=FRAME_MS, repeat=4):
    """多带声带：激活频带各振一个正弦（f=带中心）叠加——频谱形状发声。
    与 mel 编码对称（编码压成指纹，声带振成频谱）。"""
    fr = int(SR * dur_ms * repeat / 1000)
    t = np.arange(fr) / SR
    out = []
    for w in mel_words:
        bits = parse_mel(w)
        wave = np.zeros(fr)
        for k, on in enumerate(bits):
            if on:
                wave += 0.5 * np.sin(2 * np.pi * _CENTERS[k] * t)
        m = np.abs(wave).max()
        out.append(wave / (m + 1e-9) * 0.5)
    return np.concatenate(out) if out else np.zeros(0)


# ────────────────────────────────────────────────────────────────
#  网络（机制参数对齐 v35，教学纯信号）
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
    words = [w for w in sorted(set(MEL_WORDS) | set(concept_words)) if w not in pats]
    if words:
        new_pats, cursor = allocate_pats(ng, words, 4, cursor)
        pats.update(new_pats)
    return cursor


def teach_both(ng, pats, word, traj):
    for _ in range(N_ROUNDS):
        _learn_sentence(ng, traj + [word], pats, slot=0)     # 感知桥
        _learn_sentence(ng, [word] + traj, pats, slot=0)     # 生成桥


def generate(ng, pats, word, traj, steps):
    """注入概念 → 回响 → 轨迹引导读出 mel 帧序列。"""
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
            hit = [w for w in MEL_WORDS
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


# ────────────────────────────────────────────────────────────────
#  main
# ────────────────────────────────────────────────────────────────

def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT / "runs" / f"_probe_sound_mel_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print("═══ mel 频谱物理层：真实音效逆向解析 + 反推 ═══", flush=True)
    rep = {"meta": {"ts": ts, "source": "ESC-50", "bands": N_BANDS,
                    "thresh": 0.25, "frame_ms": FRAME_MS}, "sections": {}}

    # 载入真实音效（8kHz 归一）
    import wave as wavmod
    def load(fp):
        w = wavmod.open(str(fp), "rb")
        n, sr, ch = w.getnframes(), w.getframerate(), w.getnchannels()
        d = np.frombuffer(w.readframes(n), dtype=np.int16).reshape(-1, ch)[:, 0]
        d = d.astype(np.float64) / 32767.0
        if sr != SR:
            t_new = np.arange(int(len(d) * SR / sr)) / SR
            d = np.interp(t_new, np.arange(len(d)) / sr, d)
        return d / (np.sqrt(np.mean(d ** 2)) + 1e-9)

    real = {"鸟": SOUND_DIR / "bird_real.wav",
            "牛": SOUND_DIR / "cow_real.wav",
            "猫": SOUND_DIR / "cat_real.wav"}
    waves = {w: load(fp) for w, fp in real.items()}

    # ── A. 逆向解析：mel 帧词结构（vs 过零率版：鸟跳变 0.735/牛 0.621/猫 0.49）──
    print("\n═══ A. 逆向解析（mel 编码真实音效）═══", flush=True)
    rep["sections"]["A_解析"] = {}
    for w, wave in waves.items():
        seq = encode_mel_frames(wave)
        from collections import Counter
        cnt = Counter(seq)
        total = len(seq)
        jumps = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
        traj = []
        for x in seq:
            if not traj or traj[-1] != x:
                traj.append(x)
        a = {"帧数": total, "唯一帧词": len(cnt),
             "主帧占比": round(cnt.most_common(1)[0][1] / total, 3),
             "跳变率": round(jumps / max(total - 1, 1), 3),
             "轨迹长度": len(traj), "前10帧": seq[:10]}
        rep["sections"]["A_解析"][w] = a
        print(f"  {w}: 唯一帧词={a['唯一帧词']} 主帧占比={a['主帧占比']} "
              f"跳变率={a['跳变率']} 轨迹长={a['轨迹长度']}（过零率版 0.735/0.621/0.49）",
              flush=True)

    # ── B. 反推：mel 轨迹教学 → 生成 → 一致率 ──
    print("\n═══ B. 反推（mel 轨迹教学 → 生成对比）═══", flush=True)
    ng = build_net()
    pats, cursor = {}, 0
    cursor = allocate(ng, pats, cursor, ["鸟", "牛", "猫"])
    seqs = {}
    for w, wave in waves.items():
        traj = []
        for x in encode_mel_frames(wave):
            if not traj or traj[-1] != x:
                traj.append(x)
        seqs[w] = traj
        teach_both(ng, pats, w, traj)
    rep["sections"]["B_反推"] = {}
    for w in seqs:
        traj = seqs[w]
        gen = [x for x in generate(ng, pats, w, traj, steps=len(traj) + 4) if x]
        gen = gen[:len(traj)]
        k = min(len(gen), len(traj))
        same = sum(1 for a, b in zip(gen[:k], traj[:k]) if a == b)
        r = {"教学轨迹长": len(traj), "生成轨迹长": len(gen),
             "轨迹一致率": round(same / k, 3) if k else 0.0}
        rep["sections"]["B_反推"][w] = r
        print(f"  {w}: 教学 {len(traj)} 帧 | 生成 {len(gen)} 帧 | 一致率 {r['轨迹一致率']}"
              f"（过零率版 0.082/0.526/0.204）", flush=True)

    # ── C. 声带 + 可听对比：原声 / mel 重建 / 网络生成 ──
    print("\n═══ C. 声带（多带合成）→ wav 存盘 ═══", flush=True)
    def save_wav(path, samples):
        pcm = np.clip(samples, -1, 1)
        with wavmod.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes((pcm * 32767).astype(np.int16).tobytes())
        print(f"  saved {path.name}", flush=True)

    rep["sections"]["C_声带"] = {}
    for w in seqs:
        traj = seqs[w]
        gen = [x for x in generate(ng, pats, w, traj, steps=len(traj) + 4) if x][:len(traj)]
        save_wav(run_dir / f"{w}_original.wav", waves[w])              # 原声
        save_wav(run_dir / f"{w}_mel_rebuild.wav", voicebox_mel(traj))  # mel 重建
        save_wav(run_dir / f"{w}_network.wav", voicebox_mel(gen))       # 网络生成
        # 闭环：网络生成声波 → 再听 → 唤起原概念
        heard = encode_mel_frames(voicebox_mel(gen))
        ev = evoke_ratio(ng, pats, heard, w) if heard else None
        rep["sections"]["C_声带"][w] = {"生成帧数": len(gen), "再听唤起": ev}
        print(f"  {w}: 网络生成 {len(gen)} 帧 → 声波再听 → 唤起 = {ev}", flush=True)

    rep["sections"]["summary"] = {
        "mel vs 过零率跳变率": {w: (rep["sections"]["A_解析"][w]["跳变率"], )
                              for w in real},
        "反推一致率(mel vs 过零率)": {w: (rep["sections"]["B_反推"][w]["轨迹一致率"], )
                                     for w in real},
        "生成声波再听唤起": {w: rep["sections"]["C_声带"][w]["再听唤起"] for w in real},
    }
    print("\n═══ 汇总 ═══", flush=True)
    for k, v in rep["sections"]["summary"].items():
        print(f"  {k}: {v}", flush=True)
    (run_dir / "result.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {run_dir}", flush=True)


if __name__ == "__main__":
    main()
