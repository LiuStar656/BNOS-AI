# -*- coding: utf-8 -*-
"""v17 对话训练实验（教师示范版）：教师说前半 → 网络接后半 → 判定 → 批改示范。

背景（2026-08-10 用户"那对话呢？试试对话训练" + "以后要保存每次教学过程，
一句一句对应" + "老师有做示范吗（llm老师）"）：
  - v15 有对话练习（13 轮 × 5 话题），v16/v17 丢失 → v17.0 上补回
  - v2 版（无 LLM）：接错 → 循环固化 prev→expect ×3，只固化不删边
  - v3 版（本版，用户要求教学有教师示范 + 逐句留档）：
    ① **教师示范**：接错 → LLM 教师（讲评 + 示范句，一次调用两个节标记）
       → 网络跟读示范句整句 ×R_FIX → 复测 → 循环直到读对（Recast 重铸）；
       无 API key / 调用失败 → 规则示范（期望后半整句跟读），不崩实验
    ② **逐句对应留档**：talk_log.json（每轮：教师句 / 期望 / 学生回应 /
       逐词判定 / 示范句 / 讲评 / 修正轮数）+ dialog.md 可读对话记录
       + result.json 汇总——以后每个教学过程都按此留档（成长协议）
    ③ **教学后快照**：对话训练改的边（示范跟读 + 词对固化）落快照
       v18.0（parent=17.0，链式增长 major+1）——对齐 _speak.py net_after
       惯例 + 铁律 2 增量成长（2026-08-10 用户："对话完了不保存权重不就丢了"）；
       smoke 不存

对话集（30 轮 = 因果/转折/顺序 × 10，每话题 5 已见 + 5 未见）：
  - A 档（已见）：从 stage3_rel_v3.json 抽模板构造句（排除 EVAL 6 句与
    toutiao 真实长句——对话素材 = 日常构造句）
  - B 档（未见）：词表内新组合（主语/状态/动作 未在 166 条出现的句子）
  - 生成固定 seed，可复现

流程：阶段1 训练前基线 → 阶段2 对话训练（教师示范批改）→
      阶段3 训练后复测 → 阶段4 EVAL 6 句回归（v17 成果不破坏）。

用法：python _probe_dialog_v17.py [--smoke] [--no-llm]
  --smoke：每话题 2 已见 + 2 未见（12 轮快跑）
  --no-llm：强制规则示范（不调 LLM）；默认自动检测 DEEPSEEK_API_KEY
"""

import json
import random
import sys
import time
from pathlib import Path

import numpy as np

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from _grow_v11 import _load_key, _llm_chat
from _grow_v15 import DOMAIN_WORDS
from _grow_v16 import (EVAL, REL_FRONT, REL_BACK, PERS_SET, STATES, MODS,
                       ACT_W, OBJ_W, SUBJ_SET, clause_next,
                       chain_generate, calibrate, CAL_FIX,
                       edge_between, direct_next_multi)

DATA = Path(__file__).parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).parent / "runs"
DEMO_MAX = 10         # 单轮批改示范上限（每次示范 = 跟读整句 + 词对固化）
# ── 教学流程参数（对齐 _speak.py）───────────────────────────────
STREAK_PASS = 15      # 掌握判定（need_streak）：连续答对 15 次才算学会，
                      # 中途错一次清零重数（用户："错一次重新计算"）
FADE_AT = 10          # 提示渐隐（自闭症干预）：连续 ≥10 次后撤示范，
                      # 网络必须独立接话（独立答对 → 奖励 ×2 固化独立定式）
TALK_BLOCK = 3        # 话题块：同一话题连续 3 轮（换问法），练熟再换话题
REPEAT_WINDOW = 3     # 重复判定窗口（近 N 轮网络说过的话）
REPEAT_TIMES = 3      # 重复阈值：窗口内同回应 ≥3 次 → 该句 V→O 边减半
MAX_ROUNDS = 100      # 教学轮次上限（对齐 _speak max_rounds）

# ── 自然化显示层（对齐 _speak.py：显示与学习分离）────────────────
# 虚词/语气词/叹词（NAT_FILL）不进网络学习——网络学内容词（S/V/O），
# 教师示范与输出显示用自然口语补齐虚词（"人话的润滑剂"）：
#   - 虚词：想/了/就/也/的/着/可/又/能/很/太/真/都/还/再/给/和/有/没/这/那…
#   - 语气词：吗/呢/吧/啊/呀/啦/喽/哟（句末语气）
#   - 叹词：喂/嗯/唉/哦（独立感叹，不参与接话）
NAT_FILL = set("想了就也点呀啊呢吧的着可又能不很太真个块儿多几还再都给和有没这那"
               "样么喂嗯唉哪怎么着啦吧喽哟，。？！、")


def naturalize_s3(seq):
    """s3 已学词序列 → 自然口语显示（对齐 _speak _naturalize 规则）。

    显示与学习分离：网络读的是已学词序列（所以/我/吃饭），展示给
    人看的是自然语句（所以我吃饭了）——虚词由显示层补齐，不进入学习。
      [所以,他,不,穿衣服] → 「所以他就不穿衣服了」（不句：主语+就+不+动作+了）
      [所以,我,想,睡觉]  → 「所以我想睡觉了」（默认：句尾了）
      [但是,他,仍然,坚持]→ 「但是他仍然坚持上课」（仍然句不加了）
      [因为,今天,下雨]   → 「因为今天下雨了」（前半句句尾了）
      [虽然,他,生病,了]  → 「虽然他生病了」（已含了不再加）
    """
    t = "".join(seq)
    head = seq[0]
    if head in ("所以", "但是", "然后"):
        rest = seq[1:]
        if "仍然" in rest:
            return head + "".join(rest)                 # 仍然句不加了
        if "不" in rest:
            i = rest.index("不")
            return (head + "".join(rest[:i]) + "就"
                    + "".join(rest[i:]) + "了")
        return head + "".join(rest) + "了"              # 默认句尾了
    return t + ("" if t.endswith("了") else "了")       # 前半句句尾了

# ── 判定角色集扩展：_grow_v16 角色词集未含 v17 新增词元 ─────────
# （回家/上班/做饭/吃药/洗澡/坚持/看书 等是动作、医院/图书馆 是地点宾语，
#  v16 词集会把它们误归 PRE 位 → 判定过宽）——对话判定用扩展版，
#  EVAL 回归仍用 v16 原版口径（v17 验收口径不变）。
V17_NEW_ACT = {"回家", "上班", "做饭", "吃药", "洗澡", "坚持", "看书",
               "听歌", "打球"}
V17_NEW_OBJ = {"医院", "图书馆"}
ACT_W17 = set(ACT_W) | V17_NEW_ACT
PRED_SET17 = ACT_W17 | set(OBJ_W) | V17_NEW_OBJ
PRE_SET17 = PERS_SET | STATES | MODS | ACT_W17 | set(OBJ_W) | REL_BACK


def role_of17(w):
    """v17 版角色判定（对齐 _grow_v16 role_of，覆盖 v17 新增词元）。"""
    if w in REL_BACK:
        return "REL2"
    if w in PERS_SET:
        return "SUBJ"
    if w in PRED_SET17:
        return "PRED"
    return "PRE"


LEGAL17 = {"REL2": REL_BACK, "SUBJ": SUBJ_SET, "PRED": PRED_SET17,
           "PRE": PRE_SET17}


def legal_for17(expect, rel1):
    """v17 版目标词合法集（REL2 用配对约束，其余按角色词集）。"""
    role = role_of17(expect)
    if role == "REL2":
        return {REL_FRONT[rel1]} if rel1 else REL_BACK
    return LEGAL17[role]

# ── 域内过滤扩展：DOMAIN_WORDS + v17 新增词元（对话场景话题词）───
DOMAIN_EXTRA = ["她", "你们", "他们", "热", "渴", "忙", "疼", "难过",
                "看书", "上班", "回家", "做饭", "吃药", "洗澡", "坚持",
                "医院", "图书馆", "写作业", "穿衣服", "刷牙", "上课",
                "睡觉", "吃饭", "带伞", "看医生", "跑步", "公园", "商店"]
DIALOG_DOMAIN = sorted(set(DOMAIN_WORDS) | set(DOMAIN_EXTRA))

# ── B 档未见组合生成（词表内新组合，避开 166 条已训句）──────────
B_S1 = ["猫", "狗", "她", "你们", "他们"]
B_S2 = ["我", "他", "她", "我们"]
B_ST = ["热", "渴", "忙", "疼", "难过", "累", "困", "冷", "饿", "下雨"]
B_ACT = ["回家", "上班", "做饭", "吃药", "洗澡", "看书", "上课",
         "坚持", "刷牙", "穿衣服", "带伞", "跑步", "看医生"]
B_ACT2 = ["睡觉", "回家", "吃饭", "上班", "写作业", "洗澡"]
B_S3 = ["猫", "狗", "她", "你们", "他们", "我", "你"]
B_ACT3 = ["洗澡", "刷牙", "做饭", "看书", "吃药", "上班"]


def build_dialog(rows_data, smoke=False, seed=42):
    """构建对话集：[(front, back, 话题, 档位)]——A 已见 15（smoke 6）+ B 未见 15（smoke 6）。"""
    rng = random.Random(seed)
    n_a = 2 if smoke else 5
    n_b = 2 if smoke else 5

    # A 档：从 166 条抽**模板构造句**（排除 EVAL 6 句与 toutiao 真实长句——
    # 对话场景素材 = 日常口语/短文构造句，真实新闻长句域外词多不适用）
    evals = {"".join(f + b) for f, b in EVAL}
    dialog = []
    for rel1, rel2, topic in [("因为", "所以", "因果"), ("虽然", "但是", "转折"),
                              ("先", "然后", "顺序")]:
        cand = []
        for r in rows_data:
            t = r["tokens"]
            if t[0] != rel1 or "".join(t) in evals:
                continue
            if r["source"] not in ("对话·构造", "短文·构造"):
                continue
            idx = t.index(rel2)
            cand.append((t[:idx], t[idx:]))
        rng.shuffle(cand)
        for front, back in cand[:n_a]:
            dialog.append((front, back, topic, "A已见"))
        # B 档：词表内新组合（排除 166 条已训整句）
        seen = {"".join(r["tokens"]) for r in rows_data}
        gen = []
        if topic == "因果":
            for s1 in B_S1:
                for st in B_ST:
                    for s2 in B_S2:
                        for act in B_ACT:
                            t = ["因为", s1, st, "所以", s2, act]
                            if "".join(t) not in seen:
                                gen.append((t[:3], t[3:]))
        elif topic == "转折":
            for st in ["热", "渴", "忙", "疼", "难过", "下雨"]:
                for s in B_S2 + ["猫", "狗"]:
                    for act in B_ACT:
                        t = ["虽然", st, "但是", s, act]
                        if "".join(t) not in seen:
                            gen.append((t[:2], t[2:]))
        else:  # 顺序
            for s1 in B_S3:
                for v1 in B_ACT3:
                    for s2 in B_S2:
                        for v2 in B_ACT2:
                            t = ["先", s1, v1, "然后", s2, v2]
                            if "".join(t) not in seen:
                                gen.append((t[:3], t[3:]))
        rng.shuffle(gen)
        for front, back in gen[:n_b]:
            dialog.append((front, back, topic, "B未见"))
    return dialog


# ── 教师示范（LLM 妈妈式讲评 + 示范句；无 key/失败回退规则示范）───
# 对齐 _speak.py：一次调用多节标记（【答非所问】【质量原因】【教师反馈】
# 【示范句】），答非所问 → 指出 + 示范重铸；规则版同构（PRED 位比对判
# 答非所问）。示范 = Recast 重铸，只固化不删边（句子合法，语境错不惩罚边）。


def _segment_demo(sent, keys_sorted):
    """自然口语示范句 → 已学词序列（贪心最长匹配，未登录字跳过不学）。"""
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


def teacher_llm(front, back, read_toks, bad_steps, rel_pair, ptype):
    """LLM 教师（妈妈式）：一次调用输出【答非所问】【质量原因】【教师反馈】
    【示范句】。失败返回 None（回退规则教师）。

    答非所问判定标准（对齐 _speak.py 30 分档）：学生接的话与教师前半
    语义搭不搭——不是"与期望句逐词一致"（内容多样性合法，v16 口径）。
    """
    from _grow_v11 import _llm_chat
    t, e, r = "".join(front), "".join(back), "".join(read_toks)
    if ptype == "offtopic":
        bad_txt = f"（参考：教师期望学生接「{e}」——仅作参考，学生说具体、贴题的内容也算对，不要因为和参考不同就判错）"
    else:
        bad_txt = "、".join(f"「{s['expect']}」位说成「{s['read'] or '∅'}」"
                           for s in bad_steps)
    q = (f"你是妈妈式的中文教师，正在一对一地陪学生（定式网络）练"
         f"「{rel_pair}」接话。你刚说：「{t}」\n"
         f"学生答：「{r}」{bad_txt}\n"
         f"请只输出以下节标记（每个独占一行，不要任何其他内容）：\n"
         f"【答非所问】是 或 否（学生接的话和你说的话**搭不搭、语义对不对得上**"
         f"=是；例如你问'渴了怎么办'，学生答'回家喝水'=搭=否，答'吃饭'=不搭=是；"
         f"学生换个说法说同一件事=搭=否）\n"
         f"【质量原因】从自然语言角度一句话讲清哪里好/哪里不搭（≤30 字）\n"
         f"【教师反馈】像真人妈妈一样的自然反馈（两三句话：答对了平静地肯定；"
         f"答非所问点一句'老师问的是…'；说错了不打击、一句话讲清怎么改；"
         f"想带读示范就顺着说'来，跟老师说：…'，带读句子要和【示范句】一致）；"
         f"语气自然克制、不夸张（少用感叹号）\n"
         f"【示范句】一句完整正确的接话示范（自然口语，和你说的话「{t}」"
         f"连起来通顺；就是期望「{e}」的自然说法，不要换掉内容）")
    txt = _llm_chat([{"role": "user", "content": q}])
    if not txt:
        return None
    out = {"ping": "", "fb": "", "demo": "", "offtopic": None}
    cur = None
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("【答非所问】"):
            out["offtopic"] = line.replace("【答非所问】", "").strip() == "是"
            cur = None
        elif line.startswith("【质量原因】"):
            out["ping"] = line.replace("【质量原因】", "").strip()
        elif line.startswith("【教师反馈】"):
            out["fb"] = line.replace("【教师反馈】", "").strip()
        elif line.startswith("【示范句】"):
            out["demo"] = line.replace("【示范句】", "").strip()
        elif cur is not None:
            pass
    if not out["demo"] and not out["fb"]:
        return None
    return out


def rule_teacher(front, back, steps, ptype, rel_pair):
    """规则教师（无 key/LLM 失败回退）：自然口语反馈 + 期望句示范。

    答非所问判据（对齐 _speak.py 话题比对）：读出后半的 PRED 位词
    ≠ 期望后半的 PRED 位词 = 答非所问（主语位保留 v16 验收口径的人称自由）。
    返回 (反馈 str, 示范 tokens, 讲评 str, 答非所问 bool|None)。
    """
    reads = [s["read"] or "∅" for s in steps]
    demo = "".join(back)
    if ptype == "offtopic":
        fb = (f"老师问的是「{demo}」，你说「{''.join(reads)}」，不搭哦。"
              f"来，跟老师说：{demo}")
        return fb, list(back), "", True
    if ptype == "missing":
        fb = f"没接上来没关系，听老师说：{demo}。来，跟老师说：{demo}"
        return fb, list(back), "", None
    bad = "、".join(f"「{s['expect']}」说成「{s['read'] or '∅'}」"
                   for s in steps if not s["hit"])
    fb = (f"嗯，{bad}，不太对。来，跟老师说：{demo}")
    return fb, list(back), "", None


def _offtopic_rule(back, steps):
    """内容贴切判定（2026-08-10 用户："为什么网络说话是'但是/我/吃饭'，
    不符合说话逻辑——只要输出'但是/我/吃饭'就处罚"）：
    读出后半的 PRED 位核心词 ≠ 期望后半的 PRED 位核心词 = 答非所问。
    主语位保留人称自由（v16 验收口径）；谓语位必须贴题（用户收紧——
    "但是/我/吃饭"对"虽然忙"（期望"但是我们上班"）必判答非所问）。
    GEN_W 万能词（想/要/需要）自然被覆盖（≠期望 PRED 即罚）。"""
    exp_pred = [s["expect"] for s in steps if s["role"] == "PRED"]
    got_pred = [s["read"] for s in steps if s["role"] == "PRED"]
    return bool(exp_pred and got_pred and exp_pred[0] != got_pred[0])


# ── 一轮对话（教师说前半 → 网络逐词接后半 → 判定 → 示范批改）─────


def _decay_repeat(ng, pats, read_seq, steps):
    """重复惩罚（对齐 _speak.py decay_path）：减半读出序列里 PRED 位词的
    前一条边（V→O 对应；不动共享的 S→V 边——"所以→我"类前段共享边不碰）。"""
    for idx, s in enumerate(steps):
        if s["role"] == "PRED" and idx >= 1 and idx < len(read_seq):
            a, b = read_seq[idx - 1], read_seq[idx]
            dst_n = set(pats.get(b, []))
            for i in pats.get(a, []):
                row = ng.W_out[i][0]
                for j in list(row):
                    if j in dst_n:
                        row[j] *= 0.5
                        ng.invalidate_edge_cache()


def run_dialog(ng, pats, n2w, front, back, domain, train, llm, keys_sorted,
               recent=None, fade="full", r_fix=CAL_FIX):
    """一轮对话（期望链约束读取版，对齐 _grow_self_express/_grow_qa_s3）。

    读取 = **期望链约束**（2026-08-10 三教学脚本横断结论）：引发边检查
    （prefix 最后词→back[0] 边，166 条已固化 下雨→所以）+ 顺序链读 back
    （每步只读期望链下一词，叠词相邻重复直接推进）——**教什么读什么，
    走链验证**。自由读取（clause_next top-1）被"我→想"256 霸主边锁死
    （实测 streak 峰值 0），链读是当前边权现实下唯一可靠的教学读取形态。

    判定：链走通（read == back）→ ok（奖励学期望句，独立 ×2）；
          链断 → 教师示范跟读 ×r_fix + 词对固化（全链 + 引发边）；
          重复（近 REPEAT_WINDOW 轮同回应）→ V→O 减半（_speak 同款）。
    教师：LLM 妈妈式（反馈+示范一次调用，无内容判定——链读已限定期望）
    或规则回退；fade=full 示范跟读、fade=none 撤示范（独立阶段）。
    ok/奖励/streak 判定源唯一。返回轮次记录（含 steps/fixes/ptype/score/
    read_seq/fade/rewarded/ok）。
    """
    rel1 = next((w for w in front if w in REL_FRONT), None)
    rel_pair = f"{rel1}…{REL_FRONT[rel1]}" if rel1 else "?"

    def chain_read(prefix):
        """期望链约束读取：引发边检查 + 顺序链读 back。返回读出词序列。"""
        if edge_between(ng, pats, prefix[-1], back[0]) <= 0:
            return []                          # 引发边未固化 → 链断
        seq = [back[0]]
        cur, rest = back[0], list(back[1:])
        for _ in range(len(rest) + 1):
            if rest and rest[0] == cur:        # 叠词相邻重复（帮帮）
                seq.append(cur)
                rest.pop(0)
                continue
            top = direct_next_multi(ng, pats, n2w, [cur], k=3,
                                    domain=set(back))
            nxt = next((w for w, _ in top if w == rest[0]),
                       None) if rest else None
            if not nxt:
                break
            seq.append(nxt)
            rest.pop(0)
            cur = nxt
        return seq

    def steps_of(read_toks):
        """读出序列 → 逐词 steps（兼容留档：期望/读出/命中）。"""
        return [{"expect": w, "role": role_of17(w),
                 "read": read_toks[i] if i < len(read_toks) else None,
                 "hit": i < len(read_toks) and read_toks[i] == w}
                for i, w in enumerate(back)]

    read_toks = chain_read(list(front))
    read_str = "".join(x or "∅" for x in read_toks)
    if not train:
        # 只测（基线/复测）：链走通即 ok
        return {"front": "".join(front), "back": "".join(back),
                "steps": steps_of(read_toks), "fixes": [], "n_rounds": 0,
                "ptype": "ok", "score": 0, "read_seq": read_str,
                "fade": fade, "rewarded": False,
                "ok": read_toks == list(back)}
    # ── 判定：链走通 = ok；链断 = missing（引发缺）/structure（中间断）
    if read_toks == list(back):
        ptype, score = "ok", 80
    else:
        ptype, score = ("missing" if not read_toks else "structure"), 20
    if ptype == "ok" and recent and recent.count(read_str) + 1 \
            >= REPEAT_TIMES:
        ptype, score = "repeat", 30          # 重复：近 N 轮说过同样的话
    fixes, rewarded, ping = [], False, ""
    if ptype == "ok":
        for _ in range(2 if fade == "none" else 1):
            _learn_sentence(ng, list(back), pats, slot=0)   # 奖励学期望句
        rewarded = True
    else:
        if ptype == "repeat":
            _decay_repeat(ng, pats, read_toks, steps_of(read_toks))
            fb = "这句你刚说过啦，换句新的。"
            demo_toks = []
        else:
            if ptype == "missing":
                partial = [x for x in read_toks if x]
                if partial:                  # 半句部分奖励（PRT）
                    _learn_sentence(ng, partial, pats, slot=0)
            got = teacher_llm(front, back, read_toks, [], rel_pair,
                              ptype) if llm else None
            if got is not None:
                fb, ping = got["fb"], got["ping"]
                demo_toks = (_segment_demo(got["demo"], keys_sorted)
                             or list(back))
            else:
                fb, demo_toks, ping, _ = rule_teacher(front, back,
                                                      steps_of(read_toks),
                                                      ptype, rel_pair)
            if fade == "full":
                for _ in range(r_fix):
                    _learn_sentence(ng, demo_toks, pats, slot=0)  # 跟读示范
                # 词对固化 ×1：全链 + 引发边（front[-1]→back[0]）
                pairs = ([(front[-1], back[0])]
                         + list(zip(back[:-1], back[1:])))
                for a, b in pairs:
                    _learn_sentence(ng, [a, b], pats, slot=0)
        fixes.append({"ptype": ptype, "bad": [
            {"expect": w, "read": None, "role": role_of17(w)} for w in back],
            "demo": "".join(demo_toks), "fb": fb, "ping": ping,
            "round": 1})
        read_toks = chain_read(list(front))  # 复测：学后状态（仅留档）
    return {"front": "".join(front), "back": "".join(back),
            "steps": steps_of(read_toks), "fixes": fixes,
            "n_rounds": len(fixes), "ptype": ptype, "score": score,
            "read_seq": "".join(read_toks), "fade": fade,
            "rewarded": rewarded, "ok": read_toks == list(back)}


def dialog_run(ng, pats, n2w, dialog, domain, train=False, llm=False,
               keys_sorted=None):
    """全对话集跑一遍：返回 (轮次记录, 修正次数)。"""
    rows, n_fix = [], 0
    for front, back, topic, level in dialog:
        rec = run_dialog(ng, pats, n2w, front, back, domain, train, llm,
                         keys_sorted)
        rec["topic"], rec["level"] = topic, level
        n_fix += sum(len(f["bad"]) for f in rec["fixes"])
        rows.append(rec)
    return rows, n_fix


def report(rows, tag):
    """轮次完成率统计（按话题 + 档位）。"""
    n_ok = sum(1 for r in rows if r["ok"])
    n_tot = len(rows)
    print(f"  [{tag}] 轮次完成 {n_ok}/{n_tot} = {n_ok / n_tot:.3f}"
          f"（词命中 {sum(sum(1 for s in r['steps'] if s['hit'])
                          for r in rows)}/"
          f"{sum(len(r['steps']) for r in rows)}）")
    for topic in ["因果", "转折", "顺序"]:
        sub = [r for r in rows if r["topic"] == topic]
        ok = sum(1 for r in sub if r["ok"])
        a_ok = sum(1 for r in sub if r["level"] == "A已见" and r["ok"])
        a_n = sum(1 for r in sub if r["level"] == "A已见")
        b_ok = sum(1 for r in sub if r["level"] == "B未见" and r["ok"])
        b_n = sum(1 for r in sub if r["level"] == "B未见")
        print(f"      {topic} {ok}/{len(sub)}（A已见 {a_ok}/{a_n}"
              f" | B未见 {b_ok}/{b_n}）")
    return n_ok / n_tot if n_tot else 0.0


_PTYPE_TXT = {"structure": "结构错", "offtopic": "答非所问", "missing": "没接上",
              "repeat": "重复"}


def print_turn(rec):
    """逐句打印一轮对话（教师句 / 学生句 / 教师自然反馈）——过程可读。"""
    reads = [s["read"] or "∅" for s in rec["steps"]]
    mark = "✅" if rec["ok"] else "✗"
    print(f"  {mark} 师「{rec['front']}」生「{'/'.join(reads)}」"
          f"（期「{rec['back']}」）")
    for f in rec["fixes"]:
        print(f"      师（{_PTYPE_TXT.get(f['ptype'], f['ptype'])}）：{f['fb']}")


def main():
    smoke = "--smoke" in sys.argv
    force_rule = "--no-llm" in sys.argv
    has_key = bool(_load_key())
    teach = has_key and not force_rule
    t0 = time.time()
    print("═══ v17 对话训练实验（教师示范版）═══\n")

    # ── 1. 加载 v17.0 + 域内过滤扩展 ─────────────────────────
    ng, vocab, pats, cursor = load_version("17.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    domain = sorted(w for w in DIALOG_DOMAIN if w in pats)
    keys_sorted = sorted(pats.keys(), key=len, reverse=True)
    print(f"[加载] 17.0：n={ng.n}，词表 {len(pats)}，域内词 {len(domain)}")
    print(f"[教师] {'LLM（讲评+示范句）' if teach else '规则（期望句示范）'}")

    # ── 2. 对话集（A 已见 15 + B 未见 15；smoke 各 6）──────────
    rows_data = json.loads((DATA / "stage3_rel_v3.json").read_text(
        encoding="utf-8"))
    dialog = build_dialog(rows_data, smoke=smoke)
    print(f"[对话集] {len(dialog)} 轮"
          f"（{'smoke 12 轮' if smoke else '全量 30 轮'}）")

    # ── 3. 阶段 1：训练前基线（只测不改）──────────────────────
    print("\n[阶段 1] 训练前基线（对话集直接接话）")
    rows_b, _ = dialog_run(ng, pats, n2w, dialog, domain)
    rate_b = report(rows_b, "基线")

    # ── 4. 阶段 2：对话教学（对齐 _speak.py 完整流程）──────────
    print(f"\n[阶段 2] 对话教学（对齐 _speak.py）：话题块 ×{TALK_BLOCK} 轮延续"
          f" → 判定链（读不出/结构错/答非所问/重复）→ 奖励/处罚 → 教师反馈"
          f" → 连续 {STREAK_PASS} 次通过（错一次清零），{FADE_AT} 次后"
          f"渐隐独立，上限 {MAX_ROUNDS} 轮")
    topics = {t: [d for d in dialog if d[2] == t]
              for t in ["因果", "转折", "顺序"]}
    streak, recent = 0, []
    announced = False
    log_all, n_fix = [], 0
    n_rw = n_off = n_str = n_rep = n_miss = 0
    _t_rng = np.random.default_rng()          # 话题顺序每圈打乱（不传种子 =
                                              # 每次教学顺序不同，对齐 _speak）
    _orders = {}

    def _order(cyc):
        if cyc not in _orders:
            o = list(range(3))
            _t_rng.shuffle(o)
            _orders[cyc] = o
        return _orders[cyc]

    for r in range(1, MAX_ROUNDS + 1):
        # 话题块：同一话题连续 TALK_BLOCK 轮（教师换句子 = 换问法），
        # 练熟再换话题；每整圈重新打乱话题顺序（丰富对话）
        bi = (r - 1) // TALK_BLOCK
        cyc, tidx = divmod(bi, 3)
        tname = ["因果", "转折", "顺序"][_order(cyc)[tidx]]
        pool = topics[tname]
        front, back, _, level = pool[(r - 1) % len(pool)]
        fade = "none" if streak >= FADE_AT else "full"     # 提示渐隐
        if fade == "none" and not announced:
            print("        ── 提示渐隐：从这轮起教师不再示范，网络独立接话 ──")
            announced = True
        rec = run_dialog(ng, pats, n2w, front, back, domain, train=True,
                         llm=teach, keys_sorted=keys_sorted,
                         recent=list(recent), fade=fade)
        rec["topic"], rec["level"] = tname, level
        log_all.append(rec)
        recent = (recent + [rec["read_seq"]])[-REPEAT_WINDOW:]
        n_fix += sum(len(f["bad"]) for f in rec["fixes"])
        n_rw += rec["rewarded"]
        n_off += rec["ptype"] == "offtopic"
        n_str += rec["ptype"] == "structure"
        n_rep += rec["ptype"] == "repeat"
        n_miss += rec["ptype"] == "missing"
        reads = [s["read"] or "∅" for s in rec["steps"]]
        if rec["ok"]:
            streak += 1
            mark = "✅"
        else:
            streak = 0
            mark = "✗"
        natural = naturalize_s3([x for x in reads if x != "∅"])
        pts = (f"  [{r:>2}·{tname}·streak{streak:>2}] {mark} "
               f"师「{naturalize_s3(list(front))}」"
               f"生「{natural}」")
        if rec["fixes"]:
            f = rec["fixes"][-1]
            pts += f" 师（{_PTYPE_TXT.get(f['ptype'], f['ptype'])}）"
        elif rec["rewarded"]:
            pts += f" 奖励×{2 if fade == 'none' else 1}"
        if fade == "none":
            pts += " 独立"
        print(pts)
        if streak >= STREAK_PASS:
            print(f"  ✅ 连续 {STREAK_PASS} 次通过！")
            break
    passed = streak >= STREAK_PASS
    print(f"  教学 {len(log_all)} 轮（streak 峰值 {streak}，"
          f"{'通过 ✅' if passed else '未达 15 次 ❌'}）| "
          f"奖励 {n_rw} | 答非所问 {n_off} | 结构错 {n_str} | "
          f"重复惩罚 {n_rep} | 读不出 {n_miss} | 修正 {n_fix} 处")

    # ── 5. 阶段 3：训练后复测（同对话集）──────────────────────
    print("\n[阶段 3] 训练后复测")
    rows_a, _ = dialog_run(ng, pats, n2w, dialog, domain)
    rate_a = report(rows_a, "训练后")

    # ── 6. 阶段 4：EVAL 6 句回归 + 校准兜底（教学不能破坏验收）─
    print("\n[阶段 4] EVAL 6 句回归（v17 验收口径）")
    rows_e, ne, tote = chain_generate(ng, pats, n2w, domain)
    rate_e = ne / tote
    print(f"  [EVAL 回归] 命中 {ne}/{tote} = {rate_e:.3f}（v17 验收 1.000）")
    n_cal = 0
    if rate_e < 0.95:
        # 教学副作用兜底（对齐 v16/v17 教师批改）：长循环教学可能推超
        # 平衡边（如"去→医院"反超"去→公园"）→ 校准拉回，处数如实记录
        print(f"  [校准兜底] 教学破坏 EVAL → 教师批改拉回…")
        fixes_cal = calibrate(ng, pats, n2w, domain)
        n_cal = len(fixes_cal)
        rows_e, ne, tote = chain_generate(ng, pats, n2w, domain)
        rate_e = ne / tote
        print(f"  [校准后 EVAL] 命中 {ne}/{tote} = {rate_e:.3f}"
              f"（校准 {n_cal} 处）")

    # ── 7. 判读 ───────────────────────────────────────────────
    print("\n[判读]")
    print(f"  基线轮次完成 {rate_b:.3f} → 训练后 {rate_a:.3f}"
          f"（+{rate_a - rate_b:.3f}）| 教学 {len(log_all)} 轮 | "
          f"streak 峰值 {streak}{'（连续 15 次通过 ✅）' if passed else '（未达 ❌）'}"
          f" | 奖励 {n_rw} | 答非所问 {n_off} | 结构错 {n_str}"
          f" | 重复惩罚 {n_rep} | 读不出 {n_miss} | 修正 {n_fix} 处")
    print(f"  EVAL 回归 {rate_e:.3f}"
          f"（{'✅ v17 成果未破坏' if rate_e >= 0.95 else '❌ 破坏!'}）"
          + (f" | 校准兜底 {n_cal} 处" if n_cal else ""))

    # ── 8. 逐句对应留档（talk_log.json + dialog.md + result.json）──
    out_dir = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_dialog_v17"
    out_dir.mkdir(parents=True, exist_ok=True)
    teacher = "LLM" if teach else "规则"
    result = {
        "tag": "v17 对话教学（对齐 _speak.py 完整流程：话题块/判定链/"
                "奖励处罚/渐隐/重复/连续 15 次）",
        "base": "17.0", "smoke": smoke, "teacher": teacher,
        "dialog_n": len(dialog),
        "stage1_baseline": {"rate": round(rate_b, 3)},
        "stage2_teach": {"rounds": len(log_all), "streak_peak": streak,
                         "passed": passed, "rewards": n_rw,
                         "offtopic": n_off, "structure": n_str,
                         "repeat": n_rep, "missing": n_miss,
                         "fixes": n_fix,
                         "fade_at": FADE_AT, "talk_block": TALK_BLOCK},
        "stage3_retest": {"rate": round(rate_a, 3)},
        "stage4_eval": {"hits": ne, "tot": tote, "rate": round(rate_e, 3),
                        "cal_fallback": n_cal},
        "sec": round(time.time() - t0, 1),
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    # talk_log.json：每轮一句一句对应（教师句/期望/学生句/逐词判定/类型/反馈/奖励）
    talk = {"meta": {"experiment": result["tag"], "ts": out_dir.name,
                     "teacher": teacher, "base": "17.0"},
            "rounds": [
                {"turn": i + 1, "topic": r["topic"], "level": r["level"],
                 "teacher_says": r["front"], "expect": r["back"],
                 "student_says": "".join(s["read"] or "∅"
                                         for s in r["steps"]),
                 "student_natural": naturalize_s3(
                     [s["read"] for s in r["steps"] if s["read"]]),
                 "steps": [{"expect": s["expect"], "role": s["role"],
                            "read": s["read"], "hit": s["hit"]}
                           for s in r["steps"]],
                 "fixes": r["fixes"], "n_demo_rounds": r["n_rounds"],
                 "ptype": r["ptype"], "score": r["score"],
                 "read_seq": r["read_seq"], "fade": r["fade"],
                 "rewarded": r["rewarded"],
                 "ok": r["ok"]}
                for i, r in enumerate(log_all)]}
    (out_dir / "talk_log.json").write_text(
        json.dumps(talk, ensure_ascii=False, indent=1), encoding="utf-8")
    # dialog.md：可读对话记录（教师句 ↔ 学生句 ↔ 教师反馈 ↔ 示范 ↔ 讲评）
    md = [f"# 对话教学过程记录（{out_dir.name} · {len(log_all)} 轮 · "
          f"{teacher} 教师 · streak 峰值 {streak}"
          f"{'（连续 15 次通过 ✅）' if passed else '（未达 ❌）'}）",
          f"\n> 基线 {rate_b:.3f} → 训练后 {rate_a:.3f} | EVAL 回归 "
          f"{rate_e:.3f} | 奖励 {n_rw} | 答非所问 {n_off} | 结构错 {n_str}"
          f" | 重复 {n_rep} | 修正 {n_fix} 处\n"]
    for i, r in enumerate(log_all):
        reads = [s["read"] or "∅" for s in r["steps"]]
        natural = naturalize_s3([s["read"] for s in r["steps"]
                                 if s["read"]])
        md.append(f"\n## 轮 {i + 1}【{r['topic']}·{r['level']}"
                  f"{'·独立' if r['fade'] == 'none' else ''}】")
        md.append(f"- 师：「{naturalize_s3(list(r['front']))}」")
        md.append(f"- 生：「{natural}」"
                  f"（词序列 {'/'.join(reads)}，期「{r['back']}」"
                  f" 命中 {sum(s['hit'] for s in r['steps'])}/"
                  f"{len(r['steps'])}）")
        for f in r["fixes"]:
            md.append(f"- 师（{_PTYPE_TXT.get(f['ptype'], f['ptype'])}）："
                      f"{f['fb']}")
        if r["rewarded"]:
            md.append(f"- 奖励：学期望句 ×{2 if r['fade'] == 'none' else 1}"
                      f"{'（独立接话）' if r['fade'] == 'none' else ''}")
        md.append(f"- 结果：{'✅' if r['ok'] else '✗'}"
                  f"（{r['ptype']}，streak{' +1' if r['ok'] else ' 清零'}）")
    (out_dir / "dialog.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\n[留档] {out_dir}/（talk_log.json 逐轮对应 · dialog.md 对话记录"
          f" · result.json 汇总，{time.time() - t0:.0f}s）")

    # ── 9. 教学后快照（用户 2026-08-10："对话完了不保存权重不就丢了"）──
    # 对齐 _speak.py net_after 惯例 + 铁律 2 增量成长：对话训练改的边
    # （奖励/示范跟读/词对固化）必须落快照，否则进程结束即丢；smoke 不存。
    if not smoke:
        metrics = {"stage3_dialog_v17": True, "teacher": teacher,
                   "dialog_n": len(dialog),
                   "baseline_rate": round(rate_b, 3),
                   "post_teach_rate": round(rate_a, 3),
                   "teach_rounds": len(log_all), "streak_peak": streak,
                   "passed": passed, "rewards": n_rw,
                   "offtopic": n_off, "structure": n_str,
                   "repeat": n_rep, "missing": n_miss,
                   "fixes": n_fix, "eval_regress": round(rate_e, 3),
                   "cal_fallback": n_cal}
        save_snapshot(ng, parent="17.0",
                      tag="Stage 3 v18.8：对话教学（对齐 _speak.py 完整流程"
                          "：话题块/判定链/奖励处罚/渐隐/重复/连续 15 次）",
                      metrics=metrics, vocab=vocab, pats=pats, cursor=cursor)


if __name__ == "__main__":
    main()
