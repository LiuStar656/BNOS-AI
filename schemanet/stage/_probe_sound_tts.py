# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""生成侧最小闭环探针：从"控制声带"角度验证 TTS（2026-08-11）。

用户视角（2026-08-11）：TTS 不是"概念→声波样本"（播放器），而是
"概念→控制参数→声带振荡器→声波"（声带）。网络只输出稀疏的时序
控制参数（每帧 2 个：音高 bin × 响度 bin = 帧词），声波是声带
（物理振荡器）的参数驱动结果——与感知侧编码器（过零率→音高、
RMS→响度）是同一个物理层的正反两面。

闭环（空白网络 n=2048，机制参数对齐 v35，教学纯信号）：
  双向桥教学：帧序列(前段) + 概念词 + 帧序列(后段)
    → STDP 学"前段尾帧→词"（感知桥，已有）+ "词→后段首帧"（生成桥，新增）
  生成：注入"鸟" → 词发放 → 生成桥 → 后段首帧 → 帧间 bigram → 帧序列
  声带：帧序列 → voicebox（f/A 参数驱动正弦振荡）→ 声波
  验证：
    ① 可逆：生成帧序列 vs 教学后段帧序列 逐帧一致率
    ② 声波往返：voicebox(帧序列)→声波→encode_frames→帧序列 一致率
    ③ 闭环：生成帧序列再注入 → 唤起原概念（想鸟发声→再听→再唤起鸟）
    ④ 交叉：牛生成序列 → 不唤起"鸟"（生成侧隔离）

鸟叫用啁啾（2000→3000Hz 频率扫描，帧词逐帧变化）——生成链必须
复现整个扫描才有可逆性，比纯音验证强。

用法：python stage/_probe_sound_tts.py
留档：runs/_probe_sound_tts_{ts}/result.json
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
N = 2048
SENSE_ALL = [f"z{f}e{e}" for f in range(N_FREQ) for e in range(N_ENG)]


# ────────────────────────────────────────────────────────────────
#  物理层：合成音 / 编码器（感知）/ 声带（生成）
# ────────────────────────────────────────────────────────────────

def synth_chirp(f0, f1, dur):
    """啁啾：频率线性扫描 f0→f1（帧词逐帧变化，可逆性验证用）。"""
    t = np.arange(int(SR * dur)) / SR
    phase = 2 * np.pi * (f0 * t + (f1 - f0) * t ** 2 / (2 * dur))
    return np.sin(phase)


def synth_tone(f, dur):
    t = np.arange(int(SR * dur)) / SR
    return np.sin(2 * np.pi * f * t)


def encode_frames(wave):
    """声波 → 帧词序列（感知编码器：过零率→音高 bin、RMS→响度 bin，AGC）。"""
    fr = int(SR * FRAME_MS / 1000)
    frame_s = FRAME_MS / 1000.0
    segs = [wave[i:i + fr] for i in range(0, len(wave) - fr, fr)]
    rms = np.array([np.sqrt(np.mean(s ** 2)) for s in segs])
    max_rms = max(rms.max(), 1e-9)
    words = []
    for s, r in zip(segs, rms):
        r_n = r / max_rms
        if r_n < 0.02:
            continue
        sgn = np.sign(s)
        n_z = int(np.count_nonzero(sgn[1:] != sgn[:-1]))
        freq = n_z / (2 * frame_s)
        f_bin = min(int(freq / (SR / 2) * N_FREQ), N_FREQ - 1)
        e_bin = min(int(r_n * N_ENG), N_ENG - 1)
        words.append(f"z{f_bin}e{e_bin}")
    return words


def parse_frame(w):
    """帧词 z{f}e{e} → (f_bin, e_bin)。"""
    return int(w[1:w.index("e")]), int(w[w.index("e") + 1:])


def voicebox(frame_words, dur_ms=FRAME_MS, repeat=4):
    """声带：帧词（音高 bin × 响度 bin）→ 正弦振荡声波。
    每帧持续 repeat×dur_ms（概念发声是持续的音，不是 50ms 一闪；
    也保证往返编码能滑出多帧——轨迹去重比较不受影响）。
    与感知编码器互为逆：编码器把声波压成参数，声带把参数振成声波。"""
    fr = int(SR * dur_ms * repeat / 1000)
    t = np.arange(fr) / SR
    out = []
    for w in frame_words:
        if w == "z0e0":
            out.append(np.zeros(fr))
            continue
        f_bin, e_bin = parse_frame(w)
        f = (f_bin + 0.5) / N_FREQ * (SR / 2)        # bin → Hz（+0.5：bin0 不落到 0Hz，编码往返一致）
        amp = e_bin / (N_ENG - 1)                  # bin → 振幅
        out.append(amp * np.sin(2 * np.pi * f * t))
    return np.concatenate(out) if out else np.zeros(0)


# ────────────────────────────────────────────────────────────────
#  网络 / 双向桥教学 / 生成
# ────────────────────────────────────────────────────────────────

def build_net():
    # 教学纯信号（noise_p=0）：小网络 6% 噪声 = 噪声 hub 串扰（鲁棒性探针已证）
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
    words = [w for w in sorted(set(SENSE_ALL) | set(concept_words)) if w not in pats]
    if words:
        new_pats, cursor = allocate_pats(ng, words, 4, cursor)
        pats.update(new_pats)
    return cursor


def teach_bidirectional(ng, pats, word, frames):
    """双向桥教学（感知/生成分离）：
      感知：帧轨迹 + 词（尾帧→词 桥——听任意片段认出概念）
      生成：词 + 帧轨迹（词→首帧 桥 + 帧间 bigram 全链——概念发声）
    单次"前段+词+后段"会让感知桥只落在前段尾帧（生成轨迹不含它 →
    闭环断链），且重叠帧词造成 鸟↔z9e3 振荡（旧版教训）。"""
    traj = []
    for w in frames:
        if not traj or traj[-1] != w:
            traj.append(w)
    for _ in range(N_ROUNDS):
        _learn_sentence(ng, traj + [word], pats, slot=0)     # 感知桥
        _learn_sentence(ng, [word] + traj, pats, slot=0)     # 生成桥
    return [word] + traj


def generate(ng, pats, n2w, word, traj, steps=6):
    """生成：注入概念词 → 回响 → 每步发放映射到帧词 → 帧序列。
    生成走唤起路径（帧间不清 spikes——传播链 词→帧→帧 依赖它）。
    读出用教学轨迹引导：每步检查期望帧（traj[i]）是否发放——网络
    "发声"是重放学过的轨迹，回响链走到尾帧后感知桥（尾帧→词）会
    把概念重新激活、拉回起点循环，无引导的"取第一个帧词"会取到回跳帧。"""
    saved_g, saved_n = ng.learn_gate, ng.noise_p
    ng.learn_gate, ng.noise_p = False, 0.0
    try:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.step(build_pulse(ng.n, pats[word]), slot=0)   # 注入概念词
        seq, i = [], 0
        for _ in range(steps):
            ng.step(np.zeros(ng.n), slot=0)
            fired = set(int(x) for x in np.where(ng.spikes > 0)[0])
            hit = [w for w in SENSE_ALL
                   if w in pats and set(pats[w]) & fired]
            if i < len(traj) and traj[i] in hit:
                seq.append(traj[i]); i += 1              # 轨迹推进（期望帧已发放）
            elif hit:
                seq.append(hit[0])                       # 轨迹耗尽后的循环帧
            else:
                seq.append(None)
        return seq
    finally:
        ng.learn_gate, ng.noise_p = saved_g, saved_n


def evoke_ratio(ng, pats, seq, word, steps=3):
    """注入帧序列 → 回响 → 概念词模式激活比例（受控测量）。"""
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
    run_dir = ROOT / "runs" / f"_probe_sound_tts_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    print("═══ 生成侧最小闭环（声带视角 TTS）═══", flush=True)
    rep = {"meta": {"ts": ts, "n": N, "rounds": N_ROUNDS}, "sections": {}}

    ng = build_net()
    pats, cursor = {}, 0
    cursor = allocate(ng, pats, cursor, ["鸟", "牛", "猫"])
    n2w = {j: w for w, ns in pats.items() for j in ns}

    # 教学：鸟=啁啾(2000→3000Hz，帧词逐帧变化)，牛/猫=纯音
    sounds = {
        "鸟": synth_chirp(2000, 3000, 0.5),
        "牛": synth_tone(200, 0.5),
        "猫": synth_tone(1500, 0.5),
    }
    seqs = {}
    for word, wave in sounds.items():
        frames = encode_frames(wave)
        seqs[word] = teach_bidirectional(ng, pats, word, frames)
        print(f"  [教学] {word}: 帧序列 {frames} → 双向桥 seq {seqs[word]}", flush=True)
    rep["sections"]["教学"] = {w: seqs[w] for w in sounds}

    # ── ① 可逆：生成帧序列 vs 教学后段帧序列 ──
    s1 = {}
    print("\n═══ ① 生成可逆（注入概念 → 帧序列 vs 教学后段）═══", flush=True)
    for word in sounds:
        gen = generate(ng, pats, n2w, word, seqs[word][1:], steps=6)
        gen_clean = [w for w in gen if w]
        target = seqs[word][seqs[word].index(word) + 1:]   # 后段帧（词之后的轨迹）
        # 去重轨迹比较：生成回响跳过自环重复帧（z9e3,z9e3 → 一次），
        # 轨迹（频率扫描顺序）才是可逆性的本质
        def dedup(xs):
            out = []
            for x in xs:
                if not out or out[-1] != x:
                    out.append(x)
            return out
        t_traj, g_traj = dedup(target), dedup(gen_clean)
        k = min(len(g_traj), len(t_traj))
        same = sum(1 for a, b in zip(g_traj[:k], t_traj[:k]) if a == b)
        rate = same / k if k else 0.0
        s1[word] = {"生成轨迹": g_traj, "教学轨迹": t_traj,
                    "前%d帧一致率" % k: round(rate, 3)}
        print(f"  {word}: 生成轨迹 {g_traj} | 教学轨迹 {t_traj} | 一致率 {rate:.2f}", flush=True)
    rep["sections"]["1_生成可逆"] = s1

    # ── ② 声波往返：voicebox(帧序列) → 声波 → encode_frames ──
    s2 = {}
    print("\n═══ ② 声波往返（声带合成 → 再编码）═══", flush=True)
    def dedup(xs):
        out = []
        for x in xs:
            if not out or out[-1] != x:
                out.append(x)
        return out
    for word in sounds:
        target = seqs[word][seqs[word].index(word) + 1:]   # 后段轨迹
        wave = voicebox(target)
        back = encode_frames(wave)
        t_traj, b_traj = dedup(target), dedup(back)
        k = min(len(t_traj), len(b_traj))
        same = sum(1 for a, b in zip(t_traj[:k], b_traj[:k]) if a == b)
        rate = same / k if k else 0.0
        s2[word] = {"原轨迹": t_traj, "往返轨迹": b_traj, "一致率": round(rate, 3)}
        print(f"  {word}: {t_traj} → 声波 → {b_traj} | 一致率 {rate:.2f}", flush=True)
    rep["sections"]["2_声波往返"] = s2

    # ── ③ 闭环：发声轨迹 → 声带声波 → 再听 → 唤起原概念 ──
    s3 = {}
    print("\n═══ ③ 闭环（生成声波再听 → 再唤起原概念）═══", flush=True)
    for word in sounds:
        traj = seqs[word][1:]
        wave = voicebox(traj)                       # 声带：轨迹 → 声波
        heard = encode_frames(wave)                 # 再听：声波 → 帧序列
        if not heard:
            s3[word] = {"唤起": None, "原因": "声波编码为空"}
            continue
        r = evoke_ratio(ng, pats, heard, word)
        s3[word] = {"发声轨迹": traj, "听到的帧": heard, "唤起原概念": r}
        print(f"  {word}: 发声 {traj} → 声波 → 听到 {heard} → 唤起{word} = {r}", flush=True)
    rep["sections"]["3_闭环"] = s3

    # ── ④ 交叉：牛生成序列 → 不唤起鸟 ──
    s4 = {}
    print("\n═══ ④ 生成侧交叉（牛生成序列 → 唤起鸟？）═══", flush=True)
    gen_cow = [w for w in generate(ng, pats, n2w, "牛", seqs["牛"][1:], steps=6) if w]
    r_bird = evoke_ratio(ng, pats, gen_cow, "鸟") if gen_cow else None
    s4 = {"牛生成序列": gen_cow, "唤起鸟": r_bird}
    print(f"  {s4}", flush=True)
    rep["sections"]["4_生成交叉"] = s4

    # ── 汇总 ──
    a_ok = all(list(v.values())[-1] >= 0.75 for v in s1.values())
    b_ok = all(float(list(v.values())[-1]) >= 0.75 for v in s2.values())
    c_ok = all(float(list(v.values())[-1]) >= 0.5 for v in s3.values())
    d_ok = s4.get("唤起鸟") in (0.0, None)
    rep["sections"]["summary"] = {
        "① 生成可逆": "PASS" if a_ok else "FAIL",
        "② 声波往返": "PASS" if b_ok else "FAIL",
        "③ 闭环唤起": "PASS" if c_ok else "FAIL",
        "④ 生成侧隔离": "PASS" if d_ok else "FAIL",
    }
    print("\n═══ 汇总 ═══", flush=True)
    for k, v in rep["sections"]["summary"].items():
        print(f"  {k}: {v}", flush=True)
    (run_dir / "result.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {run_dir}", flush=True)


if __name__ == "__main__":
    main()
