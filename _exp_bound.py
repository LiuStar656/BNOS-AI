# -*- coding: utf-8 -*-
"""软边界参数实验: 200 节点 L=5 下选择收敛且不成矩形的参数"""
import math
import random
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "gui"))

from widgets.knowledge_graph import ForceEngine, AREA_WIDTH, AREA_HEIGHT


def run(param_br, param_pull, n=200, frames=1500, seed=123):
    random.seed(seed)
    sim = [[0.3] * n for _ in range(n)]
    for i in range(n):
        sim[i][i] = 1.0
    eng = ForceEngine()
    # 动态替换常量级参数 (直接注入到实例)
    eng._states = []
    eng._n = n
    eng._sim_matrix = sim
    eng._cx = AREA_WIDTH / 2
    eng._cy = AREA_HEIGHT / 2
    # 复刻 setup (手动)
    import widgets.knowledge_graph as kg
    kg.BOUNDARY_RADIUS = param_br
    kg.BOUNDARY_PULL = param_pull
    from widgets.knowledge_graph import NodeState
    for i in range(n):
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(1.0, 2.0)
        eng._states.append(NodeState(
            x=eng._cx, y=eng._cy,
            vx=speed * math.cos(angle), vy=speed * math.sin(angle)))
    eng.set_force_scale(5.0)
    for _ in range(frames):
        eng.step(dt=1.0)
    xs = [s.x for s in eng._states]
    ys = [s.y for s in eng._states]
    max_d = max(math.hypot(s.x - eng._cx, s.y - eng._cy) for s in eng._states)
    edge_zone = 40
    stuck = [s for s in eng._states if (s.x < edge_zone or s.x > AREA_WIDTH - edge_zone
                                        or s.y < edge_zone or s.y > AREA_HEIGHT - edge_zone)]
    return max_d, max(xs), len(stuck)


for br, pull in [(750, 0.01), (750, 0.05), (600, 0.05), (600, 0.03), (500, 0.05), (550, 0.04)]:
    max_d, max_x, stuck = run(br, pull)
    print(f"R={br:4d} pull={pull:.2f} -> max_r={max_d:6.0f} max_x={max_x:6.0f} stuck={stuck}")
