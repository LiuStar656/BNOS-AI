# -*- coding: utf-8 -*-
"""重建词表（2026-08-11 用户指令）：找快照 → 清空词表 → 重新注入
常用词常用字 → 取消神经元上限（满了自动增加）。

指令解读：
  ① 找一个快照: v53.0（runs/v52_2_20260811_183718——零边起点涌现基座）
  ② 清空词表:   pats 全清（37145 旧词 + 音素 + 残留——全部推倒）
  ③ 重新注入:   常用字 3500（stage0_hanzi）+ 常用词 10000
                （stage1_common_words——纯汉字过滤）+ 音素 48
                （拼音教学台基础——一并注入）
  ④ 取消神经元上限: allocate_pats 游标越界自动 expand（"知识的增量=
                神经元的增量"）——池满自动扩——本轮 5.4 万模式 << 池
                15 万——机制确认（注入超池词表触发 expand 验证）

用法：python _exp_rebuild_vocab.py
"""

import json
import re
import time
from pathlib import Path

from snapshot import load_snapshot, save_snapshot
from sparse_net import allocate_pats
from _exp_pinyin import PHONEMES, K_PHON

BASE = Path(__file__).resolve().parent / "runs" / "v52_2_20260811_183718"  # v53.0
CUR = Path(__file__).resolve().parent / "data" / "curriculum"
K_WORD = 4                     # 词/字模式神经元数（与音素一致）

CN_RE = re.compile(r"^[\u4e00-\u9fff]+$")


def main():
    t0 = time.time()
    # ── ① 基座快照（零边起点）──
    ng, vocab, pats, cursor = load_snapshot(BASE)
    n_edge = sum(len(r) for i in range(ng.n) for r in [ng.W_out[i][0]] if r)
    print(f"[①] 基座 {BASE.name}: n={ng.n}  边={n_edge}  词表 {len(pats)} 词"
          f"  cursor={cursor}")
    assert n_edge == 0, "基座不是零边起点——检查失败"

    # ── ② 清空词表（推倒全部映射——神经元池保留可复用）──
    pats = {}
    cursor = 0
    print(f"[②] 词表清空：pats → {{}}（{len(pats)} 词）游标归零——"
          f"神经元池 {ng.n} 全部可复用")

    # ── ③ 重新注入：音素 48 + 常用字 3500 + 常用词 10000 ──
    hanzi = json.loads((CUR / "stage0_hanzi.json").read_text(encoding="utf-8"))
    words = json.loads((CUR / "stage1_common_words.json").read_text(encoding="utf-8"))
    words = [w for w in words if CN_RE.match(w)]        # 纯汉字过滤
    words = list(dict.fromkeys(words))                  # 去重
    hanzi = [h for h in hanzi if CN_RE.match(h)]
    hanzi = list(dict.fromkeys(hanzi))
    print(f"[③] 数据源：常用字 {len(hanzi)}（stage0_hanzi）"
          f" + 常用词 {len(words)}（stage1_common_words 纯汉字）"
          f" + 音素 {len(PHONEMES)}")

    pool = PHONEMES + hanzi + words
    new_pats, cursor = allocate_pats(ng, pool, K_WORD, cursor)
    pats.update(new_pats)
    print(f"    注入 {len(pool)} 条目 × {K_WORD} 神经元：cursor → {cursor}")

    # ── ④ 取消神经元上限验证：注入超池词表 → 自动 expand ──
    print(f"[④] 当前池 {ng.n}（需求 {cursor + 4}）——游标越界自动 expand"
          f"（allocate_pats: if cursor+k > n → expand——\"知识的增量="
          f"神经元的增量\"——无上限）")
    # 显式触发扩容验证：用超池游标调 allocate_pats → 必须自动 expand
    cursor_overflow = ng.n + 1000          # 假装已分配超池（越界游标）
    o_pats, cursor2 = allocate_pats(ng, ["#exp_overflow"], K_WORD,
                                    cursor_overflow)
    assert ng.n > 150396, "expand 未触发——自动扩容失效"
    print(f"    扩容验证：越界游标 {cursor_overflow} → allocate_pats 自动"
          f" expand n {ng.n} → {ng.n}（{ng.n - 150396} 新神经元 ✓）")
    # 清理测试条目（不污染词表——游标保持 54192 继续分配）
    pats.pop("#exp_overflow", None)

    # 校验：模式无冲突 + 零边
    all_n = set()
    for w, ns in pats.items():
        for x in ns:
            assert int(x) not in all_n, f"冲突 {w}"
            all_n.add(int(x))
    assert len(all_n) == len(pats) * K_WORD, "模式冲突"
    n_edge = sum(len(r) for i in range(ng.n) for r in [ng.W_out[i][0]] if r)
    print(f"    校验：{len(pats)} 条目 × {K_WORD} = {len(all_n)} 神经元无冲突"
          f"  边 = {n_edge}（零边起点保持）")

    # ── 存档 ──
    metrics = {
        "rebuild_vocab": {
            "base": "53.0",
            "phonemes": len(PHONEMES),
            "hanzi": len(hanzi), "words": len(words),
            "k_word": K_WORD, "n_items": len(pats),
            "n_neurons": ng.n, "edges": n_edge,
            "unlimited": "allocate_pats 游标越界自动 expand——无上限",
        },
    }
    out = save_snapshot(
        ng, parent="53.0", vocab=None, pats=pats, cursor=cursor,
        metrics=metrics, tag=f"重建词表：常用字 {len(hanzi)} + 常用词"
                             f" {len(words)} + 音素 {len(PHONEMES)}"
                             f"（零边起点·神经元无上限）",
        data_fp=str(BASE))
    print(f"[F] 快照: {out}")
    print(f"耗时 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
