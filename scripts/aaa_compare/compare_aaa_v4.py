"""
AAA v4.0 改造前后对比主脚本（无 GUI，节点级能力测试）

流程：
1. 建立独立留档目录 runs/YYYYMMDD_HHMMSS_aaa_cmp/
2. 旧版（node/aaa v2.0 两轮交互）与新版（工作区 v4.0 Prefetch 单轮）
   各建独立 DB（相同种子记忆）
3. 子进程隔离运行 measure.py（旧版/新版分开进程，避免 memos 全局状态冲突）
4. 汇总两份 JSON → 输出对比表 + 报告 markdown

用法：
    python compare_aaa_v4.py [--old-dir <旧版目录>] [--new-dir <新版目录>]
    python compare_aaa_v4.py --real      # P0: 追加真 LLM 端到端答案正确性验证

默认目录：
    旧版: C:\\Users\\Lenovo\\AppData\\Local\\Temp\\aaa_old_node
    新版: e:\\杂项\\BNOS_AI_project\\nodes\\node_python_aaa_cognition

P0（--real）：
    旧版/新版各跑一遍真实 LLM（DeepSeek）同样 4 场景，逐场景判定答对与否：
    - 新版答对 → Prefetch 全链路打通（记忆预取 → memory-context 注入 → 输出引用）
    - 新版仍答模板句 → 问题在 memory-context 注入格式/权重
"""
import os
import sys
import json
import time
import argparse
import subprocess
from datetime import datetime

PROJECT_ROOT = r"e:\杂项\BNOS_AI_project"
DEFAULT_OLD_DIR = r"C:\Users\Lenovo\AppData\Local\Temp\aaa_old_node"
DEFAULT_NEW_DIR = os.path.join(PROJECT_ROOT, "nodes", "node_python_aaa_cognition")
VENV_PYTHON = os.path.join(DEFAULT_NEW_DIR, "venv", "Scripts", "python.exe")
MEASURE_PY = os.path.join(PROJECT_ROOT, "scripts", "aaa_compare", "measure.py")


def run_measure(node_dir, mode, db_path, out_path, seed=True,
                python_exe=None, extra_skip=False, real=False):
    """子进程运行 measure.py，返回 exit code"""
    exe = python_exe or sys.executable
    cmd = [
        exe, MEASURE_PY,
        "--node-dir", node_dir,
        "--db-path", db_path,
        "--mode", mode,
        "--out", out_path,
    ]
    if seed:
        cmd.append("--seed")
    if extra_skip:
        cmd.append("--skip-retrieval")
    if real:
        cmd.append("--real")
    print(f"[run] {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=900)
    if proc.stdout:
        print(proc.stdout.strip(), flush=True)
    if proc.stderr:
        # 只打印末尾几行，避免刷屏
        tail = proc.stderr.strip().splitlines()[-8:]
        for line in tail:
            print(f"[stderr] {line}", flush=True)
    return proc.returncode


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_report(old, old_skip, new, run_dir, old_real=None, new_real=None) -> str:
    lines = []
    lines.append("# AAA v4.0 改造前后节点能力对比报告")
    lines.append("")
    lines.append(f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 旧版(v2.0 两轮交互): `{old['node_dir']}`")
    lines.append(f"- 新版(v4.0 Prefetch 单轮): `{new['node_dir']}`")
    lines.append(f"- 场景数: {len(old['turns'])} 轮对话")
    if old_real and new_real:
        lines.append(f"- P0 真 LLM 端到端验证: 是（DeepSeek 真实 LLM，两版同模型同温度）")
    lines.append("")
    lines.append("## 汇总指标")
    lines.append("")
    lines.append("| 指标 | 旧版 v2.0 | 新版 v4.0 | 变化 |")
    lines.append("|------|-----------|-----------|------|")
    lines.append(f"| LLM 往返总次数 | {old['round_trips_total']} | "
                 f"{new['round_trips_total']} | "
                 f"{(new['round_trips_total']-old['round_trips_total']):+d} "
                 f"({calc_pct(old['round_trips_total'], new['round_trips_total'])}) |")
    lines.append(f"| Prompt token 总量(估算) | {old['tokens_total']} | "
                 f"{new['tokens_total']} | "
                 f"{(new['tokens_total']-old['tokens_total']):+.1f} "
                 f"({calc_pct(old['tokens_total'], new['tokens_total'])}) |")
    lines.append(f"| 含记忆注入的轮次 | {old['turns_with_memory']}/{len(old['turns'])} | "
                 f"{new['turns_with_memory']}/{len(new['turns'])} | - |")
    lines.append("")
    lines.append("## 逐轮明细")
    lines.append("")
    lines.append("| 轮次 | 用户输入 | 版本 | 往返 | Prompt token | 记忆命中关键词 | 记忆注入 |")
    lines.append("|------|----------|------|------|--------------|----------------|----------|")
    for i, (ot, nt) in enumerate(zip(old["turns"], new["turns"])):
        for tag, t in (("旧", ot), ("新", nt)):
            kws = "、".join(t["memory_keywords"]) if t["memory_keywords"] else "-"
            lines.append(
                f"| {i} | {t['user_text'][:24]} | {tag} | {t['round_trips']} | "
                f"{sum(p['tokens'] for p in t['prompts'])} | {kws} | "
                f"{'✓' if t['memory_present'] else '✗'} |")
    lines.append("")
    lines.append("## 记忆注入确定性对照（LLM 忘记触发检索时）")
    lines.append("")
    lines.append("> 场景：模拟真实 LLM 第一轮直接回复、**不输出【语意检索】**（不保证每次都会自觉检索）。")
    lines.append("")
    lines.append("| 轮次 | 用户输入 | 旧版(未触发检索) | 新版(Prefetch) |")
    lines.append("|------|----------|-----------------|----------------|")
    for i, (ot, nt) in enumerate(zip(old_skip["turns"], new["turns"])):
        old_has = "✓" if ot["memory_present"] else "✗"
        new_has = "✓" if nt["memory_present"] else "✗"
        lines.append(f"| {i} | {ot['user_text'][:24]} | 记忆注入 {old_has} | 记忆注入 {new_has} |")
    old_skip_ok = sum(1 for t in old_skip["turns"] if t["memory_present"])
    lines.append("")
    lines.append("## 结论要点")
    lines.append("")
    if new["round_trips_total"] < old["round_trips_total"]:
        lines.append(
            f"- **往返次数减少 {old['round_trips_total']-new['round_trips_total']} 次"
            f"（{calc_pct(old['round_trips_total'], new['round_trips_total'])}）**："
            "新版 Prefetch 单轮交互不再依赖 LLM 自主决定【语意检索】，"
            "每次对话固定一次 LLM 调用，消除第二轮延迟。")
    if old_skip_ok == 0 and new["turns_with_memory"] == len(new["turns"]):
        lines.append(
            f"- **记忆注入确定性提升（决定性）**：当 LLM 忘记触发检索时，"
            f"旧版 {old_skip_ok}/{len(old_skip['turns'])} 轮有记忆注入；"
            f"新版 {new['turns_with_memory']}/{len(new['turns'])} 轮全部注入。"
            "Prefetch 使记忆检索由节点强制预取，不再依赖 LLM 自觉性。")
    elif new["turns_with_memory"] > old_skip["turns_with_memory"]:
        lines.append(
            f"- **记忆注入确定性提升**：LLM 未触发检索时旧版仅 "
            f"{old_skip['turns_with_memory']}/{len(old_skip['turns'])} 轮有记忆；"
            f"新版 {new['turns_with_memory']}/{len(new['turns'])} 轮全部注入。")
    if new["tokens_total"] > old["tokens_total"]:
        lines.append(
            f"- **单轮 prompt 更长（token +{calc_pct(old['tokens_total'], new['tokens_total'])}）**："
            "新版 v4.0 为单轮 prompt 注入了更多上下文维度（personality / perception / "
            "location / mood / memory-context 等），换取一次 LLM 往返的消除；"
            "两次调用各自重复的固定开销（模板头/上下文）合并为一次。")
    lines.append(
        "- **同一语义引擎**：两版共用 memos.py 语义检索（同一种子记忆/索引），"
        "命中差异仅来自交互架构（两轮 vs 单轮），非检索质量差异。")

    if old_real and new_real:
        lines.append("")
        lines.append("## P0 真 LLM 端到端答案正确性")
        lines.append("")
        lines.append("> 用真实 DeepSeek LLM 跑同样 4 场景（两版同种子记忆/同模型/同温度），"
                     "逐场景判定 LLM 是否真正引用记忆库中的答案。")
        lines.append("> 判定依据：回复文本中含期望答案关键词（如「二饼」「星际穿越」「专升本」）。")
        lines.append("")
        lines.append("| 轮次 | 用户输入 | 期望答案 | 旧版(两轮,LLM自觉检索) | 新版(Prefetch单轮) |")
        lines.append("|------|----------|----------|------------------------|--------------------|")
        for i, (ot, nt) in enumerate(zip(old_real["turns"], new_real["turns"])):
            oa = ot["answer"]
            na = nt["answer"]
            exp = "、".join(oa["expected"]) if oa["expected"] else "（对照组，无记忆答案）"
            o_cell = _answer_cell(oa, ot)
            n_cell = _answer_cell(na, nt)
            lines.append(f"| {i} | {ot['user_text'][:24]} | {exp} | {o_cell} | {n_cell} |")
        lines.append("")
        old_correct = old_real["answers_correct"]
        new_correct = new_real["answers_correct"]
        # 天气为对照组（expected 为空），从正确率分母中剔除
        n_scored = sum(1 for t in new_real["turns"] if t["answer"]["expected"])
        old_scored = sum(1 for t in old_real["turns"] if t["answer"]["expected"])
        lines.append(f"- 有记忆答案的场景数：{n_scored}/4（第 2 轮天气为对照组，不判正误）")
        lines.append(f"- 旧版答对 {old_correct}/{old_scored}，新版答对 {new_correct}/{n_scored}。")
        lines.append("")
        if new_correct == n_scored:
            lines.append(
                f"- **Prefetch 全链路打通（决定性）**：新版单轮（无二次检索机会）全部答对记忆问题，"
                "真实 LLM 能从 memory-context 直接提取答案 → 预取 → 注入 → 输出 整条链路有效。")
        elif new_correct >= n_scored - 1:
            lines.append(
                f"- **Prefetch 全链路基本打通**：新版答对 {new_correct}/{n_scored}，"
                "真实 LLM 已能引用 memory-context 中的答案；个别未答对场景需检查"
                "检索 top-k 命中或 memory-context 格式/权重。")
        else:
            lines.append(
                f"- **Prefetch 注入链路未生效**：新版仅答对 {new_correct}/{n_scored}，"
                "真实 LLM 未从 memory-context 提取答案 → 问题定位在 memory-context 注入格式/权重。")
        lines.append("")
        lines.append("### 新版各轮 LLM 原始回复（节选）")
        lines.append("")
        for nt in new_real["turns"]:
            snippet = (nt["reply"] or "").replace("\n", " ")[:120]
            lines.append(f"- 轮{nt['idx']} `{nt['user_text'][:24]}` → {snippet}")
    return "\n".join(lines)


def _answer_cell(ans, turn) -> str:
    """P0 判定单元格：答对/答错 + 命中关键词"""
    if not ans["expected"]:
        # 对照组（无记忆答案）：不判正误，仅看是否有记忆相关输出
        return "（对照）"
    if ans["correct"]:
        return f"✓ 答对（命中 {'、'.join(ans['found'])}）"
    return f"✗ 未命中（回复: {(turn.get('reply') or '')[:40]}）"


def calc_pct(a, b) -> str:
    if a == 0:
        return "0%"
    return f"{(b-a)/a*100:+.1f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-dir", default=DEFAULT_OLD_DIR)
    ap.add_argument("--new-dir", default=DEFAULT_NEW_DIR)
    ap.add_argument("--runs-root", default=os.path.join(PROJECT_ROOT, "runs"))
    ap.add_argument("--real", action="store_true",
                    help="P0: 追加真 LLM 端到端答案正确性验证（两版各跑一遍真实 DeepSeek）")
    args = ap.parse_args()

    if not os.path.exists(args.old_dir):
        print(f"ERROR: 旧版目录不存在 {args.old_dir}", flush=True)
        sys.exit(1)
    if not os.path.exists(args.new_dir):
        print(f"ERROR: 新版目录不存在 {args.new_dir}", flush=True)
        sys.exit(1)

    run_dir = os.path.join(
        args.runs_root, datetime.now().strftime("%Y%m%d_%H%M%S") + "_aaa_cmp")
    os.makedirs(run_dir, exist_ok=True)
    print(f"[run_dir] {run_dir}", flush=True)

    old_db = os.path.join(run_dir, "db_old", "chatbot.db")
    new_db = os.path.join(run_dir, "db_new", "chatbot.db")
    old_out = os.path.join(run_dir, "result_old.json")
    new_out = os.path.join(run_dir, "result_new.json")
    old_skip_out = os.path.join(run_dir, "result_old_skip_retrieval.json")

    # 新旧顺序执行（各自独立进程，memos 全局状态不冲突）
    rc_old = run_measure(args.old_dir, "old", old_db, old_out, seed=True)
    rc_new = run_measure(args.new_dir, "new", new_db, new_out, seed=True)
    # 对照组：旧版 LLM 忘记触发检索（同一旧版 DB，不重新播种）
    rc_old_skip = run_measure(args.old_dir, "old", old_db, old_skip_out,
                              seed=False, python_exe=None, extra_skip=True)

    if rc_old != 0 or rc_new != 0 or rc_old_skip != 0:
        print(f"ERROR: 测量进程退出码异常 old={rc_old} new={rc_new} "
              f"old_skip={rc_old_skip}", flush=True)
        sys.exit(1)

    # ── P0: 真 LLM 端到端验证（两版同 DB，不重新播种）──
    old_real = new_real = None
    if args.real:
        old_real_out = os.path.join(run_dir, "result_old_real.json")
        new_real_out = os.path.join(run_dir, "result_new_real.json")
        print("\n[P0] 真 LLM 端到端验证（DeepSeek，两版同模型同温度）...", flush=True)
        rc_old_real = run_measure(args.old_dir, "old", old_db, old_real_out,
                                  seed=False, real=True)
        rc_new_real = run_measure(args.new_dir, "new", new_db, new_real_out,
                                  seed=False, real=True)
        if rc_old_real != 0 or rc_new_real != 0:
            print(f"ERROR: real 测量失败 old_real={rc_old_real} new_real={rc_new_real}",
                  flush=True)
            sys.exit(1)
        old_real = load_json(old_real_out)
        new_real = load_json(new_real_out)

    old = load_json(old_out)
    new = load_json(new_out)
    old_skip = load_json(old_skip_out)
    report = build_report(old, old_skip, new, run_dir, old_real, new_real)
    report_path = os.path.join(run_dir, "compare_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print("\n════════ 对比报告 ════════", flush=True)
    print(report, flush=True)
    print(f"\n[report] {report_path}", flush=True)
    print(f"[artifacts] {run_dir}", flush=True)


if __name__ == "__main__":
    main()
