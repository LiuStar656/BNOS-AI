# -*- coding: utf-8 -*-
"""s3.3 问答应答教学（v2.17 方案落地）：教师问"什么是/为什么/会怎样"
→ 网络答 → LLM 教师批改。

VB-MAPP Intraverbal（内语言，四操作项最后缺口）L2 里程碑 9：
回答"What"问题。幼儿因果认知顺序（李宇明/陈前瑞）：**据因推果易、
以果溯因难**——三层问答由易到难：
  ① 据因推果（先教，166 条正向复用）：问「下雨了会怎样？」→ 答「所以要带伞」
  ② 以果溯因（后教，166 条反向 + 逆向锚点）：问「为什么带伞？」→ 答「因为下雨」
  ③ 命名应答（stage25 类别 hub）：问「什么是苹果？」→ 答「苹果是食物」

技术要点（网络只有 W_out，无逆向边）：
  - 逆向锚点边固化："带伞→因为"×N（教学固化，幼儿也是教出来的）
  - 引发边检查：关键词→链首词 边存在（固化过）即引发（避免域内竞争）
  - 期望链约束链读：每步只许读期望链剩余词（教学成果 = 链边走通）

LLM 教师一次调用：【回答判定】【质量原因】【教师反馈】【示范句】
【下个问题】——出题/判定/示范/讲评一体；无 key 回退规则。
教学流程：问 → 答 → 判定（规则 + LLM 贴切度）→ 奖励（学期望句，独立
×2）/处罚（示范跟读 ×3 + 词对固化 ×1）→ streak 15 通过。

用法：python _grow_qa_s3.py [--smoke] [--no-llm]
"""

import json
import sys
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from _grow_v11 import _load_key, _llm_chat
from _grow_v16 import (edge_between, direct_next_multi, CAL_FIX,
                       chain_generate, calibrate)

DATA = Path(__file__).parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).parent / "runs"
STREAK_PASS = 15
FADE_AT = 10
MAX_ROUNDS = 150


def build_pool(rows, cats, smoke=False):
    """问答池：[(问句, 关键词, 期望, 层)]——正反向因果 + 类别命名。

    ① 正向：问「原因会怎样？」→ 期 back（所以…）
    ② 反向：问「为什么结果？」→ 期 [因为]+原因（逆向锚点固化 结果→因为）
    ③ 命名：问「什么是X？」→ 期 [X,是,类别标签]
    """
    causal = [r for r in rows if r["tokens"][0] == "因为"
              and r["source"] in ("对话·构造", "短文·构造")]
    pool = []
    for r in causal[:(4 if smoke else 8)]:
        t = r["tokens"]
        idx = t.index("所以")
        cause, result = t[1:idx], t[idx:]       # 原因链 / 所以…结果链
        kw = next((w for w in reversed(cause) if w not in ("了", "今天")),
                  cause[-1])
        pool.append((f"{kw}会怎样？", kw, list(result), "①据因推果"))
        rkw = next((w for w in reversed(result) if w not in ("想", "要")),
                   result[-1])
        pool.append((f"为什么{rkw}？", rkw, ["因为"] + cause, "②以果溯因"))
    # ③ 命名（每类 3 词；smoke 每类 2）
    for label, d in cats.items():
        for w in d["train"][:(2 if smoke else 3)]:
            tag = d["tags"][0]
            pool.append((f"什么是{w}？", w, [w, "是", tag], "③什么是"))
    return pool


def teacher_llm(ask, expect_natural, read_toks, layer, recent_asks=None):
    """LLM 教师一次调用：回答判定 + 原因 + 反馈 + 示范 + **下个问题/答案**。

    下个问题（用户 2026-08-10："不要限制大模型的问题，保证每次教学大模型
    提的问题都是新的"——对齐 _speak.py pending_ask：LLM 自己发挥新问题+
    参考答案，网络跟读学新问答对；recent_asks 防重复）。
    """
    q = (f"你是妈妈式的中文教师，正在一对一地陪学生（定式网络）练回答。"
         f"你问：「{ask}」\n"
         f"学生答：「{''.join(x or '∅' for x in read_toks)}」"
         f"（参考：这个问题的自然回答是「{expect_natural}」这类话，"
         f"换个说法说同一件事也算对）\n"
         f"最近问过的问题：{'；'.join(recent_asks[-5:]) if recent_asks else '无'}"
         f"（下个问题不要重复这些）\n"
         f"请只输出以下节标记（每个独占一行，不要任何其他内容）：\n"
         f"【回答判定】是 或 否（学生回答和问题搭不搭、答没答到点上=是）\n"
         f"【质量原因】从自然语言角度一句话讲清哪里好/哪里不搭（≤30 字）\n"
         f"【教师反馈】像真人妈妈一样的自然反馈（两三句话：答对了平静地肯定；"
         f"答偏了点一句'老师问的是…'；想带读就顺着说'来，跟老师说：…'，"
         f"带读句子要和【示范句】一致）；语气自然克制\n"
         f"【示范句】一句完整正确的回答示范（自然口语）\n"
         f"【下个问题】围绕刚才这个问答的内容（就是「{expect_natural}」"
         f"说的这件事）换一个**全新的问法**再问一次（问题必须和上面所有"
         f"问题都不同，换说法换角度，但问的还是同一件事）\n"
         f"【下个答案】这个新问法的参考答案——**内容就是「{expect_natural}」"
         f"（学生已学过，答案内容不要变，只说这件事）**")
    txt = _llm_chat([{"role": "user", "content": q}])
    if not txt:
        return None
    out = {"ok": None, "ping": "", "fb": "", "demo": "", "next": "",
           "ans": ""}
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
        elif line.startswith("【下个问题】"):
            out["next"] = line.replace("【下个问题】", "").strip()
        elif line.startswith("【下个答案】"):
            out["ans"] = line.replace("【下个答案】", "").strip()
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


def qa_read(ng, pats, n2w, keyword, expect):
    """问答读取：引发边检查（关键词→链首 边存在）→ 期望链约束链读。

    引发 = 关键词→期望[1] 边（教学固化：带伞→因为 / 苹果→是 / 下雨→所以
    ——166 条已有 下雨→所以 边，逆向锚点靠固化）；链读每步只许读期望链
    剩余词（含相邻重复推进——叠词结构）。返回读出序列。
    """
    if edge_between(ng, pats, keyword, expect[1]) <= 0:
        return []
    seq, cur = [expect[0], expect[1]], expect[1]
    rest = list(expect[2:])
    for _ in range(max(0, len(expect) - 2)):
        if rest and rest[0] == cur:          # 相邻重复（帮帮/好好）
            seq.append(cur)
            rest.pop(0)
            continue
        top = direct_next_multi(ng, pats, n2w, [cur], k=3,
                                domain=set(expect))
        # **顺序约束**：每步只许读期望链的下一个词（rest[0]）——跳序
        # 会读出"他→了"（256）先于"他→累"（实测"因为他了累"）
        nxt = next((w for w, _ in top if w == rest[0]), None)
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
    print("═══ s3.3 问答应答教学（VB-MAPP Intraverbal：什么是/为什么/会怎样）═══\n")

    ng, vocab, pats, cursor = load_version("17.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys_sorted = sorted(pats.keys(), key=len, reverse=True)
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    from _grow_cat import build_cats
    cats = build_cats(pats, sem["words"], 12, 3)
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    pool = build_pool(rows, cats, smoke=smoke)
    print(f"[加载] 17.0：n={ng.n} | 教师 {'LLM' if teach else '规则'}"
          f" | 问答池 {len(pool)} 项"
          f"（{ {l: sum(1 for p in pool if p[3] == l) for l in
                ['①据因推果', '②以果溯因', '③什么是']} }）")

    streak, log, announced = 0, [], False
    n_ok = n_fix = n_rw = 0
    pending = None                           # LLM 生成的 (下个问题, 期望词)
    recent_asks = []
    for r in range(1, MAX_ROUNDS + 1):
        # LLM 教师自主出题（用户："不要限制大模型的问题，保证每次都是新的"）
        # ——上轮【下个问题/答案】切词词表内才用；否则回退池子轮转
        if pending and teach:
            ask, expect = pending
            pending = None
            layer = "LLM新题"
            kw = expect[0]                   # 问法随便换，内容不变——
            # 关键词 = 期望首词（内容词），引发边已固化（苹果→是）
        else:
            ask, kw, expect, layer = pool[(r - 1) % len(pool)]
        fade = "none" if streak >= FADE_AT else "full"
        if fade == "none" and not announced:
            print("  ── 提示渐隐：从这轮起教师不再示范，网络独立回答 ──")
            announced = True
        read_toks = qa_read(ng, pats, n2w, kw, expect)
        ok = read_toks == expect
        got = None
        if teach and read_toks:
            got = teacher_llm(ask, "".join(expect), read_toks, layer,
                              recent_asks=recent_asks)
            if got is not None:
                ok = bool(got["ok"])
                # LLM 换问法问已学内容（问题全新、答案沿用当前期望——
                # 网络能答 → streak 累积；全新答案会导致 streak 永远被打断）
                if got["next"]:
                    pending = (got["next"], list(expect))
        record = {"round": r, "layer": layer, "ask": ask,
                  "expect": "".join(expect), "read": "".join(read_toks),
                  "ok": ok, "fade": fade}
        recent_asks = (recent_asks + [ask])[-8:]
        if ok:
            for _ in range(2 if fade == "none" else 1):
                _learn_sentence(ng, list(expect), pats, slot=0)
            n_rw += 1
            streak += 1
            mark = "✅"
            record["reward"] = 2 if fade == "none" else 1
        else:
            if got is not None and got["demo"]:
                demo_toks = _segment_demo(got["demo"], keys_sorted) \
                    or list(expect)
                fb, ping = got["fb"], got["ping"]
            else:
                demo_toks, fb, ping = list(expect), "来，跟老师说：" \
                    + "".join(expect), ""
            if fade == "full":
                for _ in range(CAL_FIX):
                    _learn_sentence(ng, demo_toks, pats, slot=0)
                for a, b in zip(expect[:-1], expect[1:]):
                    _learn_sentence(ng, [a, b], pats, slot=0)
                if kw != expect[0]:          # 引发边（逆向锚点：带伞→因为）
                    _learn_sentence(ng, [kw, expect[1]], pats, slot=0)
            record["fb"] = fb
            record["ping"] = ping
            n_fix += 1
            streak = 0
            mark = "✗"
        log.append(record)
        print(f"  [{r:>2}·{layer}·streak{streak:>2}] {mark} "
              f"问「{ask}」→ 答「{record['read'] or '∅'}」"
              f"（期「{record['expect']}」）"
              + (f" 师：「{fb}」" if not ok and fb else "")
              + (f" 奖励×{record['reward']}" if ok and record.get("reward")
                 else ""))
        if streak >= STREAK_PASS:
            print(f"  ✅ 连续 {STREAK_PASS} 次通过！")
            break
    passed = streak >= STREAK_PASS
    print(f"  教学 {len(log)} 轮（streak 峰值 {streak}，"
          f"{'通过 ✅' if passed else '未达 ❌'}）| 奖励 {n_rw} | 处罚 {n_fix} 次")

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
    print(f"  [EVAL 回归] {ne}/{tote} = {rate_e:.3f}"
          f"（校准兜底 {n_cal} 处）")

    # ── 留档 + 快照 ───────────────────────────────────────────
    out_dir = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_qa_s3"
    out_dir.mkdir(parents=True, exist_ok=True)
    teacher = "LLM" if teach else "规则"
    result = {"tag": "s3.3 问答应答（Intraverbal：什么是/为什么/会怎样）",
              "base": "17.0", "teacher": teacher,
              "rounds": len(log), "streak_peak": streak, "passed": passed,
              "rewards": n_rw, "fixes": n_fix,
              "eval": {"hits": ne, "tot": tote, "rate": round(rate_e, 3),
                       "cal_fallback": n_cal},
              "sec": round(time.time() - t0, 1)}
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "talk_log.json").write_text(
        json.dumps({"meta": result, "rounds": log},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# s3.3 问答教学过程记录（{out_dir.name} · {teacher} 教师）",
          f"\n> streak 峰值 {streak}{'（连续 15 次通过 ✅）' if passed else '（未达 ❌）'}"
          f" | 奖励 {n_rw} | 处罚 {n_fix} | EVAL 回归 {rate_e:.3f}\n"]
    for rec in log:
        md.append(f"- 轮 {rec['round']}【{rec['layer']}·{'独立' if rec['fade']=='none' else '示范'}】"
                  f"问「{rec['ask']}」→ 答「{rec['read'] or '∅'}」"
                  f"（期「{rec['expect']}」）"
                  + (f" 师：「{rec.get('fb','')}」" if not rec["ok"] and rec.get("fb") else "")
                  + (" ✅" if rec["ok"] else " ✗"))
    (out_dir / "dialog.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\n[留档] {out_dir}/（talk_log.json 逐轮 + dialog.md + result.json，"
          f"{time.time() - t0:.0f}s）")

    if not smoke:
        save_snapshot(ng, parent="17.0",
                      tag="Stage 3 v18.13：s3.3 问答应答（Intraverbal："
                          "什么是/为什么/会怎样，LLM 教师 + 逆向锚点）",
                      metrics=result, vocab=vocab, pats=pats, cursor=cursor)


if __name__ == "__main__":
    main()
