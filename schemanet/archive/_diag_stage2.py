# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""Stage 2 卡死定位诊断（临时，定位后删除）。"""
import os
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_k, "1")
import faulthandler
faulthandler.enable()
import json
import time

import numpy as np

from snapshot import load_version
from sparse_net import allocate_pats

t0 = time.time()
ng, vocab, pats, cursor = load_version("6.0")
print("1 loaded", ng.n, round(time.time() - t0, 1), flush=True)

sents = json.loads(open("data/curriculum/stage2_sents.json", encoding="utf-8").read())
need = sorted({w for s in sents[:3000] for w in s if w not in pats})
total_new = len(need) * 4
if cursor + total_new > ng.n:
    ng.expand(cursor + total_new)
pats_new, cursor = allocate_pats(ng, need, 4, cursor)
pats.update(pats_new)
print("2 alloc", ng.n, round(time.time() - t0, 1), flush=True)

neurons = [j for w in sents[0] for j in pats[w]]
ng.v[:] = 0.0
ng.spikes[:] = 0.0
ng.pre_trace[:] = 0.0
print("3 cleared", flush=True)
ng.wta_k = len(neurons)
print("4 step start, wta_k=", ng.wta_k, flush=True)
from schema_net import build_pulse
ng.step(build_pulse(ng.n, neurons), slot=0)
print("5 step done", round(time.time() - t0, 1), flush=True)
