# -*- coding: utf-8 -*-
"""[EXP] 拼音音素粒度自然涌现教学：「叫爸爸」→ 音节组合 + 共享结构

诊断（2026-08-11，用户）："改用拼音的形式肯定是我们之前的颗粒度把网络
焊死了"——词粒度下 爸爸/妈妈 是两套零共享的 4 神经元死模式，学到的是
"叫→爸爸"具体配对（死记 + 马太）；拼音粒度把词拆成 声母+韵母 音素原子：

    爸爸 = b a b a    妈妈 = m a m a    哥哥 = g e g e    叫 = j iao

结构差异（本实验要验证的假设）：
  ① 组合性：音节 = 声母+韵母 组合（b→a 组合边）——不是闭集死记
  ② 共享性：爸爸/妈妈 共享韵母 a、共享 CV-CV 重复节奏——结构可复用
  ③ 论元强调 > 联想边：注入论元 amp=20 > 联想边 w_max=16——当前论元胜出
     （词粒度 E3 已验证"新词重读"原理——音素级全程应用）

协议（同 [PLAN] 自然涌现条件——老师只做三件事）：
  说（音素流 + 韵律强调）→ 零食（release_da——DA 门控）→ 验证
  零边起点（v53.0）——所有边由 STDP/Hebbian 自然长出

阶段：
  A. 音素表就位（47 音素 × 4 神经元——从空池分配，零边起点自检）
  B. 教学「叫 爸爸」×N → 音节组合边/重复边涌现曲线
  C. 验证：jiao 联想 / ba 组合自持 / 叫爸爸 轨道完成
  D. 教学「叫 妈妈」×N → 共享 a 结构——当前论元胜出？（颗粒度验证点）
  E. 泛化：未教「叫 哥哥」（g e g e）——诚实记录（规则层级预期未现）

用法：python _exp_pinyin.py
"""

import time
from pathlib import Path

import numpy as np

from schema_net import build_pulse
from snapshot import load_snapshot, save_snapshot
from sparse_net import allocate_pats

BASE = Path(__file__).resolve().parent / "runs" / "v52_2_20260811_183718"  # v53.0
N_TEACH = 30             # 「叫爸爸」「叫妈妈」各 30 次（同次数——公平竞争）
K_PHON = 4               # 音素原子模式神经元数（真正最小单元——词粒度是死记）
AMP_VERB = 1.0           # 动词轻声（j iao——须 ≥θ=1.0 发放）
AMP_ARG = 20.0           # 论元重读（> 联想边 w_max=16——注入论元必胜）
REWARD = 2.0             # 每次教学零食量（da_max 截断）

# 音素表（声母 23 + 韵母 25——48 个原子音素；声调暂缓——阶段二）
# 韵母含三拼音节复合 i-ao（"叫"= j-iao 需要）；声母/韵母表含旧声音实验
# 残留条目（b/a/i 等——零边快照下干净，长度需=4 校验）
SHENGMU = ("b p m f d t n l g k h j q x zh ch sh r z c s y w").split()
YUNMU = ("a o e i u ü ai ei ui ao ou iu ie üe er an en in un ün "
         "ang eng ing ong iao").split()
PHONEMES = SHENGMU + YUNMU
assert len(PHONEMES) == 48, len(PHONEMES)

# 词 → 音素流（简化：韵母整体——"叫"= j+iao；声调暂不编码）
WORD_PH = {
    "叫":   ["j", "iao"],
    "爸爸": ["b", "a", "b", "a"],
    "妈妈": ["m", "a", "m", "a"],
    "哥哥": ["g", "e", "g", "e"],      # 未教论元（泛化测试）
}
JIAO = WORD_PH["叫"]


def teach_once(ng, pats, seq, amp_arg=AMP_ARG, reward=REWARD, verb_len=None):
    """自然涌现教学一次：零食（DA 门控）→ 音素流（动词轻声 + 论元重读）
    → 空拍留痕 → 句尾零食（资格迹兑现全部相邻配对——含音节组合 b→a、
    跨音节 a→b、动词→论元 j→b 等——全部自然长出）。
    verb_len：动词音素数（默认 len(JIAO)——字母级动词更长可覆写）。"""
    if verb_len is None:
        verb_len = len(JIAO)
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)      # 句间清痕迹（跨次教学不串扰）
    ng.release_da(reward)              # 先给零食——学习开关（da=0 不学）
    for i, ph in enumerate(seq):
        ng.spikes = np.zeros(ng.n)
        amp = amp_arg if i >= verb_len else AMP_VERB   # 论元重读、动词轻声
        ng.step(build_pulse(ng.n, pats[ph], amp), slot=0)
        ng.spikes = np.zeros(ng.n)
        ng.step(np.zeros(ng.n), slot=0)   # 空拍：痕迹衰减（前驱仍 >0.3 阈值）
    ng.release_da(reward)              # 句尾零食——延迟归因兑现配对


def recall(ng, pats, seq, amps, max_steps=10, wta_k=None):
    """冻结态检索（learn_gate=False——零学习）：
    逐音素注入（注入拍后留空拍——传播链自然延续）→ 空拍至收敛。
    显示只保留音素神经元（底噪无名神经元过滤——只关心语言结构）。"""
    n2w = {int(x): w for w, ns in pats.items() for x in ns}
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)
    gate = ng.learn_gate
    wta_old = ng.wta_k
    ng.learn_gate = False
    if wta_k:
        ng.wta_k = wta_k
    timeline = []
    for ph, amp in zip(seq, amps):
        ng.step(build_pulse(ng.n, pats[ph], amp), slot=0)
        now = {n2w.get(int(x)) for x in np.where(ng.spikes > 0)[0]}
        now = {w for w in now if w}          # 只留音素（滤底噪）
        timeline.append((f"注入{ph}", now))
    for _ in range(max_steps):
        ng.step(np.zeros(ng.n), slot=0)
        now = {n2w.get(int(x)) for x in np.where(ng.spikes > 0)[0]}
        now = {w for w in now if w}
        timeline.append(("空拍", now))
        if not now:
            break
    ng.learn_gate = gate
    ng.wta_k = wta_old
    return timeline


def edge_weight(ng, pats, pre, post, slot=0):
    """pre→post 全部音素模式边（均值/最大/条数）。"""
    ws = [ng.W_out[i][slot].get(j, 0.0)
          for i in pats[pre] for j in pats[post]]
    return float(np.mean(ws)), float(np.max(ws)), int(np.sum(np.array(ws) > 0))


def count_edges(ng):
    return sum(len(r) for i in range(ng.n) for r in [ng.W_out[i][0]] if r)


def show_timeline(tl, title):
    print(f"    {title}")
    for tag, phs in tl:
        disp = "".join(sorted(phs)) if phs else "—"
        print(f"      {tag:>10} → {disp}")


def main():
    t0 = time.time()
    # ── A. 音素表就位（空池分配 + 零边起点自检）──
    ng, vocab, pats, cursor = load_snapshot(BASE)
    print(f"[A] 基座 {BASE.name}: n={ng.n}  边={count_edges(ng)}  "
          f"cursor={cursor}  w_max={ng.w_max}  wta_k={ng.wta_k}  theta={ng.theta}")
    assert count_edges(ng) == 0, "基座不是零边起点——检查失败"
    missing = [p for p in PHONEMES if p not in pats]
    # 旧声音实验残留音素（b/a/i 等）——长度校验（须=4，零边快照下干净）
    for p in PHONEMES:
        if p in pats:
            assert len(pats[p]) == K_PHON, f"残留音素 {p} 长度 {len(pats[p])}"
    if missing:
        new_pats, cursor = allocate_pats(ng, missing, K_PHON, cursor)
        pats.update(new_pats)
        lo = min(min(v) for v in new_pats.values())
        hi = max(max(v) for v in new_pats.values())
        print(f"    分配 {len(missing)} 音素 × {K_PHON} 神经元 = [{lo}, {hi}]"
              f"  cursor={cursor}")
    # 音素模式落位确认（应全部在空池/新分配区——不与旧词表神经元冲突）
    all_ph = set()
    for p in PHONEMES:
        all_ph.update(int(x) for x in pats[p])
    assert len(all_ph) == len(PHONEMES) * K_PHON, "音素模式冲突——检查失败"
    print(f"    音素 {len(PHONEMES)} × {K_PHON} = {len(all_ph)} 神经元就位（无冲突）")

    def ph_seq(*words):
        seq, amps = [], []
        for w in words:
            seq += WORD_PH[w]
            amps += [AMP_ARG] * len(WORD_PH[w])
        # 动词轻声（第一个词=叫：j,iao 轻声）
        for i in range(len(JIAO)):
            amps[i] = AMP_VERB
        return seq, amps

    print(f"[B] 教学「叫 爸爸」×{N_TEACH}（奖励 {REWARD} + 论元重读 {AMP_ARG}"
          f" > 联想边 {ng.w_max}）")
    seq_b, _ = ph_seq("叫", "爸爸")
    curve = []
    for i in range(1, N_TEACH + 1):
        teach_once(ng, pats, seq_b)
        if i in (1, 5, 10, 20, 30):
            row = {f"{p[0]}->{p[1]}": edge_weight(ng, pats, *p) for p in
                   [("j", "b"), ("iao", "a"), ("b", "a"), ("a", "b")]}
            curve.append((i, row))
            print(f"    第 {i:2d} 次: j→b {row['j->b'][0]:5.2f} | "
                  f"iao→a {row['iao->a'][0]:5.2f} | b→a {row['b->a'][0]:5.2f} | "
                  f"a→b {row['a->b'][0]:5.2f}   总边 {count_edges(ng)}")
    for pre, post in [("j", "b"), ("iao", "a"), ("b", "a"), ("a", "b"),
                      ("j", "a"), ("iao", "b")]:
        m, mx, nn = edge_weight(ng, pats, pre, post)
        print(f"    {pre}→{post} = 均值 {m:.3f} 最大 {mx:.3f} 边数 {nn}")

    print("[C] 验证（冻结检索 learn_gate=False）")
    show_timeline(recall(ng, pats, ["j", "iao"], [AMP_VERB] * 2),
                  "C1 输入「叫」(j iao) → 联想带出")
    show_timeline(recall(ng, pats, ["b", "a"], [AMP_ARG] * 2),
                  "C2 输入「ba」(b a) → 音节组合自持？")
    show_timeline(recall(ng, pats, *ph_seq("叫", "爸爸")),
                  "C3 输入「叫 爸爸」→ 轨道完成？")

    print(f"[D] 教学「叫 妈妈」×{N_TEACH}（共享韵母 a——颗粒度验证点）")
    seq_m, _ = ph_seq("叫", "妈妈")
    for i in range(1, N_TEACH + 1):
        teach_once(ng, pats, seq_m)
    for pre, post in [("j", "m"), ("iao", "a"), ("m", "a"), ("a", "m"),
                      ("j", "b"), ("a", "b"), ("iao", "m"), ("j", "iao")]:
        m, mx, nn = edge_weight(ng, pats, pre, post)
        print(f"    {pre}→{post} = 均值 {m:.3f} 最大 {mx:.3f} 边数 {nn}")
    show_timeline(recall(ng, pats, *ph_seq("叫", "妈妈")),
                  "D1 输入「叫 妈妈」→ 当前论元胜出？（vs 先学 b 联想）")
    show_timeline(recall(ng, pats, *ph_seq("叫", "妈妈"), wta_k=4),
                  "D1b 输入「叫 妈妈」wta_k=4 → 注入论元 m(36) vs 联想 b(16)——收窄竞争？")
    show_timeline(recall(ng, pats, ["j", "iao"], [AMP_VERB] * 2),
                  "D2 输入「叫」→ 联想（双轨并存？马太观察）")
    show_timeline(recall(ng, pats, ["j", "iao"], [AMP_VERB] * 2, wta_k=4),
                  "D2b 输入「叫」wta_k=4 → 联想收窄？（a→b vs a→m 对称）")
    show_timeline(recall(ng, pats, *ph_seq("叫", "爸爸")),
                  "D3 输入「叫 爸爸」→ 旧轨保留？")
    show_timeline(recall(ng, pats, *ph_seq("叫", "爸爸"), wta_k=4),
                  "D3b 输入「叫 爸爸」wta_k=4 → 对称验证（b 注入 36 > m 联想 16）")

    print("[E] 泛化：未教「叫 哥哥」(g e g e——音素已就位、组合从未教)")
    show_timeline(recall(ng, pats, *ph_seq("叫", "哥哥")),
                  "E1 输入「叫 哥哥」→ ？（规则层级预期未现——诚实记录）")
    show_timeline(recall(ng, pats, *ph_seq("叫", "哥哥"), wta_k=4),
                  "E1b 输入「叫 哥哥」wta_k=4 → 未教组合（g→e 无边）收窄后？")

    # ── F. 存档 ──
    metrics = {
        "pinyin": {
            "base": "53.0", "phonemes": len(PHONEMES), "k_phon": K_PHON,
            "teach": N_TEACH, "amp": {"verb": AMP_VERB, "arg": AMP_ARG},
            "reward": REWARD,
            "curve": [[i, {k: v[0] for k, v in row.items()}]
                      for i, row in curve],
            "edges": {f"{p}->{q}": edge_weight(ng, pats, p, q)
                      for p, q in [("j", "b"), ("j", "m"), ("b", "a"),
                                   ("a", "b"), ("m", "a"), ("a", "m"),
                                   ("j", "g"), ("g", "e")]},
            "total_edges": count_edges(ng),
        },
    }
    out = save_snapshot(
        ng, parent="53.0", vocab=vocab, pats=pats, cursor=cursor, metrics=metrics,
        tag=f"拼音音素粒度：叫爸爸/叫妈妈（47 音素×4，论元重读 {AMP_ARG}，"
            f"{N_TEACH}+{N_TEACH} 次）+ 哥哥泛化记录", data_fp=str(BASE))
    print(f"[F] 快照: {out}")
    print(f"耗时 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
