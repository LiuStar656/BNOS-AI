# -*- coding: utf-8 -*-
"""[EXP] 拼音字母级颗粒度：「叫爸爸/叫妈妈」= jiaobaba/jiaomama 连续字母流

用户决策（2026-08-11）：把复合韵母原子（j-iao）拆成字母流（j-i-a-o）——
26 个字母原子——零语言学先验（声母/韵母表也是注入）——更细的颗粒度：

    叫   = j i a o      爸爸 = b a b a      妈妈 = m a m a      哥哥 = g e g e
    共享: jiao 与其他音节共享 j、i；爸爸/妈妈共享 a、共享 CV-CV 重复
    结构: 音节（CV 组块）不再显式——网络要自己从字母流发现（振荡器涌现）

复用协议与函数（_exp_pinyin.py）：
  说（字母流 + 韵律：动词轻声 1.0、论元重读 20.0）→ 零食（DA 门控）→ 验证
  零边起点 v53.0——所有边 STDP 自然长出

验证点（对齐复合韵母级——颗粒度对比）：
  B: 教学 jiaobaba ×30 → "叫"组装边（j→i→a→o）/ 叫→爸爸（o→b）/ 爸爸（b→a,a→b）
  C: jiao 联想 / ba 自持振荡 / jiaobaba 轨道
  D: 教学 jiaomama ×30 → o→b vs o→m（马太？）a→b vs a→m（共享中和？）
     D1 wta=20（用户质疑点：jiaomama 是否还带出 b？）
     D1b wta=4（注意收窄——当前论元胜出？）
  E: jiaogege（g e 未组合——诚实记录）

用法：python _exp_pinyin_letters.py
"""

import time
from pathlib import Path

import numpy as np

from snapshot import load_snapshot, save_snapshot
from sparse_net import allocate_pats
from _exp_pinyin import (teach_once, recall, edge_weight, count_edges,
                         show_timeline, AMP_VERB, AMP_ARG, REWARD, K_PHON)

BASE = Path(__file__).resolve().parent / "runs" / "v52_2_20260811_183718"  # v53.0
N_TEACH = 30

LETTERS = list("abcdefghijklmnopqrstuvwxyz")      # 26 字母原子
assert len(LETTERS) == 26

WORD_L = {
    "叫":   ["j", "i", "a", "o"],
    "爸爸": ["b", "a", "b", "a"],
    "妈妈": ["m", "a", "m", "a"],
    "哥哥": ["g", "e", "g", "e"],
}
JIAO_L = WORD_L["叫"]
VERB_LEN = len(JIAO_L)                            # 4——动词字母数（覆写默认 2）


def ph_seq(*words):
    seq, amps = [], []
    for w in words:
        seq += WORD_L[w]
        amps += [AMP_ARG] * len(WORD_L[w])
    for i in range(VERB_LEN):
        amps[i] = AMP_VERB
    return seq, amps


def main():
    t0 = time.time()
    # ── A. 字母表就位（26 × 4 = 104 神经元——空池分配 + 零边起点自检）──
    ng, vocab, pats, cursor = load_snapshot(BASE)
    print(f"[A] 基座 {BASE.name}: n={ng.n}  边={count_edges(ng)}  "
          f"cursor={cursor}  w_max={ng.w_max}  wta_k={ng.wta_k}  theta={ng.theta}")
    assert count_edges(ng) == 0, "基座不是零边起点——检查失败"
    missing = [c for c in LETTERS if c not in pats]
    if missing:
        new_pats, cursor = allocate_pats(ng, missing, K_PHON, cursor)
        pats.update(new_pats)
        lo, hi = min(min(v) for v in new_pats.values()), \
            max(max(v) for v in new_pats.values())
        print(f"    分配 {len(missing)} 字母 × {K_PHON} 神经元 = [{lo}, {hi}]")
    all_l = set()
    for c in LETTERS:
        all_l.update(int(x) for x in pats[c])
    assert len(all_l) == 26 * K_PHON, "字母模式冲突"
    print(f"    字母 26 × {K_PHON} = {len(all_l)} 神经元就位（无冲突）")

    print(f"[B] 教学 jiaobaba ×{N_TEACH}（j i a o b a b a——奖励 {REWARD}"
          f" + 论元重读 {AMP_ARG} > 联想边 {ng.w_max}）")
    seq_b = ph_seq("叫", "爸爸")[0]
    curve = []
    for i in range(1, N_TEACH + 1):
        teach_once(ng, pats, seq_b, verb_len=VERB_LEN)
        if i in (1, 5, 10, 20, 30):
            row = {f"{p[0]}->{p[1]}": edge_weight(ng, pats, *p)[0] for p in
                   [("j", "i"), ("i", "a"), ("a", "o"), ("o", "b"),
                    ("b", "a"), ("a", "b")]}
            curve.append((i, row))
            print(f"    第 {i:2d} 次: j→i {row['j->i']:5.2f} | i→a {row['i->a']:5.2f}"
                  f" | a→o {row['a->o']:5.2f} | o→b {row['o->b']:5.2f}"
                  f" | b→a {row['b->a']:5.2f} | a→b {row['a->b']:5.2f}"
                  f"   总边 {count_edges(ng)}")
    for pre, post in [("j", "i"), ("i", "a"), ("a", "o"), ("o", "b"),
                      ("b", "a"), ("a", "b"), ("o", "a"), ("a", "o")]:
        m, mx, nn = edge_weight(ng, pats, pre, post)
        print(f"    {pre}→{post} = 均值 {m:.3f} 最大 {mx:.3f} 边数 {nn}")

    print("[C] 验证（冻结检索 learn_gate=False）")
    show_timeline(recall(ng, pats, ["j", "i", "a", "o"], [AMP_VERB] * 4),
                  "C1 输入 jiao（叫）→ 联想带出")
    show_timeline(recall(ng, pats, ["b", "a"], [AMP_ARG] * 2),
                  "C2 输入 ba → 音节自持振荡？")
    show_timeline(recall(ng, pats, *ph_seq("叫", "爸爸")),
                  "C3 输入 jiaobaba → 轨道完成？")

    print(f"[D] 教学 jiaomama ×{N_TEACH}（j i a o m a m a——共享 a——"
          f"颗粒度对比点）")
    seq_m = ph_seq("叫", "妈妈")[0]
    for i in range(1, N_TEACH + 1):
        teach_once(ng, pats, seq_m, verb_len=VERB_LEN)
    for pre, post in [("o", "m"), ("m", "a"), ("a", "m"), ("o", "b"),
                      ("a", "b"), ("o", "a")]:
        m, mx, nn = edge_weight(ng, pats, pre, post)
        print(f"    {pre}→{post} = 均值 {m:.3f} 最大 {mx:.3f} 边数 {nn}")
    show_timeline(recall(ng, pats, *ph_seq("叫", "妈妈")),
                  "D1 输入 jiaomama wta=20 → （用户质疑点：还带 b 吗？）")
    show_timeline(recall(ng, pats, *ph_seq("叫", "妈妈"), wta_k=4),
                  "D1b 输入 jiaomama wta=4 → 当前论元胜出？")
    show_timeline(recall(ng, pats, ["j", "i", "a", "o"], [AMP_VERB] * 4),
                  "D2 输入 jiao → 联想（双轨？马太？）")

    print("[E] 泛化：jiaogege（g e g e——未教组合——诚实记录）")
    show_timeline(recall(ng, pats, *ph_seq("叫", "哥哥"), wta_k=4),
                  "E1 输入 jiaogege wta=4 → ？（预期复读——规则层级未现）")

    metrics = {
        "pinyin_letters": {
            "base": "53.0", "letters": 26, "k_phon": K_PHON,
            "teach": N_TEACH, "amp": {"verb": AMP_VERB, "arg": AMP_ARG},
            "reward": REWARD, "verb_len": VERB_LEN,
            "curve": curve,
            "edges": {f"{p}->{q}": edge_weight(ng, pats, p, q) for p, q in
                      [("o", "b"), ("o", "m"), ("b", "a"), ("a", "b"),
                       ("m", "a"), ("a", "m"), ("j", "i"), ("i", "a"),
                       ("a", "o")]},
            "total_edges": count_edges(ng),
        },
    }
    out = save_snapshot(
        ng, parent="53.0", vocab=vocab, pats=pats, cursor=cursor, metrics=metrics,
        tag=f"拼音字母级：jiaobaba/jiaomama（26 字母×4，论元重读 {AMP_ARG}，"
            f"{N_TEACH}+{N_TEACH} 次）+ jiaogege 记录", data_fp=str(BASE))
    print(f"[F] 快照: {out}")
    print(f"耗时 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
