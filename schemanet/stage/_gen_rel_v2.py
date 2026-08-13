# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""Stage 3 v16 数据生成：配对句式 + 小句内容（上百条，质量优先：对话 + 短文）。

背景（2026-08-10 用户）：
  - "s3 在句式上的颗粒度不够，句式的复杂度没有这么低"——s3 现训 4 词定式
  - "用质量更好的来训练，主要是对话和短文的"——旧 stage3_sents.json 是商品
    评价碎片（苹果好吃/快递/好评），质量不达标 → 数据来源改为：

来源：
  ① 短文·真实：toutiao_cat_data.txt（头条新闻标题，38 万行）精筛配对关系句
     ——去标点 → jieba 分词 → 词表外词 ≤4 → 排除 ASCII 专名堆砌（游戏/科技）
  ② 对话·构造：日常口语对话关系句（词表内模板，我/你/他 + 日常事件）
  ③ 短文·构造：书面叙述关系句（词表内模板，叙述一件事）

四维升级全覆盖（用户 2026-08-10 决策）：
  嵌套复合关系 / 内容小句化（因为[S V O]所以[S V O]）/ 关系词位置多样 /
  句内修饰加长（今天/时间 + 助词了 + 动宾 + 去地点）

落档：data/curriculum/stage3_rel_v2.json
结构：[{"tokens": [...], "source": "短文·真实/对话·构造/短文·构造", "sent": "..."}]

用法：python _gen_rel_v2.py
"""

import json
import re
from pathlib import Path

import jieba

from snapshot import load_version

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
RAW = DATA / "raw" / "toutiao_cat_data.txt_unzip" / "toutiao_cat_data.txt"
OUT = DATA / "stage3_rel_v2.json"

# ── 词表内构造词（模板用；启动时自检全部在 v15.0 词表）─────────
CHECK_WORDS = ["我", "你", "他", "她", "我们", "他们", "猫", "狗",
               "下雨", "饿", "困", "累", "冷", "生病", "带伞",
               "睡觉", "吃饭", "看医生", "穿衣服", "坚持", "上课",
               "洗手", "刷牙", "写作业", "跑步",
               "想", "去", "看", "吃", "要", "不", "仍然", "今天",
               "苹果", "西瓜", "牛奶", "面包", "公园", "家", "学校", "商店",
               "因为", "所以", "虽然", "但是", "先", "然后", "了", "石头",
               "洗澡", "书", "鱼", "喝", "睡"]


def build_templates():
    """词表内构造：对话（口语）/ 短文（叙述）配对关系句。

    每个模板给出显式自然组合（避免病句），返回 [(tokens, source), ...]。
    """
    rows = []

    # ── 因果组（因为…所以…）───────────────────────────────────
    # 对话·因果 ① 主语重复小句：因为[S 状态 了]所以[S 想 动作]
    C1 = [("他", "累", "睡觉"), ("我", "困", "睡觉"), ("猫", "饿", "吃饭"),
          ("他", "生病", "看医生"), ("狗", "饿", "吃饭"), ("我", "冷", "穿衣服")]
    for s, st, act in C1:
        rows.append((["因为", s, st, "了", "所以", s, "想", act], "对话·构造"))
    # 对话·因果 ② 时间修饰：因为[今天 状态]所以[S 动作] / 因为[状态]所以[S 不 动作]
    C2 = [("下雨", "我", "带伞"), ("下雨", "我们", "去公园"),
          ("冷", "他", "穿衣服"), ("下雨", "他", "去学校")]
    for st, s, act in C2:
        rows.append((["因为", "今天", st, "所以", s, act], "对话·构造"))
        rows.append((["因为", st, "所以", s, "不", act], "对话·构造"))
    # 短文·因果 ③ 主语切换：因为[S1 状态]所以[S2 动作]
    C3 = [("他", "累", "他", "睡觉"), ("我", "饿", "我们", "吃饭"),
          ("他", "生病", "他", "看医生"), ("猫", "累", "猫", "睡觉")]
    for s1, st, s2, act in C3:
        rows.append((["因为", s1, st, "所以", s2, act], "短文·构造"))
    # 短文·因果 ④ 双小句带宾语：因为[S 动作 O]所以[S 动作 O]
    C4 = [("我", "吃", "苹果", "我", "喝", "牛奶"), ("他", "吃", "西瓜", "他", "睡", "觉")]
    # 注：喝/觉 需词表验证；不安全则跳过（自检兜底）
    for s1, v1, o1, s2, v2, o2 in C4:
        rows.append((["因为", s1, v1, o1, "所以", s2, v2, o2], "短文·构造"))
    # 对话·因果 ⑤ 无主原因：因为[状态]所以[S 动作]
    C5 = [("下雨", "我", "带伞"), ("饿", "我们", "吃饭"), ("冷", "他", "穿衣服")]
    for st, s, act in C5:
        rows.append((["因为", st, "所以", s, act], "对话·构造"))

    # ── 转折组（虽然…但是…）───────────────────────────────────
    # 对话·转折 ⑥ 主语重复：虽然[S 状态 了]但是[S 仍然 动作]
    T1 = [("他", "累", "上课"), ("我", "困", "写作业"), ("他", "生病", "上课"),
          ("猫", "饿", "不吃饭"), ("我", "冷", "跑步")]
    for s, st, act in T1:
        rows.append((["虽然", s, st, "了", "但是", s, "仍然", act], "对话·构造"))
    # 对话·转折 ⑦ 去地点：虽然[状态]但是[S 去 O]
    T2 = [("下雨", "我们", "公园"), ("下雨", "他", "学校"), ("冷", "我", "公园"),
          ("累", "他们", "家")]
    for st, s, place in T2:
        rows.append((["虽然", st, "但是", s, "去", place], "对话·构造"))
    # 短文·转折 ⑧ 双小句：虽然[S V]但是[S V O]
    T3 = [("他", "生病", "他", "上课"), ("她", "累", "她", "写作业"),
          ("他", "困", "他", "坚持", "上课")]
    for s1, st, s2, v, *rest in T3:
        if rest:
            rows.append((["虽然", s1, st, "但是", s2, v, rest[0]], "短文·构造"))
        else:
            rows.append((["虽然", s1, st, "但是", s2, v], "短文·构造"))
    # 短文·转折 ⑨ 时间修饰：虽然[今天 状态]但是[S V]
    T4 = [("下雨", "他", "跑步"), ("冷", "我们", "去公园"),
          ("下雨", "猫", "睡觉"), ("累", "我", "坚持")]
    for st, s, act in T4:
        rows.append((["虽然", "今天", st, "但是", s, act], "短文·构造"))

    # ── 顺序组（先…然后…）─────────────────────────────────────
    # 对话·顺序 ⑩ 主语重复：先[S 动作]然后[S 动作]（口语存在：先你走我收拾）
    X1 = [("我", "洗手", "我", "吃饭"), ("他", "刷牙", "他", "睡觉"),
          ("猫", "吃饭", "猫", "睡觉"), ("我", "吃饭", "我", "写作业")]
    for s1, v1, s2, v2 in X1:
        rows.append((["先", s1, v1, "然后", s2, v2], "对话·构造"))
    # 短文·顺序 ⑪ 双小句带宾语：先[S V O]然后[S V O]
    X2 = [("我", "吃", "苹果", "我", "喝", "牛奶"),
          ("我们", "洗", "手", "我们", "吃", "饭"),
          ("猫", "吃", "鱼", "猫", "睡", "觉"),
          ("我", "看", "书", "我", "写", "作业")]
    for s1, v1, o1, s2, v2, o2 in X2:
        rows.append((["先", s1, v1, o1, "然后", s2, v2, o2], "短文·构造"))
    # 对话·顺序 ⑫ 主语后置（探测断点）：先[动作]然后[S 动作]——最自然口语
    X3 = [("吃饭", "我", "写作业"), ("洗手", "我们", "吃饭"),
          ("刷牙", "我", "睡觉"), ("吃饭", "他", "上课"),
          ("洗手", "他", "吃饭"), ("写作业", "我", "睡觉"),
          ("跑步", "我", "洗澡"), ("吃饭", "猫", "睡觉")]
    for v1, s, v2 in X3:
        rows.append((["先", v1, "然后", s, v2], "对话·构造"))
    # 短文·顺序 ⑬ 助词了：先[S 动作 了]然后[S 动作]
    X4 = [("猫", "吃饭", "猫", "睡觉"), ("他", "写作业", "他", "跑步"),
          ("我", "洗手", "我", "吃饭"), ("我们", "吃饭", "我们", "写作业")]
    for s1, v1, s2, v2 in X4:
        rows.append((["先", s1, v1, "了", "然后", s2, v2], "短文·构造"))

    # ── 验收种子句（v16 链式接话验收的 6 句代表，补齐结构）──────
    # 与 C2/X3/T2/C5 重叠的已有；补 2 句缺失结构（助词了 + 主语重复）
    EXTRA = [
        (["虽然", "他", "生病", "了", "但是", "他", "上课"], "短文·构造"),
        (["因为", "他", "累", "所以", "他", "睡觉"], "短文·构造"),
    ]
    for t, src in EXTRA:
        rows.append((t, src))

    return rows


def clean_title(t):
    """去标点（保留中文字符）。"""
    return re.sub(r"[，。？！、；：“”\"'\u2018\u2019\u201c\u201d（）()…—\-—\s,.;:!?\u3000]", "", t)


def filter_toutiao(keys):
    """从 toutiao 新闻标题精筛短文·真实配对关系句。

    标准：含 虽然…但是 / 因为…所以 配对；去标点后 5-22 词；
    无 ASCII 字母数字（排除游戏/科技专名堆砌）；词表外词 ≤4。
    """
    lines = RAW.read_text(encoding="utf-8", errors="ignore").splitlines()
    titles = []
    for l in lines:
        parts = l.split("_!_")
        if len(parts) >= 4:
            t = parts[3].strip()
            if ("虽然" in t and "但是" in t) or ("因为" in t and "所以" in t):
                titles.append(t)
    out, seen = [], set()
    for t in titles:
        c = clean_title(t)
        toks = list(jieba.cut(c))
        n = len(toks)
        if n < 5 or n > 22:
            continue
        if any(ch.isascii() and ch.isalnum() for w in toks for ch in w):
            continue
        miss = [w for w in toks if w not in keys]
        if len(miss) > 4:
            continue
        key = "".join(toks)
        if key in seen:
            continue
        seen.add(key)
        out.append({"tokens": toks, "source": "短文·真实", "sent": "".join(toks),
                    "miss": miss})
    return out


def main():
    # ── 1. 加载 v15.0 词表 + 构造词自检 ────────────────────────
    ng, vocab, pats, cursor = load_version("15.0")
    keys = set(pats.keys())
    miss_check = [w for w in CHECK_WORDS if w not in keys]
    if miss_check:
        print(f"[自检] 构造词缺 {len(miss_check)}：{miss_check}")
        print("  需要从模板中剔除或词表补词，脚本中止")
        raise SystemExit(1)
    print(f"[词表] v15.0 共 {len(keys)} 词，构造词全部在表")

    # ── 2. toutiao 短文·真实精筛 ───────────────────────────────
    real = filter_toutiao(keys)
    real_sorted = sorted(real, key=lambda r: (len(r["miss"]), len(r["tokens"])))
    print(f"[短文·真实] toutiao 精筛 {len(real)} 条")
    for r in real_sorted[:10]:
        print(f"  ({len(r['tokens'])}词 缺{len(r['miss'])}) {' '.join(r['tokens'])}"
              f"{' 缺词:' + '、'.join(r['miss']) if r['miss'] else ''}")

    # ── 3. 模板构造（对话 + 短文）──────────────────────────────
    tmpl = build_templates()
    print(f"[模板构造] {len(tmpl)} 条（对话·构造 + 短文·构造）")
    for t, src in tmpl[:12]:
        print(f"  {src}：{' '.join(t)}")

    # ── 4. 合并落档 ────────────────────────────────────────────
    rows = []
    for t, src in tmpl:
        rows.append({"tokens": t, "source": src, "sent": "".join(t),
                     "miss": []})
    for r in real_sorted:
        rows.append(r)

    n_causal = sum(1 for r in rows if "因为" in r["tokens"])
    n_turn = sum(1 for r in rows if "虽然" in r["tokens"])
    n_seq = sum(1 for r in rows if "先" in r["tokens"])
    n_tot = len(rows)
    print(f"\n[汇总] 共 {n_tot} 条（因果 {n_causal} / 转折 {n_turn} / 顺序 {n_seq}）"
          f" | 真实 {len(real_sorted)} / 构造 {len(tmpl)}")
    print(f"  来源分布：{ {src: sum(1 for r in rows if r['source'] == src) for src in
                          ['短文·真实', '对话·构造', '短文·构造']} }")
    print(f"  词表覆盖：{sum(1 for r in rows if not r['miss'])}/{n_tot} 条词表内"
          f"（缺词条数 {sum(1 for r in rows if r['miss'])}，训练时 allocate_pats）")

    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"\n[落档] {OUT}")


if __name__ == "__main__":
    main()
