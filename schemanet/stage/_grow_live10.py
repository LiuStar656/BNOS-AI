# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""持续循环运行（2026-08-11 用户："能持续循环吗？"）。

循环性（对应昼夜节律 + 学习循环）：
  ① 时钟无限循环：phase = t mod 16（时间永续——底层不停）
  ② 课表循环：每天 5 节课（8 种形式按天轮换 + 内容按天轮换——
     教学周而复始）
  ③ 在线编码持续累积：每经历一件事 → 事件↔相位 Hebbian（经历
     塑造时间记忆——多次经历边权累积）
  ④ 观察成长：表达评分随天变化（越活越熟练？——在线编码累积 +
     奖励固化 → 表达质量提升曲线）

用法：python _grow_live10.py [DAYS] [--smoke]
"""

import random
import sys
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version
from _grow_v11 import _load_key, _llm_chat
from _grow_v16 import edge_between

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
PHASE_MEM = {range(2, 6): "早上", range(6, 10): "中午",
             range(10, 14): "晚上"}

# 8 种教学形式（按天轮换）＋ 内容池（按天轮换——备课循环）
FORMS = ["示范跟读", "提问应答", "情景对话", "故事", "游戏", "扩展",
         "纠错重铸", "日常闲聊"]
CONTENTS = [
    "早上起床，洗手，刷牙，吃饭",
    "你饿不饿呀？",
    "你早上做了什么？",
    "小猫饿了，小猫吃饭。小猫吃饱了，小猫睡觉。",
    "我们来玩'说什么就做什么'：说'拍拍手'",
    "你说'饿了'，妈妈教你多说一点",
    "（重铸孩子刚才说错的）",
    "今天天气真好呀",
]
LESSON_PHASES = [2, 6, 10, 13, 15]      # 每天 5 节课的相位


def llm_teacher(form, content, kw, toks, trace):
    import re
    mind = " → ".join(
        "「%s」冒出%s" % (t["state"], t["cands"][:2])
        for t in trace[:3]) or "（无）"
    said = "/".join([kw] + toks) if toks else "（说不出话）"
    q = (f"你是妈妈式的老师，一对一陪着一个只能听和说的自闭症儿童"
         f"（无视觉）。\n"
         f"本节课形式：{form}。内容背景：{content}\n"
         f"孩子开口前内心：{mind}\n孩子说：「{said}」\n"
         f"请按本节课形式自然教学，只输出：\n"
         f"【一致性】0-10【自然度】0-10\n"
         f"【教师反馈】妈妈式自然反馈（贴合形式，≤30 字）\n"
         f"【示范句】孩子该说的自然句（≤10 字）")
    txt = None
    for _ in range(2):
        txt = _llm_chat([{"role": "user", "content": q}])
        if txt:
            break
    if not txt:
        return None
    parts = re.split(r"【(一致性|自然度|教师反馈|示范句)】", txt)
    out = {"cons": None, "nat": None, "fb": "", "demo": ""}
    for i in range(1, len(parts), 2):
        val = (parts[i + 1] if i + 1 < len(parts) else "").strip()
        if parts[i] == "一致性":
            out["cons"] = float("".join(c for c in val if c.isdigit()
                                        or c == ".")[:3] or 0)
        elif parts[i] == "自然度":
            out["nat"] = float("".join(c for c in val if c.isdigit()
                                       or c == ".")[:3] or 0)
        elif parts[i] == "教师反馈":
            out["fb"] = val
        elif parts[i] == "示范句":
            out["demo"] = val
    if out["cons"] is None or out["nat"] is None:
        return None
    return out


def main():
    from _exam_free import FUNC, free_read, build_domain, build_teach_out
    from _grow_qa_s3 import build_pool as qa_build_pool, _segment_demo
    from _grow_cat import build_cats
    from _grow_teacher import penalize_drift
    import json

    days = int(sys.argv[1]) if len(sys.argv) > 1 and \
        sys.argv[1].isdigit() else 5
    smoke = "--smoke" in sys.argv
    if smoke:
        days = 2
    random.seed(33)
    has_llm = bool(_load_key())
    t0 = time.time()
    print(f"═══ 持续循环运行（{days} 天 × 16 相位 = {days*16} 时刻）═══\n")

    ng, vocab, pats, cursor = load_version("32.0")
    ng.w_max = 64.0
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)
    keys_sorted = sorted(pats.keys(), key=len, reverse=True)

    def encode_phase(ev, phase):
        if ev not in pats:
            return
        _learn_sentence(ng, [f"CLK_{phase}", ev], pats, slot=0)
        _learn_sentence(ng, [ev, f"CLK_{phase}"], pats, slot=0)

    # ── 持续循环 ──────────────────────────────────
    phase = 0
    last_tail = None
    day_scores, day_thoughts = [], []
    for day in range(1, days + 1):
        d_scores, d_thoughts = [], 0
        for step in range(16):
            phase = (phase + 1) % 16
            mem_word = next((w for r, w in PHASE_MEM.items()
                             if phase in r), None)
            if phase in LESSON_PHASES:
                # 教师课（形式/内容按天轮换——循环课表）
                i = (day * 5 + LESSON_PHASES.index(phase)) % 8
                form, content = FORMS[i], CONTENTS[i]
                kw = {"提问应答": "饿", "示范跟读": "早上",
                      "情景对话": "早上", "故事": "猫", "游戏": "手",
                      "扩展": "饿", "纠错重铸": "饿",
                      "日常闲聊": "天气"}[form]
                trace = []
                read = free_read(ng, pats, n2w, [kw], domain,
                                 teach_out=teach_out, trace=trace)
                toks = []
                for w in [x.split("(")[0] for x in read]:
                    if w.startswith("[") or w in toks:
                        break
                    toks.append(w)
                encode_phase(kw, phase)
                got = llm_teacher(form, content, kw, toks, trace) \
                    if has_llm else None
                if got is None:
                    cons = sum(1 for tr in trace
                               if tr["chosen"] in [c for c, _ in tr["cands"]]
                               ) / max(len(trace), 1) * 10
                    nat = 7.0 if any(w in toks for w in ("吃", "饭")) \
                        else 2.0
                    got = {"cons": cons, "nat": nat, "fb": "", "demo": ""}
                score = got["cons"] * got["nat"]
                d_scores.append(score)
                demo_toks = _segment_demo(content, keys_sorted)
                if score >= 60 and demo_toks:
                    for _ in range(2):
                        _learn_sentence(ng, demo_toks, pats, slot=0)
                elif score < 40 and toks:
                    penalize_drift(ng, pats, toks, demo_toks or [])
                print(f"  D{day} 相位{phase:2d} ★{form}「{content[:10]}…」"
                      f" 说「{'/'.join([kw] + toks) or '∅'}」"
                      f" {score:.0f}分")
            else:
                # 空闲：念头 + 在线编码
                if random.randint(1, 4) == 1:
                    seed_w = last_tail if (last_tail and
                                           random.random() < .5) \
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
                            last_tail = toks[-1]
                            d_thoughts += 1
                            encode_phase(seed_w, phase)
        day_scores.append(sum(d_scores) / len(d_scores) if d_scores else 0)
        day_thoughts.append(d_thoughts)
        print(f"  ── 第 {day} 天：课均分 {day_scores[-1]:.0f}"
              f" · 念头 {d_thoughts}")

    # ── 成长曲线 ──────────────────────────────────
    print(f"\n═══ 持续循环统计（{days} 天）═══")
    print("  天数: " + " ".join(f"D{i:<3d}" for i in range(1, days + 1)))
    print("  课均分: " + " ".join(f"{s:5.0f}" for s in day_scores))
    print("  念头数: " + " ".join(f"{c:5d}" for c in day_thoughts))
    if len(day_scores) >= 2:
        trend = "↑ 成长" if day_scores[-1] > day_scores[0] + 5 else \
                ("→ 平稳" if abs(day_scores[-1] - day_scores[0]) <= 5
                 else "↓")
        print(f"  课均分 {day_scores[0]:.0f} → {day_scores[-1]:.0f}：{trend}")
    # 编码累积检查（同一事件多次经历的边权）
    for ev in ("饿", "早上", "猫", "天气"):
        ws = [(p, edge_between(ng, pats, ev, f"CLK_{p}"))
              for p in range(16)]
        strong = [(p, w) for p, w in ws if w > 0]
        print(f"  「{ev}」时间记忆：{strong[:5]}{'…' if len(strong) > 5 else ''}"
              f"（经历过的相位有边——多次经历边权累积）")
    print(f"  循环性：时钟无限（phase mod 16）· 课表按天轮换 · "
          f"编码持续累积——系统可持续运行")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
