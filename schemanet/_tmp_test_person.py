# -*- coding: utf-8 -*-
"""人称视角测试：给守一说「守一饿了么」（在叫她）vs「我饿了」（陈述
说话者状态）——守一能不能分出来"是不是在和她说"。

用 v40.1 网络构造场景（不发 LLM），跑两组听觉输入对比反应。
用法：python _tmp_test_person.py
"""
import sys
import io
import contextlib

sys.path.insert(0, "stage")
import _scene_mom_llm as S
from snapshot import load_version, load_consolidated

buf = io.StringIO()


def make_net():
    with contextlib.redirect_stdout(buf):
        net = S.SceneMomLLM(resume=False)      # 快速构造（v35）
        ng, vocab, pats, cursor = load_version("40.1")   # 换成 v40.1（有守一）
        net.ng, net.vocab, net.pats, net.cursor = ng, vocab, pats, cursor
        net.n2w = {j: w for w, ns in pats.items() for j in ns}
        net.cons, net.val = load_consolidated("40.1")
        net.has_llm = False                    # 不调 LLM——只测网络反应
        net._build_reader()                    # domain/teach_out 重建（v40.1 版）
    return net


def run(txt, steps=4):
    net = make_net()
    net.mom_say(txt)
    out = []
    for _ in range(steps):
        r = net.process()
        if r:
            out.append(r)
    return out


print("═══ 人称视角测试（v40.1 守一）═══\n")

print("① 老师说：「守一饿了吗？」（叫名字 + 问她饿不饿——在和她说话）")
out1 = run("守一饿了吗")
for marker, text in out1:
    print(f"   网络 → ({marker}) {text}")
if not out1:
    print("   网络 → （沉默）")

print("\n② 老师说：「我饿了」（说话者自己的状态——不是在对她说）")
out2 = run("我饿了")
for marker, text in out2:
    print(f"   网络 → ({marker}) {text}")
if not out2:
    print("   网络 → （沉默）")

print("\n③ 对照组——直接叫名字：「守一」")
out3 = run("守一")
for marker, text in out3:
    print(f"   网络 → ({marker}) {text}")
if not out3:
    print("   网络 → （沉默）")
