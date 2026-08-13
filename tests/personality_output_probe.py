# -*- coding: utf-8 -*-
"""实验 B：人格漂移 → prompt → 输出 因果验证（方案见 docs/cogevo/[EXP]-人格漂移输出影响验证实验方案.md）

三组对照（唯一变量 = 注入的人格向量）：
    A 基线     : agent:0 种子向量  [0.41, 0.52, 0.14, 0.10]
    B 漂移后   : agent:0 最终向量  [0.43, 0.52, 0.23, 0.20]（exp_5a60r_ai_self 真实漂移）
    C 阳性对照 : warmth 0.1 vs 0.9（方法敏感性验证，必须显著）

输出层观测：parse_llm_output → estimate_style_from_reply（生产同款观测函数，口径一致）。
判定：显示层 diff（.1f 跨格）+ 输出层分布（Mann-Whitney U + Cohen's d）+ 同向性。

用法（项目根目录，AAA 节点 venv）：
    & nodes/node_python_aaa_cognition/venv/Scripts/python.exe tests/personality_output_probe.py [--repeats 5] [--inputs 20]
"""
import os
import sys
import json
import time
import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# v3 并行：LLM 调用是 IO 密集，默认 4 线程并发（可用 EXP_PARALLEL 覆盖）。
# 800 次调用串行 ~80 分钟 → 4 并发 ~20 分钟。
_WORKERS = int(os.environ.get("EXP_PARALLEL", "4"))
_sample_lock = threading.Lock()

# 演化长跑防 OpenBLAS 内存分配失败（必须在 import numpy/memos 之前设置）
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

# v1.9 实验变量：百分比表达验证（EXP_PERCENT=1）——「90% 直接度」+ 连续程度
# 语义说明（百分比越高程度越高），是否可替代行为锚点。只影响本次 run。
if os.environ.get("EXP_PERCENT"):
    def _percent_section(vector: dict, style_description: str = "") -> str:
        if not vector:
            return ""
        labels = [("warmth", "温暖度"), ("playfulness", "活泼度"),
                  ("directness", "直接度"), ("curiosity", "好奇心")]
        mids = {"warmth": 0.6, "playfulness": 0.4, "directness": 0.5, "curiosity": 0.5}
        row = " | ".join(
            f"{lb}: {vector.get(dim, mids[dim]) * 100:.0f}%" for dim, lb in labels)
        parts = [
            "### 你的性格（会随使用自然演化，不需主动提及）",
            "各维度为 0-100% 的连续程度标尺：百分比越高代表该特质程度越高，"
            "越低代表程度越低，50% 为中等程度。当前值：",
            row,
        ]
        if style_description:
            parts.append(f"说话风格: {style_description}")
        return "\n".join(parts)
    prs.build_personality_section = _percent_section
    print("[实验B] 人格段格式 = 百分比 + 连续程度说明（EXP_PERCENT=1）", flush=True)

# v2.1 实验变量：五档动作级描述（EXP_ACT5=1）——描述差异最大化。
# 插值版相邻档只差程度词（非常 vs 相当），0.14 vs 0.23 描述差异仍不够大；
# 改为五档每档一段独立动作级描述（不只程度词，行为模式也随档变化），
# 验证真实漂移能否被 LLM 感知。只影响本次 run，不动生产 build_personality_section。
if os.environ.get("EXP_ACT5"):
    _ACT5_ANCHORS = {
        "warmth": [
            "冷淡疏离、保持距离、公事公办，极少寒暄",
            "话少、礼貌客气，偶尔关心对方近况",
            "自然平和、不过分热络也不冷淡",
            "比较热情、会主动关心对方近况",
            "热情主动、语气温暖、主动关心并表达支持",
        ],
        "playfulness": [
            "一本正经、严肃认真，从不开玩笑",
            "正经为主，偶尔带一点轻松",
            "轻松自然、偶尔玩笑",
            "比较爱开玩笑、语气轻松活泼",
            "爱开玩笑、语气活泼有趣，常逗趣",
        ],
        "directness": [
            "委婉含蓄、说话绕圈子，先寒暄铺垫再引入正题，几乎不直接说重点，常用「可能、也许」",
            "比较委婉、说话留有余地，会先铺垫但能点到正题，偶尔直接表态",
            "有话直说但注意分寸，简洁明确，适当客套",
            "比较直接、简洁明确，少客套，直接进入正题",
            "直截了当、不拐弯抹角、开门见山，不铺垫直接说",
        ],
        "curiosity": [
            "关注当下、很少追问，对新鲜事物不主动了解",
            "较少追问，偶尔对感兴趣的事问一两句",
            "适度关注，会追问细节但不刨根问底",
            "比较好奇、会主动追问细节",
            "强烈好奇、主动追问、爱探索，常问为什么",
        ],
    }

    def _act5_anchor(dim: str, v: float) -> str:
        band = _ACT5_ANCHORS.get(dim)
        if not band:
            return ""
        if v <= 0.2:
            return f"（{band[0]}）"
        if v <= 0.4:
            return f"（{band[1]}）"
        if v <= 0.6:
            return f"（{band[2]}）"
        if v <= 0.8:
            return f"（{band[3]}）"
        return f"（{band[4]}）"

    def _act5_section(vector: dict, style_description: str = "") -> str:
        if not vector:
            return ""
        labels = [("warmth", "温暖度"), ("playfulness", "活泼度"),
                  ("directness", "直接度"), ("curiosity", "好奇心")]
        mids = {"warmth": 0.6, "playfulness": 0.4, "directness": 0.5, "curiosity": 0.5}
        row = " | ".join(
            f"{lb}: {vector.get(dim, mids[dim]):.1f}"
            f"{_act5_anchor(dim, vector.get(dim, mids[dim]))}" for dim, lb in labels)
        parts = [
            "### 你的性格（会随使用自然演化，不需主动提及）",
            "各维度均为 0-1 范围，当前值如下（0=完全不是，1=极致，0.5=中等）：",
            row,
        ]
        if style_description:
            parts.append(f"说话风格: {style_description}")
        return "\n".join(parts)

    prs.build_personality_section = _act5_section
    prs._personality_anchor = _act5_anchor
    print("[实验B] 人格段格式 = 五档动作级描述（EXP_ACT5=1，描述差异最大化）", flush=True)

sys.argv = _RAW_ARGV

OUT_DIR = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test",
                       "runs", time.strftime("%Y%m%d_%H%M%S") + "_expB")
os.makedirs(OUT_DIR, exist_ok=True)
SAMPLES_PATH = os.path.join(OUT_DIR, "probe_samples.jsonl")

# ── 三组向量（exp_5a60r_ai_self 的 agent:0 真实漂移 + 极值对照） ──
_DEFAULT_V = {"warmth": 0.5, "playfulness": 0.5,
              "directness": 0.5, "curiosity": 0.5}
_SEED_0 = {"warmth": 0.41, "playfulness": 0.52,
           "directness": 0.14, "curiosity": 0.10}
_FINAL_0 = {"warmth": 0.4339, "playfulness": 0.5225,
            "directness": 0.2342, "curiosity": 0.20}

GROUPS = {
    "A_seed": {"vector": _SEED_0, "label": "基线(agent:0 种子)"},
    "B_drift": {"vector": _FINAL_0, "label": "漂移后(agent:0 final)"},
    "C_low": {"vector": dict(_DEFAULT_V, warmth=0.1), "label": "极值 warmth=0.1"},
    "C_high": {"vector": dict(_DEFAULT_V, warmth=0.9), "label": "极值 warmth=0.9"},
    "D_low": {"vector": dict(_DEFAULT_V, directness=0.1), "label": "极值 directness=0.1"},
    "D_high": {"vector": dict(_DEFAULT_V, directness=0.9), "label": "极值 directness=0.9"},
    "E_low": {"vector": dict(_DEFAULT_V, curiosity=0.1), "label": "极值 curiosity=0.1"},
    "E_high": {"vector": dict(_DEFAULT_V, curiosity=0.9), "label": "极值 curiosity=0.9"},
}

# v3 维度敏感性：每个维度一组极值对照（0.1 vs 0.9），验证 LLM 是否响应该维度
# （20260808 真实漂移 A/B 功效不足的归因问题：若极值显著 → 维度可观测，只是
#  漂移幅度小；若极值不显著 → 该维度注入/观测本身无效，需修 prompt 措辞）
EXTREME_PAIRS = [
    ("warmth", "C_low", "C_high"),
    ("directness", "D_low", "D_high"),
    ("curiosity", "E_low", "E_high"),
]

DIMS = ("warmth", "playfulness", "directness", "curiosity")


# ── 上下文构造：唯一差异是 personality 段 ────────────────────────
def build_ctx(vector, text):
    # 注意：prompt._prepare_ctx 会无条件用 ctx['user_text'] 覆盖 user_text_section，
    # 必须同时传 user_text，否则用户输入在 prompt 中丢失（P1 修复）
    return {
        "identity_key": "probe",
        "fixed_cognition": "", "self_cognition": "", "other_cognition": "",
        "recent_feelings": "", "mood_trend": "", "perception": "",
        "location_section": "", "attachment_context": "", "reflection_section": "",
        "history_summary": "", "user_info": "", "self_info": "",
        "user_text": text,
        "user_text_section": f"### 用户输入\n{text}",
        "current_date": "2026-08-08", "current_time": "12:00:00",
        "personality": prs.build_personality_section(vector, ""),
        "mood": prs.build_mood_section(0.0),   # 情绪固定 0.0，排除第二变量
        "pool_batch_section": "", "db_path": "", "user_id": "probe",
    }


# ── 断点续跑：按 (group, input_idx) 跳过已完成样本 ───────────────
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
    # v3 并发写保护：多线程同时 append 会交错整行 json
    with _sample_lock:
        with open(SAMPLES_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")


def run_group(gid, gdef, inputs, repeats, done):
    """并行运行组内全部输入（v3）：线程池并发调 LLM，进度按完成数打印。"""
    pending = [(i, text) for i, text in enumerate(inputs) if (gid, i) not in done]
    n_done = len(inputs) - len(pending)
    print(f"  [{gid}] 待跑 {len(pending)} 条（{_WORKERS} 线程并发）", flush=True)
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        futs = {ex.submit(_run_item, gid, gdef, i, text, repeats): i for i, text in pending}
        for fut in as_completed(futs):
            fut.result()  # 抛出异常及时暴露
            n_done += 1
            print(f"  [{gid}] 完成 {n_done}/{len(inputs)} 条输入", flush=True)


def _run_item(gid, gdef, i, text, repeats):
    """单条输入的全部采样（组间+组内全并行 v4：从 run_group._work 提取为顶层）。"""
    for rep in range(repeats):
        ctx = build_ctx(gdef["vector"], text)
        prompt_text = pmt.build_direct(ctx)
        raw = evo.llm_infer(prompt_text)
        # v6.5 截断防御：未闭合节标记 → 重试一次（防半句回复污染观测）
        if psr.is_truncated(raw or ""):
            raw = evo.llm_infer(prompt_text + "\n\n（注意：上次输出被截断，请完整输出全部小节。）")
        parsed = psr.parse_llm_output(raw)
        obs = prs.estimate_style_from_reply(parsed)
        append_sample({"group": gid, "input": i, "text": text, "rep": rep,
                       "raw": raw, "style": obs})


def run_all_parallel(groups, inputs, repeats, done):
    """v4 组间+组内全并行：所有 (gid, input) 任务统一提交一个线程池。"""
    tasks = [(gid, gdef, i, text)
             for gid, gdef in groups.items()
             for i, text in enumerate(inputs)
             if (gid, i) not in done]
    n_skip = len(inputs) * len(groups) - len(tasks)
    n_done = n_skip
    total = len(tasks)
    print(f"  全并行：待跑 {total} 条输入 × {repeats} 采样（{_WORKERS} 线程，"
          f"组间+组内同时跑，跳过 {n_skip}）", flush=True)
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        futs = {ex.submit(_run_item, gid, gdef, i, text, repeats): (gid, i)
                for gid, gdef, i, text in tasks}
        for fut in as_completed(futs):
            fut.result()  # 抛出异常及时暴露
            n_done += 1
            gid, _ = futs[fut]
            done.add(futs[fut])
            print(f"  [{gid}] 完成 {n_done}/{len(tasks) + n_skip} 条输入", flush=True)


# ── 统计：Mann-Whitney U（手写，含并列秩）+ Cohen's d ────────────
def _ranks(values):
    """并列均值秩。返回 (秩列表, 是否含并列)。"""
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
    """双尾正态近似 U 检验，返回 (p_value, 是否并列修正)。"""
    combined = list(a) + list(b)
    na, nb = len(a), len(b)
    ranks, tied = _ranks(combined)
    ua = sum(ranks[:na]) - na * (na + 1) / 2.0
    mu = na * nb / 2.0
    if tied:
        # 并列秩修正方差
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
    # 双尾 p（标准正态近似）
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
    return (ma - mb) / sp if sp else 0.0


def load_samples(gid):
    rows = []
    with open(SAMPLES_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                s = json.loads(line)
                if s["group"] == gid:
                    rows.append(s)
    return rows


# ── 报告 ────────────────────────────────────────────────────────
def show_layer_diff():
    """显示层：种子 vs 漂移后向量的 build_personality_section 文本 diff。"""
    sa = prs.build_personality_section(_SEED_0, "")
    sb = prs.build_personality_section(_FINAL_0, "")
    changed = []
    for dim in DIMS:
        va, vb = _SEED_0[dim], _FINAL_0[dim]
        if round(va, 1) != round(vb, 1):
            changed.append(f"{dim}: {va:.3f}→{vb:.3f}（显示 {va:.1f}→{vb:.1f}）")
    return changed, sa, sb


def stats_rows(gid_a, gid_b):
    """输出层：组间每维 U 检验 + Cohen's d + 均值。任一组无样本返回 []。"""
    a = load_samples(gid_a)
    b = load_samples(gid_b)
    if not a or not b:
        return []
    rows = []
    for dim in DIMS:
        va = [s["style"].get(dim, 0.5) for s in a]
        vb = [s["style"].get(dim, 0.5) for s in b]
        p = mann_whitney_u(va, vb)
        d = cohen_d(vb, va)
        ma = sum(va) / len(va)
        mb = sum(vb) / len(vb)
        rows.append({"dim": dim, "n_a": len(va), "n_b": len(vb),
                     "mean_a": round(ma, 4), "mean_b": round(mb, 4),
                     "delta": round(mb - ma, 4), "cohen_d": round(d, 4),
                     "p": round(p, 4)})
    return rows


def main():
    ap_r = "--repeats" in _RAW_ARGV
    repeats = int(_RAW_ARGV[_RAW_ARGV.index("--repeats") + 1]) if ap_r else 5
    n_inputs = 20
    if "--inputs" in _RAW_ARGV:
        n_inputs = int(_RAW_ARGV[_RAW_ARGV.index("--inputs") + 1])
    inputs = POOL_NEUTRAL[:n_inputs]
    global GROUPS
    if "--groups" in _RAW_ARGV:
        only = [g.strip() for g in _RAW_ARGV[_RAW_ARGV.index("--groups") + 1].split(",")]
        GROUPS = {k: v for k, v in GROUPS.items() if k in only}
        print(f"[实验B] 仅跑组: {list(GROUPS)}（A/B 用历史数据，避免重复成本）", flush=True)
    print(f"[实验B] run_dir={OUT_DIR}  组={list(GROUPS)}  输入={n_inputs}  "
          f"采样={repeats}/条  → 约 {len(GROUPS) * n_inputs * repeats} 次 LLM 调用",
          flush=True)
    print(f"[实验B] 模型={evo.MODEL}  temperature={evo.TEMPERATURE}", flush=True)

    done = _done_keys()
    run_all_parallel(GROUPS, inputs, repeats, done)

    # ── 显示层 diff ──
    changed, sa, sb = show_layer_diff()
    print("\n[显示层] 种子 vs 漂移后 build_personality_section：", flush=True)
    print("  A:", sa.replace("\n", " | "), flush=True)
    print("  B:", sb.replace("\n", " | "), flush=True)
    print("  跨 .1f 显示阈值的维度：", changed or "无", flush=True)

    # ── 输出层统计 ──
    print("\n[输出层] A(种子) vs B(漂移后)：", flush=True)
    rows_ab = stats_rows("A_seed", "B_drift")
    if not rows_ab:
        print("  （A/B 无样本——本次仅跑极值组，A/B 用历史 run 数据）", flush=True)
    for r in rows_ab:
        sig = "✓" if r["p"] < 0.05 else " "
        print(f"  {sig} {r['dim']:12s} A={r['mean_a']:.3f} B={r['mean_b']:.3f} "
              f"Δ={r['delta']:+.3f} d={r['cohen_d']:+.3f} p={r['p']:.4f}", flush=True)

    # v3 维度敏感性：各维度极值对照（0.1 vs 0.9）
    rows_ext = {}
    for dim, lo, hi in EXTREME_PAIRS:
        print(f"[输出层] 极值对照 {dim}（{lo} vs {hi}）：", flush=True)
        rows_ext[dim] = stats_rows(lo, hi)
        for r in rows_ext[dim]:
            sig = "✓" if r["p"] < 0.05 else " "
            print(f"  {sig} {r['dim']:12s} lo={r['mean_a']:.3f} hi={r['mean_b']:.3f} "
                  f"Δ={r['delta']:+.3f} d={r['cohen_d']:+.3f} p={r['p']:.4f}", flush=True)

    # ── 同向性（B 相对 A 的漂移方向 vs 向量漂移方向） ──
    direction = {}
    if rows_ab:
        for dim in DIMS:
            delta_vec = _FINAL_0[dim] - _SEED_0[dim]
            row = next(r for r in rows_ab if r["dim"] == dim)
            delta_out = row["delta"]
            direction[dim] = {"vector_delta": round(delta_vec, 4),
                              "output_delta": delta_out,
                              "same_direction": (delta_vec > 0) == (delta_out > 0) if delta_out else None}
        print("[同向性] 向量漂移方向 vs 输出风格偏移方向：", flush=True)
        for dim, v in direction.items():
            print(f"  {dim:12s} 向量Δ={v['vector_delta']:+.3f}  输出Δ={v['output_delta']:+.3f}  "
                  f"同向={v['same_direction']}", flush=True)

    result = {"run_dir": OUT_DIR, "model": evo.MODEL, "temperature": evo.TEMPERATURE,
              "inputs": n_inputs, "repeats": repeats,
              "groups": {g: gd["label"] for g, gd in GROUPS.items()},
              "vectors": {"A_seed": _SEED_0, "B_drift": _FINAL_0},
              "display_layer": {"changed_dims": changed, "A_text": sa, "B_text": sb},
              "output_layer": {"A_vs_B": rows_ab, "extreme": rows_ext},
              "direction": direction,
              "verdict": _verdict(rows_ab, rows_ext, changed, direction)}
    with open(os.path.join(OUT_DIR, "probe_results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    _write_report(result)
    print(f"\n[完成] {OUT_DIR}", flush=True)


def _verdict(rows_ab, rows_ext, changed, direction):
    """分层判定（v3，20260808 维度敏感性）：行为意义的证据必须是「显著且同向」。

    v2 修复原逻辑缺陷：A/B 中 directness 显著但**反向**、playfulness 同向但不显著，
    原 `if ab_sig:` 把两者拼成『显著且同向』结论。v3 另将方法敏感性扩展为
    三维度极值对照（warmth/directness/curiosity 0.1 vs 0.9），回答「该维度
    LLM 到底响应不响应」——极值显著 → 维度可观测，真实漂移只是幅度小；
    极值不显著 → 维度注入/观测无效，需修 prompt 措辞。
    """
    c_rows = rows_ext.get("warmth", [])
    c_sig = any(r["p"] < 0.05 for r in c_rows)
    # 维度敏感性：哪些维度极值显著（模型能响应）
    dim_sig = [dim for dim, rows in rows_ext.items()
               if any(r["p"] < 0.05 and r["delta"] != 0 for r in rows)]
    dim_sig_note = (f"维度敏感性：极值对照显著维度 = {dim_sig}（"
                    f"{'均可观测，真实漂移仅幅度不足' if len(dim_sig) == 3 else '未显著维度需修 prompt 措辞或观测'}）")
    # 仅极值 run（--groups 跳过 A/B）：无 A/B 判定可做，直接报维度敏感性
    if not rows_ab:
        return f"仅极值对照 run（A/B 用历史数据）：{dim_sig_note}"
    if not c_rows:
        return f"warmth 极值对照无数据，方法敏感性未知。{dim_sig_note}"
    if not c_sig:
        return ("方法敏感性未通过：warmth 极值对照无显著差异 → 输出层观测方法失效"
                "或注入无效，需人工检查原始回复区分，A/B 差异不可判定")
    if not changed:
        return f"显示层无跨格维度：真实漂移幅度不足以让 prompt 可见 → 漂移不影响输出（需提高步长/精度重验）。{dim_sig_note}"
    sig_dims = [r["dim"] for r in rows_ab if r["p"] < 0.05 and r["delta"] != 0]
    sig_same = [d for d in sig_dims if direction.get(d, {}).get("same_direction") is True]
    sig_reverse = [d for d in sig_dims if direction.get(d, {}).get("same_direction") is False]
    if sig_same:
        return (f"漂移真实影响输出：{len(sig_same)} 个维度显著且同向"
                f"（{sig_same}）→ 演化有行为意义。{dim_sig_note}")
    if sig_reverse:
        return (f"漂移影响待定：{len(sig_reverse)} 个维度显著但方向与向量相反"
                f"（{sig_reverse}）→ 不能判定为行为意义，"
                f"需排查观测函数维度耦合或模型对数值的语义理解，或增大漂移幅度重验。{dim_sig_note}")
    return f"显示层有变化但输出层无显著差异：注入存在但权重低 → 需增强 prompt 约束或调整措辞。{dim_sig_note}"


def _write_report(res):
    lines = [
        "# 实验 B 报告：人格漂移 → prompt → 输出 因果验证",
        "",
        f"- run_dir：`{res['run_dir']}`",
        f"- 模型：{res['model']}  temperature={res['temperature']}",
        f"- 输入：{res['inputs']} 条（POOL_NEUTRAL） × {res['repeats']} 采样 × {len(res['groups'])} 组",
        "",
        "## 一、组设计",
        "",
        "| 组 | 含义 | 向量 |",
        "|---|---|---|",
        "| A_seed | 基线 | " + json.dumps(res["vectors"]["A_seed"], ensure_ascii=False) + " |",
        "| B_drift | 真实漂移 | " + json.dumps(res["vectors"]["B_drift"], ensure_ascii=False) + " |",
        "| C_low / C_high | 极值对照 | warmth 0.1 vs 0.9 |",
        "| D_low / D_high | 极值对照 | directness 0.1 vs 0.9 |",
        "| E_low / E_high | 极值对照 | curiosity 0.1 vs 0.9 |",
        "",
        "## 二、显示层（.1f 精度）",
        "",
        "A: `" + res["display_layer"]["A_text"].replace("\n", " | ") + "`",
        "B: `" + res["display_layer"]["B_text"].replace("\n", " | ") + "`",
        "",
        "跨显示阈值维度：" + (", ".join(res["display_layer"]["changed_dims"]) or "无"),
        "",
        "## 三、输出层（estimate_style_from_reply 关键词观测）",
        "",
        "### A vs B（真实漂移）",
        "",
        "| 维度 | A均值 | B均值 | Δ | Cohen's d | p |",
        "|---|---|---|---|---|---|",
    ]
    for r in res["output_layer"]["A_vs_B"]:
        lines.append(f"| {r['dim']} | {r['mean_a']} | {r['mean_b']} | {r['delta']:+.3f} | "
                     f"{r['cohen_d']:+.3f} | {r['p']} |")
    lines += [
        "",
        "### 维度敏感性（极值对照 0.1 vs 0.9）",
        "",
        "| 对照维度 | 输出维度 | low均值 | high均值 | Δ | Cohen's d | p |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for dim, rows in res["output_layer"]["extreme"].items():
        for r in rows:
            lines.append(f"| {dim} | {r['dim']} | {r['mean_a']} | {r['mean_b']} | "
                         f"{r['delta']:+.3f} | {r['cohen_d']:+.3f} | {r['p']} |")
    lines += [
        "",
        "## 四、同向性",
        "",
        "| 维度 | 向量Δ | 输出Δ | 同向 |",
        "|---|---|---|---|",
    ]
    for dim, v in res["direction"].items():
        lines.append(f"| {dim} | {v['vector_delta']:+.3f} | {v['output_delta']:+.3f} | {v['same_direction']} |")
    lines += [
        "",
        "## 五、判定",
        "",
        res["verdict"],
    ]
    with open(os.path.join(OUT_DIR, "probe_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
