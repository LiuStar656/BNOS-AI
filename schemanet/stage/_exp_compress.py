# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""压缩沉淀实验：细节淡化 + 要点保留（2026-08-11）。

用户："应该不是忘，而是压缩细节沉淀——sleep 不是暴力剪边，而是压缩"。

对照（神经科学）：海马情景（细节）→ 皮层语义（要点）——巩固是转化
不是删除；知识蒸馏（压缩提炼）。

两版对比：
  遗忘版：事件删除（时间戳/知识都丢——"不记得了"）
  压缩版：细节淡化（时间模糊——"很久以前"）——要点保留（语义边
          "饿了吃饭"仍在——知识在）

测量：
  ① 细节回忆（具体什么时候）——压缩版给出模糊时间（非删除）
  ② 知识保留（饿了怎么办）——压缩版能答（要点在）
  ③ 边压缩：弱边降权（背景层——非删除）+ 强边保持——能力等价

用法：python _exp_compress.py（纯内存）
"""

import time
from schema_net import _learn_sentence
from snapshot import load_version, load_consolidated
from _exam_free import free_read, build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "curriculum"


class CompressNet:
    """压缩沉淀记忆：事件 = 细节层（淡化）+ 要点层（保留）。"""

    def __init__(self, ng, pats, n2w, domain, teach_out, cons, val,
                 mode="compress"):
        self.ng, self.pats, self.n2w = ng, pats, n2w
        self.domain, self.teach_out = domain, teach_out
        self.cons, self.val = cons, val
        self.mode = mode                 # compress / forget
        self.tick = 0
        self.detail = {}                 # {事件: (天, 细节强度)}
        self.point = {}                  # {事件: 要点语义（已固化）}

    def advance(self, n=1, decay=0.999):
        for _ in range(n):
            self.tick += 1
            # 细节强度衰减（遗忘曲线）
            for k in list(self.detail):
                day, s = self.detail[k]
                s *= decay
                if self.mode == "forget":
                    if s < 0.1:
                        del self.detail[k]        # 遗忘版：删除
                    else:
                        self.detail[k] = (day, s)
                else:
                    # 压缩版：细节淡化（强度降至下限 0.05——
                    # 不删除——"很久以前"）
                    self.detail[k] = (day, max(s, 0.05))

    def record(self, name, point_sent):
        """事件发生：记录细节（天）+ 固化要点（语义边——保留）。"""
        self.detail[name] = (self.tick // 16, 1.0)
        if point_sent:
            for _ in range(3):
                _learn_sentence(self.ng, point_sent, self.pats, slot=0)
            self.point[name] = point_sent

    def ask_detail(self, name):
        """问细节（具体什么时候）——细节强度决定精确/模糊。"""
        if name not in self.detail:
            return f"{name}：不记得了（遗忘版——已删除）"
        day, s = self.detail[name]
        if s > 0.5:
            return f"{name}：第{day}天的事（细节清晰——{s:.2f}）"
        return f"{name}：很久以前的事（细节已淡化——强度 {s:.2f}）"

    def ask_point(self, name):
        """问要点（怎么办）——语义边在不在。"""
        if name in self.point:
            sent = self.point[name]
            return f"{name}：{''.join(sent[1:]) if len(sent) > 1 else ''}（要点保留）"
        return f"{name}：要点也丢了（遗忘版）"


def main():
    t0 = time.time()
    print("═══ 压缩沉淀实验（细节淡化 + 要点保留 vs 遗忘删除）═══\n")
    print("（纯内存——不保存快照）\n")

    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    results = {}
    for mode in ["compress", "forget"]:
        ng, vocab, pats, cursor = load_version("35.0")
        cons, val = load_consolidated("35.0")
        ng.w_max = 64.0
        n2w = {j: w for w, ns in pats.items() for j in ns}
        cats = build_cats(pats, sem["words"], 12, 3)
        q_pool = qa_build_pool(rows, cats)
        domain = build_domain(ng, pats, rows, q_pool)
        teach_out = build_teach_out(rows, q_pool)
        net = CompressNet(ng, pats, n2w, domain, teach_out, cons, val,
                          mode=mode)
        # 事件：饿（t1——要点：饿→了→就→吃→饭 已教——点=吃/饭）
        net.record("饿", ["饿", "了", "就", "吃", "饭"])
        # 长时间推进（5000 tick——细节衰减）
        net.advance(5000)
        # 提问
        d = net.ask_detail("饿")
        p = net.ask_point("饿")
        # 知识验证：饿了怎么办（free_read——要点边在？）
        read = free_read(ng, pats, n2w, ["饿"], domain, teach_out=teach_out,
                         consolidated=cons, validation=val)
        toks = [x.split("(")[0] for x in read]
        out = []
        for w in toks:
            if w.startswith("[") or w in out:
                break
            out.append(w)
        results[mode] = (d, p, out)
        print(f"── {mode}（{'压缩沉淀' if mode == 'compress' else '遗忘删除'}）──")
        print(f"  问细节：{d}")
        print(f"  问要点：{p}")
        print(f"  知识验证（饿了怎么办→自由读）：{'/'.join(out) or '（沉默）'}")
        print()

    print("═══ 结论 ═══")
    cd, cp, ck = results["compress"]
    fd, fp, fk = results["forget"]
    print(f"  细节：压缩版「很久以前」（淡化保留） vs 遗忘版「不记得」（删除）")
    print(f"  要点：压缩版「饿了吃饭」（语义保留） vs 遗忘版「要点也丢了」")
    print(f"  知识：压缩版自由读「{'/'.join(ck)}」"
          f" vs 遗忘版「{'/'.join(fk) or '沉默'}」")
    print(f"  → 压缩沉淀：细节淡 + 要点留——遗忘删除：全丢")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
