"""临时脚本：找出 _read_db 输出中 content 为冒号/以冒号结尾/等号占位的记录"""
import sys, os
os.chdir(r"E:\杂项\BNOS_AI_project")
sys.path.insert(0, r"E:\杂项\BNOS_AI_project")

from gui.widgets.knowledge_panel import _read_db

rows = _read_db()
print("=== content 为空/仅冒号/仅等号/冒号结尾 ===")
bad_kinds = {"空": 0, "仅冒号": 0, "仅等号": 0, "冒号结尾": 0, "等号空": 0}
examples = {}
for r in rows:
    c = (r["content"] or "").strip()
    if not c:
        bad_kinds["空"] += 1
        examples.setdefault("空", []).append(r)
    elif c == ":" or c == "：":
        bad_kinds["仅冒号"] += 1
        examples.setdefault("仅冒号", []).append(r)
    elif c == "=" or c == "＝":
        bad_kinds["仅等号"] += 1
        examples.setdefault("仅等号", []).append(r)
    elif c.endswith((":", "：")):
        bad_kinds["冒号结尾"] += 1
        examples.setdefault("冒号结尾", []).append(r)
    elif " = " in c and (c.endswith(" = ") or " =  " in c or "= None" in c):
        bad_kinds["等号空"] += 1
        examples.setdefault("等号空", []).append(r)

for k, v in bad_kinds.items():
    print(f"  {k}: {v} 条")
    for r in examples.get(k, [])[:6]:
        print(f"    [{r['table']}] id={r['id']} content={r['content'][:70]!r}")
    print()
