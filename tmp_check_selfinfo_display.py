"""临时脚本：查看 self_info / fixed_cognition 在 _read_db 中的实际 content"""
import sys, os
os.chdir(r"E:\杂项\BNOS_AI_project")
sys.path.insert(0, r"E:\杂项\BNOS_AI_project")

from gui.widgets.knowledge_panel import _read_db

rows = _read_db()
for t in ("self_info", "fixed_cognition"):
    print(f"=== {t} ===")
    for r in rows:
        if r["table"] == t:
            print(f"  id={r['id']} | content={r['content']!r} | extra={r['extra']!r} | time={r['created_at']!r}")
    print()
