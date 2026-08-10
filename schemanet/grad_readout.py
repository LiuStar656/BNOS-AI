# -*- coding: utf-8 -*-
"""定式网络梯度读出层（Phase 4 可复用模块）。

定位：定式网络本体（SparseSchemaNet / schema_net.SchemaNet）是**纯动力学层**
（积分-发放 + Hebbian/STDP 教学式学习沉淀二元转移定式）。本模块是独立的
**可微读出/学习层**，持有网络引用，把"已沉淀的转移定式"变成可微的条件概率
分布，并提供稀疏梯度训练：

  前向（可微读出，4a）：
      logits[w_t] = Σ_pos ctx_wgt[pos] × score(w_t, prefix[last-pos])
      score(w, src) = Σ_{j∈pats[w]} W[j,0,src] / k
      ctx_wgt 为自由参数（信任分布，单纯形投影），W 为定式网络已沉淀的转移

  梯度训练（4b，稀疏梯度）：
      - 冻结 W 快速路径：预计算 S[V,V]（score 全表），只训 ctx_wgt
        （W 不动 → 定式零扰动，专攻"该信任哪个上下文词"）
      - 微调 W 路径：∂L/∂W 只在 W 非零处有值（梯度天然稀疏），
        更新只碰非零子集，W 结构（连接拓扑）不动 = 定式动力学保留

  4c 双轨学习门：learn_mode ∈ {hebbian, grad, dual} 由本模块编排
      hebbian = 教学式（_learn_sentence，共现/转移定式实时沉淀）
      grad    = Hebbian 预训练后冻结 learn_gate，梯度精调读出层
      dual    = hebbian 教学式 + 梯度精调交替（在线场景）

  4d 灾难性遗忘防护：snapshot_w()/restore_w()（梯度前快照、可回滚），
      nnz()/w_delta() 量化梯度对定式结构的扰动。

用法（完整验收见 _accept_grad.py）：
    ro = GradReadout(ng, pats, vocab, pats_mat)
    ro.train_ctx(positions, lr=0.5, epochs=20, seed=42)   # 冻结 W：只训 ctx_wgt
    acc, hits, total, samples = ro.evaluate(test_toks)    # top-1 评估
"""

import time

import numpy as np

from schema_net import _learn_sentence
from sparse_net import _out_edges_accum, _row_from_dict


# ════════════════════════════════════════════════════════════════
#  梯度读出层
# ════════════════════════════════════════════════════════════════

class GradReadout:
    """定式网络的可微读出/学习层（稀疏梯度，W 结构不动）。

    参数：
        ng        SparseSchemaNet（已 Hebbian 预训练，learn_gate 冻结后传入更稳）
        pats      {词: 神经元模式}
        vocab     词表列表（按频率降序，读出层维度）
        pats_mat  (V, k) 模式矩阵（_pats_matrix 的输出）
        maxlen    上下文最大长度（pos 0 = 末词）
    """

    def __init__(self, ng, pats, vocab, pats_mat, maxlen=5):
        self.ng = ng
        self.pats = pats
        self.vocab = vocab
        self.vocab_idx = {w: i for i, w in enumerate(vocab)}
        self.pats_mat = pats_mat
        self.maxlen = maxlen
        self.ctx_wgt = None     # 上下文信任分布（末词 → 远端），训练后填充
        self.S = None           # 冻结 W 快速路径的 score 全表 S[V,V]
        self.S_norm = None      # 温度归一化版（÷max，argmax 不变，稳定训练）
        self._snap = None       # W 快照（4d 灾难性遗忘防护）
        # numpy 出边镜像（训练提速：dW 累积/_apply 向量化，语义与 dict 完全等价）
        self._edge_dst = None   # 每神经元槽0出边目标数组（None=无出边）
        self._edge_w = None     # 每神经元槽0出边权重数组（镜像，_apply 后同步）
        self._edge_dirty = None # 本次训练触碰过的神经元（_apply 后需写回 dict）

    # ── 前向（冻结 W 快速路径，S 矩阵预计算）───────────────────────

    def build_score_matrix(self):
        """S[V, V]：S[w][src] = score(w, src) = Σ_{j∈pats[w]} W[j,0,src]/k。"""
        V = len(self.vocab)
        S = np.zeros((V, V))
        for si, w in enumerate(self.vocab):
            acc = _out_edges_accum(self.ng, self.pats[w], 0)
            S[:, si] = acc[self.pats_mat].sum(axis=1) / self.pats_mat.shape[1]
        self.S = S
        s_max = float(S.max())
        self.S_norm = S / s_max if s_max > 0 else S
        return S

    def logits(self, prefix_ids):
        """前向 logits（V 维，ctx_wgt 自由参数 → 单纯形投影后加权）。
        位置语义：pos0 = 末词，pos1 = 倒数第 2 词……（列反转对齐）。"""
        Ln = min(self.maxlen, len(prefix_ids))
        cw = self.ctx_wgt[:Ln]
        s = cw.sum()
        wgt = cw / s if s > 0 else cw
        cols = prefix_ids[-Ln:][::-1]  # 末词在列首，对齐 wgt[0]=末词
        return self.S_norm[:, cols] @ wgt

    # ── 训练：冻结 W，只训 ctx_wgt（exp2 快速路径）─────────────────

    def train_ctx(self, positions, lr=0.5, epochs=20, seed=42, subsample=None):
        """只训上下文信任分布。初值 = 信任末词（数据支持才拉起远端权重），
        梯度只把有统计信息的远端位置抬起来。返回训练秒数。
        subsample：每 epoch 随机抽 N 个样本（None=全量；大语料提速用）。"""
        self.build_score_matrix()
        self.ctx_wgt = np.array([1.0] + [0.0] * (self.maxlen - 1))
        t0 = time.time()
        for ep in range(epochs):
            rng = np.random.default_rng(seed + ep)
            perm = rng.permutation(len(positions))
            if subsample is not None and subsample < len(perm):
                perm = perm[:subsample]
            for idx in perm:
                pidxs, target = positions[idx]
                Ln = min(self.maxlen, len(pidxs))
                cw = self.ctx_wgt[:Ln]
                s = cw.sum()
                wgt = cw / s if s > 0 else cw
                logits = self.S_norm[:, pidxs[-Ln:]] @ wgt
                ex = np.exp(logits - logits.max())
                probs = ex / ex.sum()
                dL = probs.copy()
                dL[target] -= 1.0
                d_wgt = np.array([float(self.S_norm[:, wid] @ dL)
                                  for wid in reversed(pidxs[-Ln:])])
                nrm = float(np.linalg.norm(d_wgt))
                if nrm > 1.0:  # 梯度裁剪兜底（防 logits 尺度漂移正反馈）
                    d_wgt = d_wgt / nrm
                cw -= lr * d_wgt
                np.clip(cw, 0.0, None, out=cw)  # 就地写回（cw 是 ctx_wgt[:Ln] 视图）
                s = cw.sum()
                if s > 0:
                    cw /= s
        s = self.ctx_wgt.sum()
        if s > 0:
            self.ctx_wgt = self.ctx_wgt / s
        return round(time.time() - t0, 1)

    # ── 训练：微调 W 非零子集 + ctx_wgt（exp1 路径）────────────────

    def train_w(self, positions, lr=0.5, epochs=10, seed=42, ctx_init=None,
                subsample=None, batch_size=1):
        """梯度微调 W 非零子集（稀疏梯度，结构不动）+ ctx_wgt。
        ctx_wgt 初值：默认 trace 等效（末词 1，远端 0.05×0.5^i）；
        ctx_init 可传入 train_ctx 的结果作为起点（先快路径训位置信任，再微调 W）。
        subsample：每 epoch 随机抽 N 个样本（None=全量；大语料提速用，
        小语料/Phase 4 验收不传即保持全量行为不变）。
        batch_size：mini-batch 梯度累积（>1 时每 batch 重建一次 S 矩阵快照，
        前向/d_wgt 全走矩阵乘——在线 SGD → mini-batch SGD 语义变化，需回归验收；
        =1 保持原逐样本在线语义）。返回训练秒数。"""
        if ctx_init is not None:
            self.ctx_wgt = np.array(ctx_init, dtype=float)
        else:
            self.ctx_wgt = np.array([1.0] + [0.05 * 0.5 ** i for i in range(1, self.maxlen)],
                                    dtype=float)
        self.build_edge_mirror()   # 镜像提速（语义与 dict 等价）
        t0 = time.time()
        for ep in range(epochs):
            if batch_size > 1:
                self.build_score_matrix()   # epoch 内 W 快照（mini-batch 近似）
            rng = np.random.default_rng(seed + ep)
            perm = rng.permutation(len(positions))
            if subsample is not None and subsample < len(perm):
                perm = perm[:subsample]
            for b0 in range(0, len(perm), max(1, batch_size)):
                batch = perm[b0:b0 + max(1, batch_size)]
                d_wgt = np.zeros(self.maxlen)
                dW = {}
                for idx in batch:
                    pidxs, target = positions[idx]
                    dg, dWi, _ = self._grads(pidxs, target, use_s=bool(batch_size > 1))
                    d_wgt += dg
                    for i, gi in dWi.items():
                        tgt = dW.get(i)
                        if tgt is None:
                            dW[i] = gi.copy()
                        else:
                            tgt += gi          # ndarray 原地累积
                if len(batch) > 1:
                    # 标准 mini-batch SGD：梯度取平均（步长稳定），
                    # 学习率按 batch 线性放大 lr*B（总更新量与在线 SGD 等价）
                    d_wgt /= len(batch)
                    for i, gi in dW.items():
                        gi /= len(batch)
                    self._apply(d_wgt, dW, lr * len(batch))
                else:
                    self._apply(d_wgt, dW, lr)
        self.ctx_wgt = np.clip(self.ctx_wgt, 0.0, None)
        self.sync_edges()          # 镜像写回 dict（训练结束一次）
        return round(time.time() - t0, 1)

    # ── 评估（top-1，与 wsum/trace 同口径）─────────────────────────

    def evaluate(self, toks_list, n_samples=8):
        """冻结 W 快速路径评估（用 S_norm）。返回 (acc, hits, total, samples)。"""
        hits = total = 0
        samples = []
        for toks in toks_list:
            ids = [self.vocab_idx[w] for w in toks if w in self.vocab_idx]
            for t in range(1, len(ids)):
                logits = self.logits(ids[:t]).copy()
                logits[logits <= 0] = -np.inf  # 无转移信号 → 不参与候选
                for wid in ids[:t]:            # 排除前缀内已现词
                    logits[wid] = -np.inf
                cand_idx = int(np.argmax(logits))
                pred = self.vocab[cand_idx]
                total += 1
                if pred == toks[t]:
                    hits += 1
                elif len(samples) < n_samples:
                    order = np.argsort(-logits)
                    top3 = [self.vocab[i] for i in order[:3]]
                    samples.append({"ctx": "".join(toks[:t]), "truth": toks[t],
                                    "pred": pred, "top3": top3})
        return (hits / total if total else 0.0), hits, total, samples

    def evaluate_w(self, toks_list, n_samples=8):
        """微调 W 路径评估（逐位置前向，无 S 矩阵）。"""
        hits = total = 0
        samples = []
        for toks in toks_list:
            ids = [self.vocab_idx[w] for w in toks if w in self.vocab_idx]
            for t in range(1, len(ids)):
                logits = self._logits_w(ids[:t]).copy()
                logits[logits <= 0] = -np.inf
                for wid in ids[:t]:
                    logits[wid] = -np.inf
                cand_idx = int(np.argmax(logits))
                pred = self.vocab[cand_idx]
                total += 1
                if pred == toks[t]:
                    hits += 1
                elif len(samples) < n_samples:
                    order = np.argsort(-logits)
                    top3 = [self.vocab[i] for i in order[:3]]
                    samples.append({"ctx": "".join(toks[:t]), "truth": toks[t],
                                    "pred": pred, "top3": top3})
        return (hits / total if total else 0.0), hits, total, samples

    # ── 4c 双轨学习门：hebbian 教学式入口 ──────────────────────────

    @staticmethod
    def learn_sentence_hebbian(ng, toks, pats, slot=0):
        """hebbian 轨：教学式学习（与 schema_net._learn_sentence 同一实现）。"""
        _learn_sentence(ng, toks, pats, slot=slot)

    # ── 4d 灾难性遗忘防护：W 快照 / 恢复 / 扰动量化 ─────────────────

    def snapshot_w(self):
        """深拷贝当前 W（梯度前调用）。"""
        self._snap = [[{j: w for j, w in row.items()} for row in rows]
                      for rows in self.ng.W_out]

    def restore_w(self):
        """回滚 W 到最近快照（梯度破坏了定式时启用）。"""
        if self._snap is None:
            raise RuntimeError("GradReadout.restore_w: 无快照，先调 snapshot_w()")
        self.ng.W_out = [[_row_from_dict(d) for d in rows] for rows in self._snap]
        self.ng.invalidate_edge_cache()   # [兼容占位] 数组即事实源，无实际置脏

    def nnz(self):
        """W 非零连接总数（结构度量）。"""
        return sum(len(row) for rows in self.ng.W_out for row in rows)

    def w_delta(self):
        """与快照的扰动量化：{max_delta, n_changed, n_tot}（结构内权重改动）。"""
        if self._snap is None:
            return None
        max_d = 0.0
        n_changed = n_tot = 0
        for i, rows in enumerate(self.ng.W_out):
            for k, row in enumerate(rows):
                for j, w in row.items():
                    n_tot += 1
                    d = abs(w - self._snap[i][k].get(j, 0.0))
                    if d > 1e-9:
                        n_changed += 1
                    if d > max_d:
                        max_d = d
        return {"max_delta": round(max_d, 4), "n_changed": n_changed,
                "n_tot": n_tot}

    # ── 内部：微调 W 路径的前向/反向（稀疏梯度）────────────────────

    def build_edge_mirror(self):
        """把 W_out 槽0 出边转成 numpy 数组镜像（训练提速）。
        每神经元：_edge_dst[i]=出边目标数组、_edge_w[i]=出边权重数组（副本，
        训练只改镜像；train_w 结束后 _sync_edges 写回）。EdgeRow 重构后
        镜像直接取自数组事实源（dst int32、w float64），零重建开销。"""
        n = self.ng.n
        self._edge_dst = [None] * n
        self._edge_w = [None] * n
        for i in range(n):
            row = self.ng.W_out[i][0]
            if row:
                self._edge_dst[i] = row.dst.copy()      # int32（fancy-index 兼容）
                self._edge_w[i] = row.w.copy()          # float64（与 Python float 一致）

    def sync_edges(self):
        """把镜像权重写回 EdgeRow（train_w 结束后调用一次）。
        镜像 dst 序与行内排序一致（build 时拷贝、训练只改 w）→ 整行数组替换。"""
        for i in range(self.ng.n):
            dst, w = self._edge_dst[i], self._edge_w[i]
            if dst is None:
                continue
            row = self.ng.W_out[i][0]
            row.dst = dst.astype(np.int32)
            row.w = np.clip(w, 0.0, self.ng.w_max)
        self.ng.invalidate_edge_cache()   # [兼容占位] 数组即事实源，无实际置脏

    def _out_edges_accum_fast(self, src_idxs, slot=0):
        """镜像版出边聚合（= _out_edges_accum，fancy-index 向量化）。"""
        acc = np.zeros(self.ng.n)
        for i in src_idxs:
            dst, w = self._edge_dst[i], self._edge_w[i]
            if dst is None or len(dst) == 0:
                continue
            acc[dst] += w
        return acc

    def _score_vec(self, src_idxs):
        if self._edge_dst is not None:
            acc = self._out_edges_accum_fast(src_idxs)
        else:
            acc = _out_edges_accum(self.ng, src_idxs, 0)
        return acc[self.pats_mat].sum(axis=1) / self.pats_mat.shape[1]

    def _logits_w(self, prefix_ids):
        V = len(self.vocab)
        logits = np.zeros(V)
        for pos, wid in enumerate(reversed(prefix_ids)):
            if pos >= self.maxlen:
                break
            logits += self.ctx_wgt[pos] * self._score_vec(self.pats[self.vocab[wid]])
        return logits

    def _grads(self, prefix_ids, target, T=1.0, use_s=False):
        """反向：返回 (d_ctx_wgt[L], dW 稀疏累积 dict)。
        dW: {i: {j: g}}——i=源神经元、j=目标神经元（已有连接才更新，保持稀疏）。
        use_s=True：前向/d_wgt 走 S 矩阵快照（batch 训练用，省逐位置 _score_vec）；
        dW 累积仍逐位置精确（只依赖 g_n，与 S 无关）。"""
        V = len(self.vocab)
        if use_s and self.S is not None:
            Ln = min(self.maxlen, len(prefix_ids))
            cols = prefix_ids[-Ln:][::-1]        # 末词在列首，对齐 ctx_wgt[0]
            logits = self.S[:, cols] @ self.ctx_wgt[:Ln]   # 原始尺度（= _logits_w）
        else:
            logits = self._logits_w(prefix_ids)
        ex = np.exp((logits - logits.max()) / T)
        probs = ex / ex.sum()
        dL = probs.copy()
        dL[target] -= 1.0  # V 维 CE 梯度

        d_wgt = np.zeros(self.maxlen)
        dW = {}
        g_n = np.zeros(self.ng.n)
        np.add.at(g_n, self.pats_mat.ravel(), np.repeat(dL, self.pats_mat.shape[1]))
        g_n /= self.pats_mat.shape[1]

        for pos, wid in enumerate(reversed(prefix_ids)):
            if pos >= self.maxlen:
                break
            if use_s and self.S is not None:
                s = self.S[:, wid]               # 列 = score(·, wid)，原始尺度
            else:
                s = self._score_vec(self.pats[self.vocab[wid]])
            d_wgt[pos] += float(s @ dL)
            cw = self.ctx_wgt[pos]
            for i in self.pats[self.vocab[wid]]:
                if self._edge_dst is not None:
                    dst = self._edge_dst[i]
                    if dst is None or len(dst) == 0:
                        continue
                    gi = dW.get(i)
                    if gi is None:
                        gi = np.zeros(len(dst))
                        dW[i] = gi
                    gi += cw * g_n[dst]          # 向量化累积（镜像版）
                else:
                    row = self.ng.W_out[i][0]
                    if not row:
                        continue
                    gi = dW.setdefault(i, {})
                    for j, w in row.items():
                        g = cw * g_n[j]
                        if g != 0.0:
                            gi[j] = gi.get(j, 0.0) + g
        return d_wgt, dW, probs

    def _apply(self, d_wgt, dW, lr):
        """更新 ctx_wgt + W 非零子集（clip [0, w_max]，保持稀疏）。
        镜像版：dW 为 {i: ndarray}（长度=出边数），更新镜像数组。
        dict 版：dW 为 {i: {j: g}}（batch 累积结构兼容，逐条目更新）。"""
        self.ctx_wgt -= lr * d_wgt
        if self._edge_dst is not None:
            for i, gi in dW.items():
                if gi is None:
                    continue
                w = self._edge_w[i]
                w -= lr * gi
                np.clip(w, 0.0, self.ng.w_max, out=w)
        else:
            for i, gi in dW.items():
                row = self.ng.W_out[i][0]
                for j, g in gi.items():
                    if j in row:
                        row[j] = min(max(row[j] - lr * g, 0.0), self.ng.w_max)
