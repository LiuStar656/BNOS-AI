# -*- coding: utf-8 -*-
"""定式网络生成器（Phase 3：生成与解码）。

定位：给定前缀 → 逐词采样生成完整句。生成引擎 = 梯度读出（Phase 4 的
GradReadout.train_w 精调后的 _logits_w），对照 Hebbian 静态读出（wsum/trace）
——诚实定位"梯度精调后的条件概率"对生成质量的实际增益。

解码策略（标准，纯 numpy 零外部依赖）：
  - top-k 采样（默认 k=20）：只保留 logits 前 k 大 → 温度 softmax → 采样
  - 温度 T（默认 0.8）：分布锐度（>1 平滑、<1 锐化）
  - 重复惩罚 penalty（默认 1.2）：对生成历史中已出现词的 logits 除以 penalty
  - 停止：达 max_len 或无有效候选（无转移信号）
  - 贪心（top_k=1 / 直接 argmax）作对照

用法：
  gen = Generator(ro, outsum)          # ro = GradReadout（已 train_w 精调）
  gen.generate(["我"])                 # 梯度读出生成
  gen.generate(["我"], engine="trace") # Hebbian trace 对照（需 outsum）
"""

import numpy as np

from sparse_net import predict_cands_wsum_sparse, predict_cands_trace_sparse


class Generator:
    """定式网络生成器：梯度读出（train_w 后）主引擎 + Hebbian 静态读出对照。

    参数：
        ro       GradReadout（已 train_w 精调，生成引擎 = ro._logits_w）
        outsum   {词: 源词出边总强度}（trace 对照的 norm_base；None 则 trace 退化为裸 wsum）
        seed     采样随机种子
    """

    def __init__(self, ro, outsum=None, seed=42):
        self.ro = ro
        self.ng = ro.ng
        self.pats = ro.pats
        self.vocab = ro.vocab
        self.vocab_idx = ro.vocab_idx
        self.outsum = outsum
        self.rng = np.random.default_rng(seed)

    # ── 引擎：三类读出的 logits 向量（V 维，量纲一致可比）─────────

    def _engine_logits(self, ids, engine):
        """返回 logits（V 维，-inf = 无转移信号）。wsum/trace 用稀疏向量化版
        （SparseSchemaNet 无稠密 W）。trace 内部走 ng.step 注入前缀更新
        pre_trace——learn_gate 冻结下不改权重，仅污染膜电位状态（只读安全）。"""
        if engine == "grad":
            logits = self.ro._logits_w(ids).copy()
        else:
            logits = np.full(len(self.vocab), -np.inf)
            prefix = [self.vocab[i] for i in ids]
            pats_mat = self.ro.pats_mat
            if engine == "wsum":
                cands = predict_cands_wsum_sparse(self.ng, prefix, self.pats,
                                                  self.vocab, pats_mat, slot=0)
            elif engine == "trace":
                cands = predict_cands_trace_sparse(self.ng, prefix, self.pats,
                                                   self.vocab, pats_mat, slot=0,
                                                   norm_base=self.outsum,
                                                   delta_off=0.02)
            else:
                raise ValueError(f"未知引擎: {engine}")
            for w, s in cands:
                logits[self.vocab_idx[w]] = s
        return logits

    # ── 单步采样 ──────────────────────────────────────────────────

    def _sample(self, logits, used_ids, top_k, temp, penalty):
        l = logits.copy()
        l[l <= 0] = -np.inf                      # 无转移信号过滤
        for wid in used_ids:                     # 重复惩罚（生成历史）
            if np.isfinite(l[wid]):
                l[wid] /= penalty
        n_valid = int(np.isfinite(l).sum())
        if n_valid == 0:
            return None
        k = min(top_k, n_valid)
        if k < n_valid:
            thr = np.partition(l, -k)[-k]        # top-k 截断
            l[l < thr] = -np.inf
        mx = float(l.max())
        ex = np.exp((l - mx) / temp)
        s = float(ex.sum())
        if s <= 0 or not np.isfinite(s):
            return None
        probs = ex / s
        return int(self.rng.choice(len(self.vocab), p=probs))

    # ── 完整生成 ──────────────────────────────────────────────────

    def generate(self, start, max_len=10, top_k=20, temp=0.8, penalty=1.2,
                 engine="grad"):
        """给定前缀词序列，逐词采样生成完整句。返回词列表（含前缀）。"""
        ids = [self.vocab_idx[w] for w in start if w in self.vocab_idx]
        if not ids:
            return []
        for _ in range(max_len - len(ids)):
            wid = self._sample(self._engine_logits(ids, engine), ids,
                               top_k, temp, penalty)
            if wid is None:
                break
            ids.append(wid)
        return [self.vocab[i] for i in ids]

    def generate_argmax(self, start, max_len=10, penalty=1.2, engine="grad"):
        """贪心生成（每步取概率最高，对照采样）。"""
        ids = [self.vocab_idx[w] for w in start if w in self.vocab_idx]
        if not ids:
            return []
        for _ in range(max_len - len(ids)):
            l = self._engine_logits(ids, engine).copy()
            l[l <= 0] = -np.inf
            for wid in ids:
                if np.isfinite(l[wid]):
                    l[wid] /= penalty
            wid = int(np.argmax(l)) if np.isfinite(l).any() else None
            if wid is None:
                break
            ids.append(wid)
        return [self.vocab[i] for i in ids]
