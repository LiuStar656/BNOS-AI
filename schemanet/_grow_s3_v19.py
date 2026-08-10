# -*- coding: utf-8 -*-
"""s3 正式课程 v19 整合：对话教学 → 自我表达 → 问答应答，单进程顺序教学。

对齐 v2.17/v2.18 幼小衔接 + 早教自我表达设计（2026-08-10）：
  阶段 A 对话教学（期望链约束读取——v18.x 三教学脚本横断结论：自由读取
    被"我→想"256 霸主边锁死，链读 15 轮收敛）
  阶段 B 自我表达（网络=自闭症类比：内感受→表达绑定 + FCT + 自发发起）
  阶段 C 问答应答（Intraverbal：据因推果/以果溯因/什么是 + LLM 换问法）
每阶段独立 streak 15 通过（错一次清零），LLM 教师（一次调用多节）+ 规则
回退；教学后统一 EVAL 回归 + 校准兜底 + 快照 v19.0。

用法：python _grow_s3_v19.py [--no-llm] [--smoke]
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

# ── 阶段 A：对话教学（期望链约束读取）───────────────────────────
from _probe_dialog_v17 import build_dialog, run_dialog, DIALOG_DOMAIN


def stage_dialog(ng, pats, n2w, teach, smoke, log):
    rows_data = json.loads((DATA / "stage3_rel_v3.json").read_text(
        encoding="utf-8"))
    dialog = build_dialog(rows_data, smoke=smoke)
    topics = {t: [d for d in dialog if d[2] == t]
              for t in ["因果", "转折", "顺序"]}
    domain = sorted(w for w in DIALOG_DOMAIN if w in pats)
    keys_sorted = sorted(pats.keys(), key=len, reverse=True)
    streak, recent = 0, []
    import numpy as np
    _rng = np.random.default_rng()
    orders = {}

    def order(cyc):
        if cyc not in orders:
            o = list(range(3))
            _rng.shuffle(o)
            orders[cyc] = o
        return orders[cyc]

    print("\n── 阶段 A：对话教学（期望链约束读取，话题块 ×3 延续）──")
    n_rw = n_fix = 0
    for r in range(1, 100):
        bi = (r - 1) // 3
        cyc, tidx = divmod(bi, 3)
        tname = ["因果", "转折", "顺序"][order(cyc)[tidx]]
        pool = topics[tname]
        front, back, _, level = pool[(r - 1) % len(pool)]
        fade = "none" if streak >= FADE_AT else "full"
        rec = run_dialog(ng, pats, n2w, front, back, domain, train=True,
                         llm=teach, keys_sorted=keys_sorted,
                         recent=list(recent), fade=fade)
        rec["topic"], rec["level"] = tname, level
        recent = (recent + [rec["read_seq"]])[-3:]
        n_rw += rec["rewarded"]
        n_fix += len(rec["fixes"])
        if rec["ok"]:
            streak += 1
        else:
            streak = 0
        log.append({"stage": "A对话", "round": r, "topic": tname,
                    "front": rec["front"], "read": rec["read_seq"],
                    "expect": rec["back"], "ok": rec["ok"],
                    "ptype": rec["ptype"], "fade": fade})
        if streak >= STREAK_PASS:
            print(f"  [A] 连续 {STREAK_PASS} 次通过（{r} 轮）✅")
            break
    print(f"  [A] streak 峰值 {streak} | 奖励 {n_rw} | 处罚 {n_fix} 次")
    return streak >= STREAK_PASS


# ── 阶段 B：自我表达（网络=自闭症类比）──────────────────────────
from _grow_self_express import (STATES, STATE_SET, EXPR_DOMAIN,
                                express_read, teacher_llm as se_llm,
                                _segment_demo as seg)


def stage_self_express(ng, pats, n2w, teach, smoke, log):
    pool = []
    for st, d in STATES.items():
        for situ, kw in d["situ"][: (1 if smoke else 2)]:
            pool.append((situ, kw, d["expr"], "层2感受"))
    streak, n_rw, n_fix = 0, 0, 0
    print("\n── 阶段 B：自我表达（情境引发 → 我+状态词 → FCT/因果）──")
    for r in range(1, 100):
        situ, kw, expect, layer = pool[(r - 1) % len(pool)]
        fade = "none" if streak >= FADE_AT else "full"
        read_toks, state = express_read(ng, pats, n2w, kw, expect)
        ok = read_toks == expect
        got = None
        if teach and state:
            got = se_llm(situ, "".join(expect), read_toks, st)
            if got is not None:
                ok = bool(got["ok"])
        if ok:
            for _ in range(2 if fade == "none" else 1):
                _learn_sentence(ng, list(expect), pats, slot=0)
            n_rw += 1
            streak += 1
        else:
            if got is not None and got["demo"]:
                demo_toks = seg(got["demo"], sorted(pats.keys(),
                                                    key=len, reverse=True)) \
                    or list(expect)
            else:
                demo_toks = list(expect)
            if fade == "full":
                for _ in range(CAL_FIX):
                    _learn_sentence(ng, demo_toks, pats, slot=0)
                for a, b in zip(expect[:-1], expect[1:]):
                    _learn_sentence(ng, [a, b], pats, slot=0)
                if expect[1] in EXPR_DOMAIN:
                    _learn_sentence(ng, [kw, expect[1]], pats, slot=0)
            n_fix += 1
            streak = 0
        log.append({"stage": "B表达", "round": r, "layer": layer,
                    "situ": situ, "read": "".join(read_toks),
                    "expect": "".join(expect), "ok": ok, "fade": fade})
        if streak >= STREAK_PASS:
            print(f"  [B] 连续 {STREAK_PASS} 次通过（{r} 轮）✅")
            break
    # 层4 自发验收
    n_self = sum(1 for st, d in STATES.items()
                 if express_read(ng, pats, n2w, st, d["expr"])[0]
                 == d["expr"])
    print(f"  [B] streak 峰值 {streak} | 奖励 {n_rw} | 处罚 {n_fix} 次"
          f" | 自发发起 {n_self}/{len(STATES)}")
    return streak >= STREAK_PASS


# ── 阶段 C：问答应答（Intraverbal + LLM 换问法）────────────────
from _grow_qa_s3 import build_pool, qa_read, teacher_llm as qa_llm


def stage_qa(ng, pats, n2w, teach, smoke, log):
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    from _grow_cat import build_cats
    cats = build_cats(pats, sem["words"], 12, 3)
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    pool = build_pool(rows, cats, smoke=smoke)
    streak, n_rw, n_fix = 0, 0, 0
    pending, recent_asks = None, []
    print("\n── 阶段 C：问答应答（什么是/为什么/会怎样 + LLM 换问法）──")
    for r in range(1, 120):
        if pending and teach:
            ask, expect = pending
            pending = None
            layer = "LLM新题"
            kw = expect[0]
        else:
            ask, kw, expect, layer = pool[(r - 1) % len(pool)]
        fade = "none" if streak >= FADE_AT else "full"
        read_toks = qa_read(ng, pats, n2w, kw, expect)
        ok = read_toks == expect
        got = None
        if teach and read_toks:
            got = qa_llm(ask, "".join(expect), read_toks, layer,
                         recent_asks=recent_asks)
            if got is not None:
                ok = bool(got["ok"])
                if got["next"]:
                    pending = (got["next"], list(expect))
        recent_asks = (recent_asks + [ask])[-8:]
        if ok:
            for _ in range(2 if fade == "none" else 1):
                _learn_sentence(ng, list(expect), pats, slot=0)
            n_rw += 1
            streak += 1
        else:
            if got is not None and got["demo"]:
                demo_toks = seg(got["demo"], sorted(pats.keys(), key=len,
                                                    reverse=True)) \
                    or list(expect)
            else:
                demo_toks = list(expect)
            if fade == "full":
                for _ in range(CAL_FIX):
                    _learn_sentence(ng, demo_toks, pats, slot=0)
                for a, b in zip(expect[:-1], expect[1:]):
                    _learn_sentence(ng, [a, b], pats, slot=0)
                if kw != expect[0]:
                    _learn_sentence(ng, [kw, expect[1]], pats, slot=0)
            n_fix += 1
            streak = 0
        log.append({"stage": "C问答", "round": r, "layer": layer, "ask": ask,
                    "read": "".join(read_toks), "expect": "".join(expect),
                    "ok": ok, "fade": fade})
        if streak >= STREAK_PASS:
            print(f"  [C] 连续 {STREAK_PASS} 次通过（{r} 轮）✅")
            break
    print(f"  [C] streak 峰值 {streak} | 奖励 {n_rw} | 处罚 {n_fix} 次")
    return streak >= STREAK_PASS


def main():
    smoke = "--smoke" in sys.argv
    force_rule = "--no-llm" in sys.argv
    teach = bool(_load_key()) and not force_rule
    t0 = time.time()
    print("═══ s3 正式课程 v19：对话 → 自我表达 → 问答应答 ═══\n")

    ng, vocab, pats, cursor = load_version("17.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    print(f"[加载] 17.0：n={ng.n}，词表 {len(pats)} | "
          f"教师 {'LLM' if teach else '规则'}")

    log = []
    ok_a = stage_dialog(ng, pats, n2w, teach, smoke, log)
    ok_b = stage_self_express(ng, pats, n2w, teach, smoke, log)
    ok_c = stage_qa(ng, pats, n2w, teach, smoke, log)

    # ── EVAL 回归 + 校准兜底 ─────────────────────────────────
    from _grow_v15 import DOMAIN_WORDS
    domain = sorted(w for w in DOMAIN_WORDS if w in pats)
    _, ne, tote = chain_generate(ng, pats, n2w, domain)
    rate_e = ne / tote
    n_cal = 0
    if rate_e < 0.95:
        print(f"  [校准兜底] EVAL {rate_e:.3f} → 教师批改拉回…")
        n_cal = len(calibrate(ng, pats, n2w, domain))
        _, ne, tote = chain_generate(ng, pats, n2w, domain)
        rate_e = ne / tote
    print(f"  [EVAL 回归] {ne}/{tote} = {rate_e:.3f}（校准兜底 {n_cal} 处）")

    ok_all = bool(ok_a and ok_b and ok_c and rate_e >= 0.95)
    print(f"\n[验收] A对话 {'✅' if ok_a else '❌'} | "
          f"B表达 {'✅' if ok_b else '❌'} | C问答 {'✅' if ok_c else '❌'}"
          f" | EVAL {rate_e:.3f} | {'全部通过 ✅' if ok_all else '有失败 ❌'}")

    # ── 留档 + 快照 v19.0 ─────────────────────────────────────
    out_dir = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_s3_v19"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"tag": "s3 正式课程 v19（对话→自我表达→问答应答）",
              "base": "17.0", "teacher": "LLM" if teach else "规则",
              "stageA_dialog": ok_a, "stageB_express": ok_b,
              "stageC_qa": ok_c, "eval": {"hits": ne, "tot": tote,
                                          "rate": round(rate_e, 3),
                                          "cal_fallback": n_cal},
              "all_ok": ok_all, "sec": round(time.time() - t0, 1)}
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "talk_log.json").write_text(
        json.dumps({"meta": result, "rounds": log},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# s3 正式课程 v19 教学过程记录（{out_dir.name}）",
          f"\n> A对话 {'✅' if ok_a else '❌'} | B表达 {'✅' if ok_b else '❌'}"
          f" | C问答 {'✅' if ok_c else '❌'} | EVAL {rate_e:.3f}\n"]
    for rec in log:
        md.append(f"- [{rec['stage']}·轮{rec['round']}] "
                  f"{rec.get('front') or rec.get('situ') or rec.get('ask')}"
                  f" → 「{rec['read'] or '∅'}」（期「{rec['expect']}」）"
                  + (" ✅" if rec["ok"] else " ✗"))
    (out_dir / "dialog.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\n[留档] {out_dir}/（talk_log.json 逐轮 + dialog.md + result.json，"
          f"{time.time() - t0:.0f}s）")

    if not smoke:
        save_snapshot(ng, parent="17.0",
                      tag="Stage 3 v19：s3 正式课程（对话教学链读 + "
                          "自我表达 + 问答应答，幼小衔接整合）",
                      metrics=result, vocab=vocab, pats=pats, cursor=cursor)


if __name__ == "__main__":
    main()
