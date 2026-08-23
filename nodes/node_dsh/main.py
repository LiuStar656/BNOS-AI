"""
BNOS 节点 — DeepSeek Harness 执行器官（node_dsh）

业务逻辑：接收 task 任务描述 → 调用 DSH headless（`dsh --profile headless <task>`）
执行完整 Agent 循环（工具调用/文件读写/shell/子 Agent）→ 返回最终回答。

集成要点：
- DSH 本体（@deepseek-ai/dsh）装在节点目录 node_modules/，节点自包含
- DSH_HOME 指向节点内 dsh_home/，headless profile 状态（sessions）隔离在节点内
- 模型 Key 从 llm_infer 节点 node_config.json 复用（运行时注入环境变量，不落盘）
- 工作区沙箱：nodes/shared/dsh_workspace/（DSH 唯一可读写目录）
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

NODE_DIR = Path(__file__).resolve().parent

# 节点任务活动状态文件（GUI 等待气泡实时文案的数据源，原子写）
_ACTIVITY_FILE = NODE_DIR.parent / "shared" / "node_activity.json"


def _write_activity(stage: str, text: str, rid: str = "") -> None:
    """原子写节点活动状态（tmp + replace，避免并发写撕裂）。"""
    try:
        data = {"stage": stage, "text": text, "ts": time.time()}
        if rid:
            data["request_id"] = rid
        _ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _ACTIVITY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_ACTIVITY_FILE)
    except OSError:
        pass

# 头部输出行数（headless 在最终回答前可能打印启动日志，最终回答在末尾）
DSH_TIMEOUT = 600  # Agent 任务可能执行多轮工具调用，放宽到 10 分钟

# 任务取消标记（GUI 终止按钮写入；DSH 执行期间检测到即 kill 子进程）
_CANCEL_FILE = NODE_DIR.parent / "shared" / "dsh_cancel.json"
_CANCEL_WINDOW_S = 60


def _cancel_requested() -> bool:
    """检测任务取消标记（时间窗口内有效）；检测到即消费删除。"""
    try:
        data = json.loads(_CANCEL_FILE.read_text(encoding="utf-8"))
        ts = float(data.get("ts", 0))
        if time.time() - ts <= _CANCEL_WINDOW_S:
            try:
                _CANCEL_FILE.unlink()
            except OSError:
                pass
            return True
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return False


def _kill_tree(proc: subprocess.Popen) -> None:
    """整树终止 DSH 子进程，防孤儿进程残留。

    Windows 上 `taskkill /T` 连子进程一起杀（DSH 会派生子 Agent/shell）；
    仅 kill 父进程会把 node.exe 变孤儿，永久占用管道句柄导致 listener 卡死。
    """
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _read_llm_key() -> str:
    """从 llm_infer 节点配置复用 DeepSeek API Key（单点维护）。"""
    cfg_path = NODE_DIR.parent / "node_python_llm_infer" / "node_config.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        for p in cfg.get("parameters", []):
            if p.get("name") == "api_key":
                return str(p.get("default", "")).strip()
    except (OSError, json.JSONDecodeError):
        pass
    return os.environ.get("DEEPSEEK_API_KEY", "")


def _resolve_dsh_cmd():
    """定位 DSH 入口，返回 (cwd, argv 前缀)。

    优先源码版（harness/，tsx 直接加载 TS，改源码即改即用）；
    fallback 到 npm 编译包（node_modules/@deepseek-ai/dsh）。
    """
    harness = NODE_DIR / "harness"
    src_bin = harness / "apps" / "cli" / "src" / "bin.ts"
    if src_bin.is_file() and (harness / "node_modules" / "tsx").exists():
        return str(harness), ["node", "--import", "tsx/esm", str(src_bin)]
    npm_bin = NODE_DIR / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    if npm_bin.is_file():
        return str(NODE_DIR), ["node", str(npm_bin)]
    return None, None


def _patch_has_entries(path: Path) -> bool:
    """extra.patch.yml 是否存在实际 patch 条目（仅注释/空白视为无内容）。

    DSH 的 loadOverlayPatches 要求 patch 文件顶层是 YAML 数组；仅注释的文件
    解析后为空数组同样报错，因此这里必须跳过"只有注释头"的文件。
    """
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return any(ln.strip() and not ln.strip().startswith("#") for ln in text.splitlines())


def _run_dsh(task: str, session_id: str = "") -> dict:
    """调用 DSH headless 执行单次 Agent 任务。

    session_id 非空时注入 DSH_SESSION_ID，由 fork 的 headless runner
    通过 agents.resume 续接已持久化会话（多轮对话保留上下文）；
    为空则新建会话，并从 DSH 输出解析新生成的 session_id 回带。
    """
    key = _read_llm_key()
    if not key:
        return {"ok": False, "message": "未找到 DeepSeek API Key（llm_infer 配置或 DEEPSEEK_API_KEY）", "result": ""}

    dsh_home = NODE_DIR / "dsh_home"
    workspace = NODE_DIR.parent / "shared" / "dsh_workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    run_cwd, cmd_prefix = _resolve_dsh_cmd()
    if not cmd_prefix:
        return {"ok": False, "message": "DSH 未安装（节点目录运行 start.bat 会自动安装）", "result": ""}

    env = os.environ.copy()
    env["DSH_HOME"] = str(dsh_home)
    env["DEEPSEEK_API_KEY"] = key
    # BNOS fork：共享协议目录（nodes/shared/）。headless runner 的
    # userQuestions provider 据此定位 dsh_question_in/out.json（DSH 提问回 GUI）。
    env["DSH_SHARED_DIR"] = str(NODE_DIR.parent / "shared")
    # 源码版 fork：Agent 工作根限定在沙箱目录（harness 的 process.cwd() 保持不变，
    # 但会话 header.cwd 使用 DSH_WORKDIR 覆盖）
    env["DSH_WORKDIR"] = str(workspace)
    # 运行时参数（GUI「DSH 管理」维护的 runtime.json）：默认温度 + 默认 Agent 预设。
    # 温度经 DSH_TEMPERATURE 注入 headless 的 agent/request；预设经 DSH_PRESET
    # 选择 roster（headless setup 挂载）；留空则不注入。
    runtime_json = dsh_home / "runtime.json"
    if runtime_json.is_file():
        try:
            rt = json.loads(runtime_json.read_text(encoding="utf-8"))
            temp = rt.get("temperature")
            if isinstance(temp, (int, float)) and not isinstance(temp, bool):
                env["DSH_TEMPERATURE"] = str(temp)
            preset = rt.get("preset")
            if isinstance(preset, str) and preset.strip():
                env["DSH_PRESET"] = preset.strip()
        except (OSError, json.JSONDecodeError):
            pass
    # 会话续接：非空则 fork 的 headless runner 走 agents.resume
    if session_id:
        env["DSH_SESSION_ID"] = session_id
    env.setdefault("PYTHONIOENCODING", "utf-8")

    # 附加 patch：GUI「DSH 管理」维护的 extra.patch.yml，存在实际 patch 条目
    # 才叠加加载。仅注释/空白的文件也会被 DSH 判定为非法顶层数组（必须非空，
    # 不能只看文本非空——注释头也算文本）
    cmd = cmd_prefix + ["--profile", "headless"]
    extra_patch = dsh_home / "profiles" / "headless" / "extra.patch.yml"
    if _patch_has_entries(extra_patch):
        cmd += ["--patch", str(extra_patch)]
    cmd.append(task)

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(run_cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
    except OSError as exc:
        return {"ok": False, "message": f"DSH 启动失败: {exc}", "result": ""}

    # 后台线程排空 stdout/stderr：不排空的话，DSH 输出超过管道缓冲
    # （Windows 约 64KB）会永久阻塞写端 → 进程"挂死"（CPU=0、永不退出）。
    out_lines: list[str] = []
    err_lines: list[str] = []

    def _pump(stream, sink) -> None:
        try:
            for line in iter(stream.readline, ""):
                sink.append(line)
        except (OSError, ValueError):
            pass

    pump_out = threading.Thread(target=_pump, args=(proc.stdout, out_lines), daemon=True)
    pump_err = threading.Thread(target=_pump, args=(proc.stderr, err_lines), daemon=True)
    pump_out.start()
    pump_err.start()

    # 执行期轮询：超时 / 用户终止（GUI 取消标记）→ 整树 kill 子进程
    start = time.time()
    cancelled = False
    while proc.poll() is None:
        if time.time() - start > DSH_TIMEOUT:
            _kill_tree(proc)
            return {"ok": False, "message": f"DSH 任务超时（>{DSH_TIMEOUT}s）", "result": ""}
        if _cancel_requested():
            _kill_tree(proc)
            cancelled = True
            break
        time.sleep(0.5)
    # 收尾：等 reader 线程读完残余输出（进程已退出，readline 立即返回）
    pump_out.join(timeout=5)
    pump_err.join(timeout=5)
    if cancelled:
        return {"ok": False, "message": "DSH 任务已取消", "result": "", "cancelled": True}

    if proc.returncode != 0:
        return {
            "ok": False,
            "message": f"DSH 执行失败（code {proc.returncode}）",
            "result": ("".join(err_lines) or "".join(out_lines)).strip()[-2000:],
        }

    stdout = "".join(out_lines).strip()
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    # 解析 fork 输出的 __BNOS_SESSION__=xxx 行（会话标识），其余为回答正文
    out_session = ""
    body = []
    for ln in lines:
        if ln.startswith("__BNOS_SESSION__="):
            out_session = ln.split("=", 1)[1].strip()
        else:
            body.append(ln)
    # fork 的 headless 只向 stdout 写 session 行 + outcome.text；回答正文
    # 含换行时会被拆成多行，必须整段拼接，不能只取末行（否则多行回答截断）
    final = "\n".join(body) if body else ""
    # fork 在 resume 失败时写 [bnos] resume session ... failed 提示并回退新会话
    resume_fallback = "[bnos] resume session" in "".join(err_lines)
    return {
        "ok": True,
        "message": "DSH 任务完成（会话续接失败，已新建会话）" if resume_fallback else "DSH 任务完成",
        "result": "\n".join(body)[-4000:],
        "final": final,
        # 优先回带 DSH 实际使用的会话 id（新建/续接/回退均为真实 id），
        # 解析不到时（异常路径）才回带输入 id
        "session_id": out_session or session_id,
    }


class MyNode:
    """节点的业务逻辑处理器。"""

    def __init__(self):
        pass

    def process(self, data: dict) -> dict:
        task = data.get("task", "")
        if isinstance(task, dict):
            task = task.get("text", "")
        task = str(task).strip()
        if not task:
            return {"ok": False, "message": "缺少 task 字段"}
        # 上报活动状态：DSH 执行中（GUI 等待气泡实时显示；执行期间可能长时无回复）
        _write_activity("dsh", "DSH 正在执行中…", str(data.get("task_id", "")))
        # BNOS 语言约束：DSH 内置默认系统提示为英文（headless 未挂预设），
        # 注入中文要求让模型以简体中文思考、回复与说明操作（含工具调用前的
        # 操作说明/权限申请描述）。置于 task 最前，作为最高优先级指令。
        task = "（语言要求）始终使用简体中文思考、回复与说明操作。\n" + task
        # 工作模式直通：AAA 携带完整上下文，拼入 task 前缀让 DSH 带背景执行。
        # 字段须与 AAA _gather_context 产出对齐（personality 为角色种子性格段，
        # perception/other_cognition/self_info/mood 等为认知画像；字段缺失跳过）。
        context = data.get("context")
        if isinstance(context, dict) and context:
            sys_prompt = context.get("system_prompt")
            if isinstance(sys_prompt, str) and sys_prompt.strip():
                # AAA 直通（工作模式）：注入 AAA 完整提示词（人格+认知+行为准则+
                # 输出格式），DSH 替代 LLM 层按其执行并组织回复
                task = (
                    "（语言要求）始终使用简体中文思考、回复与说明操作。\n\n"
                    "（完整系统提示）你是本机 AI 助手，以下是你的人格、认知与行为"
                    "准则。请据此执行其中的用户请求（可调用工具完成任务），并严格"
                    "按其中的【输出格式】组织最终回复：\n"
                    + sys_prompt.strip()
                )
            else:
                # 普通直连（GUI/AAA 工具路径）：携带背景上下文拼入 task 前缀。
                # 字段须与 AAA _gather_context 产出对齐（personality 为角色种子
                # 性格段，perception/other_cognition/self_info/mood 等为认知画像；
                # 字段缺失跳过）。
                lines = []
                for key in ("personality", "self_cognition", "fixed_cognition", "other_cognition",
                            "recent_feelings", "mood", "mood_trend", "recent_observations",
                            "perception", "history_summary", "self_info", "user_info"):
                    val = context.get(key)
                    if isinstance(val, str) and val.strip():
                        lines.append(f"{key}: {val.strip()}")
                if lines:
                    task = "（背景上下文）\n" + "\n".join(lines) + "\n（用户请求）\n" + task
        session_id = str(data.get("session_id", "")).strip()
        result = _run_dsh(task, session_id)
        # 任务标识回带：GUI 侧 dsh.run_task_sync 以 task_id 精确判定"本次任务完成"
        task_id = str(data.get("task_id", "")).strip()
        if task_id:
            result["task_id"] = task_id
        return result


# ════════════════════════════════════════════════════════════════
#  框架桥接（开发者不要修改）
# ════════════════════════════════════════════════════════════════

_node = MyNode()


def process(data: dict) -> dict:
    """框架入口，由 listener.py 或 import 调用。"""
    return _node.process(data)


if __name__ == "__main__":
    input_data = {}
    if len(sys.argv) >= 2:
        try:
            input_data = json.loads(sys.argv[1])
        except Exception:
            pass
    if not input_data:
        s = sys.stdin.read().strip()
        if s:
            input_data = json.loads(s)
    if not input_data:
        print(json.dumps({"code": -1, "error": "no input"}, ensure_ascii=False))
        sys.exit(1)

    result = process(input_data)
    port = result.pop("_port", None)
    output = {"code": 0, "data": result}
    if port:
        output["type"] = port
    print(json.dumps(output, ensure_ascii=False))
