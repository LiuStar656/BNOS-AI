# -*- coding: utf-8 -*-
"""生成有偏语料 corpus_biased.json（真实有偏语料验证，A 方案第一步）。

动机：corpus_large.json 是 22 模板**等概率轮转**抽样 → uniform 分布（45 个宾语
各 1 次），转移后继平局率最大化——trace/grad 的最不利场景（Phase 2 发现②）。
本脚本制造**有偏**语料，三层偏斜：
  ① 全局词频 Zipf（高频词多用、低频词少用）
  ② 模板带权重（常见句式高频）
  ③ **主语→宾语偏好关联**（条件偏斜核心）：不同主语有不同偏好子集
     （我→看书/听音乐…，他→打篮球/踢足球…，她→画画/唱歌…）——合并视图下
     "喜欢"后继近似平局，但按主语分组后继明确 → trace 借主语痕迹破平局、
     梯度学主语-宾语关联的甜区（corpus_ctx 思路在主语料上的展开）
目标：词表 ≥500、句数 2000+、后继平局率下降。可复现：固定 seed。
"""
import json
from collections import Counter
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent
rng = np.random.default_rng(2026)

# ── 基础真实句（现有 100 句）──
base = json.loads((DATA / "corpus.json").read_text(encoding="utf-8"))

# ── 变量池（口语活动词，PREF 外不参与条件偏斜，拆词无妨）──
WANT = ["吃火锅", "去旅游", "看电影", "买书", "学吉他", "学游泳", "跑步减肥",
        "养宠物", "开公司", "写小说", "环游世界", "睡懒觉", "吃甜品", "打游戏",
        "看演唱会", "学做饭", "考驾照", "换手机", "买电脑", "去海边", "看星星",
        "爬山", "钓鱼", "种花", "做手工", "写日记", "学钢琴", "看动画",
        "学摄影", "骑摩托", "学画画", "做木工", "研究机器人", "学历史", "玩桌游",
        "学做菜", "整理房间", "参加比赛", "学外语", "去露营"]
MOODS = ["很高兴", "很难过", "很累", "很忙", "很闲", "很饿", "很困", "很激动",
         "很紧张", "很放松", "很开心", "很疲惫", "很焦虑", "很平静", "很兴奋",
         "很无聊", "很充实", "很孤独", "很幸福", "很迷茫"]
DAYS = ["今天", "昨天", "明天"]
ACT = ["上班", "上学", "看电影", "吃饭", "跑步", "购物", "开会", "加班", "旅行", "回家",
       "散步", "健身", "睡觉", "写报告", "做实验", "打扫卫生", "买菜", "修电脑", "见朋友", "出差"]
ADJS = ["真好看", "真好吃", "真有意思", "真好玩", "真好听", "真漂亮",
        "真可爱", "真感人", "真好笑", "真不错", "真糟糕", "真麻烦", "真精彩", "真热闹"]
OBJS = ["这部电影", "这道菜", "这本书", "这个游戏", "这首歌", "这个地方",
        "这只猫", "这个故事", "这个笑话", "这个天气", "这条街", "这双鞋",
        "这个方案", "这个任务", "这个假期", "这部动画", "这个软件", "这次旅行"]
PLACES = ["公司", "学校", "公园", "家里", "图书馆", "健身房", "餐厅", "电影院",
          "超市", "医院", "车站", "海边", "山上", "咖啡馆", "办公室", "实验室", "球场",
          "机场", "码头", "体育馆", "剧场", "书店", "花店", "药店", "理发店", "银行", "游泳馆",
          "博物馆", "游乐园", "植物园", "动物园", "水族馆"]
TIMES = ["早上", "中午", "下午", "晚上", "周末", "工作日", "放假的时候", "下雨的时候", "有空的时候", "放假时",
         "清晨", "傍晚", "半夜", "天亮前", "天黑后"]
REASONS = ["太累了", "没有时间", "天气不好", "心情不好", "工作太忙", "太贵了",
           "距离太远", "已经试过了", "朋友推荐", "以前就想去", "感觉不错", "需要休息",
           "想放松一下", "明天再说", "下次一定"]
# 主语 12 个：各主语 top1 偏好词互不相同（合并"喜欢"后继近似平局的必要条件）
SUBJECTS = ["我", "你", "他", "她", "爸爸", "妈妈", "朋友", "同事", "妹妹", "哥哥", "邻居", "同学"]

# 新变量池（扩词表 + 制造更多后继平局源）
FOOD = ["火锅", "烧烤", "饺子", "面条", "米饭", "包子", "馒头", "炒面", "粉", "菜",
        "汤圆", "粽子", "月饼", "烧饼", "烤鱼", "凉面", "蛋炒饭", "红烧肉", "酸辣粉", "白粥"]
WEATHER = ["晴天", "下雨", "阴天", "刮风", "下雪", "多云", "雷雨", "起雾",
           "打雷", "大晴天", "暴风雨"]
PROFS = ["医生", "老师", "护士", "司机", "厨师", "律师", "警察", "工人", "农民", "店员", "老板", "保安",
         "木匠", "修理工", "会计", "设计师"]
LANG = ["数学", "语文", "英语", "物理", "化学", "历史", "地理", "音乐", "体育", "美术",
        "生物", "政治", "计算机", "经济学", "哲学"]
FAMILY = ["弟弟", "姐姐", "爷爷", "奶奶", "儿子", "女儿", "孙子", "孙女", "侄子", "外甥"]
FREQ = ["每天", "常常", "偶尔", "很少", "经常", "每周", "总是", "从不"]
THING = ["手表", "耳机", "雨伞", "台灯", "闹钟", "背包", "鞋子", "帽子", "花瓶", "窗帘"]
VERBS_NO_LIKE = ["想", "觉得", "知道", "记得", "希望", "打算", "习惯"]   # T_verb_want 专用（去"喜欢"，避免污染"喜欢"后继平局）

GREET = ["你好", "你好吗", "早上好", "晚上好", "最近怎么样", "好久不见",
         "很高兴见到你", "再见", "保重", "晚安", "欢迎光临", "祝你顺利",
         "生日快乐", "恭喜恭喜", "新年快乐", "一路顺风", "辛苦了", "慢走",
         "多多关照", "请多指教", "别来无恙", "后会有期", "周末愉快", "午安"]
QUESTION = ["你吃饭了吗", "你今天忙不忙", "你喜欢什么运动", "你周末有什么安排",
            "最近在忙什么", "你觉得这个方案怎么样", "你想去哪里玩", "你今天心情怎么样",
            "你周末去不去公园", "你明天有空吗", "你要不要一起吃饭", "你觉得怎么样",
            "你家住在哪里", "你几点下班", "你喜不喜欢看球", "你最近看了什么电影",
            "你学了什么新东西", "你晚饭吃了吗", "你这个月忙不忙", "你周末去不去爬山",
            "你锻炼身体吗", "你平时听什么歌", "你几点睡觉", "你今天去哪里了",
            "你家有几口人", "你养过宠物吗", "你上班远不远", "你经常加班吗",
            "你周末去哪里玩", "你最近看了什么书", "你平时怎么上班", "你中午吃什么",
            "你昨晚睡得好吗", "你下周有什么计划", "你最喜欢哪个季节", "你周末有空吗",
            "你昨天晚上吃了什么", "你平时喜欢吃什么", "你最近在学什么", "你放假打算去哪",
            "你以前住哪里", "你周末睡到几点", "你上次考试考了多少分", "你打算学什么专业",
            "你早饭吃了吗", "你家养了什么动物", "你昨天见过谁", "你的手表多少钱"]


def zipf_weights(n, s=1.0):
    """Zipf 权重：w_i = 1/(i+1)^s（i 从 0 起），归一化。"""
    r = np.arange(1, n + 1)
    w = 1.0 / r ** s
    return w / w.sum()


def pick(items, weights=None):
    """按权重取一个元素（缺省 = 均匀）。"""
    if weights is None:
        weights = np.ones(len(items)) / len(items)
    return items[int(rng.choice(len(items), p=weights))]


# ── 主语→宾语偏好（条件偏斜核心）────────────────────────────────
# 关键：① 偏好词必须是 jieba **单 token**（复合词"打篮球"会被拆成"打/篮球"，
#       抹平条件关联）；② 必须同时有"主语+宾语"**直接相邻**的短句式，让
#       W[宾语←主语] 非零——否则 trace 借主语痕迹时 W[w←主语]=0 帮不上破局。
# 主语偏好（单 token 活动词，各主语区分度明确；**top1 互不相同**保证
# 合并视图下"喜欢"后继近似平局——trace 破局的前提）
PREF = {
    "我": ["看书", "散步", "喝茶", "读书", "写作", "做饭", "唱歌", "购物", "逛街", "写字"],
    "你": ["旅行", "跑步", "健身", "爬山", "摄影", "瑜伽", "游泳", "逛街", "冥想", "散步"],
    "他": ["打", "踢", "下棋", "钓鱼", "爬山", "跑步", "健身", "编程", "看", "摄影"],
    "她": ["画画", "唱歌", "跳舞", "养花", "购物", "瑜伽", "冥想", "逛街", "看书", "织"],
    "爸爸": ["钓鱼", "下棋", "做饭", "看", "跑步", "爬山", "摄影", "写字", "养花", "健身"],
    "妈妈": ["做饭", "购物", "散步", "养花", "看书", "瑜伽", "织", "打扫", "唱歌", "跳舞"],
    "朋友": ["吃", "旅行", "打", "爬山", "唱歌", "看", "跳舞", "逛街", "下棋", "健身"],
    "同事": ["上班", "加班", "跑步", "健身", "喝茶", "看书", "编程", "看", "出差", "购物"],
    "妹妹": ["跳舞", "唱歌", "画画", "跑步", "读书", "写字", "逛街", "下棋", "爬山", "购物"],
    "哥哥": ["踢", "打", "下棋", "跑步", "健身", "编程", "看", "钓鱼", "爬山", "摄影"],
    "邻居": ["养", "下棋", "散步", "聊天", "喝茶", "钓鱼", "看", "浇", "种", "修"],
    "同学": ["跑步", "打", "学", "画画", "唱歌", "看书", "逛街", "打游戏", "编程", "旅游"],
}
W_PREF = {s: zipf_weights(len(PREF[s]), 1.5) for s in SUBJECTS}   # 陡：每主语 top 偏好占比 ~50%

# 全局 Zipf 权重
W_WANT = zipf_weights(len(WANT), 1.0)
W_MOOD = zipf_weights(len(MOODS), 1.2)
W_ACT = zipf_weights(len(ACT), 1.0)
W_ADJ = zipf_weights(len(ADJS), 1.1)
W_OBJ = zipf_weights(len(OBJS), 1.0)
W_PLACE = zipf_weights(len(PLACES), 1.0)
W_TIME = zipf_weights(len(TIMES), 1.2)
W_REASON = zipf_weights(len(REASONS), 1.0)
W_FOOD = zipf_weights(len(FOOD), 1.0)
W_WEATHER = zipf_weights(len(WEATHER), 1.0)
W_PROF = zipf_weights(len(PROFS), 1.0)
W_LANG = zipf_weights(len(LANG), 1.0)
W_FAMILY = zipf_weights(len(FAMILY), 1.0)
W_FREQ = zipf_weights(len(FREQ), 1.0)
W_THING = zipf_weights(len(THING), 1.0)
W_SUBJ = np.ones(len(SUBJECTS)) / len(SUBJECTS)   # 完全均匀：各主语句量一致（合并后继平局、trace 破局的前提）


def pref(s):
    """按主语偏好取一个词。"""
    return pick(PREF[s], W_PREF[s])


def subj():
    return pick(SUBJECTS, W_SUBJ)


# ── 模板（fn, weight）：主语相关模板制造条件偏斜 ──
# 注意：subj() 必须只取一次（先固定主语，再按该主语取偏好），否则主语-偏好错配。
def T_short():
    s = subj()
    return s + pref(s)                       # 我看书（短句式：W[宾语←主语] 非零的关键）

def T_like():
    s = subj()
    return s + "喜欢" + pref(s)              # 我喜欢看书

def T_also_like():
    s = subj()
    return s + "也" + "喜欢" + pref(s)       # 他也喜欢打篮球

def T_not_like():
    s = subj()
    return s + "不" + "喜欢" + pref(s)       # 她不喜欢画画

def T_like_and():
    s = subj()
    return s + "喜欢" + pref(s) + "和" + pref(s)   # 我喜欢看书和散步

def T_verb_want():
    s = subj()
    return s + pick(VERBS_NO_LIKE, zipf_weights(len(VERBS_NO_LIKE), 1.2)) + pick(WANT, W_WANT)   # 他想去旅游

def T_not_want():
    s = subj()
    return s + "不想" + pick(WANT, W_WANT) + "了"

def T_like_reason():
    s = subj()
    return s + "喜欢" + pref(s) + "因为" + pick(REASONS, W_REASON)

def T_like_q():
    s = subj()
    return s + "喜欢" + pref(s) + "吗"          # 你喜欢旅行吗（通用 subj()，不固定"你"）

def T_eat():
    s = subj()
    return s + "吃" + pick(FOOD, W_FOOD)        # 他吃火锅

def T_want_eat():
    s = subj()
    return s + "想" + "吃" + pick(FOOD, W_FOOD)  # 我想吃面条

def T_weather():
    return "今天" + pick(WEATHER, W_WEATHER) + "了"   # 今天下雨了

def T_job():
    s = subj()
    return s + "是" + pick(PROFS, W_PROF)       # 他是医生

def T_study():
    s = subj()
    return s + "学" + pick(LANG, W_LANG)        # 她学英语

def T_day_act():
    return pick(DAYS, zipf_weights(3, 1.0)) + subj() + pick(ACT, W_ACT) + "了"   # 今天我上班了

def T_yday_place_act():
    s = subj()
    return s + pick(DAYS, zipf_weights(3, 1.0)) + "在" + pick(PLACES, W_PLACE) + pick(ACT, W_ACT) + "了"  # 他昨天在公司加班了

def T_day_go():
    return "今天" + pick(TIMES, W_TIME) + subj() + "去" + pick(PLACES, W_PLACE)  # 今天下午我去海边

def T_reason_mood():
    return "因为" + pick(REASONS, W_REASON) + subj() + "很" + pick(MOODS, W_MOOD)

def T_day_mood():
    return "今天" + subj() + "很" + pick(MOODS, W_MOOD)   # 今天他很累

def T_family():
    s = subj()
    return s + "有" + pick(FAMILY, W_FAMILY)              # 他有弟弟

def T_freq_act():
    s = subj()
    return s + pick(FREQ, W_FREQ) + pick(ACT, W_ACT)      # 他每天跑步

def T_buy_thing():
    s = subj()
    return s + "买" + "了" + pick(THING, W_THING)         # 他买了手表

TEMPLATES = [
    (T_short, 12),
    (T_like, 20),
    (T_also_like, 10),
    (T_like_and, 6),
    (T_like_q, 4),
    (T_not_like, 6),
    (T_verb_want, 8),
    (T_not_want, 3),
    (T_like_reason, 3),
    (T_eat, 6),
    (T_want_eat, 4),
    (T_weather, 6),
    (T_job, 4),
    (T_study, 4),
    (lambda: "我觉得" + pick(OBJS, W_OBJ) + pick(ADJS, W_ADJ), 12),    # 我觉得这部电影真好看
    (lambda: "我觉得" + "很" + pick(MOODS, W_MOOD), 8),                # 我觉得很累
    (T_day_act, 10),
    (T_yday_place_act, 8),
    (T_day_go, 8),
    (T_reason_mood, 5),
    (T_day_mood, 5),
    (T_family, 4),
    (T_freq_act, 6),
    (T_buy_thing, 4),
    (lambda: "你" + "觉得" + pick(OBJS, W_OBJ) + pick(ADJS, W_ADJ) + "吗", 4),
    (lambda: "我们" + pick(["一起", "经常", "偶尔", "很少", "总是"], zipf_weights(5, 1.0)) + pick(ACT, W_ACT), 6),
    (lambda: pick(QUESTION), 10),
    (lambda: pick(GREET), 6),
]

N_TARGET = 15000


def gen_biased(rng):
    wsum = sum(w for _, w in TEMPLATES)
    probs = [w / wsum for _, w in TEMPLATES]
    out = []
    for _ in range(N_TARGET):
        t = rng.choice(len(TEMPLATES), p=probs)
        out.append(TEMPLATES[t][0]())
    return out


syn = gen_biased(rng)
# 不去重：重复句是频率统计信号（真实对话语料高频句重复出现），
# 模板组合有限（8 主语×10 偏好=80 种），去重会把频率信息砍成 1 条。
out = list(base) + syn

(DATA / "corpus_biased.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"生成 {len(out)} 句（基础 {len(base)} + 合成 {len(out) - len(base)}）→ data/corpus_biased.json")


# ── 统计对比（与 corpus_large 对照）──
def corpus_stats(toks_list):
    freq = Counter(w for toks in toks_list for w in toks)
    order = sorted(freq.values(), reverse=True)
    n_tok = sum(order)
    top10_share = sum(order[:10]) / n_tok
    z = np.array(order, dtype=float) / n_tok
    h_freq = -(z * np.log2(z)).sum()
    h_freq_max = np.log2(len(order))
    succ = {}
    for toks in toks_list:
        for a, b in zip(toks, toks[1:]):
            succ.setdefault(a, Counter())[b] += 1
    n_uniq = np.array([len(c) for c in succ.values()])
    h_succ = []
    for a, c in succ.items():
        vals = np.array(list(c.values()), dtype=float)
        p = vals / vals.sum()
        h_succ.append(-(p * np.log2(p)).sum())
    h_succ = np.array(h_succ)
    # 近似平局源词占比：后继熵 > 0.75 × log2(后继数)（信息利用率低 = 平局）
    tie_share = np.mean(h_succ > 0.75 * np.log2(n_uniq + 1))
    return {
        "n_sent": len(toks_list), "n_tok": n_tok, "vocab": len(freq),
        "top10_share": round(top10_share, 3),
        "freq_entropy_norm": round(h_freq / h_freq_max, 3),
        "succ_uniq_mean": round(float(n_uniq.mean()), 1),
        "succ_entropy_norm": round(float((h_succ / np.log2(n_uniq + 1)).mean()), 3),
        "tie_share": round(float(tie_share), 3),
    }


import jieba

for name, path in [("corpus_large", DATA / "corpus_large.json"),
                   ("corpus_biased", DATA / "corpus_biased.json")]:
    toks = [jieba.lcut(s) for s in json.loads(path.read_text(encoding="utf-8"))]
    print(f"\n[{name}] {corpus_stats(toks)}")

# 条件偏斜展示：全局 vs 按主语分组的"喜欢"后继（2-gram 关联）
print("\n条件偏斜检查（'喜欢'后继：全局 vs 按主语分组）:")
toks = [jieba.lcut(s) for s in out]
succ = {}
for t in toks:
    for a, b in zip(t, t[1:]):
        succ.setdefault(a, Counter())[b] += 1
print(f"  [全局→喜欢→] {succ.get('喜欢', Counter()).most_common(5)}")
subj_succ = {}
for t in toks:
    for i in range(1, len(t) - 1):
        if t[i] == "喜欢" and t[i - 1] in SUBJECTS:
            subj_succ.setdefault(t[i - 1], Counter())[t[i + 1]] += 1
for s in ["我", "他", "她"]:
    if s in subj_succ:
        print(f"  [{s}→喜欢→] {subj_succ[s].most_common(5)}")
