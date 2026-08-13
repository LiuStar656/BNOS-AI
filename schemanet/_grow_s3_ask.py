# -*- coding: utf-8 -*-
"""s3.4 主动提问 + 反问/设问（v2.17 方案落地：《指南》5-6 岁"听不懂或有
疑问时能主动提问" + 小学衔接预备的反问设问）。

三形态（幼儿教育对齐）：
  ① 主动提问（Mand 扩展，VB-MAPP 提问 = Mand L3）：网络读到"不懂的"
     （问答链断：引发边缺失）→ **主动问"为什么X？"**——"不懂就问"，
     教师回答示范 → 学问答对（闭环：提问 → 获答 → 学会）
  ② 反问（小学衔接预备，诚实标注）：口语反问"你不是吃饭了吗？"——
     虚词层（难道/吗/不是…吗）自然化显示；内容词 = 已学句
  ③ 设问（叙述自答）：自问自答"什么是苹果？苹果是水果"——问句链 +
     答句链连读（问句走通 → 答句走通）

教学流程（复用链读 + LLM 教师 + streak 15）：
  ① 主动提问：教师给"不懂情境"（问 X 会怎样，网络链断）→ 教师示范
     "不懂就问：为什么X？"→ 网络跟读提问链 [为什么,X] → 固化 为什么→X
     → 下次链断 → 网络主动输出提问链（= 主动提问成功）→ 教师答（示范
     期望回答）→ 学问答对 → 闭环
  ② 反问：教师示范反问句（内容 = 已学句 + 虚词）→ 网络跟读内容词链
     → 自然化显示（难道/吗 虚词层补齐）
  ③ 设问：教师示范自问自答（问句+答句连读）→ 网络跟读双链

用法：python _grow_s3_ask.py [--smoke] [--no-llm]
"""

import json
import sys
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from _grow_v11 import _load_key, _llm_chat
from _grow_v16 import (CAL_FIX, chain_generate, calibrate,
                       edge_between, direct_next_multi)

DATA = Path(__file__).parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).parent / "runs"
STREAK_PASS = 15
FADE_AT = 10
MAX_ROUNDS = 100

# ── 主动提问素材：网络**没学过**的问答对（真正"不懂才问"）───────
# 新组合：回答链引发边（喝水→因为）与提问链（为什么→喝水）都不存在
# → 初始链断 → 教师示范"不懂就问" → 固化提问链 → 主动问 → 教师答 →
# 固化回答链 → 学会 → 下次直接答（提问→获答→学会闭环，幼儿 FCT 同构）
NEW_ASKS = [
    ("为什么看医生？", "看医生", ["为什么", "看医生"], ["因为", "生病"]),
    ("为什么要吃饭？", "吃饭", ["为什么", "吃饭"], ["因为", "饿"]),
    ("为什么穿衣服？", "穿衣服", ["为什么", "穿衣服"], ["因为", "冷"]),
    ("为什么回家？", "回家", ["为什么", "回家"], ["因为", "累"]),
    ("为什么吃药？", "吃药", ["为什么", "吃药"], ["因为", "疼"]),
    ("为什么睡觉？", "睡觉", ["为什么", "睡觉"], ["因为", "困"]),
]


def build_ask_pool(rows, smoke=False):
    return NEW_ASKS[:(3 if smoke else len(NEW_ASKS))]


# ── 反问/设问素材（内容词全词表内已查证；虚词层显示）────────────
RHET_ITEMS = [          # [(自然句, 内容词链, 类型)]
    ("你不是吃饭了吗？", ["你", "吃", "饭", "了", "吗"], "反问"),
    ("难道你不冷吗？", ["你", "冷", "吗"], "反问"),
    ("什么是苹果？苹果是水果", ["什么", "是", "苹果", "苹果", "是", "水果"], "设问"),
    ("为什么下雨要带伞？因为下雨", ["为什么", "下雨", "带伞", "因为", "下雨"], "设问"),
]


def teacher_llm(situ, read_toks, mode):
    """LLM 教师：判定 + 反馈 + 示范（一次调用）。"""
    q = (f"你是妈妈式的中文教师，正在陪学生（定式网络）练"
         f"{'提问和回答' if mode == 'ask' else '反问设问'}。\n"
         f"你给它的情境：「{situ}」\n"
         f"学生说：「{''.join(x or '∅' for x in read_toks)}」\n"
         f"请只输出以下节标记（每个独占一行）：\n"
         f"【回答判定】是 或 否（学生说得对不对、贴不贴）\n"
         f"【质量原因】一句话讲清（≤30 字）\n"
         f"【教师反馈】妈妈式自然反馈（两三句话，带读'来，跟老师说：…'）\n"
         f"【示范句】一句完整示范（自然口语）")
    txt = _llm_chat([{"role": "user", "content": q}])
    if not txt:
        return None
    out = {"ok": None, "ping": "", "fb": "", "demo": ""}
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("【回答判定】"):
            out["ok"] = line.replace("【回答判定】", "").strip() == "是"
        elif line.startswith("【质量原因】"):
            out["ping"] = line.replace("【质量原因】", "").strip()
        elif line.startswith("【教师反馈】"):
            out["fb"] = line.replace("【教师反馈】", "").strip()
        elif line.startswith("【示范句】"):
            out["demo"] = line.replace("【示范句】", "").strip()
    if out["ok"] is None and not out["demo"]:
        return None
    return out


def _segment_demo(sent, keys_sorted):
    toks, i = [], 0
    while i < len(sent):
        for w in keys_sorted:
            if sent.startswith(w, i):
                toks.append(w)
                i += len(w)
                break
        else:
            i += 1
    return toks


def chain_read(ng, pats, n2w, kw, expect):
    """链读：引发边检查（kw→expect[0]）+ 顺序链读（期望链约束）。"""
    if edge_between(ng, pats, kw, expect[0]) <= 0:
        return []
    seq = [expect[0]]
    cur, rest = expect[0], list(expect[1:])
    for _ in range(len(rest) + 1):
        if rest and rest[0] == cur:
            seq.append(cur)
            rest.pop(0)
            continue
        top = direct_next_multi(ng, pats, n2w, [cur], k=3, domain=set(expect))
        nxt = next((w for w, _ in top if w == rest[0]), None) if rest else None
        if not nxt:
            break
        seq.append(nxt)
        rest.pop(0)
        cur = nxt
    return seq


def main():
    smoke = "--smoke" in sys.argv
    force_rule = "--no-llm" in sys.argv
    teach = bool(_load_key()) and not force_rule
    t0 = time.time()
    print("═══ s3.4 主动提问 + 反问/设问（《指南》5-6 岁主动提问）═══\n")

    ng, vocab, pats, cursor = load_version("17.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys_sorted = sorted(pats.keys(), key=len, reverse=True)
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    pool = build_ask_pool(rows, smoke=smoke)
    print(f"[加载] 17.0：n={ng.n} | 教师 {'LLM' if teach else '规则'}"
          f" | 提问素材 {len(pool)} 项 + 反问设问 {len(RHET_ITEMS)} 项")

    log, streak, n_rw, n_fix = [], 0, 0, 0
    n_asked = 0                              # 主动提问成功次数
    # ── 阶段1：主动提问（不懂就问 → 教师答 → 学会闭环）────────
    print("\n── 阶段1：主动提问（链断 → 问「为什么X」→ 教师答 → 学会）──")
    for r in range(1, MAX_ROUNDS + 1):
        ask, kw, q_chain, a_chain = pool[(r - 1) % len(pool)]
        fade = "none" if streak >= FADE_AT else "full"
        # 网络表现：会答（回答链走通）→ 直接答；不会 → 主动问
        ans = chain_read(ng, pats, n2w, kw, a_chain)
        if ans == a_chain:
            read_toks, mode = ans, "答"
            ok = True
        else:
            q = chain_read(ng, pats, n2w, kw, q_chain)
            if q == q_chain:                 # 主动提问成功
                read_toks, mode = q, "主动问"
                ok = True
                n_asked += 1
            else:
                read_toks, mode = [], "不会"
                ok = False
        # 判定 = 客观链读（问链通/答链通）——LLM 判"提问"会被误判为
        # "没回答"（prompt 期待回答，实测 streak 波动）；LLM 只做示范反馈
        got = None
        if not ok and teach:
            got = teacher_llm(ask, read_toks, "ask")
        record = {"round": r, "stage": "提问", "ask": ask,
                  "read": "".join(read_toks), "ok": ok, "mode": mode,
                  "fade": fade}
        if ok:
            # 奖励（闭环：问了才获得答案）：答对学回答链；主动问 = 提问链
            # + 回答链（"提问→获答→学会"——幼儿不懂就问，问了才得到答案）
            target = list(a_chain if mode == "答" else q_chain + a_chain)
            for _ in range(2 if fade == "none" else 1):
                _learn_sentence(ng, list(target), pats, slot=0)
            n_rw += 1
            streak += 1
        else:
            # 不会 → 教师示范**只教提问**（"不懂就问：为什么X？"）——
            # 答案要靠"问"获得（下轮问出后教师才教回答，两步闭环）
            demo_toks = list(q_chain)
            if got is not None and got["demo"]:
                demo_toks = _segment_demo(got["demo"], keys_sorted) \
                    or list(q_chain)
            if fade == "full":
                for _ in range(CAL_FIX):
                    _learn_sentence(ng, demo_toks, pats, slot=0)
                for a, b in zip([kw] + q_chain[:-1], q_chain):
                    _learn_sentence(ng, [a, b], pats, slot=0)
            record["fb"] = got["fb"] if got else "来，跟老师说：" + "".join(q_chain)
            n_fix += 1
            streak = 0
        log.append(record)
        print(f"  [{r:>2}·streak{streak:>2}] {'✅' if ok else '✗'} "
              f"情境「{ask}」→ {mode}「{record['read'] or '∅'}」"
              + (f" 师：「{record['fb']}」" if not ok and "fb" in record else ""))
        if streak >= STREAK_PASS:
            print(f"  ✅ 连续 {STREAK_PASS} 次通过！")
            break
    ok1 = streak >= STREAK_PASS
    print(f"  [阶段1] streak 峰值 {streak} | 主动提问 {n_asked} 次 | "
          f"奖励 {n_rw} | 处罚 {n_fix}")

    # ── 阶段2：反问/设问（教师示范 → 跟读内容链 → 自然化显示）──
    print("\n── 阶段2：反问/设问（小学衔接预备，跟读 + 虚词层显示）──")
    streak, n_rw, n_fix = 0, 0, 0
    for r in range(1, MAX_ROUNDS + 1):
        natural, chain, kind = RHET_ITEMS[(r - 1) % len(RHET_ITEMS)]
        fade = "none" if streak >= FADE_AT else "full"
        # 内容链读取（去掉虚词后的词表内链）：链首 = 链[0] 直接激活
        read_toks = chain_read(ng, pats, n2w, chain[0], chain[1:]) \
            if len(chain) > 1 else chain
        if len(chain) > 1:
            read_toks = [chain[0]] + read_toks
        ok = read_toks == chain
        record = {"round": r, "stage": kind, "natural": natural,
                  "read": "".join(read_toks), "ok": ok, "fade": fade}
        if ok:
            for _ in range(2 if fade == "none" else 1):
                _learn_sentence(ng, list(chain), pats, slot=0)
            n_rw += 1
            streak += 1
        else:
            if fade == "full":
                for _ in range(CAL_FIX):
                    _learn_sentence(ng, list(chain), pats, slot=0)
                for a, b in zip(chain[:-1], chain[1:]):
                    _learn_sentence(ng, [a, b], pats, slot=0)
            record["fb"] = "来，跟老师说：" + natural
            n_fix += 1
            streak = 0
        log.append(record)
        if streak >= STREAK_PASS:
            print(f"  ✅ 连续 {STREAK_PASS} 次通过！")
            break
    ok2 = streak >= STREAK_PASS
    print(f"  [阶段2] streak 峰值 {streak} | 奖励 {n_rw} | 处罚 {n_fix}")

    # ── EVAL 回归 + 留档 + 快照 ───────────────────────────────
    from _grow_v15 import DOMAIN_WORDS
    domain = sorted(w for w in DOMAIN_WORDS if w in pats)
    _, ne, tote = chain_generate(ng, pats, n2w, domain)
    rate_e = ne / tote
    n_cal = 0
    if rate_e < 0.95:
        n_cal = len(calibrate(ng, pats, n2w, domain))
        _, ne, tote = chain_generate(ng, pats, n2w, domain)
        rate_e = ne / tote
    print(f"  [EVAL 回归] {ne}/{tote} = {rate_e:.3f}（校准兜底 {n_cal} 处）")

    out_dir = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_s3_ask"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"tag": "s3.4 主动提问 + 反问/设问",
              "base": "17.0", "teacher": "LLM" if teach else "规则",
              "stage1_ask": {"ok": ok1, "asked": n_asked},
              "stage2_rhet": ok2,
              "eval": {"hits": ne, "tot": tote, "rate": round(rate_e, 3),
                       "cal_fallback": n_cal},
              "sec": round(time.time() - t0, 1)}
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "talk_log.json").write_text(
        json.dumps({"meta": result, "rounds": log},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[留档] {out_dir}/（talk_log.json + result.json，"
          f"{time.time() - t0:.0f}s）")

    if not smoke:
        save_snapshot(ng, parent="17.0",
                      tag="Stage 3 v20：s3.4 主动提问 + 反问/设问"
                          "（《指南》5-6 岁主动提问 + 小学衔接预备）",
                      metrics=result, vocab=vocab, pats=pats, cursor=cursor)


if __name__ == "__main__":
    main()
