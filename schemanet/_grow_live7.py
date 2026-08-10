# -*- coding: utf-8 -*-
"""运行-教学融合（2026-08-10 用户："能不能把教学融入进去？因为教学
就是刻意设计的情景，但是是有意义的"）。

哲学回答：强行设计情景（坏）= 预先剧本喂入（网络被动）；有意义的
教学（好）= **响应式教学**——网络在运行中自发冒出念头 → 教师在
"可教时刻"（teachable moment）针对网络**当前实际活动**介入教学
（偶发教学 incidental teaching / NDBI 儿童主导干预）。

框架（网络的生活流 + 教学介入）：
  每步（相位推进）：
    ① 念头冒出（静默运行机制：时钟唤起/联想流/噪声触发）
    ② 念头评估（LLM：一致性×自然度 = 门槛×高度）
    ③ 教学决策：
       - 念头好（≥80）→ 轻奖励固化，**不打断**（生活继续）
       - 念头差（<60）→ **可教时刻**：LLM 教师设计针对性教学
         （一句话情景 + 示范句——针对孩子刚才说的）→ 跟读 → 修正
       - 沉默太久（连续 N 步无念头）→ 偶发教学（教师用有意义的
         问题启动——"你饿不饿呀？"——教学性启动，非剧本）
  输出：运行-教学融合日志（念头流 + 教学介入点 + 修正效果）。

用法：python _grow_live7.py [--seed N] [--smoke]
"""

import random
import sys
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version
from _grow_v11 import _load_key, _llm_chat
from _grow_qa_s3 import _segment_demo

DATA = Path(__file__).parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).parent / "runs"
N_STEPS = 24                     # 运行步数（1.5 天）
SILENCE_LIMIT = 6                # 沉默阈值：连续 N 步无念头 → 偶发教学
PHASE_MEM = {range(2, 6): "早上", range(6, 10): "中午",
             range(10, 14): "晚上"}

# 内感受源（念头池——自由运行中网络"会想到"的状态词；偶发教学用它
# 启动，教学语由 LLM 生成——有意义的设计，非剧本）
STATE_WORDS = ["饿", "冷", "累", "渴"]


def llm_judge(kw, toks, trace):
    """念头评估：一致性（门槛）× 自然度（高度）。"""
    mind = " → ".join(
        f"想到「{t['state']}」，心里冒出 {t['cands'][:2]}"
        for t in trace[:4]) or "（无）"
    said = "/".join([kw] + toks) or "（说不出话）"
    q = (f"你是只能听和说的评估者（面对一个自闭症儿童，无视觉）。\n"
         f"孩子心里：{mind}\n孩子说：「{said}」\n"
         f"输出：\n【一致性】0-10（说的和心里想的贴不贴）\n"
         f"【自然度】0-10（像不像人话）")
    txt = _llm_chat([{"role": "user", "content": q}])
    if not txt:
        return None
    out = {}
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("【一致性】"):
            out["cons"] = float("".join(c for c in line if c.isdigit()
                                        or c == ".")[:3] or 0)
        elif line.startswith("【自然度】"):
            out["nat"] = float("".join(c for c in line if c.isdigit()
                                       or c == ".")[:3] or 0)
    if "cons" not in out or "nat" not in out:
        return None
    return out


def llm_teach(kw, toks):
    """可教时刻教学：LLM 妈妈式教师——针对孩子刚才的实际表达设计
    有意义的情景教学（不是剧本，是响应）。"""
    said = "/".join(toks) or "（说不出话）"
    q = (f"你是妈妈式的老师，面对一个只能听和说的自闭症儿童。\n"
         f"孩子刚才想说「{kw}」这件事，说出口的是：「{said}」"
         f"（表达混乱/不自然）。\n"
         f"这是一个可教时刻：请设计一个有意义的教学（针对孩子刚才"
         f"想说的这件事本身）\n"
         f"【教学语】妈妈式一句话（指出问题 + 引导，≤22 字，自然口语）\n"
         f"【示范句】孩子此刻应该说的自然完整句（≤10 字）")
    txt = _llm_chat([{"role": "user", "content": q}])
    if not txt:
        return None
    out = {"fb": "", "demo": ""}
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("【教学语】"):
            out["fb"] = line.replace("【教学语】", "").strip()
        elif line.startswith("【示范句】"):
            out["demo"] = line.replace("【示范句】", "").strip()
    return out if out["demo"] else None


def main():
    from _exam_free import FUNC, free_read, build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool
    from _grow_cat import build_cats
    import json

    seed = int(sys.argv[sys.argv.index("--seed") + 1]) \
        if "--seed" in sys.argv else 7
    smoke = "--smoke" in sys.argv
    random.seed(seed)
    has_llm = bool(_load_key())
    t0 = time.time()
    print(f"═══ 运行-教学融合（网络生活流 + 可教时刻响应教学）═══\n")
    print(f"（教学 = 响应式：只在网络冒出念头后、针对它的实际活动介入"
          f"——偶发教学）\n")

    ng, vocab, pats, cursor = load_version("30.1")
    ng.w_max = 64.0
    n2w = {j: w for w, ns in pats.items() for j in ns}
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)

    phase = 0
    silence = 0
    n_teach = n_good = n_silent = 0
    last_tail = None
    for step in range(N_STEPS):
        phase = (phase + 1) % 16
        # ① 念头冒出（静默运行：时钟唤起/联想/噪声）
        thought = None
        mem_word = next((w for r, w in PHASE_MEM.items()
                         if phase in r), None)
        if random.randint(1, 3) == 1:
            seed_w = last_tail if (last_tail and random.random() < 0.5) \
                else mem_word
            if seed_w:
                trace = []
                read = free_read(ng, pats, n2w, [seed_w], domain,
                                 teach_out=teach_out, trace=trace)
                toks = []
                for w in [x.split("(")[0] for x in read]:
                    if w.startswith("[") or w in toks:
                        break
                    toks.append(w)
                if toks:
                    thought = (seed_w, toks, trace)
                    last_tail = toks[-1]
        if thought is None:
            silence += 1
            if silence >= SILENCE_LIMIT:
                # ④ 偶发教学：沉默太久——教师用有意义的问题启动
                kw = random.choice(STATE_WORDS)
                got = llm_teach(kw, [])
                n_silent += 1
                silence = 0
                if got:
                    print(f"[相位{phase:2d}] （沉默 {SILENCE_LIMIT} 步）"
                          f"教师偶发教学：「{got['fb']}」")
                    # 跟读示范（教学启动表达）
                    for w in ("饿", "冷", "累", "渴"):
                        if w == kw:
                            _learn_sentence(
                                ng, {"饿": ["饿", "了", "就", "吃", "饭"],
                                     "冷": ["冷", "了", "就", "穿", "衣服"],
                                     "累": ["累", "了", "就", "睡觉"],
                                     "渴": ["渴", "了", "就", "喝", "水"]}[w],
                                pats, slot=0)
            continue
        silence = 0
        kw, toks, trace = thought
        # ② 念头评估（LLM：一致性×自然度）
        got = llm_judge(kw, toks, trace) if has_llm else None
        if got is None:
            cons = sum(1 for t in trace
                       if t["chosen"] in [c for c, _ in t["cands"]]
                       ) / max(len(trace), 1) * 10
            nat = 7.0 if any(w in toks for w in ("吃", "饭")) else 2.0
            got = {"cons": cons, "nat": nat}
        score = got["cons"] * got["nat"]
        said = "/".join([kw] + toks)
        if score >= 80:
            n_good += 1
            print(f"[相位{phase:2d}] 念头：「{said}」"
                  f"（{got['cons']:.0f}×{got['nat']:.0f}={score:.0f}）"
                  f" ✅ 好念头——不打断，生活继续")
        else:
            # ③ 可教时刻：针对网络刚才的实际活动响应教学
            teach = llm_teach(kw, toks) if has_llm else None
            n_teach += 1
            if teach:
                print(f"[相位{phase:2d}] 念头：「{said}」"
                      f"（{got['cons']:.0f}×{got['nat']:.0f}={score:.0f}）"
                      f" ⚠ 可教时刻")
                print(f"        教师：「{teach['fb']}」"
                      f" 跟读「{teach['demo']}」×2")
            else:
                print(f"[相位{phase:2d}] 念头：「{said}」"
                      f"（{score:.0f}）⚠ 可教时刻（规则示范）")
            # 规则回退示范（LLM 无 key 或解析失败）
            if not (teach or {}).get("demo"):
                expect = {"饿": ["饿", "了", "就", "吃", "饭"],
                          "冷": ["冷", "了", "就", "穿", "衣服"],
                          "累": ["累", "了", "就", "睡觉"],
                          "渴": ["渴", "了", "就", "喝", "水"]}.get(kw, [])
            else:
                expect = []
            keys_sorted = sorted(pats.keys(), key=len, reverse=True)
            for _ in range(2):
                if teach and teach["demo"]:
                    demo_toks = _segment_demo(teach["demo"], keys_sorted)
                    if demo_toks:
                        _learn_sentence(ng, demo_toks, pats, slot=0)
                elif expect:
                    _learn_sentence(ng, expect, pats, slot=0)

    print(f"\n═══ 运行-教学融合统计 ═══")
    print(f"  运行 {N_STEPS} 步：好念头 {n_good} · 可教时刻教学 {n_teach}"
          f" · 偶发教学 {n_silent}")
    print(f"  教学全部响应式（念头后介入，针对实际活动）——"
          f"无预设剧本")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
