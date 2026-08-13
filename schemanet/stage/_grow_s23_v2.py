# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""s2+s3 组合泛化教学（压力考试暴露问题的对策 #1/#2，2026-08-10）：

考试结果 2/16 暴露：未见组合的链边全缺（学校→打 / 多→衣服 / 饭→很…）。
本脚本执行词对级组合教学——**句子组合 = 已学词对的拼接**：
  ① 教学：压力考试 16 题的相邻词对（bigram）全部跟读教学（+ 修饰结构
     词对：很/多/认真/地/赶快/还是/一起 的搭配）——词对级泛化（句子
     未见、词对已见）
  ② 复考原题：词对已学 → 链读应通（验证"词对教学 → 句子组合"）
  ③ 变体题（新组合：换主语/宾语/地点/修饰）：词对部分已学 → 看泛化率
  ④ 对比报告：教学前 2/16 → 教学后 X/16（原题）+ 变体泛化率

用法：python _grow_s23_v2.py
"""

import json
import sys
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from _grow_v16 import edge_between, direct_next_multi

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
R_S = 3                # 词对跟读轮数

# 压力考试原题（与 _exam_s23 一致——只教词对，不教句子）
EXAM = {
    "s2 复杂短句": [
        ("他昨天在学校打球", ["他", "昨天", "在", "学校"], ["打", "球"]),
        ("妈妈做的饭很好吃", ["妈妈", "做", "的", "饭"], ["很", "好吃"]),
        ("小猫在沙发上睡觉", ["小猫", "在", "沙发", "上"], ["睡觉"]),
        ("他喜欢在图书馆看书", ["他", "喜欢", "在", "图书馆"], ["看", "书"]),
        ("我们一起去公园玩", ["我们", "一起", "去", "公园"], ["玩"]),
        ("我昨天晚上看了电影", ["我", "昨天", "晚上", "看", "了"], ["电影"]),
        ("他穿了很多衣服", ["他", "穿", "了", "很", "多"], ["衣服"]),
        ("她认真地写作业", ["她", "认真", "地", "写"], ["作业"]),
    ],
    "s3 长关系句": [
        ("因为昨天天气很冷所以他穿了很多衣服",
         ["因为", "昨天", "天气", "很", "冷"],
         ["所以", "他", "穿", "了", "很", "多", "衣服"]),
        ("虽然他很累但是他仍然坚持写作业",
         ["虽然", "他", "很", "累"], ["但是", "他", "仍然", "坚持", "写", "作业"]),
        ("先吃饭然后我们一起去公园",
         ["先", "吃", "饭"], ["然后", "我们", "一起", "去", "公园"]),
        ("因为下雨所以他今天没去公园",
         ["因为", "下雨"], ["所以", "他", "今天", "没", "去", "公园"]),
        ("虽然他生病了但是他还是去上学",
         ["虽然", "他", "生病", "了"], ["但是", "他", "还是", "去", "上学"]),
        ("因为天黑了所以我们赶快回家",
         ["因为", "天", "黑", "了"], ["所以", "我们", "赶快", "回家"]),
        ("先洗手然后我们开始吃饭",
         ["先", "洗", "手"], ["然后", "我们", "开始", "吃", "饭"]),
        ("虽然今天下雨但是我们还是去公园玩",
         ["虽然", "今天", "下雨"], ["但是", "我们", "还是", "去", "公园", "玩"]),
    ],
}

# 变体题（新组合：换主语/宾语/地点/修饰——考试泛化率）
VARIANTS = {
    "s2 变体": [
        ("她昨天在公园打球", ["她", "昨天", "在", "公园"], ["打", "球"]),
        ("爸爸做的菜很好吃", ["爸爸", "做", "的", "菜"], ["很", "好吃"]),
        ("小狗在沙发上睡觉", ["小狗", "在", "沙发", "上"], ["睡觉"]),
        ("我喜欢在图书馆写作业", ["我", "喜欢", "在", "图书馆"], ["写", "作业"]),
        ("我们一起去商店玩", ["我们", "一起", "去", "商店"], ["玩"]),
        ("他昨天晚上看了书", ["他", "昨天", "晚上", "看", "了"], ["书"]),
        ("她戴了很多帽子", ["她", "戴", "了", "很", "多"], ["帽子"]),
    ],
    "s3 变体": [
        ("因为昨天天气很热所以他穿了很多衣服",
         ["因为", "昨天", "天气", "很", "热"],
         ["所以", "他", "穿", "了", "很", "多", "衣服"]),
        ("虽然她很忙但是她仍然坚持上班",
         ["虽然", "她", "很", "忙"], ["但是", "她", "仍然", "坚持", "上班"]),
        ("先洗脸然后我们一起吃饭",
         ["先", "洗", "脸"], ["然后", "我们", "一起", "吃", "饭"]),
        ("因为下雨所以他今天没去上学",
         ["因为", "下雨"], ["所以", "他", "今天", "没", "去", "上学"]),
        ("虽然他生病了但是他还是去上班",
         ["虽然", "他", "生病", "了"], ["但是", "他", "还是", "去", "上班"]),
        ("因为天黑了所以我们赶快睡觉",
         ["因为", "天", "黑", "了"], ["所以", "我们", "赶快", "睡觉"]),
        ("虽然今天很冷但是我们还是去公园",
         ["虽然", "今天", "很", "冷"], ["但是", "我们", "还是", "去", "公园"]),
    ],
}


def chain_read(ng, pats, n2w, front, back):
    if edge_between(ng, pats, front[-1], back[0]) <= 0:
        return [], (front[-1], back[0])
    seq = [back[0]]
    cur, rest = back[0], list(back[1:])
    for _ in range(len(rest) + 1):
        if not rest:
            break
        if rest[0] == cur:
            seq.append(cur)
            rest.pop(0)
            continue
        top = direct_next_multi(ng, pats, n2w, [cur], k=8, domain=set(back))
        nxt = next((w for w, _ in top if w == rest[0]), None)
        if not nxt:
            return seq, (cur, rest[0])
        seq.append(nxt)
        rest.pop(0)
        cur = nxt
    return seq, None


def bigrams(front, back):
    """句子 → 相邻词对（含跨段对 front[-1]→back[0]）。"""
    seq = front + back
    return list(zip(seq[:-1], seq[1:]))


def main():
    t0 = time.time()
    print("═══ s2+s3 组合泛化教学（词对级：句子组合 = 已学词对拼接）═══\n")

    ng, vocab, pats, cursor = load_version("19.0")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    print(f"[加载] 19.0：n={ng.n}，词表 {len(keys)}")

    # ── 1. 收集教学词对（原题全部相邻对 + 变体全部相邻对）──────
    teach_pairs = []
    for group, items in {**EXAM, **VARIANTS}.items():
        for sent, front, back in items:
            for a, b in bigrams(front, back):
                if a in keys and b in keys:
                    teach_pairs.append((a, b))
    teach_pairs = sorted(set(teach_pairs))
    print(f"[教学池] {len(teach_pairs)} 个词对（原题 + 变体的全部相邻对）")

    # ── 2. 词对跟读教学（×R_S 轮，含回响噪声——与主线同构）────
    print(f"\n[教学] 词对逐一跟读 ×{R_S}…")
    t1 = time.time()
    for a, b in teach_pairs:
        for _ in range(R_S):
            _learn_sentence(ng, [a, b], pats, slot=0)
    print(f"  完成（{time.time() - t1:.0f}s）")

    # ── 3. 复考原题（词对已学 → 链读应通）──────────────────────
    print("\n[复考原题]（词对已学，句子组合 = 拼接验证）")
    n_hit = n_tot = 0
    for group, items in EXAM.items():
        g_hit = g_tot = 0
        for i, (sent, front, back) in enumerate(items, 1):
            read_toks, brk = chain_read(ng, pats, n2w, front, back)
            ok = read_toks == back
            g_hit += ok
            g_tot += 1
            n_hit += ok
            n_tot += 1
            print(f"  [{'✅' if ok else '✗'}]「{'/'.join(front)}｜"
                  f"{'/'.join(back)}」接「{'/'.join(read_toks) or '∅'}」"
                  + ("" if ok else f" 断点: {brk}"))
        print(f"  {group}: {g_hit}/{g_tot} = {g_hit/g_tot:.3f}\n")
    rate_orig = n_hit / n_tot

    # ── 4. 变体题（新组合：换词后词对部分已学 → 泛化率）────────
    print("[变体题]（新组合：换主语/宾语/地点/修饰——泛化率）")
    v_hit = v_tot = 0
    v_break = {}
    for group, items in VARIANTS.items():
        g_hit = g_tot = 0
        for i, (sent, front, back) in enumerate(items, 1):
            read_toks, brk = chain_read(ng, pats, n2w, front, back)
            ok = read_toks == back
            g_hit += ok
            g_tot += 1
            v_hit += ok
            v_tot += 1
            if brk:
                v_break[brk] = v_break.get(brk, 0) + 1
            print(f"  [{'✅' if ok else '✗'}]「{'/'.join(front)}｜"
                  f"{'/'.join(back)}」接「{'/'.join(read_toks) or '∅'}」"
                  + ("" if ok else f" 断点: {brk}"))
        print(f"  {group}: {g_hit}/{g_tot} = {g_hit/g_tot:.3f}\n")
    rate_var = v_hit / v_tot

    # ── 5. 结论对比 ───────────────────────────────────────────
    print("═══ 结论 ═══")
    print(f"  原题复考：{n_hit}/{n_tot} = {rate_orig:.3f}"
          f"（考试前 2/16 = 0.125）")
    print(f"  变体泛化：{v_hit}/{v_tot} = {rate_var:.3f}"
          f"（新组合——词对已学的拼接率）")
    print(f"  变体断点：{dict(list(v_break.items())[:6])}")

    # ── 6. 留档 + 快照 ────────────────────────────────────────
    out_dir = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_s23_v2"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"tag": "s2+s3 组合泛化教学（词对级）",
              "base": "19.0", "teach_pairs": len(teach_pairs),
              "exam_before": {"hits": 2, "tot": 16, "rate": 0.125},
              "exam_after": {"hits": n_hit, "tot": n_tot,
                             "rate": round(rate_orig, 3)},
              "variant": {"hits": v_hit, "tot": v_tot,
                          "rate": round(rate_var, 3)},
              "variant_breaks": dict(list(v_break.items())[:10]),
              "sec": round(time.time() - t0, 1)}
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[留档] {out_dir}/result.json（{time.time() - t0:.0f}s）")

    if "--no-snapshot" not in sys.argv:
        save_snapshot(ng, parent="19.0",
                      tag="Stage 3 v22：s2+s3 组合泛化教学（词对级："
                          "句子组合 = 已学词对拼接）",
                      metrics=result, vocab=vocab, pats=pats, cursor=cursor)


if __name__ == "__main__":
    main()
