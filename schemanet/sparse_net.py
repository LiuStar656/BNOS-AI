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
from numba import njit, prange

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

    def scale_below(self, thr, factor):
        """部分缩放（sleep downscaling——de Vivo 2017）：w < thr 的条目
        ×factor（最强边豁免——"spared the largest ones"）。"""
        mask = self.w < thr
        if mask.any():
            self.w = self.w.copy()
            self.w[mask] *= factor
            return int(mask.sum())
        return 0

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
def _merge_rows(nr, offs, dsts, ws, koff, keys, deltas, w_max, clip_low,
                out_offs, out_dst, out_w, out_len):
    """多行批量合并（扁平化输入，nr 行一次算完）。语义 = 逐行 batch_update。

    第三波提速（2026-08-10）：searchsorted×m + argsort O((n+m)log) →
    线性双指针一趟 O(n+m)。大行（高频词出边 4 万+）此前每发放步全量重排，
    占 _apply_edge_updates 87%。keys 每行唯一（top/pre 集合天然唯一），
    但**并非升序**（WTA top 按 vmax×gain 降序）→ 行内先 argsort keys
    （m≤380 开销可忽略，大行成本仍由 n 主导），归并即有序。输出直接写
    out 缓冲（容量 = 总现有 + 总更新），免逐行临时数组。

    同时修复潜伏 bug：新键插入也做 [clip_low, w_max] 截断（原实现原样写
    dlt——stdp_neg>0 时写入负权重；参考实现写入 max(0, -stdp_neg)=0。
    v13.0 对拍未触发因 stdp_neg=0，第三波起分支对拍覆盖）。"""
    for r in range(nr):
        dst = dsts[offs[r]:offs[r + 1]]
        w = ws[offs[r]:offs[r + 1]]
        key = keys[koff[r]:koff[r + 1]]
        dlt = deltas[koff[r]:koff[r + 1]]
        s = out_offs[r]
        # keys 唯一 → 排序结果与稳定性无关；排序后归并（见上）
        order = np.argsort(key)
        i = 0
        j = 0
        o = 0
        n = len(dst)
        m = len(key)
        while i < n and j < m:
            kj = key[order[j]]
            if dst[i] < kj:
                out_dst[s + o] = dst[i]
                out_w[s + o] = w[i]
                i += 1
            elif dst[i] > kj:
                nv = dlt[order[j]]
                if nv > w_max:
                    nv = w_max
                if nv < clip_low:
                    nv = clip_low
                out_dst[s + o] = kj
                out_w[s + o] = nv
                j += 1
            else:
                nv = w[i] + dlt[order[j]]
                if nv > w_max:
                    nv = w_max
                if nv < clip_low:
                    nv = clip_low
                out_dst[s + o] = dst[i]
                out_w[s + o] = nv
                i += 1
                j += 1
            o += 1
        while i < n:
            out_dst[s + o] = dst[i]
            out_w[s + o] = w[i]
            i += 1
            o += 1
        while j < m:
            nv = dlt[order[j]]
            if nv > w_max:
                nv = w_max
            if nv < clip_low:
                nv = clip_low
            out_dst[s + o] = key[order[j]]
            out_w[s + o] = nv
            j += 1
            o += 1
        out_len[r] = o


@njit(cache=True, parallel=True)
def _update_v(n, slots, v, fat, raw, inp_idx, inp_amp, slot, decay, noise_p,
              noise_amp, std_dep, std_rec):
    """融合 v 更新（唤起路径）：膜电位衰减 + 噪声（逐槽，prange）+ 注入 + STD 恢复。
    噪声内化（2026-08-10 第五波）：raw = rng.random(n) 原始值，`(raw<p)*amp`
    与 numpy 位级一致（IEEE 比较/乘法确定性）——与 _train_core 同款，
    省 numpy 比较+乘两 pass（推理步 ~1.2ms → ~0.3ms）。
    语义与 `v*decay + (raw<p)*amp` + `v[:,slot]+=pulse` + `fat*=std_rec` 逐位一致。
    注入幅度（2026-08-11 韵律强调）：inp_amp[j] = 注入强度——轻声 0.5 /
    强调 1.5（教师韵律引导注意力——"叫(轻声) 爸爸(强调)"——小孩注意
    在目标词）。amp 全 1 时与旧 `+= 1.0` 位级一致。"""
    for i in prange(n):
        nz = (raw[i] < noise_p) * noise_amp
        for s in range(slots):
            v[i, s] = v[i, s] * decay + nz
    for j in range(len(inp_idx)):
        v[inp_idx[j], slot] += inp_amp[j]
    if std_dep > 0:
        for i in prange(n):
            fat[i] *= std_rec


@njit(cache=True, parallel=True)
def _wta_cand(n, slots, v, last_k_star, ref_left, theta,
              is_cand, cand_idx, cand_val):
    """融合 WTA 前置：argmax/k_star（prange）+ 候选收集（vmax≥θ 且可发放）+
    ref_left 基础 -1（对应原尾部 np.maximum(ref_left-1, 0)，候选判定用
    未递减值、与旧时序一致）。返回候选数 n_c。
    cand_idx[:n_c]/cand_val[:n_c] = 候选神经元与其 vmax（神经元号升序）。
    注意：pre_trace 衰减不放这里——STDP 在 WTA 之后仍要读未衰减痕迹
    （放这里会先于 STDP 衰减 → 语义分叉），保留在 step 尾部就地 *=。"""
    for i in prange(n):
        kmax = 0
        for s in range(1, slots):
            if v[i, s] > v[i, kmax]:
                kmax = s
        last_k_star[i] = kmax
        is_cand[i] = (v[i, kmax] >= theta) and (ref_left[i] == 0)
    n_c = 0
    for i in range(n):
        if is_cand[i]:
            cand_idx[n_c] = i
            cand_val[n_c] = v[i, last_k_star[i]]
            n_c += 1
    for i in prange(n):
        r = ref_left[i] - 1
        ref_left[i] = r if r > 0 else 0
    return n_c


@njit(cache=True, parallel=True)
def _train_core(n, slots, v, fat, raw, inp_idx, inp_amp, slot, decay, noise_p,
                noise_amp, theta, ref_left, last_k_star, is_cand, cand_idx,
                cand_val, refract_clear, std_dep, std_rec):
    """学习路径三段合一（2026-08-10 第二波提速）：衰减+噪声 → 注入 → STD 疲劳
    恢复 → refract_clear → argmax+候选收集 → ref_left 基础 -1，单 prange 内核。
    语义 = _update_v + refract_clear + _wta_cand 逐位一致（spikes 为空时传播
    跳过，两路径终态相同）：
      - 噪声内化：raw = rng.random(n) 原始值，`(raw<p)*amp` 与 numpy 位级一致
        （IEEE 比较/乘法确定性）；
      - refract_clear 在 argmax 前（= 原传播后、WTA 前的位置）；
      - 候选判定用未递减 ref_left，与旧时序一致。
    注入幅度（2026-08-11 韵律强调）：inp_amp[j]——轻声/强调两档。"""
    for i in prange(n):
        nz = (raw[i] < noise_p) * noise_amp
        for s in range(slots):
            v[i, s] = v[i, s] * decay + nz
    for j in range(len(inp_idx)):
        v[inp_idx[j], slot] += inp_amp[j]
    if std_dep > 0:
        for i in prange(n):
            fat[i] *= std_rec
    if refract_clear:
        for i in prange(n):
            if ref_left[i] > 0:
                for s in range(slots):
                    v[i, s] = 0.0
    for i in prange(n):
        kmax = 0
        for s in range(1, slots):
            if v[i, s] > v[i, kmax]:
                kmax = s
        last_k_star[i] = kmax
        is_cand[i] = (v[i, kmax] >= theta) and (ref_left[i] == 0)
    n_c = 0
    for i in range(n):
        if is_cand[i]:
            cand_idx[n_c] = i
            cand_val[n_c] = v[i, last_k_star[i]]
            n_c += 1
    for i in prange(n):
        r = ref_left[i] - 1
        ref_left[i] = r if r > 0 else 0
    return n_c


@njit(cache=True)
def _prop_accum(dst, w, edge_min, drive):
    """传播驱动单 pass 累加（2026-08-10 第二波提速）：drive[dst[e]] += w[e]，
    弱边（w < edge_min）跳过（= 原 concat 后过滤再 add.at 的语义逐位一致：
    过滤是逐元素比较、累加顺序与拼接顺序相同）。edge_min=0 全量累加。"""
    for e in range(len(dst)):
        vw = w[e]
        if vw >= edge_min:
            drive[dst[e]] += vw


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
                 w_max=16.0, wta_k=16, noise_p=0.06, noise_amp=0.2,
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
        # ── 神经调质（2026-08-11 R-STDP 三因子——用户："神经元本身就有
        #    奖惩机制"）──
        # da：多巴胺水平（全局调质——外部 release_da 间接触发；瞬时脉冲
        # 每 step 衰减回基线）。elig：神经元级资格迹（"刚才活动过"的临时
        # 记忆——指数衰减——奖励时凭它做时间信用分配）。
        # 学习调制：Δw = STDP × (1 + DA_GAIN × RPE)——RPE（奖赏预测误差）
        # 正强化 LTP、负抑制——三因子规则（Izhikevich 2007 / Florian 2007）；
        # RPE 内化（2026-08-11 治疗三）：da_expected 为 TD 预期——网络
        # 预期奖赏——RPE = 实际 − 预期——稳定奖励 RPE→0（熟悉）、意外
        # 奖励正 RPE（新奇）、落空负 RPE（失望）——对话奖赏内化为预期。
        self.da = 0.0
        self.da_expected = 0.0    # 奖赏预期（TD——历史平均）
        self.td_rate = 0.1        # 预期学习率（Schultz 1997——TD 更新）
        self.last_rpe = 0.0       # 最近奖赏预测误差（学习调制用）
        self.elig = np.zeros(n)
        self.da_gain = 1.0
        self.da_decay = 0.9
        self.elig_decay = 0.9
        self.da_max = 2.0
        # 惩罚力度系数（2026-08-11 用户："惩罚效果不是一时半会就出现的，
        # 加大力度"）：da<0 时资格迹兑现增量 ×punish_factor（默认 3——
        # 比奖励陡——惩罚反应更快）
        self.punish_factor = 3.0
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

    def _decay_elig_pairs(self):
        """突触级资格迹指数衰减（τ_e——"刚活动过"的临时记忆）：
        每拍 ×elig_decay；跌破阈值清除（防无限膨胀——只留最近活跃配对）。"""
        if not self._elig_pairs:
            return
        ep = self._elig_pairs
        for k in list(ep):
            v = ep[k] * self.elig_decay
            if v < 0.05:
                del ep[k]
            else:
                ep[k] = v

    def release_da(self, amount):
        """外部唯一奖惩接口（间接触发——不直接改边）：注入多巴胺调质。
        正 = 奖赏（后续学习强化）、负 = 惩罚（抑制学习）。瞬时脉冲，
        随后每 step 指数衰减回基线。
        RPE 内化（2026-08-11 治疗三）：实际 DA 到达 → 计算奖赏预测误差
        RPE = da − da_expected → TD 更新预期（预期跟踪实际）——网络对
        "这样说会得到多少好处"形成预期——稳定奖励 RPE 趋 0（熟悉——
        对话本身成为奖赏源）、意外奖励正 RPE（新奇——强化学）、
        落空负 RPE（失望——抑制学）。
        资格迹兑现（2026-08-11——R-STDP 三因子补全，Izhikevich 2007
        Δw = DA × e）：奖励/惩罚到达时——对"刚才活动过"的神经元
        （elig>阈值——最近发放过）的**出边**按 RPE×elig 兑现——
        **时间信用分配**：行为发生在几拍前、奖励延迟到达——凭资格
        迹归因到当时的突触（distal reward problem 的解——之前 elig
        只写不读——三因子缺兑现环节）。正 RPE 强化出边（这个行为
        被奖励）、负 RPE 压制出边（这个行为被惩罚——LTD）。"""
        self.da = max(-self.da_max, min(self.da_max, self.da + amount))
        self.last_rpe = self.da - self.da_expected
        self.da_expected += self.td_rate * self.last_rpe
        # 突触级资格迹兑现（2026-08-11——Izhikevich 2007 Δw = η·DA·e_ij）：
        # 奖惩到达 → 只对"刚活动过的配对"（_elig_pairs 有标）的边操作——
        # da>0 强化该配对、da<0 压制该配对（LTD）。**配对级**——压
        # 「拿→香蕉」（错配——刚配对有标）不碰「拿→苹果」（未配对无标）
        # ——不误伤（用户："不怕说错，怕用机制改不过来"——错误可逆且精准）。
        # 门控用 da 本身（v4——RPE 只内化不门控——防预期抬高后无奖励
        # 教学误压旧知识）。神经元级 elig 兑现已废弃（误伤根因——不再使用）。
        # 惩罚力度（2026-08-11 用户："惩罚效果不是一时半会就出现的，加大
        # 力度"）：da<0（惩罚）时增量 ×punish_factor（默认 3——比奖励陡——
        # 生物对应：惩罚/负反馈反应更快——Anderson 2022 抑制诱发遗忘 SIF——
        # 被压的联想快速变弱）。正奖励保持 eta 原力度。
        if abs(self.da) > 0.05 and self._elig_pairs:
            mod = self.da_gain * self.da
            factor = self.punish_factor if mod < 0.0 else 1.0
            dlt_base = self.eta * mod * factor
            for (pre, post), e in list(self._elig_pairs.items()):
                row = self.W_out[pre][0]
                if post in row:
                    row[post] = min(self.w_max,
                                    max(0.0, row[post] + dlt_base * e))

    def build_track_map(self, pats, skeletons=None):
        """轨道映射构建：定式词神经元 → 其槽位神经元（上下文消歧用）。
        由持有词表的调用方（场景/教学）在定式注册后调用。
        返回 self.track_map（dict: 词神经元 id → 槽位神经元集合）。

        结构下沉 v2（2026-08-11 用户："结构怎么放到网络上"——从 dict
        元数据到突触结构）：轨道信息**从突触边结构重建**——不读 skeletons
        dict（dict 仅构建脚手架）：
          · 槽位神经元 = 有"词→它"入边 且 "它→词/槽"出边的中间神经元
            （synfire chain 节点——角色神经元 role）
          · 词→槽 强边 = 入口（词是入口词）
          · 槽→词 强边 = 绑定（role-filler binding——"词在槽"= 边存在）
          · 槽→槽 强边 = 主干（轨道推进）
        实现：收集 W_out 中 w≥主干强度（64 档）的边——源是词（pats 有）
        → 目标为槽（入边来自词、出边到词）——重建 track_map/readout。
        无 skeletons 时（纯突触）也能工作——dict 剥离后网络仍运行。"""
        self.track_map = {}
        self._track_slots = set()
        self._track_readout = {}
        self._track_readout_nwords = {}
        # ── 从突触结构识别轨道（不依赖 skeletons）──
        # 强边（w ≥ 16——主干/绑定档）参与轨道；弱边（联想）不参与
        STRONG = 16.0
        # ① 收集强边：src → dst（slot0）
        strong = {}    # src -> set(dst)
        for i in range(self.n):
            row = self.W_out[i][0]
            if not row:
                continue
            dsts = {int(j) for j, w in row.items() if w >= STRONG}
            if dsts:
                strong[i] = dsts
        # ② 识别槽位神经元：有"词→它"入边（src 是词）且"它→词"出边
        #    或"它→槽"出边（轨道中间节点）
        #    槽 = 不是词表词（不在 pats 反查）但有强出边的神经元
        #    （词神经元在 pats 里——槽神经元不在——结构识别）
        pats_set = set()
        for w, ns in pats.items():
            pats_set.update(int(x) for x in ns)
        # 槽候选：有入边的非词神经元
        for src, dsts in strong.items():
            if src in pats_set:
                continue      # src 是词——不是槽
            # src 是槽候选（非词但有强出边）
            self._track_slots.add(src)
        # ③ 轨道映射：词 → 其直连槽（词→槽 强边）
        for src, dsts in strong.items():
            if src not in pats_set:
                continue      # src 是槽——跳过（主干边）
            # src 是词：出边目标是槽（轨道入口）
            for d in dsts:
                if d in self._track_slots:
                    self.track_map.setdefault(int(src), set()).add(int(d))
        # ④ 读出映射：槽 → 绑定词（槽→词 强边）
        for src in self._track_slots:
            row = self.W_out[src][0]
            words = {int(j) for j, w in row.items()
                     if w >= STRONG and int(j) in pats_set}
            if words:
                self._track_readout[src] = words
                # 绑定词数 = 词数（按 pats 分组——每词 k 神经元）
                k_word = max((len(pats.get(w, [])) for w in
                              (next((w for w, ns in pats.items()
                                     if int(x) in ns), None)
                               for x in words) if w), default=4)
                self._track_readout_nwords[src] = \
                    max(1, len(words) // k_word) if k_word else len(words)
        self._track_slots_list = np.array(sorted(self._track_slots),
                                           dtype=np.int64)
        return self.track_map

    def reset(self):
        self.v = np.zeros((self.n, self.slots))
        self.spikes = np.zeros(self.n)
        self.last_k_star = np.zeros(self.n, dtype=int)
        self.pre_trace = np.zeros(self.n)
        self.refractory_left = np.zeros(self.n, dtype=int)
        # WTA 融合内核工作区（预分配，避免每步临时分配）
        self._is_cand = np.zeros(self.n, dtype=bool)
        self._cand_idx = np.zeros(self.n, dtype=np.int64)
        self._cand_val = np.zeros(self.n)
        # 发放缓冲（第六波 Step3：复用避免每步 1.2MB 分配；返回给调用者的是
        # 本缓冲——调用方须步内消费（np.where 等即时操作），跨步持有会被覆写）
        self._spikes_buf = np.zeros(self.n)
        # 传播 drive 缓冲（第七波：预分配 (slots, n)，每槽清零复用，免每步分配）
        self._drive = np.zeros((self.slots, self.n))
        # 定向传播链缓冲（2026-08-11）：跨槽 drive 累计——唤起路径 WTA
        # 候选过滤用（"被当前词驱动到的神经元"）
        self._drive_any = np.zeros(self.n)
        # 轨道映射（2026-08-11 上下文消歧）：定式词神经元 → 其槽位神经元。
        # 唤起时当前发放词是定式词 → 槽位候选加权（轨道优先——在轨道上
        # 只走轨道——Vreeswijk 上下文消歧 / Sejnowski 定向流）。由持有词表
        # 的调用方在定式注册后调 build_track_map 构建；空 = 关闭。
        self.track_map = {}
        self._track_slots = set()
        self._track_readout = {}        # 槽位神经元 → 绑定词神经元（词读出）
        self._track_slots_list = np.array([], dtype=np.int64)
        self._last_inp = np.array([], dtype=np.int64)   # 上一拍注入（词终端判定）
        # 本句注入上下文（2026-08-11 论元消歧）：本句累积注入的词（叫X→回答X
        # 的 X 来自输入）——空闲 5 拍视为句边界清空（跨句不残留论元）。
        self._ctx_inp = set()
        self._ctx_idle = 0
        # 上一注入拍记录（2026-08-11 相邻配对打标用——不被间隔拍清空）
        self._prev_inp = set()
        # 突触级资格迹（2026-08-11 用户："不怕说错，怕用机制改不过来"——
        # 神经元级 elig 惩罚误伤：压「拿香蕉」时把 拿→苹果 也压了。Izhikevich
        # 2007 / Florian 2007：资格迹是**每条突触的配对标记**（synaptic tag）
        # ——e_ij（pre→post 对）——奖惩只作用于"刚活动过的配对"——惩罚只
        # 压错配、不误伤。稀疏 dict：{(pre, post): 资格值}——STDP/Hebbian
        # 写边时对实际修改的配对打标；每拍衰减；release_da 兑现 Δw=η×RPE×e
        # （只对有标的边操作）。神经元级 self.elig 保留作兼容（不再用于兑现）。
        self._elig_pairs = {}
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
        # 第六波 Step4：属性局部化（每步省 ~40 次 self 属性访问的 Python 帧
        # 开销；数组局部变量 = 同一对象，内核就地修改，无需写回）。
        n = self.n
        slots = self.slots
        v = self.v
        fat = self.fat
        spikes = self.spikes
        last_k = self.last_k_star
        ref_left = self.refractory_left
        pre_trace = self.pre_trace
        # 提速第二波（2026-08-10）：噪声内化 + 训练路径三段合一（_train_core）。
        # 学习路径（spikes 为空）→ 单 prange 内核完成 衰减+噪声+注入+疲劳恢复+
        # refract_clear+argmax+候选+ref-1；唤起路径（spikes 非空）→ 保持分步
        # （传播必须插在 update_v 与 WTA 之间）。两路径与参考实现逐位一致。
        # 底噪学习门控（2026-08-11 底噪过度设计诊断）：_drive_any 统一在本步
        # 开头清零——学习路径（不传播）不残留上一拍驱动值，保证"本拍是否有
        # 信号来源"判定准确（注入 or 传播驱动；噪声越阈发放两者皆无→不学）。
        self._drive_any[:] = 0.0
        # _sig_spikes：本拍"信号发放"掩码（学习态 pre_trace 只加信号发放——
        # 噪声词不入痕迹；间隔拍 top 空 → 全 0 → 痕迹只衰减不添加）
        if not hasattr(self, "_sig_spikes"):
            self._sig_spikes = np.zeros(n)
        else:
            self._sig_spikes[:] = 0.0
        raw = self.rng.random(n)   # 原始均匀值（内核内做 <p / ×amp，位级一致）
        inp_idx = np.nonzero(input_pulse)[0]
        # 本句注入上下文维护（2026-08-11）：有注入 → 累积论元 + 空闲计数归零；
        # 无注入 → 空闲 +1，超 5 拍视为句边界 → 清空（跨句不残留——防
        # 「叫爷爷」后隔很久输入「爸爸」时爷爷仍算论元）。
        if len(inp_idx):
            # 新行为开始（上一拍空闲或首拍注入）→ 清突触级资格迹
            # （2026-08-11）：每个行为 = 新的配对窗口——旧行为配对标
            # 清零——奖惩只作用于本次行为的配对（拿→香蕉），不误伤历史
            # 配对（拿→苹果——上次教学残留标）——精准惩罚（用户："不怕
            # 说错，怕用机制改不过来"——错误可逆且不误伤）。同句内连续
            # 注入（论元补充）不重清（_ctx_idle==0 保持累积）。
            if self._ctx_idle > 0:
                self._elig_pairs.clear()
            # 句内序列配对打标（2026-08-11——资格迹不依赖 pre_trace——
            # trace 半衰期 1 拍撑不到下一词）：**相邻注入词**配对（当前词
            # ↔ 上一注入词——本次行为的序列配对）——「叫 爸爸」标 (叫,爸爸)；
            # 不与历史 ctx 词配对（防惩罚「叫爷爷」误压历史 叫→爸爸——
            # 用户 2026-08-11："建边是正常的"——配对=本次行为窗口）。
            # 配对窗口（_prev_inp——上一注入拍记录，不被间隔拍清空）
            # 独立于论元上下文（_ctx_inp——累积——论元回声用）。
            if self._ctx_idle > 0:
                self._prev_inp = set()     # 新行为开始——清上一词
            for w_new in inp_idx:
                for w_old in self._prev_inp:
                    # 标"本次活跃的相邻配对"（新旧都标——2026-08-11 颗粒度
                    # 修正：用户"出现爸爸/叫为什么不惩罚"——惩罚应作用于
                    # 本次活跃的边（叫→爸爸——无论元提前答=错→惩罚压制）；
                    # 奖励强化同边（叫爸爸→爸爸=对→强化）——**靠场景比例
                    # 决定净效果**（正确教学多→净强化；错误场景多→净弱化
                    # ——Izhikevich Δw=DA×活跃边原语义）。不误伤靠教学
                    # 协议（只在错误场景惩罚）——不是引擎过滤。
                    if int(w_old) != int(w_new):
                        self._elig_pairs[(int(w_old), int(w_new))] = 1.0
            self._prev_inp = set(int(x) for x in inp_idx)
            self._ctx_inp.update(int(x) for x in inp_idx)
            self._ctx_idle = 0
        else:
            self._ctx_idle += 1
            if self._ctx_idle > 5:
                self._ctx_inp = set()
        # 注入幅度（2026-08-11 韵律强调）：脉冲值即强度——轻声 0.5 /
        # 强调 1.5；默认全 1（= 旧 +1.0 注入，位级一致）
        inp_amp = input_pulse[inp_idx] if len(inp_idx) else np.zeros(0)
        if not spikes.any():
            n_c = _train_core(n, slots, v, fat, raw,
                              inp_idx, inp_amp, slot, self.membrane_decay,
                              self.noise_p, self.noise_amp, self.theta,
                              ref_left, last_k,
                              self._is_cand, self._cand_idx, self._cand_val,
                              self.refract_clear and self.refractory > 0,
                              self.std_dep, self.std_rec)
        else:
            # 第五波：噪声内化进 _update_v（raw 直传，内核内 <p/×amp，位级一致）
            _update_v(n, slots, v, fat, raw,
                      inp_idx, inp_amp, slot, self.membrane_decay,
                      self.noise_p, self.noise_amp,
                      self.std_dep, self.std_rec)

            # 分槽传播（稀疏：只遍历发放神经元出边的非零行，镜像 numpy 批量累加）
            # 第六波 Step2/3：一次扫描拿发放索引（兼作 any 判断，免双扫描）→
            # 按主导槽掩码分桶（掩码保序 → senders 集合与 np.where 相同）
            fire_idx = np.where(spikes > 0)[0]
            if len(fire_idx):
                # 联想/推理分域（2026-08-11）：on_track 在传播前判定——
                # 本拍发放含槽位/定式词 = 轨道激活 → 传播只走主干档边
                # （联想边被 edge_min 过滤）；无轨道 = 思考（自由联想）。
                on_track = any(s in self._track_slots for s in fire_idx) \
                    or any(s in self.track_map for s in fire_idx)
                # 词读出终端（2026-08-11 模式完成即止）：轨道上（senders
                # 含槽位）时——绑定词（定式词）是"读出终端"——不传播
                # （读出即止——不驱动语料漂移——海马重放读完即收敛）。
                # 槽位继续传播（主干推进）；注入的定式词（入口）不受影响
                # （senders 不含槽位时不过滤）。
                if self.track_map:
                    # 词读出终端（2026-08-11 模式完成即止）：
                    # ① 槽位：总是传播（主干推进）
                    # ② 定式词：仅当"上一拍注入"（入口词进轨道）可传播；
                    #    读出的绑定词 → 终端（不传播——不驱动语料/不回读）
                    # ③ 非定式词（语料）：自由联想——照常传播
                    last_inp_set = set(int(x) for x in self._last_inp)
                    keep_mask = [
                        int(s) in self._track_slots or
                        int(s) not in self.track_map or
                        int(s) in last_inp_set
                        for s in fire_idx]
                    fire_idx = fire_idx[keep_mask]
                self._drive_any[:] = 0.0   # 定向链：跨槽 drive 累计（本拍清零）
                for k in range(slots):
                    senders = fire_idx[last_k[fire_idx] == k]
                    if len(senders):
                        # 第七波：drive 预分配复用（免每槽 np.zeros 分配；
                        # 清零→累加→v+=→下槽清零，语义与原 np.zeros 一致）
                        drive_k = self._drive[k]
                        drive_k *= 0.0
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
                                    ws.append(e[1] * (1.0 - fat[i]))
                                else:
                                    ws.append(e[1])
                        if ds:
                            all_dst = np.concatenate(ds)
                            all_w = np.concatenate(ws)
                            if len(all_dst):
                                # 第二波提速：add.at → numba 单 pass（edge_min 过滤内嵌，
                                # 免 concat 后过滤 pass；累加顺序一致 → 位级一致）
                                # 联想/推理分域（2026-08-11 下沉②——用户："突触连接连的
                                # 是联想链，推理链走主干"）：**轨道激活时**传播只走主干档
                                # 边（≥16——联想边弱档被过滤——联想不出现在推理 k）；
                                # 无轨道（思考/自由联想）→ 全量传播（联想可用）。
                                _prop_accum(all_dst, all_w,
                                            self.edge_min if not on_track
                                            else max(self.edge_min, 16.0),
                                            drive_k)
                        if self.inh_norm > 0:  # 层1 全局活动抑制：除法归一化
                            tot = drive_k.sum()
                            if tot > self.inh_norm:
                                drive_k *= self.inh_norm / tot
                        v[:, k] += drive_k
                        self._drive_any += drive_k   # 定向链：跨槽累计

            # 不应期硬清：处于不应期的神经元膜电位清零（防组装自振复燃——
            # 刚发放过的组装被自身模式内互连驱动，不应期一过立即复燃）
            if self.refract_clear and self.refractory > 0:
                v[ref_left > 0] = 0.0

            # 主导槽 + WTA（融合内核：argmax + 候选收集 + 不应期基础 -1，prange 并行）
            n_c = _wta_cand(n, slots, v, last_k,
                            ref_left, self.theta,
                            self._is_cand, self._cand_idx, self._cand_val)
        candidates = self._cand_idx[:n_c]
        vmax_c = self._cand_val[:n_c]   # = v[candidates, k_star[candidates]]，神经元号升序
        # ── 定向传播链（2026-08-11 用户："动力学传播链应该按突触权重来实现"）──
        # 唤起路径（spikes 非空）时：候选 = 被当前发放词驱动到的神经元
        # （drive > 0——当前词出边按权重驱动）∪ 本拍注入目标（外部输入）。
        # 取代"全网络汇聚竞争"——传播链沿突触权重定向流动，不被高频 hub
        # （入边汇聚统计）劫持（Vreeswijk 上下文消歧 / Sejnowski 定向流）。
        # 学习路径（spikes 空）保持全局 WTA（训练需共同发放竞争）。
        if spikes.any() and len(candidates):
            inp_mask = np.zeros(n, dtype=bool)
            inp_mask[inp_idx] = True
            keep = (self._drive_any > 0) | inp_mask
            # 轨道硬过滤（2026-08-11 用户："就算突触权重有多高，推理链
            # 的时候不符合都不应该出现在 k 里"）：轨道上（本拍发放含
            # 定式词或槽位——推理链已激活）→ k 只收推理链候选：
            #   ① 槽位（主干推进——k-(k-1) 逐拍）
            #   ② 注入词（论元回声——X 来自输入）
            #   ③ 轨道绑定词（当前槽位读出——固定内容补全 / 论元）
            #   联想边（词→词共现——思考用）权重再高也被硬剔——
            #   推理链时联想不参与（Vreeswijk 上下文消歧硬版——
            #   "轨道上只走轨道"从"压倒"升级为"排除"）。
            # 轨道未激活（无定式词/槽位发放）→ 联想照常（思考场景）。
            if self.track_map:
                senders_set = set(np.where(spikes > 0)[0])
                on_track = any(s in self._track_slots for s in senders_set) \
                    or any(s in self.track_map for s in senders_set)
                if on_track:
                    # 当前槽位绑定词（2026-08-11 修正——用户："这不是补全，
                    # 也是指令啊"）：轨道读出**统一论元回声**——无论绑定
                    # 几个词（唯一/多绑定同构）——「跟我一起说X」和「叫X」
                    # 一样是动词框架+论元：内容/论元来自输入（_ctx_inp），
                    # 不是"补全历史绑定"。输入动词单独（「跟我一起说」）
                    # → 无论元 → 只出动词（不补全内容——与「叫」单独只
                    # 出「叫」一致）。
                    track_words = set()
                    for s in senders_set:
                        track_words |= self._track_readout.get(s, set())
                    cur_inp = set(self._ctx_inp)
                    if cur_inp:
                        track_words &= cur_inp    # 论元回声：只读当前注入
                    # cur_inp 空（无注入的空拍——轨道补全读出）→ 保持
                    # track_words（不剔内容——槽1→内容 传播拍无注入时
                    # 内容该读出——2026-08-11 修复：空拍取交集把内容剔了）
                    is_slot = np.isin(candidates, self._track_slots_list)
                    is_inp = np.isin(candidates, inp_idx)
                    is_track_word = np.isin(
                        candidates,
                        np.array(sorted(track_words), dtype=np.int64)) \
                        if track_words else np.zeros(len(candidates),
                                                     dtype=bool)
                    keep_track = is_slot | is_inp | is_track_word
                    # keep 全长（n）→ 用候选神经元 id 置 False（联想硬剔）
                    keep[candidates[~keep_track]] = False
                    # 生成链修复（2026-08-11 用户："带出绑定词很明显就是
                    # 生成链出现问题"）：被剔联想候选**同步清零膜电位**——
                    # 联想词被剔但 v 残留 → 下一拍学习路径（全局 WTA 无
                    # 轨道过滤）把它放出——生成链泄漏（输入「叫爷爷」带
                    # 出妈妈/爸爸）。剔 = 清 v（与词层消歧 keep2 的
                    # v[drop]=0 一致——联想不出现在生成链，也不残留）。
                    drop_track = candidates[~keep_track]
                    if len(drop_track):
                        v[drop_track, :] = 0.0
                    # 被剔联想候选记录（2026-08-11 惩罚压制目标）：推理时
                    # 被轨道剔除的联想词（爸爸——不该出现在 k）——惩罚
                    # 到达时压它们的入边（见学习块 LTD——"惩罚压制不掉
                    # 说明惩罚机制有问题"——被剔候选=错误联想=惩罚对象）
                    if hasattr(self, "_punish_cands"):
                        self._punish_cands.update(
                            int(x) for x in drop_track)
            # 轨道优先（上下文消歧 2026-08-11）：当前发放词是定式词 →
            # 其槽位候选加权（×10——在轨道上只走轨道——Vreeswijk 消歧 /
            # Sejnowski 定向流）。非轨道候选不被排除，仅被轨道压倒。
            track_boost = np.zeros(len(candidates), dtype=bool)
            if self.track_map:
                for s in np.where(spikes > 0)[0]:
                    slots = self.track_map.get(int(s))
                    if slots:
                        for ci in range(len(candidates)):
                            if candidates[ci] in slots:
                                track_boost[ci] = True
            keep_idx = keep[candidates]
            if not keep_idx.all():
                candidates = candidates[keep_idx]
                vmax_c = vmax_c[keep_idx]
                track_boost = track_boost[keep_idx]
            if track_boost.any():
                vmax_c = vmax_c * np.where(track_boost, 10.0, 1.0)
            # 词层上下文消歧（2026-08-11）：定式词/轨道上时——
            # ① 过渡拍（senders 全是词）：词候选全剔（只走轨道槽位）
            # ② 轨道上（senders 含槽位）：词候选只保留当前槽位绑定词
            #    （槽→词读出——轨道上只读轨道内容；教学链词/语料剔除）
            # 消歧 v2（2026-08-11 用户："叫X→回答X"规则）：allowed 限定为
            #   **当前注入词 ∩ 绑定词**——听到「叫妈妈」→ 注入{叫,妈妈}
            #   → 槽1 绑定词 {爸爸,妈妈} ∩ 注入 = {妈妈} → 只读妈妈
            #   （爸爸是历史绑定——不读出）。轨道上的词读出 = 论元回声
            #   （X 已注入——回答 X——不是死记历史绑定词）。
            # 论元保留 v3（2026-08-11 用户测试叫爷爷/奶奶）：**当前注入的
            #   词无条件保留**（is_inp）——论元 X（妈妈/爷爷/奶奶）不是
            #   绑定词时不能被轨道过滤剔掉（"叫X→回答X"的 X 来自输入——
            #   回答 = 论元回声）。过滤只剔"非注入的语料词"。
            # 固定内容型 v4（2026-08-11 用户"跟我一起说→我的名字叫守一"）：
            #   槽位绑定词（2026-08-11 修正——用户："这不是补全，也是指令
            #   啊"）：统一论元回声——无论绑定几个词，「跟我一起说X」和
            #   「叫X」同构（动词框架+论元）——内容/论元来自输入，不补全。
            if self._track_readout:
                senders_set = set(np.where(spikes > 0)[0])
                has_slot = any(s in self._track_slots for s in senders_set)
                has_track_word = any(s in self.track_map for s in senders_set)
                if has_slot or has_track_word:
                    allowed = set()
                    if has_slot:
                        # 当前句注入词（本句累积——论元——叫X的X）
                        cur_inp = set(self._ctx_inp)
                        for s in senders_set:
                            allowed |= self._track_readout.get(s, set())
                        if cur_inp:
                            # 论元回声：只读当前注入的绑定词（统一——
                            # 唯一/多绑定同构；输入动词单独→无论元→
                            # 不读出内容——不补全）
                            allowed &= cur_inp
                        # cur_inp 空（无注入空拍——轨道补全读出）→ 保持
                        # allowed（内容该读出——与硬过滤一致修复）
                    is_slot = np.isin(candidates, self._track_slots_list)
                    is_word = np.isin(
                        candidates,
                        np.array(sorted(allowed), dtype=np.int64)) \
                        if allowed else np.zeros(len(candidates), dtype=bool)
                    is_inp = np.isin(candidates, inp_idx)  # 论元无条件保留
                    keep2 = is_slot | is_word | is_inp
                    if not keep2.all():
                        # 消歧剔除的候选清零膜电位（2026-08-11 框架语义：
                        # 历史绑定词非当前论元 → 彻底清零——×0.05 不够
                        # （64×0.05=3.2 仍过阈——下一拍学习路径全局 WTA
                        # 无轨道消歧会放出）；清零 = 槽位填充语义——槽被
                        # 当前论元实例化，历史填充物不参与读出）。
                        drop = candidates[~keep2]
                        if len(drop):
                            v[drop, :] = 0.0
                        candidates = candidates[keep2]
                        vmax_c = vmax_c[keep2]
        k_star = last_k                 # 内核已就地写入本步 argmax
        if len(candidates) > self.wta_k:
            # 增益调制：WTA 排序用 vmax×gain（候选判定仍用原始 v≥θ），
            # 高价值词（如"不要"）被驱动后优先发放
            key = vmax_c * self.gain[candidates]
            # 注意：不用 argpartition——并列 key 时它与 argsort 的 top-k 集合
            # 可能不同（发放分叉 → 网络演化连锁分叉，实测 105 万边差异），
            # 语义铁律优先（2026-08-10 验证后回退）。
            top = candidates[np.argsort(key)[::-1][: self.wta_k]]
        else:
            top = candidates

        new_spikes = self._spikes_buf   # 第六波 Step3：预分配复用（步内覆写）
        new_spikes[:] = 0.0
        if len(top):
            # 侧抑制清扫（v13.2，2026-08-10）：把"过阈但没被选中"的候选 v 压低
            # ×inh_loose——每步清扫，防止老候选越积越高霸榜（超临界雪崩引擎）。
            # 生物对应：lateral inhibition（发放神经元抑制邻近未发放者）。
            if self.inh_loose < 1.0 and len(candidates) > len(top):
                # 第五波：setdiff1d（unique+isin，候选上万时 ~2.9ms）→ 布尔掩码
                # （148k 标记 + fancy 取，~0.2ms）。结果集合一致；losers 用于
                # 逐元素乘法，顺序无关 → 位级一致。
                mark = np.zeros(n, dtype=bool)
                mark[top] = True
                losers = candidates[~mark[candidates]]
                if len(losers):
                    v[losers, :] *= self.inh_loose
            new_spikes[top] = 1.0
            if self.std_dep > 0:
                # 发放 → 疲劳累积（2026-08-11 sAHP 语义修正：原"设置"fat=std_dep
                # 无累积——高频发放无法形成临界频率抑制；改为 += 累积（每次发放
                # +Δ——后超极化式）——std_rec 恢复与其竞争——临界频率动力学）
                fat[top] = np.minimum(fat[top] + self.std_dep, 1.0)
            if self.learn_gate:
                # 底噪学习门控（2026-08-11 底噪过度设计诊断）：只有本拍有
                # 信号来源（注入脉冲 或 传播驱动）的发放才参与学习——噪声
                # 越阈发放（无注入无 drive——纯底噪）不写边：防止
                # 「注入词→随机词」STDP 污染（30 次教学 712 条随机边实证，
                # 见 docs/reports/05/[REPORT]-底噪过度设计诊断）。
                signal = len(inp_idx) > 0 or bool(self._drive_any.any())
                if signal:
                    # 信号过滤：top 里只保留"有信号"的发放神经元——学习路径
                    # （spikes 空）是全局 WTA，注入拍 top 会混入同拍噪声越阈词
                    # （Hebbian 两两互连 → 猫↔随机词 w=1.2/次的污染链）；
                    # 唤起路径 top 已被 drive|注入过滤，再滤等价无变化。
                    inp_mask = np.zeros(n, dtype=bool)
                    inp_mask[inp_idx] = True
                    sig_mask = inp_mask | (self._drive_any > 0)
                    top_sig = top[sig_mask[top]]
                    if not len(top_sig):
                        signal = False      # 理论不发生（signal 来源必在 top）
                    else:
                        top_arr = np.asarray(top_sig, dtype=np.int32)
                        # Hebbian/STDP 批量合并（2026-08-10 numba 提速）：原 O(k²)/O(k×pre)
                        # Python 双循环 + 每对 row.get() 全部移到 numba 内核 _merge_rows，
                        # 语义逐位一致：存在键累加 + w_max 截断 + stable 插入（= batch_update）。
                        # R-STDP 三因子（2026-08-11 修复 v3）：学习增量 × DA 门控
                        # ——Δw = STDP × DA_GAIN×RPE，**双极调制**：
                        #   · da≈0（无奖励）→ mod=0 → 不建边（训狗语义：
                        #     零食是学习开关——无奖励纯复读零改动）
                        #   · da>0（奖励）→ mod>0 → 强化（LTP）
                        #   · da<0（惩罚）→ mod<0 → **压制（LTD——负向
                        #     学习压边）**——用户（2026-08-11）："应该用
                        #     惩罚给压制掉，如果惩罚压制不掉说明惩罚机制
                        #     就有问题"。原 v2 把负 mod 归零（惩罚=不学）
                        #     ——惩罚形同虚设——联想边（叫→爸爸）永远压
                        #     不掉。v3：负 RPE → 负增量 → 边权重下降。
                        # v4 门控用 DA 本身（2026-08-11——Izhikevich 原式
                        # Δw = DA×e）：RPE（da−da_expected）在预期被抬高后
                        # （教学苹果时多次给零食）——无奖励教学（da=0）会
                        # 产生负 RPE → **无意的惩罚**——教学新内容（香蕉）
                        # 时把旧知识（苹果边）压掉。门控改用 **da 本身**：
                        # da=0 不学、da>0 强化、da<0 惩罚——预期（RPE）
                        # 只用于 da_expected 的 TD 内化，不参与门控。
                        mod = self.da_gain * self.da
                        # 负 mod 保留（LTD 压边）；0 保持（无奖励不学）
                        # 惩罚压制被剔联想（2026-08-11 用户："应该用惩罚给
                        # 压制掉"）：da<0 时——推理中被轨道剔除的联想候选
                        # （_punish_cands——错误联想）的**入边**被负向调制
                        # （LTD——压边）。被剔候选=不该出现的联想=惩罚对象
                        # ——压它的驱动边（如 叫→爸爸——叫爷爷时爸爸被剔
                        # → 压 叫→爸爸 → 联想被惩罚压制，边保留但变弱）。
                        if mod < 0.0 and getattr(self, "_punish_cands", None):
                            pc = np.array(sorted(self._punish_cands),
                                          dtype=np.int32)
                            self._punish_cands.clear()
                            for j in pc:
                                for i in range(self.n):
                                    row = self.W_out[i][0]
                                    if j in row:
                                        row[j] = max(0.0,
                                                     row[j] + mod * 0.1)
                        else:
                            self._punish_cands = set()
                        # Hebbian：共同发放对 (a, c) → W[c][k_star[a]][a] += eta（排除自连接）
                        # 行 (c, ka)，键 = {a ∈ top : k_star[a]==ka, a≠c}
                        # 惩罚安全（2026-08-11 用户："建边是正常的"）：mod<0
                        # （惩罚）时 Hebbian 跳过——**不压历史已学边**（叫→
                        # 爸爸——不是本次行为的错）——惩罚只经资格迹作用于
                        # "本次新建的配对"（_elig_pairs——不存在的边）——
                        # 精准惩罚不误伤（正 mod 照常强化共发放对）。
                        if mod >= 0.0:
                            row_to_a = {}
                            for a in top_arr:
                                ka = int(k_star[a])
                                for c in top_arr:
                                    if a != c:
                                        row_to_a.setdefault((int(c), ka), []).append(int(a))
                            groups = [(self.W_out[c][ka],
                                       np.asarray(aset, dtype=np.int32),
                                       np.full(len(aset), self.eta * mod))
                                      for (c, ka), aset in row_to_a.items()]
                            self._apply_edge_updates(groups, self.w_max)
                            # 突触级资格迹打标（2026-08-11）：实际被写边的配对
                            # (pre→post)——Hebbian 是 top 内互连（双向——c→a）
                            for (c, ka), aset in row_to_a.items():
                                for a in aset:
                                    self._elig_pairs[(int(c), int(a))] = 1.0
                        # STDP：前驱痕迹 → 当前发放，学 W[后继 ← 前驱]（只正向）
                        if (self.stdp_pre > 0 or self.stdp_neg > 0) and self.pre_trace.any():
                            pre_idx = np.where(self.pre_trace > self.trace_thres)[0]
                            if self.stdp_pre > 0 and len(pre_idx):
                                # 行 (pp, k_star[jj])，键 = {jj ∈ top : jj≠pp}
                                # 惩罚安全（2026-08-11）：mod<0 时 STDP 跳过
                                # （不压历史前驱边——惩罚只经资格迹作用）
                                if mod >= 0.0:
                                    row_to_a = {}
                                    for jj in top_arr:
                                        kj = int(k_star[jj])
                                        for pp in pre_idx:
                                            if jj != pp:
                                                row_to_a.setdefault((int(pp), kj), []).append(int(jj))
                                    groups = [(self.W_out[pp][kj],
                                               np.asarray(aset, dtype=np.int32),
                                               np.full(len(aset), self.stdp_pre * mod))
                                              for (pp, kj), aset in row_to_a.items()]
                                    self._apply_edge_updates(groups, self.w_max)
                                    # 打标：前驱→当前发放（pre→post 配对）
                                    for (pp, kj), aset in row_to_a.items():
                                        for jj in aset:
                                            self._elig_pairs[(int(pp), int(jj))] = 1.0
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
                        # 信号发放掩码（pre_trace 只加信号发放——语义链前驱
                        # 用；噪声词不入痕迹——下一拍 STDP 学"前驱→后继"）
                        self._sig_spikes[top_sig] = 1.0
                        self.slot_freq[top_sig, k_star[top_sig]] += 1
                        self.elig[top_sig] = 1.0
                if not signal:
                    # 底噪拍：跳过全部学习（Hebbian/STDP/资格迹/唤醒计数/
                    # pre_trace 记录——底噪发放不留痕——防"底噪词→下一拍
                    # 注入词"STDP 反向污染）
                    v[top, :] = 0.0
                    self.spikes = new_spikes
                    self._last_inp = inp_idx.copy()
                    self.da *= self.da_decay
                    self.elig *= self.elig_decay
                    self._decay_elig_pairs()
                    pre_trace *= self.trace_decay
                    if self.refractory > 0:
                        ref_left[top] = self.refractory
                    return new_spikes

        v[top, :] = 0.0
        # 唤醒计数/资格迹已在门控块内完成（学习态信号拍）；冻结态不计数
        # （纯检索零改动——含计数——sleep 时冻结态也拒绝执行）
        self.spikes = new_spikes
        self._last_inp = inp_idx.copy()   # 记录本拍注入（下一拍词终端判定用）
        # 神经调质衰减（2026-08-11）：多巴胺瞬时脉冲回基线——无外部表
        self.da *= self.da_decay
        self.elig *= self.elig_decay
        self._decay_elig_pairs()
        # 第六波 Step1：痕迹就地更新（省 1.2MB 分配/步；乘后加顺序与原来
        # `a*decay + b` 相同 → 位级一致）。衰减无条件（间隔拍/空拍痕迹持续
        # 衰减——STDP 前驱判定用上一步衰减后的值）；"加"学习态只加信号
        # 发放（_sig_spikes——噪声词不入痕迹），冻结态保持原逻辑
        # （冻结态 pre_trace 无 STDP 读取者——仅保持原对拍语义）。
        pre_trace *= self.trace_decay
        if self.learn_gate:
            pre_trace += self._sig_spikes
        else:
            pre_trace += new_spikes
        if self.refractory > 0:
            # 基础 -1 已由 _wta_cand/_train_core 内核完成（2026-08-10 第二波：
            # 删除原尾部 np.maximum(ref-1,0)——双递减在 refractory≥2 时语义分叉
            # （refractory=1 饱和到 0 无感故对拍通过），与参考实现单次递减对齐）
            if len(top):
                ref_left[top] = self.refractory
        return new_spikes

    def sleep_chunking(self, pats, cursor, min_calls=10, k=4, w=64.0,
                       max_len=6):
        """用进废退组块化（2026-08-11）：主干被调用 ≥ min_calls → 整句 token。

        判据（用户："不能单纯看突触权重，要从主干来看——主干被调用了
        多少次"）：**主干（定式槽位轨道）调用次数**——不是突触权重。
        理由：长难句教 100 次边权照样高，但主干是稀疏组合、从不重复
        （用进废退——不被调用不固化）；高频短句反复走同一主干（槽位
        发放计数累积）——固化（组块化）。

        动作：达标定式的 first 实例 → allocate_pats 整句 token（进词表）
        + 入口词 → token 强边。之后注入入口词 → 1 拍读出整句
        （逐词传播 3k → 组块读出 1k）。原词链保留（组合性——换主体
        仍走链泛化）。

        返回 (新增 token 数, cursor)。"""
        if not self.learn_gate:
            return 0, cursor
        skeletons = getattr(self, "skeletons", None) or {}
        made = 0
        for sk in skeletons.values():
            L = sk.get("len", 0)
            if L < 2 or L > max_len:
                continue
            content = sk.get("content", {})
            if 0 not in content:
                continue
            # 主干调用次数 = 入口槽（位置 0）发放计数（每次走轨道必发槽0）
            calls = int(self.slot_freq[content[0][0], 0])
            if calls < min_calls:
                continue
            seq = list(sk.get("first", []))
            if len(seq) != L:
                continue
            token = "".join(seq)
            if token in pats:
                continue                      # 已组块（幂等）
            alloc, cursor = allocate_pats(self, [token], k, cursor)
            pats[token] = alloc[token]
            for i in pats.get(seq[0], []):    # 入口词 → 整句 token
                for j in pats[token]:
                    self.W_out[i][0][j] = w
            made += 1
        return made, cursor

    def sleep_chunk_rank(self, pats, cursor, top_pct=0.2, k=4, w=64.0,
                         max_len=6):
        """相对分值组块化（2026-08-11 用户设计："固定主干的句式里的词语
        之间的突触权重相加后的总数除以所有固定句式的突触的总数之和——
        分值在前百分之几就固化到词表里"）。

        判据（用进废退的相对统计形式——用户）：
          score(句式) = Σ 该句式绑定词之间的突触权重   （"词语之间的
                        突触权重相加后的总数"——句内词对边权总和）
          score_norm  = score(句式) / Σ 所有句式 score   （"除以所有
                        固定句式的突触的总数之和"）
          排名前 top_pct%（分值占比前百分之几）→ 固化进词表

        与 min_calls 版（绝对次数）的区别：**相对分值**——不依赖"教了
        多少次"的绝对量，看句式在全部句式中的相对地位——用得多的句式
        占比高 → 固化；用得少的占比低 → 保持组合（换主体仍泛化）。

        动作：达标定式 first 实例 → allocate_pats 整句 token + 入口词
        → token 强边（1 拍读出整句——k 压力缓解）。

        返回 (新增 token 数, cursor)。"""
        if not self.learn_gate:
            return 0, cursor
        skeletons = getattr(self, "skeletons", None) or {}
        # ── 计算每个"框架实例"的权重分值 ──
        # 共享定式（叫X）是**一个框架**（bound 多绑定）——固化单位是
        # **实例**（入口词 + 具体绑定词组合——「叫爸爸」「叫爷爷」）。
        # 实例分值 = 该实例的词间突触权重总和（入口→绑定 边权——
        # "固定主干的句式里的词语之间的突触权重"）。
        scores = []        # (score, token_seq)
        for sig, sk in skeletons.items():
            L = sk.get("len", 0)
            if L < 2 or L > max_len:
                continue
            bound = sk.get("bound", {})
            entry = sk.get("first", [None])[0] if sk.get("first") else None
            if entry is None or entry not in bound:
                continue
            ns_entry = pats.get(entry)
            if not ns_entry:
                continue
            # 实例 = 入口词 + 位置 i 的绑定词（first 的其余位用固定词/
            # 绑定词——按位取：位置 0=入口，其余位取该位绑定词）
            # 简化：实例 = 入口词 + 每个其他位绑定词（枚举组合）
            other_slots = [i for i in range(L) if i != 0]
            for slot_i in other_slots:
                # 该槽位的绑定词（可能多个——爸爸/爷爷/妹妹）
                slot_words = [w for w, idx in bound.items() if idx == slot_i]
                for wb in slot_words:
                    ns_b = pats.get(wb)
                    if not ns_b:
                        continue
                    # 实例分值 = 入口→绑定 边权（词间突触权重）
                    score = sum(self.W_out[i][0].get(j, 0.0)
                                for i in ns_entry for j in ns_b)
                    seq = [entry] + [wb if idx == slot_i
                                     else next((w for w, ix in bound.items()
                                                if ix == idx), w)
                                     for idx in range(1, L)]
                    scores.append((score, seq))
        if not scores:
            return 0, cursor
        # ── 归一化：实例分值 / 全部分值总和 ──
        grand = sum(s for s, _ in scores)
        if grand <= 0:
            return 0, cursor
        ranked = sorted(scores, key=lambda kv: -kv[0])
        # ── 排名前 top_pct% 的实例固化 ──
        n_chunk = max(1, int(round(len(ranked) * top_pct)))
        made = 0
        for score, seq in ranked[:n_chunk]:
            token = "".join(seq)
            if token in pats:
                continue
            alloc, cursor = allocate_pats(self, [token], k, cursor)
            pats[token] = alloc[token]
            for i in pats.get(seq[0], []):
                for j in pats[token]:
                    self.W_out[i][0][j] = w
            made += 1
        return made, cursor

    def sleep_prune_words(self, pats, cursor, min_calls=2, n2w=None,
                          keep_top=30000, max_len=6):
        """词表用进废退淘汰（2026-08-11 用户："词表里的词是阶段性的，
        随时间推移就不用了——词表上的词应该用进废退——常用词的数量是
        固定的，但词的数量是会增加的"）。

        ⚠️ 已冻结（2026-08-11 用户决策）：**不启用**——词淘汰会把词移出
        词表（神经元变孤儿、边清零）——但阶段性词在对话中会复现——淘汰
        后 k 窗口少了可用词 → 表达压力增大。代码保留（可回溯），调用方
        不应启用。未来若启用：需分批淘汰（remove_word O(n) 全表扫描——
        37k 词全表淘汰过慢）。

        语义（用户）：词表容量有限（常用词数量固定——keep_top）——
        新词持续加入（allocate_pats——词数增加）→ 必须淘汰低频词——
        **用进废退**（对应大脑突触修剪 synaptic pruning / 词频遗忘）：
        阶段性词（时事词——"特朗普/军运会"）随时间不使用 → 唤醒计数低
        → 移出词表（remove_word——边/定式/固化全清）。

        判据：词级唤醒 = 该词所有神经元 slot_freq 总和（窗口内使用次数）
        ——低频词（< min_calls）且不在高频保护区 → 淘汰；词表超 keep_top
        → 强制淘汰最低频。

        返回 (淘汰词数, cursor)。"""
        if not self.learn_gate:
            return 0, cursor
        from schema_net import remove_word
        n2w = n2w if n2w is not None else {}
        # 词级唤醒计数
        word_freq = {}
        for w, ns in pats.items():
            if len(w) > max_len:
                continue          # 长 token（固化句）不参与词表淘汰
            freq = sum(int(self.slot_freq[i, :].sum()) for i in ns)
            word_freq[w] = freq
        if not word_freq:
            return 0, cursor
        # 排序：低频在前
        ranked = sorted(word_freq.items(), key=lambda kv: kv[1])
        pruned = 0
        # ① 低频淘汰：唤醒 < min_calls（阶段性词——不再使用）
        for w, freq in ranked:
            if freq >= min_calls:
                break
            if w in pats:
                cursor = remove_word(self, pats, w, n2w=n2w)
                pruned += 1
        # ② 容量控制：词表超 keep_top → 强制淘汰最低频（常用词数量固定）
        over = len(pats) - keep_top
        if over > 0:
            for w, freq in ranked:
                if over <= 0:
                    break
                if w in pats:
                    remove_word(self, pats, w, n2w=n2w)
                    over -= 1
                    pruned += 1
        return pruned, cursor
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

    def sleep_downscale(self, keep_ratio=0.2, factor=0.82, eps=0.01):
        """SHY 睡眠（2026-08-11 治疗五——对齐 de Vivo 2017 / Tononi-Cirelli
        突触稳态假说——"先缩放、跌破生存阈值的才修剪"）：

          ① 豁免：最强 keep_ratio（20%）突触不动（de Vivo: spared the
             largest——最大最稳定的突触保护）
          ② 乘性缩放：其余 ×factor（0.82——所有突触按比例降权——相对
             结构保留——强的仍强；缩放把最弱的推到生存阈值以下）
          ③ 阈值删除：缩放后跌破生存阈值（eps——极小）的边删除（小胶质
             细胞修剪对应——删除是缩放的结果——不是排序删弱）
          ④ gain 归一化：神经元权重（兴奋性）回基线（内在可塑性重置）
          ⑤ fat 清零（睡眠压力释放）+ slot_freq 重置（新窗口）
        词汇转正（临时身份 → 正式）由调用方 sleep 后调
        promote_oov_words（pats 在外部）。

        返回 (删除条目数, 缩放条目数, 豁免条目数, 豁免阈值, gain归一数)。
        """
        if not self.learn_gate:
            return 0, 0, 0, 0.0, 0
        # ① 动态豁免阈值：边总数蓄水池采样（每条边等概率）
        rng = np.random.default_rng(42)
        K = 40000
        pool = np.empty(K, dtype=np.float64)
        _total = 0
        for i in range(self.n):
            for k in range(self.slots):
                row = self.W_out[i][k]
                n = len(row)
                if not n:
                    continue
                ww = row.w
                if _total + n <= K:
                    pool[_total:_total + n] = ww
                else:
                    m = np.arange(_total + 1, _total + n + 1)
                    mask = rng.random(n) < K / m
                    if mask.any():
                        pos = rng.integers(0, K, size=int(mask.sum()))
                        pool[pos] = ww[mask]
                _total += n
        thr = float(np.quantile(pool[:_total], 1 - keep_ratio)) if _total else 0.0
        cleared = scaled = spared = 0
        for i in range(self.n):
            for k in range(self.slots):
                row = self.W_out[i][k]
                if not row:
                    continue
                ww = row.w
                spared += int((ww >= thr).sum())      # ① 豁免（最强 20%——不动）
                m = ww < thr                          # ② 乘性缩放（其余 ×factor）
                if m.any():
                    row.w = row.w.copy()
                    row.w[m] *= factor
                    scaled += int(m.sum())
                cleared += row.prune_below(eps)       # ③ 缩放后跌破生存阈值 → 删
                self.slot_freq[i, k] = 0              # ⑤ 唤醒计数重置
        # ④ gain 归一化（神经元兴奋性回基线——内在可塑性重置）
        n_gain = int((self.gain != 1.0).sum())
        self.gain[:] = 1.0
        self.fat[:] = 0.0                             # ⑤ 睡眠压力释放
        self.da = 0.0
        self.da_expected = 0.0
        return cleared, scaled, spared, thr, n_gain

    def sleep_pressure(self):
        """内生睡眠压力（Borbély Process S——2026-08-11 治疗五）：
        slot_freq 总和（唤醒计数累积——活动量——sleep 时重置）。
        白天活动越多压力越高——达到阈值 → 触发睡眠（SHY 缩放+重置）
        ——活动驱动的睡眠节律（不是外部定时）。"""
        if not self.learn_gate:
            return 0.0
        return float(self.slot_freq.sum())

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
        self._is_cand = np.pad(self._is_cand, (0, pad))
        self._cand_idx = np.pad(self._cand_idx, (0, pad))
        self._cand_val = np.pad(self._cand_val, (0, pad))
        self._spikes_buf = np.pad(self._spikes_buf, (0, pad))
        self._drive = np.pad(self._drive, ((0, 0), (0, pad)))
        # 定向链跨槽 drive 累计缓冲（2026-08-11 新增——此前扩容遗漏 →
        # consolidate 分配新槽位后长度不齐 → 底噪门控 sig_mask 广播崩溃，
        # 且 WTA 定向链候选过滤读旧数组——轨道永远无法激活）
        self._drive_any = np.pad(self._drive_any, (0, pad))
        # fat/elig 随扩容对齐（std_dep 疲劳 + R-STDP 资格迹——老数组传播
        # 时长度不齐会索引错位）
        self.fat = np.pad(self.fat, (0, pad))
        self.elig = np.pad(self.elig, (0, pad))
        self.slot_freq = np.pad(self.slot_freq, ((0, pad), (0, 0)))
        # gain 随扩容对齐（2026-08-11 修复：np.pad 默认填充 0 → 扩容新增
        # 神经元（身份词/定式槽位）gain=0 → 传播路径 WTA key=vmax×gain=0
        # → 永久排除——模式轨道永远无法激活（推理链物理断裂）。填充 1
        # （新神经元正常参与竞争）。）
        self.gain = np.pad(self.gain, (0, pad), constant_values=1)
        # _sig_spikes 随扩容对齐（2026-08-11 底噪门控新增字段——consolidate
        # 分配新槽位神经元后长度不齐 → pre_trace += _sig_spikes 广播崩溃）
        if hasattr(self, "_sig_spikes"):
            self._sig_spikes = np.pad(self._sig_spikes, (0, pad))
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

    动力学注入定式保留（单句内 pre_trace 自然累积），读出走 S 矩阵直读
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


def promote_oov_words(ng, pats, cursor, oov_words, freeze_thr=0.0,
                      k=4, w=64.0):
    """词汇巩固：临时身份（字组合并集）→ 正式身份（独立神经元）。

    转正条件（2026-08-11 用户："两个字变成词要不要进入前 20% 的
    强边才转化？"→ 要——转正 = 冻结的延续）：
      词的边权 ≥ 前 20% 冻结阈值（freeze_thr——sleep_downscale
      动态计算返回的网络保护线）——进入冻结区 = 网络认为重要
      （豁免压缩）→ 正式化；没进入 = 被压缩 → 自然遗忘（生词
      没记熟 sleep 就压没了——对应人：没记住就忘了）。
    阈值以下不转正（"还没熟"——继续字组合身份观察）。

    语义边**迁移**（改进 _grow_oov v1 的不迁移——转正不丢语义）：
      入边重指向：所有指向字神经元的边 → 改指向正式神经元（同权重）
      出边复制：字神经元的出边复制到正式神经元

    返回 (pats, cursor, promoted_words)。
    """
    import numpy as _np
    promoted = []
    for w, chars in list(oov_words.items()):
        if w not in pats:
            continue
        ns = set(pats[w])
        # 转正信号：进入前 20% 冻结区（边权 ≥ 网络保护线）
        edges = [v for i in ns for v in ng.W_out[i][0].values()]
        if not edges:
            continue
        edge_max = float(_np.max(edges))
        if freeze_thr <= 0 or edge_max < freeze_thr:
            continue
        # 正式身份：分配独立神经元
        p_new, cursor = allocate_pats(ng, [w], k, cursor)
        new_ns = p_new[w]
        # 语义边迁移：入边重指向（指向字神经元 → 指向正式神经元）
        for i in range(ng.n):
            row = ng.W_out[i][0]
            if not row:
                continue
            for j in list(row.keys()):
                if j in ns:
                    v = row[j]
                    del row[j]
                    for nj in new_ns:
                        if nj not in row:
                            row[nj] = v
                            break
        # 出边复制：字神经元出边 → 正式神经元（同权重）
        for i in ns:
            src = ng.W_out[i][0]
            for j, v in src.items():
                for ni in new_ns:
                    if j not in ng.W_out[ni][0]:
                        ng.W_out[ni][0][j] = v
                        break
        # 词表换新模式（正式身份）
        pats[w] = new_ns
        del oov_words[w]
        promoted.append(w)
    return pats, cursor, promoted
