# -*- coding: utf-8 -*-
"""候选 B/C 读出引擎 + 主题保持/切换测试（基于 score 全表 S[V,V]）。

候选 B 精度加权（预测编码）：来源信任 ∝ 该来源条件分布的尖锐度（1/熵）。
   分布尖锐 = 强转移定式 = 可信；分布平 = 不可信 → 动态来源信任（非固定位置信任）。
   公式：logits = S_norm[:, last] + Σ_nonlast w_b × sharp_norm(src) × S_norm[:, src]

候选 C 话题焦点门控（自上而下）：主题词（转移中心性高）痕迹额外激活。
   中心性 = 该词作为来源的转移总量（S 列和），归一化。
   trace 的非末词权重 × (1 + β×cent_norm(src))，其余完全同 trace →
   内容级"留主题、丢细节"（内容压缩式遗忘的雏形）。

主题保持/切换测试：同主题异细节对句应预测一致（压缩，JS 应小），
   异主题同末词对句应预测不同（区分，JS 应大）。
   指标 = JS(切换对) − JS(保持对)：越大 = 越接近"内容压缩式遗忘"。
"""
from collections import Counter

import numpy as np

from schema_net import build_pulse
from _accept_scale20w import GRP_TAGS, gname


# ── 统计量（冻结 W，离线预计算）─────────────────────────────────────

def col_entropy(col):
    """条件分布（score 列）的熵：尖锐=小，平=大。"""
    x = col - float(col.max())
    e = np.exp(x)
    s = float(e.sum())
    p = e / s if s > 0 else e
    return -float((p * np.log(p + 1e-12)).sum())


def sharpness(S_norm):
    """每词作为来源的分布尖锐度（1/熵），归一化到和=1（V 维）。"""
    V = S_norm.shape[1]
    sh = np.array([1.0 / (col_entropy(S_norm[:, w]) + 1e-6) for w in range(V)])
    s = float(sh.sum())
    return sh / s if s > 0 else sh


def centrality(S):
    """每词作为来源的转移中心性 = S 列和（该词指向多少转移强度），归一化 [0,1]。"""
    c = S.sum(axis=0)
    m = float(c.max())
    return c / m if m > 0 else c


# ── 主题注意力（Topic Attention, TA）：查询-键匹配（真正注意力）────────

def _col_norm_cols(M):
    """按列 L2 归一化（每列为单位向量）。"""
    n = np.linalg.norm(M, axis=0)
    return M / n[None, :] if float(n.max()) > 0 else M


def ta_logits(S_norm, prefix_ids, tau=2.0, decay=0.3, residual=0.0):
    """主题注意力 logits（零训练，只用 W 列）。

    查询 q = 前缀位置转移分布的加权平均（位置权重 exp(-decay·pos)，近端高）；
    键   = 每个历史位置的转移分布列；
    α    = softmax(τ·cos(q, 列))——与主题相似的词被记住，不相似的被遗忘；
    logits = Σ α·列（residual>0 时叠加末词列 residual 倍，保底末词信号）。

    同末词、异前缀 → q 不同 → α 不同 → logits 不同（这是 trace/grad/candB/C
    的静态权重做不到的：它们对同末词组内所有样本给同一权重分布）。
    """
    L = len(prefix_ids)
    cols = S_norm[:, prefix_ids]                      # (V, L)
    pos_w = np.exp(-decay * np.arange(L)[::-1])       # 末词 pos=0 → 权重最高
    pos_w = pos_w / pos_w.sum()
    q = cols @ pos_w                                  # (V,)
    qn = q / (np.linalg.norm(q) + 1e-12)
    cols_n = _col_norm_cols(cols)
    sim = cols_n.T @ qn                               # (L,)
    e = np.exp(tau * (sim - sim.max()))
    a = e / e.sum()                                   # 注意力权重
    logits = cols @ a
    if residual > 0:
        logits = logits + residual * cols[:, -1]
    return logits


def eval_ta_g(S_norm, vocab, toks_list, tau=2.0, decay=0.3, residual=0.0):
    """主题注意力位置分层 top-1（同 GRPS 口径）。"""
    vtab = {w: i for i, w in enumerate(vocab)}
    hits, total = Counter(), Counter()
    for toks in toks_list:
        ids = [vtab[w] for w in toks if w in vtab]
        for t in range(1, len(ids)):
            logits = ta_logits(S_norm, ids[:t], tau, decay, residual)
            used = set(ids[:t])
            order = np.argsort(-logits)
            cand = next((wi for wi in order if logits[wi] > 0 and wi not in used),
                        None)
            g = gname(t)
            total[g] += 1
            if cand is not None and vocab[cand] == toks[t]:
                hits[g] += 1
    return {GRP_TAGS[i]: (hits[i] / total[i] if total[i] else None)
            for i in range(len(GRP_TAGS))}, int(sum(total.values()))


# ── 候选 B：精度加权（纯统计读出，无需网络状态）─────────────────────

def cand_b_logits(S_norm, sharp, prefix_ids, w_b=0.5):
    """候选 B logits：末词 1.0 + 非末词按尖锐度加权（总权重 w_b）。"""
    Ln = len(prefix_ids)
    if Ln == 1:
        return S_norm[:, prefix_ids[0]].copy()
    sh = sharp[prefix_ids[:-1]]
    s = float(sh.sum())
    w = (sh / s) * w_b if s > 0 else np.zeros_like(sh)
    logits = S_norm[:, prefix_ids[-1]].copy() + S_norm[:, prefix_ids[:-1]] @ w
    return logits


def eval_cand_b_g(S_norm, sharp, vocab, toks_list, w_b=0.5):
    """候选 B 位置分层 top-1（同 GRPS 口径）。"""
    vtab = {w: i for i, w in enumerate(vocab)}
    hits, total = Counter(), Counter()
    for toks in toks_list:
        ids = [vtab[w] for w in toks if w in vtab]
        for t in range(1, len(ids)):
            logits = cand_b_logits(S_norm, sharp, ids[:t], w_b)
            used = set(ids[:t])
            order = np.argsort(-logits)
            cand = next((wi for wi in order if logits[wi] > 0 and wi not in used),
                        None)
            g = gname(t)
            total[g] += 1
            if cand is not None and vocab[cand] == toks[t]:
                hits[g] += 1
    return {GRP_TAGS[i]: (hits[i] / total[i] if total[i] else None)
            for i in range(len(GRP_TAGS))}, int(sum(total.values()))


# ── 候选 C：话题焦点门控（trace + 中心性增强）────────────────────────

def eval_cand_c_g(ng, toks_list, S, S_norm, pats, vocab, norm_base, delta_off,
                  cent_norm, beta=2.0):
    """候选 C 位置分层 top-1：非末词 wgt ×= (1 + β×cent_norm)，其余同 trace。"""
    vtab = {w: i for i, w in enumerate(vocab)}
    V = len(vocab)
    hits, total = Counter(), Counter()
    norm_arr = np.zeros(V)
    for wi, w in enumerate(vocab):
        norm_arr[wi] = norm_base.get(w, 0.0) if norm_base else 0.0
    for toks in toks_list:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.refractory_left = np.zeros(ng.n, dtype=int)
        ng.last_k_star = np.zeros(ng.n, dtype=int)
        for t in range(1, len(toks)):
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(build_pulse(ng.n, pats[toks[t - 1]]), slot=0)
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(np.zeros(ng.n), slot=0)
            last = toks[t - 1]
            p_last = S[:, vtab[last]].copy()
            den = norm_arr[vtab[last]]
            if den > 0:
                p_last /= den
            used = set(toks[:t])
            order = np.argsort(-p_last)
            top_idx = [wi for wi in order if p_last[wi] > 0 and vocab[wi] not in used]
            if len(top_idx) >= 2 and p_last[top_idx[0]] - p_last[top_idx[1]] >= delta_off:
                cands = [(vocab[wi], round(float(p_last[wi]), 6)) for wi in top_idx]
            else:
                last_pats = pats[last]
                trace_last = float(np.max(ng.pre_trace[last_pats])) if last_pats else 0.0
                cnt_last = toks[:t].count(last)
                mix = 0.9 * cnt_last * p_last
                for i, w in enumerate(toks[:t]):
                    if w == last:
                        continue
                    pw = pats[w]
                    if not pw:
                        continue
                    tr = float(np.max(ng.pre_trace[pw]))
                    if tr <= 0:
                        continue
                    wi = vtab[w]
                    p = S[:, wi].copy()
                    den = norm_arr[wi]
                    if den > 0:
                        p /= den
                    wgt = 0.1 * tr * (1.0 + beta * cent_norm[wi])
                    if trace_last > 0:
                        wgt /= trace_last
                    mix += wgt * p * toks[:t].count(w)
                cands = [(vocab[wi], round(float(mix[wi]), 6)) for wi in range(V)
                         if mix[wi] > 0 and vocab[wi] not in used]
                cands.sort(key=lambda x: -x[1])
            pred = cands[0][0] if cands else None
            g = gname(t)
            total[g] += 1
            if pred == toks[t]:
                hits[g] += 1
    return {GRP_TAGS[i]: (hits[i] / total[i] if total[i] else None)
            for i in range(len(GRP_TAGS))}, int(sum(total.values()))


# ── 主题保持/切换测试（内容压缩式遗忘）────────────────────────────────

def _js(p, q):
    """JS 散度（p, q 为概率向量，V 维，含零）。"""
    m = 0.5 * (p + q)
    eps = 1e-12
    kl1 = float((p * np.log((p + eps) / (m + eps))).sum())
    kl2 = float((q * np.log((q + eps) / (m + eps))).sum())
    return 0.5 * (kl1 + kl2)


def _softmax_logits(logits):
    x = logits - float(np.max(logits))
    e = np.exp(x)
    s = float(e.sum())
    return e / s if s > 0 else e


def _trace_logits(ng, pats, vocab, vtab, S, norm_arr, word_list, delta_off,
                  focus=False, cent_norm=None, beta=2.0):
    """跑 trace（focus=False）或候选 C（focus=True）前缀，返回 mix logits（V 维）。"""
    ids = [vtab[w] for w in word_list if w in vtab]
    if not ids:
        return None
    V = len(vocab)
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)
    ng.refractory_left = np.zeros(ng.n, dtype=int)
    ng.last_k_star = np.zeros(ng.n, dtype=int)
    for wid in ids:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.step(build_pulse(ng.n, pats[vocab[wid]]), slot=0)
        ng.v = np.zeros((ng.n, ng.slots))
        ng.step(np.zeros(ng.n), slot=0)
    last = ids[-1]
    p_last = S[:, last].copy()
    den = norm_arr[last]
    if den > 0:
        p_last /= den
    used = set(ids)
    order = np.argsort(-p_last)
    top_idx = [wi for wi in order if p_last[wi] > 0 and wi not in used]
    if len(top_idx) >= 2 and p_last[top_idx[0]] - p_last[top_idx[1]] >= delta_off:
        return p_last
    last_pats = pats[vocab[last]]
    trace_last = float(np.max(ng.pre_trace[last_pats])) if last_pats else 0.0
    cnt_last = ids.count(last)
    mix = 0.9 * cnt_last * p_last
    for w in set(ids):
        if w == last:
            continue
        pw = pats[vocab[w]]
        if not pw:
            continue
        tr = float(np.max(ng.pre_trace[pw]))
        if tr <= 0:
            continue
        p = S[:, w].copy()
        den = norm_arr[w]
        if den > 0:
            p /= den
        wgt = 0.1 * tr * ids.count(w)
        if focus:
            wgt *= (1.0 + beta * cent_norm[w])
        if trace_last > 0:
            wgt /= trace_last
        mix += wgt * p
    return mix


def _top1(logits, vocab, used):
    order = np.argsort(-logits)
    wi = next((w for w in order if w > 0 and logits[w] > 0 and w not in used),
              None)
    return vocab[wi] if wi is not None else None


def pair_test(ng, ro, pats, vocab, S, S_norm, sharp, cent_norm, norm_base,
              pairs, delta_off, beta=2.0):
    """pairs: [(tag, 句A, 句B)]，tag ∈ keep/switch。
    打印每引擎在每对上的 top-1 + JS；返回 {引擎: 区分度差}。"""
    vtab = ro.vocab_idx
    V = len(vocab)
    norm_arr = np.zeros(V)
    for wi, w in enumerate(vocab):
        norm_arr[wi] = norm_base.get(w, 0.0) if norm_base else 0.0
    stat = {}
    for tag, sa, sb in pairs:
        ia = [vtab[w] for w in sa if w in vtab]
        ib = [vtab[w] for w in sb if w in vtab]
        if not ia or not ib:
            print(f"[{tag}] 跳过（词表外）: {' '.join(sa)} / {' '.join(sb)}")
            continue
        print(f"\n[{tag}] A={' '.join(sa)}  |  B={' '.join(sb)}")
        # 纯读出引擎（无需网络）
        ra = {}
        for eng, la in (("wsum", S_norm[:, ia[-1]].copy()),
                        ("grad", ro.logits(ia).copy()),
                        ("candB", cand_b_logits(S_norm, sharp, ia))):
            la = la.copy()
            if eng == "grad":
                la[la <= 0] = -np.inf
                for wid in ia:
                    la[wid] = -np.inf
            ra[eng] = (_top1(la, vocab, set(ia)), _softmax_logits(la))
        rb = {}
        for eng, lb in (("wsum", S_norm[:, ib[-1]].copy()),
                        ("grad", ro.logits(ib).copy()),
                        ("candB", cand_b_logits(S_norm, sharp, ib))):
            lb = lb.copy()
            if eng == "grad":
                lb[lb <= 0] = -np.inf
                for wid in ib:
                    lb[wid] = -np.inf
            rb[eng] = (_top1(lb, vocab, set(ib)), _softmax_logits(lb))
        for eng in ("wsum", "grad", "candB"):
            pa, la = ra[eng]
            pb, lb = rb[eng]
            js = _js(la, lb)
            stat.setdefault(eng, []).append((tag, js, pa == pb))
            print(f"  {eng:5s}: A→{pa:6s}  B→{pb:6s}  相同={pa == pb}  JS={js:.3f}")
        # trace / 候选 C（网络动力学）
        for eng, focus in (("trace", False), ("candC", True)):
            ma = _trace_logits(ng, pats, vocab, vtab, S, norm_arr, sa,
                               delta_off, focus, cent_norm, beta)
            mb = _trace_logits(ng, pats, vocab, vtab, S, norm_arr, sb,
                               delta_off, focus, cent_norm, beta)
            if ma is None or mb is None:
                print(f"  {eng:5s}: 跳过（词表外）")
                continue
            pa = _top1(ma, vocab, set(ia))
            pb = _top1(mb, vocab, set(ib))
            js = _js(_softmax_logits(ma), _softmax_logits(mb))
            stat.setdefault(eng, []).append((tag, js, pa == pb))
            print(f"  {eng:5s}: A→{pa:6s}  B→{pb:6s}  相同={pa == pb}  JS={js:.3f}")
    print("\n── 区分度差 = JS(切换对) − JS(保持对)（越大越接近'内容压缩式遗忘'）──")
    diff = {}
    for eng, lst in stat.items():
        js_keep = [x[1] for x in lst if x[0] == "keep"]
        js_sw = [x[1] for x in lst if x[0] == "switch"]
        d = (sum(js_sw) / len(js_sw) if js_sw else 0.0) - \
            (sum(js_keep) / len(js_keep) if js_keep else 0.0)
        diff[eng] = d
        print(f"  {eng:5s}: JS_keep={sum(js_keep)/len(js_keep):.3f}  "
              f"JS_switch={sum(js_sw)/len(js_sw):.3f}  区分度差={d:+.3f}")
    return diff
