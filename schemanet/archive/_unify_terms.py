# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""术语统一脚本：图论词 → 脑神经科学/神经网络词（用户 2026-08-10 决策）。

主词：突触 + 连接混合——
  - 图论"边"系列（出边/入边/边数/条边/强边/弱边/边权重/边总数/平均出边密度）
    → 突触系列（传出突触/传入突触/突触数/条突触/强突触/弱突触/突触强度/突触总数/平均突触密度）
  - "连接"保留（连接级归因处罚等通用语境）
  - "节点"不盲替（可能含架构节点/节点边界等系统术语，dry-run 后人工判断）
  - "边"单字不替（旁边/边界/一边等非图论义）
  - 报告文件名不动（引用链稳定），正文全量替换

用法：
  python _unify_terms.py          # dry-run：统计 + 上下文样本
  python _unify_terms.py --apply  # 执行替换写回
"""

import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"

# 替换表（长词优先，防子串误伤；按顺序应用）
REPL = [
    ("平均出边密度", "平均突触密度"),
    ("出边", "传出突触"),
    ("入边", "传入突触"),
    ("边权重", "突触强度"),
    ("边总数", "突触总数"),
    ("边数", "突触数"),
    ("条边", "条突触"),
    ("强边", "强突触"),
    ("弱边", "弱突触"),
]

# 需人工审查的词（dry-run 列出上下文，不自动替换）
REVIEW = ["节点", "连接数"]


def main():
    apply_mode = "--apply" in sys.argv
    files = sorted(DOCS.rglob("*.md"))
    total = 0
    for fp in files:
        text = fp.read_text(encoding="utf-8")
        hits = 0
        ctx = []
        for old, new in REPL:
            n = text.count(old)
            if not n:
                continue
            hits += n
            # 收集前 3 处上下文
            start = 0
            shown = 0
            while shown < 3:
                i = text.find(old, start)
                if i < 0:
                    break
                ctx.append(f"    …{text[max(0, i-18):i+len(old)+18]!r}…")
                start = i + len(old)
                shown += 1
        total += hits
        if hits:
            print(f"{fp.relative_to(DOCS.parent)}: {hits} 处")
            for c in ctx:
                print(c)
    print(f"\n总计命中 {total} 处（docs/ 下 {len(files)} 个 md）")
    if not apply_mode:
        print("\n[dry-run] 未写入。--apply 执行替换（节点/连接数 见下方审查清单）")
        return

    # ── 执行替换 ──
    n_files, n_repl = 0, 0
    for fp in files:
        text = fp.read_text(encoding="utf-8")
        orig = text
        for old, new in REPL:
            text = text.replace(old, new)
        if text != orig:
            fp.write_text(text, encoding="utf-8")
            n_files += 1
            n_repl += sum(orig.count(o) for o, _ in REPL)
    print(f"[apply] 已替换 {n_repl} 处 / {n_files} 个文件")

    # ── 审查清单输出 ──
    print("\n[审查] '节点'/'连接数' 上下文（需人工判断是否替换）：")
    for fp in files:
        text = fp.read_text(encoding="utf-8")
        for w in REVIEW:
            start = 0
            shown = 0
            while shown < 2:
                i = text.find(w, start)
                if i < 0:
                    break
                print(f"  {fp.name} | {w}: …{text[max(0,i-15):i+len(w)+15]!r}…")
                start = i + len(w)
                shown += 1


if __name__ == "__main__":
    main()
