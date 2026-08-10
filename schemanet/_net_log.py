# -*- coding: utf-8 -*-
"""经历日志（记忆持久化）：checkpoint + 增量事件日志（[PLAN]-定式网络记忆持久化方案）。

持续学习在内存中逐句进行，保存粒度原本是会话级——会话中途崩溃，最后保存到
崩溃之间的经历全部丢失。本模块把"经历"变成 append-only 事件日志：

    持续学习（内存中）
       │  每句经历 append → _exp_logs/active.jsonl（E 事件，几十字节/句）
       │  定期 checkpoint（复用 save_snapshot 版本机制）+ 归档 active
       ▼
    崩溃 → recover_latest() = load_version(最近 checkpoint) + 重放剩余日志
          → 恢复到崩溃前状态（丢失窗口 = 未刷盘的日志量）

两类事件：
  - E（经历）：教学式 _learn_sentence（干净注入，Hebbian/STDP 确定性重建）。
    附 rng 状态（get_state）——教学步有噪声（noise_p=0.06），重放必须恢复
    原始噪声序列才能逐位一致（方案文档对拍容差 1e-9 是此妥协；本实现记录
    rng 状态 → 严格 0 差异重放）。
  - O（操作差分）：RL 奖励/惩罚等状态依赖操作（strengthen/decay/delete），
    直接应用差分恢复（不可用句子复现）。

设计约束（方案文档 §七）：不入侵 _learn_sentence/Hebbian 内核；不引入数据库；
快照版本机制原样复用；checkpoint 归档后 active 清空重开。

用法：
    log = ExpLog()
    log.learn(ng, ["我", "吃", "苹果"], pats, slot=0)   # 记录 + 教学
    out = log.checkpoint(ng, vocab, pats, cursor, tag="checkpoint")  # 全量快照 + 归档
    ng2, vocab2, pats2, cursor2 = log.recover_latest()  # 最近 checkpoint + 重放
"""

import json
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import RUNS, load_version, save_snapshot


def _rng_state_to_json(rng):
    """np.random.Generator 状态 → JSON 可序列化 dict（PCG64：state/inc 转 int）。"""
    st = rng.bit_generator.state
    out = {"bit_generator": st["bit_generator"]}
    inner = {}
    for k, v in st["state"].items():
        inner[k] = int(v)
    out["state"] = inner
    out["has_uint32"] = int(st["has_uint32"])
    out["uinteger"] = int(st["uinteger"])
    return out


def _rng_state_from_json(rng, d):
    """JSON 恢复 → rng 状态。PCG64 状态是 128 位整数（numpy 2.x），
    保持 Python int 直传，setter 内部转换（np.uint64 会溢出）。"""
    rng.bit_generator.state = d


class ExpLog:
    """经历日志：append 只写事件，checkpoint 触发快照+归档，recover 重建状态。"""

    def __init__(self, base=None):
        base = Path(base) if base else RUNS
        self.log = base / "_exp_logs" / "active.jsonl"
        self.arch = self.log.parent / "archive"
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.arch.mkdir(parents=True, exist_ok=True)
        self._fh = None   # 打开的文件句（复用，避免每次 open/write/close 开销）

    # ── 写 ──

    def _write(self, ev):
        """append 一行（句柄复用；崩溃丢最后半行可接受，方案风险表已列）。"""
        if self._fh is None:
            self._fh = open(self.log, "a", encoding="utf-8")
        self._fh.write(json.dumps(ev, ensure_ascii=False) + "\n")

    def flush(self):
        """强制落盘（教学/推理切换、checkpoint 前调用）。"""
        if self._fh is not None:
            self._fh.flush()

    def close(self):
        """关闭文件句（会话结束/测试清理调用）。"""
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def learn(self, ng, words, pats, slot=0):
        """教学经历（E）：先记录 rng 状态再教学（重放 = set_state + 同一句），
        返回 _learn_sentence 结果。"""
        ev = {"t": "E", "words": list(words), "slot": int(slot),
              "rng": _rng_state_to_json(ng.rng), "ts": time.time()}
        self._write(ev)
        return _learn_sentence(ng, words, pats, slot=slot)

    def append_edge(self, op, src, slot, dst, dw):
        """RL 操作差分（O）原语级。op ∈ {strengthen, decay, delete}。"""
        self.append_op(op, src=int(src), slot=int(slot), dst=int(dst),
                       dw=round(float(dw), 6))

    def append_op(self, op, **fields):
        """操作级 O 事件（重放执行原函数，见 register_op）。
        字段随操作而定：penalize{src,dst} / decay_path{path,factor} 等。"""
        self._write({"t": "O", "op": op, **fields, "ts": time.time()})

    def checkpoint(self, ng, vocab, pats, cursor, tag="checkpoint",
                   parent=None, base=None, metrics=None):
        """全量快照（复用 save_snapshot 版本机制）+ 归档 active 日志。
        返回快照目录名（= 归档文件名）。"""
        out = save_snapshot(ng, parent=parent, tag=tag, metrics=metrics,
                            vocab=vocab, pats=pats, cursor=cursor, base=base)
        self._archive(out.name)
        return out.name

    def _archive(self, version_dir):
        """active → 不可变归档文件（文件名 = checkpoint 版本目录名），active 清空。
        空日志也落空归档文件——archive 文件 = checkpoint 锚点（recover 靠它定位）。"""
        if self._fh is not None:
            self._fh.flush()
            self._fh.close()
            self._fh = None
        dest = self.arch / f"{version_dir}.jsonl"
        if self.log.exists() and self.log.stat().st_size > 0:
            self.log.replace(dest)
        else:
            dest.touch()
        self.log.touch()

    # ── 读（恢复入口）──

    def _iter_events(self):
        if not self.log.exists():
            return
        self.flush()   # 确保缓冲已落盘再读（同进程恢复场景）
        for line in self.log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)

    def recover_latest(self, base=None):
        """最近 checkpoint + 重放归档后剩余日志 → (ng, vocab, pats, cursor)。
        崩溃后一键恢复。E 事件先恢复 rng 状态再重放（位级一致）。"""
        rows = _checkpoint_versions(base or RUNS)
        if not rows:
            raise FileNotFoundError("无 checkpoint 版本（_exp_logs 恢复需要至少一个快照）")
        ng, vocab, pats, cursor = load_version(rows[-1]["version"], base=base)
        n_e = n_o = 0
        for ev in self._iter_events():
            if ev["t"] == "E":
                _rng_state_from_json(ng.rng, ev["rng"])
                _learn_sentence(ng, ev["words"], pats, slot=ev["slot"])
                n_e += 1
            elif ev["t"] == "O":
                _apply_diff(ng, ev, pats)
                n_o += 1
        print(f"[recover] checkpoint v{rows[-1]['version']} + 重放 "
              f"{n_e} 句经历 / {n_o} 条差分")
        return ng, vocab, pats, cursor


def _checkpoint_versions(base):
    """归档目录里的 checkpoint 版本（按归档文件名 → 追溯索引版本号）。"""
    arch = Path(base) / "_exp_logs" / "archive"
    if not arch.exists():
        return []
    from snapshot import snapshot_index
    idx = {r["dir"]: r for r in snapshot_index(base)}
    return [idx[f.stem] for f in sorted(arch.glob("*.jsonl")) if f.stem in idx]


def _apply_diff(ng, ev, pats=None):
    """O 事件直接应用（状态依赖操作不可重放，差分精确恢复）。
    三原语内置（strengthen/decay/delete）；操作级事件（如 _speak 的
    penalize/decay_path）由调用方 register_op 注册重放函数（原函数执行，
    语义精确；_net_log 不复制实现，避免漂移）。"""
    op = ev["op"]
    if op in _OP_HANDLERS:
        _OP_HANDLERS[op](ng, ev, pats)
    elif op == "strengthen":
        src, slot, dst, dw = ev["src"], ev["slot"], ev["dst"], ev["dw"]
        row = ng.W_out[src][slot]
        nv = row.get(dst, 0.0) + dw
        row[dst] = min(nv, ng.w_max)
    elif op == "decay":
        src, slot, dst, dw = ev["src"], ev["slot"], ev["dst"], ev["dw"]
        row = ng.W_out[src][slot]
        row[dst] = max(row.get(dst, 0.0) * (1.0 - dw), 0.0)
    elif op == "delete":
        src, slot, dst = ev["src"], ev["slot"], ev["dst"]
        row = ng.W_out[src][slot]
        if dst in row:
            del row[dst]
    else:
        raise ValueError(f"未知 O 操作: {op!r}（操作级事件需 register_op 注册）")


# 操作级 O 事件注册表（调用方注册重放函数，语义 = 重放执行原函数）
_OP_HANDLERS = {}


def register_op(name, fn):
    """注册操作级 O 事件的重放函数 fn(ng, ev, pats)。"""
    _OP_HANDLERS[name] = fn
