import os
import sys
import json
import time
import hashlib
import subprocess
import shutil
import signal
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FTimeoutError
from datetime import datetime


def _is_frozen_exe() -> bool:
    """检测是否为 Nuitka/PyInstaller 打包的 exe"""
    if getattr(sys, 'frozen', False):
        return True
    try:
        __import__('__compiled__')
        return True
    except ImportError:
        pass
    if sys.argv[0].lower().endswith('.exe'):
        return True
    return False


def _repair_pyvenv_cfg(venv_path):
    """重建缺失的 pyvenv.cfg"""
    cfg_content = f"""home = {os.path.dirname(sys.executable)}
implementation = CPython
version_info = {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}
include-system-site-packages = false
base-prefix = {sys.prefix}
base-exec-prefix = {sys.prefix}
base-executable = {sys.executable}
"""
    cfg_path = os.path.join(venv_path, "pyvenv.cfg")
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(cfg_content)


# exe 模式下用 cwd（Popen 已设 cwd=node_path），开发模式用 __file__
if _is_frozen_exe():
    NODE_DIR = os.getcwd()
else:
    NODE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(NODE_DIR, "node_config.json")
LOG_DIR = os.path.join(NODE_DIR, "logs")

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)


def log(msg, level="INFO"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] [{level}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        pass
    with open(os.path.join(LOG_DIR, "listener.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ==================== 自愈逻辑：启动前环境检测与修复 ====================

def check_and_repair_environment():
    """检测并修复虚拟环境"""
    if _is_frozen_exe():
        log("exe 模式，跳过 venv 检测", "INFO")
        return True

    venv_path = os.path.join(NODE_DIR, "venv")

    # 检测Python解释器
    if os.name == "nt":
        python_exe = os.path.join(venv_path, "Scripts", "python.exe")
    else:
        python_exe = os.path.join(venv_path, "bin", "python")

    pyvenv_cfg = os.path.join(venv_path, "pyvenv.cfg")
    if os.path.exists(python_exe) and not os.path.exists(pyvenv_cfg):
        log(f"检测到 pyvenv.cfg 缺失，尝试自动修复...", "WARNING")
        try:
            _repair_pyvenv_cfg(venv_path)
            if os.path.exists(pyvenv_cfg):
                log("pyvenv.cfg 已重建")
                return True
        except Exception as e:
            log(f"重建 pyvenv.cfg 失败: {e}", "ERROR")

    if not os.path.exists(python_exe):
        log("检测到虚拟环境异常，尝试自动修复...", "WARNING")

        if os.path.exists(venv_path):
            try:
                shutil.rmtree(venv_path, ignore_errors=True)
                log("已清理损坏的虚拟环境")
            except Exception as e:
                log(f"清理失败: {e}", "ERROR")
                return False

        software_root = os.path.dirname(NODE_DIR)
        create_node_script = os.path.join(software_root, "..", "python_create_node.py")

        if os.path.exists(create_node_script):
            log("开始重建虚拟环境...")
            try:
                result = subprocess.run(
                    [sys.executable, create_node_script, "--repair-only", NODE_DIR],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    encoding="utf-8",
                )
                if result.returncode == 0:
                    log("虚拟环境重建成功")
                    return True
                else:
                    log(f"重建失败: {result.stderr}", "ERROR")
                    return False
            except Exception as e:
                log(f"重建异常: {e}", "ERROR")
                return False
        else:
            log("找不到python_create_node.py，无法自动修复", "ERROR")
            log("请手动删除venv文件夹后重新创建节点", "WARNING")
            return False

    return True


def resolve_python() -> str:
    """优先使用 venv Python，不存在则回退到系统 Python。"""
    if _is_frozen_exe():
        return sys.executable
    venv_py = os.path.join(NODE_DIR, "venv", "Scripts", "python.exe") if os.name == "nt" else os.path.join(NODE_DIR, "venv", "bin", "python")
    if os.path.exists(venv_py):
        return venv_py
    log("venv Python 不存在，使用系统 Python", "WARNING")
    return sys.executable


# 执行环境检测
if _is_frozen_exe():
    pass
elif not check_and_repair_environment():
    log("环境修复失败，将尝试使用系统 Python 运行", "WARNING")

# ==================== 自愈逻辑结束 ====================

try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
except Exception as e:
    log(f"配置加载失败: {e}", "ERROR")
    sys.exit(1)

UPPER_FILE = os.path.abspath(os.path.join(NODE_DIR, cfg["listen_upper_file"])) if cfg.get("listen_upper_file") else ""
OUTPUT_FILE = os.path.abspath(os.path.join(NODE_DIR, cfg["output_file"])) if cfg.get("output_file") else ""
# ==================== 多端口输出路由 ====================
OUTPUT_PORTS = {}
for port in cfg.get("output_ports", []):
    if isinstance(port, dict) and port.get("name"):
        fpath = port.get("output_file", "")
        if fpath:
            OUTPUT_PORTS[port["name"]] = os.path.abspath(os.path.join(NODE_DIR, fpath))
# ==================== 多端口输出路由结束 ====================
NODE_NAME = cfg["node_name"]
MY_FILTER = cfg.get("filter", {})
PROCESS_FLAG = f"_processed_{NODE_NAME}"

import atexit

PID_FILE = os.path.join(NODE_DIR, f"{NODE_NAME}.pid")


def cleanup():
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
        log("PID 文件已清理")
    _stop_local_backend()
    log("程序已退出")


atexit.register(cleanup)

# ==================== port_mappings 数据路由 ====================

def find_project_root():
    """从 NODE_DIR 向上查找项目根目录（包含 pipeline.json）"""
    d = NODE_DIR
    for _ in range(5):
        if os.path.isfile(os.path.join(d, "pipeline.json")):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.dirname(NODE_DIR))


def resolve_input_sources():
    """自动解析输入源文件列表。"""
    sources = []

    # 1. listen_upper_file
    if UPPER_FILE:
        sources.append(UPPER_FILE)

    # 2. port_mappings 字符串值（输入端口 → 文件路径）
    for port_name, mapping in cfg.get("port_mappings", {}).items():
        if isinstance(mapping, str):
            path = mapping if os.path.isabs(mapping) else os.path.abspath(os.path.join(NODE_DIR, mapping))
            sources.append(path)

    # 3. pipeline.json edges
    project_root = find_project_root()
    pipeline_path = os.path.join(project_root, "pipeline.json")
    nodes_dir = os.path.join(project_root, "nodes")

    if os.path.exists(pipeline_path):
        try:
            with open(pipeline_path, "r", encoding="utf-8") as f:
                pipeline = json.load(f)
            for edge in pipeline.get("edges", []):
                if edge["to"] == NODE_NAME:
                    src_node = edge["from"]
                    src_node_dir = os.path.join(nodes_dir, src_node)
                    src_cfg_path = os.path.join(src_node_dir, "node_config.json")
                    if os.path.exists(src_cfg_path):
                        with open(src_cfg_path, "r", encoding="utf-8") as f2:
                            src_cfg = json.load(f2)
                        src_output = src_cfg.get("output_file", "./output.json")
                        src_path = os.path.abspath(os.path.join(src_node_dir, src_output))
                        if src_path not in sources:
                            sources.append(src_path)
                            log(f"  上游节点 [{src_node}] → {src_path}")
        except Exception as e:
            log(f"解析 pipeline.json 输入源失败: {e}", "WARNING")

    # 大小写规范化去重（Windows 上 E:\ 和 e:\ 是同一路径）
    seen = set()
    deduped = []
    for p in sources:
        key = os.path.normcase(p)
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped


def unwrap_data(data):
    """如果数据是包装格式 {'code': 0, 'data': {...}}，提取内层 data"""
    if isinstance(data, dict) and "code" in data and "data" in data:
        inner = data["data"]
        if isinstance(inner, dict):
            return inner
    return data


def is_my_data(data):
    if not MY_FILTER:
        return True
    # 匹配任一端口条件即可通过
    for _port_name, criteria in MY_FILTER.items():
        if all(data.get(k) == v for k, v in criteria.items()):
            return True
    return False


# ==================== 本地 LLM 服务管理 ====================

_llama_server_backend = None


def _get_param(name, default=None):
    """从 cfg 的 parameters 中提取参数值"""
    for p in cfg.get("parameters", []):
        if p.get("name") == name:
            return p.get("default", default)
    return default


def _start_local_backend():
    """根据配置启动本地 llama-server（http_server 模式）"""
    global _llama_server_backend
    if _is_frozen_exe():
        return
    model_type = _get_param("model_type", "http_server")
    if model_type != "http_server":
        return

    try:
        from backends import LlamaServerBackend
        params = {p["name"]: p.get("default") for p in cfg.get("parameters", [])}
        backend = LlamaServerBackend(params)
        if backend.start():
            _llama_server_backend = backend
            log(f"llama-server 已启动 (pid={backend.server_process.pid if backend.server_process else 'existing'})")
        else:
            log("llama-server 启动失败，推理时将降级为 cli_local 模式", "WARNING")
    except Exception as e:
        log(f"llama-server 启动异常: {e}，推理时将降级为 cli_local 模式", "WARNING")


def _stop_local_backend():
    """停止本地 llama-server"""
    global _llama_server_backend
    if _llama_server_backend:
        _llama_server_backend.stop()
        _llama_server_backend = None
        log("llama-server 已停止")


# ==================== 解析输入源 ====================

INPUT_SOURCES = resolve_input_sources()

if not INPUT_SOURCES:
    log("没有配置任何输入源，将保持待机状态等待数据...", "INFO")
else:
    log(f"输入源 ({len(INPUT_SOURCES)} 个):")
    for s in INPUT_SOURCES:
        log(f"  - {s}")


log("=" * 50)
log(f"节点启动: {NODE_NAME}")
log(f"过滤: {MY_FILTER}")
log("当前环境: 独立虚拟环境（可迁移模式+自愈）")
with open(PID_FILE, "w") as f:
    f.write(str(os.getpid()))
log(f"PID 文件已生成: {PID_FILE}")

# 启动本地 llama-server（如果配置为 http_server 模式）
_start_local_backend()

RUNNING = True


def signal_handler(signum, frame):
    global RUNNING
    log("收到退出信号，准备退出...", "WARNING")
    RUNNING = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

log("=" * 50)

# ==================== 并发处理 ====================
WRITE_LOCK = threading.Lock()

_LLM_MAIN = None

def _get_llm_main():
    """惰性加载 main 模块。LLM 的 MyNode 不预加载大模型，仅启动后端。"""
    global _LLM_MAIN
    if _LLM_MAIN is not None:
        return _LLM_MAIN
    import main as _m
    _LLM_MAIN = _m
    log("已加载 LLM main 模块")
    return _LLM_MAIN

MAX_WORKERS = min(len(INPUT_SOURCES) or 1, 8)  # 最多 8 线程
_trackers = {p: 0.0 for p in INPUT_SOURCES}
_content_hashes = {}


def _process_one(src_path, raw_data):
    """在线程中处理单条数据，不影响主循环轮询"""
    try:
        input_data = unwrap_data(raw_data)
        log(f"处理: {src_path}")

        if _is_frozen_exe():
            import importlib
            _node_main = importlib.import_module("_bnos_main")
            _node_main.NODE_DIR = NODE_DIR
            result = _node_main.process(input_data)
            output = json.dumps({
                "code": 0,
                "type": cfg.get("output_type", "default"),
                "data": result
            }, ensure_ascii=False)
        else:
            # 直接 import 调用，避免子进程开销
            llm_main = _get_llm_main()
            with ThreadPoolExecutor(max_workers=1) as _timeout_pool:
                future = _timeout_pool.submit(llm_main.process, input_data)
                try:
                    result = future.result(timeout=180)
                except _FTimeoutError:
                    log(f"处理超时 [{src_path}]: 超过 180 秒未返回", "ERROR")
                    return
            # 格式化输出（与 main.py __main__ 块逻辑一致）
            if isinstance(result, list):
                output_obj = {"code": 0, "data": result}
            else:
                port = result.pop("_port") if "_port" in result else cfg.get("output_type", "default")
                output_obj = {"code": 0, "type": port, "data": result}
            output = json.dumps(output_obj, ensure_ascii=False)

        if not output:
            log("空返回")
            return

        # 写 output 加锁防止并发写错乱
        with WRITE_LOCK:
            # 按端口路由输出：根据 type 字段选择对应文件
            try:
                output_obj = json.loads(output)
                port_name = output_obj.get("type", "default")
                out_path = OUTPUT_PORTS.get(port_name, OUTPUT_FILE)
            except (json.JSONDecodeError, KeyError):
                out_path = OUTPUT_FILE
            out_dir = os.path.dirname(out_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output)
            log(f"写入 {out_path}")

        # 标记已处理
        if isinstance(input_data, dict):
            raw_data[PROCESS_FLAG] = True
            with WRITE_LOCK:
                with open(src_path, "w", encoding="utf-8") as f:
                    json.dump(raw_data, f, indent=2, ensure_ascii=False)
                log(f"标记: {PROCESS_FLAG}")

    except subprocess.TimeoutExpired:
        log(f"处理超时 [{src_path}]: 子进程超过 180 秒未返回", "ERROR")
    except Exception as e:
        log(f"处理异常 [{src_path}]: {e}", "ERROR")


# ── 主循环：快速检查 → 提交到线程池 ──
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    while RUNNING:
        try:
            for src_path in INPUT_SOURCES:
                if not os.path.isfile(src_path):
                    continue

                try:
                    current_mtime = os.path.getmtime(src_path)
                except OSError:
                    continue

                if current_mtime <= _trackers.get(src_path, 0.0):
                    continue

                try:
                    with open(src_path, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    _trackers[src_path] = current_mtime
                    continue

                # 内容哈希去重
                content_str = json.dumps(raw_data, ensure_ascii=False)
                content_hash = hashlib.md5(content_str.encode()).hexdigest()
                if content_hash == _content_hashes.get(src_path):
                    _trackers[src_path] = current_mtime
                    continue

                _trackers[src_path] = current_mtime
                _content_hashes[src_path] = content_hash

                # 检查防重标记（检查 raw_data，因为 _process_one 写标记到外层）
                if isinstance(raw_data, dict) and raw_data.get(PROCESS_FLAG):
                    continue
                if not is_my_data(unwrap_data(raw_data)):
                    continue

                log(f"新数据: {src_path}")
                # 丢到线程池异步处理，不阻塞轮询
                executor.submit(_process_one, src_path, raw_data)

        except json.JSONDecodeError:
            log("数据包格式错误", "ERROR")
        except Exception as e:
            log(f"循环异常: {e}", "ERROR")

        time.sleep(0.1)
