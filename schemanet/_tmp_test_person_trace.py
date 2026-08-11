# -*- coding: utf-8 -*-
"""人称视角测试（内心活动版）：展示网络听到老师的话后内部每一步
——组词、候选收集、试读（思考环 trace）、选择。
用法：python _tmp_test_person_trace.py
"""
import sys
import io
import contextlib

sys.path.insert(0, "stage")
import _scene_mom_llm as S
from snapshot import load_version, load_consolidated
from _exam_free import free_read

buf = io.StringIO()


def make_net():
    with contextlib.redirect_stdout(buf):
        net = S.SceneMomLLM(resume=False)
        ng, vocab, pats, cursor = load_version("40.1")
        net.ng, net.vocab, net.pats, net.cursor = ng, vocab, pats, cursor
        net.n2w = {j: w for w, ns in pats.items() for j in ns}
        net.cons, net.val = load_consolidated("40.1")
        net.has_llm = False
        net._build_reader()

    # 内心活动版 _read：free_read 带 trace——展示思考环
    def _read_trace(self_, seed_w, ctx=None):
        trace = []
        read = free_read(self_.ng, self_.pats, self_.n2w, [seed_w],
                         self_.domain, teach_out=self_.teach_out,
                         consolidated=self_.cons, ctx=ctx,
                         validation=self_.val, trace=trace)
        print(f"      ┌ 试读「{seed_w}」（ctx={ctx or '无'}）——内心活动：")
        for t in trace:
            cands = "、".join(t.get("cands", []))
            print(f"      │   {t['state']}: 候选[{cands}] → 选「{t['chosen']}」")
        toks = []
        for w in [x.split("(")[0] for x in read]:
            if w.startswith("[") or w in toks:
                break
            toks.append(w)
        print(f"      └ 读出: {('/'.join(toks) if toks else '（读不出）')}")
        return toks

    net._read = _read_trace.__get__(net, type(net))
    return net


def run(txt):
    net = make_net()
    print(f"\n═══ 老师说：「{txt}」═══")
    # ① 听觉注入：逐字进入（展示组词）
    net.mom_say(txt)
    pend = "".join(net.pending)
    print(f"  [听觉注入] 组词缓冲 pending = {pend!r}"
          f"{'（含词表外字→junk）' if net.junk else ''}")
    # ② process 内部逐 tick
    for step in range(4):
        r = net.process()
        if r:
            print(f"  [tick] → ({r[0]}) 「{r[1]}」")
        else:
            print(f"  [tick] → 继续思考（无输出）")


print("═══ 人称视角——内心活动观察（v40.1 守一）═══")
run("守一饿了吗")
run("我饿了")
run("守一")
