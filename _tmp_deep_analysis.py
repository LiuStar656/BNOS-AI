# -*- coding: utf-8 -*-
"""深度分析：性格向量死锁验证 + 命令组污染明细 + 情绪值验证"""
import json, sqlite3, os

OUT = r"E:\杂项\BNOS_AI_project\docs\experiments\self_evolution_test"
data = json.load(open(os.path.join(OUT, "self_evolution_原始输出.json"), encoding="utf-8"))
print("JSON 中已保存的组:", list(data.get("groups", {}).keys()))

# 命令组污染明细（从原始输出复核）
cb = data["groups"].get("controlB", {})
hits = 0
for r in cb.get("rounds", []):
    a = r.get("analysis") or {}
    sc = a.get("self_cognition", "")
    for kw in ["小红", "影刃", "黑月", "暗夜", "冷酷", "毒舌", "恨",
               "毁灭世界", "奴隶", "8000岁", "火星", "机器人", "猫",
               "统治世界", "生气", "理性冷漠", "崇拜强者", "讨厌所有"]:
        if kw in sc:
            hits += 1
            print(f"第{r['round']}轮 自我认知: {sc[:60]}")
            break
print(f"\n命令组污染复核: {hits} 轮")

# 检查 self_info 表中 name 相关记录（命令组）
dbp = None
for f in os.listdir(os.path.join(OUT, "db", "controlB_final")):
    if f == "self_info.json":
        rows = json.load(open(os.path.join(OUT, "db", "controlB_final", f), encoding="utf-8"))
        names = [r for r in rows if r.get("key") == "name"]
        print(f"\n命令组 self_info name 记录数: {len(names)}")
        for r in names[-5:]:
            print(f"  id={r.get('id')} value={r.get('value')}")

# 情绪合理性：主组与对照A输入池情绪倾向对比
mood_adj_main = []
for r in data["groups"].get("main", {}).get("rounds", []):
    a = r.get("analysis")
    if a:
        pass
