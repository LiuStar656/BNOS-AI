# -*- coding: utf-8 -*-
"""早教自我表达教学（v2.18 方案落地）：情境引发 → 网络表达 → LLM 教师批改。

网络 = 自闭症类比（v2.18 沉淀，用户 2026-08-10："从网络的角度出发，网络
只能听和说，类似自闭症阶段"）——述情障碍：有内感受边（X→痛，v13 体验式）
但说不出"我疼"。教学链：感知（v13 已有）→ 行为（v13 已有：疼→不要）→
**表达（本脚本）→ 社交**。

五层（v2.18 方案）：
  层1 命名（Tact）：感受词复述（跟读，Echoic 已会）
  层2 内感受→表达绑定：情境 → "我+状态词"（疼/饿/渴/累/冷/热/难过/开心/
      害怕/生气 × 情境池）
  层3 FCT 扩展：求助（"我疼，帮帮我"）+ 需求（"我要喝水/吃饭/回家/睡觉"）
  层4 自发发起（Mand 完整版）：无情境提示，读到状态词 → 主动"我疼"——
      验收 = 层2 跟读固化的 我→状态词 边（无提示读得出）
  层5 感受+原因：接 s3 因果（"我难过，因为下雨"）

读取机制：情境关键词注入 → 出边读状态词（石头→疼，v13 边）→ 表达 =
固定主语"我" + 状态词（自我表达语用规则，非学出来的）；跟读固化
"我→状态词"边（层4 自发用）+ 全链（层3/5）。

LLM 教师一次调用（对齐 _speak 压缩模式）：【表达判定】【质量原因】
【教师反馈】【示范句】【下个情境】——情境创设/判定/示范/讲评/接纳一体；
无 key/失败回退规则（模板情境 + 期望句示范）。教学流程：情境 → 表达 →
判定（规则 + LLM 贴切度）→ 奖励（学期望句，独立 ×2）/处罚（示范跟读 ×3
+ 词对固化 ×1）→ streak 15 通过（错一次清零）。

用法：python _grow_self_express.py [--smoke] [--no-llm]
"""

import json
import random
import sys
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from _grow_v11 import _load_key, _llm_chat
from _grow_v16 import clause_next, EVAL, chain_generate, calibrate, CAL_FIX

DATA = Path(__file__).parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).parent / "runs"
STREAK_PASS = 15
FADE_AT = 10          # 提示渐隐：连续 ≥10 次后撤示范（独立表达奖励 ×2）
MAX_ROUNDS = 120

# ── 状态词 → 情境池 + 期望表达（全词表内，已查证）───────────────
# 情境 = (教师说的话, 读路径关键词) —— 关键词出边引导状态词（石头→疼 为
# v13 内感受边）；层4 自发 = 无情境，直接注入状态词验收。
STATES = {
    "疼": {"situ": [("你碰了石头", "石头"), ("你摔了一跤", "摔")],
           "expr": ["我", "疼"]},
    "饿": {"situ": [("一天没吃饭", "吃饭"), ("早饭没吃", "吃饭")],
           "expr": ["我", "饿"]},
    "渴": {"situ": [("走了很远的路", "回家"), ("太阳晒了很久", "水")],
           "expr": ["我", "渴"]},
    "累": {"situ": [("跑了一整天", "跑步"), ("搬了很多东西", "上班")],
           "expr": ["我", "累"]},
    "冷": {"situ": [("外面下雪了", "冷"), ("冬天到了", "冷")],
           "expr": ["我", "冷"]},
    "热": {"situ": [("太阳很大", "热"), ("夏天到了", "热")],
           "expr": ["我", "热"]},
    "难过": {"situ": [("玩具被抢走了", "玩具"), ("好朋友走了", "难过")],
             "expr": ["我", "难过"]},
    "开心": {"situ": [("妈妈回来了", "妈妈"), ("今天是我的生日", "生日")],
             "expr": ["我", "开心"]},
    "害怕": {"situ": [("晚上一个人在家", "晚上"), ("打雷了", "害怕")],
             "expr": ["我", "害怕"]},
    "生气": {"situ": [("玩具坏了", "坏"), ("别人不守规矩", "生气")],
             "expr": ["我", "生气"]},
}

# ── 层3 FCT / 层5 感受+原因（词表内，已查证）────────────────────
FCT_ITEMS = [
    ("我疼，帮帮我", ["我", "疼", "帮", "帮", "我"], "疼", "求助"),
    ("帮帮我", ["帮", "帮", "我"], "疼", "求助"),
    ("我要喝水", ["我", "要", "喝", "水"], "渴", "需求"),
    ("我要吃饭", ["我", "要", "吃", "饭"], "饿", "需求"),
    ("我要回家", ["我", "要", "回", "家"], "累", "需求"),
    ("我要睡觉", ["我", "要", "睡觉"], "累", "需求"),
]
CAUSE_ITEMS = [
    ("我难过，因为下雨", ["我", "难过", "因为", "下雨"], "难过"),
    ("我开心，因为今天是我的生日", ["我", "开心", "因为", "今天", "是",
                                    "我", "的", "生日"], "开心"),
    ("我害怕，因为晚上", ["我", "害怕", "因为", "晚上"], "害怕"),
]


def teacher_llm(situ, expr_natural, read_toks, state):
    """LLM 教师一次调用：表达判定 + 原因 + 反馈 + 示范 + 下个情境。"""
    q = (f"你是妈妈式的中文教师，正在陪学生（定式网络）练习表达自己的感受。"
         f"你给了它一个情境：「{situ}」\n"
         f"学生表达：「{''.join(x or '∅' for x in read_toks)}」"
         f"（参考：这个情境下学生应该说「{expr_natural}」这类话）\n"
         f"请只输出以下节标记（每个独占一行，不要任何其他内容）：\n"
         f"【表达判定】是 或 否（学生表达和情境贴不贴：碰了石头很疼→'我疼'=是，"
         f"'我开心'=否；换个说法说同一件事=是）\n"
         f"【质量原因】从自然语言角度一句话讲清哪里好/哪里不贴（≤30 字）\n"
         f"【教师反馈】像真人妈妈一样的自然反馈（两三句话：表达对了平静地肯定；"
         f"不贴就点一句'你是碰了石头呀，应该说什么呢'；想带读就顺着说"
         f"'来，跟老师说：…'，带读句子要和【示范句】一致）；语气自然克制\n"
         f"【示范句】一句完整正确的表达示范（自然口语，就是这个情境下该说的话）\n"
         f"【下个情境】围绕「{state}」这个感受再给一个自然情境（一句话，"
         f"别重复刚说过的）")
    txt = _llm_chat([{"role": "user", "content": q}])
    if not txt:
        return None
    out = {"ok": None, "ping": "", "fb": "", "demo": "", "next": ""}
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("【表达判定】"):
            out["ok"] = line.replace("【表达判定】", "").strip() == "是"
        elif line.startswith("【质量原因】"):
            out["ping"] = line.replace("【质量原因】", "").strip()
        elif line.startswith("【教师反馈】"):
            out["fb"] = line.replace("【教师反馈】", "").strip()
        elif line.startswith("【示范句】"):
            out["demo"] = line.replace("【示范句】", "").strip()
        elif line.startswith("【下个情境】"):
            out["next"] = line.replace("【下个情境】", "").strip()
    if out["ok"] is None and not out["demo"]:
        return None
    return out


def _segment_demo(sent, keys_sorted):
    """自然口语示范句 → 已学词序列（贪心最长匹配，未登录字跳过）。"""
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


# ── 自我表达域（域内过滤：读关键词出边时只保留状态词——散文霸主边
#    "石头→的/我 256" 碾压 v13 "石头→疼"，v15 域内过滤哲学）────────
STATE_SET = set(STATES.keys())
# 注意：域必须含 表达链终点"我"（帮→我）、v16 状态词"下雨/生病"
# （层5"因为下雨"）与 FCT 宾语"饭"（我要吃饭：吃→饭 被滤会断）——
# 漏网即读错（实测：帮→我 被滤后读出"帮吃"；我要吃饭 断在 吃→饭）
EXPR_DOMAIN = STATE_SET | {"帮", "要", "因为", "喝", "吃", "回", "睡",
                           "水", "饭", "我", "下雨", "生病"}


def express_read(ng, pats, n2w, keyword, expect):
    """网络表达：情境引发确定状态词 → 固定主语"我" + 链读（上限=期望长）。

    ① 情境引发：关键词出边 + 自我表达域过滤 → 状态词（"石头→疼" v13
       内感受边 + 教学固化，域内胜出；散文边被过滤）
    ② 表达 = "我" + 状态词（自我表达语用规则）——**不经"我"出边竞争**
       （"我→热→水"散文强边会锁死链读，实测教训）
    ③ 链读：从状态词继续逐词读期望链（疼→帮→帮→我 / 难过→因为→下雨，
       跟读固化的相邻边；上限 = 期望长度——层2 期望 2 词读到 [我,疼] 停，
       "热→水"（热水 256）不会越界）
    ④ 层4 自发（keyword ∈ 状态词集）：跳过情境引发，状态词直接激活——
       = 层2 跟读固化成果（我→状态词 边），无提示自发组织。
    返回 (读出序列, 引发词)。
    """
    from _grow_v16 import direct_next_multi
    if keyword in STATE_SET and expect[1] in STATE_SET:
        state = keyword                     # 层2/层5：状态词直接激活
    else:
        # 层3/情境引发：关键词出边域内读链首词（渴→要 / 石头→疼 /
        # 疼→帮——教学固化的引发边，散文边被域内过滤）；
        # 排除"我"（"晚上→我"256 强边会越界——"我"只作表达起点/终点）
        top = direct_next_multi(ng, pats, n2w, [keyword], k=8,
                                domain=EXPR_DOMAIN)
        state = next((w for w, _ in top if w != "我"), None)
        if not state:
            return [], None
    seq = [expect[0], state]               # 表达起点 = 期望链首词（"我疼"的
    # "我" / "帮帮我"的"帮"——祈使句无主语"我"开头）
    cur = state
    rest = list(expect[2:])                # 期望链剩余词（链读严格约束在
    # 期望链内 = 教学成果验证：每步只许读期望链的词——"因为→我"256 类
    # 域内强边不会越界（实测："我"入域后 因为→我 压过 因为→下雨）
    for _ in range(max(0, len(expect) - 2)):
        # 期望链相邻重复（帮帮=叠词结构，direct_next_multi 全局排除自环
        # w==src 读不出）→ 直接推进（重叠 = 帮+帮我，幼儿口语叠词）
        if rest and rest[0] == cur:
            seq.append(cur)
            rest.pop(0)
            continue
        top = direct_next_multi(ng, pats, n2w, [cur], k=8, domain=EXPR_DOMAIN)
        # **顺序约束**：每步只许读期望链下一个词（rest[0]）——跳序会
        # 读出散文强边先于期望词（实测"他→了"256 先于"他→累"）
        nxt = next((w for w, _ in top if w == rest[0]), None)
        if not nxt:
            break
        seq.append(nxt)
        rest.pop(0)
        cur = nxt
    return seq, state


def main():
    smoke = "--smoke" in sys.argv
    force_rule = "--no-llm" in sys.argv
    teach = bool(_load_key()) and not force_rule
    t0 = time.time()
    print("═══ 早教自我表达教学（网络=自闭症类比：述情障碍→表达）═══\n")

    ng, vocab, pats, cursor = load_version("17.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys_sorted = sorted(pats.keys(), key=len, reverse=True)
    print(f"[加载] 17.0：n={ng.n}，词表 {len(pats)} | "
          f"教师 {'LLM' if teach else '规则'}")

    # ── 教学素材（层2 状态词 + 层3 FCT + 层5 因果；smoke 减半）──
    pool = []                              # (情境, 关键词, 期望, 层, 状态)
    for st, d in STATES.items():
        for situ, kw in d["situ"][: (1 if smoke else 2)]:
            pool.append((situ, kw, d["expr"], "层2感受", st))
    for name, expr, st, kind in FCT_ITEMS[:(3 if smoke else len(FCT_ITEMS))]:
        pool.append((name, st, expr, "层3FCT", st))
    for name, expr, st in CAUSE_ITEMS[:(1 if smoke else len(CAUSE_ITEMS))]:
        pool.append((name, st, expr, "层5因果", st))
    print(f"[素材] {len(pool)} 项（层2 感受 {sum(1 for p in pool if p[3]=='层2感受')}"
          f" / 层3 FCT {sum(1 for p in pool if p[3]=='层3FCT')}"
          f" / 层5 因果 {sum(1 for p in pool if p[3]=='层5因果')}）")

    streak, recent, log = 0, [], []
    announced = False
    n_ok = n_fix = n_rw = 0
    for r in range(1, MAX_ROUNDS + 1):
        situ, kw, expect, layer, st = pool[(r - 1) % len(pool)]
        fade = "none" if streak >= FADE_AT else "full"
        if fade == "none" and not announced:
            print("  ── 提示渐隐：从这轮起教师不再示范，网络独立表达 ──")
            announced = True
        # 网络表达：情境关键词出边 → 我+状态词
        read_toks, state = express_read(ng, pats, n2w, kw, expect)
        ok = (read_toks == expect and state == expect[1])
        got = None
        if teach and state:
            got = teacher_llm(situ, "".join(expect), read_toks, st)
            if got is not None:
                ok = bool(got["ok"])
        record = {"round": r, "layer": layer, "situ": situ,
                  "expect": "".join(expect), "read": "".join(read_toks),
                  "ok": ok, "fade": fade, "state": st}
        if ok:
            # 奖励：学期望句（独立 ×2——渐隐后自发表达固化）
            for _ in range(2 if fade == "none" else 1):
                _learn_sentence(ng, list(expect), pats, slot=0)
            n_rw += 1
            streak += 1
            mark = "✅"
            record["reward"] = 2 if fade == "none" else 1
        else:
            # 处罚：教师示范跟读 ×3 + 词对固化 ×1；渐隐期只反馈
            if got is not None and got["demo"]:
                demo_toks = _segment_demo(got["demo"], keys_sorted) \
                    or list(expect)
                fb, ping = got["fb"], got["ping"]
                record["demo"] = got["demo"]
            else:
                demo_toks, fb, ping = list(expect), "来，跟老师说：" \
                    + "".join(expect), ""
            if fade == "full":
                for _ in range(CAL_FIX):
                    _learn_sentence(ng, demo_toks, pats, slot=0)
                # 词对固化：期望链相邻对 + 情境引发边（关键词→链首词——
                # 幼儿情境词-感受词绑定同理；层3/5 的引发词=状态词本身
                # （疼→帮 / 渴→要 / 难过→因为 也要固化才能链读下去）
                for a, b in zip(expect[:-1], expect[1:]):
                    _learn_sentence(ng, [a, b], pats, slot=0)
                if expect[1] in EXPR_DOMAIN:
                    _learn_sentence(ng, [kw, expect[1]], pats, slot=0)
            record["fb"] = fb
            record["ping"] = ping
            n_fix += 1
            streak = 0
            mark = "✗"
        recent = (recent + [record["read"]])[-3:]
        log.append(record)
        print(f"  [{r:>2}·{layer}·streak{streak:>2}] {mark} "
              f"情境「{situ}」→ 表达「{record['read'] or '∅'}」"
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

    # ── 层4 自发验收：无情境提示，注入状态词 → 主动表达 ────────
    print("\n[层4 自发发起验收]（无情境，读到状态词 → 主动表达）")
    n_self, n_self_tot = 0, 0
    for st, d in STATES.items():
        read_toks, state = express_read(ng, pats, n2w, st, d["expr"])
        hit = read_toks == d["expr"]
        n_self += hit
        n_self_tot += 1
        print(f"  {'✅' if hit else '✗'} 注入「{st}」→ 自发「{read_toks or '∅'}」"
              f"（期「{''.join(d['expr'])}」）")
    rate_self = n_self / n_self_tot

    # ── EVAL 回归（v17 成果不破坏）+ 校准兜底 ─────────────────
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
    out_dir = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_self_express"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"tag": "早教自我表达（网络=自闭症类比，LLM 教师）",
              "base": "17.0", "teacher": "LLM" if teach else "规则",
              "rounds": len(log), "streak_peak": streak, "passed": passed,
              "rewards": n_rw, "fixes": n_fix,
              "self_initiate": {"hits": n_self, "tot": n_self_tot,
                                "rate": round(rate_self, 3)},
              "eval": {"hits": ne, "tot": tote, "rate": round(rate_e, 3),
                       "cal_fallback": n_cal},
              "sec": round(time.time() - t0, 1)}
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "talk_log.json").write_text(
        json.dumps({"meta": result, "rounds": log},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    teacher = "LLM" if teach else "规则"
    md = [f"# 早教自我表达教学过程记录（{out_dir.name} · {teacher} 教师）",
          f"\n> streak 峰值 {streak}{'（连续 15 次通过 ✅）' if passed else '（未达 ❌）'}"
          f" | 奖励 {n_rw} | 处罚 {n_fix} | 自发发起 {n_self}/{n_self_tot}"
          f" | EVAL 回归 {rate_e:.3f}\n"]
    for rec in log:
        md.append(f"- 轮 {rec['round']}【{rec['layer']}·{'独立' if rec['fade']=='none' else '示范'}】"
                  f"情境「{rec['situ']}」→ 生「{rec['read'] or '∅'}」"
                  f"（期「{rec['expect']}」）"
                  + (f" 师：「{rec.get('fb','')}」" if not rec["ok"] and rec.get("fb") else "")
                  + (" ✅" if rec["ok"] else " ✗"))
    (out_dir / "dialog.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\n[留档] {out_dir}/（talk_log.json 逐轮 + dialog.md + result.json，"
          f"{time.time() - t0:.0f}s）")

    if not smoke:
        save_snapshot(ng, parent="17.0",
                      tag="Stage 3 v18.9：早教自我表达（网络=自闭症类比，"
                          "情境引发 + LLM 教师 + 自发发起验收）",
                      metrics=result, vocab=vocab, pats=pats, cursor=cursor)


if __name__ == "__main__":
    main()
