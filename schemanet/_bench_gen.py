# -*- coding: utf-8 -*-
"""临时测速：加载 runs/20260809_103532/net.npz 后生成速度（分阶段计时）。"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from schema_net import _word_pattern
from sparse_net import load_net, _pats_matrix, outsum_sparse
from grad_readout import GradReadout
from generator import Generator

t0 = time.time()
ng, vocab = load_net("runs/20260809_103532/net.npz", seed=42)
print(f"① 加载模型: {time.time() - t0:.1f}s（含 1809 万连接重建）")

t0 = time.time()
pats = {w: _word_pattern(ng.n, ng.wta_k, w) for w in vocab}
pats_mat = _pats_matrix(pats, vocab)
outsum = outsum_sparse(ng, pats, vocab, slot=0)
print(f"② 模式/出边构建: {time.time() - t0:.1f}s")

t0 = time.time()
ro = GradReadout(ng, pats, vocab, pats_mat, maxlen=8)
print(f"③ GradReadout（含 S 矩阵）: {time.time() - t0:.1f}s")

gen = Generator(ro, outsum=outsum, seed=49)
prefixes = ["很", "酒店", "味道", "我", "质量", "送餐", "房间", "不错", "这个", "在"]

t0 = time.time()
for pre in prefixes:
    g = gen.generate([pre], max_len=10, top_k=12, temp=1.1, penalty=2.5, engine="grad")
    print(f"  [{pre}] -> {''.join(g)}")
dt = time.time() - t0
print(f"④ 生成 10 条（各 10 词）: 总 {dt:.2f}s, 平均 {dt / len(prefixes) * 1000:.1f}ms/条, "
      f"{dt / (len(prefixes) * 10) * 1000:.1f}ms/词")
