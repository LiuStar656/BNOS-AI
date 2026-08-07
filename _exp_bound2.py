# -*- coding: utf-8 -*-
"""软边界参数实验2: 真实分布 sim (混合相似度) 200节点 L=5"""
import math
import random
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "gui"))

import widgets.knowledge_graph as kg
from widgets.knowledge_graph import ForceEngine, NodeState, AREA_WIDTH, AREA_HEIGHT


def make_real_sim(n, seed=7):
    """模拟真实知识图谱: 相似度混合分布, 少量强相关, 部分互斥"""
    random.seed(seed)
    sim = [[0.0] * n for _ in range(n)]
    for i in range(n):
        sim[i][i] = 1.0
    for i in range(n):
        for j in range(i + 1, n):
            r = random.random()
            if r < 0.15:
                s = random.uniform(0.75, 0.95)   # 强相关(吸引)
            elif r < 0.45:
                s = random.uniform(0.45, 0.75)   # 弱相关(防碰撞)
            else:
                s = random.uniform(0.1, 0.45)    # 无关(斥力)
            sim[i][j] = sim[j][i] = s
    return sim


def run(br, pull, sim, frames=1500, seed=123):
    random.seed(seed)
    n = len(sim)
    kg.BOUNDARY_RADIUS = br
    kg.BOUNDARY_PULL = pull
    eng = ForceEngine()
    eng.setup(n, sim)
    eng.set_force_scale(5.0)
    for _ in range(frames):
        eng.step(dt=1.0)
    xs = [s.x for s in eng._states]
    ys = [s.y for s in eng._states]
    max_r = max(math.hypot(s.x - eng._cx, s.y - eng._cy) for s in eng._states)
    edge_zone = 40
    stuck = [s for s in eng._states if (s.x < edge_zone or s.x > AREA_WIDTH - edge_zone
                                        or s.y < edge_zone or s.y > AREA_HEIGHT - edge_zone)]
    return max_r, len(stuck)


sim200 = make_real_sim(200)
sim100 = make_real_sim(100)
sim50 = make_real_sim(50)

print("=== 真实混合 sim, L=5 ===")
for br, pull in [(750, 0.01), (750, 0.05), (600, 0.1), (500, 0.1), (500, 0.15)]:
    for n, sim in [(200, sim200), (100, sim100), (50, sim50)]:
        mr, st = run(br, pull, sim)
        print(f"R={br:4d} pull={pull:.2f} n={n:3d} -> max_r={mr:6.0f} stuck={st}")
    print()

# 对照组: L=1 默认布局是否基本不变 (R=750 pull=0.01 时软边界不应触发)
print("=== L=1 默认布局 (R=750 pull=0.01) ===")
random.seed(123)
eng = ForceEngine()
eng.setup(200, sim200)
eng.set_force_scale(1.0)
for _ in range(800):
    eng.step(dt=1.0)
max_r1 = max(math.hypot(s.x - eng._cx, s.y - eng._cy) for s in eng._states)
print(f"L=1 n=200 -> max_r={max_r1:.0f}")
