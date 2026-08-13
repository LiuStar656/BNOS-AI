# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""B1: VQ 原型量化——真实音效 mel 向量数据驱动聚类（2026-08-11）。

路线（用户："继续，直到完全走不通"）：先量化原始音频 → 连续 mel 向量 →
**VQ（矢量量化）**：k-means 把三音全部帧的 mel 向量聚成 K=64 个原型状态，
帧词 = 最近原型 ID。对比均匀 mel 256 词版（跳变率 0.53-0.58、反推
0.06-0.19、感知鸟/牛 1.0 猫 0.0）：
  - 精度由数据决定（频谱密集处原型多、稀疏处少——自适应，优于均匀 bin）
  - 词表固定 64（转移对可重复、bigram 可学）
  - k-means 是无监督数据统计（非转译模型，无语义）

验证：A 逆向解析（VQ 帧词结构 vs 均匀 mel）→ B 感知（全音流→概念）
→ C 生成（概念→原型流→码本声带→声波→再听唤起）→ D 交叉。

用法：python stage/_probe_vq_mel.py
留档：runs/_probe_vq_mel_{ts}/result.json
"""
import json
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema_net import _learn_sentence, build_pulse
from sparse_net import SparseSchemaNet, allocate_pats
from stage._probe_sound_mel import _W, _CENTERS, build_net, SR, FRAME_MS

ROOT = Path(__file__).resolve().parent.parent
SOUND_DIR = ROOT / "runs" / "_real_sounds"

N_PROTO = 64                     # VQ 原型数
VQ_WORDS = [f"v{i}" for i in range(N_PROTO)]
N_ROUNDS = 3


# ────────────────────────────────────────────────────────────────
#  数据：真实音效 → mel 向量帧
# ────────────────────────────────────────────────────────────────

def load_wav_8k(fp):
    w = wave.open(str(fp), "rb")
    n, sr, ch = w.getnframes(), w.getframerate(), w.getnchannels()
    d = np.frombuffer(w.readframes(n), dtype=np.int16).reshape(-1, ch)[:, 0]
    d = d.astype(np.float64) / 32767.0
    if sr != SR:
        t_new = np.arange(int(len(d) * SR / sr)) / SR
        d = np.interp(t_new, np.arange(len(d)) / sr, d)
    return d / (np.sqrt(np.mean(d ** 2)) + 1e-9)


def mel_frames(wave, n_fft=512):
    """声波 → 每帧 8 维 mel 向量（log 能量、帧内归一——连续，不量化）。"""
    fr = int(SR * FRAME_MS / 1000)
    win = np.hanning(fr)
    frames = []
    for i in range(0, len(wave) - fr, fr):
        spec = np.abs(np.fft.rfft(wave[i:i + fr] * win, n_fft)) ** 2
        be = _W @ spec
        m = be.max()
        if m > 1e-12:
            frames.append(be / m)
    return np.array(frames) if frames else np.zeros((0, len(_CENTERS)))


def kmeans(X, k=N_PROTO, iters=60, seed=7):
    """numpy k-means（无监督数据统计）。"""
    rng = np.random.default_rng(seed)
    centers = X[rng.choice(len(X), k, replace=False)].copy()
    for _ in range(iters):
        d = ((X[:, None, :] - centers[None, :, :]) ** 2).sum(-1)
        assign = d.argmin(1)
        new = np.array([X[assign == i].mean(0) if (assign == i).any() else centers[i]
                        for i in range(k)])
        centers = new
    return centers


def frames_to_vq(frames, centers):
    """mel 帧向量 → VQ 帧词序列。"""
    d = ((frames[:, None, :] - centers[None, :, :]) ** 2).sum(-1)
    return [f"v{int(i)}" for i in d.argmin(1)]


# ────────────────────────────────────────────────────────────────
#  网络 / 教学 / 验证（复用 mel 探针模式）
# ────────────────────────────────────────────────────────────────

def allocate(ng, pats, cursor, concept_words):
    words = [w for w in sorted(set(VQ_WORDS) | set(concept_words)) if w not in pats]
    if words:
        new_pats, cursor = allocate_pats(ng, words, 4, cursor)
        pats.update(new_pats)
    return cursor


def teach_both(ng, pats, word, traj):
    for _ in range(N_ROUNDS):
        _learn_sentence(ng, traj + [word], pats, slot=0)
        _learn_sentence(ng, [word] + traj, pats, slot=0)


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
            hit = [w for w in VQ_WORDS
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


def voicebox_vq(vq_words, centers, dur_ms=FRAME_MS, repeat=4):
    """码本声带：原型中心（mel 能量向量）→ 多带正弦叠加。"""
    fr = int(SR * dur_ms * repeat / 1000)
    t = np.arange(fr) / SR
    out = []
    for w in vq_words:
        vec = centers[int(w[1:])]
        wave = sum(0.5 * vec[k] * np.sin(2 * np.pi * _CENTERS[k] * t)
                   for k in range(len(vec)))
        m = np.abs(wave).max()
        out.append(wave / (m + 1e-9) * 0.5)
    return np.concatenate(out) if out else np.zeros(0)


# ────────────────────────────────────────────────────────────────
#  main
# ────────────────────────────────────────────────────────────────

def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT / "runs" / f"_probe_vq_mel_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print("═══ B1: VQ 原型量化（真实音效 mel → 64 原型）═══", flush=True)
    rep = {"meta": {"ts": ts, "k": N_PROTO, "source": "ESC-50"}, "sections": {}}

    real = {"鸟": SOUND_DIR / "bird_real.wav",
            "牛": SOUND_DIR / "cow_real.wav",
            "猫": SOUND_DIR / "cat_real.wav"}
    waves = {w: load_wav_8k(fp) for w, fp in real.items()}
    frames_all = {w: mel_frames(wave) for w, wave in waves.items()}

    # ── VQ 码本：三音全部帧聚类 ──
    X = np.concatenate(list(frames_all.values()))
    centers = kmeans(X)
    print(f"  VQ 码本: {X.shape[0]} 帧 → {N_PROTO} 原型（mel 8 维）", flush=True)
    rep["sections"]["码本"] = {"帧数": len(X), "原型": N_PROTO}

    # ── A. 逆向解析：VQ 帧词结构 vs 均匀 mel 256 词 ──
    print("\n═══ A. 逆向解析（VQ 帧词结构）═══", flush=True)
    rep["sections"]["A_解析"] = {}
    for w, frames in frames_all.items():
        seq = frames_to_vq(frames, centers)
        from collections import Counter
        cnt = Counter(seq)
        total = len(seq)
        jumps = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
        a = {"帧数": total, "唯一原型": len(cnt),
             "主原型占比": round(cnt.most_common(1)[0][1] / total, 3),
             "跳变率": round(jumps / max(total - 1, 1), 3),
             "前10帧": seq[:10]}
        rep["sections"]["A_解析"][w] = a
        print(f"  {w}: 唯一原型={a['唯一原型']} 主原型占比={a['主原型占比']} "
              f"跳变率={a['跳变率']}（均匀 mel: 0.571/0.531/0.582）", flush=True)

    # ── B. 教学 + 感知 ──
    ng = build_net()
    pats, cursor = {}, 0
    cursor = allocate(ng, pats, cursor, ["鸟", "牛", "猫"])
    trajs = {}
    for w, frames in frames_all.items():
        seq = frames_to_vq(frames, centers)
        traj = []
        for x in seq:
            if not traj or traj[-1] != x:
                traj.append(x)
        trajs[w] = traj
        teach_both(ng, pats, w, traj)
        print(f"  [教学] {w}: VQ 轨迹 {len(traj)} 帧", flush=True)

    print("\n═══ B. 感知（全音 VQ 流 → 唤起概念）═══", flush=True)
    sB = {}
    for w in waves:
        seq = frames_to_vq(frames_all[w], centers)
        sB[f"{w}流→{w}"] = evoke_ratio(ng, pats, seq, w)
    print(f"  {sB}", flush=True)
    rep["sections"]["B_感知"] = sB

    # ── C. 生成 + 闭环 ──
    print("\n═══ C. 生成（概念→原型流→码本声带→声波→再听）═══", flush=True)
    sC = {}
    for w in waves:
        traj = trajs[w]
        gen = [x for x in generate(ng, pats, w, traj, steps=len(traj) + 4) if x]
        gen = gen[:len(traj)]
        wave = voicebox_vq(gen, centers)
        heard = frames_to_vq(mel_frames(wave), centers)
        ev = evoke_ratio(ng, pats, heard, w) if len(heard) else None
        k = min(len(gen), len(traj))
        same = sum(1 for a, b in zip(gen[:k], traj[:k]) if a == b)
        sC[w] = {"轨迹一致率": round(same / k, 3) if k else 0.0,
                 "再听唤起": ev}
        print(f"  {w}: 生成 {len(gen)} 帧 轨迹一致率={sC[w]['轨迹一致率']} "
              f"再听唤起={ev}", flush=True)
        import wave as wavmod
        pcm = np.clip(wave, -1, 1)
        with wavmod.open(str(run_dir / f"{w}_network_vq.wav"), "wb") as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(SR)
            f.writeframes((pcm * 32767).astype(np.int16).tobytes())
    rep["sections"]["C_生成闭环"] = sC

    # ── D. 交叉 ──
    print("\n═══ D. 交叉（他音流 → 唤起鸟？）═══", flush=True)
    sD = {f"{wa}流→鸟": evoke_ratio(ng, pats, frames_to_vq(frames_all[wa], centers), "鸟")
          for wa in waves if wa != "鸟"}
    print(f"  {sD}", flush=True)
    rep["sections"]["D_交叉"] = sD

    rep["sections"]["summary"] = {
        "A 解析跳变率": {w: rep["sections"]["A_解析"][w]["跳变率"] for w in waves},
        "B 感知": sB,
        "C 生成一致率/再听": {w: sC[w] for w in waves},
        "D 交叉": sD,
    }
    print("\n═══ 汇总 ═══", flush=True)
    for k, v in rep["sections"]["summary"].items():
        print(f"  {k}: {v}", flush=True)
    (run_dir / "result.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {run_dir}", flush=True)


if __name__ == "__main__":
    main()
