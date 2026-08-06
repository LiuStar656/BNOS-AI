import os
import sys
import json
import time
import hashlib
import subprocess
import shutil
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime


def _is_frozen_exe() -> bool:
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


# ==================== 自愈逻辑 ====================

def check_and_repair_environment():
    if _is_frozen_exe():
        log("exe 模式，跳过 venv 检测", "INFO")
        return True

    venv_path = os.path.join(NODE_DIR, "venv")
    if os.name == "nt":
        python_exe = os.path.join(venv_path, "Scripts", "python.exe")
    else:
        python_exe = os.path.join(venv_path, "bin", "python")

    pyvenv_cfg = os.path.join(venv_path, "pyvenv.cfg")
    if os.path.exists(python_exe) and not os.path.exists(pyvenv_cfg):
        log("pyvenv.cfg 缺失，尝试修复...", "WARNING")
        try:
            _repair_pyvenv_cfg(venv_path)
            if os.path.exists(pyvenv_cfg):
                log("pyvenv.cfg 已重建")
                return True
        except Exception as e:
            log(f"重建失败: {e}", "ERROR")

    if not os.path.exists(python_exe):
        log("venv 异常，尝试自动修复...", "WARNING")
        if os.path.exists(venv_path):
            shutil.rmtree(venv_path, ignore_errors=True)
        software_root = os.path.dirname(NODE_DIR)
        create_node_script = os.path.join(software_root, "..", "python_create_node.py")
        if os.path.exists(create_node_script):
            try:
                subprocess.run(
                    [sys.executable, create_node_script, "--repair-only", NODE_DIR],
                    capture_output=True, text=True, timeout=120,
                )
                log("venv 重建成功")
                return True
            except Exception as e:
                log(f"重建失败: {e}", "ERROR")
                return False
        else:
            log("找不到 python_create_node.py，尝试直接创建 venv...", "WARNING")
            try:
                subprocess.run(
                    [sys.executable, "-m", "venv", venv_path],
                    capture_output=True, text=True, timeout=60,
                )
                log("venv 创建成功")
            except Exception as e:
                log(f"venv 创建失败: {e}", "ERROR")
                return False
    return True


if not check_and_repair_environment():
    log("环境修复失败", "ERROR")
    sys.exit(1)

# ==================== 配置加载 ====================

try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
except Exception as e:
    log(f"配置加载失败: {e}", "ERROR")
    sys.exit(1)

UPPER_FILE = os.path.abspath(os.path.join(NODE_DIR, cfg["listen_upper_file"])) if cfg.get("listen_upper_file") else ""
OUTPUT_FILE = os.path.abspath(os.path.join(NODE_DIR, cfg["output_file"])) if cfg.get("output_file") else ""
NODE_NAME = cfg["node_name"]
MY_FILTER = cfg.get("filter", {})
PROCESS_FLAG = f"_processed_{NODE_NAME}"

import atexit

PID_FILE = os.path.join(NODE_DIR, f"{NODE_NAME}.pid")


def cleanup():
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
        log("PID 文件已清理")
    log("程序已退出")


atexit.register(cleanup)


# ==================== 多源解析 ====================

def find_project_root():
    d = NODE_DIR
    for _ in range(5):
        if os.path.isfile(os.path.join(d, "pipeline.json")):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.dirname(NODE_DIR))


def resolve_input_sources():
    sources = []
    if UPPER_FILE:
        sources.append(UPPER_FILE)
    for port_name, mapping in cfg.get("port_mappings", {}).items():
        if isinstance(mapping, str):
            path = mapping if os.path.isabs(mapping) else os.path.abspath(os.path.join(NODE_DIR, mapping))
            sources.append(path)
    project_root = find_project_root()
    pipeline_path = os.path.join(project_root, "pipeline.json")
    if os.path.exists(pipeline_path):
        try:
            with open(pipeline_path, "r", encoding="utf-8") as f:
                pipeline = json.load(f)
            for edge in pipeline.get("edges", []):
                if edge["to"] == NODE_NAME:
                    src_node = edge["from"]
                    src_cfg_path = os.path.join(project_root, "nodes", src_node, "node_config.json")
                    if os.path.exists(src_cfg_path):
                        with open(src_cfg_path, "r", encoding="utf-8") as f2:
                            src_cfg = json.load(f2)
                        src_path = os.path.abspath(os.path.join(project_root, "nodes", src_node, src_cfg.get("output_file", "./output.json")))
                        if src_path not in sources:
                            sources.append(src_path)
        except Exception as e:
            log(f"解析 pipeline.json 输入源失败: {e}", "WARNING")
    return sources


def unwrap_data(data):
    if isinstance(data, dict) and "code" in data and "data" in data:
        inner = data["data"]
        if isinstance(inner, dict):
            return inner
    return data


def is_my_data(data):
    if not MY_FILTER:
        return True
    for _port_name, criteria in MY_FILTER.items():
        if all(data.get(k) == v for k, v in criteria.items()):
            return True
    return False


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
with open(PID_FILE, "w") as f:
    f.write(str(os.getpid()))
log(f"PID: {os.getpid()}")

# ==================== 并发处理 ====================
WRITE_LOCK = threading.Lock()
MAX_WORKERS = min(len(INPUT_SOURCES) or 1, 4)
_trackers = {p: 0.0 for p in INPUT_SOURCES}
_content_hashes = {}

RUNNING = True


def signal_handler(signum, frame):
    global RUNNING
    log("收到退出信号", "WARNING")
    RUNNING = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

log("=" * 50)


def _process_one(src_path, raw_data):
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
            py_path = os.path.join(NODE_DIR, "venv", "Scripts", "python.exe") if os.name == "nt" else os.path.join(NODE_DIR, "venv", "bin", "python")
            res = subprocess.run(
                [py_path, os.path.join(NODE_DIR, "main.py"), json.dumps(input_data)],
                capture_output=True, text=True, encoding="utf-8",
            )
            output = res.stdout.strip()

        if not output:
            log("空返回")
            return

        with WRITE_LOCK:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                f.write(output)

        raw_data[PROCESS_FLAG] = True
        with WRITE_LOCK:
            with open(src_path, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, indent=2, ensure_ascii=False)

        log(f"完成: {PROCESS_FLAG}")
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

                content_str = json.dumps(raw_data, ensure_ascii=False)
                content_hash = hashlib.md5(content_str.encode()).hexdigest()
                if content_hash == _content_hashes.get(src_path):
                    _trackers[src_path] = current_mtime
                    continue

                _trackers[src_path] = current_mtime
                _content_hashes[src_path] = content_hash

                if raw_data.get(PROCESS_FLAG):
                    continue
                if not is_my_data(raw_data):
                    continue

                log(f"新数据: {src_path}")
                executor.submit(_process_one, src_path, raw_data)

        except json.JSONDecodeError:
            log("数据包格式错误", "ERROR")
        except Exception as e:
            log(f"循环异常: {e}", "ERROR")

        time.sleep(0.1)
