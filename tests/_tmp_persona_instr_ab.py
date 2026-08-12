# -*- coding: utf-8 -*-
"""指令缺失假设验证：人格向量"使用指令"有无 → 输出差异（空白记忆受控对照）。

用户假设（2026-08-12）：expB 纯数值版几乎不影响输出的根因，可能不是
「模型看不懂数值」，而是「提示词里从未告诉模型这个向量怎么用」——
现有 personality 段只有定义（0-1 范围）+ 行为锚点，没有类似 mood 段的
使用指令（「请按此数值在回复中体现相应风格」）。

设计：两个空白记忆实例（build_ctx 全部记忆段置空 = 空库），同一套输入
（POOL_NEUTRAL），唯一变量 = personality 段是否追加使用指令行。

组（2 向量水平 × 2 指令水平）：
    A1 default·无指令   A2 default·有指令
    B1 性格·无指令      B2 性格·有指令
    _V_CHAR = warmth 0.9 / playfulness 0.8 / directness 0.2 / curiosity 0.7

分析：
    1. A1 vs A2、B1 vs B2：同向量下「指令有无」对四维风格观测的差异
    2. 方向符合度：B2 相对 B1 的 warmth（应↑）、directness（应↓）偏移方向
    3. 回复长度 + 同输入文本相似度：输出内容层面是否可区分

用法（AAA 节点 venv）：
    & nodes/node_python_aaa_cognition/venv/Scripts/python.exe tests/_tmp_persona_instr_ab.py
"""
import os
import sys
import json
import time
import math
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

# self_evolution_test import 时会把 sys.argv[1] 当轮数 → 先保存后恢复
_RAW_ARGV = sys.argv[:]
sys.argv = [sys.argv[0]]

import self_evolution_test as evo          # llm_infer / MODEL / TEMPERATURE
import personality as prs
import prompt as pmt
import parser as psr
from cognitive_evolution_test import POOL_NEUTRAL

sys.argv = _RAW_ARGV

# ── 两种人格段格式（唯一差异 = 使用指令行）───────────────────────────
_INSTRUCTION = (
    "**重要**：以上性格数值是你当前的性格状态，请据此在回复中自然地体现"
    "相应的性格特征——数值越高的维度表现越明显，数值越低则越收敛；"
    "请主动用言行呈现这些特质，不要提及数值本身。"
)


def sec_no_inst(vector, style_description=""):
    """无使用指令：生产 v2.1 现状格式（数值 + 定义 + 行为锚点）。"""
    return prs.build_personality_section(vector, style_description)


def sec_with_inst(vector, style_description=""):
    """有使用指令：同上 + 追加使用指令行（唯一差异）。"""
    return prs.build_personality_section(vector, style_description) + "\n" + _INSTRUCTION


_V_PLAIN = {"warmth": 0.5, "playfulness": 0.5, "directness": 0.5, "curiosity": 0.5}
_V_CHAR = {"warmth": 0.9, "playfulness": 0.8, "directness": 0.2, "curiosity": 0.7}

GROUPS = {
    "A1_plain_noinst": {"vector": _V_PLAIN, "sec": sec_no_inst,  "label": "default·无指令"},
    "A2_plain_inst":   {"vector": _V_PLAIN, "sec": sec_with_inst, "label": "default·有指令"},
    "B1_char_noinst":  {"vector": _V_CHAR,  "sec": sec_no_inst,  "label": "性格·无指令"},
    "B2_char_inst":    {"vector": _V_CHAR,  "sec": sec_with_inst, "label": "性格·有指令"},
}
DIMS = ("warmth", "playfulness", "directness", "curiosity")

OUT_DIR = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test",
                       "runs", time.strftime("%Y%m%d_%H%M%S") + "_instrAB")
os.makedirs(OUT_DIR, exist_ok=True)
SAMPLES_PATH = os.path.join(OUT_DIR, "probe_samples.jsonl")


def build_ctx(vector, text, sec_fn):
    """两个空白记忆实例：全部记忆段置空，唯一差异 = personality 段格式。"""
    return {
        "identity_key": "probe",
        "fixed_cognition": "", "self_cognition": "", "other_cognition": "",
        "recent_feelings": "", "mood_trend": "", "perception": "",
        "location_section": "", "attachment_context": "", "reflection_section": "",
        "history_summary": "", "user_info": "", "self_info": "",
        "user_text": text,
        "user_text_section": f"### 用户输入\n{text}",
        "current_date": "2026-08-12", "current_time": "12:00:00",
        "personality": sec_fn(vector, ""),
        "mood": prs.build_mood_section(0.0),   # 情绪固定 0.0，排除第二变量
        "pool_batch_section": "", "db_path": "", "user_id": "probe",
    }


def _done_keys():
    if not os.path.exists(SAMPLES_PATH):
        return set()
    keys = set()
    with open(SAMPLES_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                s = json.loads(line)
                keys.add((s["group"], s["input"]))
    return keys


def append_sample(sample):
    with _sample_lock:
        with open(SAMPLES_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")


def _run_item(gid, gdef, i, text, repeats):
    for rep in range(repeats):
        ctx = build_ctx(gdef["vector"], text, gdef["sec"])
        prompt_text = pmt.build_direct(ctx)
        raw = evo.llm_infer(prompt_text)
        if psr.is_truncated(raw or ""):
            raw = evo.llm_infer(prompt_text + "\n\n（注意：上次输出被截断，请完整输出全部小节。）")
        parsed = psr.parse_llm_output(raw)
        obs = prs.estimate_style_from_reply(parsed)
        append_sample({"group": gid, "input": i, "text": text, "rep": rep,
                       "raw": raw, "style": obs})


def run_all_parallel(groups, inputs, repeats, done):
    tasks = [(gid, gdef, i, text)
             for gid, gdef in groups.items()
             for i, text in enumerate(inputs)
             if (gid, i) not in done]
    n_skip = len(inputs) * len(groups) - len(tasks)
    n_done = n_skip
    total = len(tasks)
    print(f"  全并行：待跑 {total} 条 × {repeats} 采样（{_WORKERS} 线程，跳过 {n_skip}）", flush=True)
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        futs = {ex.submit(_run_item, gid, gdef, i, text, repeats): (gid, i)
                for gid, gdef, i, text in tasks}
        for fut in as_completed(futs):
            fut.result()
            n_done += 1
            gid, _ = futs[fut]
            done.add(futs[fut])
            print(f"  [{gid}] 完成 {n_done}/{len(tasks) + n_skip} 条输入", flush=True)


# ── 统计（Mann-Whitney U 含并列秩 + Cohen's d）───────────────────────
def _ranks(values):
    order = sorted(range(len(values)), key=lambda k: values[k])
    ranks = [0.0] * len(values)
    i, n = 0, len(values)
    tied = False
    while i < n:
        j = i
        while j < n and values[order[j]] == values[order[i]]:
            j += 1
        r = (i + 1 + j) / 2.0
        if j - i > 1:
            tied = True
        for k in range(i, j):
            ranks[order[k]] = r
        i = j
    return ranks, tied


def mann_whitney_u(a, b):
    combined = list(a) + list(b)
    na, nb = len(a), len(b)
    ranks, tied = _ranks(combined)
    ua = sum(ranks[:na]) - na * (na + 1) / 2.0
    mu = na * nb / 2.0
    if tied:
        freqs = {}
        vals = sorted(combined)
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


def load_samples(gid):
    rows = []
    with open(SAMPLES_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                s = json.loads(line)
                if s["group"] == gid:
                    rows.append(s)
    return rows


def group_stats(gid):
    rows = load_samples(gid)
    if not rows:
        return None
    out = {}
    for dim in DIMS:
        vals = [s["style"].get(dim, 0.5) for s in rows]
        m = sum(vals) / len(vals)
        sd = (sum((x - m) ** 2 for x in vals) / (len(vals) - 1)) ** 0.5 if len(vals) > 1 else 0.0
        out[dim] = (m, sd)
    lens = [len(s["raw"] or "") for s in rows]
    return {"n": len(rows), "style": out,
            "len_mean": sum(lens) / len(lens), "samples": rows}


def compare(ga, gb):
    """ga 无指令 vs gb 有指令，每维 Δ（b-a）/d/p。"""
    rows = []
    for dim in DIMS:
        va = [s["style"].get(dim, 0.5) for s in ga["samples"]]
        vb = [s["style"].get(dim, 0.5) for s in gb["samples"]]
        rows.append({"dim": dim,
                     "mean_a": sum(va) / len(va), "mean_b": sum(vb) / len(vb),
                     "delta": (sum(vb) / len(vb)) - (sum(va) / len(va)),
                     "cohen_d": cohen_d(va, vb), "p": mann_whitney_u(va, vb)})
    return rows


def text_overlap(gid_noinst, gid_inst):
    """同输入同采样下，无指令 vs 有指令回复的字符级 Jaccard（内容差异量化）。"""
    a = load_samples(gid_noinst)
    b = load_samples(gid_inst)
    key_a = {(s["input"], s["rep"]): s for s in a}
    key_b = {(s["input"], s["rep"]): s for s in b}
    sims = []
    for k in set(key_a) & set(key_b):
        ta, tb = (key_a[k]["raw"] or ""), (key_b[k]["raw"] or "")
        sa, sb = set(ta), set(tb)
        if not sa and not sb:
            continue
        inter = len(sa & sb)
        union = len(sa | sb)
        sims.append(inter / union if union else 1.0)
    return sum(sims) / len(sims) if sims else None


def main():
    repeats = 5
    n_inputs = 20
    if "--repeats" in _RAW_ARGV:
        repeats = int(_RAW_ARGV[_RAW_ARGV.index("--repeats") + 1])
    if "--inputs" in _RAW_ARGV:
        n_inputs = int(_RAW_ARGV[_RAW_ARGV.index("--inputs") + 1])
    inputs = POOL_NEUTRAL[:n_inputs]
    print(f"═══ 指令缺失验证：人格向量使用指令有无 → 输出差异 ═══", flush=True)
    print(f"  模型={evo.MODEL} temp={evo.TEMPERATURE}  输入={n_inputs} × 采样={repeats} "
          f"× 组={len(GROUPS)} → 约 {n_inputs * repeats * len(GROUPS)} 次调用", flush=True)
    print(f"  空白记忆：全部记忆段置空；唯一变量 = personality 段是否含使用指令行", flush=True)

    done = _done_keys()
    run_all_parallel(GROUPS, inputs, repeats, done)

    # 组统计 + 对比
    st = {gid: group_stats(gid) for gid in GROUPS}
    print("\n[组统计] 四维风格 mean±std + 回复长度", flush=True)
    for gid, gd in GROUPS.items():
        s = st[gid]
        if not s:
            print(f"  {gid} 无样本", flush=True)
            continue
        dims_txt = "  ".join(f"{d}={s['style'][d][0]:.3f}±{s['style'][d][1]:.3f}" for d in DIMS)
        print(f"  [{gid:16s}] {gd['label']:12s} n={s['n']}  {dims_txt}", flush=True)

    print("\n[对比] 无指令 vs 有指令（同向量）：", flush=True)
    cmp_rows = {}
    for pair_name, (g_a, g_b) in {"A(default)": ("A1_plain_noinst", "A2_plain_inst"),
                                  "B(性格)": ("B1_char_noinst", "B2_char_inst")}.items():
        print(f"  ── {pair_name}：{g_a} vs {g_b}", flush=True)
        rows = compare(st[g_a], st[g_b])
        cmp_rows[pair_name] = rows
        for r in rows:
            sig = "✓" if r["p"] < 0.05 else " "
            print(f"  {sig} {r['dim']:12s} 无指令={r['mean_a']:.3f} 有指令={r['mean_b']:.3f} "
                  f"Δ={r['delta']:+.3f} d={r['cohen_d']:+.3f} p={r['p']:.4f}", flush=True)

    # 方向符合度（性格向量 B2 vs B1：warmth 应↑、playfulness 应↑、directness 应↓、curiosity 应↑）
    print("\n[方向符合度] B（性格向量 0.9/0.8/0.2/0.7）有指令 vs 无指令：", flush=True)
    expect = {"warmth": 1, "playfulness": 1, "directness": -1, "curiosity": 1}
    dir_ok = {}
    b_rows = cmp_rows["B(性格)"]
    for r in b_rows:
        exp = expect[r["dim"]]
        ok = (r["delta"] > 0) == (exp > 0) if r["delta"] != 0 else None
        dir_ok[r["dim"]] = ok
        print(f"  {r['dim']:12s} 期望{'↑' if exp > 0 else '↓'} 实际Δ={r['delta']:+.3f} "
              f"符合={ok}", flush=True)
    n_ok = sum(1 for v in dir_ok.values() if v is True)
    n_sig = sum(1 for r in b_rows if r["p"] < 0.05)

    # 回复长度差异
    print("\n[回复长度]（字符）：", flush=True)
    for pair_name, (g_a, g_b) in {"A(default)": ("A1_plain_noinst", "A2_plain_inst"),
                                  "B(性格)": ("B1_char_noinst", "B2_char_inst")}.items():
        la, lb = st[g_a]["len_mean"], st[g_b]["len_mean"]
        print(f"  {pair_name}: 无指令={la:.1f}  有指令={lb:.1f}  (Δ={lb - la:+.1f})", flush=True)

    # 同输入文本相似度
    sim_a = text_overlap("A1_plain_noinst", "A2_plain_inst")
    sim_b = text_overlap("B1_char_noinst", "B2_char_inst")
    print("\n[同输入回复相似度]（字符级 Jaccard，1=完全相同）：", flush=True)
    print(f"  A(default): {sim_a:.3f}   B(性格): {sim_b:.3f}", flush=True)

    verdict = (
        f"B 组(性格向量)方向符合 {n_ok}/4 维，显著维度 {n_sig}/4；"
        + ("若 warmth/directness 符合预期方向且有显著差异 → 指令缺失是数值效力弱的重要根因"
           if n_ok >= 2 else "若方向符合但效应弱 → 指令有效但不足以替代描述；"
                              "若无差异 → 指令缺失假设未获支持")
    )
    print(f"\n[判定] {verdict}", flush=True)

    result = {"run_dir": OUT_DIR, "model": evo.MODEL, "temperature": evo.TEMPERATURE,
              "inputs": n_inputs, "repeats": repeats,
              "groups": {g: gd["label"] for g, gd in GROUPS.items()},
              "instruction": _INSTRUCTION,
              "stats": {gid: {d: s["style"][d] for d in DIMS} | {"len_mean": s["len_mean"]}
                        for gid, s in st.items() if s},
              "compare": cmp_rows, "direction": dir_ok,
              "text_sim": {"A": sim_a, "B": sim_b},
              "verdict": verdict}
    with open(os.path.join(OUT_DIR, "instrAB_results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"\n[完成] {OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
