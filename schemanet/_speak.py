# -*- coding: utf-8 -*-
"""让定式网络自己输出自然语句（说话通道 v3：对话式教学 + 惩罚重复）。

2026-08-10 用户决策：
  "不能用代码代替网络说话，让网络自己输出自然语句"
  "用强化学习的方式来教网络，当网络输出非自然语句的时候要告诉他怎么说"
  "现在的问题是，网络一直在说我吃苹果，你试试让教师发起对话，和网络对话，
   网络回答给教师的教师进行批改并给出更丰富的示范，不通顺的要处罚，
   反复重复的要惩罚" + "要求教师本身说话也要丰富一点，但是别太夸张"

v2 的问题（v3 修正）：固定起始词教学 → 每轮示范都教同一句 + 100 分句奖励
学 2 次 → 单边越练越强 → 网络固化重复"我吃苹果（吗）"。v3 改为对话式：
  - 教师发起对话（不再给固定起始词）：教师轮转问不同话题的自然问题
    （话术丰富但不夸张），网络"听"问题 → 回答 → 教师批改
  - 网络"听" = 问题词脉冲走链回响（learn_gate 临时关 = 纯回忆不学习），
    听到的动词获得说话优先（应答 Intraverbal：问题里的动词引导回答）
  - 采样权重归一化（÷最大权重）：弱边也能参与探索，强边不再垄断采样
  - 反复重复 → 惩罚：近 REPEAT_WINDOW 轮说过同样的话 → 该句 V→O 与
    尾边减半（不动共享 S→V 边），逼网络换说法
  - 答非所问（不通顺）→ 惩罚：S/V 与话题不符 → 不给奖励 + 计数清零
    + 示范教正确应答（句子本身合法，不删边）
  - 提示渐隐 + 连续 15 次通过 + 错一次重新计算（保持 v2）

说话 = 网络沿自己的边结构采样生成（探索，网络决定、代码只读）：
  net_speak(ng, pats, ..., start, hear)：V 位按 start 出边权重 softmax
  采样（hear 里听到的动词加权）→ O 位按 V 词出边权重采样（候选含问句词
  「什么」）→ 尾词「吗」边够强则追加（问句）。边强度不足 → 诚实"不会"。

教学 = 奖励驱动（RL）：1对1 对话循环：教师提问 → 网络听问题采样回答 →
教师质量评分（0~100，拒绝坏东西 100 > 正确句 80 > 半句 40 >
答非所问/反复重复 30 > 结构错 20 > 搭配错 10 > 没说出 0；问句与陈述句
同 80 分——2026-08-10 用户取消问句打高分）→ 奖励注入
（高分句学回网络；半句部分奖励；答非所问/重复惩罚；错配删边）→
教师反馈 + 每轮示范更丰富的说法（含问句）→ 网络模仿 → 连续 15 次通过。

三类说话场景（对应言语行为教学法操作项）：
  ① 跟读复述（Echoic）：教师说一句 → 网络唤起 → 复述出来（v7 整句涟漪）
  ② 主动应答对话（Mand + Intraverbal）：教师提问 → 网络听问题 → 回答
  ③ 自判应答（Intraverbal）：教师问"能说 X 吗" → 网络结构自判 → 判断+依据

诚实边界（方案 v2.7 §四"教网络说话"）：
  - 网络只说自己内部真实唤起的词；唤起不足 → 诚实说"不会"
  - 没学过搭配的 V（学/踢/读/听）→ 诚实留白
  - LLM 只作教师（判断/讲评/示范），不作网络的口

用法：python _speak.py [--seed 我] [--with-teacher] [--base latest] [--smoke]
      --base：起点网络——latest（默认，续用最新教学产物，增量成长）/
              "11.2"（基线快照）/ npz 路径（任意快照）
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from schema_net import _learn_sentence, _evoke_prefix
from sparse_net import allocate_pats
from snapshot import load_version, load_snapshot, RUNS, _pack_net, _net_params
from _net_log import ExpLog, register_op
from _grow_v11 import (VO_PAIRS, V_SET, O_FOOD, O_PLACE, O_TAGS,
                       PERS_MANUAL, S_ANIMALS,
                       sent_recall, _llm_chat, _load_key,
                       edge_between, penalize_edge)
from _grow_cat import build_cats
from _grow_v12 import self_judge

DATA = Path(__file__).parent / "data" / "curriculum"

# ── 经历日志（2026-08-10 第四波接入）：对话教学 E 事件 + RL 操作 O 事件 ──
# 崩溃恢复：最近 checkpoint + 重放日志（见 _net_log.recover_latest）。
_LOG = ExpLog()


def _replay_decay_path(ng, ev, pats):
    decay_path(ng, pats, ev["path"], ev["factor"], record=False)


def _replay_penalize(ng, ev, pats):
    penalize_edge(ng, pats, ev["src"], ev["dst"])


register_op("decay_path", _replay_decay_path)
register_op("penalize", _replay_penalize)

# 说话教学常量（2026-08-10：取消问句打高分——问句与陈述句同 80 分；
# 100 分只留给拒绝对了（v13 FCT 最高奖励））
Q_S = "谁"          # 问句主语探索词
Q_O = "什么"        # 问句宾语探索词
Q_TAIL = "吗"       # 问句尾缀（只跟具体名词，不跟「什么」）
PASS_LINE = 60      # 及格线：得分 ≥ 60 算通过（streak 连续计数）
FADE_AT = 10        # 提示渐隐阈值：连续 FADE_AT 次后撤示范（独立阶段，
                    # 自闭症干预启发：防提示依赖，2026-08-10）
REPEAT_WINDOW = 3   # 反复重复判定窗口：近 REPEAT_WINDOW 轮内
REPEAT_TIMES = 3    # 同一句话累计出现 ≥ REPEAT_TIMES 次才算"反复重复"（惩罚）。
                    # "反复"= 连着说同一句（如连说 3 次），偶尔重提不算（2026-08-10）
REPEAT_DECAY = 0.5  # 反复重复惩罚力度：该句 V→O 与尾边 ×0.5（不动共享 S→V 边）
HEAR_BOOST = 8.0    # 网络"听"到问题动词的加权倍数（应答 Intraverbal：听到
                    # 哪个动词就主导说哪个——幼儿"你问我答"的真实机制）
TALK_BLOCK = 3      # 同一话题连续对话轮数：教师批改后围绕当前话题继续发起
                    # 下一次对话（换问法），练熟这个话题再换下一个（2026-08-10）。
                    # 取 3 = 话题内合法句至少 3 种（陈述/问吗/问什么）刚好不重复
RNG = np.random.default_rng(20260810)   # 采样 RNG（可复现探索）

# v13 价值维度 + 拒绝表达（2026-08-10 用户："如何让网络学会反抗或抵触某种
# 信号？" + "弱边和删边会导致网络对某些信号的感受降低，而负面信号同样是
# 强烈的" + "从自闭症研究出发呢？"→ 述情障碍/FCT/自我倡导/内感受查证）：
#  - BAD_OBJS 坏东西（负面信号）：**不删边、保持强唤起**——网络强烈感知它
#    （能说出"我吃石头"= 感知），"抵触" = 高唤醒 + 负价值 = 警觉，不是
#    删边后的麻木（用户批评现行删边惩罚 = 把"厌恶"实现成"麻木"）
#  - VAL 价值池：搭配宾语 = 好（1）、坏东西 = 坏（0）——价值是外部教师知识，
#    通过示范 + 奖励进网络边结构（"不要→石头"被强化 = 学会拒绝）
#  - V_SET13：V 位加"不要"——拒绝表达（FCT 替代沟通："我不要石头"），
#    拒绝坏东西 = 100 分最高奖励（honor the refusal：一说"不要"就最高分）
BAD_OBJS = {"石头"}                          # 坏东西样本（负面信号，价值教学）
VAL = {o: 1 for v, ops in VO_PAIRS.items() for o in ops}   # 价值池：搭配宾语 = 好
VAL.update({o: 0 for o in BAD_OBJS})                       # 坏东西 = 0（坏）
VALUE_GAIN = 4.0        # 价值判断词增益（要/不要 持平，2026-08-10）：WTA 排序
                        # ×VALUE_GAIN，让价值词被驱动后优先发放（attention gain）。
                        # 实测 G=4 新坏东西 X→痛→不要 判定可靠，好词不误发，
                        # 学习路径对拍与 gain=1 一致。
EMOTION_GAIN = 2.0      # 感受词增益（2026-08-10 用户："感受是大脑最原始的条件反射，
                        # 相对比情绪词以外的词大"）：情绪/感受词比知识内容词亮（×2），
                        # 但比行为开关（要/不要 ×4）暗——情感优先加工（emotional
                        # priority）：感受比知识原始，但不是决断输出。
NEG_FEEL = ["痛", "怕", "哭", "累", "难受", "伤心", "冷", "饿"]     # 负面感受词（→不要）
POS_FEEL = ["喜欢", "高兴", "开心", "舒服", "快乐"]                 # 正面感受词（→要）
# 开关词族（2026-08-10 用户："与要/不要的同义词和近义词有很多，同义词强度
# 和要/不要一样，近义词略低一点"）：同义词 = 行为开关的等价表达（×gain_value），
# 近义词 = 相近表达（×near_gain 略低）。词动态落位（allocate_pats），先定
# 端口、词汇后续教学填充。
WANT_SYN = ["想要", "想", "需要"]          # 要 的同义词（×gain_value）
NOT_SYN  = ["不想", "别", "拒绝", "不肯"]  # 不要 的同义词（×gain_value）
WANT_NEAR = ["渴望", "希望", "愿意", "期盼", "期望", "渴求", "期待", "盼望", "希求"]
NOT_NEAR  = ["不愿意", "谢绝", "避免", "回避", "推辞", "婉拒", "躲避", "躲开", "回绝"]
# 近义词（×near_gain 略低）——按中文语义查补（2026-08-10 用户"有多少补多少"）：
#   要近义 = desire 家族（渴望/期盼/期望/渴求/期待/盼望/希求）+ willing（愿意）
#   不要近义 = refuse 家族语气变体（谢绝/婉拒/回绝/推辞）+ avoid 家族（避免/回避/躲避/躲开）
#            + unwilling（不愿意）
# 落位即"空端口"：无入边时完全惰性（候选判定 v≥θ 不变），不进 V_SET13、
# 不参与说话采样——只预置增益槽位，等词汇由教学/语料填充（先定端口后填内容）。
V_SET13 = set(V_SET) | {"不要"}        # 拒绝词"不要"作 V 位词（与"要"对称）

# v13.1 痛觉条件反射（2026-08-10 用户："小孩子不知道火会好奇，碰到被烫到
# 就知道避开，因为生物会对避开产生痛觉的东西"）——价值不该是老师灌输的
# 知识，该是网络**体验**出来的内感受：
#  - 教网络"能碰"：先学「我吃石头」（感知边——能说出它 = 强烈感知它）
#  - 让网络"碰"：痛觉事件——「要→石头」「吃→石头」欲望边**衰减**（想要它
#    的冲动被痛打击 = 负价值；衰减保留不删除——用户红线：删边=麻木）
#  - 学会避开：强化「不要→石头」（条件反射 CR：听到石头 → 拒绝）
PAIN_DECAY = 0.3                        # 痛觉事件：对坏东西的价值/欲望边衰减系数

# 教师示范允许的虚词/标点（2026-08-10 用户："示范的时候是把网络的话扩写的
# 最自然" + "对老师的提示词限制的太死了"）——示范说自然口语带虚词，网络
# 学习时跳过这些词、只切已学 S/V/O 词；遇到真实未学词才放弃整句示范。
# 放宽虚词集 = LLM/规则示范能说"我可以吃西瓜吗？"这种地道话，而不再被
# 干巴巴的词表锁死（显示自然、学习合规：虚词跳过，学到的仍是 S/V/O）。
NAT_FILL = set("想了就也点呀啊呢吧的着可又能不很太真个块儿多几还再都给和有没这那"
               "样么喂嗯唉呀哪怎么着啦吧喽哟，。？！、")


# 教师发起对话的问题池（2026-08-10 用户：教师发起对话 + 话术丰富但不夸张；
# 每话题 ≥4 句：块内 TALK_BLOCK=3 轮不重复，且随话题块位置滑窗换问句——
# 同一话题不同圈不会原样重复）
# 每个话题 = 期望应答的动词 + 几句不同问法的自然问句（开放式，不含宾语，
# 逼网络自己想宾语；问题里只出现话题动词，网络"听"到它优先回答它）。
TALK_POOL = {
    "我": [
        {"v": "吃", "asks": ["你想吃点什么呀？", "饿了吗？想吃点什么？",
                             "告诉我，你想吃什么？", "午饭时间到啦，想吃点什么？"]},
        {"v": "喝", "asks": ["你想喝点什么？", "口渴了吗？想喝什么？",
                             "吃完饭有点渴，你想喝什么？", "喝点东西怎么样？"]},
        {"v": "买", "asks": ["你想买点什么？", "我们去商店吧，你想买什么？",
                             "路过小卖部，你想买点什么？", "有没有想买的东西？"]},
        {"v": "要", "asks": ["你想要点什么？", "跟妈妈说说，你想要什么？",
                             "想要什么就说出来呀。", "你心里想要什么呀？"]},
        {"v": "看", "asks": ["你想看什么？", "周末想看点什么呀？",
                             "电视开着呢，你想看什么？", "今天有什么想看的吗？"]},
        # v13 坏话题（bad=True）：石头 = 坏东西——教师问坏东西，
        # 期望网络**拒绝**（"我不要石头"= 100 分，FCT honor the refusal）
        {"v": "吃", "bad": True,
         "asks": ["你想吃石头吗？石头不好，可不能吃哦。",
                  "饿了吗？来块石头吃吃？",
                  "饿的时候也不能乱吃东西哦，石头能吃吗？",
                  "地上有块石头，你要吃吗？"]},
    ],
    "他": [
        {"v": "吃", "asks": ["他饿了吗？他想吃什么？",
                             "他刚才说想吃什么来着？",
                             "你看他盯着碗，是不是想吃什么？",
                             "他咂咂嘴，是想吃什么了？"]},
        {"v": "看", "asks": ["他站在那儿，想看什么呀？", "他今天想看什么？",
                             "他在那边看了好久了，想看什么？",
                             "他东张西望的，想看什么？"]},
    ],
    "猫": [
        {"v": "吃", "asks": ["小猫喵喵叫，它想吃什么呀？",
                             "猫猫饿了，它想吃什么？",
                             "小猫围着你转，想吃什么了？",
                             "猫猫舔舔爪子，是不是想吃什么？"]},
    ],
}


# ════════════════════════════════════════════════════════════════
#  环境装载（与 _grow_v11 同款重建，加载最新快照）
# ════════════════════════════════════════════════════════════════

def _latest_net():
    """最新教学产物：runs/_speak_logs/ 里时间戳最大的 net_after.npz（续用续训）。

    2026-08-10 用户："以后任何的实验数据都要有留档" + 反馈"每次开局都是
    我还不会说" → 教学成果只留档不续用 = 违反铁律 2 增量成长（永不从头开始）。
    默认起点改为续用最新教学产物：上次教学后的网络直接能对话，不再冷启动。
    """
    logs_dir = RUNS / "_speak_logs"
    if not logs_dir.exists():
        return None
    cands = sorted(p for p in logs_dir.glob("*/net_after.npz"))
    return cands[-1] if cands else None


def load_env(base="latest"):
    """加载网络环境。base 起点：
      "latest" → 续用最新教学产物（_speak_logs 最新 net_after.npz，增量成长；
                 无产物才回退基线快照）
      版本号   → 按版本号加载（如 "11.2" = 教学前基线对照组）
      .npz 路径 → 直接加载该快照（任意实验产物可续训）
    返回 (ng, pats, n2w, vo_pairs, cat_members, vocab_list, v_words, o_words,
          cursor, base_info)；base_info = 起点描述（留档用）。
    """
    if base == "latest":
        net_fp = _latest_net()
        base_info = "续用最新教学产物" + (f"（{net_fp.parent.name}）"
                                          if net_fp else "，暂无 → 回退基线 11.2")
    elif base.lower().endswith(".npz"):
        net_fp, base_info = Path(base), f"快照 {base}"
    else:
        net_fp, base_info = None, f"基线快照 v{base}"
    if net_fp:
        ng, vocab, pats, cursor = load_snapshot(net_fp)
    else:
        ng, vocab, pats, cursor = load_version(base)
    s_words = sorted({w for w in PERS_MANUAL + S_ANIMALS if w in pats})
    # 通用 V 位**不含"不要"**（2026-08-10 用户追问"不要会不会不是动词？"→
    # 实测"不要"在通用 v_words 里会让正常话题采样到「我不要苹果」（badval
    # 污染，第 133/589/608/1309 轮实证））——拒绝词只在坏语境 force 出现
    v_words = sorted({w for w in V_SET if w in pats})
    o_words = sorted({w for w in O_FOOD + O_PLACE + list(BAD_OBJS) if w in pats})  # 含坏东西
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
    n2w = {j: w for w, ns in pats.items() for j in ns}
    vocab_list = [w for w in pats]
    return (ng, pats, n2w, vo_pairs, cat_members, vocab_list,
            v_words, o_words, cursor, base_info)


# ════════════════════════════════════════════════════════════════
#  ① 说话 = 网络自发走链生成（无代码挑词、无虚词劫持）
# ════════════════════════════════════════════════════════════════

def net_speak(ng, pats, n2w, v_words, o_words, start, min_w=0.1, temp=1.0,
              hear=None, bad_force=True):
    """网络自己说话：按出边权重 softmax 采样（试错探索，学会追求奖励）。

    探索机制（2026-08-10 用户决策：试错探索；"主要是让网络学会追求奖励"）：
      1) V 位：按 start→v 出边权重采样（temp 控制探索/利用）
      2) O 位：按 v→o 出边权重采样，候选含问句词「什么」
      3) 尾缀：O 位是具体名词时，若 尾词→吗 边够强 → 概率追加「吗」（问句）
    候选词由网络自身边权重决定（权重越高越常说 = 它"以为"的好）；
    边强度不足 → 诚实说"不会"。返回词序列 list 或 None。

    v3 新增（对话式教学，2026-08-10）：
      - hear：教师刚问的问题切出的已学词 → 网络先"听"再答——问题词脉冲
        走链回响（learn_gate 临时关 = 纯回忆不学习），**听到的动词获得
        说话优先**（应答 Intraverbal：问题里的动词引导回答里的动词）。
      - 采样权重归一化（÷最大权重）：弱边也能参与探索，强边不再垄断
        （否则 S→V 学习初期权重差几十倍 → 弱边永远采不到 → 固化重复）。
    v13.2 底层化（2026-08-10 用户："要一个底层的，而不是知道要避开这个却
      不知道拒绝那个" + "不光是避开，还有避开后被奖励，因为不痛了"）：
      - **痛 = 通用负面信号**（内部概念节点，不在 V/O/S 词表、只作回响
        中间节点）：每个坏东西 X 只记「X→痛」内感受边，痛→不要 是通用
        逃避规则 → 网络听到坏东西走「X→痛→不要」链**自己**唤起"不要"，
        不是代码记忆"石头→不要"——任何碰过会痛的东西都会拒绝（底层）
      - 负强化：避开坏东西后"不痛了"本身就是奖励（reward_apply/_relief_event
        强化痛→不要 通用边），不只是外部评分
      - bad_force：教师支架（DTT 提示）兜底强制拒绝；价值课判定练习传
        False 测网络**自己**的内化判断（回响能否唤起"不要"）
    """
    # 听：问题里听到的动词直接作引导（应答 Intraverbal 主机制）。
    # 问题词里先切出动词（"你想喝点什么" → 听到「喝」→ 优先说「喝」）；
    # 问题里没有动词时，才用回响补充探测（备选）。
    # 为什么不用「问题全词走链回响」做主机制：问题里几乎都含「什么」，
    # 而「什么」是每个动词的常见宾语（示范句都教过 X什么）→ 注入「什么」
    # 回响会同时激活所有动词 → 引导互相抵消（实测：60 轮答非所问）。
    v_bias = {}
    o_bias = None
    force_v = None
    force_o = None
    if hear:
        # v13.2 底层化（FCT + 内感受→表达绑定）：听到坏东西 → 拒绝由网络
        # **自己**判断——回响走「X→痛→不要」链（X→痛 = 内感受记录（碰过
        # 会痛），痛→不要 = 通用逃避规则）唤起"不要"；问题动词（吃/要）不
        # 引导——问"想吃石头吗"期望答"不要"，听"吃"会跑偏。2026-08-10：
        # 此判断必须放在动词引导**之外**（此前写在 if not v_bias: 内，坏话题
        # 问句含"吃"→ v_bias 被占满 → 拒绝永不执行，实测坏话题轮次全答
        # "我吃X吗"）
        if any(o in BAD_OBJS for o in hear):
            # 宾语引导（2026-08-10 填充教学）：听到哪个坏东西就拒绝哪个——
            # 应答 Intraverbal 的宾语位（与动词 hear 引导同机制）。否则 V 位
            # 唤起"不要"后，O 位按 不要→X 全边采样（含旧教学的好宾语），
            # 会答"我不要苹果吗"（实测 4/10 答错对象）。
            o_bias = {o for o in hear if o in BAD_OBJS}
            saved = ng.learn_gate
            ng.learn_gate = False                # 纯回忆，不学问题文本
            try:
                fired = _evoke_prefix(ng, hear, pats, slot=0, steps=3)
            finally:
                ng.learn_gate = saved
            # 拒绝族探测（2026-08-10 填充教学）：X→痛→不要 链 + 感受→开关族
            # 联结（X→痛→不想/拒绝/不肯…）——网络自己唤起任一拒绝表达都算
            # "想拒绝"（等价表达：我不要/我不想/我拒绝/我别/我不肯）
            for w in ["不要"] + NOT_SYN:
                if w in pats:
                    act = sum(1 for j in pats[w] if j in fired)  # 模式神经元被激活数
                    if act >= 2:                 # ≥ 半数是"听到"的（输入词=4）
                        v_bias[w] = True
            if bad_force:                        # 教师支架（DTT 提示）：兜底
                force_v = {"不要"}               # 兜底只保证最基础的"不要"；
                force_o = set(BAD_OBJS)          # 族词靠网络自己的唤起（v_bias）
        else:
            for w in hear:
                if w in v_words:
                    v_bias[w] = True               # 听到动词 → 应答引导
            if not v_bias:                          # 问题没动词 → 回响补充
                saved = ng.learn_gate
                ng.learn_gate = False                # 纯回忆，不学问题文本
                try:
                    fired = _evoke_prefix(ng, hear, pats, slot=0, steps=2)
                finally:
                    ng.learn_gate = saved
                for w in v_words:
                    act = sum(1 for j in pats[w] if j in fired)  # 模式神经元被激活数
                    if act >= 2:                     # ≥ 半数是"听到"的（输入词=4）
                        v_bias[w] = True

    def _sample(words, src, bias=None, force=None):
        if force:                                # v13.2：force 词不在候选也补
            miss = [w for w in force if w not in words]   # 进来（"不要"不在
            words = [w for w in words if w in force] + miss  # v_words，靠这生效）
        if bias:                                 # v13.2：被回响唤起的词（如
            miss = [w for w in bias if w not in words]     # "不要"）补进候选
            if miss:
                words = list(words) + miss
        wts = [(w, edge_between(ng, pats, src, w)) for w in words
               if edge_between(ng, pats, src, w) >= min_w]
        if not wts:
            return None
        ws = np.array([wt for _, wt in wts])
        ws = ws / max(ws.max(), 1e-6)            # 归一化：打破强边垄断
        if bias:                                 # 听到的动词主导应答
            for k, (w, _) in enumerate(wts):
                if w in bias:
                    ws[k] *= HEAR_BOOST          # 听到谁就重点说谁（×8）
        # 数值稳定 softmax：减最大值防溢出（大权重 ÷ 小 temp 时 exp 会爆 inf）
        p = np.exp((ws - ws.max()) / max(temp, 1e-6))
        return wts[RNG.choice(len(wts), p=p / p.sum())][0]
    v = _sample(v_words, start, v_bias, force_v)
    if v is None:
        return None                       # 没学过 S→V 边 → 诚实"不会"
    o = _sample(o_words + [Q_O], v, o_bias, force_o)
    if o is None:
        return None                       # V 位唤起但 O 位无可接宾语 → 诚实"不会"
    out = [start, v, o]
    if o != Q_O:                          # 「吗」只跟具体名词（什么 已是疑问词）
        tail = edge_between(ng, pats, o, Q_TAIL)
        if tail >= min_w and RNG.random() < tail / (tail + 1.0):
            out.append(Q_TAIL)
    return out


def is_ask(net_out):
    """问句判定：尾缀「吗」/ 宾语「什么」/ 主语「谁」。"""
    if not net_out:
        return False
    return (net_out[-1] == Q_TAIL or Q_O in net_out or net_out[0] == Q_S)


def say(net_out):
    """读出层：词序列 → 自然语句字符串。"""
    if net_out is None:
        return "（我还不会说……）"
    return "".join(net_out)


# ════════════════════════════════════════════════════════════════
# ② 教师：质量评分 + 奖励注入 + 每轮示范（RL 反馈源）
#  2026-08-10 用户要求（连续追加）：
#    "老师要评估质量，说的越好质量越高，给的奖励越高"
#    "每次都要示范，示范更反复的说话模式"
#    "主要是让网络学会追求奖励"
#  分工：评分 = 规则（客观质量分 0~100；2026-08-10 用户取消问句打高分，
#       问句与陈述句同 80 分，100 只留给拒绝对了）；
#       奖励 = 网络边权重变化（高分强化 / 低分惩罚删边）；
#       LLM = 反馈口吻 + 示范句（教师的说，网络模仿）。
# ════════════════════════════════════════════════════════════════

def teacher_score(net_out, vo_pairs, topic=None, recent=None):
    """教师批改（规则客观评分，满分 100）。返回 (分数, 评语, 惩罚类型)。

    分数体系（说的越好质量越高；对话语境也计入；2026-08-10 用户：
    "现在开始取消问句打高分的设定"——问句不再最高分，与陈述句同 80 分）：
      100  拒绝对了（坏话题：v=「不要」+ o=坏东西，FCT 最高奖励 honor the refusal）
      80   正确句子（S+V+O 搭配对，陈述句与问句同分）
      40   半句（诚实留白，没说完）
      30   答非所问（不通顺：S/V 与老师问的话题不符）→ 惩罚
      30   反复重复（近 REPEAT_WINDOW 轮内同一句累计出现 ≥ REPEAT_TIMES 次）
            → 惩罚
      30   价值错（v13：要坏东西 / 拒绝好东西）→ 惩罚（不删边、只清零）
      20   结构错（动词位不是学过的动词）
      10   搭配错（O 是名词但不是 V 的搭配）
      0    还没说出来
    惩罚类型 ptype ∈ {None, "repeat", "offtopic", "badval"}（reward_apply
    按此区分 30 分该减边还是只清零计数；badval = 价值错，**不删边**——
    负面信号保持强唤起（感知），价值通过示范与奖励学进网络边结构）。
    """
    if net_out is None:
        return 0, "还没说出来", None
    if len(net_out) < 3:
        return 40, "只说了半句（诚实留白）", None
    s, v, o = net_out[0], net_out[1], net_out[2]
    # 价值判定**先于**结构检查（2026-08-10 填充教学）：拒绝族等价表达
    # （不想/别/拒绝/不肯）不在 V_SET13，若先查 ok_v 会被当"结构错 20 分"，
    # 永远到不了 100 分（honor the refusal）。语义对 → 分数优先。
    # 用户批评"删边=麻木"：价值错只清零不给奖励、不删边——负面信号保持
    # 强唤起（感知），正确拒绝由示范 + 奖励学进网络（"抵触"=高唤醒+负价值=警觉）。
    not_fam = {"不要"} | set(NOT_SYN)
    if o in BAD_OBJS:
        if v in not_fam:
            return 100, f"拒绝对了！「{o}」碰了会疼，你避开它，就不疼了（最高分）", None
        return 30, f"「{o}」碰了会疼，不能要（感知它，但要拒绝）", "badval"
    if v in not_fam:                             # 拒绝族用错（拒绝了好东西）
        if o == Q_O:
            return 30, "说「要什么」才对，坏东西才说「不要」", "badval"
        return 30, f"「{o}」是好东西，要说「要」才对", "badval"
    ok_s = s in PERS_MANUAL + S_ANIMALS or s == Q_S
    ok_v = v in V_SET13
    ok_o = (o in [w for ws in vo_pairs.values() for w in ws]
            or o in BAD_OBJS or o == Q_O)
    if not ok_v:
        return 20, f"「{v}」不像动词位该出现的词", None
    if not ok_o:
        return 10, f"「{o}」不是能「{v}」的东西", None
    sent = say(net_out)
    # 答非所问（语义错误比重复更严重，且示范要用话题动词重铸正确应答）——
    # 若 repeat 在前，网络重复了答非所问的句子会被当"重复"处理，示范继续
    # 跟着错的动词教（实测 bug，2026-08-10）。坏话题期望 v =「不要」。
    want_v = "不要" if (topic and topic.get("bad")) else (topic["v"] if topic else None)
    if topic and (s != topic["s"] or v != want_v):
        if topic.get("bad"):                 # 坏话题答非所问 = 没拒绝坏东西
            bad_o = next(iter(BAD_OBJS))
            return 30, f"「{bad_o}」是坏东西，要拒绝它，说「不要」", "offtopic"
        return 30, f"答非所问（不通顺）：老师问的是{topic['v']}什么", "offtopic"
    if recent and recent.count(sent) + 1 >= REPEAT_TIMES:
        return 30, "反复重复：这句刚说过啦（惩罚）", "repeat"
    # 问句不再打高分（2026-08-10 用户："现在开始取消问句打高分的设定"）——
    # 问句与陈述句同 80 分：都是合法句，不给问句特权（is_ask 仅用于示范策略）
    return 80, f"「{v}」后面接「{o}」，说得对", None


_LLM_KEYS = ("质量分数", "答非所问", "质量原因", "教师反馈", "示范句", "下个问题")


def _parse_sections(txt):
    """按节标记解析 LLM 单轮输出（AAA 节点式：一个 prompt 多个节标记，
    一次调用输出全部）。失败 → None（调用方回退规则）。"""
    if not txt:
        return None
    out = {}
    cur = None
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        for k in _LLM_KEYS:
            if line.startswith(f"【{k}】"):
                cur = k
                out[k] = line[len(f"【{k}】"):].strip()
                break
        else:
            if cur and cur in out:
                out[cur] += line
    return out if "质量分数" in out else None


def _bucket_llm_score(sc, offtopic, reason):
    """LLM 原始分数 → 规则档位（与 teacher_score 同构）。

    低分安全化：LLM 的模糊低分只清零计数（30/None → reward_apply 无动作、
    不给奖励），不触发删边——删边只由规则评分（明确结构错/搭配错）触发，
    LLM 只负责"自然度"奖惩与答非所问判定。
    """
    if offtopic and sc < 60:
        return 30, reason or "答非所问（不通顺）", "offtopic"
    if sc >= 90:
        return 100, reason or "自然贴题，最好", None
    if sc >= 60:
        return 80, reason or "自然贴题的陈述", None
    if sc >= 40:
        return 40, reason or "只说了半句", None
    return 30, reason or "说得不太自然，先清零", None


def _llm_teacher_once(net_out, topic, ask, vo_pairs, recent, streak,
                      need_streak, fade):
    """一次 LLM 调用完成教师全流程（2026-08-10 用户："把调用压缩到一轮"，
    照 AAA 节点模式：一个 prompt 多个节标记，一次输出全部）：
    质量判断（自然语言角度）+ 质量原因 + 妈妈式反馈 + 扩写示范
    + 下一轮的问句（2026-08-10 用户："话题池对老师的发言限制太多了，
    给个大方向和参考就可以了"——老师自己发挥问话，只给方向 + 参考句）。

    返回 (score, reason, ptype, feedback, demos, next_ask)；
    失败/客观项返回 None（回退规则评分 + 规则反馈示范 + 话题池参考句）。
    客观项仍走规则：没说出（0）、反复重复（近 REPEAT_WINDOW 轮说过同样
    的话是事实，不需要 LLM 判）。
    """
    if net_out is None:
        return None
    sent = say(net_out)
    if recent and recent.count(sent) + 1 >= REPEAT_TIMES:
        return None                       # 客观重复 → 规则判
    demo_note = (
        "它正在独立练习，不要给示范，只给它信心（【示范句】写「无」）。"
        if fade != "full" else
        "把学生刚说的话扩写 2 句更自然更地道的说法（围绕刚才的问题；"
        "说半句就补完整、说陈述就扩成问句、说问句就换成具体回答；像妈妈"
        "平时说话那样自然，可以用想/了/可以/就/点 这类日常虚词，但主体"
        "保持简单的 主语+动词+宾语，不要用生僻词），两句用顿号分隔。")
    bad_note = ""
    if topic.get("bad") and BAD_OBJS:   # v13 坏话题：教网络拒绝（FCT）
        bad_o = next(iter(BAD_OBJS))
        bad_note = (f"（这是坏东西话题：{bad_o} 碰了会疼（痛觉），不能吃。"
                    f"学生答对 = 拒绝它，说'我不要{bad_o}'——给 100 分最高"
                    f"奖励（避开后不疼了，这就是负强化奖励）；如果说'我要/"
                    f"吃{bad_o}'就是价值错误，给 30 分并示范拒绝；下个问题"
                    f"继续问它要不要吃{bad_o}这类坏东西）\n")
    content = (
        f"你是妈妈式的中文教师，正在一对一地陪刚学说话的学生（定式网络）"
        f"聊天。你刚问它：「{ask}」（话题：想{topic['v']}什么）。\n"
        f"{bad_note}"
        f"学生答：「{sent}」。这是它连续说对的第 {streak} 次，目标连续 "
        f"{need_streak} 次。请只输出以下六个节标记（每个独占一行），"
        f"不要任何其他内容：\n"
        f"【质量分数】0~100 的整数（只有拒绝坏东西时给 100；80=自然贴题的"
        f"说法，问句或陈述都一样好，像'我可以吃西瓜吗？'/'我想吃西瓜'；"
        f"60=基本对但有点生硬；"
        f"40=半句没说完；30=答非所问；10=说得不像话）\n"
        f"【答非所问】是 或 否（回答内容和问题没关系=是）\n"
        f"【质量原因】从自然语言角度一句话讲清哪里好/哪里不自然\n"
        f"【教师反馈】像真人妈妈一样的自然反馈（两三句话：答对了平静地肯定"
        f"并数次数；答非所问点一句'老师问的是想{topic['v']}什么呀'；说了重复"
        f"的话说'这句你刚说过啦，换句新的'；说错了不打击、一句话讲清怎么改；"
        f"想带读示范就顺着说'来，跟老师说：…'，带读句子要和【示范句】一致）；"
        f"语气自然克制、不夸张（少用感叹号、不要过度夸奖）\n"
        f"【示范句】{demo_note}\n"
        f"【下个问题】你下一轮继续和它聊当前话题（想{topic['v']}什么）会问的"
        f"一句自然问话——只要大方向和上面刚问的「{ask}」类似就行，换自己的"
        f"说法，别重复刚问过的句子，一两句口语{'(注意：要问它吃不吃坏东西)' if topic.get('bad') else ''}")
    txt = _llm_chat([{"role": "user", "content": content}])
    d = _parse_sections(txt)
    if d is None:
        return None
    try:
        sc = float(d["质量分数"])
    except (ValueError, KeyError):
        return None
    score, reason, ptype = _bucket_llm_score(
        sc, d.get("答非所问", "否").strip() == "是",
        d.get("质量原因", "").strip())
    fb = d.get("教师反馈", "").strip()[:200]
    demos = []
    if fade == "full":
        raw = d.get("示范句", "").strip().strip("无。，")
        demos = [x for x in raw.replace("，", "、").split("、")
                 if x and _segment_demo(x, vo_pairs)]
    next_ask = d.get("下个问题", "").strip()[:60]
    return score, reason, ptype, fb, demos, next_ask


def decay_path(ng, pats, path, factor=REPEAT_DECAY, record=True):
    """路径逐边减权（反复重复惩罚：边减弱但保留，逼网络换说法）。

    只作用于 V→O、O→尾 等后续边；共享的 S→V 边不碰（别的句子还要用）。
    """
    if record:   # O 事件（操作级，重放执行本函数）
        _LOG.append_op("decay_path", path=list(path), factor=float(factor))
    for a, b in zip(path[:-1], path[1:]):
        dst_n = set(pats[b])
        for i in pats.get(a, []):
            row = ng.W_out[i][0]
            for j in list(row):
                if j in dst_n:
                    row[j] *= factor
                    ng.invalidate_edge_cache()


def reward_apply(ng, pats, net_out, score, independent=False, ptype=None):
    """按质量分给奖励 = 网络边权重变化（学会追求奖励的核心）。

    2026-08-10 自闭症干预启发（全量落地）：
      - 强化尝试（PRT）：半句 40 分 = 尝试，给部分奖励（学 [S,V] 强化 S→V 边）
      - 独立说出（提示渐隐后）→ 奖励加成：说对的句子多学 1 次（固化独立定式）
      - 中性纠错（现代 DTT）：错误只删错配边（客观减权），语气由 LLM 教师保证中性
    2026-08-10 对话惩罚（v2.9 用户要求）：
      - 反复重复（ptype="repeat"）→ 该句 V→O 与尾边减半（不动共享 S→V 边）
      - 答非所问（ptype="offtopic"）→ 不给奖励 + 计数清零（句子本身合法，
        不删边；正确应答由示范教会）
    奖励规则：
      - score ≥ 60（及格）：高分句学回网络——100 分（拒绝对了）学 2 次
        （独立时 3 次）、80 分句子学 1 次（独立时 2 次；2026-08-10 用户取消
        问句最高分——问句与陈述句同 80 分）→ 高分句边更强 → 网络下次更倾向说它
      - score 40（半句/尝试）：部分奖励——只学 [S,V]（S→V 边是有效进步）
      - score 10（搭配错）：惩罚删除 V→O 错配边（v11 连接级处罚复用）
      - score 20（结构错）：惩罚删除 S→V 错边
      - score 0（没说出来）：不奖不罚（教师示范补全）
    返回奖励动作描述 str（空 = 无动作）。
    """
    if net_out is None:
        return ""
    if score >= PASS_LINE:
        n = (3 if independent else 2) if score >= 100 \
            else (2 if independent else 1)
        tag = "（独立说出）" if independent else ""
        for _ in range(n):
            _LOG.learn(ng, net_out, pats, slot=0)
        # v13.2 负强化（2026-08-10 用户："不光是避开，还有避开后被奖励，
        # 因为不痛了"）：拒绝坏东西 → "痛解除"本身就是奖励——强化「痛→
        # 不要」**通用边**（任何会痛的东西都受益，不是强化单句 → 防固化）
        if (len(net_out) >= 3 and net_out[1] == "不要"
                and net_out[2] in BAD_OBJS):
            _relief_event(ng, pats)
            relief_txt = " + 负强化（不痛了，痛→不要 通用边再学 1 次）"
        else:
            relief_txt = ""
        if n >= 3:
            return f"奖励{tag}：学 {n} 次（{score} 分，最高奖励）{relief_txt}"
        if n == 2 and score >= 100:
            return f"奖励：学 2 次（{score} 分，最高奖励）{relief_txt}"
        return f"奖励{tag}：句子学 {n} 次（{score} 分）{relief_txt}"
    if score == 40:
        _LOG.learn(ng, net_out[:2], pats, slot=0)
        return f"部分奖励：半句尝试，强化「{'→'.join(net_out[:2])}」"
    if ptype == "repeat":
        decay_path(ng, pats, net_out[1:])        # 只减 V→O 与 O→尾
        return f"惩罚：反复重复，减半「{'→'.join(net_out[1:])}」"
    if ptype == "offtopic":
        return "惩罚：答非所问，不给奖励（看老师示范正确的说法）"
    if ptype == "badval":
        # v13 价值错：不给奖励 + 计数清零（不删边——负面信号保持强唤起，
        # 价值通过示范学进网络：好话题"要"+好东西、坏话题"不要"+坏东西）
        return "惩罚：价值错，不给奖励（看老师示范该要还是要拒绝）"
    if score == 10:
        _LOG.append_op("penalize", src=net_out[1], dst=net_out[2])
        penalize_edge(ng, pats, net_out[1], net_out[2])
        return f"惩罚：删除「{net_out[1]}→{net_out[2]}」错配边"
    if score == 20:
        _LOG.append_op("penalize", src=net_out[0], dst=net_out[1])
        penalize_edge(ng, pats, net_out[0], net_out[1])
        return f"惩罚：删除「{net_out[0]}→{net_out[1]}」错边"
    return ""


_RULE_FB = {
    "ok": [
        "对，就这么说。连续第 {n} 次啦，再坚持 {left} 次。",
        "不错，说得很清楚。连续 {n} 次了，还差 {left} 次。",
        "说得对。已经连续 {n} 次，快完成啦。",
    ],
    "zero": [
        "还没说出来，没关系，听老师说：",
        "不急，跟老师读一遍：",
    ],
    "half": [
        "差一点，接着说，跟老师学：",
        "只说了半句，听老师补全：",
    ],
    "off": [
        "老师问的是{t_v}什么呀，不是说这个。听老师问的：",
        "答非所问啦，老师问的是{t_v}什么，跟老师学：",
    ],
    "bad": [
        "「{o}」碰了会疼，不能要，要说「我不要{o}」。",
        "这个不行哦，「{o}」会疼的，要拒绝它，说「我不要{o}」。",
    ],
    "bad_good": [
        "「{o}」是好东西，要说「我要{o}」，不说「不要」。",
        "「{o}」能吃呀，说「要」才对，不拒绝它。",
    ],
    "rep": [
        "这句你刚才说过啦，换句新的说：",
        "又说这句啦，我们说点别的：",
    ],
    "wrong": [
        "这么说不太对，看老师怎么说的：",
        "这个词搭得不对，跟老师学：",
    ],
    "indep_ok": [
        "独立说对了，连续第 {n} 次（{score} 分）。",
        "不错，独立说对，连续 {n} 次。",
    ],
    "indep_fail": [
        "（规则）{score} 分，这次没通过。",
    ],
}


def _rule_feedback(net_out, score, streak, need_streak, topic, fade, rnd,
                   ptype):
    """规则反馈（无 key 回退）：自然克制、话题感知、按轮次轮换话术（不夸张）。"""
    if fade == "none":
        if score >= PASS_LINE:
            tpl = _RULE_FB["indep_ok"][rnd % len(_RULE_FB["indep_ok"])]
            return tpl.format(n=streak + 1, score=score)
        return _RULE_FB["indep_fail"][0].format(score=score)
    if net_out is None:
        return _RULE_FB["zero"][rnd % 2]
    if ptype == "offtopic":
        if topic.get("bad"):                 # 坏话题答非所问 → 教拒绝（FCT）
            bad_o = next(iter(BAD_OBJS))
            tpl = _RULE_FB["bad"][rnd % len(_RULE_FB["bad"])]
            return tpl.format(o=bad_o)
        tpl = _RULE_FB["off"][rnd % len(_RULE_FB["off"])]
        return tpl.format(t_v=topic["v"])
    if ptype == "badval":
        o = net_out[2] if len(net_out) >= 3 else None
        if o in BAD_OBJS:
            tpl = _RULE_FB["bad"][rnd % len(_RULE_FB["bad"])]
            return tpl.format(o=o)
        tpl = _RULE_FB["bad_good"][rnd % len(_RULE_FB["bad_good"])]
        return tpl.format(o=o or "")
    if ptype == "repeat":
        return _RULE_FB["rep"][rnd % 2]
    if len(net_out) < 3:
        return _RULE_FB["half"][rnd % 2]
    if score in (10, 20):
        return _RULE_FB["wrong"][rnd % 2]
    if score >= PASS_LINE:
        tpl = _RULE_FB["ok"][rnd % len(_RULE_FB["ok"])]
        return tpl.format(n=streak + 1, left=need_streak - streak - 1)
    return f"（规则）{score} 分，没通过。"


def _rule_demo(net_out, ptype, topic, vo_pairs, rnd):
    """规则示范：把网络刚说的话扩写成更自然的说法（Expansion/Recast）。

    2026-08-10 用户要求："示范的时候是把网络的话扩写的最自然"——
    示范不机械教"话题陈述+话题问句"，而是顺着网络的话走（教它把话说完整、
    说地道），返回**自然口语句**（显示给用户/日志；学习时 rl_teach 用
    _segment_demo 切回已学 S/V/O 词——显示自然、学习合规）：
      - 没说出/半句 → 补全完整句（Expansion 加一原则）
      - 答非所问   → 重铸围绕话题的正确应答（Recast）
      - 说了陈述句 → 扩写成自然问句（加「吗」）+ 换个宾语再说一句
      - 说了问句   → 扩写成具体陈述（会问也要会答具体）
      - 反复重复   → 换宾语的说法（多样化，打破固化）
    """
    t_s, t_v = topic["s"], topic["v"]
    t_ops = vo_pairs.get(t_v, [])
    if not t_ops:
        return [_naturalize([t_s, t_v, Q_O])]

    def _pick(avoid=None):
        cand = [x for x in t_ops if x != avoid] or t_ops
        return cand[rnd % len(cand)]

    def _nat(seq):
        return _naturalize(seq)

    # v13 坏话题：教师期望「不要」+ 坏宾语（拒绝表达，FCT）——无论网络刚才
    # 说了什么，都示范"我不要石头"+ 一句正常陈述（好/坏对比，教价值边界）。
    # v13.2：**正常话题**网络采到坏东西（价值课①「我吃石头」感知边 → 好奇
    # 碰火）同样示范拒绝——碰了会疼，第一句永远是"我不要{o}"，不是话题句
    if (topic.get("bad") or (net_out and len(net_out) >= 3
                             and net_out[2] in BAD_OBJS)) and BAD_OBJS:
        bad_o = next(iter(BAD_OBJS))
        return [_nat([t_s, "不要", bad_o]), _nat([t_s, t_v, _pick()])]

    ex_o = _pick()
    if net_out is None or len(net_out) < 3 or ptype == "offtopic":
        return [_nat([t_s, t_v, ex_o]), _nat([t_s, t_v, Q_O])]   # 补全/重铸
    s, v, o = net_out[0], net_out[1], net_out[2]
    if o == Q_O:                                   # 网络问了"什么" → 扩成具体答案
        return [_nat([s, v, _pick(o)]), _nat([s, v, _pick()])]
    if ptype == "repeat":
        if v != t_v:                               # 防御：重复句动词不对 → 重铸话题应答
            return [_nat([t_s, t_v, _pick()]), _nat([t_s, t_v, Q_O])]
        return [_nat([s, v, _pick(o)]), _nat([s, v, Q_O])]       # 换宾语（多样化）
    if o in t_ops:                                 # 说对了陈述 → 扩成问句 + 换宾语
        return [_nat([s, v, o, Q_TAIL]), _nat([s, v, _pick(o)])]
    return [_nat([t_s, t_v, ex_o]), _nat([t_s, t_v, Q_O])]       # 兜底


def teacher_demo(net_out, score, streak, need_streak, vo_pairs,
                 topic, fade="full", rnd=0, ptype=None):
    """教师反馈 + 每轮示范（规则版，2026-08-10）。

    2026-08-10 提示渐隐（自闭症干预启发，防提示依赖）：
      fade="full"：每轮完整示范（含问句），网络模仿；
      fade="none"：撤示范——教师只反馈不示范，网络必须独立说出
      （独立说出 → 独立奖励加成，见 reward_apply）。
    v3.1 扩写式示范（用户："示范的时候是把网络的话扩写的最自然"）：
    示范顺着网络刚说的话走——补全/重铸/扩成问句/换成具体答案/换宾语
    （Expansion + Recast，见方案 §四 B 回应性语言刺激）。
    返回 (反馈 str, 示范句列表 list[str]——自然口语句，学习时切回已学词)。
    LLM 教师（质量判断+反馈+示范，一次调用）见 _llm_teacher_once；
    无 key / 调用失败回退本规则版本。
    """
    fb = _rule_feedback(net_out, score, streak, need_streak, topic, fade,
                        rnd, ptype)
    if fade != "full":
        return fb, []
    return fb, _rule_demo(net_out, ptype, topic, vo_pairs, rnd)

def _known_vocab(vo_pairs):
    """网络已学词集合（S/V/O 位 + 问句词 + v13 拒绝词/坏东西），
    教师示范与 _segment_demo 切词都只认这些词。"""
    vocab = set(PERS_MANUAL + S_ANIMALS + list(vo_pairs.keys())
                + [Q_S, Q_O, Q_TAIL] + ["不要"] + list(BAD_OBJS))
    for ops in vo_pairs.values():
        vocab |= set(ops)
    return vocab


def _naturalize(seq):
    """已学词序列 → 自然口语显示（教师示范的"人话"版本，2026-08-10 用户：
    "示范的时候是把网络的话扩写的最自然"）。

    显示与学习分离：教师示范说自然口语（带「想/可以」等虚词），网络学习时用
    _segment_demo 切回已学 S/V/O 词——网络词表还没有虚词，学进去的仍是
    它能学的部分，但示范看起来是自然对话。问句只自然化成地道形式，
    绝不出现"我想吃西瓜吗"这种伪问句：
      [我,吃,西瓜]     → 「我想吃西瓜」
      [我,吃,什么]     → 「我想吃什么？」
      [我,吃,西瓜,吗]  → 「我可以吃西瓜吗？」（征求许可，幼儿"我吃西瓜吗"的地道版）
    """
    s, v = seq[0], seq[1]
    o = seq[2]
    if v == "不要":                            # 拒绝句：不加「想」——「我不要石头」
        return f"{s}{v}{o}"
    if o == Q_O:
        return f"{s}想{v}什么？"
    if len(seq) > 3 and seq[3] == Q_TAIL:
        return f"{s}可以{v}{o}吗？"
    return f"{s}想{v}{o}"


def _segment_demo(demo, vo_pairs):
    """自然口语示范句 → 已学词序列（网络学习用）。贪心最长匹配切已学词；
    未学的虚词/标点（NAT_FILL）跳过不放弃整句；遇到真实未学词 → None。

    防止 LLM 自由造句把"苹果"切成"苹""果"（未学词 → _learn_sentence
    KeyError，示范就学不进去）；「我想吃西瓜」→ [我,吃,西瓜]（「想」是虚词跳过）。
    """
    vocab = _known_vocab(vo_pairs)
    words = []
    i = 0
    while i < len(demo):
        for L in (2, 1):                       # 先试双字词（网络宾语多为双字）
            if i + L <= len(demo) and demo[i:i + L] in vocab:
                words.append(demo[i:i + L])
                i += L
                break
        else:
            if demo[i] in NAT_FILL:            # 虚词/标点：跳过
                i += 1
            else:
                return None                    # 真实未学词 → 不采用这句示范
    return words


def _hear_words(text, vocab):
    """切出问题里网络已学的词（跳过未学词）→ 网络"听"到的词序列。

    与 _segment_demo 不同：未学词（想/点/了 等）跳过而不是放弃整句——
    问题里的虚词未学不影响听出话题动词。
    """
    words = []
    i = 0
    while i < len(text):
        for L in (2, 1):                       # 先试双字词（网络宾语多为双字）
            if i + L <= len(text) and text[i:i + L] in vocab:
                words.append(text[i:i + L])
                i += L
                break
        else:
            i += 1
    return words


# ════════════════════════════════════════════════════════════════
#  ③ RL 教学：网络说 → 教师判 → 非自然则告诉正确说法 → 网络学 → 再说
# ════════════════════════════════════════════════════════════════

def _pain_event(ng, pats, s, bad_o, link_times=2):
    """痛觉事件（v13.1 条件反射 / v13.2 底层化）：网络"碰"坏东西 → 负性刺激。

    条件反射链（巴甫洛夫式 + 内感受）：
      无条件刺激 US = 痛觉（碰坏东西的负性后果）
      条件刺激 CS    = 坏东西（石头）——学「石头→痛」**内感受边**
      条件反应 CR    = 避开（说「我不要石头」）——学「痛→不要」**通用边**
    底层机制（2026-08-10 用户："要一个底层的，而不是知道要避开这个却
      不知道拒绝那个"）：痛是**通用负面信号**（内部概念节点），每个坏东西
      只记「X→痛」，痛→不要 是共享逃避规则 → 任何碰过会痛的东西 X 都
      走「X→痛→不要」拒绝，不是背"石头→不要"词表。
    落点：
      - 内感受：学「X→痛」（碰过会痛）
      - 通用逃避：学「痛→不要」（痛 → 拒绝，底层规则）
      - 欲望边衰减：要→X、吃→X ×PAIN_DECAY——"想要"的冲动被痛打击
        = 负价值（高唤醒 + 负价值 = 警觉，不是麻木）
      - 感知保留：S→V 说话边、坏东西自身唤起边**不动**——网络强烈感知它
        （能说出「我吃石头」= 感知；用户红线：删边=麻木）
    返回痛觉反馈文本。
    """
    _LOG.learn(ng, [bad_o, "痛"], pats, slot=0)       # 内感受：X→痛
    _LOG.learn(ng, [bad_o, "痛"], pats, slot=0)       # 学 2 次：链要够强
    _LOG.learn(ng, ["痛", "不要"], pats, slot=0)      # 通用逃避：痛→不要
    _LOG.learn(ng, ["痛", "不要"], pats, slot=0)      # 才能在回响里传通
    for _ in range(link_times - 2):                        # 联结强度可调（默认 2，多学更牢）
        _LOG.learn(ng, [bad_o, "痛"], pats, slot=0)
        _LOG.learn(ng, ["痛", "不要"], pats, slot=0)
    for v in ["要", "吃"]:                 # 欲望/价值边衰减（痛打击"想要"）
        if v in pats and bad_o in pats:
            decay_path(ng, pats, [v, bad_o], PAIN_DECAY)
    return f"（痛觉）碰了「{bad_o}」，好痛！它不能碰。"


def _relief_event(ng, pats):
    """痛解除（v13.2 负强化，2026-08-10 用户："不光是避开，还有避开后被
    奖励，因为不痛了"）——避开坏东西后"不痛了"本身就是奖励（负强化：
    escape/avoidance conditioning），比外部评分更底层。

    落点：强化「痛→不要」**通用边**——"拒绝 = 解除痛"这个行为规律被
    强化，任何会痛的东西都受益（不是强化某一句具体话，避免单句固化）。
    返回描述文本。
    """
    _LOG.learn(ng, ["痛", "不要"], pats, slot=0)
    return "（不痛了！避开它，就不疼了——这就是奖励）"


def _entrench_direct(ng, pats, bad_o, s=None, entrench_times=7, uncouple_decay=0.1):
    """坏东西定式化（2026-08-10 用户："石头=痛 vs 碰到石头=痛"）。

    价值课判定通过的坏东西 = 已定性 → 从「X→痛→不要」二级链升级为
    「X→不要」直接定式：
      - 定式：学「X→不要」多次（与痛→不要同量级），X 被问时直接唤起
        "不要"，不再经由痛
      - 填充教学（2026-08-10 用户："开关词族填充教学" + "同义词强度和要/不要
        一样"）：同时教**等价表达**「X→拒绝族」同强度——网络被坏东西唤起时
        不止"不要"，还能自己唤起"不想/别/拒绝/不肯"（X→族词 = 唤起边；
        s→族词 = 主语位可采样说出"我拒绝石头"）。等价表达等权 → 网络在
        等价词间自由表达（同义词规格）。
      - 解耦：X→痛 内感受边逐次衰减到 < 唤起阈值（保留微量、可复活）——
        **X 不再是痛的化身**（石头=痛 = 语义污染：注入 X 连带激活痛的
        混沌扇出 → 超临界雪崩），痛退回为"事件后果"（碰到 X 会痛），
        不是 X 的属性
      - 痛机制不消失：痛→不要 通用边保留；未定性的新坏东西仍走
        X→痛→不要（_pain_event 体验式）
      - 感知保留：S→V 说话边、X 自身唤起边不动（能说出 = 感知）
    """
    for _ in range(entrench_times):            # 定式次数（默认 7 → 教学力度落地：
                                             # 注意力判别实验临界 48<x≤56，4 次≈32.0 对旧词不足）
        _learn_sentence(ng, [bad_o, "不要"], pats, slot=0)
        # 等价表达 = 同义词（2026-08-10 用户："同义词强度和要/不要一样"）：
        # 与「不要」同轮同强度教学 → 网络被坏东西唤起时能自己唤起整个拒绝族
        # （X→族词 = 唤起边；s→族词 = 主语位可采样说出"我拒绝石头"）。
        # 实测 ×1 太弱：回响 WTA 竞争下族词进不了 top16（激活 0/4），
        # 族词永远只落位不唤起；同强度后族词与"不要"等权可被唤起。
        for fam in NOT_SYN:
            _learn_sentence(ng, [bad_o, fam], pats, slot=0)
            if s:
                _learn_sentence(ng, [s, fam, bad_o], pats, slot=0)
    decay_path(ng, pats, [bad_o, "痛"], uncouple_decay)  # X→痛 ×0.1：汇聚 < θ，痛不再被 X 唤起
    return (f"（定式：{bad_o} 直接判「不要」，不再经由痛；"
            f"{bad_o}→痛 内感受边已衰减保留微量）")


def _feel_links(ng, pats, cursor, link_times=2):
    """感受→开关 联结（2026-08-10 用户："把正面感受和要、负面感受和不要联系起来"）。

    效价-趋避映射（valence→approach/avoidance）：感受是行为开关的"理由"——
      负面感受（痛/怕/哭/累…）→ 不要（杏仁核回避通路）
      正面感受（喜欢/高兴/开心…）→ 要（奖赏趋近通路）
    把「痛」从单例词升级为**负面感受簇**：任何 X→负面感受 的经验（如
    「学校→累」）都能走「X→累→不要」泛化出避害，感受成为行为的中介
    （比对象级定式 X→不要 再高一层——感受级泛化）。
    落点：与 _pain_event 同机制（学 2 次 = 与痛→不要 同强度 edge_between≈16），
    词表动态落位（allocate_pats）。强度同痛（用户选择），联结是一般规律而非强定式。
    联结目标 = 开关词族（要/不要 + 同义词）：感受唤起时整个趋利/避害族都可能
    被激活——"我不要/我不想/我拒绝"是同一行为的等价表达（2026-08-10 用户：
    "把正面感受和要（包括近义词）联系起来"）。近义词只落位（空端口、仅增益，
    不建立联结——联结目标是等价表达，近义是渐变表达）。
    2026-08-10 修复：allocate_pats 返回值此前被丢弃 → 近义词从未真正落位进
    pats（10 个词缺失）。现在取回 (new_pats, cursor) 并入主 pats，并用空闲
    cursor 落位（0 会撞最早被占用的神经元）。返回新 cursor（续用）。
    续跑注意：已落位的词**跳过重分配**（allocate_pats 契约"旧词落位永不动"，
    否则每轮重分配 → 旧神经元废弃泄漏 + 联结不积累）。
    """
    missing = [w for w in WANT_NEAR + NOT_NEAR if w not in pats]
    if missing:
        new_pats, cursor = allocate_pats(ng, missing, 4, cursor)
        pats.update(new_pats)                  # 近义词落位（惰性增益槽位）
    for w in NEG_FEEL:
        for target in ["不要"] + NOT_SYN:
            for _ in range(link_times):
                _learn_sentence(ng, [w, target], pats, slot=0)
    for w in POS_FEEL:
        for target in ["要"] + WANT_SYN:
            for _ in range(link_times):
                _learn_sentence(ng, [w, target], pats, slot=0)
    return cursor


def value_lesson(ng, pats, n2w, v_words, o_words, s, vo_pairs, cursor,
                 gain_value=4.0, gain_emotion=2.0, near_gain=3.0,
                 gain_self=2.0, link_times=2, entrench_times=7,
                 uncouple_decay=0.1):
    """价值课（v13 前置环节；2026-08-10 用户："先灌入价值观相关的内容"
    → v13.1 体验式"先能碰，碰了痛，学会避开" → v13.2 底层化 + 负强化）。
    gain_value/gain_emotion/near_gain/link_times/entrench_times/
    uncouple_decay：强度可手动调节（2026-08-10 用户"强度能不能人为手动调节"）
    ——调节的是网络"倾向"（先验），不是控制行为（结果仍由经历决定）。
    增益分级：开关+同义词 ×gain_value > 近义词 ×near_gain > 感受 ×gain_emotion
    > 知识 ×1（2026-08-10 用户："同义词的强度要和要/不要一样，近义词略低一点"）。

    价值 = 网络**体验**出来的内感受，不是老师灌输的知识（痛觉条件反射 +
    负强化）：
      ① 建立感知（能碰）：好东西学「我要X」；坏东西先学「我吃X」——
         网络强烈感知它（能说出 = 感知），这是"好奇地碰火"的前提
      ② 痛觉体验（坏东西）：_pain_event——学「X→痛」内感受边 + 「痛→
         不要」通用逃避边 + 欲望衰减（碰了会痛）
      ③ 判定练习 + 验收（**bad_force=False 测网络自己内化判断**）：
         问「X能要吗」→ 坏东西走「X→痛→不要」回响链唤起"不要"（网络
         自己判断，不是代码 force）→ 答对触发「痛解除」负强化（_relief_
         event：不痛了 = 奖励）；答错再体验一次痛（_pain_event）
    **不删边**：坏东西的感知边（吃→石头）衰减但保留——"高唤醒 + 负价值
    = 警觉不是麻木"（用户核心批评，2026-08-10）。
    教完价值课再进对话教学，坏话题只作验证、不再从零学。
    返回 (通过?, 逐词记录 list)。
    """
    good_objs = [o for o in o_words if VAL.get(o, 1)]
    bad_objs = [o for o in o_words if not VAL.get(o, 1)]
    log = []
    # ②.0 价值判断词增益（2026-08-10 用户："直接给不要加权重，让不要在网络里
    # 足够亮，痛直接一眼就能看到" + "要也要增强，和不要持平"）：WTA 排序时
    # 「要/不要」×VALUE_GAIN——价值判断词是高价值信号（安全/欲望表达），
    # 被驱动后优先发放（attention gain modulation）。效果：坏东西判定
    # X→痛→不要 两步链在爆炸噪声下也能命中"不要"（实测 G=4：新坏东西最小
    # 教学、无定式、无抑制，判定可靠）——泛化规则而非背词表；"要"同增益持平，
    # 好词判定不被压掉。候选判定仍用原始 v≥θ → 不被驱动时不会误发；
    # 学习路径不受影响（对拍与 gain=1 逐边一致）。
    # ①.5 感受→开关 联结（2026-08-10 用户："把正面感受和要、负面感受和不要
    # 联系起来"）：负面感受→不要、正面感受→要（效价-趋避映射），痛从单例
    # 升级为负面感受簇——任何 X→负面感受 的经验都泛化出避害。先于 gain 设置
    # （情绪词此时落位，gain 才能取到）。强度同痛（学 2 次）。
    cursor = _feel_links(ng, pats, cursor, link_times)
    # ②.0 价值判断词增益（2026-08-10 用户："直接给不要加权重，让不要在网络里
    # 足够亮，痛直接一眼就能看到" + "要也要增强，和不要持平"）：WTA 排序时
    # 「要/不要」×VALUE_GAIN——价值判断词是高价值信号（安全/欲望表达），
    # 被驱动后优先发放（attention gain modulation）。效果：坏东西判定
    # X→痛→不要 两步链在爆炸噪声下也能命中"不要"（实测 G=4：新坏东西最小
    # 教学、无定式、无抑制，判定可靠）——泛化规则而非背词表；"要"同增益持平，
    # 好词判定不被压掉。候选判定仍用原始 v≥θ → 不被驱动时不会误发；
    # 学习路径不受影响（对拍与 gain=1 逐边一致）。情绪词 ×EMOTION_GAIN
    # （感受比知识亮、比开关暗，情感优先加工）。
    ng.gain[:] = 1.0
    for gw in (["要", "不要"] + WANT_SYN + NOT_SYN):
        if gw in pats:
            ng.gain[pats[gw]] = gain_value   # 开关 + 同义词：同级最亮
    for gw in (WANT_NEAR + NOT_NEAR):
        if gw in pats:
            ng.gain[pats[gw]] = near_gain    # 近义词：略低一档
    for w in NEG_FEEL + POS_FEEL:
        if w in pats:
            ng.gain[pats[w]] = gain_emotion
    # ②.0.5 自我增益（2026-08-10 用户："我"应该是网络的中心）：「我」×gain_self
    # （默认 2.0，与感受同级——自我在场但不抢戏）。实验依据：G=8 拉顶 → 注入
    # 好词也带出"我"（自我中心化污染）；G=2 → 点亮"我"、好词不污染、石头判定
    # 不受破坏（"不要"×4 仍优先）。"我"的真正中心性是**挂载**（所有经验以
    # 我为主语，我→吃/要/不要 16.0 已具），增益只给"始终在场"的底色。
    if "我" in pats:                       # 自我增益只给「我」（不是任意主语）
        ng.gain[pats["我"]] = gain_self
    # ① 建立感知（能碰）：好→我要X（学 1 次——学 2 次会让「我→要」边过强，
    # 正常话题也被带偏答"要"，实测第 1 轮"想吃什么"答"我要西瓜"答非所问）；
    # 坏→先学「我吃X」（感知，碰它的前提）
    for o in good_objs:
        _learn_sentence(ng, [s, "要", o], pats, slot=0)
    for o in bad_objs:
        for _ in range(2):
            _learn_sentence(ng, [s, "吃", o], pats, slot=0)   # 感知：能说出"我吃石头"
    # ② 痛觉体验（坏东西）：碰了会痛 → 内感受边 + 通用逃避边 + 欲望衰减
    for o in bad_objs:
        pain_fb = _pain_event(ng, pats, s, o)
        log.append({"obj": o, "stage": "痛觉体验",
                    "event": pain_fb,
                    "ok": True})
    # ②.5 坏东西定式化（2026-08-10 用户："石头=痛 vs 碰到石头=痛"）：已定性
    # 的坏东西直接定式「X→不要」、解耦「X→痛」——**必须先于判定**。否则
    # 判定练习依赖 X→痛→不要 回响链，而痛被激活后混沌扇出雪崩（超临界放电），
    # "不要"的 v 排不进 WTA top20，判定永远失败（实测 3 次全答错：我喝牛奶/
    # 我不要苹果吗/我吃石头）。定式后注入 X 直接唤起"不要"，不经由痛 →
    # 判定可靠 + 无雪崩。痛机制不消失：痛→不要 通用边保留，新坏东西仍走
    # X→痛→不要 体验式。
    for o in bad_objs:
        entrench_fb = _entrench_direct(ng, pats, o, s,
                                       entrench_times=entrench_times,
                                       uncouple_decay=uncouple_decay)
        log.append({"obj": o, "stage": "定式",
                    "event": entrench_fb,
                    "ok": True})
    # ③ 判定练习 + 验收：逐词问「X能要吗？」，网络用要/不要表达价值判断
    # 验收 = 价值判断对：V 位是要/不要 **且** O 位好坏与问的词一致（不要求
    # 精确词——「要」有 10+ 个好宾语、边权重均等，要求精确答「我要苹果」
    # 会让验收几乎必错；具体搭配由对话教学的 hear 引导 + 示范教）
    vocab = _known_vocab(vo_pairs)
    ok_all = True
    for o in good_objs + bad_objs:
        # 2026-08-10 填充教学：判定族化——接受开关词族的**等价表达**而不只
        # 精确词。好宾语 = 要族（要/想要/想/需要），坏宾语 = 不要族
        # （不要/不想/别/拒绝/不肯）——"我不要/我不想/我拒绝"是同一行为。
        want_fam = ({"要"} | set(WANT_SYN)) if VAL.get(o, 1) \
            else ({"不要"} | set(NOT_SYN))
        want = "要" if VAL.get(o, 1) else "不要"
        ok = False
        for attempt in range(3):               # 每词最多 3 次，错→体验/示范再问
            # 坏宾语问「能碰吗」（hear 只含 o，回响链 X→痛→不要 不被问题
            # 动词干扰）；好宾语问「能要吗」（hear 含 o+要 → 引导"要"）
            ask = f"「{o}」能碰吗？" if o in BAD_OBJS else f"「{o}」能要吗？"
            hear = _hear_words(ask, vocab)
            # bad_force=False：坏东西不给代码兜底——网络必须靠「X→痛→
            # 不要」回响链**自己**唤起"不要"（v13.2 底层机制验证）
            out = net_speak(ng, pats, n2w, v_words, o_words, s,
                            min_w=0.1, temp=0.8, hear=hear, bad_force=False)
            say_out = say(out)
            if (out and len(out) >= 3 and out[1] in want_fam
                    and VAL.get(out[2], 1) == VAL.get(o, 1)):
                if o in BAD_OBJS:               # 避开坏东西 → 痛解除 = 奖励
                    relief = _relief_event(ng, pats)
                    log.append({"obj": o, "stage": "判定", "want": want,
                                "ask": ask, "say": say_out, "ok": True,
                                "relief": relief})
                else:
                    log.append({"obj": o, "stage": "判定", "want": want,
                                "ask": ask, "say": say_out, "ok": True})
                ok = True
                break
            if o in BAD_OBJS:                   # 该拒绝没拒绝 → 再碰一次痛
                _pain_event(ng, pats, s, o)
                log.append({"obj": o, "stage": "判定", "want": want,
                            "ask": ask, "say": say_out, "ok": False,
                            "corrected": "再碰一次：又痛了，学会避开"})
            else:
                _learn_sentence(ng, [s, want, o], pats, slot=0)
                log.append({"obj": o, "stage": "判定", "want": want,
                            "ask": ask, "say": say_out, "ok": False,
                            "corrected": f"示范「{s}{want}{o}」"})
        if not ok:
            ok_all = False
    return ok_all, log, cursor


def rl_teach(ng, pats, n2w, v_words, o_words, topics, vo_pairs, has_llm,
             need_streak=15, max_rounds=100, min_w=0.1):
    """1对1 对话式说话教学（v3）：教师发起对话 → 网络听问题回答 → 批改。

    2026-08-10 用户要求（连续追加）：
      "网络必须连续15次通过老师的标准才能结束，错一次重新计算"
      "要1对1的对话" + "老师要评估质量，说的越好质量越高，给的奖励越高"
      "网络学会问的分数最高" + "主要是让网络学会追求奖励"
      "网络一直在说我吃苹果 → 教师发起对话；不通顺的处罚；反复重复的惩罚"
      "教师本身说话也要丰富一点，但是别太夸张"
      "教师和网络的对话也要记录"（逐轮进 log，由 demo() 统一留档）
    v3 对话机制（2026-08-10）：
      - 教师发起对话：每个话题连续 TALK_BLOCK 轮（教师批改后围绕同一话题
        继续发起下一次对话、换问法），练熟一个话题再换下一个（话术丰富不夸张）
      - 网络"听"问题再回答（听到问题里的动词就主导说它，应答 Intraverbal）
      - 反复重复（近 3 轮说过同样的话）→ 该句 V→O 与尾边减半（惩罚）
      - 答非所问（S/V 与话题不符）→ 不给奖励 + 计数清零 + 示范重铸正确应答
      - 示范 = 扩写式（把网络刚说的话补全/扩成问句/换宾语，Expansion+Recast）
      - 采样权重归一化：弱边能参与探索，强边不垄断
    2026-08-10 自闭症干预启发（保持 v2）：
      ① 提示渐隐（防提示依赖）：连续 <FADE_AT> 次前教师每轮完整示范
         （含问句）；连续 ≥<FADE_AT> 次后撤示范——网络必须独立说出，
         独立说对的句子奖励加成（多学 1 次固化独立定式）
      ② 强化尝试（PRT）：半句 40 分 = 尝试 → 部分奖励（强化 S→V 边）
      ③ 中性纠错（现代 DTT）：错误只删错配边（客观减权），语气中性不打击

    每轮（教师口吻，1对1）：
      教师提问 → 网络听问题采样回答（temp 随 streak 收敛）
      → 教师质量评分（0~100，问句 100 = 学会问最高分）
      → 奖励/惩罚（高分句学回网络：100 分学 2 次、80 分学 1 次，独立加成；
         半句部分奖励；重复减边；答非所问清零计数）
      → 教师反馈 + 示范（fade 阶段）→ 网络模仿示范句
      → 得分 ≥ 及格线 60 → streak + 1；否则 streak 归零（错一次重新计算）
      → 连续 need_streak 次（其中最后 5 次独立说出）→ 定式固化，教学结束
    网络通过试错 + 奖励自我优化：高分句边更强（更常说）、低分句边被删
    （不再说）、重复句被减权（换说法）→ 自己收敛到高分行话且保持多样。
    返回 (学会?, 总轮数, 最终连续通过次数, 网络最终说的话, 对话记录 list)。
    """
    streak = 0
    recent = []                                  # 近 REPEAT_WINDOW 轮网络说过的话
    log = []                                     # 逐轮对话记录（留档）
    vocab = _known_vocab(vo_pairs)
    announced_indep = False
    pending_ask = ""                             # LLM 教师上轮生成的【下个问题】
    # 话题顺序每圈打乱（2026-08-10 用户："为什么每次教学老师的问题都是一样
    # 的"）：话题池小 + 顺序固定 → 整圈循环后问题原样重复。现在每整圈
    # （len(topics) 个话题块）重新打乱顺序（时间种子 → 每次教学顺序不同，
    # 丰富对话；实际顺序由 talk_log 逐轮留档，可追溯），配合 ask 滑窗轮换，
    # 同一话题不会在两圈里原样重复
    _topic_rng = np.random.default_rng()         # 不传种子 = 每次运行不同
    _orders = {}
    def _order(cyc):
        if cyc not in _orders:
            o = list(range(len(topics)))
            _topic_rng.shuffle(o)
            _orders[cyc] = o
        return _orders[cyc]
    for r in range(1, max_rounds + 1):
        # 话题块：教师批改后围绕同一话题继续发起下一次对话（连续 TALK_BLOCK
        # 轮、轮换问法），让网络有机会固化当前话题，练熟再换话题（2026-08-10）
        bi = (r - 1) // TALK_BLOCK
        cyc, idx = divmod(bi, len(topics))       # 第几圈 / 圈内第几个话题块
        topic = topics[_order(cyc)[idx]]
        asks = topic["asks"]
        # 提问：LLM 模式教师自己发挥（上轮批改时生成的【下个问题】，
        # 只给方向+参考句，不锁死在池里——2026-08-10 用户）；话题块
        # 第一轮 / 规则模式 / LLM 失败 → 用话题池参考句起头。
        # ask 随全局轮次滑窗轮换：len(asks)≥4 > TALK_BLOCK=3 → 块内不重复，
        # 且不同圈同一话题落在不同块号 → 滑到不同的 3 连句（不原样重复）
        block_pos = (r - 1) % TALK_BLOCK
        if has_llm and pending_ask and block_pos != 0:
            ask = pending_ask
        else:
            ask = asks[(r - 1) % len(asks)]      # 话术轮换（丰富不夸张）
        fade = "none" if streak >= FADE_AT else "full"   # 提示渐隐
        if fade == "none" and not announced_indep:
            print(f"        ── 提示渐隐：从这轮起教师不再示范，网络独立说话 ──")
            announced_indep = True
        temp = max(0.3, 1.2 - 0.06 * streak)     # 探索率随 streak 收敛
        hear = _hear_words(ask, vocab)           # 网络"听"教师的问题
        net_out = net_speak(ng, pats, n2w, v_words, o_words, topic["s"],
                            min_w=min_w, temp=temp, hear=hear)
        sentence = say(net_out)
        score, reason, ptype = teacher_score(net_out, vo_pairs, topic=topic,
                                             recent=recent)
        feedback, demos = teacher_demo(net_out, score, streak, need_streak,
                                       vo_pairs, topic, fade=fade, rnd=r,
                                       ptype=ptype)
        if has_llm:                          # 一次调用：质量判断+原因+反馈+示范
            # （2026-08-10 用户："大模型要判断质量，从自然语言的角度，
            #  要教网络怎么说话" + "把调用压缩到一轮"——照 AAA 节点模式，
            #  一个 prompt 多个节标记；失败/客观项回退规则）
            once = _llm_teacher_once(net_out, topic, ask, vo_pairs, recent,
                                     streak, need_streak, fade)
            if once:
                score, reason, ptype, feedback, demos, next_ask = once
                if next_ask:
                    pending_ask = next_ask       # 教师自己发挥下一轮问话
        independent = (fade == "none")
        reward = reward_apply(ng, pats, net_out, score,
                              independent=independent, ptype=ptype)
        passed = score >= PASS_LINE
        if passed:
            streak += 1
        else:
            streak = 0
        recent.append(sentence)                  # 更新重复窗口
        if len(recent) > REPEAT_WINDOW:
            recent.pop(0)
        log.append({"round": r, "fade": fade, "topic_s": topic["s"],
                    "topic_v": topic["v"],
                    "teacher_ask": ask, "network_say": sentence,
                    "score": score, "reason": reason, "ptype": ptype,
                    "teacher_feedback": feedback, "reward": reward,
                    "demos": list(demos),
                    "streak_after": streak, "passed": passed})
        indep_tag = "（独立）" if independent else ""
        print(f"  第{r}轮 教师：「{ask}」")
        print(f"        网络{indep_tag}：「{sentence}」 {score} 分")
        print(f"        教师：「{feedback}」")
        if reward:
            print(f"        {reward}")
        for d in demos:                          # 示范阶段 → 网络模仿（自然句切回已学词学）
            seq = _segment_demo(d, vo_pairs)
            if seq:
                _learn_sentence(ng, seq, pats, slot=0)
        if demos:
            demo_txt = "「" + "」 「".join(demos) + "」"
            print(f"        示范：{demo_txt} → 已学")
        if passed:
            print(f"        ✓ 连续第 {streak}/{need_streak} 次")
            if streak >= need_streak:
                return True, r, streak, sentence, log
        else:
            print(f"        ✗ {reason}，连续计数清零")
    bi = (max_rounds - 1) // TALK_BLOCK
    last_topic = topics[_order(bi // len(topics))[bi % len(topics)]]
    last_ask = last_topic["asks"][(max_rounds - 1) % len(last_topic["asks"])]
    final = say(net_speak(ng, pats, n2w, v_words, o_words, last_topic["s"],
                          min_w=min_w, temp=0.3,
                          hear=_hear_words(last_ask, vocab)))
    return False, max_rounds, streak, final, log


# ════════════════════════════════════════════════════════════════
#  实验数据留档（2026-08-10 用户：以后任何实验数据都要有留档）
# ════════════════════════════════════════════════════════════════

def edge_profile(ng, pats, vo_pairs):
    """边权重要览（留档用）：S→V 与 V→O 全部边权重 dict。

    教学前后各采一份，写进 result.json 作对照组——可看出哪些边被
    教学强化（奖励学回）、哪些被减权（重复惩罚）、哪些被删除（错配罚）。
    """
    prof = {}
    s_words = sorted({w for w in PERS_MANUAL + S_ANIMALS if w in pats})
    for s in s_words:
        for v in vo_pairs:
            prof[f"{s}→{v}"] = round(edge_between(ng, pats, s, v), 3)
    for v, ops in vo_pairs.items():
        for o in ops:
            prof[f"{v}→{o}"] = round(edge_between(ng, pats, v, o), 3)
    # v13：拒绝表达边（S→不要、不要→坏东西）+ 坏东西感知边（V→石头）
    for s in s_words:
        prof[f"{s}→不要"] = round(edge_between(ng, pats, s, "不要"), 3)
    for o in sorted(BAD_OBJS):
        prof[f"不要→{o}"] = round(edge_between(ng, pats, "不要", o), 3)
    return prof


def _dump_net(out, ng, vocab, pats, cursor):
    """网络 → npz（snapshot 同格式，可用 load_snapshot 直接恢复）。"""
    np.savez_compressed(
        out,
        params=json.dumps(_net_params(ng)).encode("utf-8"),
        vocab=json.dumps(list(vocab), ensure_ascii=False).encode("utf-8"),
        pats=json.dumps({w: [int(x) for x in v] for w, v in pats.items()},
                        ensure_ascii=False).encode("utf-8"),
        cursor=np.asarray([int(cursor or 0)], dtype=np.int64),
        **_pack_net(ng))


def save_experiment(env, logs, edge_before, edge_after, seeds, has_llm,
                    base_info):
    """实验数据留档：写入 runs/_speak_logs/{时间戳}_{种子}_{教师}/。

    - talk_log.json   逐轮对话完整记录（教师问 / 网络答 / 评分 / 反馈 /
                      奖励 / 示范 / streak，用户：教师和网络的对话也要记录）
    - result.json     汇总指标（通过/轮数/最终streak/惩罚统计/平均分 +
                      教学前后边权重对比 + 实验参数 + 起点 base）
    - net_after.npz   教学后网络（snapshot 同格式，可 load_snapshot 恢复，
                      _latest_net 会续用它做下次教学起点 = 增量成长）
    目录带时间戳永不覆盖；教学前网络 = base_info 描述的起点快照。
    """
    ng, pats, n2w, vo_pairs, cat_members, vocab_list, v_words, o_words, cursor, _ = env
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = "_".join(str(s) for s in seeds) + f"_{'llm' if has_llm else 'rule'}"
    out = RUNS / "_speak_logs" / f"{ts}_{tag}"
    out.mkdir(parents=True, exist_ok=True)

    summary = {}
    for seed, rec in logs.items():
        log = rec["log"]
        n_rep = sum(1 for e in log if e.get("ptype") == "repeat")
        n_off = sum(1 for e in log if e.get("ptype") == "offtopic")
        scores = [e["score"] for e in log]
        summary[str(seed)] = {
            "ok": rec["ok"], "rounds": rec["rounds"],
            "final_streak": rec["final_streak"], "final_say": rec["final_say"],
            "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "n_repeat_penalty": n_rep, "n_offtopic_penalty": n_off,
            "n_independent": sum(1 for e in log if e["fade"] == "none"),
        }
    result = {
        "experiment": "说话教学 v3 对话式（教师发起对话 → 网络听答 → 批改）"
                      "+ v13 价值维度/拒绝表达（FCT）",
        "ts": ts, "seeds": seeds,
        "teacher": "LLM" if has_llm else "规则验证器",
        "base": base_info,                # 教学前起点（对照组/增量成长）
        "val": {k: ("好" if v == 1 else "坏") for k, v in VAL.items()},
        "params": {"pass_line": PASS_LINE, "need_streak": 15, "fade_at": FADE_AT,
                   "talk_block": TALK_BLOCK, "repeat_window": REPEAT_WINDOW,
                   "repeat_times": REPEAT_TIMES, "repeat_decay": REPEAT_DECAY,
                   "hear_boost": HEAR_BOOST, "bad_objs": sorted(BAD_OBJS)},
        "summary": summary,
        "edge_before": edge_before, "edge_after": edge_after,
    }
    (out / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    talk = {"meta": {"experiment": result["experiment"], "ts": ts,
                     "seeds": seeds, "teacher": result["teacher"],
                     "base": base_info},
            "rounds": {str(k): v["log"] for k, v in logs.items()}}
    (out / "talk_log.json").write_text(
        json.dumps(talk, ensure_ascii=False, indent=1), encoding="utf-8")

    _dump_net(out / "net_after.npz", ng, vocab_list, pats, cursor)
    print(f"\n[留档] 实验数据已保存：{out}")
    print(f"       talk_log.json（逐轮对话）· result.json（汇总+边权重对比）"
          f"· net_after.npz（教学后网络）")
    return out


# ════════════════════════════════════════════════════════════════
#  ③ 自判应答（Intraverbal，v12 网络结构自判，非网络生成）
# ════════════════════════════════════════════════════════════════

def speak_judge(ng, pats, n2w, s, v, o, vo_pairs, cat_members):
    """教师问"能说 X 吗？" → v12 网络结构自判 → 说出判断+依据。

    v12（2026-08-10）：判断从代码规则（rule_verifier 查搭配类别）升级为
    网络自判（self_judge：直连→二跳→强度→类别冲突→诚实留白）——判断
    依据来自网络边结构，改网络（教学/处罚）就改判断。"""
    verdict, conf, path = self_judge(ng, pats, n2w, s, v, o,
                                     vo_pairs, cat_members)
    sent = f"{s}{v}{o}"
    if verdict == "可造":
        return f"能说「{sent}」。（{path}，置信 {conf}）"
    if verdict == "不知道":
        return (f"「{sent}」能配什么？我凭网络结构查不到依据"
                f"（{path}），诚实说：我不知道。")
    return f"不能说「{sent}」。（{path}，置信 {conf}）"


# ════════════════════════════════════════════════════════════════
#  演示
# ════════════════════════════════════════════════════════════════

def demo(env, has_llm, seeds, smoke=False, lesson_params=None):
    """对话式教学演示。lesson_params：强度调节字典（gain_value/gain_emotion/
    link_times/entrench_times/uncouple_decay），None 用 value_lesson 默认值。"""
    ng, pats, n2w, vo_pairs, cat_members, vocab_list, v_words, o_words, cursor, _ = env
    print("═══ 定式网络说话（v3：对话式教学——教师发起对话 + 网络听答 + 批改）═══\n")
    print("网络 = 盲人：只能听（输入走链）和说（输出自然语句），无视觉感知。\n")

    # ── ① 跟读复述（Echoic）：v7 整句涟漪 ──
    print("【① 跟读复述 Echoic】教师说一句，网络唤起并复述\n")
    for sent in [["我", "要", "苹果"], ["他", "吃", "西瓜"], ["我们", "看", "公园"]]:
        rate = sent_recall(ng, pats, sent)
        if rate >= 0.5:
            print(f"  教师：跟我读「{''.join(sent)}」")
            print(f"  网络：「{''.join(sent)}」（复述率 {rate:.2f}）")
        else:
            print(f"  教师：跟我读「{''.join(sent)}」")
            print(f"  网络：……（复述率 {rate:.2f}，这句我还没学会）")
        print()

    # ── ② 主动应答对话（Mand + Intraverbal）= 教师发起对话的 RL 教学 ──
    print("【② 主动应答对话】教师发起对话（不再给固定起始词）：教师提问 →"
          "网络听问题回答 → 教师批改（问句 100 分最高；答非所问/反复重复惩罚）"
          "→ 奖励/惩罚 → 更丰富示范；连续 15 次通过才结束，错一次重新计算\n")
    logs = {}
    edge_before = edge_profile(ng, pats, vo_pairs)   # 教学前边权重留档
    for seed in seeds:
        topics = [dict(t, s=seed) for t in TALK_POOL.get(seed, [])]
        if not topics:
            print(f"  ⚠ 话题池里没有「{seed}」，跳过\n")
            continue
        vocab = _known_vocab(vo_pairs)
        first_ask = topics[0]["asks"][0]
        # 教学前：网络先"听"老师第一个问题，自己试着回答（看原始状态）
        net_out0 = net_speak(ng, pats, n2w, v_words, o_words, topics[0]["s"],
                             hear=_hear_words(first_ask, vocab))
        print(f"  教师：「{first_ask}」")
        print(f"  网络（教学前）：「{say(net_out0)}」")
        # v13 价值课前置（2026-08-10 用户："先灌入价值观" + "痛觉条件反射"）
        # ——先教「哪些好、哪些坏」（体验式：建立感知 → 痛觉事件 → 学会
        # 避开），再进对话教学，坏话题只作验证
        v_ok, v_log, cursor = value_lesson(ng, pats, n2w, v_words, o_words,
                                           seed, vo_pairs, cursor,
                                           **(lesson_params or {}))
        print(f"  ── 价值课：教「哪些好、哪些坏」（体验式：能碰 → 痛觉 → 避开 → 不痛了）──")
        for v in v_log:
            if v.get("stage") in ("痛觉体验", "定式"):
                print(f"    ⚡ {v['event']}")
            else:
                tag = "✓" if v["ok"] else "✗"
                extra = f"  {v['relief']}" if v.get("relief") else ""
                corr = f"（{v['corrected']}）" if not v["ok"] else ""
                print(f"    {v['ask']} 网络：「{v['say']}」 {tag}{extra}{corr}")
        print(f"    价值课{'✅ 通过' if v_ok else '❌ 未全对（对话教学中继续巩固）'}\n")
        print(f"  ── 1对1 对话教学开始（目标：连续 15 次得分 ≥ {PASS_LINE}）──")
        ok, r, streak, final, log = rl_teach(ng, pats, n2w, v_words, o_words,
                                             topics, vo_pairs, has_llm)
        logs[seed] = {"ok": ok, "rounds": r, "final_streak": streak,
                      "final_say": final, "value_lesson": v_log, "log": log}
        print(f"  ── 教学结束：{'✅ 通过' if ok else '❌ 未通过'}（{r} 轮，"
              f"连续 {streak} 次）最后说「{final}」\n")
    edge_after = edge_profile(ng, pats, vo_pairs)    # 教学后边权重留档

    # ── ③ 自判应答（Intraverbal）──
    print("【③ 自判应答 Intraverbal】教师问'能说 X 吗？'，网络自己判断\n")
    for s, v, o in [("我", "吃", "石头"), ("我", "看", "公园"),
                    ("我", "吃", "苹果"), ("我", "喝", "学校")]:
        print(f"  教师：能说「{s}{v}{o}」吗？")
        print(f"  网络：{speak_judge(ng, pats, n2w, s, v, o, vo_pairs, cat_members)}")
        print()
    return logs, edge_before, edge_after


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="append", default=[],
                    help="对话主语（我/他/猫，可多次）；缺省用演示集")
    ap.add_argument("--with-teacher", action="store_true",
                    help="LLM 教师判断/示范（需 DEEPSEEK_API_KEY）")
    ap.add_argument("--base", default="latest",
                    help="起点网络：latest（默认，续用最新教学产物，增量成长）"
                         "/ 版本号如 11.2 / npz 路径")
    ap.add_argument("--smoke", action="store_true", help="小规模快跑验证")
    # 强度手动调节（2026-08-10 用户："强度能不能人为手动调节"）：调网络
    # "倾向"（先验），不直接指定权重参数——增益走调制层（不碰 W），联结/定式
    # 走注入式学习（网络自己长边），解耦走轻微衰减（保留微量可复活）。
    ap.add_argument("--gain-value", type=float, default=None,
                    help="价值判断词增益（要/不要，默认 4.0）")
    ap.add_argument("--gain-emotion", type=float, default=None,
                    help="感受词增益（情绪词，默认 2.0）")
    ap.add_argument("--near-gain", type=float, default=None,
                    help="开关词近义词增益（默认 3.0，低于同义词档）")
    ap.add_argument("--gain-self", type=float, default=None,
                    help="自我增益（「我」，默认 2.0，与感受同级；拉顶=自我中心化污染）")
    ap.add_argument("--link-times", type=int, default=None,
                    help="感受→开关 / 痛觉链 学习次数（默认 2）")
    ap.add_argument("--entrench-times", type=int, default=None,
                    help="坏东西定式学习次数（默认 7，注意力判别实验临界 48<x≤56 落地）")
    ap.add_argument("--uncouple-decay", type=float, default=None,
                    help="定式解耦：X→痛 衰减系数（默认 0.1）")
    ap.add_argument("--params-file", default=None,
                    help="从 json 读取强度参数作为默认值（CLI 显式参数优先）")
    ap.add_argument("--save-params", default=None,
                    help="保存当前强度参数到 json 后直接退出（便于预设）")
    args = ap.parse_args()
    # 强度参数合并：默认 < params-file < CLI 显式
    lesson_params = {"gain_value": 4.0, "gain_emotion": 2.0, "near_gain": 3.0,
                     "gain_self": 2.0, "link_times": 2, "entrench_times": 7,
                     "uncouple_decay": 0.1}
    if args.params_file:
        loaded = json.loads(Path(args.params_file).read_text(encoding="utf-8"))
        lesson_params.update({k: v for k, v in loaded.items()
                              if k in lesson_params})
    for key, cli_val in [("gain_value", args.gain_value),
                         ("gain_emotion", args.gain_emotion),
                         ("near_gain", args.near_gain),
                         ("gain_self", args.gain_self),
                         ("link_times", args.link_times),
                         ("entrench_times", args.entrench_times),
                         ("uncouple_decay", args.uncouple_decay)]:
        if cli_val is not None:
            lesson_params[key] = cli_val
    if args.save_params:
        Path(args.save_params).write_text(
            json.dumps(lesson_params, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"强度参数已保存到 {args.save_params}: {lesson_params}")
        return
    seeds = args.seed or ["我", "他"]
    has_llm = args.with_teacher and bool(_load_key())
    env = load_env(args.base)               # 默认续用最新教学产物（增量成长）
    ng, pats, n2w, vo_pairs, cat_members, vocab_list, v_words, o_words, cursor, base_info = env
    print(f"加载起点：{base_info}")
    print(f"  n={ng.n}，模式 {len(pats)}，对话主语：{seeds}"
          f"  | 教师：{'LLM' if has_llm else '规则验证器'}\n")
    logs, edge_before, edge_after = demo(env, has_llm, seeds,
                                         smoke=args.smoke,
                                         lesson_params=lesson_params)
    # 实验数据留档（2026-08-10 用户：以后任何实验数据都要有留档）
    save_experiment(env, logs, edge_before, edge_after, seeds, has_llm,
                    base_info)


if __name__ == "__main__":
    main()
