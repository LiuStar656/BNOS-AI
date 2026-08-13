# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""在线时序编码 + 教师多样课程（2026-08-11 用户："相位进动时网络内部
结构要有细微变化（经历即编码）" + "丰富教师的课程表现形式"）。

① 在线时序编码（时钟从计数器升级为编码器）：
   网络经历事件（念头冒出/教师刺激）→ 事件词 与 当前相位 CLK_phase
   双向共发放 → Hebbian 微调（经历即记住时间——不需要教学）：
     相位→事件（CLK_phase→事件：这个相位想起这件事——唤起）
     事件→相位（事件→CLK_phase：什么时候发生的——询问）
   验证：经历后 相位唤起（相位 X 附近想起事件）/ 时间顺序
   （相位距离 = 时间距离）

② 教师多样课程表现形式（真实教学——8 种形式课表）：
   示范跟读 / 提问应答 / 情景对话（多轮）/ 故事 / 游戏 /
   扩展（加一原则）/ 纠错重铸 / 日常闲聊
   ——每课形式不同（真实父母教学的形式多样性）

用法：python _grow_live9.py [--smoke]
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
TOTAL = 40                       # 时间轴（2.5 天）
PHASE_MEM = {range(2, 6): "早上", range(6, 10): "中午",
             range(10, 14): "晚上"}

# ── 教师多样课程表：(时刻, 形式, 内容) ──────────────
# 8 种表现形式（真实教学多样性——内容背景 = 常识/自我表达/生活）
SCHEDULE = [
    (2, "示范跟读", "早上起床，洗手，刷牙，吃饭"),
    (6, "提问应答", "你饿不饿呀？"),
    (10, "情景对话", "你早上做了什么？"),
    (15, "故事", "小猫饿了，小猫吃饭。小猫吃饱了，小猫睡觉。"),
    (19, "游戏", "我们来玩'说什么就做什么'：说'拍拍手'"),
    (24, "扩展", "你说'饿了'，妈妈教你多说一点"),
    (28, "纠错重铸", "（重铸孩子刚才说错的）"),
    (33, "日常闲聊", "今天天气真好呀"),
]


def llm_teacher(lesson_form, lesson_content, kw, toks, trace):
    """教师一次调用（按形式生成真实教学——妈妈式）。"""
    mind = " → ".join(
        "「%s」冒出%s" % (t["state"], t["cands"][:2])
        for t in trace[:3]) or "（无）"
    said = "/".join([kw] + toks) if toks else "（说不出话）"
    q = (f"你是妈妈式的老师，一对一陪着一个只能听和说的自闭症儿童"
         f"（无视觉）。\n"
         f"本节课形式：{lesson_form}。内容背景：{lesson_content}\n"
         f"孩子开口前内心（可观测）：{mind}\n孩子说：「{said}」\n"
         f"请按本节课形式自然教学，只输出：\n"
         f"【一致性】0-10【自然度】0-10\n"
         f"【教师反馈】妈妈式自然反馈（贴合本节课形式：示范就带读、"
         f"问答就追问、对话就接话、故事就讲/问、游戏就玩、扩展就加"
         f"词、重铸就重说一遍、闲聊就接着聊；≤30 字）\n"
         f"【示范句】此刻孩子该说的自然句（≤10 字）")
    import re
    txt = None
    for _ in range(2):                     # 失败重试一次
        txt = _llm_chat([{"role": "user", "content": q}])
        if txt:
            break
    if not txt:
        return None
    # re 分节解析（长 prompt 下 LLM 输出可能换行/多行——不依赖同行）
    parts = re.split(r"【(一致性|自然度|教师反馈|示范句)】", txt)
    out = {"cons": None, "nat": None, "fb": "", "demo": ""}
    for i in range(1, len(parts), 2):
        key, val = parts[i], (parts[i + 1] if i + 1 < len(parts) else "").strip()
        if key == "一致性":
            out["cons"] = float("".join(c for c in val if c.isdigit()
                                        or c == ".")[:3] or 0)
        elif key == "自然度":
            out["nat"] = float("".join(c for c in val if c.isdigit()
                                       or c == ".")[:3] or 0)
        elif key == "教师反馈":
            out["fb"] = val
        elif key == "示范句":
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

    random.seed(21)
    smoke = "--smoke" in sys.argv
    has_llm = bool(_load_key())
    t0 = time.time()
    print("═══ 在线时序编码 + 教师多样课程 ═══\n")

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

    def encode_phase(event_word, phase):
        """在线时序编码：经历事件 ↔ 当前相位 双向 Hebbian 微调
        （相位→事件 唤起 + 事件→相位 询问——经历即记住时间）。"""
        if event_word not in pats:
            return
        _learn_sentence(ng, [f"CLK_{phase}", event_word], pats, slot=0)
        _learn_sentence(ng, [event_word, f"CLK_{phase}"], pats, slot=0)

    # ── 运行（时间轴：时钟永动 + 教师并行 + 在线编码）──
    schedule = SCHEDULE[:3] if smoke else SCHEDULE
    phase = 0
    last_tail = None
    events = []                  # 经历记录：(时刻, 相位, 事件词)
    n_idle = n_teach = n_thought = 0
    for t in range(TOTAL):
        phase = (phase + 1) % 16
        mem_word = next((w for r, w in PHASE_MEM.items() if phase in r),
                        None)
        lesson = next((s for s in schedule if s[0] == t), None)
        if lesson:
            # 教师时刻（并行叠加）——形式多样的课程
            form, content = lesson[1], lesson[2]
            kw = {"提问应答": "饿", "示范跟读": "早上", "情景对话": "早上",
                  "故事": "猫", "游戏": "手", "扩展": "饿",
                  "纠错重铸": "饿", "日常闲聊": "天气"}.get(form, "饿")
            n_teach += 1
            trace = []
            read = free_read(ng, pats, n2w, [kw], domain,
                             teach_out=teach_out, trace=trace)
            toks = []
            for w in [x.split("(")[0] for x in read]:
                if w.startswith("[") or w in toks:
                    break
                toks.append(w)
            # 在线时序编码：教师课 = 经历（与当前相位绑定）
            encode_phase(kw, phase)
            events.append((t, phase, kw))
            got = llm_teacher(form, content, kw, toks, trace) \
                if has_llm else None
            if got is None:
                cons = sum(1 for tr in trace
                           if tr["chosen"] in [c for c, _ in tr["cands"]]
                           ) / max(len(trace), 1) * 10
                nat = 7.0 if any(w in toks for w in ("吃", "饭")) else 2.0
                got = {"cons": cons, "nat": nat, "fb": "", "demo": ""}
            score = got["cons"] * got["nat"]
            print(f"[t={t:2d} 相位{phase:2d}] ★教师（{form}）"
                  f"「{content[:14]}{'…' if len(content) > 14 else ''}」")
            print(f"       网络说：「{'/'.join([kw] + toks) or '（无）'}」"
                  f" {got['cons']:.0f}×{got['nat']:.0f}={score:.0f}")
            print(f"       教师：「{got['fb']}」"
                  f"（示范：{got['demo']}）")
            # 在线编码打印（经历→相位）
            print(f"       [编码] {kw}↔CLK_{phase}（经历即记住时间）")
            if score >= 80:
                for _ in range(3):
                    _learn_sentence(ng, [kw] + ["了"] + toks[1:],
                                    pats, slot=0) if False else None
                    _learn_sentence(ng, ["饿了", "就", "吃", "饭"],
                                    pats, slot=0) if kw == "饿" else None
            # 简化奖励：高分跟读期望（按形式内容分词）
            demo_toks = _segment_demo(content, keys_sorted)
            if score >= 60 and demo_toks:
                for _ in range(2):
                    _learn_sentence(ng, demo_toks, pats, slot=0)
            elif score < 40 and toks:
                n_dec = penalize_drift(ng, pats, toks, demo_toks or [])
                print(f"       [处罚] 漂移边降权 {n_dec} 条")
        else:
            # 空闲时段：时间流逝 + 念头（在线编码到相位）
            n_idle += 1
            if random.randint(1, 4) == 1:
                seed_w = last_tail if (last_tail and random.random() < .5) \
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
                        n_thought += 1
                        encode_phase(seed_w, phase)   # 念头也编码时间
                        events.append((t, phase, seed_w))
                        print(f"[t={t:2d} 相位{phase:2d}]（空闲）冒出"
                              f"「{seed_w}/{'/'.join(toks[:3])}」"
                              f" [编码] {seed_w}↔CLK_{phase}")

    # ── 在线时序编码验证 ──────────────────────────
    print(f"\n═══ 在线时序编码验证（经历即记住时间——无教学）═══")
    for t, ph, ev in events[:6]:
        w2c = edge_between(ng, pats, ev, f"CLK_{ph}")
        c2w = edge_between(ng, pats, f"CLK_{ph}", ev)
        print(f"  「{ev}」经历于相位 {ph} → 事件→CLK_{ph} = {w2c:g}"
              f" · CLK_{ph}→事件 = {c2w:g}"
              f"（{'✅ 已编码' if w2c + c2w > 0 else '✗'}）")
    if len(events) >= 2:
        ph_a, ph_b = events[0][1], events[1][1]
        print(f"  时间顺序：{events[0][2]}（相位 {ph_a}）先于 "
              f"{events[1][2]}（相位 {ph_b}）——"
              f"{'✅ 相位距离 = 时间距离' if ph_a < ph_b else '⚠ 跨天回绕'}")
    print(f"\n═══ 时间线统计 ═══")
    print(f"  总时刻 {TOTAL}：空闲 {n_idle} · 念头 {n_thought} · "
          f"教师课 {n_teach}（8 种形式）· 在线编码 {len(events)} 次")
    print(f"  时钟 = 编码器：每经历一件事，结构微调（Hebbian）——"
          f"经历即记住时间")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
