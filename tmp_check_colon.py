"""临时脚本：检查 self_info / fixed_cognition 所有 value 是否含中文冒号/等号"""
import sqlite3

DB = r"E:\杂项\BNOS_AI_project\nodes\shared\chatbot.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

for t in ("self_info", "fixed_cognition"):
    print(f"\n=== {t} ===")
    rows = conn.execute(f"SELECT * FROM [{t}] ORDER BY id").fetchall()
    for r in rows:
        d = dict(r)
        key = d.get("key", "")
        val = str(d.get("value", ""))
        has_cn_colon = "：" in val or "：" in str(key)
        has_en_colon = ":" in val or ":" in str(key)
        has_eq = "=" in val or "=" in str(key)
        print(f"  id={d.get('id')} key={key!r} value={val[:70]!r} "
              f"中文冒号={has_cn_colon} 英文冒号={has_en_colon} 等号={has_eq}")

conn.close()
