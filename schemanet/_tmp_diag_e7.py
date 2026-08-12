# -*- coding: utf-8 -*-
"""E7 输入表示瓶颈判别：crc32 哈希 vs 语义嵌入（bge-small-zh + z-score top-k）。

E7-1 主对照：seed=42，同语料/同网络/同评估口径，唯一变量 = 模式生成器
  → 三路（wsum/trace/grad）top-1 + PPL（复用 _paper_eval 管线）
E7-2 语义迁移：A 组训练词（猫/狗/鸡…）→ B 组近义词（猪/兔/鹿…）模式重叠 + 动态唤起
  → 哈希 ≈0，语义 >0 ⇒ 表示携带语义结构（铁证）

用法：python _tmp_diag_e7.py [--quick]  （--quick 跳过 E7-1 只做 E7-2）
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")

from schema_net import _word_pattern, _learn_sentence  # noqa: E402
from sparse_net import (SparseSchemaNet, evaluate_wsum_smat,  # noqa: E402
                        evaluate_trace_smat, build_pulse)
from _paper_eval import (N, K, MAXLEN, load_corpus, train_schemanet,  # noqa: E402
                         ppl_wsum, ppl_trace, ppl_grad, SEED_DEF,
                         EVAL_SUB_TRAIN, EVAL_SUB_TEST, SCAN_SUB)

EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
CACHE = Path("runs/_e7_semantic_cache.npz")
DIR_SEED = 777  # 随机方向 rng（固定可复现）

# ── 语义模式生成器（复刻 EMBER z-score top-k）────────────────────────
_enc = None


def _get_encoder():
    """transformers 直连加载 BGE（mean pooling + L2 归一化，与 sentence-transformers 的
    bge 默认池化一致），避免依赖 sentence-transformers。"""
    global _enc
    if _enc is None:
        import torch
        from transformers import AutoModel, AutoTokenizer
        _tok = AutoTokenizer.from_pretrained(EMBED_MODEL, local_files_only=True)
        _m = AutoModel.from_pretrained(EMBED_MODEL, local_files_only=True)
        _m.eval()

        def _encode(words):
            with torch.no_grad():
                inp = _tok(words, padding=True, truncation=True,
                           max_length=64, return_tensors="pt")
                out = _m(**inp)
                emb = out.last_hidden_state.mean(dim=1)          # mean pooling
                emb = torch.nn.functional.normalize(emb, p=2, dim=1)
            return emb.numpy().astype(np.float32)

        _enc = _encode
    return _enc


def build_semantic_pats(vocab, n=N, k=K, seed=DIR_SEED, cache_tag=None):
    """{word: sorted 神经元 id}。嵌入 → cos 到 n 个随机单位方向 → z 标准化 → top-k。

    cache_tag：非 None 时用独立缓存文件（E7-2b 小网络 n/k 与 E7-1 不同，
    模式空间不同，不能复用同一缓存——否则返回错误维度的神经元 id）。"""
    cache = {}
    cache_file = CACHE if cache_tag is None else CACHE.with_name(f"_e7_semantic_{cache_tag}.npz")
    if cache_file.exists():
        try:
            c = np.load(cache_file, allow_pickle=True)
            cache = dict(c["cache"].item())
        except Exception:  # noqa: BLE001
            cache = {}
    missing = [w for w in vocab if w not in cache]
    if missing:
        enc = _get_encoder()
        emb = np.asarray(enc(missing), dtype=np.float32)
        emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-12)
        rng = np.random.default_rng(seed)
        dirs = rng.standard_normal((n, emb.shape[1]))
        dirs = dirs / (np.linalg.norm(dirs, axis=1, keepdims=True) + 1e-12)
        cos = emb @ dirs.T                       # (m, n)
        mu = cos.mean(axis=1, keepdims=True)
        sigma = cos.std(axis=1, keepdims=True) + 1e-12
        z = (cos - mu) / sigma
        topk = np.argpartition(z, -k, axis=1)[:, -k:]   # top-k 索引
        for i, w in enumerate(missing):
            top = topk[i]
            top = top[np.argsort(z[i][top])][::-1]
            cache[w] = np.sort(top).tolist()
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        np.savez(cache_file, cache=cache)
    return {w: cache[w] for w in vocab}


def sem_fn_factory(vocab):
    pats = build_semantic_pats(vocab)
    return lambda n, k, w: pats[w]


# ── E7-1 主对照 ──────────────────────────────────────────────────────
def run_cond(tag, pats_fn):
    """复刻 _paper_eval.main_single 的评估口径，返回 result dict。"""
    t0 = time.time()
    print(f"── {tag} ──", flush=True)
    train_toks, test_toks, vocab, vocab_idx = load_corpus(SEED_DEF)
    unk_ids = {vocab_idx["<UNK>"]} if "<UNK>" in vocab_idx else set()
    rng_scan = np.random.default_rng(SEED_DEF + 9002)
    scan_toks = [test_toks[i] for i in
                 rng_scan.choice(len(test_toks), min(SCAN_SUB, len(test_toks)), replace=False)]
    r = train_schemanet(train_toks, vocab, SEED_DEF, scan_toks=scan_toks, pats_fn=pats_fn)
    ng, ro, S, outsum, delta_off = (r["ng"], r["ro"], r["S"], r["outsum"], r["delta_off"])
    print(f"  Hebbian {r['timing']['hebbian']}s | sleep {r['timing']['sleep']}s "
          f"| train_w {r['timing']['train_w']}s | delta_off={delta_off}", flush=True)

    rng = np.random.default_rng(SEED_DEF + 9001)
    ev_tr = [train_toks[i] for i in
             rng.choice(len(train_toks), min(EVAL_SUB_TRAIN, len(train_toks)), replace=False)]
    ev_te = [test_toks[i] for i in
             rng.choice(len(test_toks), min(EVAL_SUB_TEST, len(test_toks)), replace=False)]

    w_tr = evaluate_wsum_smat(S, vocab, ev_tr, norm_base=outsum)
    w_te = evaluate_wsum_smat(S, vocab, ev_te, norm_base=outsum)
    t_tr = evaluate_trace_smat(ng, ev_tr, S, r["pats"], vocab, outsum, delta_off=delta_off)
    t_te = evaluate_trace_smat(ng, ev_te, S, r["pats"], vocab, outsum, delta_off=delta_off)
    g_tr = ro.evaluate_w(ev_tr)
    g_te = ro.evaluate_w(ev_te)
    print(f"  top-1: wsum {w_tr[0]:.4f}/{w_te[0]:.4f}  trace {t_tr[0]:.4f}/{t_te[0]:.4f}  "
          f"grad {g_tr[0]:.4f}/{g_te[0]:.4f}", flush=True)

    ppl = {}
    ppl["wsum"] = ppl_wsum(S, outsum, ev_te, vocab, vocab_idx, unk_ids)
    ppl["trace"] = ppl_trace(ng, S, outsum, ev_te, r["pats"], vocab, vocab_idx, unk_ids, delta_off)
    ppl["grad"] = ppl_grad(ro, ev_te, vocab, vocab_idx, unk_ids, use_w=True)
    for kk, (a, nu, na, nn) in ppl.items():
        print(f"  PPL[{kk}]: all {a:.1f} / no-unk {nu:.1f} (n={na})", flush=True)

    return {
        "tag": tag, "seed": SEED_DEF,
        "top1": {"wsum": {"train": w_tr[0], "test": w_te[0]},
                 "trace": {"train": t_tr[0], "test": t_te[0]},
                 "grad": {"train": g_tr[0], "test": g_te[0]}},
        "ppl": {kk: {"all": float(v[0]), "no_unk": float(v[1]), "n": v[2]}
                for kk, v in ppl.items()},
        "w_reward_nnz": r["timing"]["nnz_post"], "elapsed_sec": round(time.time() - t0, 1),
    }


# ── E7-2 语义迁移 ────────────────────────────────────────────────────
GROUP_A = ["猫", "狗", "鸡", "牛", "马", "羊", "鸟", "鱼"]
GROUP_B = ["猪", "兔", "鹿", "狐", "狼", "鼠", "蛇", "蛙"]
TEMPLATES = ["这只X很可爱", "我看见一只X", "X在门口", "我喜欢X", "X跑得很快"]


def overlap_rate(pats_a, pats_b, n=N, k=K):
    """A-B 组模式平均神经元重叠率。哈希随机期望 = k²/n；语义应显著更高。"""
    rows = []
    for wa in GROUP_A:
        for wb in GROUP_B:
            sa, sb = set(pats_a[wa]), set(pats_b[wb])
            rows.append(len(sa & sb) / k)
    return float(np.mean(rows)), float(np.std(rows))


def evo_dynamic_migration(pats_fn, n=2048, k=8, rounds=3):
    """小规模 Hebbian：训练 A 组模板句 → 注入 B 词，测 A 词模式唤起率。
    返回 (train 句数, 唤起率%)。"""
    rng = np.random.default_rng(42)
    ng = SparseSchemaNet(n=n, slots=1, theta=1.0, membrane_decay=0.9, eta=0.1,
                         w_max=16.0, wta_k=k, noise_p=0.0, noise_amp=0.0,
                         refractory=1, stdp_pre=0.5, rng=rng)
    # 词模式（用同一生成器逻辑，接口 n/k 不同）
    all_words = set(GROUP_A) | set(GROUP_B)
    for t in TEMPLATES:
        all_words |= set(t.replace("X", ""))
    all_words = [w for w in all_words if w]
    base = pats_fn(n, k, "猫")   # 探针：确保 fn 支持任意 n/k
    pats = {w: pats_fn(n, k, w) for w in all_words}

    # 训练：模板 × A 组词（句子级 token 序列）
    train_sents = [t.replace("X", w) for w in GROUP_A for t in TEMPLATES] * rounds
    for sent in train_sents:
        ng.da = 1.0
        toks = [c for c in sent if c in pats]
        if len(toks) < 2:
            continue
        _learn_sentence(ng, toks, pats, slot=0)
    ng.learn_gate = False

    # 测试：注入 B 词脉冲 → 追踪 A 词模式发放
    a_mask = np.zeros(n, dtype=bool)
    for w in GROUP_A:
        a_mask[pats[w]] = True
    hits = total = 0
    for wb in GROUP_B:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        for step in range(3):
            pulse = build_pulse(n, pats[wb]) if step == 0 else np.zeros(n)
            ng.step(pulse, slot=0)
        if bool(np.any(ng.spikes[a_mask])):
            hits += 1
        total += 1
    return len(train_sents), hits / total * 100.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="跳过 E7-1，只跑 E7-2")
    args = ap.parse_args()

    print("═══ E7 输入表示瓶颈判别 ═══", flush=True)

    # E7-2 静态重叠（无需嵌入模型的对照组哈希可直接算；语义需要加载模型）
    print("\n【E7-2a 静态重叠】A 组(训练) × B 组(测试) 模式神经元重叠率（期望：哈希=k²/n）")
    print(f"  随机期望重叠率 = {K*K/N:.4f}")
    # 哈希重叠（用 _word_pattern）
    ha = {w: _word_pattern(N, K, w) for w in GROUP_A + GROUP_B}
    o_h, sd_h = overlap_rate(ha, ha)
    print(f"  哈希: overlap={o_h:.4f}±{sd_h:.4f}")

    # 语义重叠
    if not args.quick:
        sem_vocab = list(GROUP_A) + list(GROUP_B)
        sem = build_semantic_pats(sem_vocab)
        o_s, sd_s = overlap_rate(sem, sem)
        print(f"  语义: overlap={o_s:.4f}±{sd_s:.4f}")

    # E7-1 主对照（哈希 vs 语义 完整管线）
    if not args.quick:
        print("\n【E7-1 主对照】seed=42 完整管线（Hebbian→sleep→train_w→三路评估）")
        res = {}
        res["hash"] = run_cond("哈希(crc32)", _word_pattern)
        sem_fn = sem_fn_factory(_load_vocab())
        res["semantic"] = run_cond("语义(bge+zscore)", sem_fn)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path("runs") / f"paper_e7_{ts}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "result.json").write_text(
            json.dumps({"version": "e7-v1", "group_overlap": {"hash": o_h, "semantic": o_s},
                        "cond": res}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"留档: {out_dir}/")
    else:
        print("\n[--quick] 跳过 E7-1 主对照")

    # E7-2b 动态迁移（小网络，两种编码）
    print("\n【E7-2b 动态迁移】训练 A 组模板句 → 注入 B 词，A 词唤起率")
    try:
        n_dyn, rate_h = evo_dynamic_migration(
            lambda n, k, w: _word_pattern(n, k, w), n=2048, k=8)
        print(f"  哈希: train {n_dyn} 句, B→A 唤起率 {rate_h:.1f}%")
    except Exception as e:  # noqa: BLE001
        print(f"  哈希动态迁移失败: {e}")

    # E7-2b 语义动态迁移（小网络 n=2048/k=8，独立构建词汇表与缓存）
    # 修复（2026-08-12）：此前 build_semantic_pats 只对 corpus_open 词表构建，
    # 而 A 组词（猫/狗…）不在词表 → KeyError '猫'；且默认 N/K 与 evo 小网络
    # 不匹配（8192/16 的神经元 id 会越 2048 边界）。现按 evo 参数重建 + 并入
    # A∪B 组词与模板字，并用独立缓存（_e7_semantic_dyn.npz）避免污染 E7-1。
    try:
        dyn_vocab = list(set(_load_vocab()) | set(GROUP_A) | set(GROUP_B)
                         | set("".join(TEMPLATES).replace("X", "")))
        sem_dyn = build_semantic_pats(dyn_vocab, n=2048, k=8, cache_tag="dyn2048k8")
        n_dyn, rate_s = evo_dynamic_migration(
            lambda n, k, w: sem_dyn[w], n=2048, k=8)
        print(f"  语义: train {n_dyn} 句, B→A 唤起率 {rate_s:.1f}%")
    except Exception as e:  # noqa: BLE001
        print(f"  语义动态迁移失败: {e}")


def _load_vocab():
    _, _, vocab, _ = load_corpus(SEED_DEF)
    return vocab


if __name__ == "__main__":
    main()
