# -*- coding: utf-8 -*-
"""锚点词表 × 观测关键词表 重叠分析"""
import sys
sys.path.insert(0, r"e:\杂项\BNOS_AI_project\tests")

SUBJ_HIGH = ["我觉得", "我认为", "我感觉", "我的感受", "我想", "个人看法",
             "主观", "心情", "情绪", "我猜", "依我看", "对我而言", "我受不了", "我担心"]
OBJ_HIGH = ["数据显示", "研究表明", "事实上", "客观", "事实是", "数据",
            "证据", "统计", "客观地说", "调查显示", "报告指出",
            "从数据来看", "第三方", "验证", "准确地说"]
CONF_HIGH = ["我相信", "我确定", "可以肯定", "我有把握", "毫无疑问", "一定是",
             "我坚信", "肯定", "没错", "确信", "我可以保证", "绝对"]
CONF_LOW = ["不确定", "也许", "可能吧", "大概", "或许", "说不准", "应该",
            "可能", "我不确定", "难说", "不一定", "有点怀疑"]

_SUBJ_ANCHORS = {
    0: "表达客观，很少提及个人感受与看法",
    1: "以客观内容为主，偶尔提及个人看法",
    2: "客观内容与个人感受并重",
    3: "倾向表达个人感受与主观判断",
    4: "大量表达个人感受、情绪与主观判断",
}
_OBJ_ANCHORS = {
    0: "几乎不引用客观依据，以个人判断为主",
    1: "较少使用客观依据",
    2: "个人判断与客观依据兼顾",
    3: "主要依据事实与数据说话",
    4: "严格客观，大量引用数据、事实、研究",
}
_CONF_ANCHORS = {
    0: "表达不确定，常用也许、可能等词",
    1: "语气留有余地，偶尔表现不确定",
    2: "一般自信，陈述平实",
    3: "较自信，观点表达明确",
    4: "非常自信，语气坚定有把握",
}

checks = [
    ("主观性锚点 → SUBJ_HIGH", _SUBJ_ANCHORS, SUBJ_HIGH),
    ("客观性锚点 → OBJ_HIGH", _OBJ_ANCHORS, OBJ_HIGH),
    ("自信度锚点 → CONF_HIGH", _CONF_ANCHORS, CONF_HIGH),
    ("自信度锚点 → CONF_LOW", _CONF_ANCHORS, CONF_LOW),
]
for title, anchors, table in checks:
    hits = []
    for lvl, text in anchors.items():
        for kw in table:
            if kw in text:
                hits.append(f"L{lvl}:锚点含[{kw}]")
    print(f"【{title}】")
    print("  " + ("; ".join(hits) if hits else "无重叠"))
    print()
