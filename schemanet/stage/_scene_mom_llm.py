# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""妈妈 LLM 场景脚本 v2（2026-08-11）：三刺激源 + LLM 一次调用多功能。

v1 暴露（10 次预算全被「回应」吃掉）：网络复读回声句（永不沉默→故事
永不触发）、词表外字没进无效缓冲（减边 0 次）。v2 修复：
  ① 表达冷却：表达后 12 tick 静默——沉默出现 → 故事可触发
  ② 妈妈提问 → 网络尝试回应（话中名词走链——对话有进展）
  ③ 词表外字 = 网络不认识的无效字 → 直接进 junk（≥10 触发判定减边）

用户要求：
  ① LLM 调用时机（2026-08-11 收紧）：只有 守一主动回答（reply）/
     主动提问（ask）/ 一直思考没说话（沉默 ≥ SILENCE_TICK）才调用
     ——自发表达、例行故事、无效字不再单独触发
  ② 妈妈主动互动：讲故事（沉默时）
  ③ 网络主动互动：妈妈回答 + 发散衍生
  ④ 刺激源区分：环境 / 听觉 / 自身 tick
  ⑤ 听觉刺激源带「老师说：」前缀
  ⑥ 一次调用实现全部功能（AAA 节标记式——_speak.py 结构）
  ⑦ 先跑 10 次调用看效果

用法：python _scene_mom_llm.py（纯内存——不保存快照；需要 DEEPSEEK key）
"""

import json
import random
import time
from collections import deque
from pathlib import Path

from snapshot import load_version, load_consolidated
from _grow_v11 import _load_key, _llm_chat

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
RUNS = Path(__file__).resolve().parent.parent / "runs"
SCENE_TAG = "场景沉淀"


def _latest_scene_ver():
    """最新场景沉淀版本（index.jsonl 里 tag 含『场景沉淀』的最新版）。"""
    idx = RUNS / "index.jsonl"
    if not idx.exists():
        return None
    found = None
    for line in idx.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if SCENE_TAG in d.get("tag", ""):
            found = d["version"]
    return found


def _load_scene_meta(version):
    fp = RUNS / f"_scene_mom_meta_{version}.json"
    if fp.exists():
        return json.loads(fp.read_text(encoding="utf-8"))
    return {}


def _load_scene_latest():
    """从最新场景沉淀快照加载（记忆延续——不再每轮问同样的问题）。"""
    v = _latest_scene_ver()
    if v:
        return load_version(v)
    return load_version("35.0")


def _save_scene(ng, cons, val, absorbed, ask_taught, teach_pairs, metrics,
               pats=None, cursor=None):
    """场景沉淀：快照（net+固化句+验证门）+ meta（学词/问句/教学对）。"""
    from snapshot import save_snapshot
    tag = f"{SCENE_TAG}：妈妈LLM社交学习（{metrics.get('calls', 0)} 次调用/"
    tag += f"提问 {metrics.get('n_ask', 0)} 次/学词 {len(absorbed)} 个/"
    tag += f"回忆 {metrics.get('recall_ok', 0)} 次）"
    out = save_snapshot(ng, parent="35.0", tag=tag,
        pats=pats, cursor=cursor,
        consolidated=cons, validation=val, metrics=metrics)
    ver = out.name.split("_")[0].lstrip("v") + "." + out.name.split("_")[1]
    meta = {"version": ver, "absorbed": list(absorbed),
            "ask_taught": list(ask_taught),
            "teach_pairs": [list(p) for p in teach_pairs]}
    (RUNS / f"_scene_mom_meta_{ver}.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return ver



# ── 参数 ──────────────────────────────────────────
TICK_SEC = 1.0             # 1 tick = 1 秒（2026-08-11 定义：与 LLM
                           # 调用 timeout=15s 对齐——节流 15 tick =
                           # 一次调用耗时上限；沉默 24 tick = 24 秒）
JUNK_LIMIT = 10            # 无效字缓冲阈值（>10 或 >20——可调）
LONG_SENT = 20             # 单句超 20 字 → 也触发判定
SILENCE_TICK = 24          # 沉默阈值：24 tick（= 24 秒）无表达（一直
                           # 思考没说话）→ 老师介入讲故事
COOLDOWN = 12              # 表达后冷却（tick）——不重复表达
INVALID_CD = 60            # 无效字判定冷却（tick）——防预算被连续吃掉
LLM_BUDGET = 30            # 30 次调用预算
SLEEP_PRESSURE_THR = 200    # 内生睡眠压力阈值（活动量累积——Process S——
                            # 超阈值触发 SHY 睡眠——活动驱动节律）
ASK_CD = 20                # 提问冷却（问一次消化一阵——防连环问吃预算）
PHASES = 16
SEED = 42

# ── 分值体系（2026-08-11 温和化调整——用户："有点激进"）──
BOOST_BASE = 1.03          # 回合基础奖励（回应即有——从 1.02 上调一点）
BOOST_GOOD = 1.06          # 高分链强化（原 1.05）
BOOST_DIRECT = 1.08        # 直接回答最高分（原 1.1——过猛下调）
BOOST_STREAK = 1.12        # 连对大奖励（原 1.15——下调）
PENALTY_FACTOR = 0.8       # 惩罚减边（原 0.5——太狠会把链打碎，温和化）
SENT_CD_TICKS = 30         # 句冷却（原 40——时间惩罚也温和）
W_NAT, W_CPX, W_FIT = 0.35, 0.30, 0.35   # 综合分权重（原 0.35/0.25/0.4）

# ── 奖惩（2026-08-11 R-STDP 三因子——用户："神经元本身就有奖惩机制"）──
# 外部不再直接改边——只经 ng.release_da() 注入多巴胺调质（间接触发）。
# 学习增量 = STDP × (1 + DA_GAIN×da)——网络自己决定学多少：
#   正确应答 release_da(+2)（好处大）→ 后续学习 ×3
#   一般应答 release_da(+1)（有价值）→ ×2
#   重复/答错 release_da(-1)（惩罚）→ 学习被抑制
#   "第一次+1 / 没意思=0"由基线 STDP + 突触饱和（w_max）+ DA 衰减自然涌现

PUNCT = set("。，！？、：；“”‘’（）《》…—～·")   # 标点——不算字
SELF_NAME = "守一"          # 网络自己的名字（身份——被叫应答触发词）
# 语气字（孩子常见却不值得问的——好奇词扫描跳过）
TONE_W = set("啦呀呢啊哦嗯呼呜诶咯哒嘿哟唉噢")

# 环境刺激源：场景事件（tick → 词）——t3 老师在（环境在场锚点：
# 网络感知"老师"实体——人称/角色绑定的前提）
ENV_EVENTS = {3: ["老师"], 4: ["猫"], 9: ["雨"], 14: ["天", "黑"], 18: ["狗"]}
# 相位记忆（自身 tick 刺激源——时序教学绑定）
PHASE_MEM = {range(2, 6): "早上", range(6, 10): "中午",
             range(10, 14): "晚上"}
# 表达意图动机词（网络词表内）——主动互动 = 有需求/有疑问/找妈妈
MOTIVE = {"疑问": ["怎", "么", "办", "为", "什", "么", "吗"],
          "需求": ["饿", "疼", "困", "渴", "冷"],
          "分享": ["妈"]}
FUNC = {"的", "了", "不", "很", "我", "是", "在", "也", "就", "都",
        "和", "吗", "这", "那", "你", "他", "她", "有", "说", "妈",
        # 功能词/口语碎片扩充（听过但无需"教"的词——问它们学不到知识）
        "给", "一个", "小", "它", "把", "被", "从", "向", "对", "让",
        "叫", "些", "每", "各", "谁", "哪", "会", "能", "要", "去",
        "来", "上", "下", "多", "少", "真", "最", "更", "哦", "啦",
        "拿", "伸", "手", "脚", "指", "东西", "这是", "就是", "这个",
        "那个", "一样", "时候", "像", "没", "着", "过", "吧", "呢",
        "啊", "呀", "嗯", "们", "又", "再", "先", "后", "只", "还",
        "才", "刚", "正", "别", "怎么", "什么", "为什么", "哪",
        # 解释性口语（回应/解释里常见——不问它们）
        "宝宝", "好不好", "哪里", "可以", "看看", "慢慢", "天上",
        "一双", "小手", "一粒", "米", "搬", "点", "跟", "哪儿",
        "朵", "那边", "后来", "变成", "一下", "一会儿", "样子",
        "软", "暖暖", "甜甜", "悄悄", "轻轻", "慢慢", "一起", "自己",
        "妈妈", "爸爸", "太阳", "月亮", "星星", "云", "风", "雨", "水"}
ASK_WORDS = {"哪", "吗", "呀", "什么", "怎么", "呢", "吧", "谁",
             "为什么"}   # 疑问词（谁/为什么——2026-08-11 补齐）
PRONOUNS = {"你", "我", "他", "她", "它", "我们", "你们", "他们"}  # 人称代词——不试读
# 动作词（行为维度——好奇时问"怎么做"而非"是什么"；网络
# 不知道"行为"概念——用动作词表建立行为问句维度）
ACTION_WORDS = {"飞", "跑", "跳", "走", "游", "爬", "吃", "喝", "睡",
                "咬", "啃", "采", "追", "找", "看", "听", "说", "拿",
                "给", "变", "落", "滚", "拍", "摸", "洗", "穿", "戴",
                "玩", "笑", "哭", "叫", "唱", "蹦", "蹲", "站", "坐",
                "躺", "扔", "接", "打", "吹", "擦", "盖", "搬", "画",
                "写", "读", "问", "答", "帮", "来", "去", "回", "开",
                "关", "停", "动", "做", "学", "教", "想", "知道",
                "绕", "转", "升", "落", "长", "照", "发", "光", "反射",
                "站", "住", "望", "移动", "发光", "燃烧", "搬", "抬",
                "排", "采", "埋", "挖", "结", "变成", "长大", "孵"}


class SceneMomLLM:
    def __init__(self, resume=False):
        if resume:
            self.ng, self.vocab, self.pats, self.cursor = _load_scene_latest()
            self.resumed = True
        else:
            self.ng, self.vocab, self.pats, self.cursor = load_version("35.0")
            self.resumed = False
        self.ng.w_max = 64.0
        self.n2w = {j: w for w, ns in self.pats.items() for j in ns}
        # 固化句（34.0——v35 剪枝后仍加载）：{起始词: [(toks, slots, 类型)]}
        # 条件化验证：{(qtype, 主题, 句): (对, 错)}——回答"该问题"的对错
        if resume:
            self.cons, self.val = load_consolidated(_latest_scene_ver())
            self.n_ring = 0
        else:
            self.cons, self.val = load_consolidated("34.0")
            # 黑洞治疗（2026-08-11）：压缩双向回声环（X↔「的」类 11.2
            # 双向边——黑洞结构）；单向教学边不动——域内能力零损伤
            from _exp_cure_blackhole import cure_echo_rings
            self.n_ring = cure_echo_rings(self.ng, self.pats, self.n2w)
        self._build_reader()
        self.has_llm = bool(_load_key())
        # 状态
        self.tick = 0
        self.phase = 0
        self.said = []                # 网络说出的流
        self.pending = []             # 听觉缓冲（逐字累积）
        self.junk = deque(maxlen=60)  # 无效字缓冲（词表外字/组词失败）
        self.last_tail = None         # 联想流尾词（自身 tick 念头）
        self.silence = 0              # 沉默计数（无表达 tick 数）
        self.cooldown = 0             # 表达冷却（不重复表达）
        self.q_nouns = []             # 妈妈提问的话中名词列表（待网络回应）
        self.q_txt = ""               # 妈妈提问原文（问题分型）
        self.invalid_cd = 0           # 无效字判定冷却
        self.injected = []            # 最近一句注入的词表内字（无效字判定源）
        self.calls = 0                # LLM 调用计数（预算）
        self.scores = []              # 网络表达的评价记录（自然度/复杂度）
        self.last_toks = []           # 最近一次表达的词序列（强化用）
        self.recent_says = deque(maxlen=5)   # 近 5 次表达（重复检测）
        self.llm_replies = []         # LLM 原始回答（完整展示用）
        self.sent_cd = {}             # 句冷却表 {句: 剩余 tick}——时间惩罚
        self.offend = {}              # 重犯计数 {句: 次数}——冷却期满又犯
        self.need_demo = False        # 待示范标记（上次答非所问/答不出）
        self.streak = 0               # 连续有效对答计数（≥3 → 大奖励）
        self.last_q_txt = ""          # 上次表达时的提问（复读判定）
        self.curious = deque(maxlen=6)   # 好奇词（故事里词表外实词——想提问）
        self.curious_cnt = {}         # 好奇词出现次数（≥2 → 学词吸收）
        self.absorbed = []            # 已学会的新词（听故事学词）
        self.n_ask = 0                # 网络主动提问次数（指物问）
        self.n_recall_ok = 0          # 回忆验证成功次数（沉淀统计）
        self.ask_cd = 0               # 提问冷却（问一次消化一阵）
        self.ask_taught = set()       # 已教问句结构的词（X是什么）
        self.called = False           # 被叫标记（听到自己的名字——待应答）
        self.called_reply = False     # 本次表达是否为被叫应答（奖励判定）
        self.called_prompt = False    # 应答带语气词/疑问词（表示听到了）
        self.bad_reply = 0            # 错误应答奖励计数（≤10 次给——之后停）
        self.heard_reply = 0          # 听觉学习：听到"守一，我在呢"示范计数
        self.learned_reply = None     # 听学应答词序列（印象在边——被叫时
                                      # 按边验证读出；不存 cons 固化表）
        self.heard_rule_learned = False  # 规则句已学（听到X要说Y——1 次学会）
        # 恢复上次场景沉淀（学词入域/问句结构/教学出边——记忆不丢）
        # 记忆本体在固化表 cons 里：有 ask/answer 条目的词 = 学过的
        if resume:
            for k, items in self.cons.items():
                for c in items:
                    if c[2] == "ask":
                        self.ask_taught.add(k)
                        self.domain.add(k)   # 学过的词入域（不再好奇）
                    elif c[2] == "answer":
                        self.domain.add(k)
                        for a, b in zip(c[0][:-1], c[0][1:]):
                            self.teach_out.setdefault(a, set()).add(b)
            self.absorbed = [k for k in self.cons]
        self.asked_word = None        # 最近一次提问的词（解释后教问句）
        self.ask_mem = deque(maxlen=5)   # 提问记忆（事后询问验证用）
        self.last_call_tick = 0       # 上次 LLM 调用 tick（节流防限流）
        self.teach_pairs = set()      # 场景教学对（沉淀用——resume 恢复）
        self.base_absorbed = len(self.absorbed)   # 学词基线（判断本轮新增）
        self.recall = None            # 回忆状态 {"kw", "stage"}——事后询问
        self.last_explain = []        # 最近一次解释句分词（答案固化用）
        self.edged = []               # 已减边字
        self.log = []
        self.mom = []                 # 妈妈说过的流（听觉刺激源）

    # ── 读出器（free_read 走链——网络结构读出）──
    def _build_reader(self):
        from _exam_free import build_domain, build_teach_out
        from _grow_qa_s3 import build_pool as qa_build_pool
        from _grow_cat import build_cats
        rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
        sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
        cats = build_cats(self.pats, sem["words"], 12, 3)
        q_pool = qa_build_pool(rows, cats)
        self.domain = build_domain(self.ng, self.pats, rows, q_pool)
        self.teach_out = build_teach_out(rows, q_pool)

    def _read(self, seed_w, ctx=None):
        """网络自由读（自身 tick 念头/表达——内容全来自网络结构）。
        ctx（确认/怎么办）→ 固化句优先 + 条件化验证：妈妈问"饿了吗"
        → 固化句「我饿了」验证通过 → 整句读出（准确回答）。"""
        from _exam_free import free_read
        read = free_read(self.ng, self.pats, self.n2w, [seed_w],
                         self.domain, teach_out=self.teach_out,
                         consolidated=self.cons, ctx=ctx,
                         validation=self.val)
        toks = []
        for w in [x.split("(")[0] for x in read]:
            if w.startswith("[") or w in toks:
                break
            toks.append(w)
        return toks

    def _chain_exists(self, seq):
        """链边齐全验证：seq 相邻词对在 W_out 都有实边（印象在边——
        边被删 = 遗忘 = 读不出）。b 是词——用 pats[b] 神经元查边。"""
        for a, b in zip(seq[:-1], seq[1:]):
            if a not in self.pats or b not in self.pats:
                return False
            targets = set(self.pats[b])
            if not any(targets & set(self.ng.W_out[i][0].keys())
                       for i in self.pats[a]):
                return False
        return True

    def _learn_reply(self, trigger, reply, why):
        """听学建边：触发词+应答词 整链教学（印象进边——不是固化表）。
        守一被教 → 记录应答词序列（learned_reply——被叫时按边验证
        读出）；边随 sleep 生命周期生灭。"""
        from schema_net import _learn_sentence
        seq = [trigger] + list(reply)
        _learn_sentence(self.ng, seq, self.pats, slot=0)
        for a, b in zip(seq[:-1], seq[1:]):
            self.teach_out.setdefault(a, set()).add(b)
            self.teach_pairs.add((a, b))
        if trigger == SELF_NAME:
            self.learned_reply = list(reply)
        self.log.append(f"    [听学] {why} → 建边 {'/'.join(seq)}"
                        f"（印象进边——不固化）")

    @staticmethod
    def qtype_of(txt):
        """妈妈的话 → 问题类型（复用 4.4 分型）：怎么办问/确认问。"""
        if "怎么办" in txt:
            return "怎么办"
        if any(s in txt for s in ("饿", "疼", "困", "渴", "冷", "累")):
            return "确认"
        return None

    # ── 刺激源 ──────────────────────────────────────
    def tick_stim(self):
        """[tick] 自身 tick 刺激：相位记忆唤起 → 自发念头。"""
        mem_word = next((w for r, w in PHASE_MEM.items()
                         if self.phase in r), None)
        if mem_word and mem_word in self.pats:
            return self._read(mem_word)
        return []

    def env_stim(self, word):
        """[环境] 环境刺激源：场景事件词（非听觉——无前缀）。"""
        self.log.append(f"    [环境] {word}（环境事件——场景感知）")

    def hear(self, w):
        """[听觉] 听觉刺激源：老师的话逐字进入（「老师说：」前缀由调用
        方标注）。标点不是字——跳过；词表外字 = 网络不认识的无效字
        （无神经元——供 LLM 判定，无边的减不了，跳过不进 junk）。"""
        if w in PUNCT:
            return
        if w not in self.pats:
            return
        self.pending.append(w)

    # ── 网络处理 ────────────────────────────────────
    def process(self):
        """每 tick：事后回忆（你刚才问什么/妈妈怎么回答的）→ 听觉组词
        → 被提问响应 → 好奇提问 → 自身 tick 念头。返回 (marker, text)。"""
        # 事后询问回忆：妈妈问「你刚才问妈妈什么了？」→ 固化问句；
        # 「妈妈怎么回答的？」→ 固化答案（记得 = 结构能读出）
        if self.recall and self.cooldown <= 0:
            r = self.recall
            if r["stage"] == 0:            # 问"你刚才问什么了"
                q = self._read_ask(r["kw"])
                if q:
                    self.recall["stage"] = 1
                    self.cooldown = COOLDOWN
                    self.last_toks = q
                    return ("recall_q", "/".join(q))
            elif r["stage"] == 1:          # 问"妈妈怎么回答的"
                a = self._read_answer(r["kw"])
                if a:
                    self.recall["stage"] = 2
                    self.cooldown = COOLDOWN
                    self.last_toks = a
                    return ("recall_a", "/".join(a))
        # 听觉缓冲：组词（最长匹配词表）——组不出的字进 junk
        while self.pending:
            s = "".join(self.pending)
            hit = None
            for L in range(min(len(s), 3), 0, -1):
                if s[:L] in self.pats:
                    hit = s[:L]
                    break
            if hit:
                del self.pending[:len(hit)]
                if hit in MOTIVE["需求"]:
                    self.junk.clear()      # 有效词 → 无效缓冲清零
                if hit == SELF_NAME:
                    self.called = True     # 听到自己的名字——被叫标记
                continue
            self.junk.append(self.pending.pop(0))
        # 妈妈提问 → 网络尝试回应（候选词依次试读——对话进展）
        # 冷却中不消费提问（q_nouns 保留——妈妈的提问不丢）
        if self.q_nouns and self.cooldown > 0:
            self.cooldown -= 1
            return None
        if self.q_nouns:
            ctx = self.qtype_of(getattr(self, "q_txt", ""))
            ans = None
            for noun in self.q_nouns:
                # 种子 = 名词本身（需求词是固化句 key：问"饿了吗"
                # → 从"饿"读固化句「我饿了」——准确回答）
                cand = self._read(noun, ctx=ctx)
                if not cand:
                    continue
                sent = "/".join(cand)
                if sent in self.sent_cd:      # 句冷却：这句话暂时说不出
                    continue                  # → 试下一个候选
                ans = cand
                break
            self.last_qkw = self.q_nouns[0] if self.q_nouns else "?"
            self.last_ctx = ctx or ""
            self.q_nouns = []
            if ans and self.cooldown <= 0:
                self.cooldown = COOLDOWN
                self.last_toks = ans
                return ("reply", "/".join(ans))   # 对答：回答妈妈的提问
        # 被叫应答：听到自己的名字 → 身份唤起（有人在叫我——应答）
        # 读不出（空）→ 沉默（没答上——不应答不给奖励）。
        # 应答优先：听学链（边里学的——逐跳验证 W_out 边存在）；边被
        # sleep 删除（遗忘）→ 自然退化读身份句。
        # 奖励条件在主循环：应答带语气词/疑问词（我在呢/嗯——表示
        # "听到了"）才给——纯身份句应答（守一是我的名字）不奖励。
        if self.called and self.cooldown <= 0:
            self.called = False
            cand = None
            if self.learned_reply:
                chain = [SELF_NAME] + self.learned_reply
                if self._chain_exists(chain):
                    cand = list(self.learned_reply)
            if not cand:
                cand = self._read(SELF_NAME)
            if cand:
                self.called_reply = True   # 标记——主循环按应答给奖励
                self.called_prompt = any(
                    ch in TONE_W | ASK_WORDS for w in cand for ch in w)
                self.cooldown = COOLDOWN
                self.last_toks = cand
                return ("reply", "/".join(cand))
        # 自身 tick：自发念头（冷却中不表达——不重复复读）
        if self.cooldown > 0:
            self.cooldown -= 1
            return None
        # 好奇 → 主动提问：先尝试问句结构（X是什么——教过后），
        # 没学会 → 指物问（说出新词——妈妈解释后教问句）
        if self.curious and self.ask_cd <= 0:
            w = self.curious.popleft()
            self.ask_cd = ASK_CD
            self.asked_word = w
            q = self._read_ask(w) if w in self.ask_taught else None
            self.last_toks = q or [w]
            return ("ask", "/".join(q or [w]))

    def _read_ask(self, w):
        """问句读出：固化句路径——名词「X是什么」/ 动作词「X怎么做」
        （整句读出含"是/怎么"——自由链会吞桥词走不通）。"""
        if w not in self.pats:
            return None
        for item in self.cons.get(w, []):
            if item[2] in ("ask", "ask_how"):
                return list(item[0])
        return None

    def _read_answer(self, w):
        """答案读出：直接取固化的 answer 类型条目（老师解释句——
        不走 free_read 通用选择，否则 ask 条目总是排在前面）。
        视角绑定（1 对 1）：老师话里的"你"= 网络自己 → 复述时
        换成"我"（网络的第一人称视角内化）。"""
        for item in self.cons.get(w, []):
            if item[2] == "answer":
                toks = list(item[0])
                return ["我" if t in ("你", "宝宝", "孩子") else t
                        for t in toks]
        return None

    def teach_ask(self, w, answer_toks=None):
        """教问句结构（按维度）：
          名词 → 「X是什么」（词义问句——ask 类型）
          动作词 → 「X怎么做」（行为问句——ask_how 类型）
        动态固化（free_read 固化句路径整句读出——自由链会吞桥词）。
        同时把老师刚解释的答案句固化（answer 类型——事后回忆读出）。"""
        if w not in self.pats or w in self.ask_taught:
            return
        # answer 条目放最前：free_read 固化路径未验证时取 pool[0]——
        # 被问到「X是什么」时应优先答解释句（answer），不是问句本身
        if answer_toks:
            self.cons.setdefault(w, []).insert(
                0, (answer_toks[:5], None, "answer"))
        if w in ACTION_WORDS:
            self.cons.setdefault(w, []).append(
                ([w, "怎么", "做"], None, "ask_how"))
            qtype = "怎么做"
        else:
            self.cons.setdefault(w, []).append(
                ([w, "是", "什么"], None, "ask"))
            qtype = "是什么"
        self.ask_taught.add(w)
        self.log.append(f"    [问句] 教会「{w}{qtype}」问句结构"
                        f"（固化——下次能完整问）")
        thought = self.tick_stim()
        if thought:
            for name, ws in MOTIVE.items():
                if any(w in ws for w in thought):
                    self.last_tail = thought[-1]
                    self.last_toks = thought
                    return ("spont", "/".join(thought))  # 自发：自己想到说
        return None

    # ── 验证门沉淀（LLM 评价 → 累积结构，抗单次噪声）──
    def _val_update(self, ctx, text, wrong=False):
        """把贴合度评价写进条件化验证表：{(qtype, 主题, 句): (对, 错)}
        ——好答法累积"对"，坏答法累积"错"（运行内生效，纯内存）。"""
        kw = getattr(self, "last_qkw", "?")
        key = (ctx or "?", kw, tuple(text.split("/")))
        v0, v1 = self.val.get(key, (0, 0))
        self.val[key] = (v0 + (0 if wrong else 1), v1 + (1 if wrong else 0))

    def tick_cooldowns(self):
        """句冷却表递减（时间惩罚自然消退）。"""
        for s in list(self.sent_cd):
            self.sent_cd[s] -= 1
            if self.sent_cd[s] <= 0:
                del self.sent_cd[s]

    # ── 学词吸收（听故事学词：域外词 → 妈妈解释 → 语义边 + 入域）
    #    "看过词不代表懂词"——懂 = 教学域内 + 语义边；解释句整句教学
    def absorb_words(self, txt):
        """妈妈解释句 → 教理解：把域外词（听过不懂）教成"懂"。
        解释句整句教学（共现建语义边）+ 词对加入 teach_out +
        新词加入 domain（从此 free_read 域内可读——真的懂了）。"""
        from schema_net import _learn_sentence
        seq = [w for w in self._split_words(txt) if w in self.pats]
        if not seq:
            return
        self.last_explain = seq        # 记录解释句（答案固化用）
        _learn_sentence(self.ng, seq, self.pats, slot=0)   # 语义边
        for a, b in zip(seq[:-1], seq[1:]):                # 教学出边
            self.teach_out.setdefault(a, set()).add(b)
            self.teach_pairs.add((a, b))   # 沉淀：教学对（resume 恢复）
        # 只吸收网络问的目标词（asked_word）——解释句里的其他词只
        # 建边不入域（避免拟声碎片入域膨胀）
        target = getattr(self, "asked_word", None)
        new_domain = [w for w in seq if w == target and w not in self.domain
                      and w not in FUNC]
        if not new_domain:
            target_ = getattr(self, "asked_word", None)
            if target_ in seq and target_ not in self.domain                     and target_ not in FUNC:
                new_domain = [target_]
        if new_domain:
            self.domain.update(new_domain)
            self.absorbed.extend(new_domain)
            self.log.append(f"    [学词] 听懂了：{'/'.join(new_domain)}"
                            f"（妈妈解释——语义边建立 + 入域）")
        for w in seq:
            self.curious_cnt.pop(w, None)

    # ── 减边/强化（LLM 判定与评价）──────────────────
    def penalize_chain(self, toks):
        """重复惩罚：表达链相邻边 ×0.5（复读——说过了别老说）。"""
        n_pe = 0
        for a, b in zip(toks[:-1], toks[1:]):
            if a not in self.pats or b not in self.pats:
                continue
            dst = set(self.pats[b])
            for i in self.pats[a]:
                row = self.ng.W_out[i][0]
                for j in dst:
                    if j in row:
                        row[j] = row[j] * PENALTY_FACTOR
                        n_pe += 1
        return n_pe

    def boost_chain(self, toks, factor=1.05):
        """高分强化：表达链相邻边 ×factor（说得自然——鼓励多说）。"""
        n_bo = 0
        for a, b in zip(toks[:-1], toks[1:]):
            if a not in self.pats or b not in self.pats:
                continue
            dst = set(self.pats[b])
            for i in self.pats[a]:
                row = self.ng.W_out[i][0]
                for j in dst:
                    if j in row:
                        row[j] = min(row[j] * factor, self.ng.w_max)
                        n_bo += 1
        return n_bo

    def penalize_words(self, words):
        """无效字减边：词神经元出入边 ×0.5（说错了别老说）。
        保护：功能词（FUNC）与需求词（饿/疼/困——语言核心）永不减。"""
        n_ed = 0
        for w in words:
            if w not in self.pats or w in FUNC or w in MOTIVE["需求"]:
                continue
            dst = set(self.pats[w])
            for i in dst:
                row = self.ng.W_out[i][0]
                for j in list(row.keys()):
                    row[j] = row[j] * PENALTY_FACTOR
                    n_ed += 1
        if n_ed:
            self.edged.extend([w for w in words if w in self.pats])
            self.log.append(f"    [减边] 无效字 {'/'.join(words)}"
                            f" 减边 {n_ed} 条（×{PENALTY_FACTOR}）")
        self.invalid_cd = INVALID_CD
        self.junk.clear()
        self.injected = []

    # ── LLM 妈妈（一次调用多功能——AAA 节标记式）─────
    def mom_once(self, need_story, junk_txt, net_say, is_reply=False,
                 is_ask=False):
        """一次调用实现全部功能：按需组合节标记。
        网络表达时附带【自然度】【复杂度】【贴合度】评价（对答额外高分）。
        网络提问（is_ask）→ 妈妈【回应】= 解释这个词 + 【衍生】= 发散
        （孩子知识来源：听故事 → 不懂就问 → 父母发散）。
        答非所问/答不出时附带【示范】（塑造：跟读正确 → 中等奖励，
        独立答对 → 最高分——提高准确率的核心）。
        上下文带"孩子最近会说的话"（ZPD：妈妈问题贴孩子水平）。
        返回 {故事, 无效字, 回应, 衍生, 自然度, 复杂度, 贴合度, 评价,
        示范}。"""
        if not self.has_llm or self.calls >= LLM_BUDGET:
            return None
        self.calls += 1
        self.last_call_tick = self.tick
        secs = []
        if need_story:
            secs.append("【故事】给这个刚学说话的孩子讲一个小故事"
                        "（3-5 句，口语化，有简单情节，像妈妈哄孩子）")
        if junk_txt:
            secs.append(f"【无效字】孩子刚才听到这些字但没任何反应，"
                        f"其中哪些是'无效字'（对孩子语言学习没用的杂字："
                        f"拟声词/语气词/无实义字，如 哒/咯/呀/呢 这类）？"
                        f"字串：『{junk_txt}』——注意：名词动词（兔/树/"
                        f"花/跑/看/笑 等）和常见虚词（的/了/不/很/我/是/"
                        f"在/也/就/都）都不算无效字；只输出无效字清单，"
                        f"顿号分隔，没有就写'无'")
        # ZPD 上下文：孩子最近会说的话（只约束【衍生】【示范】——
        # 故事保持正常，还要出现新词：孩子听不懂才会问——知识的来源）
        zpd = ""
        if self.recent_says or self.scores:
            know = list(self.recent_says)[-3:]
            zpd = (f"孩子最近会说：{'；'.join(know) or '不多'}。"
                   f"【衍生】和【示范】要用孩子会说的简单词（他词汇量"
                   f"有限——问题别太难）；【故事】保持正常的小故事，"
                   f"可以出现 1-2 个孩子没听过的新词（比如蝴蝶/彩虹/"
                   f"蘑菇这样的东西）——孩子听到不懂的会问，"
                   f"这是他学习的好机会。\n")
        if net_say:
            if is_ask:
                # 孩子提问（指物问「蝴蝶？」或完整问句「蝴蝶是什么」）
                # ——妈妈解释 + 发散
                secs.append(f"【回应】孩子问：「{net_say}」——他在问"
                            f"这个词/东西的意思，好奇没见过没听过。请用"
                            f"他会说的简单词一句话解释它是什么（像妈妈"
                            f"蹲下来指着说），解释里要重复说出"
                            f"「{net_say.split('/')[-1]}」两三次"
                            f"（孩子在学这个词）")
                secs.append("【衍生】从这个词发散讲一点相关的（一个小"
                            "知识或一句小故事，1 句）")
            else:
                reply_note = ("这是孩子回答你的问题（对答）——对答说明他在"
                              "和你交流，要给高分；" if is_reply else
                              "这是孩子自己想到主动说的（自发表达）；")
                secs.append(f"【回应】孩子主动说：「{net_say}」——用妈妈的"
                            f"口吻自然地回答他（1-2 句，不评价、不纠正，"
                            f"就接着聊）")
                secs.append("【衍生】从刚才孩子说的话题发散——说一句相关"
                            "的小知识或一句小故事，**也可以**问一个新问题"
                            "（不要每次都是问句——有时就讲点知识，让孩子"
                            "自己想想）")
                secs.append(f"【自然度】给这句话的自然度打分 0-100"
                            f"（像不像人话：语法/语义/连贯；{reply_note}"
                            f"越自然分数越高）")
                secs.append("【复杂度】给这句话的复杂度打分 0-100"
                            "（句子结构丰富程度：词数、连接、修饰；"
                            "越复杂分数越高）")
                secs.append(f"【贴合度】孩子是否直接回答了你刚才说的话"
                            f"（比如你问'饿了吗'他说'我饿了'=直接回答；"
                            f"你问 A 他说 B=答非所问）？0-100——直接回答"
                            f"=100（给最高分），答非所问=0")
                secs.append("【评价】一句话从自然和复杂角度评价这句话"
                            "（≤30 字）")
        if self.need_demo:
            secs.append("【示范】孩子答得不好，给一句他该说的正确话"
                        "（≤8 词，只用他最近会说的简单词），让他跟读"
                        "——像老师带读：'来，跟老师说：xxx'")
        content = ("你是老师，正在教刚学说话的孩子（定式网络）知识。"
                   "孩子只会说简单的词和短句。教学原则：解释客观准确"
                   "（定义式，不比喻不主观抒情）；故事客观（讲事实/常识"
                   "——动物习性、自然现象，可以生动但不能编造和过度拟人）；"
                   "称呼孩子用'你'（他懂'你'=他自己——你饿了吗/你听）；"
                   "不要用'宝宝/孩子'这种第三人称称呼他；说自己时说'我'"
                   "（他会慢慢懂'我'=说话的人）。解释时说'人/它/这'或"
                   "直接客观陈述。请只输出以下节"
                   "标记【故事】/【回应】/【衍生】/【无效字】/【自然度】/"
                   "【复杂度】/【贴合度】/【评价】/【示范】（每个独占一行，"
                   "必须用【】符号——不要用<教学>等标签，不要任何其他内容"
                   "）：\n")
        txt = None
        for _ in range(2):            # 失败重试 1 次（连续请求会变慢——
            txt = _llm_chat([{"role": "user", "content": content}],
                            timeout=15)   # 短超时快速回退，不拖死场景）
            if txt:
                break
            time.sleep(1.0 * (_ + 1))
        d = {}
        cur = None
        for line in (txt or "").splitlines():
            line = line.strip()
            if not line:
                continue
            for k in ("故事", "无效字", "回应", "衍生", "自然度",
                      "复杂度", "贴合度", "评价", "示范"):
                if line.startswith(f"【{k}】"):
                    cur = k
                    d[k] = line[len(f"【{k}】"):].strip()
                    break
            else:
                if cur and cur in d:
                    d[cur] += line
        # 容错：裸输出（无节标记的非空文本）→ 当妈妈直接说的话（【回应】）
        # 容错：裸输出（无节标记且像"话"的文本）→ 当老师直接说的话
        # （含 <> 等符号标签的不是话——丢弃，防格式污染）
        raw = (txt or "").strip()
        if not d and 2 <= len(raw) <= 60 and "<" not in raw and "【" not in raw:
            d["回应"] = raw
        if txt:
            self.llm_replies.append((self.calls, txt))
        return d

    def _split_words(self, txt):
        """句内最长匹配分词（词表词序列）。"""
        words = []
        i = 0
        while i < len(txt):
            hit = None
            for L in range(min(len(txt) - i, 4), 0, -1):
                if txt[i:i + L] in self.pats:
                    hit = txt[i:i + L]
                    break
            if hit:
                words.append(hit)
                i += len(hit)
            else:
                i += 1
        return words

    # 客观故事回退（LLM 失败时用——不卡场景；基于事实/常识）
    FALLBACK_STORIES = [
        "蚂蚁排成队搬米粒，一只搬不动，大家一起抬，就搬回家了。",
        "蝴蝶小时候是毛毛虫，吃树叶长大，变成蛹，最后变成蝴蝶。",
        "松鼠秋天把橡子埋进土里，冬天挖出来吃，忘了的会长成小树。",
        "蜜蜂采花蜜，把花粉带到别的花上，花才能结出果实。",
    ]

    def mom_say(self, txt, scan_curious=False):
        """[听觉] 老师说：xxx——逐字注入网络（听觉刺激源）。
        话中有疑问词 → 记录话中名词（按句内顺序取最后一个词表词——
        网络下 tick 尝试回应）。注入字计数（无效字判定源）。
        好奇扫描只在故事/衍生（scan_curious=True）——回应/解释是
        教学，不再引发好奇链（否则解释句每句都造新好奇，连环问）。"""
        self.mom.append(txt)
        self.log.append(f"    [听觉] 老师说：「{txt}」")
        self.injected = []
        for ch in txt:
            if ch in PUNCT:
                continue
            if ch in self.pats:
                self.injected.append(ch)
                self.hear(ch)
        # 好奇词：词表内但教学域外——听过但不理解（看过词不代表懂词：
        # 蝴蝶/蘑菇/雨 有神经元，但没教过意思 → 想提问）
        if scan_curious:
            for w in self._split_words(txt):
                if w in self.pats and w not in self.domain and \
                        w not in self.teach_out and w not in FUNC and \
                        w not in MOTIVE["需求"] and \
                        w != SELF_NAME and w not in self.cons:
                    # 身份词/固化句里有过 = 学过——不好奇（不懂才问）
                    if w not in self.curious:
                        self.curious.append(w)
                    self.curious_cnt[w] = self.curious_cnt.get(w, 0) + 1
        if any(a in txt for a in ASK_WORDS) or \
                any(w in txt for w in MOTIVE["需求"]):
            # 按句内位置收集全部词表词（非功能词）——网络候选回应；
            # 需求词优先（你饿不饿 → 先答饿；守一你饿不饿 → 问的是饿）
            nouns = []
            i = 0
            while i < len(txt):
                hit = None
                for L in range(min(len(txt) - i, 4), 0, -1):
                    if txt[i:i + L] in self.pats:
                        hit = txt[i:i + L]
                        break
                if hit:
                    if hit not in FUNC and hit not in ASK_WORDS \
                            and hit not in PRONOUNS:
                        nouns.append(hit)
                    i += len(hit)
                else:
                    i += 1
            if nouns:
                nouns.sort(key=lambda w: w not in MOTIVE["需求"])
                self.q_nouns = nouns
                self.q_txt = txt          # 记录妈妈提问原文（问题分型用）
        # 听觉学习（2026-08-11）：印象进边——不固化（固化表 = 函数
        # 工具——网络失去"自己组"的能力）。两种教法：
        # ① 规则句（听到X要说Y——父母教学指令）1 次学会；
        # ② 对话示范（守一，我在呢）听 ≥2 次学会。
        # 学 = _learn_sentence 建语义边 + teach_out 注册——被叫时沿
        # 边读出；边被 sleep 删除（遗忘）→ 自然读不出（生命周期）。
        toks = self._split_words(txt)
        trigger = reply = None
        if "听到" in toks and not self.heard_rule_learned:
            # 规则句：听到[触发]（要/就）说[应答]
            skip = {"要", "就", "说", "了", "的", "老师", "妈妈", "爸爸", "你"}
            for i, w in enumerate(toks):
                if w == "听到":
                    for w2 in toks[i + 1:]:
                        if w2 not in skip:
                            trigger = w2
                            break
                    break
            say_idx = [i for i, w in enumerate(toks) if w == "说"]
            if say_idx:
                reply = toks[say_idx[-1] + 1:]
            if trigger and reply:
                self.heard_rule_learned = True
                self._learn_reply(trigger, reply, f"规则句「{txt}」")
        elif SELF_NAME in toks and self.learned_reply is None:
            others = [w for w in toks if w != SELF_NAME]
            # 示范判定：应答必须"我"开头（被叫者用第一人称说自己——
            # "守一，我在呢" ✓；"守一你饿不饿"是对话/提问不是示范 ✗
            # ——防把问话回声学成应答）
            if others and others[0] == "我":
                self.heard_reply += 1
                if self.heard_reply >= 2:
                    self._learn_reply(SELF_NAME, others[:5],
                                      f"示范「{txt}」×2")


def main():
    t0 = time.time()
    random.seed(SEED)
    print("═══ 妈妈 LLM 场景 v2（三刺激源 + 一次调用多功能 + 10 次预算）═══\n")
    resume = "--resume" in sys.argv
    net = SceneMomLLM(resume=resume)
    if resume:
        v = _latest_scene_ver() or "35.0"
        print(f"[加载] 场景沉淀 v{v} ✓（恢复 {len(net.absorbed)} 个学词/"
              f"{len(net.ask_taught)} 个问句结构——记忆延续）")
    else:
        print(f"[加载] v35.0 ✓ | 黑洞治疗 {net.n_ring} 对回声环")
    print(f"LLM：{'有' if net.has_llm else '无'} | 预算 {LLM_BUDGET} 次")
    net.mom_say("你饿了吗")      # 开场：听觉刺激源（老师说"你"=网络——人称绑定）
    last_mom_story = -999
    for tick in range(1, 440):
        net.tick = tick
        net.phase = tick % PHASES
        net.tick_cooldowns()          # 句冷却递减（时间惩罚消退）
        # 环境刺激源（场景事件）
        if tick in ENV_EVENTS:
            for w in ENV_EVENTS[tick]:
                net.env_stim(w)
        # 网络处理（听觉组词 / 被提问响应 / 自身 tick 念头）
        out = net.process()          # (marker, text) 或 None
        marker, text = (out if out else (None, None))
        is_repeat = False
        if out:
            net.said.append(text)
            net.silence = 0
            if marker == "ask":
                # 好奇提问（指物问）——不评分不奖惩：回答就是奖励
                net.n_ask += 1
                net.ask_mem.append({"kw": net.asked_word or text,
                                    "tick": tick})
                net.log.append(f"    [提问] 网络问：「{text}？」"
                               f"（听故事听到不懂的——主动问）")
            elif marker in ("recall_q", "recall_a"):
                # 事后回忆回答——不调 LLM，规则验证
                if marker == "recall_q":
                    net.log.append(f"    [回忆] 网络答：「{text}」"
                                   f"（记得问过的问题——完整问句！）")
                    net.mom_say("那老师是怎么回答你的呀")
                    net.log.append(f"    [询问] 妈妈追问：答案还记得吗")
                else:
                    ok = (net.recall and net.recall["stage"] == 2
                          and any(w in text for w in
                                  (net.recall["kw"],)))
                    net.log.append(f"    [回忆] 网络答：「{text}」"
                                   f"（{'记得答案 ✓' if ok else '答案记不全'
                                      f'——妈妈再说一遍'}）")
                    if not ok:
                        ans_toks = net._read_answer(net.recall["kw"])
                        if ans_toks:
                            net.mom_say("".join(ans_toks) + "，记住了吗")
                            net.ask_cd = 10   # 重教后稍等再回忆
                    if ok:
                        net.n_recall_ok += 1
                        net.ng.release_da(1)   # 记得答案=有价值（调质）
                        net.log.append(f"    [奖励] 记得问题+答案——信号+1，"
                                       f"内部加边 {nb} 条（网络自定）")
                    net.recall = None      # 回忆验证结束
            elif net.called_reply:
                # 被叫应答奖励（2026-08-11）：叫了就该答——不参与重复
                # 惩罚。只有应答带语气词/疑问词（我在呢/嗯——表示"听
                # 到了"）才给奖励：正确应答（含"我"）一直给最高分；错
                # 误应答 ≤10 次给基础奖励，之后停。纯身份句（守一是
                # 我的名字——没有"听到了"表示）→ 应答但不奖励。
                net.called_reply = False
                net.recent_says.append(text)
                net.streak += 1
                net.last_q_txt = net.q_txt
                if not net.called_prompt:
                    net.log.append(f"    [应答] 被叫「{SELF_NAME}」→ 答「{text}」"
                                   f"——无语气/疑问（没表示听到）——应答但不奖励")
                    net.called_prompt = False
                else:
                    net.called_prompt = False
                    good = "我" in text.split("/")
                    if good:
                        net.ng.release_da(2)   # 正确应答=好处大（调质）
                        net.log.append(f"    [应答] 被叫「{SELF_NAME}」→ 答「{text}」"
                                       f"——正确应答 信号+2（好处大）"
                                       f"内部加边 {nb} 条")
                    elif net.bad_reply < 10:
                        net.bad_reply += 1
                        net.ng.release_da(1)   # 错误应答=弱信号（鼓励尝试）
                        net.log.append(f"    [应答] 被叫「{SELF_NAME}」→ 答「{text}」"
                                       f"——错误应答 信号+1（{net.bad_reply}/10）"
                                       f"内部加边 {nb} 条")
                    else:
                        nb = 0
                        net.log.append(f"    [应答] 被叫「{SELF_NAME}」→ 答「{text}」"
                                       f"——错误应答超 10 次——不再奖励")
            elif text in net.recent_says and net.q_txt != net.last_q_txt:
                # 重复（复读）→ 外部坏信号 + 习惯化加速（重复=没意思
                # ——新奇快速耗尽）——内部决定停止加边
                is_repeat = True
                net.streak = 0
                net.ng.release_da(-1)   # 复读=惩罚（负调质——抑制学习）
                net.log.append(f"    [重复] 换了问题还说「{text}」——"
                               f"信号-1 + 新奇减半（复读惩罚——内部化）")
            else:
                net.recent_says.append(text)
                net.streak += 1
                net.last_q_txt = net.q_txt
                # 表达 = 基线学习（STDP 自带"第一次+1"）；外部不注入调质
                # ——正反馈（正确/好处大）由上级分支 release_da 提供
                net.log.append(f"    [表达] 网络说：「{text}」"
                               f"（{'对答：回答妈妈' if marker == 'reply' else '自发'}"
                               f"）[基线 STDP 学习，多巴胺 "
                               f"{net.ng.da:+.2f}，连续对答 {net.streak} 次]")
        else:
            net.silence += 1
        if net.invalid_cd > 0:
            net.invalid_cd -= 1
        # 内生睡眠（治疗五-阶段2——Borbély Process S——活动驱动）：
        # 活动量累积超阈值 → SHY 睡眠（缩放+豁免+gain归一+压力清零）
        if net.ng.sleep_pressure() > SLEEP_PRESSURE_THR:
            cleared, scaled, spared, thr, n_gain = net.ng.sleep_downscale()
            net.log.append(f"    [睡眠] 活动量超阈值——SHY 睡眠"
                           f"（缩放 {scaled} 豁免 {spared} gain 归 {n_gain}）"
                           f"——压力清零")
        if net.ask_cd > 0:
            net.ask_cd -= 1
        if net.sent_cd:
            pass  # 冷却表已由 tick_cooldowns 递减
        # 事后询问：最早的未询问提问 ≥30 tick 后妈妈问「你刚才问什么
        # 了」（模板话——回忆验证不占 LLM 预算）
        mem = next((m for m in net.ask_mem if not m.get("asked")), None)
        if (mem and net.recall is None
                and tick - mem["tick"] >= 30
                and net.calls < LLM_BUDGET):
            net.recall = {"kw": mem["kw"], "stage": 0}
            mem["asked"] = True
            net.mom_say("你刚才问老师什么了呀")
            net.log.append(f"    [询问] 妈妈事后问（验证网络记得）")
        # LLM 介入判定：只有 ①守一主动回答（reply）②守一主动提问
        # （ask）③一直在思考没说话（沉默 ≥ SILENCE_TICK）才调用——
        # 自发表达/例行故事/无效字不再单独触发（省预算、调用即互动）
        reply_ask = (out and not is_repeat and marker in ("reply", "ask"))
        need_story = (net.silence >= SILENCE_TICK
                      and tick - last_mom_story > 15)
        # 无效字：单句注入 ≥ LONG_SENT 字（>10 或 >20——网络听了一长串
        # 单字）且冷却结束 → 判定其中哪些无效 → 减边（随本轮调用处理
        # ——不单独触发）
        junk_txt = ("".join(net.injected) if (len(net.injected) >= LONG_SENT
                                              and net.invalid_cd <= 0) else "")
        if (reply_ask or need_story) and net.calls < LLM_BUDGET                 and tick - net.last_call_tick >= 15:  # 节流：连续请求会变慢
            d = net.mom_once(need_story, junk_txt,
                             text if not is_repeat else None,
                             is_reply=(marker == "reply" and not is_repeat),
                             is_ask=(marker == "ask"))
            if d is None and need_story:
                # 失败回退：客观故事模板（LLM 失败也不让场景空转）
                fb = net.FALLBACK_STORIES[(net.calls // 2) %
                                          len(net.FALLBACK_STORIES)]
                net.mom_say(fb, scan_curious=True)
                last_mom_story = tick
                net.log.append(f"    [回退] LLM 失败——用客观故事模板")
            # 无论成败：判定消费后清空注入字 + 冷却（防连打吃预算）
            if junk_txt:
                net.injected = []
                net.invalid_cd = INVALID_CD
            if d:
                if d.get("故事"):
                    last_mom_story = tick
                    net.injected = []        # 故事是主动讲——不判无效字
                    net.mom_say(d["故事"], scan_curious=True)
                if d.get("回应"):
                    net.mom_say(d["回应"])
                    net.absorb_words(d["回应"])   # 解释句 → 学新词
                    if net.asked_word:            # 解释后 → 教问句结构
                        ans_toks = [w for w in net._split_words(d["回应"])
                                    if w in net.pats]
                        net.teach_ask(net.asked_word, ans_toks)
                        net.asked_word = None
                if d.get("衍生"):
                    net.mom_say(d["衍生"], scan_curious=True)
                    net.absorb_words(d["衍生"])
                if d.get("示范"):
                    demo = d["示范"]
                    net.mom_say(f"来，跟老师说：{demo}")
                    # 跟读引导：示范的词表词进入候选（网络尝试复述）
                    nouns = [w for w in net._split_words(demo)
                             if w in net.pats and w not in FUNC]
                    if nouns:
                        net.q_nouns = nouns
                    net.need_demo = False
                    net.log.append(f"    [示范] 老师带读（跟读正确=中等"
                                   f"奖励，独立答对=最高分）")
                # 自然度/复杂度/贴合度评价：综合分 = 自然×0.35 + 复杂×0.30
                # + 贴合×0.35（温和化）；贴合 ≥85 → 最高分 ×1.08；
                # 综合 ≥75 → ×1.06；贴合 <50（答非所问）→ 句冷却 + 重犯减边
                if d.get("自然度") and d.get("复杂度"):
                    try:
                        nat = float(d["自然度"])
                        cpx = float(d["复杂度"])
                        fit = float(d.get("贴合度", 0) or 0)
                    except ValueError:
                        nat = cpx = fit = None
                    if nat is not None:
                        comb = nat * W_NAT + cpx * W_CPX + fit * W_FIT
                        net.scores.append(
                            {"tick": tick, "say": text,
                             "nat": nat, "cpx": cpx, "fit": fit,
                             "comb": comb, "reply": marker == "reply",
                             "note": d.get("评价", "")[:30]})
                        net.log.append(
                            f"    [评价] 自然 {nat:.0f} 复杂 {cpx:.0f}"
                            f" 贴合 {fit:.0f} 综合 {comb:.0f}"
                            f"（{'对答' if marker == 'reply' else '自发'}）"
                            f"{d.get('评价', '')[:24]}")
                        if fit < 50 and marker == "reply":
                            # 答非所问（仅对答）→ 句冷却（时间
                            # 惩罚——不伤结构）+ 验证门错计数 + 下次示范
                            # + 多巴胺负信号（重复/答错 → 学习被抑制）
                            net.sent_cd[text] = SENT_CD_TICKS
                            net.streak = 0
                            net.offend[text] = net.offend.get(text, 0) + 1
                            net._val_update(net.last_ctx, text, wrong=True)
                            net.need_demo = True    # 下次调用妈妈给示范（塑造）
                            if net.offend[text] >= 2:
                                net.ng.release_da(-1)   # 重犯 → 负调质
                            net.log.append(
                                f"    [答非所问] 贴合 {fit:.0f}——句子冷却 "
                                f"40 tick（重犯 {net.offend[text]} 次"
                                f"{'，多巴胺-1（学习被抑制）' if net.offend[text] >= 2 else ''}"
                                f"；下次示范）")
                        elif fit >= 85:            # 直接回答 → 好处大（强 DA）
                            # + 验证门正例沉淀（累积成标准答案）
                            net._val_update(net.last_ctx, text, wrong=False)
                            net.ng.release_da(2 if net.streak >= 3 else 2)
                            net.log.append(f"    [最高分] 直接回答——"
                                           f"多巴胺 +2（好处大——后续学习"
                                           f" ×3）+ 验证门正例")
                        elif comb >= 75:
                            net.ng.release_da(1)
                            net.log.append(f"    [强化] 高分——多巴胺 +1"
                                           f"（有价值——后续学习 ×2）")
                if d.get("无效字") and d["无效字"].strip() not in ("无", ""):
                    net.penalize_words(
                        [w for w in d["无效字"].replace("，", "、").split("、")
                         if w])
        elif net.calls >= LLM_BUDGET and (need_story or junk_txt or out):
            net.log.append(f"    [预算] 调用用尽（{LLM_BUDGET} 次）——"
                           f"妈妈静默")
        # 日志
        if net.log:
            for line in net.log:
                print(f"t{tick:>3}（CLK_{net.phase:>2}）{line}")
            net.log = []

    # ── 汇总 ─────────────────────────────────────────
    print(f"\n═══ 汇总 ═══")
    print(f"  LLM 调用：{net.calls} 次（预算 {LLM_BUDGET}）")
    print(f"  网络主动表达：{len(net.said)} 次")
    for s in net.said[:12]:
        print(f"    「{s}」")
    print(f"  老师说的话（听觉刺激源）：{len(net.mom)} 句")
    print(f"  无效字减边：{len(net.edged)} 字 "
          f"（{'/'.join(net.edged[:8]) or '无'}）")
    print(f"  听故事学词（吸收新词）：{len(net.absorbed)} 个"
          f"（{'/'.join(net.absorbed[:8]) or '无'}）")
    print(f"  网络主动提问：{net.n_ask} 次（指物问——不懂就问）")
    if net.scores:
        print(f"  表达评价（LLM）：{len(net.scores)} 条")
        for s in net.scores:
            print(f"    t{s['tick']:>3} 「{s['say']}」"
                  f" 自然 {s['nat']:.0f} 复杂 {s['cpx']:.0f}"
                  f" 贴合 {s['fit']:.0f} 综合 {s['comb']:.0f}"
                  f"（{'对答' if s['reply'] else '自发'}）"
                  f" {s['note']}")
        rep = [s for s in net.scores if s["reply"]]
        sp = [s for s in net.scores if not s["reply"]]
        print(f"  贴合度：对答均 "
              f"{sum(s['fit'] for s in rep)/len(rep):.1f}"
              f"（直接回答妈妈的话=最高分——用户规则）"
              f" | 直接回答 {sum(1 for s in net.scores if s['fit'] >= 85)}/"
              f"{len(net.scores)} 次")
    print(f"\n═══ LLM 原始回答（{len(net.llm_replies)} 次）═══")
    for i, (calls, txt) in enumerate(net.llm_replies, 1):
        print(f"─── 第 {calls}/{LLM_BUDGET} 次调用 ───")
        print(txt)
    n_val = len([k for k in net.val if len(k[2]) >= 2])
    print(f"\n═══ 验证门沉淀（运行内累积）═══")
    for k, v in list(net.val.items()):
        if v[0] + v[1] >= 2 and len(k[2]) >= 2:
            print(f"  ({k[0]},{k[1]},{'/'.join(k[2])}): {v[0]}对/{v[1]}错")
    # ── 场景沉淀（记忆不丢——下次 --resume 恢复）──
    # 节制：本轮有学习（新学词/提问/回忆成功）才存——防快照链污染
    n_new = len(net.absorbed) - net.base_absorbed
    if n_new > 0 or net.n_ask > 0 or net.n_recall_ok > 0:
        metrics = {"calls": net.calls, "n_ask": net.n_ask,
                   "absorbed": len(net.absorbed),
                   "recall_ok": net.n_recall_ok}
        ver = _save_scene(net.ng, net.cons, net.val, net.absorbed,
                          net.ask_taught, net.teach_pairs, metrics,
                          pats=net.pats, cursor=net.cursor)
        print(f"[沉淀] 已保存场景快照 v{ver}（本轮 +{n_new} 学词/"
              f"提问 {net.n_ask}/回忆 {net.n_recall_ok}；"
              f"累计 {len(net.absorbed)} 学词 + "
              f"{len(net.ask_taught)} 问句结构）")
    else:
        print("[沉淀] 本轮无新学习——跳过快照（防链污染；"
              "下次 --resume 继续上次）")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
