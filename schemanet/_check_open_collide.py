# -*- coding: utf-8 -*-
"""c2a：开源语料编码碰撞预检（corpus_open.json 词表模式全等对统计）。

n=8192/k=16 下两词模式交集期望 k²/n=0.031；碰撞 = 模式完全相同的词对
（不同词映射同模式 → 学习/读出不可分）。预检词表 3000 全词对。
判定：碰撞对 <1%（方案 v1.1 Phase 2 验收项）。
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from schema_net import _word_pattern

N, K = 8192, 16
DATA = Path(__file__).parent / "data"
UNK = "<UNK>"


def main():
    corpus = json.loads((DATA / "corpus_open.json").read_text(encoding="utf-8"))
    freq = Counter(w for toks in corpus for w in toks)
    vocab = [UNK] + [w for w, _ in freq.most_common(3100) if w != UNK][:2999]  # 与 gen 脚本一致（含 UNK）

    t0 = time.time()
    groups = {}
    for w in vocab:
        pat = tuple(_word_pattern(N, K, w))
        groups.setdefault(pat, []).append(w)
    collide = {p: ws for p, ws in groups.items() if len(ws) > 1}
    n_pairs = len(vocab) * (len(vocab) - 1) // 2
    n_collide = sum(len(ws) * (len(ws) - 1) // 2 for ws in collide.values())
    print(f"词表 {len(vocab)}，全对 {n_pairs}")
    print(f"碰撞组 {len(collide)}，涉及词 {len(set(w for ws in collide.values() for w in ws))}")
    for pat, ws in list(collide.items())[:10]:
        print(f"  碰撞: {ws} → {pat[:8]}...")
    print(f"碰撞对 {n_collide}/{n_pairs} = {n_collide / n_pairs:.6f}  "
          f"({'PASS ✓ (<1%)' if n_collide / n_pairs < 0.01 else 'FAIL ✗'})")
    print(f"耗时 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
