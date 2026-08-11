# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""真实自然音效逆向解析 + 反推探针（2026-08-11）。

用户评价（2026-08-11）：合成正弦音"完全牛头不对马嘴"——要求用开源
自然音效库（ESC-50：chirping_birds/cow/cat 真实录音）先逆向解析再反推。

逆向解析要回答：现有物理层（过零率→频率bin + RMS→能量bin，64 帧词）
解析**真实音效**（宽频啁啾/谐波/共振/噪声）时，帧词序列有没有结构？
  - 若有结构（主帧词占比高、轨迹稳定）→ 反推可行：教学→生成→对比
  - 若解析乱（帧词频繁跳变）→ 物理层表达力不足的量化证据：
    真实频谱复杂度 vs 64 bin 单频估计的差距（这正是"牛头不对马嘴"的根因）

对照：同一套指标跑合成音（鸟 chirp / 牛纯音 / 猫纯音）——量化"真实 vs
合成"在物理层下的编码距离。

反推（若结构可用）：帧轨迹 + 概念词 双向桥教学 → 注入概念生成轨迹 →
voicebox 合成 → 与真实帧轨迹逐帧一致率。

用法：python stage/_probe_sound_real.py
留档：runs/_probe_sound_real_{ts}/result.json
"""
import json
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stage._probe_sound_tts import (build_net, allocate, teach_bidirectional,
                                    generate, voicebox, encode_frames,
                                    synth_chirp, synth_tone, parse_frame, SR)
from schema_net import _learn_sentence

ROOT = Path(__file__).resolve().parent.parent
SOUND_DIR = ROOT / "runs" / "_real_sounds"


# ────────────────────────────────────────────────────────────────
#  数据：真实 wav → 8kHz 单声道
# ────────────────────────────────────────────────────────────────

def load_wav_8k(fp):
    import wave
    w = wave.open(str(fp), "rb")
    n, sr, ch = w.getnframes(), w.getframerate(), w.getnchannels()
    data = np.frombuffer(w.readframes(n), dtype=np.int16).reshape(-1, ch)[:, 0]
    data = data.astype(np.float64) / 32767.0
    if sr != SR:                                   # 线性重采样 → 8kHz
        t_new = np.arange(int(len(data) * SR / sr)) / SR
        t_old = np.arange(len(data)) / sr
        data = np.interp(t_new, t_old, data)
    rms = np.sqrt(np.mean(data ** 2))
    return data / (rms + 1e-9)                     # 归一（AGC 前级）


# ────────────────────────────────────────────────────────────────
#  逆向解析统计
# ────────────────────────────────────────────────────────────────

def analyze(wave, tag):
    """帧词序列 + 结构性指标（对照合成音与真实音）。"""
    seq = encode_frames(wave)
    from collections import Counter
    cnt = Counter(seq)
    total = len(seq)
    n_unique = len(cnt)
    main_ratio = cnt.most_common(1)[0][1] / total if total else 0.0
    jumps = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
    jump_rate = jumps / max(total - 1, 1)
    traj = []
    for w in seq:
        if not traj or traj[-1] != w:
            traj.append(w)
    return {"tag": tag, "帧数": total, "唯一帧词": n_unique,
            "主帧词占比": round(main_ratio, 3),
            "跳变率": round(jump_rate, 3),
            "轨迹长度": len(traj),
            "前12帧": seq[:12],
            "轨迹前12": traj[:12]}


# ────────────────────────────────────────────────────────────────
#  反推：真实轨迹教学 → 生成 → 对比
# ────────────────────────────────────────────────────────────────

def reverse_synth(ng, pats, n2w, word, real_seq):
    """用真实音效的帧轨迹教学（去重轨迹），注入概念生成，对比轨迹。"""
    traj = []
    for w in real_seq:
        if not traj or traj[-1] != w:
            traj.append(w)
    for _ in range(3):
        _learn_sentence(ng, traj + [word], pats, slot=0)     # 感知桥
        _learn_sentence(ng, [word] + traj, pats, slot=0)     # 生成桥
    gen = [w for w in generate(ng, pats, n2w, word, traj, steps=len(traj) + 4) if w]
    gen = gen[:len(traj)]
    k = min(len(gen), len(traj))
    same = sum(1 for a, b in zip(gen[:k], traj[:k]) if a == b)
    return {"教学轨迹": traj, "生成轨迹": gen,
            "轨迹一致率": round(same / k, 3) if k else 0.0}


# ────────────────────────────────────────────────────────────────
#  main
# ────────────────────────────────────────────────────────────────

def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT / "runs" / f"_probe_sound_real_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print("═══ 真实自然音效：逆向解析 + 反推 ═══", flush=True)
    rep = {"meta": {"ts": ts, "source": "ESC-50 (karolpiczak/ESC-50)",
                    "sr": SR, "frame_ms": 50}, "sections": {}}

    real = {
        "鸟": SOUND_DIR / "bird_real.wav",
        "牛": SOUND_DIR / "cow_real.wav",
        "猫": SOUND_DIR / "cat_real.wav",
    }
    waves_real = {w: load_wav_8k(fp) for w, fp in real.items()}
    waves_synth = {"鸟": synth_chirp(2000, 3000, 0.5),
                   "牛": synth_tone(200, 0.5),
                   "猫": synth_tone(1500, 0.5)}

    # ── A. 逆向解析：真实音效 vs 合成音 编码结构 ──
    print("\n═══ A. 逆向解析（真实 vs 合成 → 帧词结构）═══", flush=True)
    rep["sections"]["A_解析"] = {"真实": {}, "合成": {}}
    for w in real:
        a_r = analyze(waves_real[w], f"真实{w}")
        a_s = analyze(waves_synth[w], f"合成{w}")
        rep["sections"]["A_解析"]["真实"][w] = a_r
        rep["sections"]["A_解析"]["合成"][w] = a_s
        print(f"  真实{w}: 唯一帧词={a_r['唯一帧词']} 主帧占比={a_r['主帧词占比']} "
              f"跳变率={a_r['跳变率']} 轨迹长={a_r['轨迹长度']}", flush=True)
        print(f"    前12帧 {a_r['前12帧']}", flush=True)
        print(f"  合成{w}: 唯一帧词={a_s['唯一帧词']} 主帧占比={a_s['主帧词占比']} "
              f"跳变率={a_s['跳变率']} 轨迹长={a_s['轨迹长度']}", flush=True)

    # ── B. 反推：真实轨迹能否教学/生成/复现 ──
    print("\n═══ B. 反推（真实帧轨迹教学 → 生成对比）═══", flush=True)
    ng = build_net()
    pats, cursor = {}, 0
    cursor = allocate(ng, pats, cursor, ["鸟", "牛", "猫"])
    n2w = {j: w for w, ns in pats.items() for j in ns}
    rep["sections"]["B_反推"] = {}
    for w in real:
        real_seq = encode_frames(waves_real[w])
        r = reverse_synth(ng, pats, n2w, w, real_seq)
        rep["sections"]["B_反推"][w] = r
        print(f"  {w}: 教学轨迹 {r['教学轨迹'][:10]}… | 生成轨迹 {r['生成轨迹'][:10]}… "
              f"| 一致率 {r['轨迹一致率']}", flush=True)

    # ── 汇总：物理层表达力判定 ──
    real_ok = {w: rep["sections"]["A_解析"]["真实"][w]["主帧词占比"]
               for w in real}
    rep["sections"]["summary"] = {
        "物理层解析真实音效": ("帧词有结构（主帧占比/轨迹可用）"
                              if all(v > 0.3 for v in real_ok.values())
                              else "帧词散乱：64 bin 单频估计表达力不足（牛头不对马嘴的量化根因）"),
        "反推轨迹一致率": {w: rep["sections"]["B_反推"][w]["轨迹一致率"] for w in real},
    }
    print("\n═══ 汇总 ═══", flush=True)
    for k, v in rep["sections"]["summary"].items():
        print(f"  {k}: {v}", flush=True)
    (run_dir / "result.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n留档: {run_dir}", flush=True)


if __name__ == "__main__":
    main()
