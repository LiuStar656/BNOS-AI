"""临时脚本：找出所有表里含中文冒号'：'的记录，定位用户看到的'：'来源"""
import sqlite3

DB = r"E:\杂项\BNOS_AI_project\nodes\shared\chatbot.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'").fetchall()]

for t in tables:
    cols = [c[1] for c in conn.execute(f"PRAGMA table_info([{t}])").fetchall()]
    if "content" not in cols and "value" not in cols and "summary" not in cols:
        continue
    col = "content" if "content" in cols else ("summary" if "summary" in cols else "value")
    rows = conn.execute(f"SELECT * FROM [{t}] WHERE [{col}] LIKE '%：%' LIMIT 5").fetchall()
    if rows:
        print(f"\n=== {t} (列: {col}) 含中文冒号 ===")
        for r in rows:
            d = dict(r)
            print(f"  id={d.get('id')} [{col}]={str(d.get(col))[:100]!r}")

conn.close()
