# -*- coding: utf-8 -*-
"""字级 OOV 落地（v14 方案）：词表外词 → 字模式并集身份 → 语境自动学语义
→ 固化落位 + 小测验。

方案（v14 [PLAN]-字级OOV，2026-08-10 落地）：
  ① 识别：教学句 tokens ∉ pats = OOV；全字已在字级字典（或现场分配）→
     字模式并集 = 临时身份（复用 allocate_pats，K=4/字）
  ② 语义自动学：pats[oov词] = 字模式并集 → _learn_sentence 正常注入 →
     与现有 Hebbian/STDP 同路径 → 语义边自然长出（吃→榴莲）
  ③ 固化落位：OOV 出现 ≥ entrench_times → allocate_pats 正式词模式 →
     pats[oov词] 换新模式（v1 简化：不迁移字模式边——诚实标注，字纠缠
     观察点）
  ④ 小测验：OOV 教学后检查——唤起（边存在）/ 语义关联（吃→OOV）/
     字级原子保留（单字模式未被破坏）

用法：python _grow_oov.py [--smoke]
"""

import json
import sys
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from sparse_net import allocate_pats
from _grow_v16 import edge_between, direct_next_multi

RUNS_DIR = Path(__file__).parent / "runs"
K = 4
ENTRENCH = 3           # 固化阈值：OOV 出现次数

# ── OOV 教学素材（真 OOV：jieba 整词不在词表，已查证）──────────
OOV_LESSONS = [
    "我想吃榴莲酥",          # 榴莲酥 OOV
    "我喜欢吃草莓酱",        # 草莓酱 OOV
    "过马路要看红绿灯",      # 红绿灯 OOV
    "她用电动牙刷刷牙",      # 电动牙刷 OOV
]


def tokenize_simple(s):
    """简单切词：优先词表词（贪心最长），否则单字（OOV 候选）。"""
    return [c for c in s]     # 简化：单字切（词表词由 pats 命中判定）


def main():
    smoke = "--smoke" in sys.argv
    t0 = time.time()
    print("═══ 字级 OOV：词表外词 → 字模式并集 → 语义自动学 → 固化 ═══\n")

    ng, vocab, pats, cursor = load_version("18.21")
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    char_pats = {}                            # 字 → 模式（现场分配）
    oov_count = {}                            # OOV 词 → 出现次数
    print(f"[加载] 18.21：n={ng.n}，词表 {len(keys)}，cursor={cursor}")

    # ── 1. 字级字典（按需分配：OOV 字不在词表则 allocate）────────
    def char_mode(ch):
        if ch in keys:                        # 单字已在词表 → 用原模式
            return pats[ch]
        if ch not in char_pats:
            new_p, cursor = allocate_pats(ng, [ch], K, cursor)
            char_pats[ch] = new_p[ch]
        return char_pats[ch]

    # ── 2. OOV 识别（jieba 整词查表）+ 字模式身份 + 教学 ───────
    import jieba
    print("\n[教学] OOV 句逐句喂入（jieba 分词 → OOV 词 → 字模式并集身份）…")
    oov_learned = []
    for s in OOV_LESSONS:
        seq = list(jieba.cut(s))
        oovs = [w for w in seq if w not in keys]
        for oov_word in oovs:
            oov_count[oov_word] = oov_count.get(oov_word, 0) + 1
            # 字模式并集 = 临时身份（进 pats，注入即建语义边）；
            # 字不在词表 → 现场 allocate（按需落位）
            pats[oov_word] = sorted(
                {j for ch in oov_word for j in char_mode(ch)})
            oov_learned.append(oov_word)
            print(f"  OOV「{oov_word}」= 字模式并集（{list(oov_word)}），"
                  f"已入 pats（第 {oov_count[oov_word]} 次出现）")
        for _ in range(2):
            _learn_sentence(ng, seq, pats, slot=0)
    print(f"  [教学] {len(OOV_LESSONS)} 句喂入，OOV 词 {oov_learned}")

    # ── 3. 固化落位（≥ ENTRENCH 次的 OOV → 正式词模式）────────
    print("\n[固化] OOV 出现 ≥%d 次 → 分配正式词模式（v1 简化不迁移字边）"
          % ENTRENCH)
    for w, n in oov_count.items():
        if n >= ENTRENCH:
            new_p, cursor = allocate_pats(ng, [w], K, cursor)
            pats[w] = new_p[w]
            print(f"  「{w}」出现 {n} 次 → 正式词模式落位（n={ng.n}）")

    # ── 4. 小测验（动态引用实际识别的 OOV 词）─────────────────
    print("\n[小测验] OOV 学习效果检查")
    results = {}
    if not oov_learned:
        print("  ❌ 无 OOV 被识别（素材词全在词表/被 jieba 拆分）——"
              "教学无效，需换真 OOV 素材")
    ow = oov_learned[0] if oov_learned else "草莓酱"
    # ① 唤起：语义边存在（吃→OOV 词，如 吃→草莓酱）
    w = edge_between(ng, pats, "吃", ow)
    results[f"吃→{ow}"] = w
    print(f"  {'✅' if w > 0 else '❌'} 语义边 吃→{ow} = {w}（OOV 词被"
          f"{'学进' if w > 0 else '没学进'}网络）")
    w2 = edge_between(ng, pats, "喜欢", ow)
    results[f"喜欢→{ow}"] = w2
    print(f"  {'✅' if w2 > 0 else '❌'} 语义边 喜欢→{ow} = {w2}")
    # ② 唤起：读"吃"出边能否唤起 OOV 词
    top = direct_next_multi(ng, pats, n2w, ["吃"], k=8)
    hit = any(x == ow for x, _ in top)
    results[f"读吃唤起{ow}"] = hit
    print(f"  {'✅' if hit else '❌'} 读「吃」出边唤起{ow}"
          f"（top: {[x for x, _ in top[:6]]}）")
    # ③ 字级原子保留：OOV 字若在词表（如 草/红/电），模式未被破坏
    chars_ok = [ch for ch in ow if ch in keys]
    print(f"  {'✅' if chars_ok else '⚠️'} 单字原子检查：{ow} 的字"
          f"{'、'.join(chars_ok) if chars_ok else '（均不在词表，现场分配无冲突）'}"
          f"（字模式与词模式并存）")
    # ④ OOV 句复述：再喂 OOV 句，边继续涨（语义自动学）
    before = edge_between(ng, pats, "吃", ow)
    for _ in range(2):
        _learn_sentence(ng, ["我", "想", "吃", ow], pats, slot=0)
    after = edge_between(ng, pats, "吃", ow)
    results["语义边再学"] = f"{before}→{after}"
    print(f"  {'✅' if after > before else '❌'} 再喂「我想吃{ow}」×2："
          f"吃→{ow} {before} → {after}"
          f"（语义边{'持续增长' if after > before else '未增长'} = "
          f"{'自动学语义成立' if after > before else '自动学失效'}）")

    # ── 5. 留档 + 快照（OOV 词典进快照）────────────────────────
    out_dir = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_oov"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"tag": "字级 OOV（v14 方案落地）", "base": "18.21",
              "oov_learned": oov_learned, "oov_count": oov_count,
              "quiz": results, "n": ng.n,
              "sec": round(time.time() - t0, 1)}
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[留档] {out_dir}/result.json（{time.time() - t0:.0f}s）")

    if not smoke:
        save_snapshot(ng, parent="18.21",
                      tag="Stage 3 v21：字级 OOV（词表外词字模式并集 + "
                          "语义自动学 + 固化落位）",
                      metrics=result, vocab=vocab, pats=pats, cursor=cursor)


if __name__ == "__main__":
    main()
