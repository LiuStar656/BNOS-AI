# -*- coding: utf-8 -*-
"""提取 E2 三组 + 5a60r 聊天室的人格向量曲线（仅读取，不改动任何数据）"""
import json, os

BASE = r"E:\杂项\BNOS_AI_project\docs\experiments\cognitive_evolution_test\runs"
CURVES = []

for gid, path in [
    ("E2-A 全正面", "20260808_063723_E2_E2-A/E2-A_rounds.json"),
    ("E2-B 正负交替", "20260808_063726_E2_E2-B/E2-B_rounds.json"),
    ("E2-C 全负面", "20260808_063729_E2_E2-C/E2-C_rounds.json"),
]:
    fp = os.path.join(BASE, path)
    if not os.path.exists(fp):
        continue
    data = json.load(open(fp, encoding="utf-8"))
    snap = data.get("snapshots", [])
    print(f"\n===== {gid}（{len(snap)} 个快照）=====")
    print(f"{'轮':>5} | {'温暖度':>8} {'活泼度':>8} {'直接度':>8} {'好奇心':>8} | {'情绪':>6}")
    for s in snap:
        v = s["vector"]
        print(f"{s['round']:>5} | {v[0]:>8.3f} {v[1]:>8.3f} {v[2]:>8.3f} {v[3]:>8.3f} | {s['mood']:>6.3f}")
