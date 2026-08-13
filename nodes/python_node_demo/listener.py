"""
BNOS Python 节点监听器 — 多源监听 + 线程池并发 + venv 自愈

数据流：
  输入源（resolve_input_sources 自动解析）
    ↓  mtime → 内容哈希去重 → filter 匹配 → processed 标记检查
    ↓
  ThreadPoolExecutor.submit(_process_one, ...)
    ↓
  main.py（subprocess.run + timeout）
    ↓
  多端口路由输出（OUTPUT_PORTS）
    ↓
  标记上游文件 _processed_<node_name>
"""

import atexit
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════
#  NODE_DIR 解析（支持 exe 打包模式）
# ═══════════════════════════════════════════


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


if _is_frozen_exe():
    NODE_DIR = os.getcwd()
else:
    NODE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(NODE_DIR, "node_config.json")
LOG_DIR = os.path.join(NODE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# ═══════════════════════════════════════════
#  日志
# ═══════════════════════════════════════════

_LOG_LOCK = threading.Lock()


def log(msg, level="INFO"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] [{level}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        pass
    with _LOG_LOCK:
        with open(os.path.join(LOG_DIR, "listener.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ═══════════════════════════════════════════
#  venv 自愈
# ═══════════════════════════════════════════


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


def check_and_repair_environment():
    """检测并修复虚拟环境（exe 模式下跳过）。"""
    if _is_frozen_exe():
        log("exe 模式，跳过 venv 检测")
        return True

    venv_path = os.path.join(NODE_DIR, "venv")
    if os.name == "nt":
        python_exe = os.path.join(venv_path, "Scripts", "python.exe")
    else:
        python_exe = os.path.join(venv_path, "bin", "python")
    pyvenv_cfg = os.path.join(venv_path, "pyvenv.cfg")

    # 检测 python.exe 存在但 pyvenv.cfg 缺失
    if os.path.exists(python_exe) and not os.path.exists(pyvenv_cfg):
        log("检测到 pyvenv.cfg 缺失，自动修复...", "WARNING")
        try:
            _repair_pyvenv_cfg(venv_path)
            if os.path.exists(pyvenv_cfg):
                log("pyvenv.cfg 已重建")
                return True
        except Exception as e:
            log(f"重建 pyvenv.cfg 失败: {e}", "ERROR")

    # venv 完全损坏
    if not os.path.exists(python_exe):
        log("检测到虚拟环境异常，尝试自动重建...", "WARNING")
        if os.path.exists(venv_path):
            shutil.rmtree(venv_path, ignore_errors=True)
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(venv_path)],
                capture_output=True, text=True, timeout=120,
            )
            # 安装依赖
            req_path = os.path.join(NODE_DIR, "requirements.txt")
            if os.path.exists(req_path) and os.path.getsize(req_path) > 0:
                pip_exe = os.path.join(venv_path, "Scripts", "pip.exe") if os.name == "nt" else os.path.join(venv_path, "bin", "pip")
                subprocess.run(
                    [pip_exe, "install", "-r", req_path],
                    capture_output=True, text=True, timeout=120,
                )
            log("虚拟环境重建成功")
        except Exception as e:
            log(f"虚拟环境重建失败: {e}", "ERROR")
            return False

    return True


if not check_and_repair_environment():
    log("环境修复失败，程序退出", "ERROR")
    sys.exit(1)


# ═══════════════════════════════════════════
#  配置加载
# ═══════════════════════════════════════════

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

# 多端口输出路由
OUTPUT_PORTS = {}
for port in cfg.get("output_ports", []):
    if isinstance(port, dict) and port.get("name"):
        fpath = port.get("output_file", "")
        if fpath:
            OUTPUT_PORTS[port["name"]] = os.path.abspath(os.path.join(NODE_DIR, fpath))

# ═══════════════════════════════════════════
#  PID 文件 & 信号处理
# ═══════════════════════════════════════════

PID_FILE = os.path.join(NODE_DIR, f"{NODE_NAME}.pid")

RUNNING = True


def _cleanup():
    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
    log("监听器已退出")


def _signal_handler(signum, frame):
    global RUNNING
    log("收到退出信号，正在关闭...", "WARNING")
    RUNNING = False


atexit.register(_cleanup)
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

with open(PID_FILE, "w") as f:
    f.write(str(os.getpid()))

# ═══════════════════════════════════════════
#  多源监听
# ═══════════════════════════════════════════


def find_project_root():
    """向上查找项目根目录（包含 pipeline.json）。"""
    d = NODE_DIR
    for _ in range(5):
        if os.path.isfile(os.path.join(d, "pipeline.json")):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.dirname(NODE_DIR))


def resolve_input_sources():
    """自动解析输入源文件列表。

    优先级：
    1. listen_upper_file
    2. port_mappings 字符串值（输入端口 → 文件路径）
    3. pipeline.json edges（关联上游节点的 output_ports）
    """
    sources = []

    # 1. listen_upper_file
    if UPPER_FILE:
        sources.append(UPPER_FILE)

    # 2. port_mappings 字符串值
    for port_name, mapping in cfg.get("port_mappings", {}).items():
        if isinstance(mapping, str):
            path = mapping if os.path.isabs(mapping) else os.path.abspath(os.path.join(NODE_DIR, mapping))
            sources.append(path)

    # 3. pipeline.json edges
    project_root = find_project_root()
    pipeline_path = os.path.join(project_root, "pipeline.json")
    nodes_dir = os.path.join(project_root, "nodes")
    if os.path.exists(pipeline_path):
        with open(pipeline_path, "r", encoding="utf-8") as f:
            pipeline = json.load(f)
        for edge in pipeline.get("edges", []):
            if edge["to"] == NODE_NAME:
                src_node = edge["from"]
                src_port = edge.get("source_port", "default")
                src_cfg_path = os.path.join(nodes_dir, src_node, "node_config.json")
                if not os.path.exists(src_cfg_path):
                    continue
                with open(src_cfg_path, "r", encoding="utf-8") as f:
                    src_cfg = json.load(f)
                # 优先从 output_ports 按端口名匹配输出文件
                src_output_file = src_cfg.get("output_file", "./output.json")
                for port in src_cfg.get("output_ports", []):
                    if isinstance(port, dict) and port.get("name") == src_port and port.get("output_file"):
                        src_output_file = port["output_file"]
                        break
                src_path = os.path.abspath(os.path.join(nodes_dir, src_node, src_output_file))
                if src_path not in sources:
                    sources.append(src_path)

    # 4. 大小写规范化去重（Windows）
    seen = set()
    deduped = []
    for p in sources:
        key = os.path.normcase(p)
        if key not in seen:
            seen.add(key)
            deduped.append(p)

    return deduped


def unwrap_data(data):
    """解包包装格式：{'code': 0, 'data': {...}} → 内层 data"""
    if isinstance(data, dict) and "code" in data and "data" in data:
        inner = data["data"]
        if isinstance(inner, dict):
            return inner
    return data


def is_my_data(data):
    """注意力过滤：空 filter 放行所有；非空时满足任一端口条件即可（OR 关系）。"""
    if not MY_FILTER:
        return True
    for _port_name, criteria in MY_FILTER.items():
        if isinstance(criteria, dict) and all(data.get(k) == v for k, v in criteria.items()):
            return True
    return False


# ═══════════════════════════════════════════
#  输入源初始化
# ═══════════════════════════════════════════

INPUT_SOURCES = resolve_input_sources()
_last_mtimes = {s: 0.0 for s in INPUT_SOURCES}
_content_hashes = {}

log(f"监听器启动 [{NODE_NAME}]")
log(f"输入源 ({len(INPUT_SOURCES)} 个):")
for s in INPUT_SOURCES:
    log(f"  - {s}")
if OUTPUT_PORTS:
    log(f"输出端口 ({len(OUTPUT_PORTS)} 个):")
    for name, path in OUTPUT_PORTS.items():
        log(f"  - {name} → {path}")
log(f"顶层回退输出: {OUTPUT_FILE}")

# ═══════════════════════════════════════════
#  并发处理
# ═══════════════════════════════════════════

WRITE_LOCK = threading.Lock()
MAX_WORKERS = min(len(INPUT_SOURCES) or 1, 8)
SUBPROCESS_TIMEOUT = 180  # 子进程超时秒数


def _resolve_python():
    """解析本节点的 Python 解释器路径。"""
    if _is_frozen_exe():
        return sys.executable
    if os.name == "nt":
        py = os.path.join(NODE_DIR, "venv", "Scripts", "python.exe")
    else:
        py = os.path.join(NODE_DIR, "venv", "bin", "python")
    if os.path.exists(py):
        return py
    return sys.executable


def _process_one(src_path: str, raw_data: dict):
    """在独立线程中处理单条数据。"""
    try:
        input_data = unwrap_data(raw_data)
        log(f"开始处理 (source: {src_path})")

        python_exe = _resolve_python()
        main_path = os.path.join(NODE_DIR, "main.py")
        input_json = json.dumps(input_data, ensure_ascii=False)

        if _is_frozen_exe():
            # exe 模式：直接 import 调用
            import _bnos_main as _node_main
            _node_main.NODE_DIR = NODE_DIR
            result = _node_main.process(input_data)
            output = json.dumps({
                "code": 0,
                "data": result,
            }, ensure_ascii=False)
        else:
            res = subprocess.run(
                [python_exe, main_path, input_json],
                capture_output=True, text=True, encoding="utf-8",
                timeout=SUBPROCESS_TIMEOUT,
            )
            if res.returncode != 0:
                log(f"main.py 返回非零: {res.stderr}", "ERROR")
                return
            output = res.stdout.strip()

        if not output:
            log("返回空数据，跳过")
            return

        # 多端口路由
        try:
            output_obj = json.loads(output)
            # 从 data 中取 _port，或从顶层取 type
            data_part = output_obj.get("data", output_obj)
            if isinstance(data_part, dict):
                port_name = data_part.pop("_port", output_obj.get("type", "default"))
            else:
                port_name = output_obj.get("type", "default")
            out_path = OUTPUT_PORTS.get(port_name, OUTPUT_FILE)
        except (json.JSONDecodeError, KeyError):
            out_path = OUTPUT_FILE

        # 写输出（加锁）
        with WRITE_LOCK:
            out_dir = os.path.dirname(out_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output)
            log(f"写入 {out_path}")

        # 标记上游文件已处理（加锁）
        raw_data[PROCESS_FLAG] = True
        with WRITE_LOCK:
            with open(src_path, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, indent=2, ensure_ascii=False)
            log(f"已标记 {PROCESS_FLAG} → {src_path}")

    except subprocess.TimeoutExpired:
        log(f"处理超时 [{src_path}]: 子进程超过 {SUBPROCESS_TIMEOUT} 秒未返回", "ERROR")
    except Exception as e:
        log(f"处理异常 [{src_path}]: {e}", "ERROR")


# ═══════════════════════════════════════════
#  主循环
# ═══════════════════════════════════════════

log("=" * 50)
log(f"节点启动: {NODE_NAME}")
log(f"PID: {os.getpid()}")
log(f"线程池: {MAX_WORKERS} workers, 超时 {SUBPROCESS_TIMEOUT}s")
log("=" * 50)

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    while RUNNING:
        try:
            for src_path in INPUT_SOURCES:
                if not os.path.exists(src_path):
                    continue

                current_mtime = os.path.getmtime(src_path)
                if current_mtime <= _last_mtimes.get(src_path, 0.0):
                    continue

                try:
                    with open(src_path, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    _last_mtimes[src_path] = current_mtime
                    continue

                # 内容哈希去重（mtime 精度不够时的兜底）
                content_str = json.dumps(raw_data, ensure_ascii=False, sort_keys=True)
                content_hash = hashlib.md5(content_str.encode()).hexdigest()
                if content_hash == _content_hashes.get(src_path):
                    _last_mtimes[src_path] = current_mtime
                    continue

                _last_mtimes[src_path] = current_mtime
                _content_hashes[src_path] = content_hash

                # 注意力过滤
                if not is_my_data(raw_data):
                    continue

                # 防重复处理
                if raw_data.get(PROCESS_FLAG):
                    continue

                # 提交到线程池（不阻塞主循环）
                executor.submit(_process_one, src_path, raw_data)

        except Exception as e:
            log(f"主循环异常: {e}", "ERROR")

        time.sleep(0.1)
