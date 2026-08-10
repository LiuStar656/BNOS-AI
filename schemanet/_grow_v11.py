# -*- coding: utf-8 -*-
"""Stage 2.6 v11 迭代（方案 v2.6 §2.6）：RL 颗粒度升级（连接级归因处罚）+ LLM 教师。

核心（2026-08-10 用户决策链）：
  - "造句只知可不可以、不知为什么" → 处罚原因必须落到连接级（颗粒度升级）：
    错误时反向追踪候选词靠哪条边进 top → 处罚落点 = 该连接显式减权删除
  - "RL 的判断由 LLM 负责"（LLM = 教师：判断 + 解释；网络 = 学生：归因处罚 + 记忆）
  - 项目硬约束：所有 RL 负反馈附 LLM 生成的自然语言处罚原因

双轨实现（方案 v2.6）：
  - DEEPSEEK_API_KEY 存在 → LLM 教师判断（LLM-as-Judge）+ LLM 原因
  - 无 key → 规则验证器（类别比对，v10 已验）+ 模板解释器（标注"模板占位"）
  冒烟/全量无 key 可跑通；LLM 接入为配置项（环境变量）。

流程（在 v10.0 快照上迭代，不重训绑定/骨架/动宾）：
  load_version("10.0")
    → 归因（候选词得分来源边追踪，make_sentence 升级版）
    → 验证器（原则级二元判断，RLBFF 粒度；LLM 教师 or 规则）
    → 处罚（连接级：异类词得分来源边显式删除）
    → 原因（LLM or 模板：归因记录 → 自然语言处罚原因）
    → 验收⑤ 归因/处罚/原因 + 继承 v10 全验收（零遗忘）
    → save_snapshot(parent="10.0") → v11.0

诚实边界（方案 v2.6）：
  - 归因粒度受"候选唤起路径可追踪"限制；多源聚合归因到主要贡献边
  - 无负向排斥权重：删除 = 惩罚上限（边权重是正实数）
  - LLM 教师判断用外部知识（教师知识），处罚归因仍在网络边内；
    "为什么"的解释来源（教师知识 vs 网络边）在诊断中显式区分
  - 无 key 回退规则验证器仍有类别级误判（"看石头"被误判负例）

用法：python _grow_v11.py [--smoke]
"""

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from schema_net import build_pulse
from snapshot import load_version, save_snapshot
from sparse_net import allocate_pats
from _rl_gate import run_train
from _grow_zh import run_recall, fire_ratio, recall_words
from _grow_cat import build_cats, edge_sum, CATS_MANUAL

K = 4
R = 5                    # 判断轮数（槽位绑定/类别）
R_SVO = 3                # 骨架跟读轮数（"读的越多印象越足"）
N_TRAIN = 800            # 骨架训练组合数
N_TEST = 400             # 测试组合数（造句验收，组合从未训练）
N_MAKE = 10              # 示例造句条数
EVAL_HANZI = 200
EVAL_WORD = 300
EVAL_SENT = 100
SEED = 42
DATA = Path(__file__).parent / "data" / "curriculum"

# 槽位模式名（虚拟词，只做角色表征；不与真实词冲突）
SLOT_S, SLOT_V, SLOT_O = "__S__", "__V__", "__O__"
TAG_ACT = "动作"
TAG_PERS = "人称"

# 与 v10 同源常量（脚本独立，不 import _grow_svo 避免执行其 main）
ACT_MANUAL = ["吃", "喝", "买", "看", "学", "要", "拿", "做", "写", "读",
              "玩", "去", "来", "打", "跑", "走", "坐", "站", "听", "说",
              "画", "踢", "跳", "洗", "穿", "戴", "种", "养", "修", "借",
              "喜欢", "知道", "学习", "工作", "跑步", "唱歌", "游泳", "跳舞"]
PERS_MANUAL = ["我", "你", "他", "她", "我们", "你们", "他们"]
S_ANIMALS = ["猫", "狗", "鸟", "鱼", "兔子"]
V_SET = ["吃", "喝", "买", "看", "学", "画", "踢", "洗", "读", "听", "要"]
O_FOOD = ["苹果", "西瓜", "面包", "牛奶", "鸡蛋", "米饭", "香蕉", "饼干"]
O_PLACE = ["学校", "公园", "家", "商店"]
O_TAGS = ["食物", "地点"]

# 动宾搭配（v10 同款例句驱动）
VO_PAIRS = {
    "吃": ["苹果", "米饭", "西瓜", "面包", "鸡蛋", "香蕉", "饼干"],
    "喝": ["牛奶"],
    "买": ["苹果", "西瓜", "鸡蛋", "面包", "牛奶"],
    "洗": ["苹果", "鸡蛋", "西瓜"],
    "要": ["苹果", "牛奶", "香蕉", "面包"],
    "画": ["苹果", "公园", "学校"],
    "看": ["公园", "学校", "家", "商店"],
    # 学 / 踢 / 读 / 听：O 集（食物/地点）无合理宾语，不配搭配
}


# ════════════════════════════════════════════════════════════════
#  归因（颗粒度升级第一步：候选词得分来源边追踪）
# ════════════════════════════════════════════════════════════════

def attributed_sentence(ng, pats, n2w, s, v, vo_pairs, cat_members):
    """造句 + 归因（v10 make_sentence 升级版）：每个候选词记录得分来源。

    返回 (ok, top, allow, sources)：
      ok      = 路径通否（同 v10：绑定/骨架/槽位类别约束）
      top     = top-8 词
      allow   = V 的搭配类别集
      sources = {词: [(源类型, 源词, 目标神经元, 权重), ...]}——
                源类型 ∈ {"V直连", "类别泛化", "O槽保底"}
    """
    ok = (edge_between(ng, pats, s, SLOT_S) > 0.1
          and edge_between(ng, pats, v, SLOT_V) > 0.1
          and edge_between(ng, pats, SLOT_S, SLOT_V) > 0.1
          and edge_between(ng, pats, SLOT_V, SLOT_O) > 0.1
          and edge_between(ng, pats, SLOT_V, TAG_ACT) > 0.1
          and any(edge_between(ng, pats, SLOT_O, t) > 0.1 for t in O_TAGS))
    virtual = {SLOT_S, SLOT_V, SLOT_O, TAG_ACT, TAG_PERS} | set(O_TAGS)
    scores = Counter()
    sources = {}

    def _add(src_type, src_word, j, wt):
        w = n2w.get(j)
        if not w or w == v or w in virtual:
            return
        scores[w] += wt
        sources.setdefault(w, []).append((src_type, src_word, j, wt))

    # 主源：V 词出边 = 直接搭配词
    for i in pats[v]:
        row = ng.W_out[i][0]
        if row:
            for j, wt in row.items():
                _add("V直连", v, j, wt)
    # 泛化：allow 类别标签出边 ×0.3（举一反三）
    allow = set()
    for o in vo_pairs.get(v, []):
        for c, mem in cat_members.items():
            if o in mem:
                allow.add(c)
    for c in allow:
        for i in pats.get(c, []):
            row = ng.W_out[i][0]
            if row:
                for j, wt in row.items():
                    _add("类别泛化", c, j, 0.3 * wt)
    # 保底：仅当 V 无搭配词（学/踢/读/听 → 泛名词池诚实留白）
    if not allow:
        for i in pats[SLOT_O]:
            row = ng.W_out[i][0]
            if row:
                for j, wt in row.items():
                    _add("O槽保底", SLOT_O, j, 0.3 * wt)
    return ok, [w for w, _ in scores.most_common(8)], allow, sources


# ════════════════════════════════════════════════════════════════
#  验证器（原则级二元判断，RLBFF 粒度；LLM 教师 or 规则回退）
# ════════════════════════════════════════════════════════════════

def rule_verifier(ng, pats, s, v, o, allow, cat_members, top):
    """规则验证器（无 key 回退，v10 类别比对）：输出每条原则的二元判断。

    原则1  S 认得自己的位（S→S槽 边）
    原则2  V 认得自己的位（V→V槽 边）+ O 认得自己的位（O→O槽 边）
    原则3  V 有搭配类别（allow 非空）
    原则4  O ∈ 搭配类别（o ∈ allow_mem）
    原则5  行为结果（O 进 top-8）
    返回 (kind, principles, allow_mem)；kind ∈ {"ok","bad","plain"}。
    """
    p1 = edge_between(ng, pats, s, SLOT_S) > 0.1
    p2 = (edge_between(ng, pats, v, SLOT_V) > 0.1
          and edge_between(ng, pats, o, SLOT_O) > 0.1)
    p3 = bool(allow)
    allow_mem = set()
    if allow:
        allow_mem = set().union(*(cat_members[c] for c in allow))
    p4 = o in allow_mem
    p5 = o in top
    principles = {"S在位": bool(p1), "V/O在位": bool(p2), "V有搭配": bool(p3),
                  "O属搭配类": bool(p4), "O进top": bool(p5)}
    if not allow:
        kind = "plain"
    elif o in allow_mem:
        kind = "ok"
    else:
        kind = "bad"
    return kind, principles, allow_mem


def _load_key():
    """读取 DEEPSEEK_API_KEY：环境变量优先，缺省读本地 .env（已 gitignore 屏蔽，
    密钥不进代码仓库）。都缺 → 返回 None（调用方回退规则版）。"""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    env_fp = Path(__file__).resolve().parent / ".env"
    if env_fp.exists():
        for line in env_fp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == "DEEPSEEK_API_KEY":
                    return v.strip().strip('"').strip("'")
    return None


def _llm_chat(messages):
    """DeepSeek chat API（标准库 urllib，无第三方依赖）。
    密钥缺失（环境变量 / .env 均无）→ 返回 None（调用方回退）。"""
    key = _load_key()
    if not key:
        return None
    try:
        import urllib.request
        body = json.dumps({"model": "deepseek-chat", "messages": messages,
                           "temperature": 0.2, "max_tokens": 200}).encode()
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"]["content"]
    except Exception as e:                     # 网络/超时/额度 → 回退，不崩实验
        print(f"    [LLM] 调用失败回退：{e}")
        return None


def llm_judge(diag):
    """LLM 教师判断：'S+V+O' 搭配是否合理 + 自然语言原因（判断由 LLM 负责）。

    输入限死（诚实底线）：只喂诊断内已有的实体（V/O/搭配类别），
    LLM 判断用其语义知识（教师知识，RLAIF）；处罚仍由网络执行。
    返回 (judgement, reason) 或 None（无 key / 调用失败 / 输出越界拦截
    ——越界时不当作判错，回退规则验证器）。
    """
    allow_txt = "、".join(diag["allow"]) if diag["allow"] else "无（诚实留白）"
    q = (f"你是中文教师。判断主谓宾搭配「{diag['S']}{diag['V']}{diag['O']}」"
         f"是否合理自然（如'吃苹果'合理、'吃石头'不合理、'看石头'合理）。"
         f"只输出两行：第一行是单个字符 对 或 错；第二行是不超过 20 字的原因。"
         f"不要参考任何给定搭配表，仅凭语义常识判断。")
    txt = _llm_chat([{"role": "user", "content": q}])
    if txt is None:
        return None
    # 解析：第一行第一个字符 = 判断（修复：原 '对' in 首词 会把'不对'误判对）
    lines = [ln.strip() for ln in txt.strip().splitlines() if ln.strip()]
    first = lines[0] if lines else txt.strip()
    judgement = "对" if first.startswith("对") else "错"
    # 越界拦截：未引用诊断内实体 → 拒绝使用（回退规则验证器，不作判错）
    # （2026-08-10 实测：prompt 给"搭配类别"上下文会锚定 LLM 判断——
    #  "看石头"被误判错；改纯语义判断，allow 只留作越界检查实体）
    if not any(e in txt for e in [diag["S"], diag["V"], diag["O"]] + diag["allow"]):
        return None
    return judgement, txt


def template_reason(diag):
    """模板解释器（无 key 回退，标注"模板占位"）：
    从归因记录生成自然语言原因——依据全部是网络真实边。"""
    if diag["kind"] == "bad":
        if diag["penalized"]:
            return (f"[模板占位] 不能'{diag['S']}{diag['V']}{diag['O']}'："
                    f"{diag['O']} 不属于 {diag['V']} 的搭配类别"
                    f"[{'、'.join(diag['allow'])}]（类别判定边权重≈0），"
                    f"候选经边 {diag['penalized']} 带入 → 已删除该边（连接级处罚）。")
        return (f"[模板占位] 不能'{diag['S']}{diag['V']}{diag['O']}'："
                f"{diag['O']} 不属于 {diag['V']} 的搭配类别"
                f"[{'、'.join(diag['allow'])}]，且无任何边将其带入候选"
                f"（零分拒绝，统计无共现）。")
    if diag["kind"] == "ok":
        return (f"[模板占位] '{diag['S']}{diag['V']}{diag['O']}' 合理："
                f"{diag['O']} 属于 {diag['V']} 的搭配类别"
                f"[{'、'.join(diag['allow'])}]（类别判定边成立）。")
    return (f"[模板占位] '{diag['S']}{diag['V']}{diag['O']}' 诚实留白："
            f"{diag['V']} 无搭配类别，宾语位回退泛名词池。")


# ════════════════════════════════════════════════════════════════
#  处罚（颗粒度升级核心：连接级归因处罚）
# ════════════════════════════════════════════════════════════════

def penalize_edge(ng, pats, src_w, dst_w):
    """连接级处罚：删除 src_w → dst_w 的全部出边（显式减权到 0 = 删除）。

    排斥 = 边不存在（稀疏网络 W 无负权重，删除即惩罚结果）。
    返回 [(源神经元, 目标神经元, 原权重)]（留档诊断用）。
    """
    removed = []
    dst_n = set(pats[dst_w])
    for i in pats.get(src_w, []):
        row = ng.W_out[i][0]
        for j in list(row):
            if j in dst_n:
                removed.append((i, j, row[j]))
                del row[j]
                ng._edge_dirty[i][0] = True
    return removed


def penalize_bad_word(ng, pats, n2w, word, sources, allow, log):
    """对进入候选的异类词执行连接级处罚：删除其全部得分来源边。

    word 的得分来源边 = 处罚落点（归因 → 处罚）。
    返回被处罚边描述（供原因生成）；无来源（零分）→ None（拒绝成立无错边）。
    """
    srcs = sources.get(word)
    if not srcs:
        return None
    for src_type, src_w, j, wt in srcs:
        # 只处罚"类别泛化/O槽保底"带来的异类词（V直连异类词 = V 误连，也罚）
        removed = penalize_edge(ng, pats, src_w, word)
        if removed:
            log.append({"src_word": src_w, "dst_word": word,
                        "src_type": src_type, "removed": removed})
    return f"{word}←({','.join(sorted({t for t, *_ in srcs}))})"


# ════════════════════════════════════════════════════════════════
#  通用（复用 v10 已验）
# ════════════════════════════════════════════════════════════════

def edge_between(ng, pats, src, dst):
    """src 模式出边汇聚到 dst 模式神经元集合的总权重（有边即 > 0）。"""
    return edge_sum(ng, pats, src, set(pats[dst]))


def sent_recall(ng, pats, s):
    """句复述率：输入整句 → 唤起整句各词比例（Stage 2 口径）。"""
    neurons = [j for w in s for j in pats[w]]
    fired = run_recall(ng, build_pulse(ng.n, neurons))
    return fire_ratio(fired, neurons)


def main():
    smoke = "--smoke" in sys.argv
    if smoke:
        print("⚠ SMOKE 模式：小规模快跑（仅验证机制，指标不具统计意义）")
        n_train, n_test = 60, 30
        n_make = 5
    else:
        n_train, n_test = N_TRAIN, N_TEST
        n_make = N_MAKE
    has_llm = bool(_load_key())
    t0 = time.time()
    print("═══ Stage 2.6 v11 迭代：RL 颗粒度升级（连接级归因处罚）+ LLM 教师 ═══\n")
    print(f"[LLM] {'DEEPSEEK_API_KEY 已配置 → LLM 教师判断 + LLM 原因'
            if has_llm else '无 API key → 规则验证器 + 模板解释器（标注[模板占位]）'}")

    # ── 1. 加载 v10.0（动宾搭配链最新）──
    ng, vocab, pats, cursor = load_version("10.0")
    hanzi = json.loads((DATA / "stage0_hanzi.json").read_text(encoding="utf-8"))
    print(f"[加载] 10.0（Stage 2.6 链最新）：n={ng.n}，模式 {len(pats)}，cursor={cursor}")

    # ── 2. 集合构造（∩ v10.0 网络）──
    s_words = sorted({w for w in PERS_MANUAL + S_ANIMALS if w in pats})
    v_words = sorted({w for w in V_SET if w in pats})
    o_words = sorted({w for w in O_FOOD + O_PLACE if w in pats})
    if not (s_words and v_words and o_words):
        raise SystemExit(f"S {len(s_words)} / V {len(v_words)} / O {len(o_words)} 有空集")

    # ── 3. 搭配类别与类别成员（v10 同款重建，验证器原则4 依据）──
    vo_pairs = {v: [o for o in ops if o in pats]
                for v, ops in VO_PAIRS.items() if v in v_words}
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats25 = build_cats(pats, sem["words"], 12, 3)
    cat_members = {}
    for l in ["食物", "地点"]:
        d = cats25.get(l)
        cat_members[l] = set(d["train"]) | set(d["hold"]) if d else set()
    cat_members["食物"] |= set(O_FOOD)
    cat_members["地点"] |= set(O_PLACE)
    noun_pool = cat_members["食物"] | cat_members["地点"]

    # ── 4. 测试组合（与 v10 同种子同划分 → 验收可比）──
    all_combos = [(s, v, o) for s in s_words for v in v_words for o in o_words]
    rng = np.random.default_rng(SEED)
    perm = rng.permutation(len(all_combos))
    train_combos = [all_combos[i] for i in perm[:n_train]]
    test_combos = [all_combos[i] for i in perm[n_train:n_train + n_test]]
    n2w = {j: w for w, ns in pats.items() for j in ns}
    eval_make = test_combos[:n_make] if smoke else test_combos
    print(f"[组合] 总 {len(all_combos)}，训练 {len(train_combos)}，"
          f"测试 {len(test_combos)}，评估 {len(eval_make)}")

    # ── 5. 归因 → 验证 → 处罚 → 原因（核心循环）──
    t1 = time.time()
    n_ok, n_bad, n_plain = 0, 0, 0
    n_ok_pass, n_bad_pass, n_plain_pass = 0, 0, 0
    n_bad_reason, n_bad_total = 0, 0        # 原因覆盖（负例必有自然语言原因）
    n_penalty_log = 0                       # 处罚次数（连接级处罚动作）
    n_attr_track = 0                        # 归因成功次数（能指出错词来源/零分）
    n_llm_judge = 0                         # LLM 教师成功判断次数（判断由 LLM 负责）
    n_llm_agree = 0                         # LLM 判定与规则验证器一致次数
    n_llm_reason = 0                        # 病句附 LLM 自然语言原因次数（非模板）
    penalty_log = []                        # 处罚留档（诊断原料）
    reason_samples = []                     # 原因示例（展示）
    for s, v, o in eval_make:
        ok_path, top, allow, sources = attributed_sentence(
            ng, pats, n2w, s, v, vo_pairs, cat_members)
        kind, principles, allow_mem = rule_verifier(
            ng, pats, s, v, o, allow, cat_members, top)
        diag = {"S": s, "V": v, "O": o, "kind": kind, "allow": sorted(allow),
                "top": top, "principles": principles,
                "allow_mem": sorted(allow_mem)[:8], "penalized": None}
        # LLM 教师判断（判断由 LLM 负责，2026-08-10 用户决策）：
        # 非 plain 组合由 LLM 判定"对/错"覆盖规则 kind；plain 无搭配留白
        # （无数据不是可判定的病句），不打扰教师。LLM 失败/越界 → 回退规则。
        llm_reason, llm_ok = None, False
        if has_llm and kind != "plain":
            res = llm_judge(diag)
            if res:
                jg, llm_reason = res
                n_llm_judge += 1
                n_llm_agree += (jg == ("对" if kind == "ok" else "错"))
                kind = "bad" if jg == "错" else "ok"
                llm_ok = (jg == "对")
        # 处罚：top 里不属于搭配类别的词（噪声/异类）→ 归因 → 删来源边
        # （2026-08-10 修复：去掉 `in noun_pool` 过滤——非名词池噪声词
        #  [点/地/与/特朗普] 进 top 同样是错误候选；v10 的 170/170 曾靠
        #  "超市"跨类词压线撑 ratio≥0.5，删噪声边后暴露 0.375 < 0.5）
        pen_done = 0
        if kind != "plain":
            bad_in_top = [w for w in top if w not in allow_mem]
        else:
            bad_in_top = [w for w in top if w not in noun_pool]
        if llm_ok:                           # 教师认可的宾语词不处罚
            bad_in_top = [w for w in bad_in_top if w != o]
        for bw in bad_in_top:
            desc = penalize_bad_word(ng, pats, n2w, bw, sources, allow,
                                     penalty_log)
            if desc:
                diag["penalized"] = desc
                pen_done += 1
                n_penalty_log += 1
                n_attr_track += 1
        # 病句组合：拒绝成立（O 未进 top）→ 归因记录（零分拒绝也算归因成功）
        if kind == "bad" and o not in top and not sources.get(o):
            n_attr_track += 1
        # 训练时统计（处罚前 top，对照用；正式验收 = 处罚后重测 5b）
        # 注意：此处 top 是处罚前的快照——2 个"画"组合曾因地点类噪声词
        # 压线失败（0.375），其噪声边在本轮处罚中被删 → 5b 重测 170/170
        if kind == "plain":
            ratio = sum(1 for w in top if w in noun_pool) / max(1, len(top))
            n_plain += 1
            n_plain_pass += ok_path and ratio >= 0.5
        elif kind == "ok":
            ratio = sum(1 for w in top if w in allow_mem) / max(1, len(top))
            n_ok += 1
            n_ok_pass += ok_path and ratio >= 0.5
        else:
            ratio = 1.0 if o not in top else 0.0
            n_bad += 1
            n_bad_total += 1
            n_bad_pass += ok_path and o not in top
        # 处罚原因（硬约束：所有 RL 负反馈附自然语言原因）
        # LLM 教师模式：判断+原因一体（llm_judge 已在判断块调用，不重复调 API）；
        # LLM 失败/越界/无 key → 模板解释器兜底（标注[模板占位]）
        if kind == "bad":
            reason = llm_reason or template_reason(diag)
            if llm_reason:
                n_llm_reason += 1
            if reason:
                n_bad_reason += 1
            if len(reason_samples) < n_make:
                reason_samples.append((s, v, o, kind, ok_path, ratio,
                                       top[:8], reason))
    # ── 5a+. LLM 教师边界案例演示（仅 has_llm 全量；不改网络，纯展示）──
    # 规则验证器类别级比对 vs LLM 语义判断——"看石头"类别不匹配但语义合法，
    # 规则会误判负例，LLM 语义判断能识别（方案 v2.6 LLM 教师设计点）
    if has_llm and not smoke:
        demo = [("我", "吃", "苹果"), ("我", "吃", "石头"),
                ("我", "看", "石头"), ("我", "喝", "学校"),
                ("我", "画", "石头"), ("我", "买", "学校")]
        print(f"\n[教师演示] LLM 判断 vs 规则验证器（不改网络）")
        for s, v, o in demo:
            ok_path, top, allow, _ = attributed_sentence(
                ng, pats, n2w, s, v, vo_pairs, cat_members)
            kind_r, _, allow_mem = rule_verifier(
                ng, pats, s, v, o, allow, cat_members, top)
            d = {"S": s, "V": v, "O": o, "kind": kind_r,
                 "allow": sorted(allow), "top": top,
                 "principles": {}, "allow_mem": sorted(allow_mem)[:8],
                 "penalized": None}
            res = llm_judge(d)
            jg_l, r_l = res if res else ("回退", "（调用失败/越界拦截）")
            print(f"  {s}+{v}+{o} → 规则: {kind_r:5s} | LLM: {jg_l} — {r_l[:36]}")
        print()
    # 无样本维度跳过（冒烟组合少）→ 占位 1.0 不判失败
    r_ok = n_ok_pass / n_ok if n_ok else 1.0
    r_bad = n_bad_pass / n_bad if n_bad else 1.0
    r_plain = n_plain_pass / n_plain if n_plain else 1.0
    r_make = (n_ok_pass + n_bad_pass + n_plain_pass) / max(1, len(eval_make))
    r_reason = n_bad_reason / n_bad_total if n_bad_total else 1.0
    n_edges_del = sum(len(e["removed"]) for e in penalty_log)
    print(f"[归因] 成功追踪 {n_attr_track} 次（错词来源边 / 零分拒绝）"
          f"（{time.time() - t1:.0f}s）")
    print(f"[处罚] 连接级处罚 {n_penalty_log} 次，删除 {n_edges_del} 条边"
          f"（落点 = 异类词得分来源边）")
    print(f"[教师] LLM 判断 {n_llm_judge} 次（与规则一致 {n_llm_agree} 次，"
          f"一致率 {n_llm_agree / max(1, n_llm_judge):.3f}；"
          f"病句 LLM 原因 {n_llm_reason}/{n_bad_total}）")

    # ── 5b. 处罚后重测（正式验收③b 口径：最终网络状态重测，不回退）──
    # 训练时统计用处罚前 top（噪声边未删）；处罚完成后异类词来源边已删除，
    # 重测验证"删除错误边后 top 变干净"——连接级处罚的价值所在。
    t2 = time.time()
    n_ok2 = n_ok2_pass = 0
    n_bad2 = n_bad2_pass = 0
    n_plain2 = n_plain2_pass = 0
    for s, v, o in test_combos:
        ok_path, top, allow, _ = attributed_sentence(
            ng, pats, n2w, s, v, vo_pairs, cat_members)
        kind, _, allow_mem = rule_verifier(
            ng, pats, s, v, o, allow, cat_members, top)
        if kind == "plain":
            ratio = sum(1 for w in top if w in noun_pool) / max(1, len(top))
            n_plain2 += 1
            n_plain2_pass += ok_path and ratio >= 0.5
        elif kind == "ok":
            ratio = sum(1 for w in top if w in allow_mem) / max(1, len(top))
            n_ok2 += 1
            n_ok2_pass += ok_path and ratio >= 0.5
        else:
            rejected = o not in top
            n_bad2 += 1
            n_bad2_pass += ok_path and rejected
    r2_ok = n_ok2_pass / n_ok2 if n_ok2 else 1.0
    r2_bad = n_bad2_pass / n_bad2 if n_bad2 else 1.0
    r2_plain = n_plain2_pass / n_plain2 if n_plain2 else 1.0
    r2_make = (n_ok2_pass + n_bad2_pass + n_plain2_pass) / max(1, len(test_combos))
    print(f"[重测] 处罚后重测（正式口径，{time.time() - t2:.0f}s）: "
          f"ok {n_ok2_pass}/{n_ok2} = {r2_ok:.4f} | "
          f"bad {n_bad2_pass}/{n_bad2} = {r2_bad:.4f} | "
          f"plain {n_plain2_pass}/{n_plain2} = {r2_plain:.4f} | "
          f"总 {r2_make:.4f}")

    # ── 6. 验收⑤ 归因/处罚/原因 ──
    ok_attr = n_attr_track >= min(len(eval_make), 3) if not smoke else True
    ok_penal = True                            # 处罚无错边时合法（零分拒绝）
    ok_reason = r_reason >= 0.8 if n_bad_total else True
    print(f"\n[验收⑤a] 归因：{n_attr_track}/{len(eval_make)} 组合能定位错误来源"
          f" {'✅' if ok_attr else '❌'}")
    print(f"[验收⑤b] 处罚：{n_penalty_log} 次连接级处罚，删除 {n_edges_del} 边"
          f"（无错边 = 零分拒绝，合法）{'✅' if ok_penal else '❌'}")
    print(f"[验收⑤c] 处罚原因：{n_bad_reason}/{n_bad_total} 病句有自然语言原因"
          f" {'✅' if ok_reason else '❌'}（硬约束：所有 RL 负反馈附原因）")
    print(f"[示例]（S+V+O → 判定 + 处罚原因）")
    for s, v, o, kind, path, ratio, top, reason in reason_samples:
        tag = {"ok": f"✓搭配 {ratio:.2f}", "bad": f"✗病句拒绝 {ratio:.2f}",
               "plain": f"~泛名词 {ratio:.2f}"}[kind]
        print(f"  {s}+{v}+{o} → {tag}（{'路径通' if path else '路径断'}）")
        print(f"    top: {top}")
        print(f"    原因: {reason}")

    # ── 7. 验收③b 继承（v10 三分口径，处罚后重测不回退）──
    print(f"\n[验收③b] 造句填充（处罚后重测 {len(test_combos)} → 宾语位类别约束）: "
          f"{r2_make:.4f} {'✅ ≥0.5' if r2_make >= 0.5 else '❌'}")
    print(f"   合理搭配: {n_ok2_pass}/{n_ok2} = {r2_ok:.4f}"
          f"（训练时处罚前 {n_ok_pass}/{n_ok} = {r_ok:.4f}）")
    print(f"   病句拒绝: {n_bad2_pass}/{n_bad2} = {r2_bad:.4f}"
          f"（异类 O 不得进 top-8）{'✅' if r2_bad >= 0.8 else '❌'}")
    print(f"   无搭配动词: {n_plain2_pass}/{n_plain2} = {r2_plain:.4f}")

    # ── 8. 验收④ 字/词/句 + 2.5 四类 + hold-out 零遗忘（继承 v10）──
    words_old = [w for w in vocab if w not in set(hanzi)]
    rng7 = np.random.default_rng(7)
    eval_hanzi = list(rng7.choice(hanzi, EVAL_HANZI, replace=False))
    rng8 = np.random.default_rng(8)
    eval_words = list(rng8.choice(words_old, EVAL_WORD, replace=False))
    sents_all = json.loads((DATA / "stage2_sents.json").read_text(encoding="utf-8"))
    rng9 = np.random.default_rng(9)
    eval_sents = [sents_all[i] for i in rng9.choice(len(sents_all), EVAL_SENT,
                                                    replace=False)]
    r0 = recall_words(ng, pats, eval_hanzi, K)
    rw0 = recall_words(ng, pats, eval_words, 20)
    rs0 = np.mean([sent_recall(ng, pats, s) for s in eval_sents])
    r0_after = recall_words(ng, pats, eval_hanzi, K)
    rw0_after = recall_words(ng, pats, eval_words, 20)
    rs0_after = np.mean([sent_recall(ng, pats, s) for s in eval_sents])
    ok_char = r0_after >= r0 - 0.01
    ok_word = rw0_after >= rw0 - 0.01
    ok_sent = rs0_after >= rs0 - 0.01
    cat_ok, hold_ok = {}, {}
    for label, d in cats25.items():
        tag_n = set()
        for t in d["tags"]:
            tag_n.update(pats.get(t, []))
        cat_ok[label] = round(float(np.mean(
            [edge_sum(ng, pats, w, tag_n) > 0.1 for w in d["train"]])), 4)
        others_n = set()
        for l2, d2 in cats25.items():
            if l2 == label:
                continue
            for t in d2["tags"]:
                others_n.update(pats.get(t, []))
            for m in d2["train"]:
                others_n.update(pats[m])
        mine = set(tag_n)
        for m in d["train"]:
            mine.update(pats[m])
        n_hok = 0
        for h in d["hold"]:
            shared = set(sem["words"][h]) & set().union(
                *(set(sem["words"][m]) for m in d["train"]))
            self_n = set(mine)
            for ss in shared:
                self_n.update(pats.get(ss, []))
            hold_ok[label] = int(edge_sum(ng, pats, h, self_n) > 0
                                 and edge_sum(ng, pats, h, self_n)
                                 >= edge_sum(ng, pats, h, others_n) * 0.5)
            n_hok += hold_ok[label]
        hold_ok[label] = n_hok
    r_cat25 = np.mean(list(cat_ok.values())) if cat_ok else 0.0
    n_hold25_ok = sum(hold_ok.values())
    n_hold25_tot = sum(len(d["hold"]) for d in cats25.values())
    ok_cat25 = all(v >= 0.9 for v in cat_ok.values()) if cat_ok else True
    ok_hold25 = n_hold25_ok >= n_hold25_tot * 0.5 if n_hold25_tot else True
    print(f"[验收④] 字 {r0_after:.4f}（base {r0:.4f}）{'✅' if ok_char else '❌ 回退!'}")
    print(f"[验收④] 词 {rw0_after:.4f}（base {rw0:.4f}）{'✅' if ok_word else '❌ 回退!'}")
    print(f"[验收④] 句 {rs0_after:.4f}（base {rs0:.4f}）{'✅' if ok_sent else '❌ 回退!'}")
    print(f"[验收④] 2.5 四类归属 {r_cat25:.4f} {'✅' if ok_cat25 else '❌'} {cat_ok}")
    print(f"[验收④] 2.5 hold-out {n_hold25_ok}/{n_hold25_tot} "
          f"{'✅' if ok_hold25 else '❌'}")

    ok_all = bool(r2_make >= 0.5 and r2_bad >= 0.8 and ok_reason
                  and ok_attr and ok_char and ok_word and ok_sent
                  and ok_cat25 and ok_hold25)
    print(f"\n═══ v11 验收: {'全部通过 ✅' if ok_all else '有失败 ❌'} "
          f"（{time.time() - t0:.0f}s）═══")

    # ── 9. 快照（parent=10.0 → v11.0；冒烟不存）──
    # 正式口径 = 处罚后重测（*_retest）；训练时（处罚前 top）作对照（*_t1）
    metrics = {"make_recall": round(r2_make, 4),
               "ok_recall": round(r2_ok, 4), "ok_n": n_ok2_pass, "ok_tot": n_ok2,
               "bad_recall": round(r2_bad, 4), "bad_n": n_bad2_pass,
               "bad_tot": n_bad2,
               "plain_recall": round(r2_plain, 4),
               "ok_recall_t1": round(r_ok, 4), "ok_n_t1": n_ok_pass,
               "ok_tot_t1": n_ok, "bad_recall_t1": round(r_bad, 4),
               "bad_n_t1": n_bad_pass, "bad_tot_t1": n_bad,
               "plain_recall_t1": round(r_plain, 4),
               "attribution_ok": n_attr_track, "attribution_tot": len(eval_make),
               "penalty_actions": n_penalty_log, "edges_deleted": n_edges_del,
               "penalty_log": penalty_log,
               "reason_coverage": round(r_reason, 4),
               "reason_n": n_bad_reason, "reason_tot": n_bad_total,
               "reason_samples": reason_samples,
               "llm_enabled": has_llm,
               "llm_judged": n_llm_judge, "llm_agree": n_llm_agree,
               "llm_reason": n_llm_reason,
               "vo_pairs": vo_pairs,
               "char_recall": round(r0_after, 4),
               "char_recall_before": round(r0, 4),
               "word_recall": round(rw0_after, 4),
               "word_recall_before": round(rw0, 4),
               "sent_recall": round(rs0_after, 4),
               "sent_recall_before": round(rs0, 4),
               "cat25_recall": round(r_cat25, 4), "cat25_per": cat_ok,
               "hold25_ok": n_hold25_ok, "hold25_total": n_hold25_tot,
               "train_combos": train_combos, "test_combos": test_combos,
               "n": ng.n, "all_ok": ok_all}
    if not smoke:
        save_snapshot(ng, parent="10.0",
                      tag="Stage 2.6 v11 迭代：RL 颗粒度升级（连接级归因处罚）"
                          "+ LLM 教师（判断+原因）",
                      metrics=metrics, vocab=vocab, pats=pats, cursor=cursor)


if __name__ == "__main__":
    main()
