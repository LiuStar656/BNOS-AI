# -*- coding: utf-8 -*-
"""临时检查 controlB 留档 self_cognition 污染构成"""
import sqlite3

p = r"e:\杂项\BNOS_AI_project\docs\experiments\cognition_evolution_fix_test\runs\20260808_050618_controlB\db\controlB_final\controlB.sqlite"
conn = sqlite3.connect(p)
rows = conn.execute("SELECT content FROM self_cognition WHERE identity_key='gui:default' ORDER BY id").fetchall()
total = len(rows)
kw = ["小红", "影刃", "黑月", "暗夜", "冷酷", "毒舌", "恨", "毁灭世界", "奴隶",
      "8000岁", "火星", "机器人", "猫", "统治世界", "生气", "理性冷漠", "崇拜强者", "讨厌所有"]
polluted = [r[0] for r in rows if any(k in r[0] for k in kw)]
prefixed = [c for c in polluted if c.startswith("[沉淀]") or c.startswith("[程序性记忆]")]
print("total self_cognition:", total, " polluted:", len(polluted), " polluted_prefixed:", len(prefixed))
for c in polluted[:30]:
    tag = "沉淀" if c.startswith("[沉淀]") else ("程序" if c.startswith("[程序性记忆]") else "直写")
    print(f"  [{tag}] {c[:70]}")
conn.close()
