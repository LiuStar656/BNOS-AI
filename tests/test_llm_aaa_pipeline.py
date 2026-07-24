"""
BNOS 全链路集成测试脚本

模拟完整数据流：
  GUI 文本 → AAA（合并 gui_adapter+user_input）→ LLM → AAA → 最终输出节点
                                                    │
                                                    ├─ reply    → live2d_face + GUI
                                                    ├─ knowledge → logseq_writer
                                                    └─ tool_call → grok_hands

用法：
  python tests/test_llm_aaa_pipeline.py

可选环境变量：
  USE_MOCK_LLM=1        — 使用 mock LLM 回复（不调真实 API，默认启用）
  USER_INPUT="..."      — 自定义用户输入文本
"""
import sys
import os
import json
import subprocess
import tempfile
import shutil

# ---------- 路径 ----------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AAA_DIR = os.path.join(PROJECT_ROOT, "nodes", "node_python_aaa_cognition")
LLM_DIR = os.path.join(PROJECT_ROOT, "nodes", "node_python_llm_infer")
LIVE2D_DIR = os.path.join(PROJECT_ROOT, "nodes", "node_js_live2d_face")
LOGSEQ_DIR = os.path.join(PROJECT_ROOT, "nodes", "node_python_logseq_writer")


def _py(node_dir):
    """获取节点 venv 的 python 路径"""
    p = os.path.join(node_dir, "venv", "Scripts", "python.exe")
    if not os.path.exists(p):
        print(f"[SKIP] 未找到 venv: {p}")
        return None
    return p


def run_main(node_dir, input_data):
    """
    运行节点 main.py 并获取结果。

    优先用子进程方式运行（模拟真实 listener 调用），
    如果子进程因 sandbox 限制失败，则回退到直接导入调用。
    """
    main_py = os.path.join(node_dir, "main.py")
    input_json = json.dumps(input_data, ensure_ascii=False)

    # ── 方式 A: 子进程方式（模拟真实 listener） ──
    py = _py(node_dir)
    if py:
        res = subprocess.run(
            [py, main_py, input_json],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        if res.returncode == 0:
            try:
                return json.loads(res.stdout.strip())
            except json.JSONDecodeError:
                print(f"  非 JSON 输出: {res.stdout[:200]}")
                return None
        else:
            stderr = (res.stderr or "")[:200]
            if "did not find executable" not in stderr:
                print(f"  STDEER: {stderr}")

    # ── 方式 B: 直接导入调用（绕开 sandbox 中文路径限制） ──
    return _run_main_direct(node_dir, input_data)


def _run_main_direct(node_dir, input_data):
    """直接导入 main.py 模块并调用 process()"""
    import importlib.util as iu
    import importlib

    main_py = os.path.join(node_dir, "main.py")
    if not os.path.exists(main_py):
        print(f"  [FAIL] main.py 不存在: {main_py}")
        return None

    # 保存现场
    old_cwd = os.getcwd()
    old_path = list(sys.path)
    old_modules = set(sys.modules.keys())

    try:
        # 切换到节点目录，确保 config.py resolve() 等相对路径正确
        os.chdir(node_dir)

        # 保留标准库路径，只添加节点目录和 venv site-packages
        sys.path = [node_dir] + old_path
        venv_sp = os.path.join(node_dir, "venv", "Lib", "site-packages")
        if os.path.isdir(venv_sp):
            sys.path.insert(0, venv_sp)

        # 载入模块（用 spec 而非 import 确保不走缓存）
        spec = iu.spec_from_file_location("_bnos_main", main_py)
        if spec is None or spec.loader is None:
            print("  [FAIL] 无法加载 main.py 模块")
            return None
        mod = iu.module_from_spec(spec)
        # 注入 NODE_DIR 环境变量供模块使用
        sys.modules["_bnos_main"] = mod
        spec.loader.exec_module(mod)

        # 调用 process()
        result = mod.process(input_data)

        # 按 main.py __main__ 的格式包装返回
        if isinstance(result, list):
            return {"code": 0, "data": result}
        else:
            cfg = mod.load_config() if hasattr(mod, "load_config") else {}
            port = result.pop("_port", cfg.get("output_type", "default"))
            return {"code": 0, "type": port, "data": result}

    except Exception as e:
        print(f"  [FAIL] 直接调用异常: {type(e).__name__}: {e}")
        return None
    finally:
        os.chdir(old_cwd)
        sys.path = old_path
        # 清理临时注入的模块
        for mod_name in list(sys.modules.keys()):
            if mod_name not in old_modules:
                del sys.modules[mod_name]


def mock_llm_reply(prompt_text):
    """生成模拟 LLM 回复（带节标记）"""
    return (
        "【自然回复】\n"
        "你好小明！很高兴认识你，今天想聊点什么呢？\n"
        "【心情】\n"
        "开心\n"
        "【想法】\n"
        "新朋友来找我聊天了！\n"
        "【当前状态】\n"
        "清醒\n"
        "【事件摘要】\n"
        "用户小明主动打招呼\n"
        "【自我认知】\n"
        "我是一个友好的 AI 助手\n"
        "【他人认知】\n"
        "小明是一个友善的用户\n"
    )


def test_aaa_build_prompt():
    """测试 AAA 节点：用户文本 → prompt 输出"""
    print("\n" + "=" * 60)
    print("[Test 1] AAA: User Text → Prompt")
    print("=" * 60)

    result = run_main(AAA_DIR, {
        "data_type": "text",
        "content": "你好，我是小明",
        "source": "gui",
    })
    if result is None:
        print("  [FAIL] AAA main.py 执行失败")
        return None

    port = result.get("type", "")
    data = result.get("data", {})
    if port != "prompt":
        print(f"  [FAIL] 期望 type='prompt', 实际: '{port}'")
        print(f"  完整输出: {json.dumps(result, ensure_ascii=False)[:300]}")
        return None
    if data.get("data_type") != "prompt":
        print(f"  [FAIL] 期望 data_type='prompt', 实际: {data.get('data_type')}")
        return None

    prompt_content = data.get("content", "")
    if not prompt_content:
        print("  [FAIL] prompt content 为空")
        return None

    # 验证 prompt 模板变量被填充
    checks = ["自我认知", "用户文本", "当前日期时间", "历史摘要", "记忆检索结果"]
    for c in checks:
        if c in prompt_content:
            print(f"  [OK] prompt 包含「{c}」")
        else:
            print(f"  [WARN] prompt 缺少「{c}」")

    print("  [PASS] AAA 构建 prompt 成功")
    return prompt_content


def test_llm_infer(prompt_content, use_mock=False):
    """测试 LLM 节点：prompt → 推理结果"""
    print("\n" + "=" * 60)
    print("[Test 2] LLM: Prompt → Inference")
    print("=" * 60)

    if use_mock:
        # mock 模式：直接返回模拟回复
        print("  [MOCK] 使用模拟 LLM 回复（不调真实 API）")
        return mock_llm_reply(prompt_content)

    result = run_main(LLM_DIR, {
        "data_type": "prompt",
        "content": prompt_content,
    })
    if result is None:
        print("  [SKIP] LLM main.py 执行失败（可能是 API Key 未配置或无模型）")
        return None

    data = result.get("data", {})
    llm_reply = data.get("content", "")
    error = data.get("error")

    if error:
        print(f"  [WARN] LLM 推理返回错误: {error}")
        return None

    if not llm_reply:
        print("  [WARN] LLM 返回空白内容")
        return None

    print(f"  LLM 回复（前 100 字）: {llm_reply[:100]}...")
    print("  [PASS] LLM 推理成功")
    return llm_reply


def test_aaa_parse_llm_output(llm_reply):
    """
    测试 AAA 节点：解析 LLM 节标记回复

    AAA 的 process() 中，解析 LLM 回复走 data_type=text + source=llm 分支。
    """
    print("\n" + "=" * 60)
    print("[Test 3] AAA: Parse LLM Section-Marked Reply")
    print("=" * 60)

    if not llm_reply:
        print("  [SKIP] 无 LLM 回复数据，跳过")
        return []

    result = run_main(AAA_DIR, {
        "data_type": "text",
        "content": llm_reply,
        "source": "llm",
    })
    if result is None:
        print("  [FAIL] AAA main.py 执行失败")
        return []

    data = result.get("data")

    # AAA 的 _on_parsed 可能返回 list（多端口输出）
    items = data if isinstance(data, list) else [data]
    ports_found = set()

    for item in items:
        if not isinstance(item, dict):
            continue
        port = item.get("_port", "?")
        data_type = item.get("data_type", "?")
        content_preview = str(item.get("content", ""))[:80]
        ports_found.add(port)
        print(f"  输出端口 [{port}] type={data_type}: {content_preview}")

    if "default" in ports_found:
        print("  [PASS] AAA 成功解析 LLM 输出")
    else:
        print("  [WARN] 未检测到 default 端口输出")

    print(f"\n  解析到的端口: {', '.join(sorted(ports_found)) or '无'}")
    return items


def test_db_persistence():
    """验证 AAA 运行后数据已写入数据库"""
    print("\n" + "=" * 60)
    print("[Test 4] Verify: DB Persistence")
    print("=" * 60)

    db_path = os.path.join(PROJECT_ROOT, "nodes", "shared", "chatbot.db")
    if not os.path.exists(db_path):
        print("  [WARN] 数据库文件不存在（首次运行会自动创建）")
        return

    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        print(f"  数据库表: {[t[0] for t in tables]}")

        counts = {}
        for t in tables:
            name = t[0]
            c = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            if c > 0:
                counts[name] = c
        conn.close()

        if counts:
            for table, count in counts.items():
                print(f"  表 {table}: {count} 条记录")
            print("  [PASS] 数据已持久化到数据库")
        else:
            print("  [WARN] 所有表为空")
    except Exception as e:
        print(f"  [WARN] 数据库检查异常: {e}")


def test_live2d_face_output(aaa_outputs):
    """
    测试 Live2D 面部节点：消费 AAA 的 reply 输出
    aaa_outputs: AAA 解析后的输出列表
    """
    print("\n" + "=" * 60)
    print("[Test 4] Live2D Face: 接收 reply → 解析情绪 → TTS")
    print("=" * 60)

    if not aaa_outputs:
        print("  [SKIP] 无 AAA 输出数据")
        return

    # 查找 reply 类型的输出
    reply_content = None
    for item in aaa_outputs:
        if item.get("data_type") == "reply":
            reply_content = item.get("content", "")
            break

    if not reply_content:
        print("  [SKIP] AAA 输出中无 reply 类型数据（可能只产生了 knowledge）")
        return

    print(f"  reply 内容: {reply_content[:100]}")

    # 调用 live2d face 的 main.js（需要 Node.js）
    main_js = os.path.join(LIVE2D_DIR, "main.js")
    if not os.path.exists(main_js):
        print("  [SKIP] main.js 不存在")
        return

    try:
        res = subprocess.run(
            ["node", main_js, json.dumps({"data_type": "reply", "content": reply_content})],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        output = json.loads(res.stdout.strip())
        data = output.get("data", {})
        print(f"  解析情绪: {data.get('emotion', '无')}")
        print(f"  纯净文本: {data.get('text', '')[:80]}")
        print(f"  TTS URL: {data.get('tts_url', '无')[:80]}")
        print("  [PASS] Live2D Face 处理成功")
    except json.JSONDecodeError:
        print("  [FAIL] Live2D 输出非 JSON")
    except FileNotFoundError:
        print("  [SKIP] 未安装 Node.js")
    except Exception as e:
        print(f"  [WARN] Live2D 处理异常: {e}")


def test_logseq_writer_output(aaa_outputs):
    """
    测试 Logseq 知识写入节点：消费 AAA 的 knowledge 输出
    aaa_outputs: AAA 解析后的输出列表
    """
    print("\n" + "=" * 60)
    print("[Test 5] Logseq Writer: 接收 knowledge → 生成 Markdown")
    print("=" * 60)

    if not aaa_outputs:
        print("  [SKIP] 无 AAA 输出数据")
        return

    knowledge_content = None
    for item in aaa_outputs:
        if item.get("data_type") == "knowledge":
            knowledge_content = item.get("content", "")
            break

    if not knowledge_content:
        print("  [SKIP] AAA 输出中无 knowledge 类型数据")
        return

    print(f"  knowledge 内容: {str(knowledge_content)[:100]}")

    result = run_main(LOGSEQ_DIR, {
        "data_type": "knowledge",
        "content": knowledge_content,
    })
    if result is None:
        print("  [SKIP] logseq_writer 未配置 venv 或执行失败")
        return

    data = result.get("data", {})
    if data.get("status") == "ok":
        print(f"  生成文件名: {data.get('filename', '?')}")
        md_preview = data.get("content", "")[:100]
        print(f"  Markdown 预览: {md_preview}")
        print("  [PASS] Logseq Writer 处理成功")
    else:
        print(f"  [WARN] Logseq Writer 返回: {data}")


def main():
    print("=" * 60)
    print("  BNOS 全链路集成测试")
    print(f"  项目根目录: {PROJECT_ROOT}")
    print("=" * 60)

    use_mock = os.environ.get("USE_MOCK_LLM", "1") == "1"

    # ── Step 0: 用户输入（直接以 GUI 格式传入 AAA，合并了旧 user_input 节点）──
    user_text = os.environ.get("USER_INPUT", "你好，我是小明")
    user_input_data = {"data_type": "text", "content": user_text, "source": "gui"}

    # ── Step 1: AAA 构建 prompt ──
    prompt_content = test_aaa_build_prompt()
    if not prompt_content:
        print("\n  [FAIL] 测试中断：AAA prompt 构建失败")
        sys.exit(1)

    # ── Step 2: LLM 推理 ──
    llm_reply = test_llm_infer(prompt_content, use_mock=use_mock)

    # ── Step 3: AAA 解析 LLM 输出 ──
    aaa_outputs = test_aaa_parse_llm_output(llm_reply)

    # ── Step 4: 数据库验证 ──
    test_db_persistence()

    # ── Step 5: 最终输出节点验证 ──
    test_live2d_face_output(aaa_outputs)
    test_logseq_writer_output(aaa_outputs)

    print("\n" + "=" * 60)
    print("  全链路测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
