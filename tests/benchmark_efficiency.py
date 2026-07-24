"""
AAA → LLM → AAA 传输效率基准测试

测量每个阶段耗时，多轮取平均。
输出格式：markdown 表格 + 原始数据。

用法:
  python tests/benchmark_efficiency.py           # mock LLM 模式
  $env:USE_MOCK_LLM=0; python tests/benchmark_efficiency.py   # 真实 LLM
"""

import sys, os, json, time, statistics, importlib.util

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AAA_DIR = os.path.join(PROJECT_ROOT, "nodes", "node_python_aaa_cognition")
LLM_DIR = os.path.join(PROJECT_ROOT, "nodes", "node_python_llm_infer")

USE_MOCK = os.environ.get("USE_MOCK_LLM", "1") == "1"
ROUNDS = int(os.environ.get("BENCH_ROUNDS", "5"))

sys.path.insert(0, AAA_DIR)
sys.path.insert(0, LLM_DIR)


# ═══════════════════════════════════════════════
#  节点调用（直接导入，避开 sandbox 中文路径 bug）
# ═══════════════════════════════════════════════

def _import_and_call(node_dir, input_data):
    """导入节点 main.py，调用 process()，返回结果 + 耗时"""
    old_cwd = os.getcwd()
    old_path = list(sys.path)
    old_modules = set(sys.modules.keys())

    try:
        os.chdir(node_dir)
        sys.path = [node_dir] + old_path
        venv_sp = os.path.join(node_dir, "venv", "Lib", "site-packages")
        if os.path.isdir(venv_sp):
            sys.path.insert(0, venv_sp)

        spec = importlib.util.spec_from_file_location("_bnos_bench", os.path.join(node_dir, "main.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_bnos_bench"] = mod
        spec.loader.exec_module(mod)

        t0 = time.perf_counter()
        result = mod.process(input_data)
        elapsed = time.perf_counter() - t0

        # 按 main.py 格式包装
        if isinstance(result, list):
            out = {"code": 0, "data": result}
        else:
            port = result.pop("_port", "default")
            out = {"code": 0, "type": port, "data": result}
        return out, elapsed

    finally:
        os.chdir(old_cwd)
        sys.path = old_path
        for m in list(sys.modules.keys()):
            if m not in old_modules:
                del sys.modules[m]


# ═══════════════════════════════════════════════
#  Mock LLM
# ═══════════════════════════════════════════════

MOCK_LLM_REPLY = """【自然回复】
你好！今天有什么想聊的？
【心情】
开心
【想法】
今天是个好日子
【当前状态】
清醒
【事件摘要】
用户向 AI 打招呼
"""


# ═══════════════════════════════════════════════
#  测试主体
# ═══════════════════════════════════════════════

TEST_PROMPTS = [
    "你好",
    "今天天气真不错",
    "帮我介绍一下你自己",
    "你有什么兴趣爱好",
    "1+1等于几",
]


def main():
    print("=" * 70)
    print(f"  AAA → LLM → AAA 传输效率基准测试")
    print(f"  LLM 模式: {'MOCK（模拟）' if USE_MOCK else '真实 API'}")
    print(f"  测试轮数: {ROUNDS}")
    print("=" * 70)

    all_rows = []

    for i in range(ROUNDS):
        user_text = TEST_PROMPTS[i % len(TEST_PROMPTS)]
        row = {"round": i + 1, "input": user_text}
        print(f"\n── 第 {i+1} 轮: {user_text}")

        # ── Step 1: AAA 构建 prompt ──
        out1, t1 = _import_and_call(AAA_DIR, {
            "data_type": "text", "content": user_text, "source": "text",
        })
        row["t_aaa_build"] = round(t1, 3)
        print(f"  AAA 构建 prompt: {t1*1000:.0f}ms")

        prompt_data = out1.get("data", {})
        prompt_content = prompt_data.get("content", "")
        prompt_len = len(prompt_content)
        row["prompt_len"] = prompt_len

        # ── Step 2: LLM 推理 ──
        if USE_MOCK:
            t2 = 0.005  # 模拟延迟
            llm_content = MOCK_LLM_REPLY
        else:
            out2, t2 = _import_and_call(LLM_DIR, {
                "data_type": "prompt", "content": prompt_content,
            })
            llm_data = out2.get("data", {})
            llm_content = llm_data.get("content", "")

        row["t_llm_infer"] = round(t2, 3)
        row["llm_reply_len"] = len(llm_content)
        print(f"  LLM 推理: {t2*1000:.0f}ms (回复 {len(llm_content)} 字符)")

        # ── Step 3: AAA 解析 LLM 回复 ──
        out3, t3 = _import_and_call(AAA_DIR, {
            "data_type": "parsed", "content": llm_content,
        })
        row["t_aaa_parse"] = round(t3, 3)

        # 统计解析结果
        parsed_items = 0
        if isinstance(out3.get("data"), list):
            parsed_items = len(out3["data"])
        row["parsed_count"] = parsed_items

        total = t1 + t2 + t3
        row["t_total"] = round(total, 3)

        if not USE_MOCK:
            print(f"  AAA 解析: {t3*1000:.0f}ms ({parsed_items} 个输出)")
            print(f"  LLM 回复片段: {llm_content[:80]}...")
        print(f"  ─> 本轮总耗时: {total*1000:.0f}ms")

        all_rows.append(row)

    # ═══════════════════════════════════════════
    #  输出统计
    # ═══════════════════════════════════════════

    print("\n\n" + "=" * 70)
    print("  统计结果")
    print("=" * 70)

    for field, label in [
        ("t_aaa_build", "AAA 构建 prompt"),
        ("t_llm_infer", "LLM 推理"),
        ("t_aaa_parse", "AAA 解析"),
        ("t_total",     "总耗时"),
    ]:
        vals = [r[field] for r in all_rows]
        avg = statistics.mean(vals)
        _min = min(vals)
        _max = max(vals)
        print(f"  {label:20s}  avg={avg*1000:7.0f}ms  min={_min*1000:7.0f}ms  max={_max*1000:7.0f}ms")

    if not USE_MOCK:
        avg_prompt = statistics.mean([r["prompt_len"] for r in all_rows])
        avg_reply = statistics.mean([r["llm_reply_len"] for r in all_rows])
        print(f"\n  Prompt 平均长度: {avg_prompt:.0f} 字符")
        print(f"  LLM 回复平均长度: {avg_reply:.0f} 字符")

    print(f"\n  标记: LLM 模式={'MOCK' if USE_MOCK else 'REAL'}  轮次={ROUNDS}")
    print("=" * 70)


if __name__ == "__main__":
    main()
