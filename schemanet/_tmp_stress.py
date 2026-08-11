# -*- coding: utf-8 -*-
"""能力压测：sleep（v39.0→v40.1，压缩=边数-18%）前后全能力对比。

测试面：① 词表/守一 ② 总边数 ③ 身份定式 ④ 固化句全表读出
⑤ 身份验证门（我叫守一） ⑥ 知识链 ⑦ 自由链。
用法：python _tmp_stress.py（纯内存）
"""
import json
from pathlib import Path

from snapshot import load_version, load_consolidated
from _exam_free import free_read, build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats
from _grow_v16 import edge_between
from schema_net import read_skeleton

DATA = Path(__file__).parent / "data" / "curriculum"
ROWS = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
SEM = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))


def stress(ver):
    ng, vocab, pats, cursor = load_version(ver)
    cons, val = load_consolidated(ver)
    n2w = {j: w for w, ns in pats.items() for j in ns}
    cats = build_cats(pats, SEM["words"], 12, 3)
    q_pool = qa_build_pool(ROWS, cats)
    domain = build_domain(ng, pats, ROWS, q_pool)
    teach_out = build_teach_out(ROWS, q_pool)
    r = {"ver": ver}

    # ① 词表 / 守一
    r["words"] = len(pats)
    r["shouyi_neurons"] = len(pats.get("守一", []))
    # ② 总边数
    r["edges"] = sum(len(ng.W_out[i][k])
                     for i in range(ng.n) for k in range(ng.slots))
    # ③ 身份定式读出
    sk = read_skeleton(ng, pats, n2w, "守一")
    r["skeleton"] = "/".join(sk) if sk else None
    # ④ 固化句全表读出（逐句对比）
    ok = total = 0
    fails = []
    for kw, cands in (cons or {}).items():
        for sent, slots, ctype in cands:
            total += 1
            out = free_read(ng, pats, n2w, [kw], domain, teach_out=teach_out,
                            consolidated=cons, validation=val, ctx=ctype)
            got = [x.split("(")[0] for x in out if not x.startswith("[")]
            if got == sent:
                ok += 1
            else:
                fails.append(f"{kw}/{ctype}:「{''.join(sent)}」→「{''.join(got)}」")
    r["consolidated"] = f"{ok}/{total}"
    r["cons_fails"] = fails[:6]
    # ⑤ 身份验证门：我叫守一（确认——应读出整句）
    out = free_read(ng, pats, n2w, ["名字"], domain, teach_out=teach_out,
                    consolidated=cons, validation=val, ctx="确认")
    r["name_recall"] = "".join(x.split("(")[0] for x in out
                               if not x.startswith("["))
    # ⑥ 知识链权重
    r["chains"] = {f"{a}→{b}": round(edge_between(ng, pats, a, b), 1)
                   for a, b in [("饿", "吃"), ("渴", "喝"), ("疼", "帮"),
                                ("困", "睡"), ("累", "休息"), ("冷", "穿")]}
    # ⑦ 自由链（无固化词入口）
    fw = free_read(ng, pats, n2w, ["猫"], domain, teach_out=teach_out,
                   consolidated=cons, validation=val)
    fw = [x.split("(")[0] for x in fw if not x.startswith("[")]
    r["free_chain"] = "/".join(fw) if fw else "（空）"
    return r


def main():
    a = stress("39.0")
    b = stress("40.1")
    print("═══ 能力压测：v39.0（sleep前）vs v40.1（sleep后）═══\n")
    print(f"{'测试项':<14}{'v39.0':<38}{'v40.1':<38}")
    print("─" * 90)
    rows = [
        ("词表词数", f"{a['words']:,}", f"{b['words']:,}"),
        ("守一神经元", a["shouyi_neurons"], b["shouyi_neurons"]),
        ("总边数", f"{a['edges']:,}", f"{b['edges']:,}"),
        ("身份定式", a["skeleton"] or "✗", b["skeleton"] or "✗"),
        ("固化句读出", a["consolidated"], b["consolidated"]),
        ("身份验证门", a["name_recall"] or "✗", b["name_recall"] or "✗"),
        ("自由链(猫)", a["free_chain"], b["free_chain"]),
    ]
    for name, x, y in rows:
        mark = "✓" if x == y else "⚠"
        print(f"{name:<14}{x!s:<38}{y!s:<38}{mark}")
    print("─" * 90)
    print("知识链（应不变——冻结区）：")
    for k in a["chains"]:
        x, y = a["chains"][k], b["chains"][k]
        mark = "✓" if x == y else "⚠"
        print(f"  {k:<10}{x:<10}{y:<10}{mark}")
    print("\n固化句失败明细（v40.1）：")
    if b["cons_fails"]:
        for f in b["cons_fails"]:
            print(f"  {f}")
    else:
        print("  无")


if __name__ == "__main__":
    main()
