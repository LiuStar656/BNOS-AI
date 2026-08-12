# -*- coding: utf-8 -*-
"""活泼维度定向验证（省钱版）：playfulness 高低是否真的影响输出。

背景：instrAB 实验发现无指令时 playfulness 维度响应几乎为 0（0.5→0.8 只动 0.009）。
本实验用带使用指令的格式（=生产将补的形态），验证活泼维度本身是否有效：
    - 有效 → 之前失效是无指令的连带效应
    - 无效 → 活泼锚点描述或观测函数本身有问题

设计（最小成本）：
    2 组 × 8 输入 × 3 采样 = 48 次调用
    PL_low : playfulness=0.1，其余 0.5
    PL_high: playfulness=0.9，其余 0.5
    唯一变量 = playfulness；格式 = 数值+锚点+使用指令（sec_with_inst）

观测：
    1. 四维风格观测（重点 playfulness）+ Mann-Whitney U + Cohen's d
    2. 活泼关键词频次（哈哈/开心/有趣/轻松/欢乐/笑...）
    3. 同输入回复抽样对比（人工可读证据）

用法：
    & nodes/node_python_aaa_cognition/venv/Scripts/python.exe tests/_tmp_persona_playfulness.py
"""
import os
import sys
import json
import math
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

_WORKERS = int(os.environ.get("EXP_PARALLEL", "4"))
_sample_lock = threading.Lock()

os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)
ROOT = os.path.dirname(TESTS_DIR)
NODE_DIR = os.path.join(ROOT, "nodes", "node_python_aaa_cognition")
if NODE_DIR not in sys.path:
    sys.path.insert(0, NODE_DIR)

_RAW_ARGV = sys.argv[:]
sys.argv = [sys.argv[0]]

import self_evolution_test as evo
import personality as prs
import prompt as pmt
import parser as psr
from cognitive_evolution_test import POOL_NEUTRAL

sys.argv = _RAW_ARGV

_INSTRUCTION = (
    "**重要**：以上性格数值是你当前的性格状态，请据此在回复中自然地体现"
    "相应的性格特征——数值越高的维度表现越明显，数值越低则越收敛；"
    "请主动用言行呈现这些特质，不要提及数值本身。"
)

# --noinst：去掉激活指令（测「无指令下活泼高低是否有差异」）
_NOINST = "--noinst" in _RAW_ARGV
# --noanchor：去掉行为锚点，只留数值+定义行（测「纯数值能否驱动」）
_NOANCHOR = "--noanchor" in _RAW_ARGV


def sec(vector, style_description=""):
    if _NOANCHOR:
        dims = []
        for dim, label in prs._PERSONALITY_LABELS:
            v = vector.get(dim, prs._PERSONALITY_MID[dim])
            dims.append(f"{label}: {v:.1f}")
        base = (
            "### 你的性格（会随使用自然演化，不需主动提及）\n"
            "各维度均为 0-1 范围，当前值如下（0=完全不是，1=极致，0.5=中等）：\n"
            " | ".join(dims)
        )
        if style_description:
            base += f"\n说话风格: {style_description}"
        return base  # 纯数值条件：无锚点、无指令
    base = prs.build_personality_section(vector, style_description)
    return base if _NOINST else base + "\n" + _INSTRUCTION


_V_BASE = {"warmth": 0.5, "playfulness": 0.5, "directness": 0.5, "curiosity": 0.5}
GROUPS = {
    "PL_low":  {"vector": dict(_V_BASE, playfulness=0.1), "label": "活泼0.1",
                "sec": sec},
    "PL_high": {"vector": dict(_V_BASE, playfulness=0.9), "label": "活泼0.9",
                "sec": sec},
}
DIMS = ("warmth", "playfulness", "directness", "curiosity")
PLAYFUL_KEYWORDS = ["哈哈", "开心", "高兴", "好玩", "有趣", "轻松", "欢乐", "嘻嘻", "耶", "妙啊"]

OUT_DIR = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test",
                       "runs", time.strftime("%Y%m%d_%H%M%S")
                       + ("_noanchor" if _NOANCHOR else ("_noinst" if _NOINST else ""))
                       + "_playfulness")
os.makedirs(OUT_DIR, exist_ok=True)
SAMPLES_PATH = os.path.join(OUT_DIR, "probe_samples.jsonl")


def build_ctx(vector, text):
    return {
        "identity_key": "probe",
        "fixed_cognition": "", "self_cognition": "", "other_cognition": "",
        "recent_feelings": "", "mood_trend": "", "perception": "",
        "location_section": "", "attachment_context": "", "reflection_section": "",
        "history_summary": "", "user_info": "", "self_info": "",
        "user_text": text,
        "user_text_section": f"### 用户输入\n{text}",
        "current_date": "2026-08-12", "current_time": "12:00:00",
        "personality": sec(vector, ""),
        "mood": prs.build_mood_section(0.0),
        "pool_batch_section": "", "db_path": "", "user_id": "probe",
    }


def _run_item(gid, gdef, i, text, repeats):
    for rep in range(repeats):
        ctx = build_ctx(gdef["vector"], text)
        raw = evo.llm_infer(pmt.build_direct(ctx))
        if psr.is_truncated(raw or ""):
            raw = evo.llm_infer(pmt.build_direct(ctx) + "\n\n（注意：上次输出被截断，请完整输出全部小节。）")
        parsed = psr.parse_llm_output(raw)
        obs = prs.estimate_style_from_reply(parsed)
        with _sample_lock:
            with open(SAMPLES_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps({"group": gid, "input": i, "text": text,
                                    "rep": rep, "raw": raw, "style": obs},
                                   ensure_ascii=False) + "\n")


def load(gid):
    rows = []
    with open(SAMPLES_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                s = json.loads(line)
                if s["group"] == gid:
                    rows.append(s)
    return rows


def _ranks(values):
    order = sorted(range(len(values)), key=lambda k: values[k])
    ranks = [0.0] * len(values)
    i, n, tied = 0, len(values), False
    while i < n:
        j = i
        while j < n and values[order[j]] == values[order[i]]:
            j += 1
        if j - i > 1:
            tied = True
        for k in range(i, j):
            ranks[order[k]] = (i + 1 + j) / 2.0
        i = j
    return ranks, tied


def mann_whitney_u(a, b):
    na, nb = len(a), len(b)
    ranks, tied = _ranks(list(a) + list(b))
    ua = sum(ranks[:na]) - na * (na + 1) / 2.0
    mu = na * nb / 2.0
    if tied:
        vals = sorted(list(a) + list(b))
        freqs = {}
        i, n = 0, len(vals)
        while i < n:
            j = i
            while j < n and vals[j] == vals[i]:
                j += 1
            if j - i > 1:
                freqs[j - i] = freqs.get(j - i, 0) + 1
            i = j
        tie_corr = sum(k * (k - 1) * (k + 1) for k in freqs) / 2.0
        sigma2 = na * nb / 12.0 * ((na + nb + 1) - tie_corr / ((na + nb) * (na + nb - 1)))
    else:
        sigma2 = na * nb * (na + nb + 1) / 12.0
    sigma = math.sqrt(max(sigma2, 1e-9))
    z = abs(ua - mu) / sigma
    p = 2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2))))
    return min(p, 1.0)


def cohen_d(a, b):
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0
    ma, mb = sum(a) / na, sum(b) / nb
    va = sum((x - ma) ** 2 for x in a) / (na - 1)
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
    sp = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    return (mb - ma) / sp if sp else 0.0


def main():
    repeats, n_inputs = 3, 8
    inputs = POOL_NEUTRAL[:n_inputs]
    if _NOANCHOR:
        fmt = "纯数值（无锚点、无指令）"
    elif _NOINST:
        fmt = "无激活指令"
    else:
        fmt = "带激活指令"
    print(f"═══ 活泼维度定向验证（playfulness 0.1 vs 0.9，{fmt}）═══", flush=True)
    print(f"  {n_inputs} 输入 × {repeats} 采样 × 2 组 = {n_inputs * repeats * 2} 次调用", flush=True)
    t0 = time.time()
    tasks = [(gid, gdef, i, text) for gid, gdef in GROUPS.items()
             for i, text in enumerate(inputs)]
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        futs = [ex.submit(_run_item, gid, gdef, i, text, repeats) for gid, gdef, i, text in tasks]
        for i, fut in enumerate(as_completed(futs)):
            fut.result()
            print(f"  进度 {i + 1}/{len(futs)}", flush=True)

    rows = {gid: load(gid) for gid in GROUPS}
    print(f"\n[风格观测]（{time.time() - t0:.0f}s 完成）", flush=True)
    for gid, gd in GROUPS.items():
        s = rows[gid]
        vals = {d: [r["style"].get(d, 0.5) for r in s] for d in DIMS}
        txt = "  ".join(f"{d}={sum(v) / len(v):.3f}" for d, v in vals.items())
        print(f"  [{gd['label']}] n={len(s)}  {txt}", flush=True)

    print("\n[对比 活泼0.9 vs 活泼0.1]", flush=True)
    lo, hi = rows["PL_low"], rows["PL_high"]
    for d in DIMS:
        a = [r["style"].get(d, 0.5) for r in lo]
        b = [r["style"].get(d, 0.5) for r in hi]
        print(f"  {d:12s} 低={sum(a) / len(a):.3f} 高={sum(b) / len(b):.3f} "
              f"Δ={sum(b) / len(b) - sum(a) / len(a):+.3f} "
              f"d={cohen_d(a, b):+.3f} p={mann_whitney_u(a, b):.4f}", flush=True)

    print("\n[活泼关键词频次]（哈哈/开心/有趣/轻松/欢乐... 每样本平均出现次数）", flush=True)
    for gid, gd in GROUPS.items():
        s = rows[gid]
        n_kw = sum(sum(1 for kw in PLAYFUL_KEYWORDS if kw in (r["raw"] or "")) for r in s)
        print(f"  [{gd['label']}] 均值={n_kw / len(s):.3f}/样本  (n={len(s)})", flush=True)

    print("\n[同输入抽样对比]（input 0）", flush=True)
    for gid, gd in GROUPS.items():
        s = [r for r in rows[gid] if r["input"] == 0]
        if s:
            body = (s[0]["raw"] or "")[:220].replace("\n", " ")
            print(f"  ── {gd['label']}: {body}...", flush=True)

    result = {"run_dir": OUT_DIR, "model": evo.MODEL, "temperature": evo.TEMPERATURE,
              "inputs": n_inputs, "repeats": repeats,
              "group_labels": {g: d["label"] for g, d in GROUPS.items()},
              "stats": {gid: {d: (sum(r["style"].get(d, 0.5) for r in rows[gid]) / len(rows[gid]))
                              for d in DIMS} for gid in GROUPS}}
    with open(os.path.join(OUT_DIR, "playfulness_results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"\n[完成] {OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
