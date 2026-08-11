# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""脉冲字符：数字(PCM)→Δ脉冲流→8位打包成字符→网络反复学（2026-08-11）。

用户路线（2026-08-11）："脉冲信号应该是字符，把字符送到网络里反复学"。
关键性质：Δ调制（近无损）+ 8 位打包（无损）→ 整个转译链路**无损**——
字符流保留脉冲流的一切时间结构（这是 mel/VQ 做不到的）。

  PCM(8kHz) → 一阶Δ(不过采样) → 1-bit流(±1) → 每8位打包 → 字符 p0..p255
  → 字符序列送网络双向桥教学（3 轮反复）→ 感知/生成/闭环

预期边界（Δ 调制的已知属性）：
  - 低频（牛 200Hz）：Δ 正常调制，字符流有周期结构（40 采样/周期=5 字节
    重复）→ bigram 可学 → 感知应通
  - 高频（鸟 2-4kHz @8kHz）：斜率过载，Δ 流混乱 → 字符随机 → 学不到
    （若实证成立 = "无损链路只在 Δ 不斜率过载的频率段可用"）

用法：python stage/_probe_pulse_chars.py
留档：runs/_probe_pulse_chars_{ts}/result.json
"""
import json
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema_net import _learn_sentence, build_pulse
from sparse_net import SparseSchemaNet, allocate_pats
from stage._probe_sound_mel import SR
from stage._probe_pop_coding import load_wav_8k

ROOT = Path(__file__).resolve().parent.parent
SOUND_DIR = ROOT / "runs" / "_real_sounds"

DUR = 0.2                        # 每音时长（s）——字符流 200 个，可学粒度
CHARS = [f"p{i}" for i in range(256)]
N_ROUNDS = 3


# ────────────────────────────────────────────────────────────────
#  无损链路：PCM → Δ脉冲流 → 8 位打包字符
# ────────────────────────────────────────────────────────────────

def delta_modulate(x):
    """一阶 Δ 调制（不过采样）：y[n] = sign(x[n] - acc[n-1])，acc 跟随。"""
    y = np.zeros(len(x))
    acc = 0.0
    for n in range(len(x)):
        e = x[n] - acc
        y[n] = 1.0 if e > 0 else -1.0
        acc += 0.02 * y[n]                 # 积分增益（步长匹配 ±1 输入）
    return y


def pack_chars(pulses):
    """1-bit 流（±1）→ 每 8 位打包 → 字符 p0..p255（无损）。"""
    bits = (pulses > 0).astype(int)
    n = len(bits) // 8
    vals = bits[:n * 8].reshape(-1, 8)
    weights = (1 << np.arange(8))[::-1]
    return [f"p{int((vals[i] * weights).sum())}" for i in range(n)]


def unpack_pulses(chars):
    """字符流 → 1-bit 流（打包的逆，无损）。"""
    out = []
    for c in chars:
        v = int(c[1:])
        out.extend([1.0 if (v >> k) & 1 else -1.0 for k in range(7, -1, -1)])
    return np.array(out)


def delta_decode(pulses, lowpass_taps=33):
    """逆Δ：泄漏积分 + 低通（重建波形）。"""
    v = 0.0
    out = np.zeros(len(pulses))
    for i, p in enumerate(pulses):
        v = v * 0.98 + p * 0.02
        out[i] = v
    b = np.ones(lowpass_taps) / lowpass_taps
    return np.convolve(out, b, mode="same")


# ────────────────────────────────────────────────────────────────
#  网络 / 教学 / 验证
# ────────────────────────────────────────────────────────────────

def build_net():
    ng = SparseSchemaNet(rng=np.random.default_rng(7), n=4096, slots=4,
                         theta=1.0, membrane_decay=0.9, eta=0.1, w_max=64.0,
                         wta_k=20, noise_p=0.0, noise_amp=0.5,
                         weight_decay=0.0, slot_cap=0.0, stdp_pre=0.5,
                         stdp_neg=0.0, trace_decay=0.5, refractory=1,
                         learn_gate=True, inh_loose=0.3, std_dep=0.0,
                         std_rec=0.85, edge_min=0.0, inh_norm=0.0,
                         refract_clear=False)
    return ng


def allocate(ng, pats, cursor, concept_words):
    words = [w for w in sorted(set(CHARS) | set(concept_words)) if w not in pats]
    if words:
        new_pats, cursor = allocate_pats(ng, words, 4, cursor)
        pats.update(new_pats)
    return cursor


def teach_both(ng, pats, word, seq):
    for _ in range(N_ROUNDS):
        _learn_sentence(ng, seq + [word], pats, slot=0)
        _learn_sentence(ng, [word] + seq, pats, slot=0)


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
            hit = [w for w in CHARS
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
    run_dir = ROOT / "runs" / f"_probe_pulse_chars_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print("═══ 脉冲字符：PCM→Δ→8位打包→网络反复学 ═══", flush=True)
    rep = {"meta": {"ts": ts, "dur": DUR, "pack": 8, "charset": 256},
           "sections": {}}

    real = {"鸟": SOUND_DIR / "bird_real.wav",
            "牛": SOUND_DIR / "cow_real.wav",
            "猫": SOUND_DIR / "cat_real.wav"}
    char_seqs = {}
    rep["sections"]["转译"] = {}
    for w, fp in real.items():
        x8 = load_wav_8k(fp)[:int(SR * DUR)]
        x8 = x8 / np.max(np.abs(x8))
        pulses = delta_modulate(x8)
        chars = pack_chars(pulses)
        char_seqs[w] = chars
        from collections import Counter
        cnt = Counter(chars)
        jumps = sum(1 for a, b in zip(chars, chars[1:]) if a != b)
        rep["sections"]["转译"][w] = {"字符数": len(chars), "唯一字符": len(cnt),
                                      "跳变率": round(jumps / max(len(chars) - 1, 1), 3)}
        print(f"  {w}: {len(chars)} 字符 唯一 {len(cnt)} 跳变率 "
              f"{jumps/max(len(chars)-1,1):.3f}", flush=True)

    # ── 教学（反复学 3 轮）──
    ng = build_net()
    pats, cursor = {}, 0
    cursor = allocate(ng, pats, cursor, ["鸟", "牛", "猫"])
    for w, chars in char_seqs.items():
        traj = []
        for x in chars:
            if not traj or traj[-1] != x:
                traj.append(x)
        teach_both(ng, pats, w, traj)
        print(f"  [教学] {w}: 轨迹 {len(traj)} 字符 × {N_ROUNDS} 轮", flush=True)

    # ── 感知 ──
    print("\n═══ 感知（字符流 → 唤起概念）═══", flush=True)
    s1 = {f"{w}流→{w}": evoke_ratio(ng, pats, char_seqs[w], w) for w in char_seqs}
    print(f"  {s1}", flush=True)
    rep["sections"]["感知"] = s1

    # ── 交叉 ──
    print("\n═══ 交叉 ═══", flush=True)
    s2 = {f"{wa}流→{wb}": evoke_ratio(ng, pats, char_seqs[wa], wb)
          for wa in char_seqs for wb in char_seqs if wa != wb}
    print(f"  {s2}", flush=True)
    rep["sections"]["交叉"] = s2

    # ── 生成：概念 → 字符流 → 解包 → 逆Δ → 声波 → 再听 ──
    print("\n═══ 生成（概念→字符→脉冲→声波→再听）═══", flush=True)
    s3 = {}
    for w in char_seqs:
        traj = []
        for x in char_seqs[w]:
            if not traj or traj[-1] != x:
                traj.append(x)
        gen = [x for x in generate(ng, pats, w, traj, steps=len(traj) + 4) if x]
        gen = gen[:len(traj)]
        pulses = unpack_pulses(gen)
        wave = delta_decode(pulses)
        heard = pack_chars(delta_modulate(wave / (np.max(np.abs(wave)) + 1e-9)))
        ev = evoke_ratio(ng, pats, heard, w) if heard else None
        k = min(len(gen), len(traj))
        same = sum(1 for a, b in zip(gen[:k], traj[:k]) if a == b)
        s3[w] = {"轨迹一致率": round(same / k, 3) if k else 0.0, "再听唤起": ev}
        print(f"  {w}: 生成 {len(gen)} 字符 一致率={s3[w]['轨迹一致率']} 再听={ev}",
              flush=True)
    rep["sections"]["生成"] = s3

    rep["sections"]["summary"] = {"感知": s1, "交叉": s2, "生成": s3}
    print("\n═══ 汇总 ═══", flush=True)
    for k, v in rep["sections"]["summary"].items():
        print(f"  {k}: {v}", flush=True)
    (run_dir / "result.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {run_dir}", flush=True)


if __name__ == "__main__":
    main()
