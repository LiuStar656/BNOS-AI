# -*- coding: utf-8 -*-
"""v17 训练管线（先见后教）：散文喂入（先见）→ 教学数据（后教）→ 分句接话。

背景（2026-08-10 用户三决策）：
  - "不是教，是先让网络见过散文"——散文 = 暴露/输入，不是配对句教学
  - 落地：散文全量喂进网络成经验（_learn_sentence 逐句）→ 先见
  - 顺序：先喂散文建立语言背景 → 再喂教学数据把目标边压回 → 后教
  - 验收：不变（仍以 v16 的 6 句分句接话为准，修正前 ≥0.95 为 v17 目标）

v17 升级（PLAN Stage3v17，2026-08-10）：
  - 数据扩量：后教数据源 stage3_rel_v2.json（108 条）→ stage3_rel_v3.json
    （166 条 = 108 现有 + 58 新模板全部词表内）——全量散文后教拉回力不足
    的应对（"虽然→但是"配对直读断点 108×2 轮拉不动）
  - 训练完成后快照 v17.0（smoke 不存）
  - 验收口径：后教后修正前 ≥0.95 且校准 ≤1 处 → 快照 v17.0

处理：散文句 jieba 分词 → 只保留词表内词（≥3 词才喂）——铁律 1 边界：
  散文只做"见过"背景（词表内共现），不扩词表不学新词（新词归 Stage 4）。

并发切块（用户 2026-08-10：怎么会花这么多时间？并发呢？能不能切块？）：
  - 2026-08-10 对拍实证：_learn_sentence 每句结尾回响 4 步 v 不清零 →
    噪声连续累积越阈发放（每句 ~3600 条随机边），噪声序列由 rng 决定 →
    纯统计批量（跳过动力学）永远不等价（对拍 1846 万边差异 340 万）。
  - 成立方案：rng 状态传递的进程切块——主进程预生成每块边界 rng state
    （只跑 random 不学习，秒级），各进程从对应 state 恢复 rng 喂自己
    的句子块 → 块内噪声序列与串行逐位一致 → 增量边合并 = 串行结果。
  - 等价性已证：100 句 2 块对拍，15332295 条边差异 0（_verify_chunk.py）。
  - 全量串行 ~60 分钟；--chunks 4 → 约 30 分钟（越喂越慢超线性）。

用法：python _probe_expose_prose.py [--smoke] [--chunks N] [--verify-chunk]
  --smoke：每本书只取前 200 句快跑（机制验证，不存快照）
  --chunks N：散文先见切 N 块进程并行（默认全量 4）
  --verify-chunk：smoke 规模对拍切块 ≡ 串行（逐边，对拍铁律）
"""

import copy
import json
import re
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import jieba
import numpy as np

from schema_net import _learn_sentence
from snapshot import load_version, save_snapshot
from sparse_net import _rows_from_arrays
from _grow_v16 import (EVAL, REL_FRONT, REL_BACK, role_of, legal_for,
                       clause_next, chain_generate, calibrate, K, R_S)

PROSE_DIR = Path(__file__).parent / "data" / "curriculum" / "raw" / "prose"
DATA = Path(__file__).parent / "data" / "curriculum"
RUNS_DIR = Path(__file__).parent / "runs"

BOOKS = ["zhaohuaxishi_luxun.txt", "nahan_luxun.txt", "panghuang_luxun.txt",
         "yecao_luxun.txt", "nanqiangbeidiao_luxun.txt"]
TITLE = {
    "zhaohuaxishi_luxun.txt": "朝花夕拾（散文集）",
    "nahan_luxun.txt": "呐喊（叙事小说集）",
    "panghuang_luxun.txt": "彷徨（叙事小说集）",
    "yecao_luxun.txt": "野草（散文诗）",
    "nanqiangbeidiao_luxun.txt": "南腔北调集（杂文）",
}


def clean_pg(text):
    """去 Gutenberg 页眉页脚与脚注标记。"""
    m = re.search(r"\*\*\*\s*START OF[^\n]*\n", text)
    if m:
        text = text[m.end():]
    m = re.search(r"\*\*\*\s*END OF[^\n]*", text)
    if m:
        text = text[:m.start()]
    text = re.sub(r"\[_?[Nn]ote:[^\]]*\]", "", text)
    text = re.sub(r"[_*#]{1,3}\s?", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def split_sents(text):
    """标点分句（。！？；切分）。"""
    return [s for s in re.split(r"[。！？；]+", text) if len(s) >= 4]


def collect_prose_seqs(keys, smoke=False):
    """读 5 本散文 → 繁转简 → 分句 → 分词 → 只保留词表内词（≥3 词）。

    返回 (seqs, stats)。seqs = [["词", ...], ...]（词表内子序列）。
    """
    from opencc import OpenCC
    cc = OpenCC("t2s")
    seqs, per_book = [], {}
    for fn in BOOKS:
        raw = (PROSE_DIR / fn).read_text(encoding="utf-8", errors="ignore")
        body = cc.convert(clean_pg(raw))
        sents = split_sents(body)
        if smoke:
            sents = sents[:200]
        kept, n_all = 0, len(sents)
        for s in sents:
            toks = [w for w in jieba.cut(s) if w in keys]
            if len(toks) >= 3:
                seqs.append(toks)
                kept += 1
        per_book[fn] = {"book": TITLE[fn], "sents": n_all, "kept": kept}
        print(f"  [{TITLE[fn]}] 分句 {n_all} → 词表内序列 {kept}")
    return seqs, per_book


# ════════════════════════════════════════════════════════════════
#  并发切块（rng 状态传递；等价性由 _verify_chunk.py 对拍证明）
# ════════════════════════════════════════════════════════════════

_RNG_START = None  # 主进程加载快照后的 rng 起点（串行基线与切块共用）


def _snap(ng):
    """全量边快照（数组级，零 dict）：返回 (src_i, slot_k, dst_j, vals)。

    W_out 按 (i, k) 行序、行内 dst 升序 → 数组天然按 (i,k,j) 复合键升序。
    内存账：1800 万边 ≈ 220MB（vs dict 版 ~2GB，8.5 倍差，见内存优化探针报告）。
    """
    rows = []
    total = 0
    for i in range(ng.n):
        for k in range(ng.slots):
            m = len(ng.W_out[i][k])
            if m:
                rows.append((i, k, m))
                total += m
    src = np.empty(total, np.int32)
    slot = np.empty(total, np.int8)
    dst = np.empty(total, np.int32)
    vals = np.empty(total, np.float64)
    off = 0
    for i, k, m in rows:
        d, w = ng.W_out[i][k].edge_view()
        n2 = off + m
        src[off:n2] = i
        slot[off:n2] = k
        dst[off:n2] = d
        vals[off:n2] = w
        off = n2
    return src, slot, dst, vals


def rng_boundaries(seqs, n_blocks):
    """主进程预生成每块边界的 rng state（只跑 random 不学习）。

    每句的 rng 消耗 = _learn_sentence 的步数：每词注入+间隔 2 步 + 结尾回响 4 步。
    返回 (per, [state, ...])：块 b 的起点 state（b=0 用 _RNG_START）。
    """
    per = -(-len(seqs) // n_blocks)
    ng, _, _, _ = load_version("16.0")
    ng.rng.bit_generator.state = copy.deepcopy(_RNG_START)
    bnds = []
    for i, seq in enumerate(seqs):
        for _ in range(2 * len(seq) + 4):
            ng.rng.random(ng.n)
        if (i + 1) % per == 0 and (i + 1) < len(seqs):
            bnds.append(copy.deepcopy(ng.rng.bit_generator.state))
    return per, bnds


def _learn_block(args):
    """单块 worker：从快照 + rng state 喂一块句子 → 返回学习后全量边数组。

    不做块内 diff（省 before 快照内存）：增量由主进程对基线数组计算。
    """
    state, block = args
    ng, _, pats, _ = load_version("16.0")
    ng.rng.bit_generator.state = copy.deepcopy(state)
    for seq in block:
        _learn_sentence(ng, seq, pats, slot=0)
    return _snap(ng)


def _key_of(src, slot, dst, n, slots):
    """(i,k,j) → int64 复合键（排序合并用）。"""
    return (src.astype(np.int64) * slots + slot) * n + dst


def _merge_chunks(base, afters, n, slots, w_max):
    """数组级合并：基线 + 各块学习后 → 最终边数组。

    每块学习后值 = 基线值 + 该块增量（STDP/Hebbian 只增不减、每步 w_max 截断）
    → 增量 = after - base（键对齐，基线缺失的边视为 0），最终 = min(基线+Σ增量, w_max)。
    返回 (src_i, slot_k, dst_j, vals)，按 (i,k,j) 升序。
    """
    sb, kb_, db, vb = base
    key_b = _key_of(sb, kb_, db, n, slots)
    dk_all, dv_all = [], []
    for aft in afters:
        s, k_, d, v = aft
        key_a = _key_of(s, k_, d, n, slots)
        idx = np.searchsorted(key_b, key_a)
        hit = idx < len(key_b)
        safe = np.minimum(idx, len(key_b) - 1)
        matched = hit & (key_b[safe] == key_a)
        dv = np.where(matched, v - vb[safe], v)
        dk_all.append(key_a)
        dv_all.append(dv)
    if dk_all:
        allk = np.concatenate(dk_all)
        allv = np.concatenate(dv_all)
        order = np.argsort(allk, kind="stable")
        allk, allv = allk[order], allv[order]
        starts = np.concatenate([[0], np.flatnonzero(np.diff(allk) != 0) + 1])
        dk_u = allk[starts]
        sumv = np.add.reduceat(allv, starts)
    else:
        dk_u = np.empty(0, np.int64)
        sumv = np.empty(0, np.float64)
    fk = np.concatenate([key_b, dk_u]) if len(dk_u) else key_b
    fv = np.concatenate([vb, sumv]) if len(sumv) else vb
    order = np.argsort(fk, kind="stable")
    fk, fv = fk[order], fv[order]
    starts = np.concatenate([[0], np.flatnonzero(np.diff(fk) != 0) + 1])
    fk_u = fk[starts]
    sum2 = np.add.reduceat(fv, starts)
    sum2 = np.minimum(sum2, w_max)
    ki = fk_u // n
    src_f = (ki // slots).astype(np.int32)
    slot_f = (ki % slots).astype(np.int8)
    dst_f = (fk_u % n).astype(np.int32)
    return src_f, slot_f, dst_f, sum2


def learn_chunks(ng, pats, seqs, chunks):
    """切块并行喂散文：rng state 传递 → 各块学习后数组 → 数组级合并重建。返回 (边数, 耗时)。"""
    t1 = time.time()
    per, bnds = rng_boundaries(seqs, chunks)
    blocks = []
    for b in range(chunks):
        s, e = b * per, min((b + 1) * per, len(seqs))
        blocks.append((_RNG_START if b == 0 else bnds[b - 1], seqs[s:e]))
    print(f"  [切块] {chunks} 块（每块 {per} 句），各块独立进程…")
    base = _snap(ng)
    with ProcessPoolExecutor(max_workers=chunks) as ex:
        afters = list(ex.map(_learn_block, blocks))
    print(f"  [切块] 各块学习完成，数组级合并（基线 {len(base[0])} 边）…")
    src_f, slot_f, dst_f, val_f = _merge_chunks(base, afters, ng.n, ng.slots, ng.w_max)
    _rows_from_arrays(ng, src_f, slot_f, dst_f, val_f)
    dt = time.time() - t1
    print(f"  [切块] 完成：最终边 {len(val_f)}，耗时 {dt:.0f}s")
    return len(val_f), dt


def verify_chunk_eq(seqs, n_blocks=2):
    """对拍铁律：切块 ≡ 串行（smoke 规模逐边）。返回是否完全等价。"""
    ng0, _, pats0, _ = load_version("16.0")

    def run_serial(seqs):
        ng, _, pats, _ = load_version("16.0")
        ng.rng.bit_generator.state = copy.deepcopy(_RNG_START)
        for seq in seqs:
            _learn_sentence(ng, seq, pats, slot=0)
        return _snap(ng)

    def run_chunks(seqs, n_blocks):
        per, bnds = rng_boundaries(seqs, n_blocks)
        base = _snap(ng0)
        afters = []
        for b in range(n_blocks):
            s, e = b * per, min((b + 1) * per, len(seqs))
            afters.append(_learn_block((_RNG_START if b == 0 else bnds[b - 1],
                                        seqs[s:e])))
        return _merge_chunks(base, afters, ng0.n, ng0.slots, ng0.w_max)

    eA = run_serial(seqs)
    eB = run_chunks(seqs, n_blocks)
    kA = _key_of(eA[0], eA[1], eA[2], ng0.n, ng0.slots)
    kB = _key_of(eB[0], eB[1], eB[2], ng0.n, ng0.slots)
    if len(kA) != len(kB) or not np.array_equal(kA, kB):
        print("[等价性] ❌ 键集合不一致——切块不等价")
        return False
    ndiff = int(np.count_nonzero(np.abs(eA[3] - eB[3]) > 1e-9))
    total = len(kA)
    print(f"[等价性] 边总数 {total}，一致 {total - ndiff}"
          f"{' ✅ 切块 ≡ 串行' if ndiff == 0 else ' ❌ 差异 ' + str(ndiff)}")
    return ndiff == 0


def main():
    smoke = "--smoke" in sys.argv
    chunks = 4 if "--chunks" not in sys.argv else max(
        1, int(sys.argv[sys.argv.index("--chunks") + 1]))
    verify_chk = "--verify-chunk" in sys.argv
    t0 = time.time()
    print("═══ v17 训练管线：先见后教（散文先见 → 166 条后教 → 校准 → 验收）═══\n")

    # ── 1. 加载 v16.0（v17 的起点）────────────────────────────
    ng, vocab, pats, cursor = load_version("16.0")
    global _RNG_START
    _RNG_START = copy.deepcopy(ng.rng.bit_generator.state)
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    print(f"[加载] v16.0：n={ng.n}，词表 {len(keys)}，cursor={cursor}")

    # ── 2. 散文句收集（词表内过滤）────────────────────────────
    print("[散文] 收集词表内序列…")
    seqs, per_book = collect_prose_seqs(keys, smoke=smoke)
    print(f"  合计可喂 {len(seqs)} 句")

    # ── 2.5 切块等价性对拍（smoke 规模实拍，对拍铁律）────────
    if verify_chk:
        print(f"\n[等价性] 切块 ≡ 串行 对拍（{min(len(seqs), 300)} 句、2 块）…")
        ok = verify_chunk_eq(seqs[:300], n_blocks=2)
        if not ok:
            print("  ❌ 切块不等价——回退逐句串行")
            chunks = 1

    # ── 3. 阶段 A：先见（喂散文，纯暴露）──────────────────────
    print(f"\n[先见] 喂散文 {len(seqs)} 句"
          f"（{'切 %d 块并行' % chunks if chunks > 1 else '逐句串行'}）…")
    if chunks > 1 and len(seqs) > 500:
        learn_chunks(ng, pats, seqs, chunks)
    else:
        t1 = time.time()
        for i, seq in enumerate(seqs):
            _learn_sentence(ng, seq, pats, slot=0)
            if (i + 1) % 500 == 0:
                print(f"    {i + 1}/{len(seqs)}（{time.time() - t1:.0f}s）")
        print(f"  [逐句] 完成，耗时 {time.time() - t1:.0f}s")

    # ── 4. 阶段 B：散文暴露后的分句接话（看碾压程度）───────────
    from _grow_v16 import DOMAIN_WORDS
    domain = sorted(w for w in DOMAIN_WORDS if w in pats)
    print("\n[散文后·修正前]（预期被碾压——先见就是会砸掉专门边）")
    rows_b, nb, totb = chain_generate(ng, pats, n2w, domain)
    rate_b = nb / totb if totb else 0.0
    print(f"  [散文后] 命中 {nb}/{totb} = {rate_b:.3f}（v16 基线 0.895）")

    # ── 5. 阶段 C：后教（166 条 ×R_S 轮把目标边拉回）──────────
    rows_data = json.loads((DATA / "stage3_rel_v3.json").read_text(
        encoding="utf-8"))
    print(f"\n[后教] {len(rows_data)} 条 ×{R_S} 轮 = {len(rows_data) * R_S} 次学习")
    t2 = time.time()
    for r in rows_data:
        for _ in range(R_S):
            _learn_sentence(ng, r["tokens"], pats, slot=0)
    print(f"  [后教] 完成，耗时 {time.time() - t2:.0f}s")

    rows_c, nc, totc = chain_generate(ng, pats, n2w, domain)
    rate_c = nc / totc if totc else 0.0
    print(f"  [后教后·修正前] 命中 {nc}/{totc} = {rate_c:.3f}"
          f"（v16 基线 0.895，v17 目标 ≥0.95）")

    # ── 6. 阶段 D：校准（教师批改，看后教后还需几处）──────────
    print("\n[校准]（后教后仍需几处教师批改？）")
    fixes = calibrate(ng, pats, n2w, domain)
    print(f"  [校准] 共 {len(fixes)} 处（v16 是 1 处，v17 目标 ≤1 处）")

    rows_d, nd, totd = chain_generate(ng, pats, n2w, domain)
    rate_d = nd / totd if totd else 0.0
    print(f"  [校准后] 命中 {nd}/{totd} = {rate_d:.3f}")

    # ── 7. 结论判读（v17 验收口径）─────────────────────────────
    print("\n[判读]")
    print(f"  散文后修正前 {rate_b:.3f}（碾压程度 = 0.895 - {rate_b:.3f}"
          f" = {0.895 - rate_b:.3f}）")
    ok_rate = round(rate_c, 3) >= 0.95
    ok_cal = len(fixes) <= 1
    print(f"  后教后修正前 {rate_c:.3f} vs v17 目标 0.95"
          f"（{'≥ 0.95 ✅' if ok_rate else '< 0.95 ❌ 教学量不够'}）")
    print(f"  后教后校准 {len(fixes)} 处 vs v17 目标 ≤1 处"
          f"（{'≤ 1 处 ✅' if ok_cal else '> 1 处 ❌ 教学量不够'}）")

    # ── 8. 快照 v17.0（smoke 不存）＋ 落档 ─────────────────────
    all_ok = bool(ok_rate and ok_cal)
    out_dir = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_probe_expose_prose"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "tag": "v17 训练管线（散文先见 → 166 条后教 → 校准 → 验收）",
        "base": "16.0", "smoke": smoke, "chunks": chunks,
        "per_book": per_book, "prose_seqs": len(seqs),
        "stageB_prose_only": {"hits": nb, "tot": totb, "rate": round(rate_b, 3)},
        "stageC_post_teach": {"hits": nc, "tot": totc, "rate": round(rate_c, 3),
                              "chain": rows_c},
        "stageD_cal": {"fixes": fixes, "hits": nd, "tot": totd,
                       "rate": round(rate_d, 3), "chain": rows_d},
        "baseline_v16": {"rate_pre_cal": 0.895, "cal_fixes": 1},
        "target_v17": {"rate_pre_cal_min": 0.95, "cal_fixes_max": 1},
        "all_ok": all_ok,
        "sec": round(time.time() - t0, 1),
    }
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False,
                                                    indent=1), encoding="utf-8")
    print(f"\n[留档] {out_dir / 'result.json'}（{time.time() - t0:.0f}s）")

    if not smoke:
        metrics = {"stage3_v17": True, "data_n": len(rows_data),
                   "data_src": {src: sum(1 for r in rows_data
                                         if r["source"] == src)
                                for src in ["短文·真实", "对话·构造", "短文·构造"]},
                   "prose_seqs": len(seqs), "chunks": chunks,
                   "prose_only_rate": round(rate_b, 3),
                   "post_teach_rate": round(rate_c, 3),
                   "cal_fixes": fixes, "post_cal_rate": round(rate_d, 3),
                   "all_ok": all_ok}
        save_snapshot(ng, parent="16.0",
                      tag="Stage 3 v17：先见后教 + 数据扩量 166 条 + 并发训练"
                          "（鲁迅 5 本散文全量先见 → 教学拉回 → 校准）",
                      metrics=metrics, vocab=vocab, pats=pats, cursor=cursor)
        print(f"  [验收] 修正前 {rate_c:.3f}（目标 ≥0.95）| 校准 {len(fixes)} 处"
              f"（目标 ≤1）| {'全部通过 ✅ 快照 v17.0' if all_ok else '有失败 ❌ 快照仍已落'}")
    else:
        print("\n  [smoke] 不存快照（机制验证）")


if __name__ == "__main__":
    main()
