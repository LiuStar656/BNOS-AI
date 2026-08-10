# -*- coding: utf-8 -*-
"""s2+s3 最终压力测试（考试）：大幅提高难度与复杂度——长句/修饰/未见组合。

考试设计（2026-08-10 用户："最后进行 s2+s3 最终压力测试，大幅提高难度和
复杂度，从测试结果里暴露问题制定下一步计划"）：
  - s2 组（复杂短句 ×8）：长主谓宾 + 时间/地点/程度修饰 + 未见组合
    （不在 stage2_sents / 166 条教学数据里——全部词表内已查证）
  - s3 组（长关系句 ×8）：嵌套关系 + 定状补 + 多内容小句 + 未见组合
考法：分句接话（教师说前半 → 网络接后半）——**期望链约束读取**（链读：
引发边检查 + 顺序链读——教学成果 = 边的组合泛化）。
判分：每句链通 = 得分；失败点 = 链断位置（哪个词对缺失/哪个结构不会）。
对照：教学句（166 条/课程句）链读全通 vs 考试新句——压力 = 未见组合的
边泛化率。暴露问题 → 下一步计划。

用法：python _exam_s23.py
"""

import json
import time
from pathlib import Path

from snapshot import load_version
from _grow_v16 import edge_between, direct_next_multi

RUNS_DIR = Path(__file__).parent / "runs"

# ── 考试题（全部词表内已查证；前半/后半 = 分句接话）────────────
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


def chain_read(ng, pats, n2w, front, back):
    """期望链约束读取：引发边检查（front 尾→back[0]）+ 顺序链读。
    返回 (读出序列, 断点词对) —— 断点 = 第一个走不通的词对。
    """
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


def main():
    t0 = time.time()
    print("═══ s2+s3 最终压力测试（大幅提高难度：长句/修饰/未见组合）═══\n")

    import sys as _s
    ver = _s.argv[1] if len(_s.argv) > 1 else "19.0"
    ng, vocab, pats, cursor = load_version(ver)
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    print(f"[加载] {ver}：n={ng.n}，词表 {len(keys)}\n")

    results, all_rows = {}, []
    n_hit = n_tot = 0
    for group, items in EXAM.items():
        print(f"── {group}（{len(items)} 题）──")
        g_hit = g_tot = 0
        for i, (sent, front, back) in enumerate(items, 1):
            miss = [w for w in front + back if w not in keys]
            if miss:
                print(f"  [{i}] ⚠️ 题目含词表外词 {miss}——跳过（应换题）")
                continue
            read_toks, brk = chain_read(ng, pats, n2w, front, back)
            ok = read_toks == back
            g_hit += ok
            g_tot += 1
            n_hit += ok
            n_tot += 1
            mark = "✅" if ok else "✗"
            brk_txt = (f" 断点: {brk[0]}→{brk[1]} 缺边" if brk
                       else " 链读中断")
            print(f"  [{i}] {mark}「{'/'.join(front)}｜{'/'.join(back)}」"
                  f" 接「{'/'.join(read_toks) or '∅'}」"
                  + ("" if ok else brk_txt))
            all_rows.append({"group": group, "sent": sent, "ok": ok,
                             "read": "".join(read_toks),
                             "brk": brk})
        results[group] = {"hits": g_hit, "tot": g_tot,
                          "rate": round(g_hit / g_tot, 3) if g_tot else 0}
        print(f"  [{group}] {g_hit}/{g_tot} = "
              f"{g_hit / g_tot:.3f}\n")

    rate = n_hit / n_tot if n_tot else 0
    print(f"═══ 总分：{n_hit}/{n_tot} = {rate:.3f} ═══")

    # ── 失败点分析（暴露问题 → 下一步计划依据）───────────────
    print("\n[失败点分析]（链断位置 → 暴露的缺口）")
    from collections import Counter
    brks = Counter(r["brk"] for r in all_rows if not r["ok"] and r["brk"])
    for (a, b), n in brks.most_common(8):
        print(f"  {a}→{b} 缺边 ×{n}")
    # 断点词分类（哪种结构不会）
    cat = Counter()
    for r in all_rows:
        if not r["ok"]:
            if r["brk"] and r["brk"][0] in ("所以", "但是", "然后"):
                cat["关系词接续"] += 1
            elif r["brk"] and r["brk"][1] in ("很", "多", "了"):
                cat["修饰成分"] += 1
            else:
                cat["普通词对"] += 1
    for k, n in cat.most_common():
        print(f"  缺口类别：{k} ×{n}")

    # ── 留档 ─────────────────────────────────────────────────
    out_dir = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_exam_s23"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"tag": "s2+s3 最终压力测试（长句/修饰/未见组合）",
              "base": "19.0", "total": {"hits": n_hit, "tot": n_tot,
                                        "rate": round(rate, 3)},
              "groups": results, "fail_breaks": [list(k) + [v] for k, v in
                                                 brks.items()],
              "sec": round(time.time() - t0, 1)}
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[留档] {out_dir}/result.json（{time.time() - t0:.0f}s）")


if __name__ == "__main__":
    main()
