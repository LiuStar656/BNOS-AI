"""检查数据库各表最新数据"""
import sqlite3
import os

db_path = r"e:\杂项\BNOS_AI_project\nodes\shared\chatbot.db"
print(f"数据库: {db_path}")
print(f"文件大小: {os.path.getsize(db_path) / 1024:.1f} KB\n")

conn = sqlite3.connect(db_path)
tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('sqlite_sequence') ORDER BY name"
).fetchall()

for (tname,) in tables:
    # 排除长字段打印
    cols = [c[1] for c in conn.execute(f"PRAGMA table_info([{tname}])").fetchall()]
    count = conn.execute(f"SELECT COUNT(*) FROM [{tname}]").fetchone()[0]
    
    # 最新5条
    latest = conn.execute(
        f"SELECT * FROM [{tname}] ORDER BY id DESC LIMIT 1"
    ).fetchone()
    
    if latest:
        row = dict(zip(cols, latest))
        # 截断长内容
        for k, v in row.items():
            if isinstance(v, str) and len(v) > 120:
                row[k] = v[:120] + "..."
        print(f"\n【{tname}】共 {count} 条 | 最新:")
        for k, v in row.items():
            print(f"  {k}: {v}")
    else:
        print(f"\n【{tname}】空表")

conn.close()
