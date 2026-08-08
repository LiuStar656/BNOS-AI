# -*- coding: utf-8 -*-
"""生成扩充语料 corpus_large.json（Phase 2 规模实验用，2000+ 句）。

构成：现有 corpus.json 100 句（真实句式）+ 规则合成 2000+ 句（多层模板×变量库）。
机械合成保证转移分布密集（bigram 统计可靠），用于验证规模扩展 + 稀疏存储；
真实句保留句式多样性。可复现：固定 seed。
"""
import json
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent
rng = np.random.default_rng(2026)

# ── 基础真实句（现有 100 句）──
base = json.loads((DATA / "corpus.json").read_text(encoding="utf-8"))

# ── 变量库 ──
LIKE = ["看书", "听音乐", "散步", "吃苹果", "吃香蕉", "喝茶", "旅行", "画画",
        "跑步", "编程", "下棋", "看电影", "游泳", "写字", "吃饺子", "打篮球",
        "踢足球", "养花", "摄影", "做饭", "爬山", "钓鱼", "唱歌", "跳舞",
        "骑自行车", "弹吉他", "读书", "写作", "学英语", "学编程", "洗碗",
        "打扫卫生", "购物", "打游戏", "看剧", "健身", "瑜伽", "冥想", "吃火锅",
        "看新闻", "做实验", "听播客", "逛公园", "洗衣服"]
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
VERBS = ["喜欢", "想", "觉得", "知道", "记得", "希望", "打算", "习惯"]
ADJS = ["真好看", "真好吃", "真有意思", "真好玩", "真好听", "真漂亮",
        "真可爱", "真感人", "真好笑", "真不错", "真糟糕", "真麻烦", "真精彩", "真热闹"]
OBJS = ["这部电影", "这道菜", "这本书", "这个游戏", "这首歌", "这个地方",
        "这只猫", "这个故事", "这个笑话", "这个天气", "这条街", "这双鞋",
        "这个方案", "这个任务", "这个假期", "这部动画", "这个软件", "这次旅行"]
PLACES = ["公司", "学校", "公园", "家里", "图书馆", "健身房", "餐厅", "电影院",
          "超市", "医院", "车站", "海边", "山上", "咖啡馆", "办公室", "实验室", "球场"]
TIMES = ["早上", "中午", "下午", "晚上", "周末", "工作日", "放假的时候", "下雨的时候", "有空的时候", "放假时"]
REASONS = ["太累了", "没有时间", "天气不好", "心情不好", "工作太忙", "太贵了",
           "距离太远", "已经试过了", "朋友推荐", "以前就想去", "感觉不错", "需要休息",
           "想放松一下", "明天再说", "下次一定"]
PEOPLE = ["他", "她", "爸爸", "妈妈", "朋友", "同事", "妹妹", "哥哥", "邻居", "同学"]

GREET = ["你好", "你好吗", "早上好", "晚上好", "最近怎么样", "好久不见",
         "很高兴见到你", "再见", "保重", "晚安", "欢迎光临", "祝你顺利"]
QUESTION = ["你吃饭了吗", "你今天忙不忙", "你喜欢什么运动", "你周末有什么安排",
            "最近在忙什么", "你觉得这个方案怎么样", "你想去哪里玩", "你今天心情怎么样",
            "你周末去不去公园", "你明天有空吗", "你要不要一起吃饭", "你觉得怎么样"]

# ── 模板：每模板独立占位槽，组合数 >> 目标句数 ──
def gen_many(rng):
    out = []
    # 模板组合（数量级估算）
    templates = [
        (lambda: "我" + "喜欢" + rng.choice(LIKE), 45),
        (lambda: "我" + "喜欢" + rng.choice(LIKE) + "和" + rng.choice(LIKE), 45 * 45),
        (lambda: "我" + "喜欢" + rng.choice(LIKE) + "也" + "喜欢" + rng.choice(LIKE), 45 * 45),
        (lambda: "我" + rng.choice(WANT) + "和" + rng.choice(WANT), 40 * 40),
        (lambda: "我" + "想" + rng.choice(WANT), 40),
        (lambda: "我今天" + rng.choice(MOODS), 20),
        (lambda: rng.choice(DAYS) + "我" + rng.choice(ACT), 3 * 20),
        (lambda: rng.choice(DAYS) + rng.choice(TIMES) + "我" + rng.choice(ACT), 3 * 10 * 20),
        (lambda: "你" + rng.choice(VERBS) + rng.choice(LIKE), 8 * 45),
        (lambda: rng.choice(OBJS) + rng.choice(ADJS), 18 * 14),
        (lambda: "我们" + rng.choice(["一起", "经常", "偶尔", "很少", "总是"]) + rng.choice(ACT), 5 * 20),
        (lambda: rng.choice(PEOPLE) + rng.choice(VERBS) + rng.choice(LIKE), 10 * 8 * 45),
        (lambda: "我觉得" + rng.choice(OBJS) + rng.choice(ADJS), 18 * 14),
        (lambda: "我" + "想" + rng.choice(WANT) + "但是" + rng.choice(REASONS), 40 * 15),
        (lambda: "我" + "喜欢" + rng.choice(LIKE) + "因为" + rng.choice(REASONS), 45 * 15),
        (lambda: "我在" + rng.choice(PLACES) + rng.choice(ACT), 17 * 20),
        (lambda: rng.choice(DAYS) + "我" + rng.choice(ACT) + "在" + rng.choice(PLACES), 3 * 20 * 17),
        (lambda: "我" + rng.choice(MOODS) + "因为" + rng.choice(REASONS), 20 * 15),
        (lambda: rng.choice(PEOPLE) + "也" + "喜欢" + rng.choice(LIKE), 10 * 45),
        (lambda: rng.choice(QUESTION), 12),
        (lambda: rng.choice(GREET), 12),
        (lambda: "今天" + rng.choice(TIMES) + "我" + "去" + rng.choice(PLACES), 10 * 17),
    ]
    for fn, _ in templates:
        # 每模板按比例抽样，保证总量 ~2500
        pass
    # 轮转抽样：保证覆盖所有模板
    n_target = 2500
    probs = [1.0] * len(templates)
    for _ in range(n_target):
        t = rng.choice(len(templates))
        out.append(templates[t][0]())
    return out


syn = gen_many(rng)
seen = set(base)
out = list(base)
for s in syn:
    if s not in seen:
        seen.add(s)
        out.append(s)

(DATA / "corpus_large.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"生成 {len(out)} 句（基础 {len(base)} + 合成 {len(out) - len(base)}）→ data/corpus_large.json")
