# -*- coding: utf-8 -*-
"""定式网络·模型能力 CLI（2026-08-11）：代码只负责参数——输出全是模型。

与旧 _cli_net.py 的本质区别（剥离全部代码层"说话"能力）：
  旧: teach_ask / absorb_words / 相位记忆 / free_read 教学链选择
      —— 是代码在替网络说话（代码层假象）
  新: 注入词（参数）→ 网络动力学（模型）→ 读发放翻译（参数）
      —— 网络发放什么就显示什么；无边 → 只能复读注入词（回声）
      这就是网络当前的真实能力边界——CLI 如实展示，不修不演。

代码职责（仅参数/读口）：
  ① 注入: 词 → 神经元脉冲（词表映射——参数）
  ② 驱动: step × N tick（参数：跑多少拍）
  ③ 读出: 发放神经元 → 词（n2w 逆映射——读口）
其余（膜电位/WTA/传播/STDP/噪声）全是网络自身动力学。

命令:
  /trace          内心显示（每 tick 发放的神经元 → 词）
  /info           网络状态（词表/边数/定式/学习开关/参数）
  /learn on|off   STDP 学习开关（教学时开；观察时关——纯检索）
  /reward N       多巴胺注入（零食接口——R-STDP 三因子调制，不改边）
  /reset          清膜电位/发放（跨轮残留清扫）
  /quit           退出

用法: python _cli_model.py [--ver 51] [--trace]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import numpy as np
from snapshot import load_version, snapshot_index
from schema_net import build_pulse

INTRO = (
    "═══ 定式网络·模型能力 CLI ═══\n"
    "（代码只负责参数注入与读出——所有输出都是网络真实发放）\n"
    "（无边状态预期：输入一个词 → 只会复读一个词——回声——模型能力）"
)


def latest_ver():
    rows = snapshot_index()
    if rows:
        return max((r["version"] for r in rows), key=lambda v: float(v))
    return "51"


def split_input(txt):
    """输入分词（参数）：整行优先（词表 token）；否则按空格拆。"""
    if txt in pats_global:
        return [txt]
    return [w for w in txt.replace("，", " ").replace("。", " ")
            .replace("？", " ").replace("！", " ").split()]


class ModelCLI:
    def __init__(self, ver):
        self.ver = ver
        self.ng, self.vocab, self.pats, self.cursor = load_version(ver)
        # 底噪修复（2026-08-11 底噪过度设计诊断）：v51 快照 params 存的
        # noise_amp=0.5（旧值）——加载后覆盖为 0.2（漂移归零实测）——
        # 新快照将固化 0.2（快照是历史记录不改写）。
        if self.ng.noise_amp > 0.21:
            self.ng.noise_amp = 0.2
        self.n2w = {j: w for w, ns in self.pats.items() for j in ns}
        self.trace = "--trace" in sys.argv
        self.learn = False          # 默认冻结（纯观察）——/learn on 开启
        self.ng.learn_gate = False
        self.events = []            # 最近一轮发放事件 [(tick, kind, neuron, word)]

    # ── 模型能力核心：注入（参数）→ 动力学（模型）→ 读出（读口）──
    def run(self, words, ticks_after=4):
        """注入词序列 → 网络自由回响 → 收集每拍真实发放。

        kind: echo = 注入拍发放（回波——网络对词的反应——确定性）
              drift = 非注入拍发放（传播或噪声——无边时 = 噪声底噪）"""
        ng, pats, n2w = self.ng, self.pats, self.n2w
        self.events = []
        tick = 0
        for w in words:
            # 注入前清膜电位/发放/痕迹（防跨轮残留串扰——仿真环境重置）
            ng.v = np.zeros((ng.n, ng.slots))
            ng.spikes = np.zeros(ng.n)
            ng.pre_trace = np.zeros(ng.n)
            ng.step(build_pulse(ng.n, pats[w]), slot=0)   # 注入词 → 发放
            for i in np.where(ng.spikes > 0)[0]:
                self.events.append((tick, "echo", i, n2w.get(i, f"#{i}")))
            tick += 1
            ng.step(np.zeros(ng.n), slot=0)               # 间隔拍（痕迹衰减）
            for i in np.where(ng.spikes > 0)[0]:
                self.events.append((tick, "drift", i, n2w.get(i, f"#{i}")))
            tick += 1
        for _ in range(ticks_after):                       # 结尾回响收敛
            ng.step(np.zeros(ng.n), slot=0)
            for i in np.where(ng.spikes > 0)[0]:
                self.events.append((tick, "drift", i, n2w.get(i, f"#{i}")))
            tick += 1
        return self.events

    def words_of(self, kind):
        """按首次发放顺序去重提取某类发放的词。"""
        out, seen = [], set()
        for _, k, _, w in self.events:
            if k == kind and w not in seen:
                seen.add(w)
                out.append(w)
        return out

    def model_out(self):
        """模型输出 = 回波词（网络对注入词的真实反应——复读/回声）。"""
        return self.words_of("echo")

    def show_info(self):
        ng = self.ng
        total = sum(len(ng.W_out[i][k]) for i in range(ng.n)
                    for k in range(ng.slots))
        print(f"  版本 {self.ver} | 词表 {len(self.pats)} 词 | "
              f"神经元 {ng.n:,} | 边 {total:,} | "
              f"定式 {len(getattr(ng, 'skeletons', {}) or {})}")
        print(f"  学习: {'开（STDP 会改边）' if self.learn else '关（纯检索——零改动）'} | "
              f"theta={ng.theta} wta_k={ng.wta_k} noise_p={ng.noise_p} | "
              f"std_dep={ng.std_dep} inh_norm={ng.inh_norm}")

    def show_round(self, words):
        echo = self.words_of("echo")
        drift = self.words_of("drift")
        if self.trace:
            print("  ── 内心活动（每 tick 发放）──")
            for t, k, i, w in self.events:
                tag = "回波" if k == "echo" else "漂移"
                print(f"    t{t} [{tag}] {w} (神经元 {i})")
        print(f"  模型输出: {' / '.join(echo) if echo else '（沉默——无回波）'}")
        if drift:
            print(f"  噪声漂移: {len(drift)} 词（{'、'.join(drift[:8])}"
                  f"{'…' if len(drift) > 8 else ''}）"
                  f"——无边传播——噪声累积越阈——网络真实底噪（非语义）")


# 分词用全局词表（split_input 引用）
pats_global = {}


def main():
    ver = sys.argv[sys.argv.index("--ver") + 1] if "--ver" in sys.argv \
        else latest_ver()
    cli = ModelCLI(ver)
    global pats_global
    pats_global = cli.pats
    print(INTRO)
    cli.show_info()
    print("\n命令：/trace /info /learn /reward /reset /quit\n")

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
            cli.trace = not cli.trace
            print(f"[内心显示: {'开' if cli.trace else '关'}]")
            continue
        if txt == "/info":
            cli.show_info()
            continue
        if txt == "/reset":
            cli.ng.reset()
            cli.events = []
            print("[已清空膜电位/发放]")
            continue
        if txt == "/learn":
            cli.learn = not cli.learn
            cli.ng.learn_gate = cli.learn
            print(f"[STDP 学习: {'开——教学模式（会改边）' if cli.learn else '关——纯检索（零改动）'}]")
            continue
        if txt.startswith("/learn "):
            on = txt.split()[1] in ("on", "开", "1")
            cli.learn = on
            cli.ng.learn_gate = on
            print(f"[STDP 学习: {'开' if on else '关'}]")
            continue
        if txt.startswith("/reward"):
            amt = float(txt.split()[1]) if len(txt.split()) > 1 else 2.0
            cli.ng.release_da(amt)
            print(f"[多巴胺 +{amt:g} → da={cli.ng.da:g} "
                  f"RPE={cli.ng.last_rpe:+.3g}]（不改边——调质下一轮学习）")
            continue

        words = split_input(txt)
        oov = [w for w in words if w not in cli.pats]
        if oov:
            print(f"  [词表外] {'、'.join(oov)}——先忽略（词表 {len(cli.pats)} 词）")
            words = [w for w in words if w in cli.pats]
        if not words:
            print("  （无词表内词——网络没听见）")
            continue
        print(f"── 注入「{' '.join(words)}」({len(words)} 词) ──")
        cli.run(words)
        cli.show_round(words)


if __name__ == "__main__":
    main()
