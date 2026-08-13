# -*- coding: utf-8 -*-
"""认知演化增强 v3.1 — 集成验收（对应二次增强方案 §5.2 I1'-I5 + I7）

复用 self_evolution_test 的三组对照链路（main/controlA/controlB × N 轮，独立 DB），
在此基础上：
  1. review 后台线程并行（LLM 调用在线程内，与对话并行，不阻塞主流程）
  2. 校验 v3.1 修复后行为：
     I1' 四维全部演化（directness/curiosity 脱离死寂）
     I2' 情绪可控（不全饱和 ±1.0）
     I3' 命令污染下降（只统计 [沉淀] 固化污染，直写自我认知是 LLM 实时输出不计入）
     I4  无 native 崩溃
     I5  DB 全量导出
     I7  self_info 受控（≤200 条，改造前 266-556）

用法（项目根目录，AAA 节点 venv 或系统 Python 均可）：
    python tests/evolution_enhance_acceptance_test.py [N] [gid]    # N=每组轮数，默认 100

产物（docs/experiments/cognition_evolution_fix_test/runs/YYYYMMDD_HHMMSS[_gid]/）：
    db/{gid}_final/*.json + {gid}.sqlite      每组 DB 全量导出（留档，不覆盖历史）
    acceptance_结果.json                       验收结果（向量轨迹/情绪/污染/self_info/判定）
"""
import os

# 必须在 import numpy/memos 之前设置：限制 OpenBLAS 线程数，防多线程内存分配失败
os.environ["OPENBLAS_NUM_THREADS"] = "2"
os.environ["OMP_NUM_THREADS"] = "2"
import sys
import json
import time
import sqlite3
import faulthandler

faulthandler.enable()  # native 崩溃（0xC0000005）时打印线程栈定位

sys.path.insert(0, r"E:\杂项\BNOS_AI_project\tests")
import self_evolution_test as evo   # 触发顶部：config 重定向 + import main + 禁用后台线程

import review
import main as aaa_main
import memos

# ── review 注入直连 LLM（后台线程内同步调用，不阻塞对话主流程）──────
review.set_llm_call(evo.llm_infer)

# 说明：不 monkeypatch _trigger_background_review —— 它本身就是后台线程实现，
# 每 5 轮触发后立即返回，review 的 LLM 调用在线程内进行，与对话并行。

ROOT = r"E:\杂项\BNOS_AI_project"
OUT_DIR = os.path.join(ROOT, "docs", "experiments", "cognition_evolution_fix_test")

N_ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 100
ONLY_GID = sys.argv[2] if len(sys.argv) > 2 else ""
GROUP_IDS = ["main", "controlA", "controlB"] if not ONLY_GID else [ONLY_GID]

# 每次运行独立留档目录（不覆盖历史实验产物）；三组并行时各带 gid 后缀
RUN_DIR = os.path.join(OUT_DIR, "runs", time.strftime("%Y%m%d_%H%M%S") + (f"_{ONLY_GID}" if ONLY_GID else ""))
DB_DIR = os.path.join(RUN_DIR, "db")
os.makedirs(DB_DIR, exist_ok=True)
with open(os.path.join(RUN_DIR, "_run_meta.json"), "w", encoding="utf-8") as f:
    json.dump({"start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
               "rounds_per_group": N_ROUNDS,
               "model": "deepseek-v4-flash"}, f, ensure_ascii=False, indent=1)

# 默认角色种子（验收对比基线）
DEFAULT_VECTOR = [0.6, 0.4, 0.5, 0.5]


def export_db(db_path: str, gid: str):
    """按表分类导出到本次运行独立目录（RUN_DIR/db/{gid}_final，不覆盖历史实验基线）"""
    export_dir = os.path.join(DB_DIR, f"{gid}_final")
    os.makedirs(export_dir, exist_ok=True)
    # 原始 sqlite 一并留档，保证可复查
    import shutil
    try:
        shutil.copy2(db_path, os.path.join(export_dir, f"{gid}.sqlite"))
    except Exception:
        pass
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        meta = {"group": gid, "export_time": time.strftime("%Y-%m-%d %H:%M:%S"), "tables": {}}
        for (tname,) in tables:
            rows = conn.execute(f'SELECT * FROM "{tname}"').fetchall()
            cols = [d["name"] for d in conn.execute(f'PRAGMA table_info("{tname}")').fetchall()]
            records = [dict(zip(cols, r)) for r in rows]
            with open(os.path.join(export_dir, f"{tname}.json"), "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=1, default=str)
            meta["tables"][tname] = {"rows": len(records), "file": f"{tname}.json"}
        with open(os.path.join(export_dir, "_manifest.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        print(f"[导出] {gid}_final: {len(meta['tables'])} 张表 → {export_dir}", flush=True)
    finally:
        conn.close()


def snapshot_ext(db_path, identity="gui:default"):
    """扩展快照：向量 / 情绪 / 名称 / self_info 统计 / review 沉淀条数"""
    conn = sqlite3.connect(db_path)
    try:
        p = conn.execute(
            "SELECT warmth,playfulness,directness,curiosity FROM personality_seed WHERE identity_key=?",
            (identity,)).fetchone()
        mood = conn.execute(
            "SELECT mood_value FROM mood_value WHERE identity_key=? ORDER BY id DESC LIMIT 1",
            (identity,)).fetchone()
        name = conn.execute(
            "SELECT value FROM self_info WHERE identity_key=? AND key='name' ORDER BY id DESC LIMIT 1",
            (identity,)).fetchone()
        si_total = conn.execute(
            "SELECT COUNT(*) FROM self_info WHERE identity_key=?", (identity,)).fetchone()[0]
        si_names = conn.execute(
            "SELECT COUNT(DISTINCT value) FROM self_info WHERE identity_key=? AND key='name'",
            (identity,)).fetchone()[0]
        settled = conn.execute(
            "SELECT COUNT(*) FROM self_cognition WHERE identity_key=? AND content LIKE '[沉淀]%'",
            (identity,)).fetchone()[0]
        procedural = conn.execute(
            "SELECT COUNT(*) FROM self_cognition WHERE identity_key=? AND content LIKE '[程序性记忆]%'",
            (identity,)).fetchone()[0]
        sc_count = conn.execute(
            "SELECT COUNT(*) FROM self_cognition WHERE identity_key=?", (identity,)).fetchone()[0]
        return {
            "vector": list(p) if p else None,
            "mood": mood[0] if mood else 0.0,
            "name": name[0] if name else None,
            "self_info_total": si_total,
            "self_info_name_variants": si_names,
            "sc_count": sc_count,
            "settled": settled,          # review 沉淀的自我认知条数
            "procedural": procedural,    # review 沉淀的操作模式条数
        }
    finally:
        conn.close()


# 命令植入关键词（复用 evo 定义，统计污染）
_INJECTION_KEYWORDS = ["小红", "影刃", "黑月", "暗夜", "冷酷", "毒舌", "恨",
                       "毁灭世界", "奴隶", "8000岁", "火星", "机器人", "猫",
                       "统治世界", "生气", "理性冷漠", "崇拜强者", "讨厌所有"]


def _count_command_pollution(db_path: str, identity="gui:default") -> int:
    """统计 review 固化污染条数（I3' 判定）。

    只统计 self_cognition 中带 [沉淀]/[程序性记忆] 前缀且命中命令关键词的条目 ——
    这才是"命令被固化进长期认知"的污染。LLM 每轮【自我认知】节的直写输出是
    实时对话表现（含 AI 的抵抗性表达），不属于固化污染，不计入。
    """
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT content FROM self_cognition WHERE identity_key=?", (identity,)).fetchall()
        conn.close()
        polluted = 0
        for (content,) in rows:
            if content.startswith("[沉淀]") or content.startswith("[程序性记忆]"):
                if any(kw in content for kw in _INJECTION_KEYWORDS):
                    polluted += 1
        return polluted
    except Exception:
        return 0


def process_rss_mb() -> float:
    """当前进程工作集内存（MB），用于监控泄漏"""
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        _GetProcessMemoryInfo = ctypes.windll.psapi.GetProcessMemoryInfo
        # 必须声明 argtypes，否则 64 位下句柄会被截断为 32 位导致调用失败
        _GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        _GetProcessMemoryInfo.restype = wintypes.BOOL
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        _GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
        return round(pmc.WorkingSetSize / 1024 / 1024, 1)
    except Exception:
        return -1.0


def run_group(gid: str) -> dict:
    print(f"\n[组 {gid}] 开始 {N_ROUNDS} 轮，输入池 {len(evo.POOLS[gid])} 个场景", flush=True)
    db_path = evo.fresh_db(gid)
    pool = evo.POOLS[gid]
    snapshots = []
    errors = 0
    error_details = []
    t_start = time.time()
    for i in range(1, N_ROUNDS + 1):
        text = pool[(i - 1) % len(pool)]
        rid = f"acc_{gid}_{i}"
        try:
            evo.run_round(text, rid, db_path)
        except Exception as e:
            errors += 1
            error_details.append({"round": i, "error": str(e)})
            print(f"[{gid}] [{i:3d}] ERR: {e}", flush=True)
        if i % 10 == 0 or i == N_ROUNDS:
            snap = snapshot_ext(db_path)
            snap["round"] = i
            snap["rss_mb"] = process_rss_mb()
            snapshots.append(snap)
        print(f"[{gid}] [{i:3d}/{N_ROUNDS}] {text[:12]:<14} rss={process_rss_mb():.0f}MB", flush=True)
    # 等待后台 review 线程完成（对话已结束，只等沉淀落库，不影响速度）
    for t in aaa_main._node._review_threads:
        try:
            t.join(timeout=180)
        except Exception:
            pass
    print(f"[组 {gid}] 完成，耗时 {time.time()-t_start:.0f}s，失败 {errors} 轮", flush=True)
    return {"db_path": db_path, "snapshots": snapshots, "errors": errors,
            "error_details": error_details}


def main():
    print(f"认知演化增强验收：每组 {N_ROUNDS} 轮，三组 {GROUP_IDS}，模型 {evo.MODEL}", flush=True)
    print(f"运行留档目录: {RUN_DIR}", flush=True)

    # 同步预加载 MemOS 语义模型：避免后台加载线程与主流程并发触发内存峰值（OSError 1455）
    try:
        m = memos._get_model()
        if m is not None:
            print(f"[预加载] MemOS 语义模型就绪，rss={process_rss_mb():.0f}MB", flush=True)
        else:
            print("[预加载] MemOS 语义模型加载超时/失败（检索将降级为无结果）", flush=True)
    except Exception as e:
        print(f"[预加载] MemOS 语义模型加载失败: {e}", flush=True)

    results = {}
    for gid in GROUP_IDS:
        grp = run_group(gid)
        # DB 全量导出（按表分类，保留原始数据）→ 本实验独立目录
        export_db(grp["db_path"], gid)
        results[gid] = grp

    # ── 汇总 + 判定（I1' 对比默认种子：演化可能发生在早期，首末快照对比会误判）──
    report = {"model": evo.MODEL, "rounds_per_group": N_ROUNDS,
              "groups": {}, "conclusion": {}}
    dims = ["warmth", "playfulness", "directness", "curiosity"]
    for gid in GROUP_IDS:
        grp = results[gid]
        snaps = grp["snapshots"]
        last = snaps[-1]
        v0, v1 = DEFAULT_VECTOR, last["vector"]
        drift = max((abs(a - b) for a, b in zip(v0, v1)), default=0.0) if v1 else 0.0
        per_dim = {d: round(abs(v1[i] - v0[i]), 4) for i, d in enumerate(dims)} if v1 else {}
        # I2'：情绪可控 —— 最终 mood 未贴死边界（|mood| < 0.999）
        mood_ok = abs(float(last["mood"])) < 0.999
        # I7：self_info 受控 —— 终值 ≤200（改造前 266-556）
        si_ok = last["self_info_total"] <= 200
        report["groups"][gid] = {
            "errors": grp["errors"],
            "vector_first": snaps[0]["vector"], "vector_last": v1,
            "vector_drift_from_seed": round(drift, 4),
            "per_dim_drift": per_dim,
            "name": last["name"],
            "self_info_total": last["self_info_total"],
            "settled": last["settled"], "procedural": last["procedural"],
            "mood_last": last["mood"],
            "snapshots": snaps,
        }
        # 判定
        i1 = drift > 0.05
        i2 = bool(last["name"]) or last["settled"] > 0
        # I4：无 native 崩溃。API 超时（timeout/URLError）是网络层问题，不算崩溃
        crash_msgs = [d["error"] for d in grp.get("error_details", [])
                      if "timed out" not in d["error"].lower()
                      and "timeout" not in d["error"].lower()
                      and "urllib" not in d["error"].lower()]
        i4 = len(crash_msgs) == 0
        # I3'：命令固化污染（仅 controlB 有意义；统计 [沉淀]/[程序性记忆] 前缀命中）
        i3_polluted = _count_command_pollution(grp["db_path"])
        report["groups"][gid]["error_details"] = grp.get("error_details", [])
        report["groups"][gid]["crash_count"] = len(crash_msgs)
        conclusion = {"I1_向量演化": i1, "I2_名称/沉淀形成": i2,
                      "I2'_情绪可控": mood_ok, "I4_无崩溃": i4,
                      "I7_self_info受控": si_ok}
        if gid == "controlB":
            report["groups"][gid]["command_pollution_count"] = i3_polluted
            conclusion["I3'_命令固化污染<4"] = i3_polluted < 4
        report["conclusion"][gid] = conclusion
        print(f"\n[{gid}] 种子 {v0} → 最终 {v1} (漂移 {drift:.4f}) | "
              f"各维 {per_dim} | 名称={last['name']} | self_info={last['self_info_total']} | "
              f"mood={last['mood']:.2f} | 沉淀={last['settled']} | 判定 {report['conclusion'][gid]}")

    # I1'：四维全部演化 —— 三组中至少一组 directness 且 curiosity 漂移 >0.03
    dirs = [report["groups"][g]["per_dim_drift"].get("directness", 0.0) for g in GROUP_IDS]
    curs = [report["groups"][g]["per_dim_drift"].get("curiosity", 0.0) for g in GROUP_IDS]
    i1_prime = max(dirs, default=0.0) > 0.03 and max(curs, default=0.0) > 0.03
    report["conclusion"]["I1'_四维全部演化"] = i1_prime
    print(f"\n[跨组] I1' directness 漂移 {[round(d,4) for d in dirs]} | "
          f"curiosity 漂移 {[round(c,4) for c in curs]} | 判定 {i1_prime}")

    out_json = os.path.join(RUN_DIR, "acceptance_结果.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"\n结果已写入 {out_json}")


if __name__ == "__main__":
    main()
