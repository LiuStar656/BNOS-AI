# -*- coding: utf-8 -*-
"""定式网络交互 CLI（2026-08-11）：用户（老师）和守一直接对话。

复用老师场景机制：用户输入 = 听觉注入（老师说）→ 网络 process（组词
→ 提问应答 → 被叫应答 → 好奇提问 → 自身念头）→ 显示网络反应。

命令：
  /trace   切换内心活动显示（组词/候选/选择）
  /info    显示网络状态（词表/边数/守一/听学应答）
  /resume  重新加载最新快照
  /quit    退出

用法：python _cli_net.py [--ver 40.1]（默认最新快照）
"""
import io
import random
import sys
import contextlib
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stage"))

from snapshot import load_version, load_consolidated, snapshot_index
import _scene_mom_llm as S

MARKER_LABEL = {"reply": "回答", "ask": "提问", "spont": "自发",
                "recall_q": "回忆", "recall_a": "回忆"}


def latest_ver():
    rows = snapshot_index()
    if rows:
        return max((r["version"] for r in rows), key=lambda v: float(v))
    return "40.1"


def load_net(ver):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        net = S.SceneMomLLM(resume=False)
        ng, vocab, pats, cursor = load_version(ver)
        net.ng, net.vocab, net.pats, net.cursor = ng, vocab, pats, cursor
        net.n2w = {j: w for w, ns in pats.items() for j in ns}
        net.cons, net.val = load_consolidated(ver)
        net.has_llm = False          # 用户就是老师——不调 LLM
        net._build_reader()
    return net


def show_net(net, ver):
    total = sum(len(net.ng.W_out[i][k])
                for i in range(net.ng.n) for k in range(net.ng.slots))
    print(f"  版本 {ver} | 词表 {len(net.pats)} 词 | 边 {total:,} | "
          f"守一 {len(net.pats.get('守一', []))} 神经元")
    if net.learned_reply:
        print(f"  听学应答: {''.join(net.learned_reply)}（被叫时按边验证读出）")
    print(f"  固化句: {sum(len(v) for v in net.cons.values())} 句 | "
          f"验证门: {len(net.val)} 条 | 定式: {len(net.ng.skeletons or {})}")


def main():
    ver = sys.argv[sys.argv.index("--ver") + 1] if "--ver" in sys.argv \
        else latest_ver()
    trace = "--trace" in sys.argv
    net = load_net(ver)
    print("═══ 定式网络交互 CLI ═══")
    print("（你是老师——直接说话；网络听到、思考、回应）\n")
    show_net(net, ver)
    print("\n命令：/trace /info /resume /quit\n")

    while True:
        try:
            txt = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break
        if not txt:
            continue
        if txt in ("/quit", "/exit", "退出"):
            print("再见。")
            break
        if txt == "/trace":
            trace = not trace
            print(f"[内心活动显示: {'开' if trace else '关'}]")
            continue
        if txt == "/info":
            show_net(net, ver)
            continue
        if txt == "/resume":
            ver = latest_ver()
            net = load_net(ver)
            print(f"[重新加载 v{ver}]")
            show_net(net, ver)
            continue

        # 教学判定（自主学习闭环）：
        # ① 网络刚提问（asked_word）→ 用户输入不含疑问词 = 回答 → 吸收；
        #    含疑问词 = 用户没答、换了新问题 → 不吸收（防污染）
        # ② 无 asked_word → 用户输入含"不懂的词"（词表内 domain 外）
        #    = 主动教学 → 吸收该词（用户直接教也能学）
        is_question = any(a in txt for a in S.ASK_WORDS) or \
            any(w in txt for w in S.MOTIVE["需求"])
        if net.asked_word and not is_question:
            net.absorb_words(txt)
            ans_toks = [w for w in net._split_words(txt) if w in net.pats]
            net.teach_ask(net.asked_word, ans_toks)
            print(f"  [学] 「{net.asked_word}」→ 吸收了「{txt}」——"
                  f"语义边+问句结构已建立")
            cand = net._read(net.asked_word)
            if cand:
                print(f"  [学会] 再问它，它会说：「{'/'.join(cand)}」")
            net.asked_word = None
        elif net.asked_word and is_question:
            print("  （上轮提问没答——继续问别的了）")
            net.asked_word = None
        else:
            # 主动教学只吃陈述句（用户在教——"蝴蝶是昆虫"）；问句/
            # 打招呼不吸收（用户在问不是在教——防污染）
            if not is_question:
                target = next((w for w in net._split_words(txt)
                               if w in net.pats and w not in net.domain
                               and w not in S.FUNC and w != S.SELF_NAME
                               and w not in net.cons), None)
                if target:
                    net.asked_word = target
                    net.absorb_words(txt)
                    ans_toks = [w for w in net._split_words(txt)
                                if w in net.pats]
                    net.teach_ask(target, ans_toks)
                    print(f"  [学] 「{target}」→ 吸收了「{txt}」——"
                          f"语义边+问句结构已建立")
                    cand = net._read(target)
                    if cand:
                        print(f"  [学会] 再问它，它会说：「{'/'.join(cand)}」")
                    net.asked_word = None

        # 听觉注入（老师说话）——先清上一轮残留（pending 未组完的字
        # /旧提问候选/旧冷却——新话覆盖旧话，防跨轮串扰回声）
        net.pending = []
        net.q_nouns = []
        net.q_txt = ""
        net.cooldown = 0
        net.mom_say(txt, scan_curious=True)   # 任何输入都扫好奇——自主发现不懂
        if trace:
            for l in net.log:
                print(f"  · {l}")
        net.log.clear()
        # 网络处理：跑最多 24 tick 等一次表达（冷却/组词/思考）
        out = None
        for _ in range(24):
            out = net.process()
            if out:
                break
        if trace and net.log:
            for l in net.log:
                print(f"  · {l}")
            net.log.clear()
        if out:
            marker, text = out
            label = MARKER_LABEL.get(marker, marker)
            print(f"守一> [{label}] {text}")
            if marker == "ask":
                print("      （守一在问你——回答它吧）")
        else:
            # 自身 tick 刺激源（非问答——真自发）：相位记忆/联想流/
            # 自发噪声——网络自己冒念头（静默期+冒出期交替）
            net.tick += 1
            net.phase = net.tick % S.PHASES
            mem = next((w for r, w in S.PHASE_MEM.items()
                        if net.phase in r), None)
            seed = None
            if net.last_tail and random.random() < 0.5:
                seed = net.last_tail              # 联想流：念头接念头
            elif mem:
                seed = mem                        # 相位记忆唤起（内部时钟）
            if seed and seed in net.pats:
                cand = net._read(seed)
                if cand:
                    net.last_tail = cand[-1]
                    print(f"守一> [自发] {'/'.join(cand)}"
                          f"（自己想到的——相位/联想）")
                else:
                    print("守一> （沉默……）")
            else:
                print("守一> （沉默……）")
        if trace:
            print()


if __name__ == "__main__":
    main()
