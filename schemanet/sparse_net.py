# -*- coding: utf-8 -*-
"""定式网络（SchemaNet）稀疏实现 —— Phase 2 规模扩展专用。

背景：n 大幅扩大后（8192+），稠密 W[n, slots, n] 内存爆炸（8192²×4×8B≈2GB），
必须稀疏存储。实测语言实验 W 非零率仅 0.11%（Hebbian/STDP 只强化共现对），
稀疏化收益是数量级：W 从 2GB → MB 级，传播/更新只碰非零行（O(非零)）。

SparseSchemaNet 与 schema_net.SchemaNet 的 step() 动力学**完全一致**
（积分-发放 + WTA + Hebbian + STDP + 痕迹 + 不应期 + 学习门），仅 W 存储
从稠密矩阵改为稀疏字典：

    W_out[i][k] = {j: w}   神经元 i 槽 k → 神经元 j 的出边权重
    （语义 = 稠密 SchemaNet.W[j, k, i]，j 的入连接来自 i）

RNG 调用点与稠密完全一致（仅 noise 一步）→ 同种子同噪声序列 → 学习结果
逐值一致（_check_sparse.py 对拍验证）。

用法：
    python sparse_net.py --corpus data/corpus_large.json --n 8192 --k 16 --kv 2000
"""

import argparse
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
from numba import njit

from schema_net import (SchemaNet, _word_pattern, _learn_sentence, _evoke_prefix,
                        _BigramModel, _TrigramModel, _evaluate_ngram, build_pulse,
                        _generate)


# ════════════════════════════════════════════════════════════════
#  EdgeRow：稀疏行（数组事实源 + dict 兼容接口）
# ════════════════════════════════════════════════════════════════

# 共享空数组（60 万行共用，避免每行独立空数组的对象开销）
_EMPTY_DST = np.zeros(0, dtype=np.int32)
_EMPTY_W = np.zeros(0, dtype=np.float64)


class EdgeRow:
    """一行出边 {j: w} 的数组实现（dict 兼容接口）。

    事实源 = dst(int32, 排序) + w(float64) 两个 numpy 数组（≈12B/边），
    取代 dict（≈110B/边，见 docs/reports/[REPORT]-定式网络内存优化探针
    实验报告-三种存储结构RSS实测.md）。w 用 float64 保证与 Python float
    （原 dict 值）逐位一致——对拍铁律"结构不变≠性能不变"。

    数组即事实源：传播镜像直接返回 (dst, w) 视图，dirty/懒重建机制废弃。

    兼容外部对 `ng.W_out[i][k]` 的全部 dict 用法：
        get / __getitem__ / __setitem__ / __delitem__ / __contains__ /
        __iter__ / items / keys / values / clear / update / copy / pop /
        __len__ / __bool__
    """
    __slots__ = ("dst", "w")

    def __init__(self, dst=None, w=None):
        self.dst = _EMPTY_DST if dst is None else dst
        self.w = _EMPTY_W if w is None else w

    # ── 读 ──
    def __len__(self):
        return len(self.dst)

    def __bool__(self):
        return len(self.dst) > 0

    def get(self, j, default=0.0):
        idx = np.searchsorted(self.dst, j)
        if idx < len(self.dst) and self.dst[idx] == j:
            return float(self.w[idx])
        return default

    def __getitem__(self, j):
        idx = np.searchsorted(self.dst, j)
        if idx < len(self.dst) and self.dst[idx] == j:
            return float(self.w[idx])
        raise KeyError(j)

    def __contains__(self, j):
        idx = np.searchsorted(self.dst, j)
        return idx < len(self.dst) and self.dst[idx] == j

    def __iter__(self):
        return iter(self.dst.tolist())

    def keys(self):
        return iter(self.dst.tolist())

    def values(self):
        return iter(self.w.tolist())

    def items(self):
        return zip(self.dst.tolist(), self.w.tolist())

    def to_dict(self):
        return {int(j): float(w) for j, w in zip(self.dst.tolist(), self.w.tolist())}

    # ── 写 ──
    def __setitem__(self, j, w):
        j = int(j)
        w = float(w)
        idx = np.searchsorted(self.dst, j)
        if idx < len(self.dst) and self.dst[idx] == j:
            self.w[idx] = w
        else:
            self.dst = np.insert(self.dst, idx, j)
            self.w = np.insert(self.w, idx, w)

    def __delitem__(self, j):
        j = int(j)
        idx = np.searchsorted(self.dst, j)
        if idx < len(self.dst) and self.dst[idx] == j:
            self.dst = np.delete(self.dst, idx)
            self.w = np.delete(self.w, idx)
        else:
            raise KeyError(j)

    def pop(self, j, default=None):
        j = int(j)
        idx = np.searchsorted(self.dst, j)
        if idx < len(self.dst) and self.dst[idx] == j:
            v = float(self.w[idx])
            self.dst = np.delete(self.dst, idx)
            self.w = np.delete(self.w, idx)
            return v
        if default is None:
            raise KeyError(j)
        return default

    def clear(self):
        self.dst = _EMPTY_DST
        self.w = _EMPTY_W

    def update(self, other):
        for j, w in other.items():
            self[j] = w

    def copy(self):
        return EdgeRow(self.dst.copy(), self.w.copy())

    def batch_update(self, pairs):
        """批量写入 {j: w}（Hebbian/STDP 每步合并用）。同 j 覆盖，新 j 插入。
        数组即事实源——就地更新，无镜像置脏。返回改动条目数。"""
        if not pairs:
            return 0
        js = np.fromiter(pairs.keys(), dtype=np.int32, count=len(pairs))
        ws = np.fromiter(pairs.values(), dtype=np.float64, count=len(pairs))
        if len(self.dst):
            idx = np.searchsorted(self.dst, js)
            # searchsorted 对大于全行最大值的键返回 len → safe 索引防越界
            exist = (idx < len(self.dst)) & (self.dst[np.minimum(idx, len(self.dst) - 1)] == js)
        else:
            # 空行：全部新增（防空行越界）
            idx = np.zeros(len(js), dtype=np.intp)
            exist = np.zeros(len(js), dtype=bool)
        n_new = int((~exist).sum())
        if exist.any():
            self.w[idx[exist]] = ws[exist]      # 先覆盖（数组未变，idx 仍有效）
        if n_new:
            self.dst = np.concatenate([self.dst, js[~exist]])
            self.w = np.concatenate([self.w, ws[~exist]])
            order = np.argsort(self.dst, kind="stable")
            self.dst = self.dst[order]
            self.w = self.w[order]
        return n_new + int(exist.sum())

    def scale(self, factor):
        """全行权重 ×factor（weight_decay / sleep 弱化用，numpy 向量化）。"""
        if len(self.w):
            self.w *= factor

    def prune_below(self, eps):
        """删除权重 ≤eps 的条目（sleep 弱边回收）。返回删除条数。"""
        if not len(self.w):
            return 0
        keep = self.w > eps
        n = int((~keep).sum())
        if n:
            self.dst = self.dst[keep]
            self.w = self.w[keep]
        return n

    def edge_view(self):
        """传播镜像视图：(dst, w)——数组即事实源，零复制零置脏。"""
        return self.dst, self.w


# ════════════════════════════════════════════════════════════════
#  numba 热路径内核（Hebbian/STDP 批量合并，2026-08-10 提速）
#  ════════════════════════════════════════════════════════════════
#  与 EdgeRow.batch_update 语义逐位一致：存在键 → w+delta 并截断
#  （w_max 截高 / clip_low 截低，即 stdp_neg 的 <0 → 0）；不存在键 →
#  插入并保持 dst 稳定有序（concat + stable argsort）。numba 只处理
#  O(k²)/O(k×pre) 的行内合并，EdgeRow 数组操作仍由 Python 侧完成。

@njit(cache=True)
def _merge_row(dst, w, keys, deltas, w_max, clip_low):
    """单行合并：现有 (dst,w) 有序；更新 keys[i]+deltas[i]（key 唯一）。
    返回 (new_dst, new_w)，保持有序。语义对齐 batch_update。"""
    n = len(dst)
    m = len(keys)
    ndst = np.empty(n + m, dtype=np.int32)
    nw = np.empty(n + m, dtype=np.float64)
    for j in range(n):
        ndst[j] = dst[j]
        nw[j] = w[j]
    n_new = 0
    for i in range(m):
        key = keys[i]
        dlt = deltas[i]
        idx = np.searchsorted(dst, key)
        if idx < n and dst[idx] == key:
            nv = nw[idx] + dlt
            if nv > w_max:
                nv = w_max
            if nv < clip_low:
                nv = clip_low
            nw[idx] = nv
        else:
            ndst[n + n_new] = key
            nw[n + n_new] = dlt
            n_new += 1
    total = n + n_new
    if n_new:
        order = np.argsort(ndst[:total], kind="stable")
        return ndst[:total][order], nw[:total][order]
    return ndst[:total], nw[:total]


@njit(cache=True)
def _merge_rows(nr, offs, dsts, ws, koff, keys, deltas, w_max, clip_low,
                out_offs, out_dst, out_w, out_len):
    """多行批量合并（扁平化输入，nr 行一次算完）。
    offs/dsts/ws：各行的现有 dst/w 拼接；koff/keys/deltas：各行的更新拼接。
    out_offs/out_dst/out_w/out_len：预分配输出（容量 = 总现有 + 总更新）。"""
    for r in range(nr):
        dst = dsts[offs[r]:offs[r + 1]]
        w = ws[offs[r]:offs[r + 1]]
        key = keys[koff[r]:koff[r + 1]]
        dlt = deltas[koff[r]:koff[r + 1]]
        new_dst, new_w = _merge_row(dst, w, key, dlt, w_max, clip_low)
        s = out_offs[r]
        for j in range(len(new_dst)):
            out_dst[s + j] = new_dst[j]
            out_w[s + j] = new_w[j]
        out_len[r] = len(new_dst)


def _row_from_dict(d):
    """dict 行 → EdgeRow（供 restore_w 等整体替换场景；d 为普通 dict）。"""
    row = EdgeRow()
    if d:
        row.dst = np.fromiter(d.keys(), dtype=np.int32, count=len(d))
        row.w = np.fromiter(d.values(), dtype=np.float64, count=len(d))
        order = np.argsort(row.dst, kind="stable")
        row.dst = row.dst[order]
        row.w = row.w[order]
    return row


def _rows_from_arrays(ng, src_i, slot_k, dst_j, vals):
    """边数组 → W_out 批量构建（替代逐条 setitem；load_net / snapshot 用）。

    按 (i,k) 组合键全局排序后切块，行内按 dst 排序——1807 万边一次
    argsort + 行内小 argsort，免去 dict 逐条插入的 O(n²) 复制。"""
    if len(vals) == 0:
        return
    keys = src_i.astype(np.int64) * (ng.slots + 1) + slot_k
    order = np.argsort(keys, kind="stable")
    ko = keys[order]
    si = src_i[order]
    dj = dst_j[order]
    va = vals[order]
    group_end = np.where(np.diff(ko) != 0)[0] + 1
    starts = np.concatenate([[0], group_end])
    ends = np.concatenate([group_end, [len(vals)]])
    for s, e in zip(starts, ends):
        i = int(si[s])
        k = int(ko[s]) - i * (ng.slots + 1)
        row = EdgeRow()
        row.dst = dj[s:e].astype(np.int32)
        row.w = va[s:e].astype(np.float64)
        o = np.argsort(row.dst, kind="stable")
        row.dst = row.dst[o]
        row.w = row.w[o]
        ng.W_out[i][k] = row


# ════════════════════════════════════════════════════════════════
#  稀疏网络核心（动力学对齐 schema_net.SchemaNet）
# ════════════════════════════════════════════════════════════════

class SparseSchemaNet:
    """定式网络稀疏版：与 SchemaNet.step() 动力学完全一致，W 稀疏存储。

    语言实验只用 slot=0，但为行为对齐保留多槽完整实现（噪声打所有槽、
    Hebbian/STDP 写到主导槽 k_star、传播按主导槽分桶）。
    """

    def __init__(self, n=8192, slots=4, theta=1.0, membrane_decay=0.9, eta=0.1,
                 w_max=16.0, wta_k=16, noise_p=0.06, noise_amp=0.5,
                 weight_decay=0.0, slot_cap=0.0, learn_gate=True,
                 stdp_pre=0.5, stdp_neg=0.0, trace_decay=0.5, refractory=1,
                 inh_loose=0.3, std_dep=0.0, std_rec=0.85,
                 edge_min=0.0, inh_norm=0.0, refract_clear=False, rng=None):
        # slot_cap：[已废弃] 满槽覆盖上限（默认永久 0；本稀疏版从未实现覆盖逻辑，
        # 由频率门控慢衰减 sleep_consolidate 取代，见 Phase 1）。
        self.n = n
        self.slots = slots
        self.theta = theta
        self.membrane_decay = membrane_decay
        self.eta = eta
        self.w_max = w_max
        self.wta_k = wta_k
        self.noise_p = noise_p
        self.noise_amp = noise_amp
        self.weight_decay = weight_decay
        self.slot_cap = slot_cap
        self.learn_gate = learn_gate
        self.stdp_pre = stdp_pre
        self.stdp_neg = stdp_neg
        self.trace_decay = trace_decay
        self.trace_thres = 0.3
        self.refractory = refractory
        # inh_loose：侧抑制清扫（lateral inhibition，2026-08-10）。WTA 选出 top
        # 后，把"过阈但没被选中"的候选 v 压低（×inh_loose）——每步清扫，防止
        # 老候选越积越高霸榜（v 不发放不回落 ×0.9 累积 = 超临界雪崩引擎之一，
        # 见 docs/reports/[REPORT]-石头痛觉刺激过强-网络超临界放电诊断.md）。
        # 生物对应：发放神经元抑制邻近未发放者——"痛是事件不是状态"：碰一下
        # → 痛发 → 躲开 → 清扫 → 恢复静息（不痛了 = 负强化奖励的前提）。
        # 1.0 = 关闭（旧动力学）。0 = 最强清扫。
        self.inh_loose = inh_loose
        # std_dep/std_rec：短期突触抑制 STD（发放者疲劳，2026-08-10）。发放后的
        # 神经元其出边驱动临时降效 ×(1-std_dep)（突触前抑制/囊泡耗竭简化版），
        # 每步按 std_rec 恢复。生物对应"层2 短期突触抑制"——高频词（的/了/是/有）
        # 持续发放 → 出边持续疲劳 → 互驱环（304 振荡，网络无静息态根因，见
        # docs/reports/[REPORT]-石头痛觉刺激过强-网络超临界放电诊断.md）被削弱；
        # 低频定式链（石头→痛→不要）隔跳使用、fat 恢复 → 满效保留。
        # std_dep=0 = 关闭（旧动力学）。
        self.std_dep = std_dep
        self.std_rec = std_rec
        self.fat = np.zeros(n)   # 每神经元疲劳度（0=满效；1=出边全失效）
        # edge_min：层2 弱边修剪（weak-edge pruning，2026-08-10）。传播时
        # 边权重 < edge_min 的出边不参与驱动——阻止"数千条弱边汇聚过阈"
        # 的雪崩扇出（实测 11.2 网络 80% 边 < 0.5，高频词"我"出边 1.7 万条、
        # 其中 1.36 万弱边 = 超临界雪崩主引擎；强定式边石头→痛=16、痛→不要=64
        # 全部保留，修剪只清弱噪声）。0 = 关闭（旧动力学）。
        # 生物对应：突触权重本身是筛选器——弱连接不足以影响下游发放。
        self.edge_min = edge_min
        # inh_norm：层1 全局活动抑制（divisive normalization，2026-08-10）。
        # 传播 drive 总强度超过 inh_norm 时按总强度除法压缩（发得越猛压得越狠），
        # 把分支参数 σ 拉回临界附近（feedback inhibition，Carandini & Heeger）。
        # 0 = 关闭（旧动力学）。
        self.inh_norm = inh_norm
        # refract_clear：不应期硬清（2026-08-10）。传播后、WTA 前，把处于
        # 不应期的神经元膜电位强制清零——防"组装自振复燃"（模式内 Hebbian
        # 互连驱动自己复燃：实测石头模式内部互连 44.4，注入后每拍自振
        # v=11.1 复燃，把后继词挤出 WTA 优先）。生物对应：AHP 后超极化
        # （发放后膜电位压低，不会立即再发放）。False = 关闭（旧动力学）。
        self.refract_clear = refract_clear
        # gain：每神经元增益调制（gain modulation，2026-08-10，用户："直接给
        # 不要加权重，让不要在网络里足够亮"）。WTA 排序用 vmax×gain（候选判定
        # 仍用原始 v≥θ → 不被驱动时不会误发），让高价值词（安全/拒绝信号"不要"）
        # 被驱动后优先发放——注意力调制：重要词反应优先级更高。默认全 1=关闭。
        # 生物对应：feature-based attention 的目标特征增益（attention gain）。
        self.gain = np.ones(n)
        self.rng = rng or np.random.default_rng()
        self.reset()

    def reset(self):
        self.v = np.zeros((self.n, self.slots))
        self.spikes = np.zeros(self.n)
        self.last_k_star = np.zeros(self.n, dtype=int)
        self.pre_trace = np.zeros(self.n)
        self.refractory_left = np.zeros(self.n, dtype=int)
        self.evictions = 0
        # 稀疏出边：W_out[i][k] = EdgeRow（数组事实源，dict 兼容接口），
        # 语义 = 稠密 W[j, k, i]。数组即事实源，传播镜像零复制（见 EdgeRow）。
        self.W_out = [[EdgeRow() for _ in range(self.slots)] for _ in range(self.n)]
        # 唤醒计数（频率门控慢衰减用）：窗口内每个槽位被"发放神经元主导"的次数。
        # 只数真实发放（防静息 v≈0 的噪声性 argmax 污染）；冻结态不计数（纯检索零改动）。
        self.slot_freq = np.zeros((self.n, self.slots), dtype=np.int32)

    def _edge_row(self, i, k):
        """返回 W_out[i][k] 的 (dst, w) numpy 视图（传播读用）。
        空行返回 None（调用处 `if e is not None` 直接跳过）。
        数组即事实源——无 dirty/懒重建（EdgeRow 重构，2026-08-10）。"""
        row = self.W_out[i][k]
        if row:
            return row.dst, row.w
        return None

    def invalidate_edge_cache(self):
        """[兼容占位] 外部写 W_out 后调用。数组即事实源，传播镜像零复制，
        无需置脏——保留方法仅为兼容旧调用（GradReadout.sync_edges/restore_w）。"""

    def _apply_edge_updates(self, groups, w_max, clip_low=0.0):
        """批量合并行更新（numba 热路径）。groups: [(row, keys(int32), deltas)]，
        keys 每行唯一（Hebbian/STDP 的键集合天然唯一）。语义 = 逐行 batch_update。
        行数组就地替换为合并结果（拷贝脱离大缓冲）。"""
        if not groups:
            return
        nr = len(groups)
        # 扁平化输入 + 前缀和（Python 层组装，量小：nr ≤ 行数，键总数 ≤ k²）
        offs = np.empty(nr + 1, dtype=np.int64)
        koff = np.empty(nr + 1, dtype=np.int64)
        out_offs = np.empty(nr + 1, dtype=np.int64)
        dst_parts, w_parts, key_parts, dlt_parts = [], [], [], []
        o1 = o2 = o3 = 0
        rows = [g[0] for g in groups]
        for r, (row, keys, deltas) in enumerate(groups):
            offs[r] = o1
            dst_parts.append(row.dst)
            w_parts.append(row.w)
            o1 += len(row)
            koff[r] = o2
            key_parts.append(keys)
            dlt_parts.append(deltas)
            o2 += len(keys)
            out_offs[r] = o3
            o3 += len(row) + len(keys)
        offs[nr] = o1
        koff[nr] = o2
        out_offs[nr] = o3
        dsts = np.concatenate(dst_parts)
        ws = np.concatenate(w_parts)
        keys = np.concatenate(key_parts)
        deltas = np.concatenate(dlt_parts)
        out_dst = np.empty(o3, dtype=np.int32)
        out_w = np.empty(o3, dtype=np.float64)
        out_len = np.empty(nr, dtype=np.int64)
        _merge_rows(nr, offs, dsts, ws, koff, keys, deltas, w_max, clip_low,
                    out_offs, out_dst, out_w, out_len)
        for r, row in enumerate(rows):
            s = out_offs[r]
            e = s + out_len[r]
            row.dst = np.copy(out_dst[s:e])
            row.w = np.copy(out_w[s:e])

    # ── W 访问兼容：稠密版读出函数用 ng.W[j, slot, i]，这里按需提供等价读取 ──
    def w_get(self, j, slot, i):
        """等价稠密 ng.W[j, slot, i]（j 的入连接来自 i）。"""
        return self.W_out[i][slot].get(j, 0.0)

    def w_rowsum(self, src, slot=0):
        """等价 Σ_j 稠密 W[j, slot, src]（源神经元出边总强度）。"""
        return sum(self.W_out[src][slot].values())

    def step(self, input_pulse, slot=0):
        """单步动力学：与 SchemaNet.step 逐行对齐（详见 schema_net.py 的注释）。"""
        slot = min(slot, self.slots - 1)  # 槽越界保护（单槽时所有输入都进槽 0）
        noise = (self.rng.random(self.n) < self.noise_p) * self.noise_amp
        self.v = self.v * self.membrane_decay + noise[:, None]
        self.v[:, slot] += input_pulse
        if self.std_dep > 0:
            self.fat *= self.std_rec   # STD 疲劳逐步恢复（高频词疲劳持续、低频链恢复）

        # 分槽传播（稀疏：只遍历发放神经元出边的非零行，镜像 numpy 批量累加）
        if self.spikes.any():
            for k in range(self.slots):
                senders = np.where((self.spikes > 0) & (self.last_k_star == k))[0]
                if len(senders):
                    drive = np.zeros(self.n)
                    # 批量累加（2026-08-10 提速）：sender 循环 → 收集全部出边
                    # 一次 np.add.at（目标侧全量调用，消除 Python 级逐行累加）。
                    # 语义逐位一致：各 sender 行内顺序 + sender 顺序拼接后 add.at，
                    # 与逐行 `drive[e[0]] += w` 的累加顺序完全相同。
                    ds, ws = [], []
                    for i in senders:
                        e = self._edge_row(i, k)
                        if e is not None:
                            ds.append(e[0])
                            if self.std_dep > 0:
                                ws.append(e[1] * (1.0 - self.fat[i]))
                            else:
                                ws.append(e[1])
                    if ds:
                        all_dst = np.concatenate(ds)
                        all_w = np.concatenate(ws)
                        if self.edge_min > 0:  # 层2 弱边修剪（弱边不参与驱动）
                            keep = all_w >= self.edge_min
                            if keep.any():
                                all_dst = all_dst[keep]
                                all_w = all_w[keep]
                            else:
                                all_dst = all_dst[:0]
                                all_w = all_w[:0]
                        if len(all_dst):
                            np.add.at(drive, all_dst, all_w)
                    if self.inh_norm > 0:  # 层1 全局活动抑制：除法归一化
                        tot = drive.sum()
                        if tot > self.inh_norm:
                            drive *= self.inh_norm / tot
                    self.v[:, k] += drive

        # 不应期硬清：处于不应期的神经元膜电位清零（防组装自振复燃——
        # 刚发放过的组装被自身模式内互连驱动，不应期一过立即复燃）
        if self.refract_clear and self.refractory > 0:
            self.v[self.refractory_left > 0] = 0.0

        # 主导槽 + WTA
        k_star = self.v.argmax(axis=1)
        vmax = self.v[np.arange(self.n), k_star]

        eligible = np.ones(self.n, dtype=bool)
        if self.refractory > 0:
            eligible = self.refractory_left == 0
        candidates = np.where((vmax >= self.theta) & eligible)[0]
        if len(candidates) > self.wta_k:
            # 增益调制：WTA 排序用 vmax×gain（候选判定仍用原始 v≥θ），
            # 高价值词（如"不要"）被驱动后优先发放
            key = vmax[candidates] * self.gain[candidates]
            # 提速（2026-08-10）：argsort 全排序 O(C log C) → argpartition 部分
            # 选择 O(C)。只取 top-k，顺序无关（new_spikes/v 清零/Hebbian 均为集合语义）。
            idx = np.argpartition(-key, self.wta_k - 1)[: self.wta_k]
            top = candidates[idx]
        else:
            top = candidates

        new_spikes = np.zeros(self.n)
        if len(top):
            # 侧抑制清扫（v13.2，2026-08-10）：把"过阈但没被选中"的候选 v 压低
            # ×inh_loose——每步清扫，防止老候选越积越高霸榜（超临界雪崩引擎）。
            # 生物对应：lateral inhibition（发放神经元抑制邻近未发放者）。
            if self.inh_loose < 1.0 and len(candidates) > len(top):
                losers = np.setdiff1d(candidates, top)
                if len(losers):
                    self.v[losers, :] *= self.inh_loose
            new_spikes[top] = 1.0
            if self.std_dep > 0:
                self.fat[top] = self.std_dep   # 发放 → 疲劳（STD 突触前抑制）
            if self.learn_gate:
                # Hebbian/STDP 批量合并（2026-08-10 numba 提速）：原 O(k²)/O(k×pre)
                # Python 双循环 + 每对 row.get() 全部移到 numba 内核 _merge_rows，
                # 语义逐位一致：存在键累加 + w_max 截断 + stable 插入（= batch_update）。
                top_arr = np.asarray(top, dtype=np.int32)
                # Hebbian：共同发放对 (a, c) → W[c][k_star[a]][a] += eta（排除自连接）
                # 行 (c, ka)，键 = {a ∈ top : k_star[a]==ka, a≠c}
                row_to_a = {}
                for a in top_arr:
                    ka = int(k_star[a])
                    for c in top_arr:
                        if a != c:
                            row_to_a.setdefault((int(c), ka), []).append(int(a))
                groups = [(self.W_out[c][ka],
                           np.asarray(aset, dtype=np.int32),
                           np.full(len(aset), self.eta))
                          for (c, ka), aset in row_to_a.items()]
                self._apply_edge_updates(groups, self.w_max)
                # STDP：前驱痕迹 → 当前发放，学 W[后继 ← 前驱]（只正向）
                if (self.stdp_pre > 0 or self.stdp_neg > 0) and self.pre_trace.any():
                    pre_idx = np.where(self.pre_trace > self.trace_thres)[0]
                    if self.stdp_pre > 0 and len(pre_idx):
                        # 行 (pp, k_star[jj])，键 = {jj ∈ top : jj≠pp}
                        row_to_a = {}
                        for jj in top_arr:
                            kj = int(k_star[jj])
                            for pp in pre_idx:
                                if jj != pp:
                                    row_to_a.setdefault((int(pp), kj), []).append(int(jj))
                        groups = [(self.W_out[pp][kj],
                                   np.asarray(aset, dtype=np.int32),
                                   np.full(len(aset), self.stdp_pre))
                                  for (pp, kj), aset in row_to_a.items()]
                        self._apply_edge_updates(groups, self.w_max)
                    if self.stdp_neg > 0 and len(pre_idx):
                        # LTD：当前发放（后发）→ 前驱入连接反序弱化
                        # W[pre_i, kstar_pre_i, top_j] -= stdp_neg（<0 → 0）
                        # 行 (jj, k_star[pp])，键 = {pp ∈ pre_idx : pp≠jj}
                        row_to_a = {}
                        for pp in pre_idx:
                            kp = int(k_star[pp])
                            for jj in top_arr:
                                if pp != jj:
                                    row_to_a.setdefault((int(jj), kp), []).append(int(pp))
                        groups = [(self.W_out[jj][kp],
                                   np.asarray(aset, dtype=np.int32),
                                   np.full(len(aset), -self.stdp_neg))
                                  for (jj, kp), aset in row_to_a.items()]
                        self._apply_edge_updates(groups, self.w_max, clip_low=0.0)
                if self.weight_decay:
                    f = 1.0 - self.weight_decay
                    for i in range(self.n):
                        for k in range(self.slots):
                            row = self.W_out[i][k]
                            if row:
                                row.scale(f)   # 整行向量化（逐条语义一致：w×(1-decay)）

        self.v[top, :] = 0.0
        # 唤醒计数（频率门控慢衰减）：只数真实发放神经元的主导槽，仅学习态
        # （冻结态纯检索，不改变任何状态，含计数——sleep 时冻结态也拒绝执行）
        if self.learn_gate and len(top):
            self.slot_freq[top, k_star[top]] += 1
        self.spikes = new_spikes
        self.last_k_star = k_star
        self.pre_trace = self.pre_trace * self.trace_decay + new_spikes
        if self.refractory > 0:
            self.refractory_left = np.maximum(self.refractory_left - 1, 0)
            if len(top):
                self.refractory_left[top] = self.refractory
        return new_spikes

    def sleep_consolidate(self, min_wake=5, decay=0.3, eps=1e-4):
        """频率门控慢衰减（睡眠记忆巩固）：低频唤醒槽位的连接逐步衰减为 0。

        - 唤醒频率判据：当前窗口内槽位被发放神经元主导的次数 slot_freq[i][k]。
          窗口长度由调用时机保证（每 window 步或显式 sleep 调用一次）。
        - 高频槽（≥ min_wake）：**不动**（活跃定式永不衰减）。
        - 低频槽：连接逐周期 ×(1-decay) 渐进弱化——期间被唤醒即可被 Hebbian/STDP
          强化抵消（**可复活**）；最终 ≤ eps 的连接条目删除（稀疏回收空间）。
        - 冻结态（learn_gate=False）拒绝执行：纯检索物理零改动。
        - 调用后全部计数重置（新窗口从零开始）。

        返回 (删除条目数, 被弱化条目数)。"""
        if not self.learn_gate:
            return 0, 0
        cleared = weakened = 0
        for i in range(self.n):
            for k in range(self.slots):
                if self.slot_freq[i, k] < min_wake:
                    row = self.W_out[i][k]
                    if row:
                        row.scale(1 - decay)          # 整行向量化弱化（逐条语义一致）
                        cleared += row.prune_below(eps)  # ≤eps 条目删除（稀疏回收）
                        weakened += len(row)          # 保留条数（原语义逐条计数）
                self.slot_freq[i, k] = 0  # 新窗口
        return cleared, weakened

    def expand(self, n_new):
        """神经元逐步扩容（v2.1 分配制配套，纯追加、任意粒度含 n+1）。

        旧知识 100% 保留：W_out 前 n_old 行原样复制（连接结构不动），
        新神经元空白供新阶段学习；所有状态数组 pad 对齐。
        粒度任意：n_new = n+1（单个新概念落位）或成批扩容，机制等价。
        验收硬指标：扩容前后旧评估集逐值一致（零遗忘）。
        """
        assert n_new > self.n
        pad = n_new - self.n
        self.v = np.vstack([self.v, np.zeros((pad, self.slots))])
        self.spikes = np.pad(self.spikes, (0, pad))
        self.pre_trace = np.pad(self.pre_trace, (0, pad))
        self.last_k_star = np.pad(self.last_k_star, (0, pad))
        self.refractory_left = np.pad(self.refractory_left, (0, pad))
        self.slot_freq = np.pad(self.slot_freq, ((0, pad), (0, 0)))
        self.gain = np.pad(self.gain, (0, pad))   # 增益数组随扩容对齐（2026-08-10 填充教学
                                                  # 落位扩容时未 pad → step() IndexError）
        self.W_out += [[EdgeRow() for _ in range(self.slots)] for _ in range(pad)]
        self.n = n_new


# ────────────────────────────────────────────────────────────────
#  分配制模式字典（v2.1：词→神经元落位，生成一次永久冻结，随快照持久化）
# ────────────────────────────────────────────────────────────────

def allocate_pats(ng, words, k, cursor=0):
    """按需为 words 分配 k 个神经元/词，返回 (pats, cursor)。

    - 从当前空白神经元按游标顺序取 k 个（分配唯一 → 新词零冲突）
    - 游标越界 → 自动 expand（任意粒度）——"知识的增量 = 神经元的增量"
    - 旧词落位（已分配的 pats）永不动；重复调用同一词返回原落位
    - pats/cursor 随快照持久化（snapshot.py），加载后 cursor 续用
    """
    pats = {}
    for w in dict.fromkeys(words):
        if cursor + k > ng.n:
            ng.expand(cursor + k)          # 按需扩容（本阶段新词落位）
        pats[w] = list(range(cursor, cursor + k))
        cursor += k
    return pats, cursor


# ════════════════════════════════════════════════════════════════
#  向量化稀疏读出（等价 schema_net._predict_cands_wsum / _predict_cands_trace）
# ════════════════════════════════════════════════════════════════

def _pats_matrix(pats, vocab):
    """词模式 → (V, k) 神经元索引数组（纯 numpy 向量化读出）。"""
    return np.array([pats[w] for w in vocab], dtype=int)


def _out_edges_accum(ng, src_idxs, slot):
    """源神经元集合 → 出边聚合向量（n 维）。"""
    acc = np.zeros(ng.n)
    for i in src_idxs:
        row = ng.W_out[i][slot]
        if row:
            for j, w in row.items():
                acc[j] += w
    return acc


def predict_cands_wsum_sparse(ng, prefix, pats, vocab, pats_mat, slot=0, norm_base=None):
    """等价 schema_net._predict_cands_wsum（向量化）。"""
    last = prefix[-1]
    used = set(prefix)
    acc = _out_edges_accum(ng, pats[last], slot)
    scores = acc[pats_mat].sum(axis=1) / pats_mat.shape[1]
    denom = norm_base.get(last, 0.0) if norm_base else 0.0
    if denom > 0:
        scores = scores / denom
    cands = [(vocab[wi], float(scores[wi])) for wi in range(len(vocab))
             if scores[wi] > 0 and vocab[wi] not in used]
    cands.sort(key=lambda x: -x[1])
    return cands


def predict_cands_trace_sparse(ng, prefix, pats, vocab, pats_mat, slot=0, norm_base=None,
                               trace_beta=0.1, delta_off=0.05):
    """等价 schema_net._predict_cands_trace（向量化）。

    每调用全清网络状态（含 refractory/last_k_star）——trace 语义是"给定前缀
    预测下一词"，与之前调用无关，状态残留是原实现的隐副作用（修正）。"""
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)
    ng.refractory_left = np.zeros(ng.n, dtype=int)
    ng.last_k_star = np.zeros(ng.n, dtype=int)
    for w in prefix:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.step(build_pulse(ng.n, pats[w]), slot=slot)
        ng.step(np.zeros(ng.n), slot=slot)
    last = prefix[-1]
    used = set(prefix)
    k = pats_mat.shape[1]

    def cond_vec(src_idxs):
        acc = _out_edges_accum(ng, src_idxs, slot)
        raw = acc[pats_mat].sum(axis=1) / k
        denom = norm_base.get(prefix[-1], 0.0) if norm_base else 0.0
        return raw / denom if denom > 0 else raw

    # 末词条件分布 → δ 判定
    p_last = cond_vec(pats[last])
    order = np.argsort(-p_last)
    top_idx = [wi for wi in order if p_last[wi] > 0 and vocab[wi] not in used]
    if len(top_idx) >= 2 and p_last[top_idx[0]] - p_last[top_idx[1]] >= delta_off:
        return [(vocab[wi], round(float(p_last[wi]), 6)) for wi in top_idx]

    # 末词平局：整条前缀加权混合
    last_pats = pats[last]
    trace_last = float(ng.pre_trace[last_pats].max()) if len(last_pats) else 0.0
    mix = np.zeros(len(vocab))
    for src_w in prefix:
        tr = float(ng.pre_trace[pats[src_w]].max()) if pats[src_w] else 0.0
        wgt = tr / trace_last if trace_last > 0 else tr
        if src_w != last:
            wgt *= trace_beta
        if wgt <= 0:
            continue
        acc = _out_edges_accum(ng, pats[src_w], slot)
        raw = acc[pats_mat].sum(axis=1) / k
        denom = norm_base.get(src_w, 0.0) if norm_base else 0.0
        p = raw / denom if denom > 0 else raw
        mix += wgt * p
    cands = [(vocab[wi], round(float(mix[wi]), 6)) for wi in range(len(vocab))
             if mix[wi] > 0 and vocab[wi] not in used]
    cands.sort(key=lambda x: -x[1])
    return cands


def outsum_sparse(ng, pats, vocab, slot=0):
    """等价稠密 outsum：源词模式所有神经元的出边总强度。"""
    return {a: sum(ng.w_rowsum(src, slot) for src in pats[a]) for a in vocab}


def build_score_mat(ng, pats, vocab, pats_mat, slot=0):
    """S[wi, src] = Σ_{j∈pats[wi]} W[j, slot, src] / k（未归一化词得分矩阵）。

    与 GradReadout 的 S 矩阵同口径（纯 numpy 读出，免 Python 出边循环）。
    V×V float64（V=3000 → 72MB），一次性构建后评估/扫描全部走矩阵直读。"""
    V = len(vocab)
    k = pats_mat.shape[1]
    S = np.empty((V, V), dtype=np.float64)
    for src_idx, w in enumerate(vocab):
        acc = _out_edges_accum(ng, pats[w], slot)
        S[:, src_idx] = acc[pats_mat].sum(axis=1) / k
    return S


def evaluate_wsum_smat(S, vocab, toks_list, norm_base=None, n_samples=8):
    """S 矩阵版 wsum next-token 评估（读出 O(V) numpy，替代逐源出边循环）。"""
    vtab = {w: i for i, w in enumerate(vocab)}
    hits = total = 0
    samples = []
    for toks in toks_list:
        for t in range(1, len(toks)):
            last = toks[t - 1]
            p = S[:, vtab[last]].copy()
            den = norm_base.get(last, 0.0) if norm_base else 0.0
            if den > 0:
                p /= den
            used = set(toks[:t])
            cands = [(vocab[wi], float(p[wi])) for wi in range(len(vocab))
                     if p[wi] > 0 and vocab[wi] not in used]
            cands.sort(key=lambda x: -x[1])
            pred = cands[0][0] if cands else None
            total += 1
            if pred == toks[t]:
                hits += 1
            elif len(samples) < n_samples:
                samples.append({"ctx": "".join(toks[:t]), "truth": toks[t], "pred": pred,
                                "top3": [c[0] for c in cands[:3]]})
    return (hits / total if total else 0.0), hits, total, samples


def evaluate_trace_smat(ng, toks_list, S, pats, vocab, norm_base, slot=0,
                        delta_off=0.05, trace_beta=0.1, n_samples=8):
    """S 矩阵版增量 trace 评估。

    动力学注入骨架保留（单句内 pre_trace 自然累积），读出走 S 矩阵直读
    （δ 判定 + 平局痕迹混合全 numpy），替代 _trace_cands_from_state 里
    逐源神经元 Python 出边循环——词表/连接规模大时几十倍加速。
    语义与原版一致：learn_gate 冻结下不写 W，仅推进膜电位状态。"""
    vtab = {w: i for i, w in enumerate(vocab)}
    V = len(vocab)
    hits = total = 0
    samples = []
    for toks in toks_list:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.refractory_left = np.zeros(ng.n, dtype=int)
        ng.last_k_star = np.zeros(ng.n, dtype=int)
        for t in range(1, len(toks)):
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(build_pulse(ng.n, pats[toks[t - 1]]), slot=slot)
            ng.step(np.zeros(ng.n), slot=slot)
            last = toks[t - 1]
            p_last = S[:, vtab[last]].copy()
            den = norm_base.get(last, 0.0) if norm_base else 0.0
            if den > 0:
                p_last /= den
            used = set(toks[:t])
            order = np.argsort(-p_last)
            top_idx = [wi for wi in order if p_last[wi] > 0 and vocab[wi] not in used]
            if len(top_idx) >= 2 and p_last[top_idx[0]] - p_last[top_idx[1]] >= delta_off:
                cands = [(vocab[wi], round(float(p_last[wi]), 6)) for wi in top_idx]
            else:
                # 末词平局：整条前缀加权混合（痕迹权重 × trace_beta 压降非末词）
                last_pats = pats[last]
                trace_last = float(ng.pre_trace[last_pats].max()) if len(last_pats) else 0.0
                mix = np.zeros(V)
                for src_w in toks[:t]:
                    tr = float(ng.pre_trace[pats[src_w]].max()) if pats[src_w] else 0.0
                    wgt = tr / trace_last if trace_last > 0 else tr
                    if src_w != last:
                        wgt *= trace_beta
                    if wgt <= 0:
                        continue
                    p = S[:, vtab[src_w]].copy()
                    d2 = norm_base.get(src_w, 0.0) if norm_base else 0.0
                    if d2 > 0:
                        p /= d2
                    mix += wgt * p
                cands = [(vocab[wi], round(float(mix[wi]), 6)) for wi in range(V)
                         if mix[wi] > 0 and vocab[wi] not in used]
                cands.sort(key=lambda x: -x[1])
            pred = cands[0][0] if cands else None
            total += 1
            if pred == toks[t]:
                hits += 1
            elif len(samples) < n_samples:
                samples.append({"ctx": "".join(toks[:t]), "truth": toks[t], "pred": pred,
                                "top3": [c[0] for c in cands[:3]]})
    return (hits / total if total else 0.0), hits, total, samples


def _trace_cands_from_state(ng, last, prefix, pats, vocab, pats_mat, slot,
                            norm_base, trace_beta, delta_off):
    """trace 读出核心：从**当前网络状态**（前缀已重放、pre_trace 已累积）读候选。

    逻辑与 predict_cands_trace_sparse 的读出部分完全一致（δ 直判 → 平局痕迹混合），
    只是不做动力学重放——状态由调用方在单句内增量维护。"""
    used = set(prefix)
    k = pats_mat.shape[1]

    def cond_vec(src_idxs):
        acc = _out_edges_accum(ng, src_idxs, slot)
        raw = acc[pats_mat].sum(axis=1) / k
        denom = norm_base.get(last, 0.0) if norm_base else 0.0
        return raw / denom if denom > 0 else raw

    # 末词条件分布 → δ 判定
    p_last = cond_vec(pats[last])
    order = np.argsort(-p_last)
    top_idx = [wi for wi in order if p_last[wi] > 0 and vocab[wi] not in used]
    if len(top_idx) >= 2 and p_last[top_idx[0]] - p_last[top_idx[1]] >= delta_off:
        return [(vocab[wi], round(float(p_last[wi]), 6)) for wi in top_idx]

    # 末词平局：整条前缀加权混合（痕迹权重 × trace_beta 压降非末词）
    last_pats = pats[last]
    trace_last = float(ng.pre_trace[last_pats].max()) if len(last_pats) else 0.0
    mix = np.zeros(len(vocab))
    for src_w in prefix:
        tr = float(ng.pre_trace[pats[src_w]].max()) if pats[src_w] else 0.0
        wgt = tr / trace_last if trace_last > 0 else tr
        if src_w != last:
            wgt *= trace_beta
        if wgt <= 0:
            continue
        acc = _out_edges_accum(ng, pats[src_w], slot)
        raw = acc[pats_mat].sum(axis=1) / k
        denom = norm_base.get(src_w, 0.0) if norm_base else 0.0
        p = raw / denom if denom > 0 else raw
        mix += wgt * p
    cands = [(vocab[wi], round(float(mix[wi]), 6)) for wi in range(len(vocab))
             if mix[wi] > 0 and vocab[wi] not in used]
    cands.sort(key=lambda x: -x[1])
    return cands


def evaluate_schemanet_trace_inc(ng, toks_list, pats, vocab, pats_mat, slot=0,
                                 norm_base=None, n_samples=8, delta_off=0.05,
                                 trace_beta=0.1):
    """增量 trace 评估：单句内逐词注入（pre_trace 自然累积，不复位重放）。

    语义与 evaluate_schemanet_sparse(readout='trace') 逐位一致——trace 重放前缀
    就是从空状态逐词 step，而相邻预测位的前缀只差一个词，增量 step 即等价；
    复杂度 O(len) 而非 O(len²)。learn_gate 冻结下不写 W，仅推进膜电位状态。"""
    hits = total = 0
    samples = []
    for toks in toks_list:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.refractory_left = np.zeros(ng.n, dtype=int)
        ng.last_k_star = np.zeros(ng.n, dtype=int)
        for t in range(1, len(toks)):
            # 注入 toks[t-1]（predict_cands_trace_sparse 重放前缀的最后两拍）
            ng.v = np.zeros((ng.n, ng.slots))
            ng.step(build_pulse(ng.n, pats[toks[t - 1]]), slot=slot)
            ng.step(np.zeros(ng.n), slot=slot)
            cands = _trace_cands_from_state(ng, toks[t - 1], toks[:t], pats, vocab,
                                            pats_mat, slot, norm_base, trace_beta,
                                            delta_off)
            pred = cands[0][0] if cands else None
            total += 1
            if pred == toks[t]:
                hits += 1
            elif len(samples) < n_samples:
                samples.append({"ctx": "".join(toks[:t]), "truth": toks[t], "pred": pred,
                                "top3": [c[0] for c in cands[:3]]})
    return (hits / total if total else 0.0), hits, total, samples


def evaluate_schemanet_sparse(ng, toks_list, pats, vocab, pats_mat, slot=0,
                              readout="wsum", norm_base=None, n_samples=8,
                              delta_off=0.05):
    """稀疏版 next-token 评估（readout: wsum / wnorm / trace）。"""
    hits = total = 0
    samples = []
    for toks in toks_list:
        for t in range(1, len(toks)):
            if readout == "wsum":
                cands = predict_cands_wsum_sparse(ng, toks[:t], pats, vocab, pats_mat,
                                                  slot=slot)
            elif readout == "wnorm":
                cands = predict_cands_wsum_sparse(ng, toks[:t], pats, vocab, pats_mat,
                                                  slot=slot, norm_base=norm_base)
            else:
                cands = predict_cands_trace_sparse(ng, toks[:t], pats, vocab, pats_mat,
                                                   slot=slot, norm_base=norm_base,
                                                   delta_off=delta_off)
            pred = cands[0][0] if cands else None
            total += 1
            if pred == toks[t]:
                hits += 1
            elif len(samples) < n_samples:
                samples.append({"ctx": "".join(toks[:t]), "truth": toks[t], "pred": pred,
                                "top3": [c[0] for c in cands[:3]]})
    return (hits / total if total else 0.0), hits, total, samples


# ════════════════════════════════════════════════════════════════
#  规模实验主流程
# ════════════════════════════════════════════════════════════════

def run_sparse_language_experiment(args):
    data_dir = Path(__file__).parent / "data"
    corpus = json.loads((data_dir / args.corpus).read_text(encoding="utf-8"))

    import jieba
    t0 = time.time()
    tokenized = [jieba.lcut(s) for s in corpus]
    freq = Counter(w for toks in tokenized for w in toks)
    vocab = [w for w, _ in freq.most_common(args.kv)]
    vocab_set = set(vocab)
    oov = sum(1 for toks in tokenized for w in toks if w not in vocab_set)
    t_token = time.time() - t0

    # ── 编码预检：碰撞对（k 中 ≥2 个重叠的词对占比）──
    t0 = time.time()
    pats = {w: _word_pattern(args.n, args.k, w) for w in vocab}
    coll_ge2 = 0
    vlist = list(vocab)
    for i in range(len(vlist)):
        pi = set(pats[vlist[i]])
        for j in range(i + 1, len(vlist)):
            if len(pi & set(pats[vlist[j]])) >= 2:
                coll_ge2 += 1
    pairs = len(vlist) * (len(vlist) - 1) // 2
    t_encode = time.time() - t0

    # ── 数据划分 ──
    rng_split = np.random.default_rng(args.seed + 9000)
    perm = rng_split.permutation(len(tokenized))
    n_train = int(len(tokenized) * args.split)
    train_toks = [tokenized[i] for i in perm[:n_train]]
    test_toks = [tokenized[i] for i in perm[n_train:]]

    # ── 学习（稀疏）──
    t0 = time.time()
    ng = SparseSchemaNet(n=args.n, slots=4, theta=1.0, membrane_decay=0.9,
                         eta=0.1, w_max=args.wmax, wta_k=args.k,
                         noise_p=0.06, noise_amp=0.5, weight_decay=0.0,
                         slot_cap=0.0, stdp_pre=args.stdp_pre, stdp_neg=0.0,
                         refractory=1, rng=np.random.default_rng(args.seed + 5000))
    for toks in train_toks:
        _learn_sentence(ng, toks, pats, slot=0)
    ng.learn_gate = False  # 评估冻结
    t_learn = time.time() - t0

    # ── W 非零率 / 内存 ──
    nnz = sum(len(row) for rows in ng.W_out for row in rows)
    nnz_ratio = nnz / (args.n * 4 * args.n)  # slots=4 硬编码（与构造一致）
    w_mem = nnz * (8 + 8 + 24)  # 每非零项约：key 8B + value 8B + dict 开销 ~24B（粗略）
    rss_mb = _rss_mb()

    # ── 评估 ──
    pats_mat = _pats_matrix(pats, vocab)
    outsum = outsum_sparse(ng, pats, vocab, slot=0)
    t0 = time.time()
    wsum_train = evaluate_schemanet_sparse(ng, train_toks, pats, vocab, pats_mat,
                                           readout="wsum")
    wsum_test = evaluate_schemanet_sparse(ng, test_toks, pats, vocab, pats_mat,
                                          readout="wsum")
    tr_train = evaluate_schemanet_sparse(ng, train_toks, pats, vocab, pats_mat,
                                         readout="trace", norm_base=outsum,
                                         delta_off=args.delta_off)
    tr_test = evaluate_schemanet_sparse(ng, test_toks, pats, vocab, pats_mat,
                                        readout="trace", norm_base=outsum,
                                        delta_off=args.delta_off)
    bi = _BigramModel(train_toks)
    tri = _TrigramModel(train_toks)
    bi_train = _evaluate_ngram(bi, train_toks)
    bi_test = _evaluate_ngram(bi, test_toks)
    tri_train = _evaluate_ngram(tri, train_toks)
    tri_test = _evaluate_ngram(tri, test_toks)
    t_eval = time.time() - t0

    # ── 消歧（trace）──
    disambig = []
    for cue, truth in [("我觉得", "很"), ("我今天", "很"), ("我想", "吃"), ("我喜欢吃", "苹果")]:
        cands = predict_cands_trace_sparse(ng, jieba.lcut(cue), pats, vocab, pats_mat,
                                           norm_base=outsum, delta_off=args.delta_off)
        disambig.append({"cue": cue, "truth": truth,
                         "top": [w for w, _ in cands[:5]],
                         "hit": bool(cands) and cands[0][0] == truth})

    # ── 生成样例 ──
    generations = []
    for start in ("你好", "我", "今天"):
        gen = _generate(ng, start, pats, vocab, max_len=12, min_cov=0.4)
        generations.append({"start": start, "seq": gen})

    return {
        "args": vars(args),
        "corpus": {"n_sent": len(corpus), "n_train": len(train_toks),
                   "n_test": len(test_toks), "vocab_size": len(vocab),
                   "oov": oov, "tokens_total": sum(len(t) for t in tokenized)},
        "encoding": {"n": args.n, "k": args.k, "collisions_ge2": coll_ge2,
                     "pairs": pairs},
        "freq_top10": freq.most_common(10),
        "scale": {"nnz": nnz, "nnz_ratio": nnz_ratio, "w_mem_bytes": w_mem,
                  "rss_mb": rss_mb},
        "timing": {"tokenize": t_token, "encode": t_encode, "learn": t_learn,
                   "eval": t_eval},
        "wsum": {"train": wsum_train, "test": wsum_test},
        "trace": {"train": tr_train, "test": tr_test},
        "bigram": {"train": bi_train, "test": bi_test},
        "trigram": {"train": tri_train, "test": tri_test},
        "disambig_trace": disambig,
        "generation": generations,
    }


# ════════════════════════════════════════════════════════════════
#  序列化（Phase 3 生成调参用：train_w 一次，反复调生成参数免重训）
# ════════════════════════════════════════════════════════════════

def save_net(ng, vocab, path, ctx_wgt=None):
    """序列化稀疏网络（W_out + 构造参数）+ 词表 + 可选 ctx_wgt。npz 压缩。"""
    src_i, slot_k, dst_j, vals = [], [], [], []
    for i in range(ng.n):
        for k in range(ng.slots):
            for j, w in ng.W_out[i][k].items():
                src_i.append(i)
                slot_k.append(k)
                dst_j.append(j)
                vals.append(w)
    params = {"n": ng.n, "slots": ng.slots, "theta": ng.theta,
              "membrane_decay": ng.membrane_decay, "eta": ng.eta, "w_max": ng.w_max,
              "wta_k": ng.wta_k, "noise_p": ng.noise_p, "noise_amp": ng.noise_amp,
              "weight_decay": ng.weight_decay, "slot_cap": ng.slot_cap,
              "stdp_pre": ng.stdp_pre, "stdp_neg": ng.stdp_neg,
              "trace_decay": ng.trace_decay, "refractory": ng.refractory,
              "inh_loose": ng.inh_loose, "std_dep": ng.std_dep, "std_rec": ng.std_rec,
              "learn_gate": ng.learn_gate}
    np.savez_compressed(path,
                        src_i=np.array(src_i, dtype=np.int32),
                        slot_k=np.array(slot_k, dtype=np.int8),
                        dst_j=np.array(dst_j, dtype=np.int32),
                        vals=np.array(vals, dtype=np.float32),
                        params=json.dumps(params).encode("utf-8"),
                        vocab=json.dumps(vocab, ensure_ascii=False).encode("utf-8"),
                        ctx_wgt=np.asarray(ctx_wgt, dtype=np.float64)
                        if ctx_wgt is not None else np.array([]))


def load_net(path, seed=42, return_ctx=False):
    """反序列化：默认返回 (SparseSchemaNet, vocab)；return_ctx=True 时返回
    (ng, vocab, ctx_wgt)（文件无 ctx_wgt 时返回 None，兼容旧模型）。"""
    z = np.load(path, allow_pickle=False)
    params = json.loads(z["params"].tobytes().decode("utf-8"))
    vocab = json.loads(z["vocab"].tobytes().decode("utf-8"))
    ng = SparseSchemaNet(rng=np.random.default_rng(seed), **params)
    src_i, slot_k, dst_j, vals = z["src_i"], z["slot_k"], z["dst_j"], z["vals"]
    _rows_from_arrays(ng, src_i, slot_k, dst_j, vals)   # 批量构建（免逐条 dict 插入）
    ctx_wgt = z["ctx_wgt"] if "ctx_wgt" in z else None
    if ctx_wgt is not None and ctx_wgt.size == 0:
        ctx_wgt = None
    if return_ctx:
        return ng, vocab, ctx_wgt
    return ng, vocab


def _rss_mb():
    """进程常驻内存（Windows 兼容，见 memory 踩坑：GetProcessMemoryInfo 需 argtypes）。"""
    try:
        import ctypes
        from ctypes import wintypes
        psapi = ctypes.windll.psapi
        kernel32 = ctypes.windll.kernel32
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        handle = kernel32.GetCurrentProcess()
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                               ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                                               wintypes.DWORD]
        psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        return round(counters.WorkingSetSize / (1024 * 1024), 1)
    except Exception:
        return None


def print_scale_report(r):
    a = r["args"]
    print("=" * 62)
    print(f"定式网络规模实验（Phase 2 稀疏版） n={a['n']} k={a['k']} 词表={r['corpus']['vocab_size']}")
    print("=" * 62)
    c = r["corpus"]
    print(f"语料：{c['n_sent']} 句（训练 {c['n_train']} / 留出 {c['n_test']}），token 总量 {c['tokens_total']}，OOV {c['oov']}")
    e = r["encoding"]
    print(f"编码预检：碰撞对(≥2重叠) {e['collisions_ge2']}/{e['pairs']} "
          f"({e['collisions_ge2']/e['pairs']*100:.3f}%)")
    s = r["scale"]
    print(f"W 稀疏：非零 {s['nnz']}（比例 {s['nnz_ratio']*100:.4f}%），"
          f"估计内存 {s['w_mem_bytes']/1e6:.1f}MB，进程 RSS {s['rss_mb']}MB")
    print(f"耗时：分词 {r['timing']['tokenize']:.1f}s 编码 {r['timing']['encode']:.1f}s "
          f"学习 {r['timing']['learn']:.1f}s 评估 {r['timing']['eval']:.1f}s")
    print("-" * 62)
    print(f"{'模型':<14}{'训练集':<10}{'留出':<10}{'hits/total'}")
    for name, d in [("SchemaNet-wsum", r["wsum"]), ("SchemaNet-trace", r["trace"]),
                    ("bigram", r["bigram"]), ("trigram", r["trigram"])]:
        acc, hits, total, _ = d["train"]
        acc2, _, _, _ = d["test"]
        print(f"{name:<14}{acc:<10.4f}{acc2:<10.4f}{hits}/{total}")
    print("-" * 62)
    print("trace 消歧：", "  ".join(
        f"{d['cue']}→{'✓' if d['hit'] else '✗'}({d['top'][0] if d['top'] else '-'})" for d in r["disambig_trace"]))
    print("生成样例：")
    for g in r["generation"]:
        print(f"  '{g['start']}' → {' '.join(g['seq'])}")
    print("=" * 62)


def save_scale_run(r, args):
    runs = Path(__file__).parent / "runs"
    runs.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = runs / f"{ts}"
    out.mkdir(exist_ok=True)
    (out / "result.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return str(out)


def main():
    p = argparse.ArgumentParser(description="定式网络规模实验（稀疏，Phase 2）")
    p.add_argument("--corpus", default="corpus_large.json")
    p.add_argument("--n", type=int, default=8192)
    p.add_argument("--k", type=int, default=16)
    p.add_argument("--kv", type=int, default=2000)
    p.add_argument("--split", type=float, default=0.8)
    p.add_argument("--stdp-pre", type=float, default=0.5)
    p.add_argument("--wmax", type=float, default=16.0)
    p.add_argument("--delta-off", type=float, default=0.05, dest="delta_off")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    r = run_sparse_language_experiment(args)
    print_scale_report(r)
    path = save_scale_run(r, args)
    print(f"留档：{path}")


if __name__ == "__main__":
    main()
